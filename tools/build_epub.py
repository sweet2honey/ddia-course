#!/usr/bin/env python3
"""把本站（index + 14 课 + 术语表 + 速查 + 三个 md）构建成一个 EPUB 3 电子书。

设计目标（按优先级）：
  1. 更新内容后，阅读软件里的笔记/高亮尽量不漂移 —— 见 docs/EPUB.md。
  2. 构建可复现：同样的输入两次构建出字节相同的 EPUB。
  3. 零外部依赖（除 lxml / Pillow 做封面），不联网。

关键约束（改代码前先读）：
  * 输出文件名由 --out 决定，**跨版本必须保持不变**。KOReader 用文件名认书
    （<book>.sdr/metadata.epub.lua），改名 = 笔记失联。
  * dc:identifier 是常量（BOOK_ID），跨版本不变。Apple Books / Calibre 用它认书。
  * spine 顺序只允许在末尾追加；不要插入、不要重排、不要改文件名。
  * 每个正文块都有内容哈希 id（p-xxxxxxxx / li-xxxxxxxx ...），供重锚工具定位。
  * 章内标题 id 由章节编号决定（sec-1-2），不随正文改动变化。

用法：
    python3 tools/build_epub.py                    # -> dist/ddia-course.epub
    python3 tools/build_epub.py --out /tmp/a.epub
    python3 tools/build_epub.py --anchors dist/anchors.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree, html

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

BOOK_ID = "urn:uuid:8f2c1d64-3b7a-5c19-9a1e-d0c5b7f4e210"  # 常量：跨版本认书用
BOOK_TITLE = "数据密集型应用系统设计 · 课程"
BOOK_AUTHOR = "课程笔记（基于 Martin Kleppmann《Designing Data-Intensive Applications》第二版）"
BUILD_DATE = "2026-01-01T00:00:00Z"  # 固定值以保持可复现；不随构建时间变化

LESSONS = [
    ("0001-tradeoffs-in-data-systems", "L1 · 数据系统架构中的权衡"),
    ("0002-nonfunctional-requirements", "L2 · 定义非功能性需求"),
    ("0003-data-models-and-query-languages", "L3 · 数据模型与查询语言"),
    ("0004-storage-and-retrieval", "L4 · 存储与检索"),
    ("0005-encoding-and-evolution", "L5 · 编码与演化"),
    ("0006-replication", "L6 · 复制"),
    ("0007-sharding", "L7 · 分片"),
    ("0008-transactions", "L8 · 事务"),
    ("0009-trouble-with-distributed-systems", "L9 · 分布式系统的麻烦"),
    ("0010-consistency-and-consensus", "L10 · 一致性与共识"),
    ("0011-batch-processing", "L11 · 批处理"),
    ("0012-stream-processing", "L12 · 流处理"),
    ("0013-philosophy-of-streaming-systems", "L13 · 流式系统的哲学"),
    ("0014-doing-the-right-thing", "L14 · 做正确的事情"),
]

MD_PAGES = [
    ("MISSION.md", "appendix-mission.xhtml", "附录 A · 这份课程的目标"),
    ("RESOURCES.md", "appendix-resources.xhtml", "附录 B · 资源清单"),
    ("NOTES.md", "appendix-notes.xhtml", "附录 C · 工作区笔记"),
]
MD_TARGET = {src: out for src, out, _ in MD_PAGES}

# 正文里要清掉的交互控件（EPUB 无 JS）
# 先删这些：删了就再也拿不到内容的（脚本、表单控件本身无内容）
DROP_TAGS = {"script", "style", "input", "select", "noscript"}
# 后删这些：内容都在 data-why / 选项文本里，组件转换完再清理
LATE_DROP_TAGS = {"textarea", "button"}

# 需要挂稳定锚点的块级元素
ANCHOR_TAGS = {"p", "li", "dd", "dt", "h2", "h3", "h4", "figure", "table",
               "blockquote", "pre", "ol", "ul", "dl"}
ANCHOR_DIV_CLASSES = {"key", "anti", "diag", "excerpt", "card", "pair",
                      "triage", "quiz", "recall", "gloss", "two", "grid2", "grid3"}


# --------------------------------------------------------------------------- #
# 文本与 id
# --------------------------------------------------------------------------- #

_WS = re.compile(r"\s+")


def norm_text(el) -> str:
    return _WS.sub("", "".join(el.itertext()))


def short_hash(tag: str, text: str) -> str:
    h = hashlib.sha1(f"{tag}\x00{text}".encode("utf-8")).hexdigest()
    return h[:8]


class AnchorAllocator:
    """给块元素分配内容哈希 id；同文本重复时按文档顺序加 -2/-3。

    id 只取决于「标签名 + 规范化文本」，所以：
      * 在别处插入/删除段落，其它段落的 id 不变；
      * 改动某段文字，只有这一段的 id 变（正是我们想要的语义）。
    """

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}
        self.records: list[dict] = []

    def assign(self, el, chapter: str) -> str:
        tag = el.tag if isinstance(el.tag, str) else "div"
        prefix = {"p": "p", "li": "li", "dd": "dd", "dt": "dt",
                  "h2": "h2", "h3": "h3", "h4": "h4",
                  "figure": "fig", "table": "tbl", "blockquote": "bq",
                  "pre": "pre", "ol": "ol", "ul": "ul", "dl": "dl"}.get(tag, "b")
        base = f"{prefix}-{short_hash(tag, norm_text(el))}"
        n = self.seen.get(base, 0) + 1
        self.seen[base] = n
        aid = base if n == 1 else f"{base}-{n}"
        el.set("id", aid)
        self.records.append({
            "id": aid,
            "tag": tag,
            "chapter": chapter,
            "text": norm_text(el)[:160],
        })
        return aid


def strip_to_text(el) -> str:
    return norm_text(el)


def section_slug(el) -> str | None:
    """h2 内部有 <span class="num">1.2</span> → id 用 sec-1-2（稳定，不由正文决定）。"""
    num = el.find('.//span[@class="num"]')
    if num is None:
        return None
    raw = (num.text_content() if hasattr(num, "text_content") else norm_text(num)).strip()
    m = re.findall(r"\d+", raw)
    return "sec-" + "-".join(m) if m else None


# --------------------------------------------------------------------------- #
# 结构转换
# --------------------------------------------------------------------------- #

def rewrite_link(href: str) -> str | None:
    """把站点内相对链接改写成 EPUB 内部链接。返回 None 表示保留原样。"""
    if not href:
        return href
    if re.match(r"^(https?:|mailto:|tel:)", href):
        return href
    path, _, frag = href.partition("#")
    frag_s = f"#{frag}" if frag else ""
    if path in ("", None):
        return href
    # 术语表锚点
    if path.endswith("reference/glossary.html") or path == "glossary.html":
        return "glossary.xhtml" + frag_s
    if path.endswith("reference/cheatsheet.html") or path == "cheatsheet.html":
        return "cheatsheet.xhtml" + frag_s
    m = re.search(r"(\d{4})-[\w-]+\.html$", path)
    if m:
        return f"lesson-{m.group(1)}.xhtml" + frag_s
    if path.endswith("index.html") or path in ("../index.html", "index.html"):
        return "index.xhtml" + frag_s
    for src, out, _ in MD_PAGES:
        if path.endswith(src):
            return out
    return None  # 未知内部链接：由调用方降级为纯文本


def process_quiz(div) -> None:
    """quiz → 静态自测：选项列表 + 正确项标记 + 逐项解析。"""
    q = div.find_class("q")
    opts = [b for b in div.iter("button")]
    feedback = div.find_class("feedback")

    for el in list(div):
        div.remove(el)

    if q:
        p = etree.SubElement(div, "p")
        p.set("class", "q")
        for child in q:
            if child.tag == "span":
                span = etree.SubElement(p, "span")
                span.set("class", "tag")
                span.text = norm_text(child)
            else:
                if len(p) > 0:
                    p[-1].tail = (p[-1].tail or "") + (child.text or "")
                else:
                    p.text = (p.text or "") + (child.text or "")
                for sub in child:
                    p.append(sub)
    # 标记为可交互题的替代说明
    hint = etree.SubElement(div, "p")
    hint.set("class", "epub-hint")
    hint.text = "（电子书里没有点击判定：正确答案已用 ✓ 标出，解析在每题下方。）"

    ul = etree.SubElement(div, "ul")
    ul.set("class", "quiz-options")
    for b in opts:
        li = etree.SubElement(ul, "li")
        ok = b.get("data-ok") == "1"
        if ok:
            li.set("class", "ok")
        # 文本顺序：✓ 前缀 + 选项原文（button 的直接文本），再挂内联子元素
        li.text = ("✓ " if ok else "") + (b.text or "")
        last = None
        for child in b:
            li.append(child)
            last = child
        why = b.get("data-why")
        if why:
            ex = etree.SubElement(li, "p")
            ex.set("class", "why")
            ex.text = why
    if feedback is not None:
        pass  # 网页里的 verdict 是 JS 产物，丢弃


def process_recall(div) -> None:
    """recall → 任务说明 + 提示 + 静态参考答案。"""
    for el in list(div):
        if el.tag in ("textarea", "button"):
            div.remove(el)
        elif el.get("class") == "answer":
            el.set("class", "answer shown")
            head = etree.Element("p")
            head.set("class", "answer-head")
            head.text = "参考答案"
            div.insert(list(div).index(el), head)


def process_triage(div) -> None:
    """triage → 场景 + 选项（正确项标 ✓）+ 静态说明。"""
    for el in list(div):
        if el.get("class") == "score":
            div.remove(el)
    for row in div.find_class("row"):
        for opts in row.find_class("opts"):
            ul = etree.Element("ul")
            ul.set("class", "triage-options")
            for b in list(opts):
                li = etree.SubElement(ul, "li")
                if b.get("data-ok") == "1":
                    li.set("class", "ok")
                    li.text = "✓ " + norm_text(b)
                else:
                    li.text = "· " + norm_text(b)
                li.tail = None
            opts.getparent().replace(opts, ul)
    for note in div.find_class("note"):
        note.set("class", "note shown")
        note.tag = "p"


def process_glossary(div) -> None:
    for dt in div.iter("dt"):
        dt.tag = "dt"  # 保持；id 已在站点里存在，别覆盖
    for p in div.find_class("see"):
        pass


def strip_attrs(el) -> None:
    for node in el.iter():
        if not isinstance(node.tag, str):
            continue
        drop = [k for k in node.attrib
                if k.startswith("data-") or k in ("onclick", "style", "aria-hidden", "tabindex")]
        for k in drop:
            del node.attrib[k]


def convert_main(main, alloc: AnchorAllocator, chapter: str) -> tuple[list, list]:
    """就地改造 <main> 的子节点，返回 (新根节点列表, 链接清单)。"""
    links: list[dict] = []

    # 1. 去掉 script / 交互控件包装
    for tag in DROP_TAGS:
        for el in main.findall(f".//{tag}"):
            el.getparent().remove(el)

    # 2. 组件级改造
    for div in list(main.iter("div")):
        cls = div.get("class") or ""
        cls_set = set(cls.split())
        if "quiz" in cls_set:
            process_quiz(div)
        elif "recall" in cls_set:
            process_recall(div)
        elif "triage" in cls_set:
            process_triage(div)
        elif "gloss" in cls_set:
            process_glossary(div)

    # 2b. 残余的表单控件（不属于任何交互组件的）
    for tag in LATE_DROP_TAGS:
        for el in main.findall(f".//{tag}"):
            el.getparent().remove(el)

    # 3. 脚注区：把 nav-links 变成「上一课/下一课」段
    for foot in main.find_class("foot"):
        for nav in foot.find_class("nav-links"):
            nav.set("class", "nav-links epub-nav")

    # 4. 链接改写
    for a in main.iter("a"):
        href = a.get("href")
        new = rewrite_link(href or "")
        if new is None:
            # 未知内部链接：保留文字，去掉链接
            a.tag = "span"
            if "href" in a.attrib:
                del a.attrib["href"]
            links.append({"href": href, "status": "unlinked"})
            continue
        if new != href:
            a.set("href", new)
        links.append({"href": new, "status": "ok",
                      "external": bool(re.match(r"^(https?:|mailto:)", new))})

    # 5. 图片
    for img in main.iter("img"):
        src = img.get("src") or ""
        name = Path(src).name
        img.set("src", f"images/{name}")
        if not img.get("alt"):
            img.set("alt", "")

    # 6. 标题 id（章内小节用编号，稳定）
    for h2 in main.iter("h2"):
        slug = section_slug(h2)
        if slug:
            h2.set("id", slug)

    # 7. 剥掉 data-* 等属性
    strip_attrs(main)

    # 8. 稳定块锚点（跳过已经有 id 的元素，比如术语表 dt）
    for el in main.iter():
        if not isinstance(el.tag, str):
            continue
        if el.get("id"):
            continue
        if el.tag in ANCHOR_TAGS:
            alloc.assign(el, chapter)
        elif el.tag == "div" and ANCHOR_DIV_CLASSES & set((el.get("class") or "").split()):
            alloc.assign(el, chapter)

    return list(main), links


# --------------------------------------------------------------------------- #
# 页面拼装
# --------------------------------------------------------------------------- #

XHTML_HEAD = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN" xml:lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="{bodyclass}">
{body}
</body>
</html>
"""


