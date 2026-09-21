---
{"attributes":{"slug":"ultra-long-session-multi-branch-decision-summary"},"decision_anchor":null,"document_id":"research:ultra-long-session-multi-branch-decision-summary","kind":"research","links":[],"origin_anchors":[],"replaces":[],"status":"proposed","task_key":null,"title":"超长多分支会话按最终决策总结：技术方案","visibility":"private"}

---
# 超长多分支会话按最终决策总结：技术方案

- Scope: 通用技术方案（非特定产品绑定）
- Date: 2026-09-20
- Method: 四路并行调研（学术算法前沿 / 工业框架实践 / 系统管线设计 / 评测与边界异常）+ 自审挑战
- Source conversation: `conversation://8b98a02c-3a1d-4043-8b20-42e6682b6185`

---

## 1. 问题定义

一个超出模型上下文窗口（可能数十万至数百万 Token）的复杂会话，包含多个交织的旁路分支任务，每个分支经历若干次决策变动（提议、反驳、修改、推翻、重新确立）。目标：**按最终决策，总结该会话共有几个分支，以及每个分支的最终裁定内容与演变过程。**

### 核心困难

| 困难 | 说明 |
| :--- | :--- |
| **拓扑交错** | 主线任务与多个旁路在时间线上高度交织，不同分支的发言物理穿插 |
| **非单调决策演化** | 决策不是"提出即定案"，而是经历反复的"提案→争论→推翻→修正→终审"，早期方案常被废弃 |
| **超长程注意力失效** | 即便使用 128k/1M 窗口模型，也会遭遇 Lost-in-the-Middle、信念惯性（Belief Inertia）和近因偏差（Recency Bias） |
| **幽灵记忆与缝合幻觉** | 被推翻的方案在注意力机制下仍对生成施加"引力"，导致废弃草案被误判为定论，或不同分支内容被交叉缝合 |

### 朴素方案为什么必然失败

- **扁平 Map-Reduce**：跨块的辩驳和推翻被分离在不同 Chunk，Reduce 阶段面对相互矛盾的分段摘要产生缝合幻觉。
- **递归 Refine**：累积摘要逐渐达到窗口上限，早期确立的关键约束被挤出。严重近因偏差，且无法并行。
- **直接全量灌入长窗口模型**：注意力稀释、Token 成本爆炸、且 ROUGE 指标会错误奖励包含废弃决策的输出。

---

## 2. 核心范式结论

经四路调研与自审挑战后，真正站住脚的硬核结论为以下五条：

### 结论 1：倒序优先 + 正向定界的双向策略是最优范式（置信度：高）

**核心洞察**：倒序读取将困难的"信念修正"问题降维为简单的"信息检索"问题。

- 正序方案要求系统在看到方案 A 时"暂时相信 A"，然后在数十轮后看到 A 被推翻时"撤销信念"——这恰好是 LLM 最薄弱的能力。
- 倒序读取直接从确定性最高的终点切入，天然跳过 80% 的中间废弃噪音。系统一开始就知道最终答案，只需补齐参数和边界。
- **但纯倒序有四个陷阱**（见第 4 节），需正向溯源补齐。
- 本方案在 Token 成本、收敛速度与因果保真度上优于纯正序方案。

### 结论 2：最终判定必须由代码层状态机执行（置信度：高）

无论正序还是倒序，LLM 都会受信念惯性和近因偏差干扰。判断"谁推翻了谁""当前哪些决策有效"必须由确定性代码计算，而非仰赖大模型一次性推断。但"确定性"的定义要诚实——议题匹配（两条决策是否属于同一主题）仍需语义层参与。

### 结论 3：分支物理隔离是防跨支污染的必要条件（置信度：高）

在最终生成阶段，每个分支必须在独立的 Prompt 上下文中合成，否则跨分支注意力串扰不可避免。

### 结论 4：废弃决策过滤率（SDFR）是唯一不可妥协的质量红线（置信度：中高）

在所有评测指标中，SDFR（最终输出中不得包含已被推翻的决策）是最直观、最致命、最好量化的。其它指标可以迭代，这条必须 Day 1 满足。

### 结论 5：先做最简版本，验证后再加层（置信度：高）

