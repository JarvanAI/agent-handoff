# 同行评审报告：SD-Handoff-Bench

**审稿人视角**：LLM-based Software Engineering / Multi-Agent Systems / Context Compaction  
**评审日期**：2026-09-22  
**总体评价**：**强接收（Strong Accept）方向，但需修订后重新审视若干关键设计决策**

---

## 一、总体印象

SD-Handoff-Bench 瞄准了一个真实且尚无系统性评测基准的痛点——长会话 Coding Agent 的决策蒸馏与跨 Agent 交接质量。这是一个**高价值的空白地带**：SWE-Bench 评测的是"从零解题"，而本基准评测的是"从断点续写"，二者构成互补。动机清晰、指标设计有学术严谨性、沙盒闭环验证避免了 LLM-as-a-judge 的自我偏见。

但在深入审视后，我识别出以下 **结构性问题和改进空间**。

---

## 二、指标体系评审

### 2.1 FDR（终局决策召回率）

**优点**：三元组 `(Entity, Attribute, FinalValue)` 形式化程度高，可机器化评判。

**问题与建议**：

1. **Ground Truth 构建的可重复性危机**。EEBS（Explicit Engineering Belief State）的标注者间一致性（Inter-Annotator Agreement）未被提及。工程决策的粒度天然模糊——"选择 PostgreSQL" 和 "选择 PostgreSQL 16 且启用 pgvector 扩展" 是同一个决策还是两个？建议：
   - 引入 **EEBS 标注规范**，明确实体-属性的层级粒度（architectural / component / config 三级），并报告 Cohen's κ ≥ 0.75 作为数据集发布的准入门槛。
   - 考虑同时报告 **宽松匹配 FDR**（实体+属性匹配即可）和 **严格匹配 FDR**（值也必须精确匹配），两个变体揭示的问题不同。

2. **FDR 缺乏对"决策间依赖关系"的建模**。现实中决策常成链：选了 ORM A → 必须用 Migration 工具 B → 进而约束了 CI 配置 C。单独的三元组召回率无法区分"丢了一个孤立叶子决策"和"丢了一个根因决策导致下游三个决策全部失效"。建议：
   - 引入 **加权 FDR（wFDR）**，根据决策在因果依赖图中的扇出度赋权。丢失一个被 5 个下游决策依赖的根节点，比丢失一个叶节点严重 5 倍。

### 2.2 NKR（负面知识保留率）与 SHR（状态伪造污染率）

**这是本方案最有洞察力的设计**，解耦了"应保留的失败经验"与"应被清除的过期状态"。学术贡献清晰。

**问题与建议**：

1. **NKR 的"足够保留"边界模糊**。一个死胡同可以被描述为 "方案 A 行不通"（一句话），也可以被描述为 "方案 A 在依赖 X ≥ 3.0 时因 ABI 不兼容导致 segfault，具体堆栈见 …"（详细根因）。只报告 Recall 不够，需要同时度量 **信息密度**。建议：
   - 为 NKR 添加一个伴随指标 **NKR-Depth**：对于每个被召回的负面知识条目，评估其是否保留了（a）失败事实、（b）根因分析、（c）重现条件三个层次。可以 0/1/2/3 打分后取平均。

2. **SHR "必须为 0%" 的工程可行性**。作为论文中的理想声明可以，但作为基准的实际评分机制需要考虑边界情况：
   - 某些决策可能处于**半推翻状态**（"我们暂时回滚了方案 A，但保留了它的接口适配层以便后续重新启用"）。这在真实 PR 中非常常见。
   - 建议区分 **硬 SHR**（将明确否决的决策标记为 Active）和 **软 SHR**（对暂时搁置/待定决策的状态标注不精确），分别报告。硬 SHR 要求 0%，软 SHR 允许一定容忍度。

### 2.3 TRA（截断穿透还原精度）

**问题**：

1. **TRA 的评测前提假设了 Agent 有本地文件系统访问权**。但在某些 A2A 场景中（尤其是跨云/跨沙盒交接），下游 Agent B 可能根本无法访问 Agent A 的本地环境。此时 TRA 退化为"信封内嵌信息的完备性"而非"穿透能力"。建议：
   - 将 TRA 拆分为 **TRA-local**（Agent 可访问原始环境）和 **TRA-detached**（Agent 仅凭信封内容还原），分别评测。后者对 session-distill 的信封设计质量要求更高。

