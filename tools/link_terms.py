"""在每课正文里给「术语表里有的词」的首次出现加跳转。

只跑一次。脚本不幂等：已链的那一处被 <a> 包住会跳过，第二次跑就会把同一课里
下一处出现当成「首次」再链一遍。要重跑先 `git checkout lessons/`。

用法：cd 仓库根目录，python3 tools/link_terms.py


规则：
- 每个术语在同一课里只链接第一次出现处。
- 跳过原文摘译块（.excerpt）、code/pre、h1-h4、已有 <a>、图注、练习区。
- 歧义大的词（图 / 模式 / 连接）不自动链接；另几个词带上下文护栏。
"""
import re
import glob
import os
import json

GLOSS = 'reference/glossary.html'
HREF = '../reference/glossary.html'

TERM_BLACKLIST = {'图', '模式', '连接'}

# 术语 -> 判定函数 (prev2, next2, need) 返回 True 表示此处不该链接
GUARDS = {
    '事务': lambda p, n, s, k: p.endswith(('联机', '混合')) or n.startswith(('型', '/', '理')),
    '复制': lambda p, n, s, k: p.endswith('被') or n.startswith(('文件', '整张', '一份', '库', '过来')),
    '无主': lambda p, n, s, k: n.startswith('动'),
    '容错': lambda p, n, s, k: p.endswith('分区'),
    '规范化': lambda p, n, s, k: p.endswith('反'),
    '偏斜': lambda p, n, s, k: p.endswith('写'),
    '物化': lambda p, n, s, k: False,
}

PROT_TAGS = {'code', 'pre', 'a', 'h1', 'h2', 'h3', 'h4', 'button',
             'figcaption', 'script', 'style', 'textarea',
             'title', 'head', 'cite', 'blockquote', 'sup', 'nav'}
PROT_KEYS = ['excerpt', 'quiz', 'recall', 'triage', 'answer', 'src', 'term',
             'reveal', 'feedback', 'note', 'gloss', 'nav-links']


def load_terms():
    g = open(GLOSS, encoding='utf-8').read()
    terms = []
    for m in re.finditer(r'<dt id="([^"]+)">(.*?)<span class="en">', g, re.S):
        zh = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if zh in TERM_BLACKLIST:
            continue
        terms.append((zh, m.group(1)))
    terms.sort(key=lambda t: -len(t[0]))
    return terms


def segments(html):
    """返回 [(start, text, stack)]，stack 是祖先标签名"""
    out = []
    stack = []
    i = 0
    for m in re.finditer(r'<[^>]+>', html):
        if m.start() > i:
            out.append((i, html[i:m.start()], tuple(stack)))
        tag = m.group(0)
        if tag.startswith('</'):
            name = tag[2:-1].strip().lower()
            for k in range(len(stack) - 1, -1, -1):
                if stack[k] == name:
                    del stack[k:]
                    break
        elif tag.endswith('/>'):
            pass
        else:
            nm = re.match(r'<([a-zA-Z0-9]+)', tag)
            if nm:
                stack.append(nm.group(1).lower())
        i = m.end()
    if i < len(html):
        out.append((i, html[i:], tuple(stack)))
    return out


def protected_ranges(html):
    ranges = []
    for m in re.finditer(r'<(div|p|section|ul|ol|li|blockquote|span)\b[^>]*class="([^"]*)"[^>]*>', html):
        if any(c in m.group(2) for c in PROT_KEYS):
            name = m.group(1)
            depth = 1
            pat = re.compile(r'</?%s\b' % name)
            for t in pat.finditer(html, m.end()):
                depth += -1 if t.group(0).startswith('</') else 1
                if depth == 0:
                    ranges.append((m.start(), t.end()))
                    break
    return ranges


def process(path, terms):
    html = open(path, encoding='utf-8').read()
    prot = protected_ranges(html)
    linked = {}
    inserts = []  # (start, end, zh, slug)

    for pos, text, stack in segments(html):
        if any(s in PROT_TAGS for s in stack):
            continue
        if any(a <= pos < b for a, b in prot):
            continue
        # 收集本段所有候选
        cands = []
        for zh, slug in terms:
            if zh in linked:
                continue
            start = 0
            while True:
                k = text.find(zh, start)
                if k < 0:
                    break
                prev = text[max(0, k - 4):k]
                nxt = text[k + len(zh):k + len(zh) + 4]
                if zh in GUARDS and GUARDS[zh](prev, nxt, text, k):
                    start = k + 1
                    continue
                cands.append((k, -len(zh), zh, slug))
                break  # 只看该术语在本段的第一次
        cands.sort()
        taken = []
        for k, neglen, zh, slug in cands:
            s, e = pos + k, pos + k + len(zh)
            if any(not (e <= ts or s >= te) for ts, te in taken):
                continue
            if zh in linked:
                continue
            taken.append((s, e))
            linked[zh] = slug
            inserts.append((s, e, zh, slug))

    out = []
    cur = 0
    for s, e, zh, slug in sorted(inserts):
        out.append(html[cur:s])
        out.append('<a class="gref" href="%s#%s">%s</a>' % (HREF, slug, html[s:e]))
        cur = e
    out.append(html[cur:])
    new = ''.join(out)
    open(path, 'w', encoding='utf-8').write(new)
    return linked


def main():
    terms = load_terms()
    print('可用术语', len(terms))
    report = {}
    for f in sorted(glob.glob('lessons/00*.html')):
        linked = process(f, terms)
        report[os.path.basename(f)] = sorted(linked)
        print(os.path.basename(f), len(linked), ' '.join(sorted(linked)))
    json.dump(report, open('.work/links.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
