---
{"attributes":{"slug":"session-search"},"decision_anchor":"human:2026-09-27:search-uses-agentsview-defer-fallback-parity","document_id":"spec:session-search","kind":"spec","links":["docs/adr/20260927-defer-embedded-search-fallback.md","docs/spec/rfc-002-session-search-architecture.md"],"origin_anchors":[],"replaces":[],"status":"draft","task_key":null,"title":"session-search 当前可观察行为","visibility":"private"}

---

# session-search 当前可观察行为

日期：2026-09-27。状态：草稿。描述 0.2.0 工作区里已经发生的行为。RFC-002 里的全局嵌入式兜底不在本规格内。

## 命令

调用者是 Agent。形式是 Skill + CLI。

教给 Agent 的正入口是三个连字符命令：

- `session-search QUERY`：查找符合的会话。
- `session-distill`：分析一份已经确定的旧会话。`--inspect <会话>` 只打印、不写文件。
- `session-handoff`：前一个会话写下短交代。不读旧日志。

`session search|distill|handoff` 是同一实现的空格形式，能跑，不写进 Skill。

`handoff` 与 `agent-handoff` 仍接受旧子命令。`run` 与 `distill` 是同一个分析函数。`send` 等于 `session-handoff`。`inspect` 等于 `session-distill --inspect`。

`session-distill run|inspect|send|search` 仍转到旧子命令。Arborist-Orca 里 `references/session-handoff.md` 是读会话规程，不是本命令。

`QUERY` 少于 3 个字符时，退出码 2，stderr 说明原因，stdout 没有信封。

## 引擎

`--engine` 取值 `auto`（默认）、`agentsview`、`embedded`。

`auto`：本机能找到 `agentsview` 可执行文件，或 `127.0.0.1:59090` 在听，就调用 agentsview。调用成功则把结果映射成信封并返回，不读 `--path`，不建本地索引。调用失败，或 agentsview 不存在，才使用嵌入式引擎。

`--engine agentsview`：只用 agentsview。不可用或调用失败时退出码 2。

`--engine embedded`：不调用 agentsview。

agentsview 的调用是 `agentsview session search QUERY --json --limit N`。有 `--project` 时附上 `--project`。CLI 失败时再试 MCP 工具 `search_sessions`，没有该工具名时再试 `session_search`。

agentsview 原始 JSON 没有 `matched_turns`。映射规则：`ordinal`、`match_ordinal`、`ordinal_range` 写入 `matched_turns`；裸 `session_id` 在有 `agent` 且不含 `:` 时写成 `{agent}:{session_id}`。它不提供整段会话的 `turn_count`，该字段为 null。这些编号不保证等于蒸馏用的 `UnifiedTurn.turn_id`。

## 嵌入式引擎（仅在上面的条件落到它时）

- 有 `--path`：只索引这些 JSONL 文件或目录。
- 没有 `--path` 且没有 `--db`：扫描当前工作目录，深度不超过 4，最多 100 个 `*.jsonl`，跳过点目录和依赖目录。
- 只有 `--db`：不扫描新文件，只打开该库并按库里登记的路径刷新。
- 未指定 `--db` 时，库文件是当前目录下的 `.handoff_index.db`。`--db` 是这个缓存文件的路径，不是 agentsview 的参数。
- 索引入库使用 `reduce_record`，不使用五个 Adapter，也不使用 `NoiseFilter`。
- 进程内做完索引再查询。没有定时任务，没有常驻进程。

## 输出

stdout：

- 默认是给人类读的短表。
- `--json` 时只打印 `agent-handoff:search:v1` 对象，字段为 `protocol`、`engine`、`query`、`project`、`total_hits`、`results`。
- `results[]` 含 `session_id`、`harness`、`score`、`snippet`、`matched_turns`、`turn_count`、`created_at`。

stderr 只放错误。搜索成功不写 Playbook，不写 sendbox。

## 蒸馏命令（与搜索分开）

`run` 和 `distill` 进入同一个处理函数，读取 `--session`、`--file` 或 `--dir`。`inspect` 把决策打到终端。`send` 不读会话文件，只根据 `--summary`、`--decision`、`--anti-pattern` 打印 `A2A-Handoff-v1`。

未传入 `--output-playbook` 或 `--output-handoff` 时，蒸馏不写文件。传入的路径原样使用。本规格不要求把结果写进 Arborist-Orca 的 `.docs/sendbox` 或 `.docs/guides`；那是调用方选择的路径。
