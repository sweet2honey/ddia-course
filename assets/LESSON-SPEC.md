# 课程写作规范（DDIA 第二版 · 14 课统一标准）

所有 lesson 都是**单个自包含 HTML**，只链接两个共享资源：

```html
<link rel="stylesheet" href="../assets/course.css">
...
<script src="../assets/course.js"></script>   <!-- body 末尾，</main> 之后 -->
```

不要内联 `<style>`，不要引入任何外部字体/JS/CDN。插图用本地 `../assets/fig/ddia_NNMM.png`。

## 读者画像（硬约束，必须照做）

- **目标：系统设计面试 / 架构评审。** 读者要的是把权衡讲清楚、能被追问、能写进评审文档。**概念框架优先于实现细节。**
- **语言：C / C++ / Rust，偏底层、性能敏感。** 例子可以落到页缓存、`fsync`、`mmap`、`O_DIRECT`、页大小、系统调用、socket 超时这一层——但落点必须是**架构决策**，不是「自己实现存储引擎」。原书的 Java/产品故事可保留，但要补一个底层视角的等价物。
- 中文写作，术语用中文译本措辞并括注英文，如「复制延迟（replication lag）」「读己之写（read-your-writes）」「写偏斜（write skew）」。
- 读者真实的三个痛点，每课至少正面回应一个：
  1. **面试被追问就崩**：名词会说，代价说不清；被问「为什么不选 X」答不出双向代价。
  2. **评审文档里写不出可被追问的取舍**：只会写「用 Redis 缓存、最终一致」，写不出放弃了哪条不变式、失效时影响谁。
  3. **选型靠跟风**：Kafka / Redis / Postgres / 图数据库，说不出在自己这个规模与故障模型下哪条假设先破。

## 厚度（硬约束）

每课 **20 分钟以上**阅读量，**至少 2500 汉字**正文，无上限（4000–6000 是常态，硬骨头章可以更多）。必须包含：

1. **至少 2 个 `.excerpt` 原文摘译块**——从 `src/chNN.md` 摘 2–5 句原意，行首用 `<span class="src">第 N 章 · 小节主题</span>` 标明来源。**必须是书里真有的意思**，不许编。机翻味道重的句子要改写通顺，但不能改变论断。
2. **至少 1 个 `.anti` 反例分析块**——左边「这样设计」，右边「为什么崩 / 怎么改」，写真实架构里的失效场景（配额、热点、重试风暴、切换丢数据……），不要写玩具例子。
3. **一段「面试里怎么答」**：给出 3–5 句可以直接背下来的答法，含数字或明确条件。
4. **至少 1 个 `.excerpt` 之外的原书插图**（有图的章）——用 `.fig` 组件引 `../assets/fig/ddia_NNMM.png`，图注从 `src/figures.json` 抄或改写。无图的章（ch14）跳过这条。
5. 结尾给一句**能贴进评审文档的话**（放 `.key` 里或单独一段）。

## 组件（只用这些 class，已全部在 course.css 里）

| 用途 | 写法 |
|---|---|
| 引文（卷首语等） | `<blockquote><p>…</p><cite>第 N 章</cite></blockquote>` |
| 原文摘译 | `<div class="excerpt"><span class="src">第 N 章 · 小节主题</span><p>…</p></div>` |
| 反例 | `<div class="anti"><h4>反例</h4><div class="pair"><div><b>这样设计</b><p>…</p></div><div><b>为什么崩</b><p>…</p></div></div><p>改法：…</p></div>` |
| 核心结论 | `<div class="key"><p><strong>…</strong></p></div>` |
| 补充卡 | `<div class="card"><h4>标题</h4><p>…</p></div>` |
| 两栏 | `<div class="grid2">…</div>` |
| 插图 | `<figure class="fig"><img src="../assets/fig/ddia_0601.png" alt="…"><figcaption><b>图 6-1</b> 图注</figcaption></figure>` |
| 表格 | 原生 `<table>`（css 已样式化），表头 `<thead>`，题注放表前一段 `.lead-in` |
| 单选 | `<div class="quiz"><p class="q">题干</p><button data-ok="1" data-why="…">A</button><button data-why="…">B</button><button data-why="…">C</button><p class="feedback"></p></div>` |
| 回忆卡 | `<div class="recall"><p>题</p><textarea placeholder="…"></textarea><button class="reveal">对照答案</button><div class="answer">…</div></div>` |
| 场景判断（多行） | `<div class="triage"><p class="score"></p><div class="row"><p>场景</p><div class="opts"><button data-ok="1">标签</button><button>标签</button></div><p class="note">解释</p></div>…</div>` |