四阶段全套流水线（SDRT 解缠 + JTMS 状态机 + 双时态图谱 + 分支隔离生成）是理论上界，不是起步架构。90% 的场景可用两遍扫描 + 定向检索覆盖。

---

## 3. 推荐实现方案：双向锚定回溯管线（Bidirectional Anchor-and-Grounding Pipeline）

本质上就是"先翻到最后看结论，结论里有看不懂的就往前翻，再扫一遍有没有遗漏的话题"——将人类做笔记的常识直觉形式化。

```
Pass 1 (倒序)：快速锁定候选决策锚点 (Candidate Anchors)
   ↓
Pass 2 (正向定向)：针对锚点做因果溯源、边界定界、代词消解
   ↓
Pass 3 (前序扫盲)：检查是否有遗漏的未决/悬挂分支
   ↓
输出：结构化最终决策报告
```

### Pass 1：倒序轻量扫描（快速定桩）

从会话尾部向前，以滑动窗口方式扫描。过滤无价值内容（工具输出、错误堆栈、冗长 JSON 返回值、thinking 块等）。

**执行目标**：提取"候选最终决策锚点（Candidate Anchor）"，而非"不可变决策"。

```python
@dataclass
class CandidateAnchor:
    topic: str              # e.g., "认证方式", "消息队列选型"
    tentative_choice: str   # e.g., "双 Token + Redis"
    anchor_turn_id: int     # 锚定的轮次
    confidence: float       # 初始置信度
    needs_grounding: bool   # 是否含代词/指代需要消解
    raw_quote: str          # 原文片段
```

**关键设计点**：
- 锚点进队列时标记为 `tentative`（待定界），而非 `frozen`（不可变）。
- 当发现某个决策含有代词指代（"按第二个方案办"）或条件前置（"如果……就……"），标记 `needs_grounding = True`。
- 一路向前读，遇到与已有锚点冲突的信息时不覆盖锚点，而是记录为"需要正向验证的候选冲突"。

### Pass 2：正向定向因果溯源（补齐边界与消解指代）

拿着 Pass 1 产出的锚点表，针对性地向历史轮次检索。不再全量遍历，而是定向提问：

| 溯源类型 | 问什么 | 解决什么问题 |
| :--- | :--- | :--- |
| **代词消解** | "Turn 490 提到的'第二个方案'定义在第几轮？具体参数？" | 避免锚点本身是"空指针" |
| **边界定界** | "关于 SQLite，最早提出时是否有限定范围/前置条件？" | 避免漏掉 Turn 12 的"仅限测试环境"这类 Scope 声明 |
| **推翻链建立** | "Kafka 推翻了谁？原因是什么？" | 生成"被否决的替代方案"记录 |
| **条件性甄别** | "Turn 450 的'切备用 4G 路由'是条件假设还是主架构决策？" | 防止把应急预案误判为主干决策 |

**实现方式**：
- 若原始会话存在结构化的 Turn 元数据（如 transcript.jsonl），可直接索引定位。
- 若为纯文本流，可使用 Embedding 向量检索，以锚点 topic 为 query 召回相关历史轮次。
- 对召回的片段，用 LLM 做窄幅度的信息抽取（不做"总结"，只抽事实），结果用于更新锚点的属性。

### Pass 3：前序分支补漏（悬挂分支审计）

对会话前 20%~30% 做一次极低成本的话题意图扫描，核对：
- 是否存在"提出过、但既不在最终锚点里、也没有显式推翻记录"的孤儿分支。
- 若有，标记为 `UNRESOLVED_ZOMBIE`，放入报告的《待办与遗留问题清单》。
- **不可**为其编造虚假的闭环结论（即不可出现"强迫闭环幻觉"）。

> **关于僵尸分支的诚实边界**：系统能检测到"这里有个悬挂的东西"，但正确归类（真的忘了 vs. 心照不宣认为不重要 vs. 线下再聊）可能需要人类判断。自动化三态分类不应过度自信。

### 代码层状态归约（Zero-LLM-Token Reduction）

Pass 1 和 Pass 2 产出的结构化锚点，汇入后端代码执行确定性归约：

