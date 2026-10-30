# 数据密集型应用系统设计（DDIA 第二版）· Resources

## Knowledge

### 主线

- [书（中文全译，第二版）: _数据密集型应用系统设计_ — Martin Kleppmann / Chris Riccomini](https://ddia.vonng.com/)
  本课程的主线教材，14 章 + 术语表。第 N 章对应 `lessons/` 里的 L N。术语以这个译本为准，含糊处回英文原书核对。本地副本在 `src/chNN.md`（从译本仓库 `content/zh/` 摊平），`src/figures.json` 是各章插图清单。
- [译本源码仓库（Vonng/ddia）](https://github.com/Vonng/ddia)
  全站 markdown 源 + 插图。**用 for**：核对某句译文、找回原文图注、查章节锚点。第二版新增的第 2 章（非功能性需求）、第 13 章（流式系统的哲学）、第 14 章（做正确的事情）只有第二版有。
- [作者书页（Kleppmann, dataintensive.net）](https://dataintensive.net/)
  两版目录对照、勘误、幻灯片与练习答案。**用 for**：确认某条论断是不是作者本人的原话、第二版删掉了什么。
- [作者博客（martin.kleppmann.com）](https://martin.kleppmann.com/)
  书的延伸论文与讲座：本地优先软件（local-first）、CRDT、形式化验证分布式系统。**用 for**：想追到书里某句话背后的论文时。

### 原始论文（书里每章的地基）

- [Dynamo: Amazon's Highly Available Key-value Store (SOSP 2007, PDF)](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)
  第 6、7 章的整套词汇来源：一致性哈希、向量时钟、 hinted handoff、读写法定人数。**用 for**：想知道「最终一致」在原始设计里到底承诺了什么。
- [Bigtable: A Distributed Storage System for Structured Data (Google, PDF)](https://research.google/pubs/pub27898/)
  第 3、4 章的来源：稀疏列族、SSTable、memtable 刷盘。**用 for**：LSM 树为什么长这样。
- [Raft 共识算法（raft.github.io）](https://raft.github.io/)
  第 10 章的对标物。交互式可视化 + 原始论文 + 各语言实现清单。**用 for**：Paxos 读不下去时的替代入口。
- [Spanner: Google's Globally-Distributed Database (OSDI 2012, PDF)](https://www.usenix.org/legacy/event/osdi10/tech/full_papers/Beaver.pdf)
  第 9、10 章的外部时间戳与 TrueTime。**用 for**：想弄清「用时钟换共识」这条路的边界条件。
- [CRDTs 入门站（crdt.tech）](https://www.crdt.tech/)
  第 13 章状态同步分支的入口，附论文与实现。**用 for**：判断什么时候可以不要协调。

### 校验与对照

- [Jepsen 分析报告](https://jepsen.io/analyses)
  把真实数据库拉到分区、时钟跳变、进程暂停下测，逐条给出「它到底保证了什么」。**用 for**：书里说「某个数据库声称可串行化」时，来这里看实测。第 8、9、10 章最好的冷水。
- [Aphyr: Strong Consistency Models](https://aphyr.com/posts/313-strong-consistency-revisited)
  线性一致 / 顺序一致 / 因果一致的可操作定义与图示。**用 for**：面试被追问「你说的强一致是哪一个」时，先在这里对齐定义。
- [Notes on Distributed Systems for Young Bloods](https://www.somethingsimilar.com/2013/01/14/notes-on-distributed-systems-for-young-bloods/)
  一页纸的实战教训（超时、重试、部分失败）。**用 for**：第 9 章「不可靠的网络」的浓缩版。
- [System Design Primer](https://github.com/donnemartin/system-design-primer)
  面试语料库。**用 for**：拿它的题目当练习场，但答案要用本课程的词汇重写——它偏清单，缺代价分析。
- [The Big Data Engineer's 面试题库（databass.dev / 各厂 blog）](https://www.databass.dev/)
  Database Internals 作者的书与文章。**用 for**：第 4 章存储引擎部分想再往实现走一步时。

## Wisdom (Communities)

- [Vonng/ddia Discussions](https://github.com/Vonng/ddia/discussions)
  译本仓库的讨论区，中文，提问质量较高。**用 for**：某句译文读不通、或想确认第二版某处是否改动时，直接问。
- [r/dataengineering](https://www.reddit.com/r/dataengineering/) / [r/ExperiencedDevs](https://www.reddit.com/r/ExperiencedDevs/)
  真实架构争论发生的地方。**用 for**：看别人怎么在评审里用这些词吵架，学语气与边界。
- [Jepsen 的 GitHub Issues](https://github.com/jepsen-io/jepsen)
  分布式正确性的高标准讨论现场。**用 for**：把一个「我们的系统是强一致的」的说法拆开看。
- [Hacker News 上 DDIA 相关讨论](https://hn.algolia.com/?q=designing+data-intensive+applications)
  每次版本更新、每次有人质疑书里某章过时，都会有一轮。**用 for**：判断某条论断的时效性。

## Gaps

- 缺少**中文**的系统设计评审社区。上面的社区基本在英文语境，中文侧只能找到零散的公众号文章。
- 缺少「书的框架 vs 你所在公司的真实架构」的对照案例。这条只能靠你把真实设计文档片段带进课里来补。
- 第 14 章（伦理与隐私）几乎没有可操作的工程材料，只有原则。若要落地，需要另找 GDPR / 数据最小化的工程实践。
- 书对「成本」讲得很少（跨可用区流量费、存储分层）。做真实架构决策时这是硬约束，课程只在需要处点名，不做完整覆盖。
