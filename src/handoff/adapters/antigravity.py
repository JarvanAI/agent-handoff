"""Antigravity session log adapter.

Parses ~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript.jsonl
with automatic penetration of transcript_full.jsonl to restore truncated content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from handoff.adapters.base import BaseSessionAdapter
from handoff.core.penetrator import LogPenetrator
from handoff.models import (
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
    UnifiedTurn,
)


class AntigravityAdapter(BaseSessionAdapter):
    """Adapter for Google Antigravity Agent logs."""

    @property
    def provider_name(self) -> str:
        return "antigravity"

    def _resolve_paths(self, path_or_id: Union[str, Path]) -> Tuple[Path, Optional[Path], str]:
        """Resolve transcript.jsonl, transcript_full.jsonl, and session_id."""
        raw = str(path_or_id).strip()
        p = Path(raw).expanduser()

        session_id = p.name

        # If direct file given
        if p.is_file():
            transcript_path = p
            session_dir = p.parent.parent.parent if p.name in ("transcript.jsonl", "transcript_full.jsonl") else p.parent
            session_id = session_dir.name
            full_path = p.parent / "transcript_full.jsonl"
            return transcript_path, (full_path if full_path.is_file() else None), session_id

        # If directory given
        if p.is_dir():
            transcript_path = p / ".system_generated" / "logs" / "transcript.jsonl"
            if not transcript_path.is_file():
                transcript_path = p / "transcript.jsonl"
            full_path = p / ".system_generated" / "logs" / "transcript_full.jsonl"
            if not full_path.is_file():
                full_path = p / "transcript_full.jsonl"
            return transcript_path, (full_path if full_path.is_file() else None), p.name

        # If UUID / session ID string given
        brain_dir = Path("~/.gemini/antigravity-cli/brain").expanduser() / raw
        if brain_dir.is_dir():
            transcript_path = brain_dir / ".system_generated" / "logs" / "transcript.jsonl"
            full_path = brain_dir / ".system_generated" / "logs" / "transcript_full.jsonl"
            return transcript_path, (full_path if full_path.is_file() else None), raw

        # Fallback to direct path
        return p, None, raw

    def parse_trajectory(self, path_or_id: Union[str, Path]) -> List[UnifiedTurn]:
        transcript_path, full_path, session_id = self._resolve_paths(path_or_id)
        if not transcript_path.is_file():
            raise FileNotFoundError(f"Antigravity transcript not found: {transcript_path}")

        penetrator = LogPenetrator(full_path) if full_path else None
        records = self.load_jsonl(transcript_path)

        unified_turns: List[UnifiedTurn] = []
        last_assistant_turn: Optional[UnifiedTurn] = None

        for idx, rec in enumerate(records):
            was_truncated = bool(rec.get("truncated_fields"))
            # Restore truncated fields if penetrator is active
            if penetrator and was_truncated:
                rec = penetrator.penetrate_record(rec, line_no=idx)

            step_idx = rec.get("step_index", idx)
            source = rec.get("source", "MODEL")
            turn_type = rec.get("type", "GENERIC")
            created_at = self.normalize_timestamp(rec.get("created_at"))
            status = rec.get("status", "DONE")
            content = str(rec.get("content", "") or "")
            if penetrator:
                content = penetrator.clean_truncation_artifacts(content)

            raw_tool_calls = rec.get("tool_calls", [])
            tool_calls = [
                ToolCallRecord(
                    tool_name=tc.get("name", "unknown_tool"),
                    tool_args=tc.get("args", {}),
                    call_id=tc.get("id"),
                )
                for tc in raw_tool_calls
                if isinstance(tc, dict)
            ]

            metadata = {
                "step_index": step_idx,
                "source": source,
                "type": turn_type,
                "status": status,
            }
            if was_truncated:
                metadata["penetrated"] = True
            if "thinking" in rec and rec["thinking"]:
                metadata["thinking"] = rec["thinking"]

            # Map roles
            if source == "USER_EXPLICIT" or turn_type == "USER_INPUT":
                role = TurnRole.USER
                turn = UnifiedTurn(
                    turn_id=f"step_{step_idx}",
                    session_id=session_id,
                    timestamp=created_at,
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    metadata=metadata,
                )
                unified_turns.append(turn)
                last_assistant_turn = None

            elif turn_type == "PLANNER_RESPONSE" or source == "MODEL":
                role = TurnRole.ASSISTANT
                turn = UnifiedTurn(
                    turn_id=f"step_{step_idx}",
                    session_id=session_id,
                    timestamp=created_at,
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    metadata=metadata,
                )
                unified_turns.append(turn)
                last_assistant_turn = turn

            elif turn_type in ("GENERIC", "ERROR_MESSAGE") or source == "SYSTEM":
                # Tool execution result or system message
                role = TurnRole.TOOL if turn_type == "GENERIC" else TurnRole.SYSTEM
                tr = ToolResultRecord(
                    tool_name=last_assistant_turn.tool_calls[-1].tool_name if (last_assistant_turn and last_assistant_turn.tool_calls) else None,
                    content=content,
                    status="error" if turn_type == "ERROR_MESSAGE" else status,
                    call_id=last_assistant_turn.tool_calls[-1].call_id if (last_assistant_turn and last_assistant_turn.tool_calls) else None,
                )
                # Also attach result directly to last assistant turn if available
                if last_assistant_turn is not None and not last_assistant_turn.tool_results:
                    last_assistant_turn.tool_results.append(tr)

                turn = UnifiedTurn(
                    turn_id=f"step_{step_idx}",
                    session_id=session_id,
                    timestamp=created_at,
                    role=role,
                    content=content,
                    tool_results=[tr],
                    metadata=metadata,
                )
                unified_turns.append(turn)

            else:
                # Other generic types
                turn = UnifiedTurn(
                    turn_id=f"step_{step_idx}",
                    session_id=session_id,
                    timestamp=created_at,
                    role=TurnRole.SYSTEM,
                    content=content,
                    tool_calls=tool_calls,
                    metadata=metadata,
                )
                unified_turns.append(turn)

        return unified_turns
