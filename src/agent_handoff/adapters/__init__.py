"""Adapter registry and auto-detection for multi-agent sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Type, Union

from agent_handoff.adapters.antigravity import AntigravityAdapter
from agent_handoff.adapters.base import BaseSessionAdapter
from agent_handoff.adapters.claude_code import ClaudeCodeAdapter
from agent_handoff.adapters.codex import CodexAdapter
from agent_handoff.adapters.cursor import CursorAdapter
from agent_handoff.adapters.grok import GrokAdapter

_ADAPTER_REGISTRY: Dict[str, Type[BaseSessionAdapter]] = {
    "antigravity": AntigravityAdapter,
    "claude": ClaudeCodeAdapter,
    "claude-code": ClaudeCodeAdapter,
    "claudecode": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "cursor": CursorAdapter,
    "grok": GrokAdapter,
}


def get_adapter(name: str) -> BaseSessionAdapter:
    """Retrieve an adapter instance by provider name."""
    clean_name = name.strip().lower().replace("_", "-")
    cls = _ADAPTER_REGISTRY.get(clean_name)
    if not cls:
        valid = ", ".join(sorted(_ADAPTER_REGISTRY.keys()))
        raise ValueError(f"Unknown provider '{name}'. Supported providers: {valid}")
    return cls()


def detect_adapter(path_or_id: Union[str, Path]) -> BaseSessionAdapter:
    """Auto-detect appropriate adapter based on file paths or IDs."""
    p = Path(path_or_id).expanduser()
    s = str(path_or_id).lower()

    # 1. Antigravity clues
    if "antigravity" in s or "brain" in s or (p.is_dir() and (p / ".system_generated").is_dir()):
        return AntigravityAdapter()
    if p.name in ("transcript.jsonl", "transcript_full.jsonl"):
        return AntigravityAdapter()

    # 2. Cursor clues
    if "cursor" in s or (p.is_dir() and (p / "store.db").is_file()) or p.name == "store.db":
        return CursorAdapter()

    # 3. Claude Code clues
    if "claude" in s or (p.is_file() and "projects" in str(p.parent)):
        return ClaudeCodeAdapter()

    # 4. Codex clues
    if "codex" in s or "rollout-" in p.name:
        return CodexAdapter()

    # 5. Grok clues
    if "grok" in s:
        return GrokAdapter()

    # Check ~/.gemini/antigravity-cli/brain/<id>
    brain_dir = Path("~/.gemini/antigravity-cli/brain").expanduser() / str(path_or_id).strip()
    if brain_dir.is_dir():
        return AntigravityAdapter()

    # Default fallback to Antigravity if ambiguous UUID
    return AntigravityAdapter()


__all__ = [
    "AntigravityAdapter",
    "BaseSessionAdapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "CursorAdapter",
    "GrokAdapter",
    "detect_adapter",
    "get_adapter",
]
