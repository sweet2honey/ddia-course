# 把网页站点做成 EPUB —— 并且让笔记不漂移

这份文档对应三个脚本：

| 脚本 | 作用 |
| --- | --- |
| `tools/build_epub.py` | 把站点（首页 + 14 课 + 术语表 + 速查 + 3 个 md）构建成 EPUB 3；同时产出 `dist/anchors.json` |
| `tools/cfi_drift.py` | 漂移实验：把旧版生成的 CFI 拿到新版解析，分类统计 exact / moved / wrong / lost |
| `tools/migrate_notes.py` | 用稳定锚点把旧版笔记迁移到新版，逐条自校验 |

```bash
python3 tools/build_epub.py                 # → dist/ddia-course.epub + dist/anchors.json
java -jar .build/tool/epubcheck-5.1.0/epubcheck.jar dist/ddia-course.epub
```

---

## 一、先说结论

**「网页转 EPUB」这一步是最容易的；真正难的是「更新后笔记不漂移」，而这件事没有免费午餐。**

- 单纯重新生成 EPUB：所有阅读器都会**部分或全部丢掉**旧笔记。实测在本项目上：
  - 没改过的章节：笔记 100% 保留（因为 CFI 的章前缀和章内 DOM 路径都没变）；
  - 改过的章节：**89% 的笔记失效**（137 条里 15 条还对得上）；失效的 122 条中，63 条是「静默错位」——阅读器不报错，高亮悄悄套到了别的段落上，另外 59 条直接解析失败。
- 只把某一章移到书脊别的位置（内容一个字没改）：**100% 失效**，因为 CFI 的 `/6/N` 是序号。
- 加了锚点迁移之后：整体可用率从 85.2% → **99.9%**（改过的章从 10.9% → 99.3%）。

所以路线是：**能自己构建 EPUB（不依赖第三方转换器）＋ 构建时埋稳定锚点 ＋ 更新后跑一次笔记迁移**。只要换成「随手用某个工具另存一份」的做法，笔记就注定漂。

---

## 二、网页 → EPUB 的几条路，以及为什么这里选自建

| 方法 | 适合 | 在本项目上的问题 |
| --- | --- | --- |
| **自建脚本（本项目做法）** | 站点结构稳定、要长期维护、要控制锚点 | 要写代码（约 900 行，用 lxml + Pillow，无新依赖） |
| Calibre「网页转电子书」/ `ebook-convert` | 一次性抓取上线网页 | 走 DOM 重排，生成的 id 每次都可能变；离线交互组件会变成半截；锚点不可控 |
| pandoc（HTML→EPUB） | 纯文章、结构简单 | 不认这套自定义 class 语义（quiz/recall/triage），CSS grid 组件会散架；`<button>` 里的选项内容和 `data-why` 会丢 |
| Sigil / 手工整理 | 只想做一版就完事 | 无法自动化，站点一更新就得重来；无锚点清单 |
| 直接发 PDF | 只读、不标注 | 阅读器笔记体系弱，且改一页就全乱 |

选自建的理由只有一条：**笔记不漂移要求「构建过程可重复、id 由内容推导」，这件事必须由自己的构建器保证**，第三方转换器不提供这个能力。

构建器做的事（细节见脚本头部注释）：

- 一章一个 XHTML，平铺在 `OEBPS/` 下（放 `OEBPS/text/` 曾导致 90 个 `RSC-007` 相对路径错误）；
- EPUB 无 JS，交互组件静态降级：quiz 正确答案标 `✓` 并把每个选项的 `data-why` 展开成解析；recall 的答案与 triage 的 note 强制可见（网页里靠 CSS 隐藏，直接搬进 EPUB 会变成「内容永久看不见」）；
- CSS grid 全部降级为单列、`rem` 换 `em`、去掉 `:target` 依赖（KOReader 等阅读器不保证支持）；
- 只打包被引用的 48 张图（`assets/fig` 里有 105 张），封面用 Pillow 现生成；
- `BOOK_ID` 固定、`dcterms:modified` 固定、zip 时间戳固定 → **同一份源文件每次构建字节级一致**（实测三次构建 sha256 相同），这对「判断这本书是不是新版本」很有用；
- epubcheck 5.1.0：0 errors / 0 warnings。