def serialize_nodes(nodes) -> str:
    out = []
    for n in nodes:
        out.append(etree.tostring(n, method="xml", encoding="unicode"))
    return "".join(out)


def build_xhtml(title: str, nodes, bodyclass: str = "") -> str:
    body = serialize_nodes(nodes)
    return XHTML_HEAD.format(title=title, body=body, bodyclass=bodyclass)


def load_main(path: Path):
    doc = html.parse(str(path))
    main = doc.find('.//main')
    if main is None:
        raise SystemExit(f"{path}: 找不到 <main>")
    return doc, main


def page_title(doc, fallback: str) -> str:
    t = doc.find(".//title")
    if t is not None and t.text:
        return t.text.split(" — ")[0].strip()
    return fallback


# --------------------------------------------------------------------------- #
# Markdown（三个附录用的极简子集）
# --------------------------------------------------------------------------- #

def inline_md(text: str):
    """返回 lxml 元素列表：支持 **bold**、`code`、[text](url)、<url>。"""
    frag = etree.Element("span")
    pattern = re.compile(
        r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|<https?://[^>]+>)")
    pos = 0
    last = None
    for m in pattern.finditer(text):
        if m.start() > pos:
            t = text[pos:m.start()]
            if last is None:
                frag.text = (frag.text or "") + t
            else:
                last.tail = (last.tail or "") + t
        tok = m.group(1)
        if tok.startswith("**"):
            el = etree.SubElement(frag, "strong")
            el.text = tok[2:-2]
        elif tok.startswith("`"):
            el = etree.SubElement(frag, "code")
            el.text = tok[1:-1]
        elif tok.startswith("["):
            mm = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok)
            el = etree.SubElement(frag, "a")
            el.set("href", rewrite_link(mm.group(2)) or mm.group(2))
            el.text = mm.group(1)
        else:
            el = etree.SubElement(frag, "a")
            el.set("href", tok[1:-1])
            el.text = tok[1:-1]
        last = el
        pos = m.end()
    if pos < len(text):
        t = text[pos:]
        if last is None:
            frag.text = (frag.text or "") + t
        else:
            last.tail = (last.tail or "") + t
    return frag