```python
def reduce_anchors(anchors: List[CandidateAnchor]) -> List[FinalDecision]:
    """
    确定性状态机：按 topic 分组后，应用 supersede 链去重。
    注意：topic 分组的相似度判定仍需 Embedding 参与，非纯字符串匹配。
    """
    topic_groups = cluster_by_topic_embedding(anchors)  # 语义聚类
    finals = []
    for topic, group in topic_groups.items():
        # 按 turn_id 排序（越晚权重越高）
        sorted_group = sorted(group, key=lambda a: a.anchor_turn_id, reverse=True)
        # 取最新的非条件性、非代词空指针的锚点为最终决策
        for anchor in sorted_group:
            if anchor.confidence >= THRESHOLD and not anchor.is_conditional:
                finals.append(FinalDecision(
                    topic=topic,
                    decision=anchor.tentative_choice,
                    confirmed_at=anchor.anchor_turn_id,
                    superseded=[a for a in sorted_group if a != anchor],
                    scope=anchor.scope_constraints,  # Pass 2 补齐的边界
                ))
                break
    return finals
```

### Pass 4：分支物理隔离生成

每个分支分配独立的 Prompt 上下文进行结构化总结，互不串扰。每份分支报告包含：
- 分支名称与归属领域
- 最终生效决议（具体、明确、不含糊）
- 演变路径（从旧方案到新方案的演化原因）
- 被否决的替代方案及否决理由
- 未决问题（若有）

---

## 4. 纯倒序方案的四大陷阱与防御

倒序优先的核心威力在于剪枝。但若将倒序读到的事实设为"不可变（Freeze）"，将遭遇以下系统性崩溃：

### 4.1 作用域前置截断（Scope Loss）

- **场景**：Turn 12 声明"本次仅针对测试环境"，Turn 480 敲定"数据库用 SQLite"。倒序先锁定 SQLite 为不可变事实后，到达 Turn 12 时作用域边界被忽略。
- **防御**：锚点标记为 `tentative`，Pass 2 做定向边界检索。

### 4.2 逆向代词空指针（Backward Coreference Null-Pointer）

- **场景**：Turn 490 说"按你说的第二个来"，Turn 492 说"听老李的"。倒序先拿到的决策实体本身是个代词。
- **防御**：Pass 1 标记 `needs_grounding = True`，Pass 2 做指代消解展开。

### 4.3 条件假说误判（Counterfactual Bleeding）

- **场景**：Turn 450 说"如果机房断网就切 4G"（条件假说），Turn 430 定了"双路万兆光纤专线"（真正主决策）。倒序先看到 450 可能将 4G 误判为主架构。
- **防御**：事件抽取时区分 `is_conditional` 标志（检测"如果/万一/假设"等条件信号词）。

### 4.4 悬挂分支完全失明（Zombie Branch Blindness）

- **场景**：会话前半段深入讨论了"国际化多语言"，后被打断后再未提及。倒序读时尾部毫无痕迹，该分支被彻底遗漏。
- **防御**：Pass 3 前序补漏扫描。

---

## 5. 输出数据结构

```json
{
  "session_metadata": {
    "session_id": "string",
    "total_turns": "integer",
    "detected_branch_count": "integer"
  },
  "branches": [
    {
      "branch_id": "string",
      "canonical_name": "string",
      "status": "RESOLVED_FINAL | UNRESOLVED_ZOMBIE | ABANDONED",
      "final_decision": {
        "summary": "string (具体、明确的最终裁定陈述)",
        "specifications": ["string"],
        "scope_constraints": ["string (作用域限制，如'仅限测试环境')"],
        "confidence_score": "number (0-1)",
        "confirmed_at_turn": "integer",
        "confirmed_by": "string"
      },
      "evolution_history": [
        {
          "turn_id": "integer",
          "speaker": "string",
          "action": "PROPOSE | MODIFY | SUPERSEDE | CONFIRM | REJECT | DEFER",
          "content": "string",
          "rationale": "string",
          "supersedes_turn": "integer | null",
          "evidence_quote": "string (原文引用)"
        }
      ],
      "rejected_alternatives": [
        {
          "proposal_content": "string",
          "rejected_at_turn": "integer",
          "rejection_reason": "string"
        }
      ],
      "dependencies": ["branch_id"]
    }
  ],
  "cross_branch_dependency_graph": [
    {
      "source_branch": "string",
      "target_branch": "string",
      "relation": "BLOCKS | REQUIRES | CONFLICTS_WITH"
    }
  ],
  "unresolved_items": [
    {
      "topic": "string",
      "last_mentioned_turn": "integer",
      "reason_unresolved": "string"
    }
  ]
}
```

