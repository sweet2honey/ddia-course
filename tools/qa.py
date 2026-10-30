#!/usr/bin/env python3
"""QA 自检：python3 tools/qa.py
检查每个 lesson / reference 页面的标签配对、相对链接、禁用项、组件数量、正文字数。"""
import re, sys, os
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOID = {'br','img','hr','meta','link','input','source','col','area','base','embed','wbr'}

class Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []
    def handle_starttag(self, tag, attrs):
        if tag not in VOID: self.stack.append((tag, self.getpos()))
    def handle_endtag(self, tag):
        if tag in VOID: return
        if not self.stack: self.errors.append(f"多余 </{tag}> @{self.getpos()}"); return
        if self.stack[-1][0] != tag:
            self.errors.append(f"未配对：期望 </{self.stack[-1][0]}>（开于 {self.stack[-1][1]}），遇到 </{tag}> @{self.getpos()}")
            for i in range(len(self.stack)-1, -1, -1):
                if self.stack[i][0] == tag: del self.stack[i:]; return
        else: self.stack.pop()

def check(path):
    html = open(path, encoding='utf-8').read()
    errs = []
    c = Checker(); c.feed(html)
    errs += c.errors
    errs += [f"未闭合 <{t}> @{p}" for t, p in c.stack]

    # 禁用项
    if re.search(r'<style[\s>]', html): errs.append("含 <style>，应外链 assets/course.css")
    for m in re.finditer(r'<script[^>]+src="(https?://[^"]+)"', html):
        errs.append(f"外链脚本 {m.group(1)}")
    for m in re.finditer(r'<link[^>]+href="(https?://[^"]+)"', html):
        errs.append(f"外链样式 {m.group(1)}")

    # 相对链接存在性
    base = os.path.dirname(path)
    for m in re.finditer(r'(?:href|src)="([^"#:]+)(?:#[^"]*)?"', html):
        rel = m.group(1)
        if rel.startswith(('http','//','mailto:','#')): continue
        tgt = os.path.normpath(os.path.join(base, rel))
        if not os.path.exists(tgt): errs.append(f"相对链接失效：{rel}")

    # 组件与字数
    def n(cls): return len(re.findall(r'class="[^"]*\b%s\b[^"]*"' % cls, html))
    stats = dict(
        excerpt=n('excerpt'), anti=n('anti'), key=n('key'), fig=n('fig'),
        quiz=n('quiz'), recall=n('recall'), triage=n('triage'),
        chars=len(re.findall(r'[\u4e00-\u9fff]', re.sub(r'<[^>]+>', '', html))),
    )
    if '/lessons/' in path:
        if stats['excerpt'] < 2: errs.append(f"摘译只有 {stats['excerpt']} 个（需 ≥2）")
        if stats['anti'] < 1: errs.append("缺 .anti 反例块")
        if stats['quiz'] + stats['recall'] + stats['triage'] < 1: errs.append("缺交互组件")
        if stats['chars'] < 2500: errs.append(f"正文汉字 {stats['chars']} < 2500")
        if 'course.js' not in html: errs.append("未引入 course.js")
        if 'course.css' not in html: errs.append("未引入 course.css")
        if 'class="foot"' not in html: errs.append("缺 .foot 页脚")
        if 'nav-links' not in html: errs.append("缺 .nav-links")
    return errs, stats

def main():
    targets = []
    for d in ('lessons', 'reference'):
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            targets += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith('.html')]
    targets.append(os.path.join(ROOT, 'index.html'))
    bad = 0
    for t in targets:
        errs, st = check(t)
        rel = os.path.relpath(t, ROOT)
        flag = 'FAIL' if errs else ' ok '
        print(f"[{flag}] {rel:52s} 汉字{st['chars']:5d} 摘译{st['excerpt']} 反例{st['anti']} 图{st['fig']} "
              f"测{st['quiz']}/忆{st['recall']}/判{st['triage']}")
        for e in errs: print("        -", e); bad += 1
    print()
    print("全部通过" if not bad else f"{bad} 处问题")
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main())
