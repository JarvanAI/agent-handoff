"""Data models for session distillation and normalized agent trajectories.

Pure-Python deterministic data structures with strong typing.
Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class TurnRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class DecisionState(str, Enum):
    PROPOSED = "PROPOSED"
    DEBATED = "DEBATED"
    SUPERSEDED = "SUPERSEDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AnchorType(str, Enum):
    TEST_VERIFIED = "test_verified"
    USER_CONFIRMED = "user_confirmed"
    CODE_COMMITTED = "code_committed"
    GOAL_ACHIEVED = "goal_achieved"


@dataclass
class ToolCallRecord:
    """Record of a tool call executed during a turn."""

    tool_name: str
    tool_args: Dict[str, Any] = field(default_factory=dict)
    call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolCallRecord:
        return cls(
            tool_name=str(data.get("tool_name", "")),
            tool_args=dict(data.get("tool_args", {})),
            call_id=data.get("call_id"),
        )


@dataclass
class ToolResultRecord:
    """Record of tool output/result corresponding to a tool call."""

    tool_name: Optional[str] = None
    content: str = ""
    status: str = "success"
    call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolResultRecord:
        return cls(
            tool_name=data.get("tool_name"),
            content=str(data.get("content", "")),
            status=str(data.get("status", "success")),
            call_id=data.get("call_id"),
        )


@dataclass
class UnifiedTurn:
    """Normalized turn representation across all Agent providers.

    Guarantees deterministic sorting, filtering, and state machine analysis.
    """

    turn_id: str
    session_id: str
    timestamp: str  # ISO 8601 or normalized string
    role: TurnRole
    content: str = ""
    raw_content: Optional[str] = None
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    tool_results: List[ToolResultRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "role": self.role.value if isinstance(self.role, TurnRole) else str(self.role),
            "content": self.content,
            "raw_content": self.raw_content,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "tool_results": [tr.to_dict() for tr in self.tool_results],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UnifiedTurn:
        raw_role = data.get("role", "user")
        try:
            role = TurnRole(raw_role)
        except ValueError:
            role = TurnRole.USER

        return cls(
            turn_id=str(data.get("turn_id", "")),
            session_id=str(data.get("session_id", "")),
            timestamp=str(data.get("timestamp", "")),
            role=role,
            content=str(data.get("content", "")),
            raw_content=data.get("raw_content"),
            tool_calls=[ToolCallRecord.from_dict(tc) for tc in data.get("tool_calls", [])],
            tool_results=[ToolResultRecord.from_dict(tr) for tr in data.get("tool_results", [])],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class DecisionEntity:
    """Architectural decision entity tracked across turns by FSM."""

    entity_id: str
    topic: str
    state: DecisionState
    decision: str
    rationale: str
    alternatives_considered: List[str] = field(default_factory=list)
    consequences: List[str] = field(default_factory=list)
    turn_id: str = ""
    superseded_by: Optional[str] = None
    causal_parent_id: Optional[str] = None
    evidence_snippets: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "topic": self.topic,
            "state": self.state.value if isinstance(self.state, DecisionState) else str(self.state),
            "decision": self.decision,
            "rationale": self.rationale,
            "alternatives_considered": self.alternatives_considered,
            "consequences": self.consequences,
            "turn_id": self.turn_id,
            "superseded_by": self.superseded_by,
            "causal_parent_id": self.causal_parent_id,
            "evidence_snippets": self.evidence_snippets,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DecisionEntity:
        raw_state = data.get("state", "PROPOSED")
        try:
            state = DecisionState(raw_state)
        except ValueError:
            state = DecisionState.PROPOSED

        return cls(
            entity_id=str(data.get("entity_id", "")),
            topic=str(data.get("topic", "")),
            state=state,
            decision=str(data.get("decision", "")),
            rationale=str(data.get("rationale", "")),
            alternatives_considered=list(data.get("alternatives_considered", [])),
            consequences=list(data.get("consequences", [])),
            turn_id=str(data.get("turn_id", "")),
            superseded_by=data.get("superseded_by"),
            causal_parent_id=data.get("causal_parent_id"),
            evidence_snippets=list(data.get("evidence_snippets", [])),
            tags=list(data.get("tags", [])),
        )


@dataclass
class AntiPatternRecord:
    """Deprecated or superseded approach preserved as a pitfall warning."""

    topic: str
    abandoned_proposal: str
    pitfall_reason: str
    recommended_alternative: str
    turn_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AntiPatternRecord:
        return cls(
            topic=str(data.get("topic", "")),
            abandoned_proposal=str(data.get("abandoned_proposal", "")),
            pitfall_reason=str(data.get("pitfall_reason", "")),
            recommended_alternative=str(data.get("recommended_alternative", "")),
            turn_id=data.get("turn_id"),
        )


@dataclass
class AnchorRecord:
    """Terminal anchor (final test pass, user confirmation, committed code)."""

    anchor_type: AnchorType
    turn_id: str
    description: str
    evidence: str = ""
    causal_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_type": self.anchor_type.value if isinstance(self.anchor_type, AnchorType) else str(self.anchor_type),
            "turn_id": self.turn_id,
            "description": self.description,
            "evidence": self.evidence,
            "causal_chain": self.causal_chain,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AnchorRecord:
        raw_type = data.get("anchor_type", "test_verified")
        try:
            anchor_type = AnchorType(raw_type)
        except ValueError:
            anchor_type = AnchorType.TEST_VERIFIED

        return cls(
            anchor_type=anchor_type,
            turn_id=str(data.get("turn_id", "")),
            description=str(data.get("description", "")),
            evidence=str(data.get("evidence", "")),
            causal_chain=list(data.get("causal_chain", [])),
        )


@dataclass
class DistillationResult:
    """Complete outcome of the programmatic session distillation pipeline."""

    session_id: str
    provider: str
    raw_turns_count: int
    cleaned_turns: List[UnifiedTurn] = field(default_factory=list)
    decisions: List[DecisionEntity] = field(default_factory=list)
    anchors: List[AnchorRecord] = field(default_factory=list)
    anti_patterns: List[AntiPatternRecord] = field(default_factory=list)
    open_tasks: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider": self.provider,
            "raw_turns_count": self.raw_turns_count,
            "cleaned_turns_count": len(self.cleaned_turns),
            "decisions": [d.to_dict() for d in self.decisions],
            "anchors": [a.to_dict() for a in self.anchors],
            "anti_patterns": [ap.to_dict() for ap in self.anti_patterns],
            "open_tasks": self.open_tasks,
            "metrics": self.metrics,
        }