---

## 6. 评测指标

严禁单独使用 ROUGE/BLEU 评测决策抽取任务。必须建立多维看板：

| 层级 | 指标 | 说明 |
| :--- | :--- | :--- |
| **拓扑基座** | Shen-F1, Variation of Information (VI) | 分支识别聚类精度，惩罚过切分/欠切分 |
| **决策核心** | Final Decision Recall (FDR) / Precision (FDP) | 最终决策的召回与精确 |
| **安全防线** | Superseded Decision Filtering Rate (SDFR) | 废弃决策在输出中被彻底剔除的比例。**必须接近 100%** |
| **因果对齐** | Rationale Grounding Accuracy | 决策理由是否来自正确分支的正确上下文 |
| **抗幻觉** | No-Zombie-Decision Rate (NZDR) | 输出中不含已废弃方案的样本比例 |

**关键注意**：传统 ROUGE 会因词汇重合度反而奖励包含废弃决策的幻觉输出。

---

## 7. 实施路线

| 阶段 | 交付物 | 建议 |
| :--- | :--- | :--- |
| **V0.1 极简验证** | 取尾部 15-20% 内容 + LLM 提取决策 + 对不确定条目做定向 RAG 检索 + 前 30% 粗扫漏分支 | 以 1/10 复杂度覆盖 80%+ 场景 |
| **V0.5 双向管线** | 完整 Pass 1-3 实现 + 代码层状态归约 + 分支隔离生成 | 覆盖代词消解、边界定界、级联失效 |
| **V1.0 生产级** | 滑动窗口流式处理 + Prompt Caching 优化 + 对抗性评测集 + SDFR 监控 | 适用于百万 Token 级超长会话 |

---

## 8. 被降级或推翻的早期结论

以下结论在自审挑战中被修正或降级：

| 早期结论 | 修正判断 | 原因 |
| :--- | :--- | :--- |
| SDRT 篇章理论 / JTMS 真值维护系统 | **过早优化**，不应作为首选实现路径 | 工程落地复杂度过高，V0.1-V0.5 阶段不需要 |
| 严格 Exact Quote 子串匹配 | **过于脆弱**，需替换为模糊匹配 + 置信度阈值 | LLM 天然会轻微改写引用，严格匹配导致大量合法事件被误杀 |
| 六分类离散 Action 体系 | **过于理想化**，需增加连续置信度维度 | 真实对话的决策光谱是连续的，"嗯这个倒也行吧"无法干净归类 |
| 僵尸分支自动化三态归类 | **可检测但无法完全自动化分类** | "真的忘了" vs "心照不宣" vs "线下再聊"在文本层面无法区分 |
| "确定性状态机零 LLM Token" | **措辞误导** | 议题匹配（两条决策是否同一主题）仍需语义层参与 |

---

## 9. 成本估算参考

对百万 Token 的会话执行完整四阶段管线：
- 输入端总处理量约 2-4 倍原文（重叠窗口 + 多遍扫描），约 200-400 万 Token LLM 调用量
- 单次成本约 $30-$100+

对同一会话执行 V0.1 极简方案：
- 仅处理尾部 15-20% + 定向检索，约 30-50 万 Token
- 单次成本约 $3-$10

---

## 10. 参考文献与工具

- 学术基准：Ubuntu IRC (Kummerfeld et al. 2019), Molweni (Li et al. 2020), QMSum (Zhong et al. 2021), MeetingBank (Hu et al. 2023), Supersede (2026), LongMemEval
- 工业框架：LangGraph Checkpointer 树, Letta/MemGPT 三层内存, AutoGen 0.4 任务隔离, Zep Graphiti 双时态图谱
- 理论基石：SDRT (Asher & Lascarides 2003), AGM 信念修正 (1985), JTMS (Doyle 1979), RAPTOR (ICLR 2024), Graph-of-Thoughts (2024)
