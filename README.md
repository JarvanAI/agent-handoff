# ⚡ handoff

> **Universal Multi-Agent Handoff Protocol & Trajectory Distillation Engine.**  
> *Turn messy 500-turn Coding Agent sessions into audit-grade Architecture Decision Records (ADRs) & battle-tested Playbooks in seconds.*  
> *Reverse-anchored, FSM-pruned, zero hallucination, zero LLM token cost.*

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](#)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](#)

---

### 🚨 The Problem: "The Vibe-Coding Hangover" & "A2A Handoff Friction"

You just spent 3 hours collaborating with Cursor, Claude Code, Antigravity, or Codex.  
It edited 47 files, failed 12 tests, pivoted across 3 database schemas, and finally worked!

**Then reality hits:**
1. **The Vibe-Coding Hangover**: When opening a PR or answering your Tech Lead's review questions (*"Why didn't we use Redis? What were the concurrency trade-offs?"*), your mind is a complete blank. You don't know why the agent settled on the final design.
2. **Session Compaction Amnesia**: Your chat context window hits the ceiling and triggers `/compact`. Hundreds of turns of deep reasoning are compressed into a few vague lines, erasing all architectural trade-offs.
3. **A2A Handoff Friction**: In multi-agent workflows, handing over 200 raw turns to downstream Agent B causes context explosion; passing a 1-sentence prompt causes catastrophic context loss and error cascading.

---

### 💡 The Solution: handoff

Agents call this as a Skill plus a CLI. Four commands match four situations:
- **`session-handoff`**: the current session writes a short handoff for the next session.
- **`session-continue`**: print one known session cropped to user messages and public replies. The calling agent reads that stdout.
- **`session-distill`**: a child process crops the same way, then prints only the decision brief so the calling agent's context stays small.
- **`session-search`**: find which past session matches a query. agentsview is used when it is installed.

```text
[Raw 500k-token Agent Session (Claude Code / Antigravity / Cursor / Codex / Grok)]
                                │
                                ▼ (1. Programmatic Deterministic Noise Filter)
[Clean Reasoning Stream (No ANSI junk, no raw bash dumps, 80%+ noise stripped)]
                                │
                                ▼ (2. Reverse Verdict Anchoring: Start from Final Consensus)
[Consensus Spine (Anchored from passing tests & user sign-offs)]
                                │
                                ▼ (3. FSM State Machine Pruning: Proposed -> Superseded -> Accepted)
[Purged Decision Graph (All overturned dead ends stripped from active truth)]
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
   [Human Playbook & ADR (Markdown)]    [Machine Handoff Envelope (JSON)]
   - Complete architectural rationale   - Minimal token footprint (<1200 chars)
   - Line-by-line defense Q&A           - Zero-loss context continuation for Agent B
```

---

### ✨ Key Features

- 🏎️ **Zero-Token Deterministic Parsing**: Built 100% in Python without calling external LLMs. Parses 1,000 turns in sub-seconds with zero API costs.
- 🎯 **Reverse Verdict Anchoring**: Starts from the final state ($t_N$) and backfills rationale, avoiding intermediate dead-end hallucinations.
- ✂️ **FSM Draft Pruning (Latest-Wins)**: Tracks the lifecycle of entities. Overturned proposals (e.g. invalid models, rejected libraries) are strictly purged from the final active state.
- 🔌 **5 Mainstream Adapters Included**:
  - **Antigravity** (`~/.gemini/antigravity-cli/brain/<id>/`)
  - **Claude Code** (`~/.claude/projects/`, `~/.claude/history.jsonl`)
  - **Cursor** (`~/.cursor/chats/`, `~/.cursor/projects/`)
  - **Codex** (`~/.codex/sessions/`, `~/.codex/history.jsonl`)
  - **Grok** (`~/.grok/sessions/<cwd>/<id>/chat_history.jsonl`, or an exported JSON chat)
- 📦 **Dual-Form Outputs**:
  - **Human-Facing**: Production-grade Architecture Decision Records (ADR) and defensive Q&A playbooks.
  - **Agent-Facing**: Zero-Loss A2A Handoff Envelope for seamless multi-agent orchestration.

---

### 🚀 Quick Start

```bash
# Install locally
pip install -e .

# 1. Previous session writes a handoff. This does not read an old transcript.
session-handoff --summary "PG stays; do not revive ES."

# 2. Calling agent loads the cropped dialogue.
session-continue --from grok --session <session_id>

# 3. Child process returns the decision brief. It does not print the dialogue.
session-distill \
  --from antigravity \
  --session e6129792-626d-48e2-bb79-be9d34b32829 \
  --output-playbook ./playbook.md \
  --output-handoff ./handoff.json

# 4. Same analysis, terminal only.
session-distill --inspect e6129792-626d-48e2-bb79-be9d34b32829 --from antigravity

# 5. Find a session, then distill that id.
session-search "BaseSessionAdapter" --json
```

---

### 📄 License

Apache License 2.0.
