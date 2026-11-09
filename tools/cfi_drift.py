#!/usr/bin/env python3
"""测量「内容更新后，按 CFI 存放的笔记会漂移到哪」。

做法：不是讲故事，是拿真的 EPUB 做实验。
  1. 从 v1.epub 取一批标注锚点（每段正文取中间位置），生成 CFI。
  2. 在 v2.epub 里按同一套规则解析这些 CFI。
  3. 比对「解析出来的文字」和「当初选中的文字」，分四类计数：
        exact   位置和文字都对
        moved   文字对，但落在了别的块（同一章内位移）
        lost    CFI 解析失败 / 落到空处
        wrong  解析成功但文字对不上（静默漂移，最危险）

CFI 规则（最小可用实现，足够复现问题）：
    /6/N[itemref]!  → spine 第 (N/2-1) 项的 XHTML 根
    /4             → body（html 的第 2 个元素子节点：head=/2, body=/4）
    /2k             → body 下第 k 个元素子节点
    /M:O            → 该元素内文本的第 O 个 UTF-16 code unit

用法：
    python3 tools/cfi_drift.py --v1 .build/exp/v1.epub --v2 .build/exp/v2.epub
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

NS = {"x": "http://www.w3.org/1999/xhtml"}


# --------------------------------------------------------------------------- #
# 读 EPUB
# --------------------------------------------------------------------------- #

@dataclass
class Book:
    path: Path
    zip: zipfile.ZipFile
    opf_dir: str
    spine: list[str]        # href（相对 opf 目录）
    spine_ids: list[str]
    docs: dict[str, etree._Element]

    @classmethod
    def open(cls, path: Path) -> "Book":
        z = zipfile.ZipFile(path)
        opf_name = None
        c = etree.fromstring(z.read("META-INF/container.xml"))
        for rf in c.iter():
            if rf.tag.endswith("rootfile"):
                opf_name = rf.get("full-path")
        opf_dir = str(Path(opf_name).parent)
        opf = etree.fromstring(z.read(opf_name))
        manifest = {}
        for item in opf.iter():
            if item.tag.endswith("item"):
                manifest[item.get("id")] = item.get("href")
        spine, spine_ids = [], []
        for ref in opf.iter():
            if ref.tag.endswith("itemref"):
                iid = ref.get("idref")
                spine_ids.append(iid)
                spine.append(manifest[iid])
        docs = {}
        for href in spine:
            full = f"{opf_dir}/{href}" if opf_dir else href
            docs[href] = etree.fromstring(z.read(full))
        return cls(path, z, opf_dir, spine, spine_ids, docs)


def elem_children(el) -> list:
    return [c for c in el if isinstance(c.tag, str)]


def text_nodes(el) -> list:
    """按文档顺序返回 (node, start, end) —— node 是 text/tail 的宿主元素 + 角色。"""
    out = []

    def walk(node):
        if not isinstance(node.tag, str):
            return
        if node.text:
            out.append((node, "text", node.text))
        for c in node:
            walk(c)
            if c.tail:
                out.append((c, "tail", c.tail))

    walk(el)
    return out


def full_text(el) -> str:
    return "".join(t[2] for t in text_nodes(el))


def utf16_units(s: str) -> int:
    """CFI 偏移按 UTF-16 code unit 计。"""
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in s)


def elem_path(root, target) -> list[int]:
    """从 root 到 target（含）的元素子节点索引路径，1-based。"""
    path = []
    node = target
    while node is not None and node is not root:
        parent = node.getparent()
        if parent is None:
            break
        idx = elem_children(parent).index(node)
        path.append(idx + 1)
        node = parent
    return list(reversed(path))


# --------------------------------------------------------------------------- #
# CFI 生成 / 解析
# --------------------------------------------------------------------------- #

def make_cfi(book: Book, href: str, el, char_offset: int) -> str:
    si = book.spine.index(href)
    path = elem_path(book.docs[href], el)
    # 末端步与字符偏移共用一个段：/2k:off —— 这样解析时不会多走一层
    parts = [f"/6/{2 * (si + 1)}[{book.spine_ids[si]}]", "!"]
    parts.append("".join(f"/{2 * p}" for p in path[:-1]))
    # CFI 里的偏移按 UTF-16 code unit 计，入参是按 Python 字符计的
    t = full_text(el)[:char_offset]
    parts.append(f"/{2 * path[-1]}:{utf16_units(t)}")
    return "epubcfi(" + "".join(parts) + ")"


_CFI = re.compile(r"^epubcfi\((.*)\)$")


def parse_cfi(cfi: str):
    m = _CFI.match(cfi)
    if not m:
        raise ValueError("not a CFI")
    body = m.group(1)
    spine_part, _, doc_part = body.partition("!")
    segs = re.findall(r"/\d+(?:\[[^\]]*\])?(?::\d+)?", doc_part)
    # 首个段是 /4 = body，它也是元素路径的第一跳，所以一起进 path
    if not segs or not segs[0].startswith("/4"):
        raise ValueError("no body")
    path = []
    off = None
    for s in segs:
        num_s, has_off, off_s = s.partition(":")
        n = int(num_s.split("!")[0][1:].split("[")[0])
        path.append(n)
        if has_off:
            off = int(off_s)
    sp = re.findall(r"/6/(\d+)", spine_part)
    si = (int(sp[0]) // 2) - 1 if sp else 0
    return si, path, off


def resolve_cfi(book: Book, cfi: str):
    si, path, off = parse_cfi(cfi)
    href = book.spine[si]
    el = book.docs[href]
    for n in path:
        kids = elem_children(el)
        i = n // 2 - 1
        if i < 0 or i >= len(kids):
            raise KeyError(f"path segment /{n} out of range")
        el = kids[i]
    if off is None:
        return href, el, 0
    # 把 UTF-16 偏移换回「相对整个元素文本的 Python 字符偏移」
    nodes = text_nodes(el)
    acc_units = 0
    acc_chars = 0
    for host, role, txt in nodes:
        n_units = utf16_units(txt)
        if acc_units + n_units >= off:
            # 落在这个文本节点内：再按字符逐个累加，处理 astral 字符
            want = off - acc_units
            got = 0
            for i, ch in enumerate(txt):
                if got >= want:
                    return href, el, acc_chars + i
                got += 2 if ord(ch) > 0xFFFF else 1
            return href, el, acc_chars + len(txt)
        acc_units += n_units
        acc_chars += len(txt)
    return href, el, len(full_text(el))


# --------------------------------------------------------------------------- #
# 实验
# --------------------------------------------------------------------------- #

def snippet(s: str, n: int = 24) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n]


def experiment(v1: Path, v2: Path, sample_every: int, take: int):
    b1, b2 = Book.open(v1), Book.open(v2)
    rows = []
    for href in b1.spine:
        if not href.startswith("lesson-"):
            continue
        root = b1.docs[href]
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if etree.QName(el).localname != "p":
                continue
            txt = full_text(el)
            if len(txt) < 40:
                continue
            off_c = len(txt) // 2
            # 选一个字符偏移，取它后面 24 字作为"用户选中的文字"
            sel = txt[off_c:off_c + 40]
            if not sel.strip():
                continue
            cfi = make_cfi(b1, href, el, off_c)
            rows.append({"href": href, "cfi": cfi, "orig": sel, "orig_para": txt})
            if len(rows) >= take:
                break
        if len(rows) >= take:
            break

    out = []
    for r in rows:
        try:
            href2, el2, off2 = resolve_cfi(b2, r["cfi"])
        except Exception as e:  # noqa: BLE001
            out.append(("lost", r, f"{type(e).__name__}: {e}"))
            continue
        txt2 = full_text(el2)
        got = txt2[off2:off2 + 40]
        if got == r["orig"]:
            status = "exact"
        elif r["orig"] in txt2:
            status = "moved"   # 还是同一块，只是偏移变了
        elif snippet(got) and snippet(got) == snippet(r["orig"]):
            status = "moved"
        elif not got.strip():
            status = "lost"
        else:
            # 找到相同文字在章内其它块？还是彻底对不上
            status = "wrong"
        out.append((status, r, {"got": got, "off": off2, "para": txt2}))

    return b1, b2, out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1", type=Path, required=True)
    ap.add_argument("--v2", type=Path, required=True)
    ap.add_argument("--take", type=int, default=400)
    ap.add_argument("--report", type=Path, default=None)
    a = ap.parse_args()

    b1, b2, out = experiment(a.v1, a.v2, 1, a.take)
    from collections import Counter
    c = Counter(s for s, _, _ in out)
    total = sum(c.values())
    print(f"样本 {total} 条（每章前若干 p 的中点位置）")
    for k in ("exact", "moved", "wrong", "lost"):
        if c[k]:
            print(f"  {k:6s} {c[k]:4d}  {c[k]/total*100:5.1f}%")
    print()
    for status, r, extra in out:
        if status != "exact":
            print(f"[{status}] {r['href']}  off={extra.get('off') if isinstance(extra, dict) else extra}")
            print(f"   原文: {r['orig'][:40]!r}")
            if isinstance(extra, dict):
                print(f"   现文: {extra['got'][:40]!r}")
    if a.report:
        a.report.write_text(json.dumps(
            [{"status": s, **r, "extra": e} for s, r, e in out],
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n明细 -> {a.report}")


if __name__ == "__main__":
    main()
