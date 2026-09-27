---
{"attributes":{"slug":"exec-plan"},"decision_anchor":"human:2026-09-27:search-uses-agentsview-defer-fallback-parity","document_id":"spec:exec-plan","kind":"spec","links":["docs/spec/version-plan.md","docs/adr/20260927-defer-embedded-search-fallback.md"],"origin_anchors":[],"replaces":[],"status":"draft","task_key":null,"title":"agent-handoff 执行计划","visibility":"private"}

---

# 执行计划

日期：2026-09-27。状态：草稿。推迟项不派工。

## Worktree 与 impler

Orca 环境 `main-59140-rekey`，runtime `764c63da-f5cd-400b-97cb-7afaa48a632b`。

| Worktree | 角色 | 做什么 | 为什么是这一份 |
|---|---|---|---|
| Orca worktree `agent-handoff`，id `92d88237-fa6b-4b1a-8cc4-8a495696d02e::/home/shenzhou/Codes/Agents/agent-handoff` | L2 impler 标签 `ah-impler`，terminal `term_846cc20d-3775-4136-bce4-b926be89da0b` | 契约对齐和测试已在这份检出完成。该标签用来在 Orca 里看见这个 OA | 仓库原先没在 Orca 注册，所以界面里没有卡片。不从 `4b38f43` 再拉子 worktree，否则看不到未提交改动 |
| 不创建 | 无 | 全局兜底、parity adapter、`search \| distill`、改 AO 的 `session-handoff.md` | Human 已推迟，或那份文件是另一套读会话规程 |
| `/home/shenzhou/Codes/Arborist-Orca/submodules/handoff` | 不派 | 停在 `4b38f43` | 同一仓库的另一次检出。指针要等本仓提交后才更新 |

不并行开第二个 impler。两个人改同一批未提交文件会冲掉对方。

## 本轮步骤

1. 四份文档写上：Agent 调用者、Skill + CLI、三个连字符命令、旧命令保留、兜底推迟、不改 AO 读会话规程。
2. `SKILL.md` 与 `README.md` 的用法改成 `session-handoff`、`session-distill`、`session-search`。
3. 测试按 `docs/spec/test-plan.md` 的 0.2.1 项跑通。
4. 不提交，除非 Human 另说。因此不更新 AO submodule gitlink。

## 明确不做

- 不重写 agentsview 的导入。
- 不增加「嵌入式命中 → agentsview 命中」适配器。
- 不把嵌入式扫描扩到五家家目录。
- 不把搜索编号改成 `UnifiedTurn.turn_id`。
- 不在本仓实现 Orca 投递。
- 不改 `Arborist-Orca/skills/orca-a2a-comm/references/session-handoff.md`。