def md_to_nodes(md: str, alloc: AnchorAllocator, chapter: str):
    nodes = []
    cur_list = None
    cur_kind = None
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            cur_list = None
            cur_kind = None
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            lvl = len(m.group(1))
            tag = "h2" if lvl <= 2 else ("h3" if lvl == 3 else "h4")
            el = etree.SubElement(etree.Element("tmp"), tag)
            frag = inline_md(m.group(2).strip())
            for k, v in frag.attrib.items():
                el.set(k, v)
            el.text = frag.text
            for child in list(frag):
                el.append(child)
            if tag == "h2":
                el.set("id", "apx-" + short_hash("h2", norm_text(el)))
            nodes.append(el)
            cur_list = None
            continue
        m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if m:
            kind = "ol" if re.match(r"\d", m.group(2)) else "ul"
            if cur_list is None or cur_kind != kind:
                cur_list = etree.Element(kind)
                cur_kind = kind
                nodes.append(cur_list)
            li = etree.SubElement(cur_list, "li")
            frag = inline_md(m.group(3).strip())
            li.text = frag.text
            for child in list(frag):
                li.append(child)
            continue
        el = etree.Element("p")
        frag = inline_md(line.strip())
        el.text = frag.text
        for child in list(frag):
            el.append(child)
        nodes.append(el)
        cur_list = None
    for el in nodes:
        alloc.assign(el, chapter) if el.tag in ANCHOR_TAGS else None
    return nodes