**测验铁律**：同一题内每个选项字数尽量相等；正确答案位置要变化，不能总在第一个；不能靠格式或顺序泄露答案。

**`.triage` 是 DDIA 的主力组件**：给 3–5 个真实架构描述，让读者判断「这属于哪种一致性/隔离级别/故障模式」。这种题最接近面试与评审的真实动作。

## 固定骨架

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>L6 · 复制 — 数据密集型应用系统设计</title>
<link rel="stylesheet" href="../assets/course.css">
</head>
<body>
<main class="page">

<p class="crumb"><a href="../reference/glossary.html">术语表</a> · 第 6 章 · 课程 6 / 14</p>

<h1>复制</h1>
<p class="standfirst">一句话说清这一章在架构决策里的位置：你为了解决什么问题，付出哪条不变式的代价。</p>

<h2><span class="num">6.1</span>小节标题</h2>
…

<hr>

<h2><span class="num">练习</span>…</h2>
<div class="triage">…</div>   <!-- 或 quiz / recall -->

<div class="foot">
  <h4>一手资源</h4>
  <p><a href="https://ddia.vonng.com/ch6/">第 6 章 复制（中文全译）</a> — 补一句为什么值得读原文。</p>

  <h4>随时问我</h4>
  <p class="ask">给一个具体到可以直接动手的邀请（贴一段你的设计文档 / 一个正在纠结的选型）。</p>

  <div class="nav-links">
    <span><a href="0005-encoding-and-evolution.html">← L5 · 编码与演化</a></span>
    <span><a href="0007-sharding.html">L7 · 分片 →</a></span>
  </div>
</div>

</main>
<script src="../assets/course.js"></script>
</body>
</html>
```

小节编号用章号（`<span class="num">6.1</span>`）。**课程编号 = 章号**，L1=ch1 … L14=ch14。

## 文件名（已定，不要改）

| 课 | 文件 |
|---|---|
| L1 | `lessons/0001-tradeoffs-in-data-systems.html` |
| L2 | `lessons/0002-nonfunctional-requirements.html` |
| L3 | `lessons/0003-data-models-and-query-languages.html` |
| L4 | `lessons/0004-storage-and-retrieval.html` |
| L5 | `lessons/0005-encoding-and-evolution.html` |
| L6 | `lessons/0006-replication.html` |
| L7 | `lessons/0007-sharding.html` |
| L8 | `lessons/0008-transactions.html` |
| L9 | `lessons/0009-trouble-with-distributed-systems.html` |
| L10 | `lessons/0010-consistency-and-consensus.html` |
| L11 | `lessons/0011-batch-processing.html` |
| L12 | `lessons/0012-stream-processing.html` |
| L13 | `lessons/0013-philosophy-of-streaming-systems.html` |
| L14 | `lessons/0014-doing-the-right-thing.html` |

## 原文本地位置

- `src/chNN.md` — 中文全译，首选
- `src/glossary.md` — 61 条术语原定义，写课时术语以此为准
- `src/figures.json` — 每章插图清单：`{"6": [{"num":"6-1","src":"assets/fig/ddia_0601.png","caption":"…"}]}`
- `assets/fig/` — 105 张插图
- 在线原站：`https://ddia.vonng.com/chN/`

## 自检（交付前必须做）

1. 用 python `html.parser` 跑一遍，确认标签配对无异常（`HTMLParser.feed` + 检查未闭合栈）。
2. 所有相对链接真实存在：`../assets/course.css`、`../assets/course.js`、`../reference/glossary.html`、前后课、`../assets/fig/*.png`。
3. 没有 `<style>`、没有外链 CDN。
4. 每课至少 2 个 `.excerpt`、至少 1 个 `.anti`、至少 1 个交互组件（quiz / recall / triage）。
5. `grep -o 'class="excerpt"' 文件 | wc -l` 数量达标；正文汉字数 ≥ 2500（`python3 -c` 数中文字符）。
