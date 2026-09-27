---
name: handoff
description: Universal Multi-Agent Handoff Protocol, trajectory distillation, and session search. Supports sender-side handoff envelopes, receiver-side session distillation, and a dual-track session-search (agentsview, then embedded SQLite FTS5) across Claude Code, Antigravity, Cursor, Codex, and Grok.
---

# handoff

A universal, zero-token, deterministic Multi-Agent Handoff Protocol and trajectory distillation engine.

- **`session-handoff`**: the current session writes a short handoff for the next session. It does not read the old transcript.
- **`session-distill`**: the next session analyzes one known previous session.
- **`session-search`**: find which past session matches a query.

The caller is an Agent. This Skill says which scenario applies; the CLI does the work. `session handoff|distill|search` also runs, but Agents should use the hyphenated commands. Arborist-Orca's "session handoff" reading procedure (`ao-session-read.py`) is a different workflow.

## Supported Platforms
- **Antigravity** (`~/.gemini/antigravity-cli/brain/<id>/`)
- **Claude Code** (`~/.claude/projects/`, `~/.claude/history.jsonl`)
- **Cursor** (`~/.cursor/chats/`, `~/.cursor/projects/`)
- **Codex** (`~/.codex/sessions/`, `~/.codex/history.jsonl`)
- **Grok** (Exported chat JSON)

## CLI Usage

```bash
# Previous session hands its conclusion to the next session.
session-handoff --summary "PG is the accepted store; do not revive ES."

# Next session analyzes one known previous session.
session-distill --from antigravity --session <session_id>

# Print that analysis without writing a file.
session-distill --inspect <session_id> --from antigravity

# Find which session mentioned a symbol. agentsview is used when installed.
session-search "BaseSessionAdapter" --json
```