---

## 三、笔记为什么会漂：阅读器到底存了什么

各种阅读器的存储位置不同，但**定位方式基本都是 EPUB CFI**（少数用私有偏移）：

```
epubcfi(/6/6[lesson-0003]!/4/10:90)
         └── spine 第 3 个 itemref   └ 文档树第 10 个元素（body 内第 5 个）第 90 个字符
```

CFI 是一个**纯路径**：不含内容、不含哈希。于是：

1. **章内插入一段** → 后面所有段落的位置 +1，CFI 仍"合法"，但指向了下一段 → 静默错位。
2. **删除一段** → 后面的段落上移，同样静默错位；越界则直接解析失败。
3. **spine 中间插一章 / 换文件名** → `/6/N` 整体位移，`!` 之后可能全部解析失败。

规范（EPUB CFI §3.5）要求实现校验方括号里那些断言（XML ID、前后文），失败就判为无效引用，**但多数阅读器只存不校验**。实测本项目改过的章节里，89% 的笔记失效，其中一半是"不报错的那种"。

各阅读器的额外事实（来自源码核对，详见 `.research/epub-annotation-drift.md`）：

- **KOReader**：sidecar 是 `<书路径去扩展名>.sdr/metadata.epub.lua`，**按文件名认书**，默认不比对内容；hash 目录模式（`partialMD5`）存在但不是默认。标注存 xPointer，加载时 `isXPointerInDocument()` 失败就 `Skipping old bookmark, invalid start xpointer:` —— **直接丢弃，不重锚**。
- **Calibre viewer**：标注存三处（库内 `annotations` 表按 `book_id+format`、配置目录下以书路径 sha256 为键的 JSON、书内 `META-INF/calibre_bookmarks.txt`）。阅读位置存的是 CFI。
- **Apple Books**：标注存在书外数据库，认书靠 `dc:identifier`（本项目 `BOOK_ID` 固定，这点对我们有利），同时保留文本片段。
- **Kindle**：位置 = 解包后字节偏移 /150，私有且未公开规范，改内容必漂。

---

## 四、本项目怎么做到「基本不漂」——三层防线

### 第 1 层：结构上把爆炸半径关进一章

一章一个 XHTML，且**只在 spine 末尾追加**，不改已有文件名。这样：

- 没改过的章，CFI 前缀（`/6/N`）和文档名都不变 → 笔记 100% 保留（实测 687/687）；
- 改动的影响被限制在「那一章之内」。

**不要**重排已有章节顺序、不要改 `lesson-000N.xhtml` 这类文件名 —— 这两件事会让所有笔记前缀失效。

### 第 2 层：给每个块埋内容锚点（`dist/anchors.json`）

构建时给每个块元素（p / li / dd / h2-h4 / figure / table / blockquote / pre / ul / ol / dl）打一个 id：

```
id = <标签前缀>-<sha1(标签名 + "\0" + 去空白后的块文本)[:8]>
```

例如 `p-e608bb6c`。含义非常关键：

- **别处增删段落 → 其它块的 id 一个都不变**（这是它比序号强的地方）；
- **某段文字被改写 → 只有那一段的 id 变**（这正是我们想要的信号：能区分"移动"和"改写"）；
- 同一个文本出现多次 → 按顺序加 `-2`/`-3`（会随重复次数变化，这是它的已知弱点）。

一次构建约 2 660 个锚点，落盘为 `dist/anchors.json`（`book_id` / `book_title` / spine / `blocks[{id, tag, chapter, text[:160]}]`）。

小节标题另有一套按编号的稳定 id：`sec-3-4`（来自 `span.num` 里的数字），改标题措辞不影响它。

### 第 3 层：更新后跑一次迁移（`tools/migrate_notes.py`）

三级降级，逐级自校验：