# --------------------------------------------------------------------------- #
# 封面
# --------------------------------------------------------------------------- #

def make_cover(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 1800
    img = Image.new("RGB", (W, H), "#fbf9f4")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 24], fill="#3d4d7a")
    serif = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
    sans = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    f_big = ImageFont.truetype(serif, 104, index=0)
    f_mid = ImageFont.truetype(sans, 44, index=0)
    f_small = ImageFont.truetype(sans, 30, index=0)

    lines = ["数据密集型", "应用系统设计"]
    y = 380
    for ln in lines:
        d.text(((W - d.textlength(ln, font=f_big)) / 2, y), ln, font=f_big, fill="#1c1a17")
        y += 150
    d.text((120, y + 120), "DDIA 第二版 · 14 章课程笔记", font=f_mid, fill="#3d4d7a")
    d.line([120, y + 200, W - 120, y + 200], fill="#ded6c8", width=3)
    sub = ["权衡 · 复制 · 分片 · 事务 · 一致性",
           "批处理 · 流处理 · 做正确的事情"]
    yy = y + 250
    for s in sub:
        d.text((120, yy), s, font=f_small, fill="#5c5850")
        yy += 52
    d.text((120, H - 160), "本电子书与同名网页内容一致；结构与段落锚点稳定，可安全更新。",
           font=f_small, fill="#8a8478")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


