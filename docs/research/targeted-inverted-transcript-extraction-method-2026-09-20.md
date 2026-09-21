---
{"attributes":{"slug":"targeted-inverted-transcript-extraction-method"},"decision_anchor":null,"document_id":"research:targeted-inverted-transcript-extraction-method","kind":"research","links":[],"origin_anchors":[],"replaces":[],"status":"proposed","task_key":null,"title":"超长会话精准提取：纯净对话过滤与靶向倒排最新定案归纳法","visibility":"private"}

---
# 超长会话精准提取方案：纯净对话过滤与靶向倒排最新定案归纳法

- Scope: 面向超长会话（数百至上千轮）的结构化知识与最终决策提取
- Target Session: `e6129792-626d-48e2-bb79-be9d34b32829` (总计 956 轮，有效对话 140 轮)
- Date: 2026-09-20
- Version: 1.0.0

---

## 一、 方法论核心思想：为什么必须“先过滤、再倒排、后聚类”？

在长达数百轮的交互会话中，原始日志（`transcript.jsonl`）存在大量**非文本讨论噪音**（文件读写、代码构建、终端执行输出、录音切片原文、调试重试等）。以 `e6129792-626d-48e2-bb79-be9d34b32829` 为例：
* **原始轮次**：956 轮（全量读取需数十万至数百万 Token，直接超窗或注意力稀释）；
* **有效对话**：经提取 `USER_INPUT` 与 `PLANNER_RESPONSE` 后，实质对话仅 **140 轮**（总字符数约 16 万字，约 6~8 万 Token）；
* **体积削减**：**压缩了 85% 以上的无用体积**，大幅降低推理成本并杜绝工具报错噪音干扰。

在此基础上，采用**“以最终简历骨架为靶心，倒排最新定案覆写”**的策略，可做到 100% 还原每个项目的**【怎么一步步讲】**与**【每一行每个词如果被问到怎么答】**。

---

## 二、 五阶段标准提取流程

```
[transcript.jsonl (956 轮)]
          │
          ▼
【Stage 1: 预处理降噪】──► 仅保留 USER_INPUT & PLANNER_RESPONSE (过滤 85% 工具噪音，收敛至 140 轮)
          │
          ▼
【Stage 2: 靶心骨架定桩】──► 锚定定版简历 5 大项目、25 个核心技术词条 (PTY, TCC, MCP, DAG, 置信度...)
          │
          ▼
【Stage 3: 关键词倒排切分】──► 聚类成 5 个独立项目子流 (每个项目仅 10~40 轮，完全在 1~2 万 Token 内)
          │
          ▼
【Stage 4: 最新决策覆写】──► 针对多次讨论的争议点，严格以末尾最新轮次为准 (如 Step 951 不加ES、Step 955 置信度算法)
          │
          ▼
【Stage 5: 隔离按序编译】──► 按简历顺序，分段输出【3分钟口语稿】+【逐行每词追问防御库】
```

### Stage 1: 预处理降噪（排除无效 Turn）
* 仅读取 `type in ("USER_INPUT", "PLANNER_RESPONSE")` 且 `content` 非空的轮次。
* 过滤掉所有 `tool_calls`、`tool_output`、空的系统轮次以及大段纯文件拷贝，直接输出轻量中间文件 `clean_dialogue.jsonl`。

### Stage 2: 靶心骨架定桩（Anchor Skeleton）
以最终定版简历（`resume_final_audited.md`）中的结构为大纲，提取每个项目的专属匹配关键词：
1. **项目一（Raven Agent / Arborist）**：`Raven`, `Arborist`, `Orca`, `PTY`, `A2A`, `Supervisor`, `Worktree`, `信封`, `Nonce`
2. **项目二（EverMe 知识库）**：`EverMe`, `Category`, `Tag`, `渐进式`, `MCP`, `置信度`, `新词发现`, `BM25`, `PostgreSQL`, `ES`
3. **项目三（商汤科技万象平台与一体机）**：`商汤`, `万象`, `一体机`, `SenseChat`, `DAG`, `LazyLLM`, `流式中断`, `坐标溯源`, `94%`, `3%`, `差错率`
4. **项目四（FNZ 交易与久尺 ToDesk）**：`FNZ`, `三井住友`, `GVC`, `TCC`, `CAS`, `无锁`, `ToDesk`, `久尺`, `4000万`, `WebSocket`
5. **项目五（开源 AI 助手与 MCP）**：`interview-helper`, `Zhihu-Collections`, `开源`, `语音 AI`

### Stage 3: 关键词倒排切分（Project Clustering）
将 140 轮对话按关键词分流到 5 个项目的专属子包中：
* 每个子包只包含与该项目相关的发言上下文，彼此物理隔离，消除了跨项目注意力污染。

### Stage 4: 最新决策覆写（Latest-Wins Conflict Resolution）
* 会话中频繁出现“先提出方案 A $\to$ 讨论发现缺陷 $\to$ 在会话末尾推翻并确立方案 B”。
* **规则**：若同一个技术点在不同轮次出现，**严格以 Step 编号最大的最终轮次为准**（如：Step 950 讨论是否加 ES，Step 951 拍板坚决不加 ES，最终采用 Step 951 的说辞；Step 955 拍板置信度具体计算公式，淘汰早期的模糊设想）。

### Stage 5: 按序结构化生成
按简历自顶向下的物理顺序，针对每个项目独立生成：
1. **项目定位与核心亮点（一句话背书）**
2. **3 分钟口语化介绍稿（STAR 架构）**
3. **逐行、逐词的面试官追问与标准应答库**

