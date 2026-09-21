---
name: session-distill
description: High-fidelity trajectory distillation and A2A handoff engine. Extracts audit-grade Architecture Decision Records (ADR) and battle-tested playbooks from messy multi-turn Coding Agent sessions (Claude Code, Antigravity, Cursor, Codex, Grok), pruning superseded drafts via reverse-anchored FSM.
---

# session-distill

A zero-token, deterministic trajectory distillation tool that turns chaotic multi-hundred-turn Coding Agent sessions into audit-grade Architecture Decision Records (ADRs), defensive interview/review playbooks, and ultra-low-token A2A handoff envelopes.

## Supported Platforms
- **Antigravity** (`~/.gemini/antigravity-cli/brain/<id>/`)
- **Claude Code** (`~/.claude/projects/`, `~/.claude/history.jsonl`)
- **Cursor** (`~/.cursor/chats/`, `~/.cursor/projects/`)
- **Codex** (`~/.codex/sessions/`, `~/.codex/history.jsonl`)
- **Grok** (Exported chat JSON)

## CLI Usage

```bash
# Run distillation on Antigravity session
python3 -m session_distill.cli run \
  --from antigravity \
  --session <session_id> \
  --output-playbook ./playbook.md \
  --output-handoff ./handoff_envelope.json

# Run distillation on Claude Code JSONL file
python3 -m session_distill.cli run \
  --from claude-code \
  --file ~/.claude/projects/my-project/session.jsonl \
  --output-playbook ./playbook.md
```
