"""Central programmatic distillation engine orchestrating adapters and core modules."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Union

from agent_handoff.adapters import BaseSessionAdapter, detect_adapter, get_adapter
from agent_handoff.core.anchor_engine import AnchorEngine
from agent_handoff.core.noise_filter import NoiseFilter
from agent_handoff.core.state_machine import DecisionStateMachine
from agent_handoff.models import DistillationResult, UnifiedTurn


class DistillationEngine:
    """Zero-LLM deterministic distillation engine."""

    def __init__(
        self,
        noise_filter: Optional[NoiseFilter] = None,
        state_machine: Optional[DecisionStateMachine] = None,
        anchor_engine: Optional[AnchorEngine] = None,
    ) -> None:
        self.noise_filter = noise_filter or NoiseFilter()
        self.state_machine = state_machine or DecisionStateMachine()
        self.anchor_engine = anchor_engine or AnchorEngine()

    def distill(
        self,
        path_or_id: Union[str, Path],
        provider: Optional[str] = None,
    ) -> DistillationResult:
        """Run the complete distillation pipeline on a session.

        Args:
            path_or_id: File path, directory, or session ID.
            provider: Optional provider name ('antigravity', 'claude-code', 'codex', 'cursor', 'grok').
                      If omitted, automatically detected.

        Returns:
            DistillationResult containing cleaned turns, decisions, anchors, and anti-patterns.
        """
        started = time.perf_counter()
        adapter, session_id, raw_turns, cleaned_turns, filter_stats, _ = self._load_dialogue(
            path_or_id, provider
        )
        raw_count = len(raw_turns)

        # 4. FSM Decision extraction & Latest-Wins arbitration
        fsm = DecisionStateMachine()
        decisions, anti_patterns = fsm.run(cleaned_turns)

        # 5. Reverse endpoint anchoring & causal chain backfill
        anchors, open_tasks = self.anchor_engine.analyze(cleaned_turns, decisions)

        metrics: Dict[str, Any] = {
            "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "raw_turns_count": raw_count,
            "cleaned_turns_count": len(cleaned_turns),
            "decisions_count": len(decisions),
            "anti_patterns_count": len(anti_patterns),
            "anchors_count": len(anchors),
            "filter_stats": filter_stats,
        }

        return DistillationResult(
            session_id=session_id,
            provider=adapter.provider_name,
            raw_turns_count=raw_count,
            cleaned_turns=cleaned_turns,
            decisions=decisions,
            anchors=anchors,
            anti_patterns=anti_patterns,
            open_tasks=open_tasks,
            metrics=metrics,
        )

    def read_dialogue(
        self,
        path_or_id: Union[str, Path],
        provider: Optional[str] = None,
    ) -> DistillationResult:
        """Crop a session to user messages and public replies.

        Does not extract decisions. session-continue prints this transcript.
        """
        adapter, session_id, raw_turns, cleaned_turns, filter_stats, elapsed_ms = self._load_dialogue(
            path_or_id, provider
        )
        return DistillationResult(
            session_id=session_id,
            provider=adapter.provider_name,
            raw_turns_count=len(raw_turns),
            cleaned_turns=cleaned_turns,
            metrics={
                "duration_ms": round(elapsed_ms, 2),
                "raw_turns_count": len(raw_turns),
                "cleaned_turns_count": len(cleaned_turns),
                "filter_stats": filter_stats,
            },
        )

    def _load_dialogue(
        self,
        path_or_id: Union[str, Path],
        provider: Optional[str],
    ) -> tuple:
        """Parse one session and apply the shared dialogue crop."""
        start_time = time.perf_counter()
        if provider:
            adapter: BaseSessionAdapter = get_adapter(provider)
        else:
            adapter = detect_adapter(path_or_id)

        raw_turns: List[UnifiedTurn] = adapter.parse_trajectory(path_or_id)
        session_id = raw_turns[0].session_id if raw_turns else Path(path_or_id).stem
        cleaned_turns, filter_stats = self.noise_filter.crop_dialogue(raw_turns)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        return adapter, session_id, raw_turns, cleaned_turns, filter_stats, elapsed_ms
