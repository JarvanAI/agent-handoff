---
name: handoff
description: Universal Multi-Agent Handoff Protocol & Trajectory Distillation Engine. Supports both sender-side online handoff envelope generation and receiver-side offline session distillation (session-distill) across Claude Code, Antigravity, Cursor, Codex, and Grok.
---

# handoff

A universal, zero-token, deterministic Multi-Agent Handoff Protocol and trajectory distillation engine.

- **Sender Mode (`handoff send / create`)**: Formats zero-loss, minimal-token context handoff envelopes for downstream agents.
- **Receiver Mode (`handoff distill` / `session-distill`)**: Distills chaotic multi-hundred-turn Coding Agent sessions into audit-grade Architecture Decision Records (ADRs) and battle-tested playbooks.

## Supported Platforms
- **Antigravity** (`~/.gemini/antigravity-cli/brain/<id>/`)
- **Claude Code** (`~/.claude/projects/`, `~/.claude/history.jsonl`)
- **Cursor** (`~/.cursor/chats/`, `~/.cursor/projects/`)
- **Codex** (`~/.codex/sessions/`, `~/.codex/history.jsonl`)
- **Grok** (Exported chat JSON)

## CLI Usage

```bash
# 1. Distill an Antigravity session (session-distill mode)
handoff run \
  --from antigravity \
  --session <session_id> \
  --output-playbook ./playbook.md \
  --output-handoff ./handoff_envelope.json

# 2. Inspect session decisions quickly
handoff inspect <session_id> --from antigravity

# 3. Backward-compatible alias
session-distill inspect <session_id> --from antigravity
```
