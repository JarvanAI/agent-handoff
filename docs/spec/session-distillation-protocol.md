---
{"attributes":{"slug":"session-distillation-protocol"},"decision_anchor":null,"document_id":"spec:session-distillation-protocol","kind":"spec","links":[],"origin_anchors":["session:e6129792-626d-48e2-bb79-be9d34b32829"],"replaces":[],"status":"accepted","task_key":null,"title":"会话蒸馏协议与数据格式规格书 (UnifiedTurn, DecisionDAG, A2AHandoffEnvelope)","visibility":"private"}

---

# 会话蒸馏协议与数据格式规格书 (Session Distillation Protocol Specification)

- **协议版本**：v2.0.0
- **适用范围**：Arborist-Orca 仓内工程规范、多 Agent 会话蒸馏流水线、A2A 跨智能体交接
- **关联实现**：`docs/session-distillation-architecture.md`
- **生命周期契约**：`.docs/sendbox/_handoff-config.yaml`

---

## 一、协议概述与设计准则

在 Arborist-Orca (AO) 体系中，会话蒸馏（Session Distillation）是将人类与 Agent 产生的长交互流水线（通常数百至上千轮）提炼为机器强类型契约与人类防御手册的核心协议。

为了确保跨异构 Agent（Claude Code, Antigravity, OpenHands, SWE-agent 等）之间的确定性与互操作性，本协议定义三个标准化的核心数据模型：
1. **`UnifiedTurn`**：消除底层异构日志格式差异的单轮交互归一化模型，支持 Penetrator 穿透状态感知；
2. **`DecisionDAG`**：表示长会话中技术决策演化、废案更迭与冲突覆写的有向无环图；
3. **`A2AHandoffEnvelope`**：符合 AO Sendbox 规范的超轻量机器交接信封，承载 Nonce、已裁定决策清单与路由策略，满足 R1 长度防御规则。

### 核心设计原则
- **确定性与无损性 (Lossless Determinism)**：对于关键代码、数学公式、配置路径，提取过程必须字字有据（Grounded），严禁生成式幻觉；
- **状态覆写单调性 (Latest-Wins Monotonicity)**：同一决策主题下的多个提案，严格以后发确认为唯一生效态，废案必须被标记并在状态图上剪枝；
- **低 Token 机器友好 (Token-Frugal Handshake)**：下游接收 Agent 的交接信封必须控制在 1.5k Token 以内，长正文通过文件指针解耦。

---

## 二、`UnifiedTurn` 数据格式与 JSON Schema

`UnifiedTurn` 是物理降噪与 Penetrator 穿透后的基础原子单位。

### 2.1 字段语义说明

| 字段名 | 类型 | 必需 | 说明 |
| :--- | :--- | :--- | :--- |
| `turn_id` | `string` | 是 | 唯一轮次标识符，格式如 `<session_id>-step-<step_index>`。 |
| `session_id` | `string` | 是 | 归属的原始会话 ID。 |
| `step_index` | `integer` | 是 | 原始时序流水中的单调递增步数索引（0-indexed 或 1-indexed）。 |
| `role` | `string` | 是 | 枚举值：`"user"`, `"agent"`, `"system"`, `"tool"`。 |
| `content` | `string` | 是 | 纯文本正文。若经过穿透，必须为穿透还原后的无损全量文本。 |
| `provenance` | `string` | 是 | 消息来源分类：`"user_human"`, `"user_unknown"`, `"agent_public"`, `"agent_internal_thinking"`, `"tool_execution"`, `"injected_system"`。 |
| `timestamp` | `string` | 否 | ISO 8601 格式时间戳（UTC）。 |
| `is_truncated` | `boolean` | 是 | 标记底层日志中是否曾出现截断（如命中 `truncated_fields`）。 |
| `penetrated` | `boolean` | 是 | 标记是否已通过 Penetrator 从底层全量存储无损还原。 |
| `tool_calls_summary` | `array` | 否 | 简要记录本轮产生的工具调用名称（不含大体积 payload）。 |
| `metadata` | `object` | 否 | 平台特定的补充上下文（如 raw_type、model_name 等）。 |