1. **fast path** —— 旧 CFI 在新书里仍能解析，且解析出的文字与笔记原文一致（去空白比对）→ `kept`，直接用。
2. **anchor path** —— 用旧 `anchors.json` 找出这条 CFI 属于哪个块 id，在新 `anchors.json` 里找同一个 id → 用文本对齐（先精确子串，失败退 `difflib` 最长公共块）在新块里定位 → 重算 CFI，**校验文字是否对得上** → `remapped`。
3. **text path** —— 锚点 id 变了（说明这段被改写），在同章候选块里按 `SequenceMatcher` 相似度打分，≥0.55 才接受 → `fuzzy`；否则 `dropped`，**标出来让人确认，不静默处理**。

实测（824 条模拟笔记，改动了 2 章、插删改合计 6 处）：

| | 裸 CFI | 迁移后 |
| --- | --- | --- |
| 改过的章（137 条） | 10.9% 可用 | **99.3%** 可用 |
| 没改的章（687 条） | 100% 可用 | 100% 可用 |
| 合计（824 条） | 85.2% | **99.9%**（1 条标 `dropped`） |

另外单独测了「spine 中间插一章」这个更狠的场景：裸 CFI **0% 可用**（432 条静默错位 / 392 条丢失），走锚点迁移后仍是 **99.9%** —— 因为锚点 id 不依赖序号。

```bash
python3 tools/migrate_notes.py \
  --old-epub v1.epub --old-anchors anchors-v1.json \
  --new-epub v2.epub --new-anchors anchors-v2.json \
  --notes notes-v1.json --out notes-v2.json
```

> `--notes` 的格式是一条条 `{"id", "cfi", "text", "note"}`。从阅读器导出笔记时，把「原文片段」一起存下来（`text` 字段）—— 这是迁移能自校验的前提。

---

## 五、日常维护流程

```bash
# 1) 改站点内容（lessons/ reference/ ...）

# 2) 构建新书 + 新锚点
python3 tools/build_epub.py --out dist/ddia-course.epub --anchors dist/anchors.json

# 3) 校验
java -jar .build/tool/epubcheck-5.1.0/epubcheck.jar dist/ddia-course.epub

# 4) 迁移笔记（旧版的 anchors.json 和笔记要留着）
python3 tools/migrate_notes.py --old-epub old.epub --old-anchors old-anchors.json \
  --new-epub dist/ddia-course.epub --new-anchors dist/anchors.json \
  --notes my-notes.json --out my-notes-migrated.json

# 5) 看报告：kept / remapped / fuzzy 可直接采信；dropped 需要人工看一眼
```

**务必归档 `dist/anchors.json`**（连同版本号或 git tag）。它是迁移的桥；丢了就只能退化到纯文本猜测。

---

## 六、阅读器设置建议（能明显降低漂移）

1. **KOReader**：`document_metadata_folder = "hash"` 会让 sidecar 目录跟着内容 hash 变 —— 换版本等于找不到旧 sidecar。**保持默认（按文件名）**，并在替换文件前先备份 `.sdr` 目录。
2. **别改文件名**。所有阅读器都或多或少按文件名/路径认书；改成 `ddia-course-v2.epub` 会变成一本新书。
3. **保持 `dc:identifier`（BOOK_ID）不变** —— 本项目已固定，Apple Books 之类的阅读器靠它认"还是同一本"。
4. **优先在 Kindle/Calibre 之外的地方做标注**，或者接受 Kindle 的 location 一定会漂（它连规范都没公开）。
5. **重新导入前导出一次笔记**（含原文片段）。哪怕迁移脚本也救不了「阅读器已经静默丢弃」的旧标注。

---

## 七、仍然会漂的情况（诚实清单）

- 段内局部改写（一句话改了几个词）：CFI 会落在旧位置附近，文字对不上 → 迁移会走 `fuzzy` 或标 `dropped`，需要人工确认。
- 完全重复的段落（同一句话在书里出现多次）：锚点 id 靠序号后缀区分，插入/删除同类重复段会让后缀整体位移。
- 整章重写：锚点全变，只有靠「章 + 相似度」这一级，命中率取决于改写幅度。
- 阅读器端根本不提供 CFI/笔记导出（如部分封闭 App）：无论构建器多稳，也只能等阅读器自己修。

这就是为什么推荐**把笔记连同原文片段一起存档**——它是不依赖任何阅读器实现的自救手段。
