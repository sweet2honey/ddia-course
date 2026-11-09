#!/usr/bin/env python3
"""把旧版 EPUB 上的笔记迁移到新版 EPUB —— 用「稳定块锚点 + 文字指纹」重新定位。

为什么需要它：阅读器存的是 CFI（指向 spine 第几个文件、文档树第几个节点、第几个字符）。
段落一插一删，数字全变；CFI 要么解析失败（笔记消失），要么解析成功但指到别的段落
（高亮静默漂移 —— 比丢更糟，因为你不看就发现不了）。

迁移分三级，逐级降级：
  1. 快路径：旧 CFI 在新书里还能解析，且解析出来的文字和笔记原文对得上 → 直接用。
  2. 锚点路径：用 anchors.json 找出「这个 CFI 属于哪个块 id」，在新书的 anchors.json 里
     找同一个 id（id 由块文本哈希而来，别处增删不影响它），用它在新书里定位新 CFI。
  3. 文字路径：锚点 id 变了（说明这段本身被改写），在旧块所在章里按文字相似度找最像的块。

输出：迁移后的 CFI 列表 + 每条的判定（kept / remapped / fuzzy / dropped）+ 报告。

用法：
    python3 tools/migrate_notes.py \\
        --old-epub .build/exp/v1.epub --old-anchors .build/exp/anchors-v1.json \\
        --new-epub .build/exp/v2.epub --new-anchors .build/exp/anchors-v2.json \\
        --notes .build/exp/notes-v1.json --out .build/exp/notes-v2.json
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cfi_drift import (  # noqa: E402
    Book,
    elem_path,
    full_text,
    resolve_cfi,
    utf16_units,
)

def norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


# --------------------------------------------------------------------------- #
# 反向查：某个 CFI 落在哪个块上
# --------------------------------------------------------------------------- #

def block_of(book: Book, anchors: dict, cfi: str):
    """CFI → (块 id, 块文字, 章 href)。找不到返回 None。"""
    href, el, off = resolve_cfi(book, cfi)
    # 往上找最近一个在 anchors 里登记过 id 的元素
    node = el
    ids = {b["id"]: b for b in anchors["blocks"]}
    while node is not None:
        bid = node.get("id")
        if bid and bid in ids:
            return bid, full_text(node), href
        node = node.getparent()
    return None


def find_element_by_id(book: Book, target_id: str):
    """在整本书里按 id 找元素，返回 (href, el)。"""
    for href in book.spine:
        root = book.docs[href]
        for el in root.iter():
            if isinstance(el.tag, str) and el.get("id") == target_id:
                return href, el
    return None, None


def cfi_for_offset(book: Book, href: str, el, char_offset: int) -> str:
    si = book.spine.index(href)
    path = elem_path(book.docs[href], el)
    t = full_text(el)[:char_offset]
    body = "".join(f"/{2 * p}" for p in path[:-1])
    return (f"epubcfi(/6/{2 * (si + 1)}[{book.spine_ids[si]}]!"
            f"{body}/{2 * path[-1]}:{utf16_units(t)})")


# --------------------------------------------------------------------------- #
# 迁移
# --------------------------------------------------------------------------- #

def migrate(old_book, old_anchors, new_book, new_anchors, notes):
    old_ids = {b["id"]: b for b in old_anchors["blocks"]}
    new_by_id = {b["id"]: b for b in new_anchors["blocks"]}
    new_by_chapter: dict[str, list] = {}
    for b in new_anchors["blocks"]:
        new_by_chapter.setdefault(b["chapter"], []).append(b)

    results = []
    for note in notes:
        rec = {"id": note["id"], "text": note["text"], "old_cfi": note["cfi"]}
        # ---- 1. 快路径 ----
        try:
            href, el, off = resolve_cfi(new_book, note["cfi"])
            got = full_text(el)[off:off + len(note["text"])]
            if norm(got) == norm(note["text"]):
                rec.update(new_cfi=note["cfi"], status="kept",
                           chapter=href, note_text=note.get("note", ""))
                results.append(rec)
                continue
        except Exception:  # noqa: BLE001
            pass

        # ---- 定位旧块 ----
        try:
            old_hit = block_of(old_book, old_anchors, note["cfi"])
        except Exception:  # noqa: BLE001
            old_hit = None
        if not old_hit:
            rec.update(status="dropped", reason="旧 CFI 无法解析到任何块")
            results.append(rec)
            continue
        old_id, old_block_text, old_href = old_hit
        chapter = old_ids.get(old_id, {}).get("chapter", "")
        rec["old_block"] = old_id

        # ---- 2. 锚点路径：同 id 在不在新书里 ----
        target = new_by_id.get(old_id)
        if target:
            href, el = find_element_by_id(new_book, old_id)
            if el is not None:
                block_text = full_text(el)
                pos = locate(block_text, note["text"])
                if pos is None:
                    # 同 id 但块文字变了（说明这段被改写）：退回按比例插值
                    ratio = _pos_ratio(old_block_text, note["text"])
                    pos = int(ratio * len(block_text))
                got = block_text[pos:pos + len(note["text"])]
                rec.update(new_cfi=cfi_for_offset(new_book, href, el, pos),
                           status="remapped", chapter=href,
                           verified=norm(got) == norm(note["text"]))
                results.append(rec)
                continue

        # ---- 3. 文字路径：在同章候选块里找最像的 ----
        best, best_score = None, 0.0
        for cand in new_by_chapter.get(chapter, []):
            score = difflib.SequenceMatcher(
                None, norm(note["text"]), norm(cand["text"])).ratio()
            if score > best_score:
                best, best_score = cand, score
        if best and best_score >= 0.55:
            href, el = find_element_by_id(new_book, best["id"])
            if el is not None:
                block_text = full_text(el)
                pos = locate(block_text, note["text"])
                if pos is None:
                    ratio = _pos_ratio(old_block_text, note["text"])
                    pos = int(ratio * len(block_text))
                pos = max(0, min(pos, max(0, len(block_text) - 1)))
                rec.update(new_cfi=cfi_for_offset(new_book, href, el, pos),
                           status="fuzzy", chapter=href, score=round(best_score, 2),
                           verified=norm(block_text[pos:pos + len(note["text"])])
                           == norm(note["text"]))
                results.append(rec)
                continue

        rec.update(status="dropped", reason="新旧版都找不到对应文字")
        results.append(rec)

    return results


def _norm_map(s: str):
    """返回 (去空白后的文本, 每个字符在原文里的下标)。"""
    chars, idx = [], []
    for i, ch in enumerate(s):
        if not ch.isspace():
            chars.append(ch)
            idx.append(i)
    return "".join(chars), idx


def locate(hay: str, needle: str):
    """在 hay 里找 needle 的最佳匹配起点（原文下标）。找不到返回 None。

    先试精确子串（去空白后），再退回 difflib 的最长公共块 —— 段落被改写时
    仍能锚到「变化最小的那一段」上。
    """
    h, hmap = _norm_map(hay)
    n, _ = _norm_map(needle)
    if not n or not h:
        return None
    i = h.find(n)
    if i >= 0:
        pos = hmap[i]
        # 笔记原文可能以空白开头（选中时带上了行首/段间空格）：把位置往前对齐，
        # 否则截取窗口会整体偏一个字符
        lead = len(needle) - len(needle.lstrip())
        while lead > 0 and pos > 0 and hay[pos - 1].isspace():
            pos -= 1
            lead -= 1
        return pos
    sm = difflib.SequenceMatcher(None, h, n, autojunk=False)
    m = sm.find_longest_match(0, len(h), 0, len(n))
    if m.size >= max(6, len(n) // 4):
        return hmap[m.a]
    return None


def _pos_ratio(block: str, needle: str) -> float:
    pos = locate(block, needle)
    if pos is None or not block:
        return 0.0
    return pos / len(block)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-epub", type=Path, required=True)
    ap.add_argument("--old-anchors", type=Path, required=True)
    ap.add_argument("--new-epub", type=Path, required=True)
    ap.add_argument("--new-anchors", type=Path, required=True)
    ap.add_argument("--notes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=None)
    a = ap.parse_args()

    old_book = Book.open(a.old_epub)
    new_book = Book.open(a.new_epub)
    old_anchors = json.loads(a.old_anchors.read_text(encoding="utf-8"))
    new_anchors = json.loads(a.new_anchors.read_text(encoding="utf-8"))
    notes = json.loads(a.notes.read_text(encoding="utf-8"))

    res = migrate(old_book, old_anchors, new_book, new_anchors, notes)
    a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    from collections import Counter
    c = Counter(r["status"] for r in res)
    n = len(res)
    print(f"笔记 {n} 条")
    for k in ("kept", "remapped", "fuzzy", "dropped"):
        if c[k]:
            print(f"  {k:9s} {c[k]:4d}  {c[k]/n*100:5.1f}%")
    ok = sum(1 for r in res if r.get("verified") is True)
    unv = sum(1 for r in res if r["status"] in ("remapped", "fuzzy") and not r.get("verified"))
    print(f"  位置自校验通过 {ok} 条；需人工确认 {unv} 条")
    if a.report:
        a.report.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"明细 -> {a.report}")


if __name__ == "__main__":
    main()