2. **截断类型需要更细致的分类学**。`[... 400 lines truncated ...]` 只是一种截断模式。真实场景中还有：
   - 二进制 blob 截断（`Binary file differs`）
   - 编码损坏（UTF-8 fallback 导致关键参数变成 `???`）
   - Pager 分页但 Agent 只看了第一页
   - CI 日志的 job-level 折叠
   
   建议数据集明确覆盖至少 3 种截断子类型，并分别报告 TRA。

### 2.4 A2A Handoff 指标组

**整体设计扎实**，但有以下盲区：

1. **SFSMA 存在"虚假高效"陷阱**。一个激进但鲁莽的 Agent B 可能在第 1 步就直接 `git commit`——SFSMA = 1，但后果是灾难性的。SFSMA 单独使用有误导性。建议：
   - SFSMA 必须与 TCSR 联合报告，或直接定义为 **Effective SFSMA（eSFSMA）**：仅统计最终成功通过测试的 run 的 SFSMA。

2. **ECR 的"相同错误"定义需要形式化**。两个错误是"相同"的判据是什么？
   - 相同的 Exception 类型？（太宽松——`ValueError` 几乎覆盖一切）
   - 相同的 Exception 类型 + 相同的触发代码路径？（较合理）
   - 相同的 stack trace 前 N 帧？（较严格但可自动化）
   
   建议明确定义匹配规则，并在论文中进行消融实验比较不同粒度定义下 ECR 的变化。

3. **HDS 综合指标的权重设定缺乏理论支撑**。Token 成本、SFSMA、ECR 三者量纲不同，如何归一化和加权？建议：
   - 要么给出一个**参数化公式**并开放权重让社区调参（如 `HDS = α·norm(TokenCost) + β·norm(SFSMA) + γ·norm(ECR)`），在论文中用帕累托分析展示不同权重组合下各方法的排序稳定性；
   - 要么放弃 HDS 这个单一数字，改为 **Handoff 雷达图**（多轴可视化），避免被批评"指标设计者的偏见决定了排名"。

4. **缺失一个关键指标：Context Efficiency Ratio（CER）**。
   - 定义：`CER = TCSR / (交接载荷 Token 数 / Agent B 上下文窗口大小)`。
   - 动机：Session-Distill 的核心价值主张是"用更少的 Token 传递更多有效信息"。CER 直接度量信息密度效率——在相同的窗口占用比下，谁能带来更高的任务完成率。这是说服工程社区采用的**杀手级指标**。

---

## 三、实验设计评审

### 3.1 对比基线的充分性

当前 4 种载荷设计（Raw Full History / Sliding Pager / Naive MapReduce / Session-Distill）**覆盖了最常见的工业实践，但缺少两个重要基线**：

1. **⑤ Structured Summarization with CoT（结构化 CoT 摘要）**：让同一个 LLM 用 Chain-of-Thought 生成结构化 JSON 摘要（不含 FSM 剪枝机制）。这是消融 Session-Distill 中 FSM 机制贡献的关键基线——如果不加这个基线，审稿人会问："也许只要让 LLM 生成 JSON 就够了，你的双向定桩和 FSM 到底贡献了多少？"

2. **⑥ Human-Written Handoff Note（人类工程师手写交接文档）**：这是**真正的性能天花板参照**。如果 Session-Distill 在某些场景能接近甚至超过人类手写交接文档，这将是最有说服力的实验结果。虽然标注成本高，但哪怕只在 20 个样本上做也值得。

### 3.2 Agent B 的选择与控制

**这是实验设计中最大的潜在混淆变量**。

1. **Agent B 的能力差异会压倒载荷差异**。如果 Agent B 用的是 GPT-4o 和 Claude Opus 4，两者自身的代码能力差异可能远大于载荷格式带来的差异。建议：
   - **固定 Agent B 的底座模型**，仅变化载荷。在主实验中使用至少 2 个不同模型分别跑一遍，报告交叉结果。
   - 明确报告 Agent B 的 system prompt 是否在不同载荷条件下完全一致（除了载荷注入位置）。

2. **Agent B 的工具权限必须标准化**。如果 Agent B 在某些载荷条件下能 `grep` 到更多上下文（因为 Raw Full History 虽然爆窗但被分段喂入），但在 Session-Distill 条件下因为信封精炼而无法触发某些搜索——这会引入系统偏差。建议：
   - 在沙盒中 **标准化 Agent B 的可用工具集和超时限制**，并作为基准配置发布。

### 3.3 沙盒执行验证的鲁棒性

