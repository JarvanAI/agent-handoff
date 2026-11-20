---
name: handoff
description: Universal Multi-Agent Handoff Protocol, trajectory distillation, and session search. Supports sender-side handoff envelopes, receiver-side session continuation and distillation, and a dual-track session-search (agentsview, then embedded SQLite FTS5) across Claude Code, Antigravity, Cursor, Codex, and Grok.
---

# handoff

A cross-provider session handoff, continuation, and trajectory distillation workflow.

- **`session-handoff`**: the current session writes a short handoff for the next session. It does not read the old transcript.
- **`session-continue`**: print the previous session's user messages and public replies. The calling agent reads that stdout and continues. Do not open the raw transcript.
- **`session-distill`**: a child process reads one known previous session, crops it the same way, then prints only the decision brief. The calling agent must not open the transcript or paste the dialogue into its own context.
- **`session-search`**: find which past session matches a query.

The shared crop drops tool calls, tool output, reasoning, and harness reminders such as `<system-reminder>`, `<user_info>`, and `<user_rules>`. When a user message contains `<user_query>`, only that inner text is kept.

The caller is an Agent. This Skill says which scenario applies; the CLI does the work. `session handoff|continue|distill|search` also runs, but Agents should use the hyphenated commands. Arborist-Orca's "session handoff" reading procedure (`ao-session-read.py`) is a different workflow.

## Previous-session reading

For `session-continue`, read [bounded continuation reading](references/continuation-reading.md)
when the output is large/unknown, a return is truncated, or the request includes OA takeover.
It covers exact-target selection, caching the existing cropped stdout once, bounded reading,
historical summaries, and honest coverage. It does not add CLI flags or raw-transcript access.

## Supported Platforms
- **Antigravity** (`~/.gemini/antigravity-cli/brain/<id>/`)
- **Claude Code** (`~/.claude/projects/`, `~/.claude/history.jsonl`)
- **Cursor** (`~/.cursor/chats/`, `~/.cursor/projects/`)
- **Codex** (`~/.codex/sessions/`, `~/.codex/history.jsonl`)
- **Grok** (`~/.grok/sessions/<cwd>/<id>/chat_history.jsonl`, or an exported chat JSON)

## CLI Usage

```bash
# Previous session hands its conclusion to the next session.
session-handoff --summary "PG is the accepted store; do not revive ES."

# Calling agent reads the cropped dialogue and continues.
session-continue --from grok --session <session_id>

# Child process returns a short decision brief. Do not read the session files.
session-distill --from antigravity --session <session_id>

# Print that analysis without writing a file.
session-distill --inspect <session_id> --from antigravity

# Find which session mentioned a symbol. agentsview is used when installed.
session-search "BaseSessionAdapter" --json
```