# --------------------------------------------------------------------------- #
# CSS（EPUB 版：单列、相对单位、不依赖 JS 与 :target）
# --------------------------------------------------------------------------- #

EPUB_CSS = """@charset "utf-8";
body { margin: 0 1.1em; line-height: 1.75; color: #1c1a17; background: #fbf9f4;
  font-family: "Noto Serif CJK SC", "Source Han Serif SC", serif; text-align: justify; }
h1 { font-size: 1.65em; line-height: 1.35; margin: 1.2em 0 0.6em; font-weight: 700; }
h2 { font-size: 1.28em; line-height: 1.4; margin: 1.8em 0 0.7em; padding-bottom: 0.25em;
  border-bottom: 1px solid #ded6c8; font-weight: 700; }
h3 { font-size: 1.08em; margin: 1.3em 0 0.5em; font-weight: 700; }
h4 { font-size: 0.92em; margin: 1.1em 0 0.4em; letter-spacing: 0.04em;
  color: #6b6459; font-family: "Noto Sans CJK SC", sans-serif; font-weight: 600; }
p { margin: 0.75em 0; }
a { color: #3d4d7a; text-decoration: none; border-bottom: 1px solid #c9c2b4; }
code { font-family: "Noto Sans Mono CJK SC", monospace; font-size: 0.88em;
  background: #f1ece0; padding: 0.05em 0.25em; border-radius: 2px; }
pre { font-family: "Noto Sans Mono CJK SC", monospace; font-size: 0.82em;
  background: #f7f3e9; border-left: 3px solid #ded6c8; padding: 0.7em 0.9em;
  overflow-x: auto; white-space: pre-wrap; }
blockquote { margin: 1em 0; padding: 0.2em 0 0.2em 1em; border-left: 2px solid #3d4d7a;
  color: #3a352e; }
blockquote cite { display: block; margin-top: 0.4em; font-size: 0.82em; color: #8a8478;
  font-style: normal; }
ul, ol { margin: 0.7em 0; padding-left: 1.4em; }
li { margin: 0.35em 0; }
hr { border: 0; border-top: 1px solid #ded6c8; margin: 1.6em 0; }
table { width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 0.86em; }
th, td { border: 1px solid #ded6c8; padding: 0.35em 0.5em; text-align: left;
  vertical-align: top; }
th { background: #f1ece0; font-weight: 700; }
figure { margin: 1.2em 0; text-align: center; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: 0.82em; color: #6b6459; text-align: left; margin-top: 0.5em;
  line-height: 1.55; }
img { max-width: 100%; height: auto; }
sup { font-size: 0.7em; vertical-align: super; }

.crumb { font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.8em; color: #8a8478;
  margin-top: 1em; }
.standfirst { font-size: 1.02em; color: #3a352e; margin: 0.8em 0 1.4em; }
.lead-in { font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.8em; color: #3d4d7a;
  letter-spacing: 0.03em; margin: 0.9em 0 0.4em; }
.num { display: inline-block; margin-right: 0.45em; color: #8a8478; font-weight: 400;
  font-size: 0.82em; font-family: "Noto Sans CJK SC", sans-serif; }
.key { margin: 1.3em 0; padding: 0.7em 0.9em; border-left: 3px solid #3d4d7a;
  background: #ffffff; border-radius: 3px; font-size: 0.96em; }
.diag { margin: 1.1em 0; padding: 0.7em 0.9em; background: #f1ece0; border-radius: 3px;
  font-size: 0.94em; }
.card { margin: 1em 0; padding: 0.85em 1em; border: 1px solid #ded6c8; background: #ffffff;
  border-radius: 4px; }
.card h4 { margin-top: 0; }
.grid2, .grid3, .two, .pair { display: block; }
.grid2 > div, .grid3 > div, .two > div, .pair > div { margin: 0.85em 0;
  padding: 0.7em 0.9em; background: #ffffff; border: 1px solid #ded6c8; border-radius: 4px; }
.pair > div > b { display: block; margin-bottom: 0.35em; color: #3d4d7a;
  font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.86em; }
.excerpt { margin: 1.2em 0; padding: 0.6em 0.9em; border-left: 3px solid #ded6c8;
  background: #f7f3e9; }
.src { display: block; font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.76em;
  color: #8a8478; margin-bottom: 0.35em; }
.anti { margin: 1.2em 0; padding: 0.6em 0.9em; border: 1px dashed #b9a48a; border-radius: 4px; }
.anti h4 { margin-top: 0; color: #8a5a3a; }
.term { display: inline; font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.76em;
  color: #6b6459; background: #f1ece0; padding: 0.05em 0.3em; border-radius: 2px;
  white-space: nowrap; }
.gref { border-bottom: 1px dotted #3d4d7a; }
.gloss { margin: 1em 0 1.6em; }
.gloss dl { margin: 0; }
.gloss dt { font-family: "Noto Sans CJK SC", sans-serif; font-weight: 700; font-size: 1em;
  margin-top: 1.1em; padding-top: 0.6em; border-top: 1px solid #ded6c8; }
.gloss .en { font-family: "Noto Sans Mono CJK SC", monospace; font-size: 0.74em;
  color: #8a8478; font-weight: 400; margin-left: 0.5em; }
.gloss dd { margin: 0.35em 0 0 0; }
.gloss .avoid { font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.8em;
  color: #8a5a3a; }
.gloss .see { font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.8em;
  color: #8a8478; }
.sheet h2 { border-bottom: 2px solid #3d4d7a; }
.sheet table { font-size: 0.8em; }

/* 交互组件在 EPUB 里的静态形态 */
.quiz { margin: 1.3em 0; padding: 0.8em 1em; border: 1px solid #ded6c8; background: #ffffff;
  border-radius: 4px; }
.quiz .q { font-weight: 700; }
.tag { font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.72em; color: #ffffff;
  background: #3d4d7a; padding: 0.1em 0.4em; border-radius: 2px; margin-right: 0.4em; }
.epub-hint { font-size: 0.78em; color: #8a8478; margin: 0.3em 0 0.6em; }
ul.quiz-options { list-style: none; padding-left: 0; }
ul.quiz-options > li { margin: 0.5em 0; padding-left: 1.1em; text-indent: -1.1em; }
ul.quiz-options > li.ok { background: #eef3e9; border-radius: 3px; padding: 0.3em 0.6em;
  text-indent: 0; }
p.why { font-size: 0.82em; color: #6b6459; margin: 0.25em 0 0.5em; }
.recall { margin: 1.3em 0; padding: 0.8em 1em; border: 1px dashed #c9c2b4; border-radius: 4px; }
.hint-inline { font-size: 0.84em; color: #6b6459; }
.answer { margin-top: 0.9em; padding: 0.7em 0.9em; background: #f7f3e9; border-radius: 3px;
  display: block; }
.answer-head { font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.78em;
  color: #3d4d7a; letter-spacing: 0.06em; margin: 0 0 0.4em; }
.triage { margin: 1.3em 0; }
.triage .row { margin: 1em 0; padding: 0.7em 0.9em; border: 1px solid #ded6c8;
  border-radius: 4px; background: #ffffff; }
ul.triage-options { list-style: none; padding-left: 0; margin: 0.4em 0; }
ul.triage-options > li { font-size: 0.9em; }
ul.triage-options > li.ok { color: #3f6b3a; font-weight: 600; }
.note { font-size: 0.82em; color: #6b6459; margin: 0.4em 0 0; display: block; }
.foot { margin-top: 2.2em; padding-top: 1em; border-top: 1px solid #ded6c8; font-size: 0.92em; }
.ask { font-style: italic; color: #3a352e; }
.epub-nav { margin-top: 1.4em; font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.86em; }
.epub-nav span { display: block; margin: 0.4em 0; }

/* 目录页 / 封面页 */
.cover-page { margin: 0; padding: 0; text-align: center; }
.cover-page img { max-width: 100%; max-height: 100%; }
.toc-list { list-style: none; padding-left: 0; }
.toc-list > li { margin: 0.45em 0; }
.toc-list > li > ul { list-style: none; padding-left: 1.2em; font-size: 0.88em; }
.toc-list .part { font-family: "Noto Sans CJK SC", sans-serif; font-size: 0.78em;
  color: #8a8478; letter-spacing: 0.06em; margin-top: 1.4em; }
"""


