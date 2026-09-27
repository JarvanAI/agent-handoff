"""Claude Code session log adapter.

Parses ~/.claude/projects/<slug>/<session_id>.jsonl and ~/.claude/history.jsonl
supporting ToolUse, ToolResult, BashOutput, and branch selection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from agent_handoff.adapters.base import BaseSessionAdapter
from agent_handoff.models import (
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
    UnifiedTurn,
)


class ClaudeCodeAdapter(BaseSessionAdapter):
    """Adapter for Claude Code logs and transcripts."""

    @property
    def provider_name(self) -> str:
        return "claude-code"

    def _find_session_file(self, path_or_id: Union[str, Path]) -> Tuple[Path, str]:
        p = Path(path_or_id).expanduser()
        if p.is_file():
            return p, p.stem

        session_id = str(path_or_id).strip()
        claude_projects = Path("~/.claude/projects").expanduser()
        if claude_projects.is_dir():
            for f in claude_projects.rglob("*.jsonl"):
                if f.stem == session_id or session_id in f.name:
                    return f, session_id

        # Check history.jsonl
        history = Path("~/.claude/history.jsonl").expanduser()
        if history.is_file():
            return history, session_id

        return p, session_id

    def _extract_blocks(self, raw_content: Any) -> Tuple[str, List[ToolCallRecord], List[ToolResultRecord]]:
        """Extract text, tool_use, and tool_result from Claude content blocks."""
        texts: List[str] = []
        tool_calls: List[ToolCallRecord] = []
        tool_results: List[ToolResultRecord] = []

        if isinstance(raw_content, str):
            return raw_content, [], []

        if isinstance(raw_content, list):
            for block in raw_content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    t = block.get("text", "")
                    if t:
                        texts.append(t)
                elif btype == "tool_use":
                    tool_calls.append(
                        ToolCallRecord(
                            tool_name=block.get("name", "unknown_tool"),
                            tool_args=block.get("input", {}),
                            call_id=block.get("id"),
                        )
                    )
                elif btype == "tool_result":
                    content_val = block.get("content", "")
                    if isinstance(content_val, list):
                        content_val = "\n".join(
                            str(c.get("text", c)) if isinstance(c, dict) else str(c)
                            for c in content_val
                        )
                    tool_results.append(
                        ToolResultRecord(
                            tool_name=block.get("tool_name"),
                            content=str(content_val),
                            status="error" if block.get("is_error") else "success",
                            call_id=block.get("tool_use_id"),
                        )
                    )

        return "\n".join(texts), tool_calls, tool_results

    def parse_trajectory(self, path_or_id: Union[str, Path]) -> List[UnifiedTurn]:
        file_path, session_id = self._find_session_file(path_or_id)
        if not file_path.is_file():
            raise FileNotFoundError(f"Claude Code session file not found: {file_path}")

        records = self.load_jsonl(file_path)
        if not records:
            return []

        # Check if this is history.jsonl
        if file_path.name == "history.jsonl":
            return self._parse_history_jsonl(records, session_id)

        # Detect active leafUuid if present
        leaf_uuid: Optional[str] = None
        for r in reversed(records):
            if r.get("type") == "last-prompt" and r.get("leafUuid"):
                leaf_uuid = r["leafUuid"]
                break

        # Index nodes by uuid for branch pruning if leaf_uuid exists
        nodes_by_uuid: Dict[str, Dict[str, Any]] = {}
        for r in records:
            uid = r.get("uuid")
            if uid:
                nodes_by_uuid[uid] = r

        active_uuids: Optional[Set[str]] = None
        if leaf_uuid and leaf_uuid in nodes_by_uuid:
            active_uuids = set()
            curr: Optional[str] = leaf_uuid
            while curr and curr in nodes_by_uuid:
                active_uuids.add(curr)
                curr = nodes_by_uuid[curr].get("parentUuid")

        unified_turns: List[UnifiedTurn] = []

        for idx, r in enumerate(records):
            uid = r.get("uuid")
            if active_uuids is not None and uid and uid not in active_uuids:
                continue

            rec_type = r.get("type")
            ts = self.normalize_timestamp(r.get("timestamp"))

            # User or Assistant message
            if rec_type in ("user", "assistant"):
                role = TurnRole.USER if rec_type == "user" else TurnRole.ASSISTANT
                msg = r.get("message", {})
                raw_content = msg.get("content") if isinstance(msg, dict) else r.get("content")

                text, tool_calls, tool_results = self._extract_blocks(raw_content)

                turn = UnifiedTurn(
                    turn_id=uid or f"turn_{idx}",
                    session_id=r.get("sessionId", session_id),
                    timestamp=ts,
                    role=role,
                    content=text,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    metadata={"uuid": uid, "parentUuid": r.get("parentUuid"), "type": rec_type},
                )
                unified_turns.append(turn)

            # Attachment records (e.g. hook outputs or notifications)
            elif rec_type == "attachment":
                attachment = r.get("attachment", {})
                att_type = attachment.get("type", "")
                if att_type == "task-notification" or "content" in attachment:
                    text = str(attachment.get("content", ""))
                    turn = UnifiedTurn(
                        turn_id=uid or f"turn_{idx}",
                        session_id=r.get("sessionId", session_id),
                        timestamp=ts,
                        role=TurnRole.SYSTEM,
                        content=text,
                        metadata={"attachment_type": att_type, "type": "attachment"},
                    )
                    unified_turns.append(turn)

        return unified_turns

    def _parse_history_jsonl(self, records: List[Dict[str, Any]], session_id: str) -> List[UnifiedTurn]:
        """Parse commands recorded in ~/.claude/history.jsonl."""
        turns: List[UnifiedTurn] = []
        for idx, rec in enumerate(records):
            sid = rec.get("sessionId", "")
            if session_id and sid and sid != session_id:
                continue

            text = rec.get("display", "")
            ts = self.normalize_timestamp(rec.get("timestamp"))
            turn = UnifiedTurn(
                turn_id=f"hist_{idx}",
                session_id=sid or session_id or "history",
                timestamp=ts,
                role=TurnRole.USER,
                content=text,
                metadata={"project": rec.get("project")},
            )
            turns.append(turn)
        return turns
