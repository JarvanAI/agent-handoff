"""Agent-handoff: session search, trajectory distillation, and handoff envelopes.

Public names are loaded on first use so ``import agent_handoff.search`` does
not pull the distillation stack into a cold search process.
"""

from __future__ import annotations

import importlib
from typing import Any

from agent_handoff.version import __version__

__all__ = [
    "AnchorRecord",
    "AnchorType",
    "AntiPatternRecord",
    "AntigravityAdapter",
    "BaseSessionAdapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "CursorAdapter",
    "DecisionEntity",
    "DecisionState",
    "DistillationEngine",
    "DistillationResult",
    "GrokAdapter",
    "HandoffEnvelopeGenerator",
    "PlaybookGenerator",
    "SearchEnvelope",
    "ToolCallRecord",
    "ToolResultRecord",
    "TurnRole",
    "UnifiedTurn",
    "__version__",
    "detect_adapter",
    "get_adapter",
    "search_sessions",
]

_EXPORTS = {
    "AnchorRecord": "agent_handoff.models",
    "AnchorType": "agent_handoff.models",
    "AntiPatternRecord": "agent_handoff.models",
    "DecisionEntity": "agent_handoff.models",
    "DecisionState": "agent_handoff.models",
    "DistillationResult": "agent_handoff.models",
    "ToolCallRecord": "agent_handoff.models",
    "ToolResultRecord": "agent_handoff.models",
    "TurnRole": "agent_handoff.models",
    "UnifiedTurn": "agent_handoff.models",
    "AntigravityAdapter": "agent_handoff.adapters",
    "BaseSessionAdapter": "agent_handoff.adapters",
    "ClaudeCodeAdapter": "agent_handoff.adapters",
    "CodexAdapter": "agent_handoff.adapters",
    "CursorAdapter": "agent_handoff.adapters",
    "GrokAdapter": "agent_handoff.adapters",
    "detect_adapter": "agent_handoff.adapters",
    "get_adapter": "agent_handoff.adapters",
    "DistillationEngine": "agent_handoff.engine",
    "HandoffEnvelopeGenerator": "agent_handoff.outputs",
    "PlaybookGenerator": "agent_handoff.outputs",
    "SearchEnvelope": "agent_handoff.search",
    "search_sessions": "agent_handoff.search",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