# --------------------------------------------------------------------------- #
# 构建
# --------------------------------------------------------------------------- #

def container_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def build(out: Path, anchors_path: Path | None) -> None:
    alloc = AnchorAllocator()
    files: dict[str, bytes] = {}
    spine: list[tuple[str, str]] = []  # (id, href)
    nav_items: list[tuple[str, str, list[tuple[str, str]]]] = []

    # ---- 封面 ----
    cover_png = ROOT / ".build" / "cover.png"
    make_cover(cover_png)
    files["OEBPS/images/cover.png"] = cover_png.read_bytes()
    cover_nodes = [etree.fromstring(
        '<div class="cover-page"><img src="images/cover.png" alt="封面"/></div>')]
    files["OEBPS/cover.xhtml"] = build_xhtml("封面", cover_nodes).encode()
    spine.append(("cover", "cover.xhtml"))

    # ---- 首页 ----
    cover_doc, main = load_main(ROOT / "index.html")
    nodes, _ = convert_main(main, alloc, "index")
    files["OEBPS/index.xhtml"] = build_xhtml("课程首页", nodes).encode()
    spine.append(("index", "index.xhtml"))
    nav_items.append(("课程首页", "index.xhtml", []))

    # ---- 14 课 ----
    for slug, label in LESSONS:
        path = ROOT / "lessons" / f"{slug}.html"
        doc, main = load_main(path)
        chap = f"lesson-{slug[:4]}"
        nodes, _ = convert_main(main, alloc, chap)
        href = f"lesson-{slug[:4]}.xhtml"
        files[f"OEBPS/{href}"] = build_xhtml(label, nodes).encode()
        spine.append((f"lesson-{slug[:4]}", href))
        subs = []
        for n in nodes:
            if isinstance(n.tag, str) and n.tag == "h2" and n.get("id"):
                subs.append((norm_text(n), f"{href}#{n.get('id')}"))
        nav_items.append((label, href, subs))
        print(f"  {slug}: {len(nodes)} 个顶层块, {len(subs)} 个小节")

    # ---- 术语表 ----
    doc, main = load_main(ROOT / "reference" / "glossary.html")
    nodes, _ = convert_main(main, alloc, "glossary")
    files["OEBPS/glossary.xhtml"] = build_xhtml("术语表", nodes).encode()
    spine.append(("glossary", "glossary.xhtml"))
    subs = [(norm_text(n), f"glossary.xhtml#{n.get('id')}")
            for n in nodes if isinstance(n.tag, str) and n.tag == "h2" and n.get("id")]
    nav_items.append(("术语表", "glossary.xhtml", subs))

    # ---- 速查 ----
    doc, main = load_main(ROOT / "reference" / "cheatsheet.html")
    nodes, _ = convert_main(main, alloc, "cheatsheet")
    files["OEBPS/cheatsheet.xhtml"] = build_xhtml("全书速查", nodes).encode()
    spine.append(("cheatsheet", "cheatsheet.xhtml"))
    subs = [(norm_text(n), f"cheatsheet.xhtml#{n.get('id')}")
            for n in nodes if isinstance(n.tag, str) and n.tag == "h2" and n.get("id")]
    nav_items.append(("全书速查", "cheatsheet.xhtml", subs))

    # ---- 附录（三个 md）----
    for src, outname, label in MD_PAGES:
        md = (ROOT / src).read_text(encoding="utf-8")
        nodes = md_to_nodes(md, alloc, outname.split(".")[0])
        href = outname
        files[f"OEBPS/{href}"] = build_xhtml(label, nodes).encode()
        spine.append((outname.split(".")[0], href))
        subs = [(norm_text(n), f"{href}#{n.get('id')}")
                for n in nodes if isinstance(n.tag, str) and n.tag == "h2" and n.get("id")]
        nav_items.append((label, href, subs))

    # ---- 图片 ----
    used = set()
    for name, data in list(files.items()):
        for m in re.finditer(rb'src="images/([^"]+)"', data):
            used.add(m.group(1).decode())
    total = 0
    used.discard("cover.png")  # 封面由 make_cover 生成，不在 assets/fig
    for name in sorted(used):
        p = ROOT / "assets" / "fig" / name
        if not p.exists():
            print(f"  !! 缺图 {name}", file=sys.stderr)
            continue
        b = p.read_bytes()
        total += len(b)
        files[f"OEBPS/images/{name}"] = b
    print(f"  图片 {len(used)} 张, {total/1024/1024:.1f} MB")

    # ---- 目录页 ----
    nav_parts = ['<nav epub:type="toc" id="toc"><h1>目录</h1><ol class="toc-list">']
    for title, href, subs in nav_items:
        nav_parts.append(f'<li><a href="{href}">{esc(title)}</a>')
        if subs:
            nav_parts.append("<ol>")
            for st, sh in subs:
                nav_parts.append(f'<li><a href="{sh}">{esc(st)}</a></li>')
            nav_parts.append("</ol>")
        nav_parts.append("</li>")
    nav_parts.append("</ol></nav>")
    nav_parts.append('<nav epub:type="landmarks" id="landmarks" hidden="hidden"><ol>'
                     '<li><a epub:type="cover" href="cover.xhtml">封面</a></li>'
                     '<li><a epub:type="toc" href="index.xhtml">目录</a></li>'
                     '<li><a epub:type="bodymatter" href="index.xhtml">开始阅读</a></li>'
                     "</ol></nav>")
    nav_doc = XHTML_HEAD.format(title="目录", body="\n".join(nav_parts), bodyclass="nav")
    files["OEBPS/nav.xhtml"] = nav_doc.encode()

    # ---- NCX（EPUB2 兼容，KOReader/老设备用）----
    ncx_points = []
    for i, (title, href, _subs) in enumerate(nav_items, 1):
        ncx_points.append(
            f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{esc(title)}</text>'
            f'</navLabel><content src="{href}"/></navPoint>')
    files["OEBPS/toc.ncx"] = f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="{BOOK_ID}"/><meta name="dtb:depth" content="1"/>
