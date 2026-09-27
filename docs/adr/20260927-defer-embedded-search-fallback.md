---
{"attributes":{"slug":"20260927-defer-embedded-search-fallback"},"decision_anchor":"human:2026-09-27:search-uses-agentsview-defer-fallback-parity","document_id":"adr:20260927-defer-embedded-search-fallback","kind":"adr","links":["docs/spec/rfc-002-session-search-architecture.md","docs/research/embedded-search-engine-research.md"],"origin_anchors":[],"replaces":[],"status":"accepted","task_key":null,"title":"会话搜索先用 agentsview，与之对齐的全局兜底推迟","visibility":"private"}

---

# ADR: 会话搜索先用 agentsview，与之对齐的全局兜底推迟

## 状态

**Accepted**（决定推迟，不在当前版本实施）
**日期**：2026-09-27
**决策者**：Human
**关联**：`docs/spec/rfc-002-session-search-architecture.md`，`docs/research/embedded-search-engine-research.md`

## 背景

0.2.0 的 `search` 在 `auto` 模式下已经优先调用本机 agentsview（CLI `agentsview session search`，失败时再试 MCP `search_sessions`）。agentsview 不可用时，才使用仓内嵌入式 SQLite FTS5。

这套嵌入式引擎今天的语料不是全局会话：只索引 `--path`，否则只扫当前工作目录下有限的 `*.jsonl`。它用自己的 `reduce_record` 降噪，不用蒸馏的五个 Adapter 和 `NoiseFilter`。因此它的 `session_id`、轮次号和命中正文都不会和 agentsview 对齐。

曾考虑把兜底做成 agentsview 的离线替代：查询时扫描 Antigravity、Claude Code、Codex、Cursor、Grok 的既定家目录，用现有 Adapter 解析成 `UnifiedTurn`，用同一套 `NoiseFilter`，写入 `~/.cache/agent-handoff/index.db`。agentsview 可用时仍然只走 agentsview。

## 决定

会话搜索的当前路径就是 agentsview。上面这套「全局、且与 agentsview 产出一致」的兜底方案整段推迟，不在 0.2.x / 0.3 实施。

不照搬 agentsview 的入库实现，也不再加一层 Adapter 去把嵌入式命中伪装成 agentsview 的命中。0.2.0 已经落地的嵌入式引擎保持原样，只作为没有 agentsview 时的本地 JSONL 查询，不继续加范围、不继续对齐协议。

## 推迟的方案（存档，供以后原样拾起）

触发：一次 `search` 进程内同步完成，不建定时任务，不常驻。

范围：只扫五种已经有读取器的家目录，不扫当前目录里偶然出现的 `*.jsonl`。

解析：`BaseSessionAdapter.parse_trajectory` → `UnifiedTurn` → `NoiseFilter`。新的会话文件格式只在本仓加读取器，不要求对方产品对接。

缓存：`~/.cache/agent-handoff/index.db`。指纹是文件大小加 mtime；变化则整文件重灌。这是缓存，不是交给 Agent 的文档。

查询：FTS5 trigram。`sqlite-vec` 仍是可选，不内置 embedding 模型。

分流：agentsview 可用则直接返回，不跑这段扫描。agentsview 不可用才跑。

显式不做：复制 agentsview 源码或它的数据库；为了字段一致再写一个「嵌入式结果 → agentsview 结果」适配器。

## 理由

agentsview 已经按产品分别导入本机全局会话，并建好索引。兜底要达到同一语料、同一命中形状，等于重写一套导入，再加一层对齐。这个成本高于当前收益。本机搜索有 agentsview 就能用。

## 后果

没有 agentsview 的环境，搜索仍然只覆盖调用方给出的 JSONL 或当前目录，不能代替 agentsview 的全局库。搜索命中里的轮次号，在走 agentsview 时来自它的 `ordinal` 映射，不保证等于蒸馏 `UnifiedTurn.turn_id`。

重新打开本 ADR 的条件：出现必须在无 agentsview 的环境里做全局会话搜索，并且接受单独的导入与对齐成本。

## 当前版本因此不做的事

- 不把嵌入式索引改成扫描五家家目录。
- 不让搜索入库复用 Adapter / `NoiseFilter`。
- 不新增 parity adapter。
- 不把 `.handoff_index.db` 的默认位置改到 `~/.cache`（那是推迟方案的一部分）。
