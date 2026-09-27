---
{"attributes":{"slug":"version-plan"},"decision_anchor":"human:2026-09-27:search-uses-agentsview-defer-fallback-parity","document_id":"spec:version-plan","kind":"spec","links":["docs/adr/20260927-defer-embedded-search-fallback.md","docs/spec/session-search.md","docs/spec/exec-plan.md","docs/spec/test-plan.md"],"origin_anchors":[],"replaces":[],"status":"draft","task_key":null,"title":"agent-handoff 版本计划","visibility":"private"}

---

# agent-handoff 版本计划

日期：2026-09-27。状态：草稿，执行前契约。

## 已定需求

- 调用者是 Agent。人可以敲同一条命令，不是另一套产品。
- 交给 Agent 的形式是 Skill + CLI。Skill 说明情景；CLI 执行。Agent 不写 `import`。
- 三个情景，三个正入口，用连字符，避免和 Arborist-Orca 里「session handoff」读会话规程撞名：
  - `session-handoff`：前一个会话把结论交给后一个会话。不读旧日志。
  - `session-distill`：后一个会话分析一份已经确定的旧会话。
  - `session-search`：后一个会话还不知道是哪一份，先按查询词查找。
- `session handoff|distill|search` 仍能跑，不写进给 AO Agent 的 Skill。
- `handoff run` 与 `handoff distill` 是同一个分析函数的旧名。`handoff inspect` 是只打印的分析。`handoff send` 是 `session-handoff` 的旧名。这些旧命令保留。
- 搜索的当前路径是 agentsview。它不可用或调用失败时，仍用已经落地的本地 JSONL 嵌入式引擎。与 agentsview 对齐的全局兜底推迟，见 ADR `docs/adr/20260927-defer-embedded-search-fallback.md`。
- 默认 stdout。只有调用方传入路径才写文件。本仓不选收件人，不投 Orca inbox。
- 不修改 `Arborist-Orca/skills/orca-a2a-comm/references/session-handoff.md`。那是 `ao-session-read.py` 的读会话规程。

## 0.2.0（工作区已有，尚未提交）

- 包名 `agent_handoff`。`import handoff` 与 `import session_distill` 仍指向它。
- `session-search`：本机有 agentsview 时查它的全局库，输出 `agent-handoff:search:v1`。
- `--engine embedded` 或 agentsview 不可用：只查 `--path`，否则只查当前目录里有限的 `*.jsonl`。这不是全局兜底。

## 0.2.1（本轮执行）

- PATH 上的 `session-distill` 加载 `/home/shenzhou/Codes/Agents/agent-handoff/src`。不带子命令时就是蒸馏；`run|inspect|send|search` 仍走旧命令。
- Skill 和 README 只教三个连字符命令和三种情景。
- Arborist-Orca 的 `submodules/handoff` 停在已提交的 `4b38f43`。未提交文件不会出现在那份检出里。

## 推迟，不排期

- 无 agentsview 时扫描五家会话目录，并用 Adapter 与 `NoiseFilter` 对齐命中。
- 嵌入式结果再套一层 agentsview 形状。
- 把 agentsview 的 `ordinal` 保证成 `UnifiedTurn.turn_id`。
- `search` 的 stdout 自动送进 `distill`。