<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>
<docTitle><text>{esc(BOOK_TITLE)}</text></docTitle>
<navMap>{''.join(ncx_points)}</navMap>
</ncx>
""".encode()

    # ---- CSS ----
    files["OEBPS/style.css"] = EPUB_CSS.encode()

    # ---- OPF ----
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
        '<item id="cover-image" href="images/cover.png" media-type="image/png" properties="cover-image"/>',
    ]
    for iid, href in spine:
        manifest.append(f'<item id="{iid}" href="{href}" media-type="application/xhtml+xml"/>')
    for name in sorted(used):
        if name == "cover.png":
            continue
        manifest.append(f'<item id="img-{name[:-4]}" href="images/{name}" media-type="image/png"/>')
    spine_xml = "".join(f'<itemref idref="{iid}"/>' for iid, _ in spine)

    # 手写 meta（不用 lxml，保证字节可复现）
    files["OEBPS/content.opf"] = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="zh-CN">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="bookid">{BOOK_ID}</dc:identifier>
<dc:title>{esc(BOOK_TITLE)}</dc:title>
<dc:language>zh-CN</dc:language>
<dc:creator>{esc(BOOK_AUTHOR)}</dc:creator>
<dc:publisher>本地生成</dc:publisher>
<dc:description>14 章 DDIA 第二版课程笔记，含术语表、速查表与自测。</dc:description>
<dc:subject>分布式系统</dc:subject>
<dc:subject>数据密集型应用</dc:subject>
<meta property="dcterms:modified">{BUILD_DATE}</meta>
<meta name="cover" content="cover-image"/>
</metadata>
<manifest>
{chr(10).join(manifest)}
</manifest>
<spine toc="ncx">
{spine_xml}
</spine>
<guide><reference type="cover" title="封面" href="cover.xhtml"/></guide>
</package>
""".encode()

    files["META-INF/container.xml"] = container_xml().encode()

    # ---- 打包（确定性 zip）----
    out.parent.mkdir(parents=True, exist_ok=True)
    order = ["mimetype", "META-INF/container.xml", "OEBPS/content.opf",
             "OEBPS/nav.xhtml", "OEBPS/toc.ncx", "OEBPS/style.css"]
    rest = sorted(k for k in files if k not in order)
    with zipfile.ZipFile(out, "w") as z:
        def add(name: str, data: bytes, compress: bool) -> None:
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
            zi.external_attr = 0o644 << 16
            zi.create_system = 3
            z.writestr(zi, data)

        add("mimetype", b"application/epub+zip", False)
        for name in order[1:]:
            add(name, files[name], True)
        for name in rest:
            add(name, files[name], True)

    if anchors_path:
        anchors_path.parent.mkdir(parents=True, exist_ok=True)
        anchors_path.write_text(json.dumps({
            "book_id": BOOK_ID,
            "book_title": BOOK_TITLE,
            "spine": [{"id": i, "href": h} for i, h in spine],
            "blocks": alloc.records,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  锚点清单 -> {anchors_path} ({len(alloc.records)} 块)")

    size = out.stat().st_size
    sha = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
    print(f"完成: {out}  {size/1024/1024:.1f} MB  sha256[:16]={sha}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DIST / "ddia-course.epub")
    ap.add_argument("--anchors", type=Path, default=DIST / "anchors.json")
    ap.add_argument("--root", type=Path, default=None,
                    help="站点根目录（默认本仓库）；用于在新旧快照上各构建一版做漂移实验")
    a = ap.parse_args()
    if a.root is not None:
        globals()["ROOT"] = a.root.resolve()
        print(f"站点根: {ROOT}")
    print(f"构建 {a.out}")
    build(a.out, a.anchors)


if __name__ == "__main__":
    main()
