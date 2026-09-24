"""Codex session log adapter.

Parses ~/.codex/archived_sessions/*.jsonl and ~/.codex/history.jsonl
supporting developer/user/assistant response items, tool calls, and event messages.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from handoff.adapters.base import BaseSessionAdapter
from handoff.models import (
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
    UnifiedTurn,
)


class CodexAdapter(BaseSessionAdapter):
    """Adapter for OpenAI Codex CLI logs and archived sessions."""

    @property
    def provider_name(self) -> str:
        return "codex"

    def _find_session_file(self, path_or_id: Union[str, Path]) -> Tuple[Path, str]:
        p = Path(path_or_id).expanduser()
        if p.is_file():
            return p, p.stem

        session_id = str(path_or_id).strip()
        archived_dir = Path("~/.codex/archived_sessions").expanduser()
        if archived_dir.is_dir():
            for f in archived_dir.glob("*.jsonl"):
                if session_id in f.name:
                    return f, session_id

        history = Path("~/.codex/history.jsonl").expanduser()
        if history.is_file():
            return history, session_id

        return p, session_id

    def _extract_content(self, content_obj: Any) -> str:
        if isinstance(content_obj, str):
            return content_obj
        if isinstance(content_obj, list):
            texts: List[str] = []
            for item in content_obj:
                if isinstance(item, dict):
                    t = item.get("text", "")
                    if t:
                        texts.append(t)
                elif isinstance(item, str):
                    texts.append(item)
            return "\n".join(texts)
        return ""

    def parse_trajectory(self, path_or_id: Union[str, Path]) -> List[UnifiedTurn]:
        file_path, session_id = self._find_session_file(path_or_id)
        if not file_path.is_file():
            raise FileNotFoundError(f"Codex session file not found: {file_path}")

        records = self.load_jsonl(file_path)
        if not records:
            return []

        # Check if history.jsonl
        if file_path.name == "history.jsonl":
            return self._parse_history_jsonl(records, session_id)

        unified_turns: List[UnifiedTurn] = []
        turn_counter = 0

        for rec in records:
            rec_type = rec.get("type")
            ts = self.normalize_timestamp(rec.get("timestamp"))
            payload = rec.get("payload", {})
            if not isinstance(payload, dict):
                continue

            if rec_type == "session_meta":
                session_id = payload.get("id", session_id)
                continue

            # response_item
            if rec_type == "response_item":
                payload_type = payload.get("type")
                if payload_type == "message":
                    raw_role = payload.get("role", "assistant")
                    if raw_role == "developer":
                        role = TurnRole.SYSTEM
                    elif raw_role == "user":
                        role = TurnRole.USER
                    else:
                        role = TurnRole.ASSISTANT

                    content = self._extract_content(payload.get("content"))
                    turn_counter += 1
                    turn = UnifiedTurn(
                        turn_id=f"codex_turn_{turn_counter}",
                        session_id=session_id,
                        timestamp=ts,
                        role=role,
                        content=content,
                        metadata={"raw_role": raw_role},
                    )
                    unified_turns.append(turn)

                elif payload_type in ("function_call", "custom_tool_call", "tool_call"):
                    # Tool call executed
                    fn_name = payload.get("name") or payload.get("function", {}).get("name", "tool")
                    raw_args = payload.get("arguments") or payload.get("function", {}).get("arguments", {})
                    if isinstance(raw_args, str):
                        try:
                            raw_args = json.loads(raw_args)
                        except Exception:
                            raw_args = {"raw": raw_args}

                    tc = ToolCallRecord(tool_name=fn_name, tool_args=raw_args, call_id=payload.get("call_id"))
                    turn_counter += 1
                    turn = UnifiedTurn(
                        turn_id=f"codex_turn_{turn_counter}",
                        session_id=session_id,
                        timestamp=ts,
                        role=TurnRole.ASSISTANT,
                        content="",
                        tool_calls=[tc],
                    )
                    unified_turns.append(turn)

                elif payload_type in ("function_call_output", "tool_result"):
                    # Tool output
                    out_content = payload.get("output", "")
                    tr = ToolResultRecord(content=str(out_content), call_id=payload.get("call_id"))
                    turn_counter += 1
                    turn = UnifiedTurn(
                        turn_id=f"codex_turn_{turn_counter}",
                        session_id=session_id,
                        timestamp=ts,
                        role=TurnRole.TOOL,
                        content=str(out_content),
                        tool_results=[tr],
                    )
                    unified_turns.append(turn)

            elif rec_type == "event_msg":
                event_type = payload.get("type")
                if event_type == "user_message":
                    text = str(payload.get("message", ""))
                    turn_counter += 1
                    turn = UnifiedTurn(
                        turn_id=f"codex_turn_{turn_counter}",
                        session_id=session_id,
                        timestamp=ts,
                        role=TurnRole.USER,
                        content=text,
                    )
                    unified_turns.append(turn)
                elif event_type in ("task_complete", "task_started"):
                    turn_counter += 1
                    turn = UnifiedTurn(
                        turn_id=f"codex_turn_{turn_counter}",
                        session_id=session_id,
                        timestamp=ts,
                        role=TurnRole.SYSTEM,
                        content=f"Codex event: {event_type}",
                        metadata={"event_type": event_type, "turn_id": payload.get("turn_id")},
                    )
                    unified_turns.append(turn)

        return unified_turns

    def _parse_history_jsonl(self, records: List[Dict[str, Any]], session_id: str) -> List[UnifiedTurn]:
        turns: List[UnifiedTurn] = []
        for idx, rec in enumerate(records):
            sid = rec.get("session_id", "")
            if session_id and sid and sid != session_id:
                continue

            text = rec.get("text", "")
            ts = self.normalize_timestamp(rec.get("ts"))
            turn = UnifiedTurn(
                turn_id=f"codex_hist_{idx}",
                session_id=sid or session_id or "codex_history",
                timestamp=ts,
                role=TurnRole.USER,
                content=text,
            )
            turns.append(turn)
        return turns