### 2.2 JSON Schema 规范 (Draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://arborist-orca.dev/schemas/distill/unified-turn.json",
  "title": "UnifiedTurn",
  "description": "Normalized single interaction turn across heterogeneous Agent platforms.",
  "type": "object",
  "required": [
    "turn_id",
    "session_id",
    "step_index",
    "role",
    "content",
    "provenance",
    "is_truncated",
    "penetrated"
  ],
  "properties": {
    "turn_id": {
      "type": "string",
      "pattern": "^[a-zA-Z0-9_-]+-step-[0-9]+$"
    },
    "session_id": {
      "type": "string",
      "minLength": 1
    },
    "step_index": {
      "type": "integer",
      "minimum": 0
    },
    "role": {
      "type": "string",
      "enum": ["user", "agent", "system", "tool"]
    },
    "content": {
      "type": "string",
      "description": "Full extracted textual content, guaranteed lossless after penetration."
    },
    "provenance": {
      "type": "string",
      "enum": [
        "user_human",
        "user_unknown",
        "agent_public",
        "agent_internal_thinking",
        "tool_execution",
        "injected_system"
      ]
    },
    "timestamp": {
      "type": "string",
      "format": "date-time"
    },
    "is_truncated": {
      "type": "boolean",
      "description": "Whether the raw source row had truncated fields."
    },
    "penetrated": {
      "type": "boolean",
      "description": "True if full content was recovered from deep storage via Penetrator."
    },
    "tool_calls_summary": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "metadata": {
      "type": "object",
      "additionalProperties": true
    }
  },
  "additionalProperties": false
}
```

---

## 三、`DecisionDAG` 数据格式与 JSON Schema

`DecisionDAG` 记录从多轮对话中抽取的架构决策演化图，是状态机剪枝（Latest-Wins）与因果溯源的计算依据。

### 3.1 字段语义说明

- **`DecisionNode`（决策节点）**：
  - `node_id`：全局唯一 ID，如 `decision-sparse-engine`；
  - `topic`：所属技术主题（如 `sparse_retrieval_engine`, `extraction_decision_model`）；
  - `state`：节点状态，枚举值：
    - `PROPOSED`：早期探讨提出，尚未形成最终结论；
    - `CONFIRMED`：最终被人类或主导 Agent 确认生效；
    - `SUPERSEDED`：已被更晚步数的定案推翻废弃（废案）；
    - `REJECTED`：被明确否决且无直接替代；
  - `confirmed_at_step`：最终裁定的 step 编号；
  - `supersedes`：本节点推翻的旧决策节点 ID 列表；
  - `grounded_quote`：原文精确引用子串，用于事后零幻觉审计；
  - `resolved_pronouns`：代词消歧记录表（记录如“这个配合”到底指向哪个技术组件）。
- **`DecisionEdge`（关系边）**：
  - `from_node` $\to$ `to_node`；
  - `relation`：`"SUPERSEDES"`（覆写推翻）、`"DERIVES_FROM"`（推导依赖）、`"CONSTRAINS"`（硬性约束）。

### 3.2 JSON Schema 规范 (Draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://arborist-orca.dev/schemas/distill/decision-dag.json",
  "title": "DecisionDAG",
  "description": "Directed Acyclic Graph representing decision evolution, superseding chains, and conflict resolution in agent sessions.",
  "type": "object",
  "required": [
    "session_id",
    "algorithm",
    "nodes",
    "edges",
    "unresolved_items"
  ],
  "properties": {
    "session_id": {
      "type": "string"
    },
    "algorithm": {
      "type": "string",
      "enum": ["Bidirectional Anchor-and-Grounding Pipeline", "Custom State Machine"]
    },
    "nodes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "node_id",
          "topic",
          "state",
          "proposed_at_step",
          "decision_text"
        ],
        "properties": {
          "node_id": { "type": "string" },
          "topic": { "type": "string" },
          "subtopic": { "type": "string" },
          "state": {
            "type": "string",
            "enum": ["PROPOSED", "CONFIRMED", "SUPERSEDED", "REJECTED"]
          },
          "proposed_at_step": { "type": "integer" },
          "confirmed_at_step": { "type": ["integer", "null"] },
          "decision_text": { "type": "string" },
          "supersedes": {
            "type": "array",
            "items": { "type": "string" }
          },
          "grounded_quote": { "type": ["string", "null"] },
          "pronouns_resolved": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["pronoun", "referent", "source_step"],
              "properties": {
                "pronoun": { "type": "string" },
                "referent": { "type": "string" },
                "source_step": { "type": "integer" }
              }
            }
          },
          "scope_constraints": { "type": ["string", "null"] },
          "engineering_tradeoff": { "type": ["string", "null"] }
        },
        "additionalProperties": false
      }
    },
    "edges": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["from_node", "to_node", "relation"],
        "properties": {
          "from_node": { "type": "string" },
          "to_node": { "type": "string" },
          "relation": {
            "type": "string",
            "enum": ["SUPERSEDES", "DERIVES_FROM", "CONSTRAINS", "CONFLICTS_WITH"]
          }
        },
        "additionalProperties": false
      }
    },
    "unresolved_items": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Topics left unclosed or interrupted at session termination."
    },
    "document_debts": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Known divergences between confirmed decisions and existing checked-in documentation."
    }
  },
  "additionalProperties": false
}
```

