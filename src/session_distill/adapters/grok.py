"""Grok exported conversation JSON/JSONL adapter.

Parses Grok conversation dumps, JSON exports, and API turn structures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from session_distill.adapters.base import BaseSessionAdapter
from session_distill.models import TurnRole, UnifiedTurn


class GrokAdapter(BaseSessionAdapter):
    """Adapter for xAI Grok exported chat sessions."""

    @property
    def provider_name(self) -> str:
        return "grok"

    def parse_trajectory(self, path_or_id: Union[str, Path]) -> List[UnifiedTurn]:
        p = Path(path_or_id).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Grok export file not found: {p}")

        raw_text = p.read_text(encoding="utf-8", errors="replace")
        session_id = p.stem

        data: Any = None
        try:
            data = json.loads(raw_text)
        except Exception:
            # Fall back to JSONL
            data = self.load_jsonl(p)

        messages: List[Dict[str, Any]] = []
        if isinstance(data, list):
            messages = data
        elif isinstance(data, dict):
            session_id = data.get("conversation_id") or data.get("id") or session_id
            for key in ("messages", "turns", "responses", "conversation"):
                if key in data and isinstance(data[key], list):
                    messages = data[key]
                    break

        unified_turns: List[UnifiedTurn] = []

        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue

            raw_sender = str(
                msg.get("sender")
                or msg.get("role")
                or msg.get("author")
                or "human"
            ).lower()

            if raw_sender in ("human", "user"):
                role = TurnRole.USER
            elif raw_sender in ("assistant", "grok", "bot", "model"):
                role = TurnRole.ASSISTANT
            elif raw_sender in ("system", "system_prompt"):
                role = TurnRole.SYSTEM
            else:
                role = TurnRole.USER

            raw_content = (
                msg.get("text")
                or msg.get("content")
                or msg.get("message")
                or ""
            )
            if isinstance(raw_content, list):
                raw_content = "\n".join(
                    str(b.get("text", b)) if isinstance(b, dict) else str(b)
                    for b in raw_content
                )
            content = str(raw_content).strip()

            raw_ts = (
                msg.get("create_time")
                or msg.get("timestamp")
                or msg.get("createdAt")
                or msg.get("time")
            )
            ts = self.normalize_timestamp(raw_ts)

            turn_id = str(msg.get("message_id") or msg.get("id") or f"grok_turn_{idx+1}")

            turn = UnifiedTurn(
                turn_id=turn_id,
                session_id=session_id,
                timestamp=ts,
                role=role,
                content=content,
                metadata={
                    "model": msg.get("model"),
                    "sender": raw_sender,
                },
            )
            unified_turns.append(turn)

        return unified_turns