**沙盒闭环验证是本方案的一大亮点**，避免了 LLM-as-a-judge 的循环偏见。但：

1. **测试断言本身的质量决定了 TCSR 的上限**。如果测试用例只覆盖了 happy path 而遗漏了 edge case，TCSR 会虚高。建议：
   - 为每个任务标注**测试覆盖度元数据**（行覆盖率、分支覆盖率），并分析 TCSR 与测试覆盖度的相关性。
   - 对于安全合规类场景，补充 **property-based testing** 或 fuzzing 层的断言。

2. **非确定性问题**。Agent B 的行为具有随机性（temperature > 0）。建议：
   - 每个 (任务, 载荷) 组合至少跑 **N ≥ 5 次**，报告均值 ± 标准差以及 pass@k 指标。
   - 明确控制并报告 Agent B 的 temperature、top_p 等采样参数。

---

## 四、数据集构建评审

### 4.1 `SD-Handoff-100` 的规模与统计效力

**100 个样本可能不够**，尤其是在 5 个场景 × 4 种载荷 = 20 个 cell 的实验矩阵下，每个 cell 只有 ~5 个样本，统计显著性堪忧。

建议：
- 若资源允许，扩展到 **SD-Handoff-250** 或以上，每个场景至少 30 个样本以满足中心极限定理的经验阈值。
- 若资源有限，考虑使用 **bootstrap 置信区间** 和 **配对检验**（Wilcoxon signed-rank test）来弥补小样本的统计不足，并在论文中明确声明。

### 4.2 受控因果对抗注入的生态效度

**"注入死胡同"是一把双刃剑**。优点是控制力强，缺点是可能产生分布偏移：人工注入的死胡同与真实工程中自然涌现的死胡同在形态上可能不同（真实死胡同往往更隐蔽、更渐进）。

建议：
- 数据集中**至少 30% 的样本完全来自真实 PR/Issue 轨迹的无注入录制**（organic subset），其余 70% 允许注入。
- 在论文中分别报告 organic vs. injected 子集上的指标差异，作为生态效度的证据。

### 4.3 场景覆盖的盲区

当前 5 大场景遗漏了几个高频真实场景：

| 遗漏场景 | 为什么重要 |
|---|---|
| **跨语言/跨栈迁移**（Python 后端 + TypeScript 前端联调） | 决策实体的命名空间跨语言时，实体消歧难度骤升 |
| **配置漂移与环境差异**（dev vs. staging vs. prod 的配置不一致） | 截断穿透和状态伪造在此场景最容易出错 |
| **并发/竞态调试** | 日志交织程度远高于顺序执行，对 FSM 的鲁棒性是极端测试 |

建议至少补充其中 1-2 个场景，或在 Future Work 中明确讨论。

---

## 五、开源传播与行业标准视角

### 5.1 可复现性工程

要让基准成为社区标准（如 SWE-Bench 之于 Agent Coding），**可复现性**是第一公民：

1. **Docker 镜像即基准**：发布一个 `sd-handoff-bench:v1` Docker 镜像，内含所有沙盒环境、测试断言、评分脚本。用户只需 `docker run` + 挂载自己的 Agent 交接载荷即可获得评分。**这是最关键的工程交付物**。

2. **评分脚本确定性**：FDR、NKR、SHR 的自动评分如果依赖 LLM 做语义匹配，则需要：
   - 固定 LLM 版本 + seed
   - 发布一个纯规则匹配的 fallback 评分器（基于字符串/正则/AST diff），作为 LLM 评分器的 calibration anchor

3. **排行榜（Leaderboard）**：参考 SWE-Bench 的做法，提供一个 GitHub Pages 排行榜，接受社区提交。但要注意：
   - 排行榜上必须同时展示 **多个指标而非单一 HDS**，避免 Goodhart 效应
   - 对每个提交要求公开交接载荷（anonymized），以便社区审查

### 5.2 杀手级特性建议

以下特性可以显著提升基准的学术影响力和工业采纳度：

1. **🔥 Live Handoff Replay（实时交接回放）**：
   提供一个 Web UI，可以可视化地回放 Agent A 的探索轨迹（带 FSM 状态转移动画），然后展示不同载荷下 Agent B 的接管行为对比。这将成为**论文 Demo 和会议 Talk 的核心卖点**。

2. **🔥 Plug-and-Play Agent Adapter（即插即用 Agent 适配器）**：
   定义一个标准的 Agent 接口协议（输入：交接信封 + 沙盒端点 → 输出：动作序列 + 最终代码 diff），使得社区可以轻松接入任何 Agent（Claude Code, Cursor, OpenHands 等）作为 Agent B 进行评测。参考 SWE-Bench 的 `run_evaluation.py` 设计。