---

## 四、`A2AHandoffEnvelope` 规范 (与 AO Sendbox 兼容)

`A2AHandoffEnvelope` 是专为 Multi-Agent 协作网络中下游接收端设计的机器可读信封。它必须完全兼容 Arborist-Orca 的仓内配置 `.docs/sendbox/_handoff-config.yaml`。

### 4.1 协议合规约束 (AO Sendbox Rules)

1. **存储物理路径**：  
   `.docs/sendbox/toAgent/<canonical-agent-name>/YYYYMMDD-from-<sender>-handoff[-<topic>].md`，根入口保留 `handoff.md`；
2. **长报告规避规则（R1 铁律）**：  
   信封正文物理行数**严禁超过 20 行**，总字符数**严禁超过 1,200 字符**。超限内容必须作为独立文件写入 `.docs/guides/` 或任务 `evidence`，信封正文仅允许存放：
   - 核心任务结论；
   - 决策指纹与 Nonce；
   - 外部交付物绝对路径。
3. **Frontmatter 格式**：  
   严格采用 Arborist 标准 YAML Frontmatter，禁止混入非标 JSON 单行元数据。

### 4.2 信封结构示例

以下为会话 `e6129792-626d-48e2-bb79-be9d34b32829` 蒸馏后生成的标准交接信封：

