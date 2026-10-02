"""Grok exported conversation JSON/JSONL adapter.

Parses Grok conversation dumps, JSON exports, and live ``chat_history.jsonl``
sessions under ``~/.grok/sessions``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

from agent_handoff.adapters.base import BaseSessionAdapter
from agent_handoff.models import ToolCallRecord, TurnRole, UnifiedTurn

_LIVE_TYPES = {"user", "assistant", "system", "reasoning", "tool_result"}


class GrokAdapter(BaseSessionAdapter):
    """Adapter for xAI Grok exported chats and live CLI sessions."""

    @property
    def provider_name(self) -> str:
        return "grok"

    def _resolve_file(self, path_or_id: Union[str, Path]) -> Path:
        p = Path(path_or_id).expanduser()
        if p.is_file():
            return p
        if p.is_dir():
            live = p / "chat_history.jsonl"
            if live.is_file():
                return live
            raise FileNotFoundError(f"Grok session directory has no chat_history.jsonl: {p}")

        token = str(path_or_id).strip()
        root = Path("~/.grok/sessions").expanduser()
        if token and root.is_dir():
            matches = [
                cand / "chat_history.jsonl"
                for cand in root.rglob(token)
                if cand.is_dir() and (cand / "chat_history.jsonl").is_file()
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise FileNotFoundError(f"Multiple Grok sessions match {token}")
        raise FileNotFoundError(f"Grok export file not found: {p}")

    @staticmethod
    def _block_text(raw_content: Any) -> str:
        if isinstance(raw_content, list):
            parts: List[str] = []
            for block in raw_content:
                if isinstance(block, dict):
                    if block.get("type") in ("tool_use", "tool_result", "reasoning"):
                        continue
                    parts.append(str(block.get("text") or block.get("content") or ""))
                else:
                    parts.append(str(block))
            return "\n".join(parts).strip()
        if raw_content is None:
            return ""
        return str(raw_content).strip()

    @staticmethod
    def _tool_calls(msg: Dict[str, Any]) -> List[ToolCallRecord]:
        raw_calls = msg.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            return []
        calls: List[ToolCallRecord] = []
        for call in raw_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = str(call.get("name") or function.get("name") or "tool")
            args = call.get("arguments") or call.get("args") or function.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"raw": args}
            if not isinstance(args, dict):
                args = {"raw": args}
            calls.append(
                ToolCallRecord(
                    tool_name=name,
                    tool_args=args,
                    call_id=call.get("id") or call.get("tool_call_id"),
                )
            )
        return calls

    def parse_trajectory(self, path_or_id: Union[str, Path]) -> List[UnifiedTurn]:
        p = self._resolve_file(path_or_id)
        session_id = p.parent.name if p.name == "chat_history.jsonl" else p.stem

        data: Any
        if p.suffix == ".jsonl":
            data = self.load_jsonl(p)
        else:
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
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

            kind = str(msg.get("type") or "").lower()
            raw_sender = str(
                msg.get("sender")
                or msg.get("role")
                or msg.get("author")
                or ""
            ).lower()

            if kind in _LIVE_TYPES:
                label = kind
            else:
                label = raw_sender or "human"

            if label in ("human", "user"):
                role = TurnRole.USER
            elif label in ("assistant", "grok", "bot", "model"):
                role = TurnRole.ASSISTANT
            elif label == "tool_result":
                role = TurnRole.TOOL
            elif label in ("system", "system_prompt", "reasoning"):
                role = TurnRole.SYSTEM
            else:
                role = TurnRole.USER

            content = self._block_text(
                msg.get("text")
                if msg.get("text") is not None
                else msg.get("content")
                if msg.get("content") is not None
                else msg.get("message")
            )
            # Reasoning bodies are encrypted. Keep the marker, not the ciphertext.
            if label == "reasoning":
                content = ""

            raw_ts = (
                msg.get("create_time")
                or msg.get("timestamp")
                or msg.get("createdAt")
                or msg.get("time")
            )
            ts = self.normalize_timestamp(raw_ts)
            turn_id = str(msg.get("message_id") or msg.get("id") or f"grok_turn_{idx+1}")
            metadata: Dict[str, Any] = {"sender": label}
            if msg.get("model") or msg.get("model_id"):
                metadata["model"] = msg.get("model") or msg.get("model_id")
            if kind:
                metadata["type"] = kind
            if msg.get("synthetic_reason"):
                metadata["synthetic_reason"] = msg.get("synthetic_reason")

            unified_turns.append(
                UnifiedTurn(
                    turn_id=turn_id,
                    session_id=session_id,
                    timestamp=ts,
                    role=role,
                    content=content,
                    tool_calls=self._tool_calls(msg) if role == TurnRole.ASSISTANT else [],
                    metadata=metadata,
                )
            )

        return unified_turns