3. **🔥 Difficulty Calibration via Human Baseline（人类基线难度标定）**：
   对每个任务，让 1-2 名人类工程师在相同的断点状态和交接信息下尝试完成后续任务，记录时间和成功率。这提供了**绝对难度标定**——不仅能说"方法 A 比方法 B 好 10%"，还能说"方法 A 达到了人类表现的 85%"。

4. **Session-Distill 信封的开放格式标准（Envelope Schema）**：
   将 Session-Distill 的输出格式定义为一个 JSON Schema / Protobuf IDL，提交给 A2A Protocol 或 MCP 社区作为 RFC。这将基准从"评测工具"升级为"协议标准提案"，传播力量级不同。

### 5.3 论文定位建议

- **一级会议投稿目标**：ICSE 2027 / FSE 2027 的 Benchmark Track 是最合适的 venue。备选 NeurIPS 2027 Datasets & Benchmarks Track（强调与 ML 社区的关联）。
- **标题建议**：当前 "SD-Handoff-Bench" 偏工具名。学术标题建议强调问题和洞察，例如：
  > *"Beyond Summarization: Benchmarking Decision-State Fidelity and Agent-to-Agent Handoff in Long-Horizon Coding Sessions"*

---

## 六、具体可落地的修改清单

| # | 优先级 | 修改项 | 工作量估计 |
|---|--------|--------|-----------|
| 1 | **P0** | 为 FDR 增加决策因果依赖图加权（wFDR） | 2-3 天（标注 + 实现） |
| 2 | **P0** | 为 NKR 增加深度子指标（NKR-Depth: 事实/根因/重现条件） | 1-2 天 |
| 3 | **P0** | SHR 区分硬 SHR / 软 SHR，只对硬 SHR 要求零容忍 | 1 天 |
| 4 | **P0** | 增加对比基线 ⑤ Structured CoT JSON（消融 FSM 机制贡献） | 3-5 天（实验） |
| 5 | **P0** | 每个 (任务, 载荷) 组合至少 5 次重复实验，报告均值±标准差 | 计算资源需求 |
| 6 | **P1** | 增加 CER（Context Efficiency Ratio）指标 | 0.5 天 |
| 7 | **P1** | SFSMA → eSFSMA（仅统计成功 run） | 0.5 天 |
| 8 | **P1** | ECR 的"相同错误"形式化定义（Exception + 代码路径匹配） | 1 天 |
| 9 | **P1** | HDS 改为开放参数化公式 + 帕累托分析，或改为雷达图 | 2 天 |
| 10 | **P1** | TRA 拆分为 TRA-local / TRA-detached | 1 天 |
| 11 | **P1** | 数据集扩展到 ≥ 200 样本，或使用 bootstrap 置信区间 | 视资源 |
| 12 | **P1** | 数据集中 ≥ 30% organic（无注入）样本 | 3-5 天（数据收集） |
| 13 | **P2** | 增加人类工程师手写交接基线（≥ 20 样本） | 5-10 天（标注） |
| 14 | **P2** | 发布 Docker 一键评测镜像 | 5-7 天 |
| 15 | **P2** | Live Handoff Replay Web UI | 2-3 周 |
| 16 | **P2** | 信封格式提交为 A2A/MCP 社区 RFC | 2-3 周 |
| 17 | **P2** | 补充跨语言/配置漂移场景 | 3-5 天/场景 |

---

## 七、总结性评价

**SD-Handoff-Bench 填补了一个重要的基准空白**。其核心洞察——将"决策状态保真度"与"避坑知识保留"解耦评测——具有学术原创性。A2A Handoff 的沙盒闭环验证设计避免了当前 LLM 评测中 LLM-as-a-judge 的自引用偏见，工程上站得住脚。

**最需要优先解决的三个问题**：
1. 消融基线不足（缺少 Structured CoT JSON 基线，无法证明 FSM 机制的增量贡献）
2. 统计效力不足（100 样本 × 5 场景 × 4 载荷，每个 cell 样本过少）
3. 复合指标 HDS 的权重设定缺乏理论支撑

解决这三个问题后，本基准完全有实力成为 **Coding Agent 长会话交接领域的 SWE-Bench 级别标杆**。

---

*以上为完整同行评审意见，欢迎进一步讨论任何具体条目。*