---

## 三、 自动化预处理脚本（Python）

在启动 Agent 前，可直接运行此脚本，秒级生成清洗后的 `clean_dialogue.jsonl`，省去 Agent 遍历 956 轮的开销：

```python
import json
from pathlib import Path

CONV_ID = "e6129792-626d-48e2-bb79-be9d34b32829"
INPUT_PATH = Path.home() / f".gemini/antigravity-cli/brain/{CONV_ID}/.system_generated/logs/transcript.jsonl"
OUTPUT_PATH = Path.home() / f".gemini/antigravity-cli/brain/{CONV_ID}/clean_dialogue.jsonl"

meaningful_turns = []
with open(INPUT_PATH, "r", encoding="utf-8") as f:
    for line in f:
        step = json.loads(line)
        stype = step.get("type")
        content = step.get("content", "")
        # 严格只保留人类输入与模型正文回复
        if stype in ("USER_INPUT", "PLANNER_RESPONSE") and content.strip():
            meaningful_turns.append({
                "step_index": step.get("step_index"),
                "type": stype,
                "content": content
            })

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for turn in meaningful_turns:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")

print(f"原始轮次: 956 -> 清洗后有效对话轮次: {len(meaningful_turns)} (已保存至 {OUTPUT_PATH})")
```

---

## 四、 派发给另一个 Agent 的执行 Prompt

你可以将以下完整提示词直接发给另一个 Agent：

```markdown
# 角色与任务目标
你是一名资深的技术面试辅导专家与大模型系统分析师。
请针对特定历史会话记录（Session ID: `e6129792-626d-48e2-bb79-be9d34b32829`），按照【纯净对话过滤 + 靶向倒排最新定案归纳法】，完整提取出一份《赵晟·面试项目逐行应答与防御手册.md》。

# 输入数据源
1. 目标会话原始日志路径：`~/.gemini/antigravity-cli/brain/e6129792-626d-48e2-bb79-be9d34b32829/.system_generated/logs/transcript.jsonl`
   （或者先运行预处理脚本提取出只含 USER_INPUT 和 PLANNER_RESPONSE 的 `clean_dialogue.jsonl`）
2. 最终定版简历路径：`~/.gemini/antigravity-cli/brain/e6129792-626d-48e2-bb79-be9d34b32829/resume_final_audited.md`

# 核心提取与归纳原则（极其重要）
1. **排除无用 Turn**：绝对不要去通读或总结底层的 tool_call、bash 输出和文件读写流水账，只聚焦人和 Agent 的核心对话。
2. **以简历为唯一主线**：严格按照 `resume_final_audited.md` 中的 5 个项目及其内部各行要点的出现顺序排布。
3. **最新裁定胜出原则（Latest-Wins）**：该会话历经多次反复推翻与迭代。若同一个知识点或技术选型讨论了多次（例如“要不要加 Elasticsearch 做 BM25”、“置信度到底怎么计算”、“3% 幻觉率怎么圆”），必须且只能采纳【会话尾声（如 Step 948~955）达成的最终版本】，彻底剔除早期已被否决的旧草案。
4. **绝不务虚，直击代码与工程细节**：所有回答必须符合会话中敲定的去包装化工程口径（例如 Arborist 为何用 PTY 伪终端而非 Docker、商汤四阶段 DAG 为何控制面/数据面分离、FNZ 的 TCC 事务补偿机制）。

# 输出文档必须包含的具体章节结构

请将最终结果保存为 `.docs/guides/赵晟-面试项目逐行应答与防御手册.md`，文档结构严格如下：

---
### 目录
1. 候选人全局定位与自我介绍标准话术（1分钟/3分钟版）
2. 全局面试口径红线（绝对不能吹、容易被问穿的雷区清单）
3. 项目一：Raven Agent / Arborist-Orca（异构 A2A 协作网络与编程平台）
   - 3.1 项目 3 分钟标准口语介绍稿（STAR 架构）
   - 3.2 简历逐行逐词·深度追问与应答防御库
4. 项目二：EverMe（个人知识库与渐进式 Agent 认知系统）
   - 4.1 项目 3 分钟标准口语介绍稿（STAR 架构）
   - 4.2 简历逐行逐词·深度追问与应答防御库（含为什么不用 ES 的取舍、置信度算法真实公式、渐进式三级 MCP 探查）
5. 项目三：商汤大模型一体机 & 万象行业大模型平台（商汤科技）
   - 5.1 项目 3 分钟标准口语介绍稿（STAR 架构，一体机与万象解耦展示）
   - 5.2 简历逐行逐词·深度追问与应答防御库（含 K8s 流式中断、四阶段确定性 DAG、94% 坐标溯源算法）
6. 项目四：万亿级分布式资产交易与高并发长连接底座（FNZ & 久尺网络 ToDesk）
   - 6.1 项目 3 分钟标准口语介绍稿（STAR 架构）
   - 6.2 简历逐行逐词·深度追问与应答防御库（含 TCC 事务补偿、CAS 无锁队列、4000 万长连接保持）
7. 项目五：开源语音 AI 助手与 MCP 工具链（interview-helper / Zhihu-MCP）
   - 7.1 项目口语介绍与开源影响力陈述
   - 7.2 核心追问应对
---

请现在开始执行，先进行降噪过滤，再逐个项目抽取，产出完整、翔实、可以直接背诵通关的最终文档。
```
