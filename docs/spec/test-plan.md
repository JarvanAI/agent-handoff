---
{"attributes":{"slug":"test-plan"},"decision_anchor":"human:2026-09-27:search-uses-agentsview-defer-fallback-parity","document_id":"spec:test-plan","kind":"spec","links":["docs/spec/session-search.md","docs/spec/version-plan.md"],"origin_anchors":[],"replaces":[],"status":"draft","task_key":null,"title":"agent-handoff 测试说明","visibility":"private"}

---

# 测试说明

日期：2026-09-27。状态：草稿。验收命令是 `python3 -m pytest tests/ -q`。通过标准是退出码 0。

## 已经在测的行为

`tests/` 里原有 22 项蒸馏测试继续导入 `handoff.*`，用来守住兼容垫片。

`tests/test_namespace.py`：`handoff`、`session_distill`、`agent_handoff` 的公开类是同一对象，版本是 `0.2.0`。

`tests/test_search.py` 覆盖：

- 嵌入式 FTS5 trigram 能命中中文和 `BaseSessionAdapter`，工具帧与 base64 不进索引。
- 源文件变化后整文件重灌，旧词不再命中。
- RRF 的 Python 结果与 SQL CTE 一致。
- 没有 `sqlite-vec` 时即使传入向量函数，`engine` 仍是 `embedded_fts5`。
- agentsview 的 `matches` / MCP `results` 映射成信封；CLI 失败时走 MCP 子进程，子进程会退出。
- `auto` 在适配器可用时不建本地库；适配器抛错时才用嵌入式引擎。
- CLI `--json` 与人类可读输出；短查询退出码 2；`--version` 含 `0.2.0`。
- 1 万条记录的点查小于 50ms。
- 独立进程做完搜索后线程数为 1，数据库能被独占打开，内存库 trigram 冷启动小于 10ms。

这些测试不要求本机 agentsview 在线。agentsview 用假命令或假 JSON。

## 0.2.1 追加的检查

pytest 里要有：

- `session_main(["handoff", ...])` 打出 `A2A-Handoff-v1`，且不读会话文件。
- `handoff_main` 与上面是同一份 JSON 形状。
- `session_main(["distill", "--inspect"])` 在没有会话目标时退出码 2。
- `distill_main(["search", "ab"])` 仍走旧搜索命令，短查询退出码 2。

包装脚本不在本仓，手工检查：

```bash
/home/shenzhou/.local/bin/session-distill --version
```

stdout 为 `session-distill 0.2.0`，加载的 `agent_handoff.cli` 位于 `/home/shenzhou/Codes/Agents/agent-handoff/src/agent_handoff/cli.py`。

## 现在不测的事

- 嵌入式引擎与 agentsview 命中一致。
- 搜索轮次号等于 `UnifiedTurn.turn_id`。
- 无 agentsview 时的全局家目录扫描。
- `search` 输出自动进入 `distill`。
