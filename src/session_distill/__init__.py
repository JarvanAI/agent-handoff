"""Session Distill: Zero-token deterministic multi-agent session distillation package.

Pure-Python pipeline converting high-noise Agent trajectories into:
1. Human-readable Markdown ADR & Defense Playbooks
2. Machine-readable Zero-Loss A2A Handoff Envelopes
"""

from session_distill.adapters import (
    AntigravityAdapter,
    BaseSessionAdapter,
    ClaudeCodeAdapter,
    CodexAdapter,
    CursorAdapter,
    GrokAdapter,
    detect_adapter,
    get_adapter,
)
from session_distill.engine import DistillationEngine
from session_distill.models import (
    AnchorRecord,
    AnchorType,
    AntiPatternRecord,
    DecisionEntity,
    DecisionState,
    DistillationResult,
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
    UnifiedTurn,
)
from session_distill.outputs import HandoffEnvelopeGenerator, PlaybookGenerator

__version__ = "0.1.0"

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
    "ToolCallRecord",
    "ToolResultRecord",
    "TurnRole",
    "UnifiedTurn",
    "__version__",
    "detect_adapter",
    "get_adapter",
]