```markdown
---
recipients:
  - role: implementer
    purpose: consume_distilled_decisions
    lifecycle: task
created: 2026-09-22T00:50:00Z
created_in: headless-6768
task: 0908-resume
recipient_brand: codex
route_policy: ao-codex-fix-execution
on_lifecycle_end: notify_supervisor
lifecycle_executor: orca
---

# A2A Handoff Envelope: Session Distillation State

- **Handshake Nonce**: `nonce-distill-e61297-20260922-01`
- **Source Session**: `e6129792-626d-48e2-bb79-be9d34b32829`
- **Source SHA256**: `d7f1b2c4e5...` (956 raw turns -> 140 clean turns -> 50 core decisions)
- **Token Compression**: 2.1M raw tokens -> 1.4k envelope tokens (99.93% reduction)

### Active Grounded Decisions (Confirmed Only)
1. `Extraction Model`: Schema-constrained Decision Model (Step 898 confirmed; Jev strictly pruned).
2. `Sparse Retrieval`: PostgreSQL Exact Keyword + Semantic Embedding lightweight Hybrid (Step 951 confirmed; ES strictly prohibited).
3. `Extraction Confidence Formula`: $Score = 0.6 P_{model} + 0.4 CosineSim$, threshold 0.70 to Uncategorized (Step 955 confirmed via Penetrator).
4. `Architecture Narrative`: Supervisor hierarchical orchestration + PTY nonces (Step 543/554 confirmed; Swarm prohibited).

### Artifact References (Zero In-Context Bloat)
- Human Playbook: `/home/shenzhou/Codes/Arborist-Orca/.docs/guides/赵晟-面试项目逐行应答与防御手册.md`
- Decision DAG Audit: `/home/shenzhou/Codes/Arborist-Orca/.docs/research/algorithm_benchmark_audit_e6129792.json`
- Task Spec: `/home/shenzhou/Codes/Arborist-Orca/docs/task-specification.md`
```

### 4.3 `A2AHandoffEnvelope` 字段规格定义

```yaml
# A2AHandoffEnvelope Data Contract
envelope_version: "2.0.0"
handshake:
  sender_agent: string       # 发送方 Canonical Agent 标识 (e.g. ao-rootorc, distill-daemon)
  recipient_agent: string    # 接收方 Canonical Agent 标识 (e.g. ra-resume-suborc)
  authority: string          # 运行权威运行时 (e.g. headless-6768)
  environment: string        # 环境标识 (e.g. headless-6768, staging)
  nonce: string              # 防重放与阶段绑定的唯一 Nonce
  epoch_timestamp: string    # ISO 8601 生成时间戳

distilled_state:
  source_session_id: string  # 原始源会话 ID
  source_sha256: string      # 原始日志内容 SHA256 校验和（检测 Source Drift）
  compression_metrics:
    raw_turns_count: int     # 原始轮次 (e.g. 956)
    clean_turns_count: int   # 物理降噪后纯净轮次 (e.g. 140)
    core_decisions_count: int # 最终生效核心决策数 (e.g. 50)
    token_savings_pct: float # Token 节省比例 (e.g. 99.9%)

active_constraints:
  prohibited_keywords: list  # 显式禁止出现的废案词汇 (e.g. ["Jev", "Elasticsearch", "Swarm", "Model-Fusion"])
  mandatory_architectures: list # 强制执行的架构模式 (e.g. ["Schema-constrained Decision Model", "PG Lightweight Hybrid"])
  grounded_formulas: list    # 必须严格保持一致的算法公式

payload_references:
  human_playbook_path: string # 人类可读手册绝对路径
  decision_dag_path: string   # 机器决策图 JSON 绝对路径
  acceptance_manifest: string # 验证断言清单路径
```

---

## 五、协议一致性测试与校验流程

为保证实现符合本规格书，系统提供自动化校验模式：

1. **Schema 校验**：使用 `jsonschema` 针对 `UnifiedTurn` 和 `DecisionDAG` 进行模式匹配，必须无 ValidationError；
2. **R1 规则静态检查**：
   ```bash
   # 验证 handoff envelope 正文是否越界 (<= 1200 字符且 <= 20 行)
   python3 -c '
   from pathlib import Path
   p = Path(".docs/sendbox/toAgent/ra-resume-suborc/handoff.md")
   lines = p.read_text().split("---")[-1].strip().splitlines()
   text = "\n".join(lines)
   assert len(lines) <= 20, f"R1 Failed: lines={len(lines)} > 20"
   assert len(text) <= 1200, f"R1 Failed: chars={len(text)} > 1200"
   print("R1 Rule Passed: Envelope strictly within bounds.")
   '
   ```
3. **废案渗透防御检查**：断言生成的 `A2AHandoffEnvelope` 中的 `active_constraints.prohibited_keywords` 绝未出现在提取决策的任意正文中。

---
*(End of Specification)*
