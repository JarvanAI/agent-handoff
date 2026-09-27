"""Cursor workspace chat and composer session adapter.

Supports Cursor chat directory structures (store.db SQLite, meta.json, prompt_history.json)
as well as exported JSON/JSONL conversation formats.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from agent_handoff.adapters.base import BaseSessionAdapter
from agent_handoff.models import (
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
    UnifiedTurn,
)


class CursorAdapter(BaseSessionAdapter):
    """Adapter for Cursor workspace chats and composer sessions."""

    @property
    def provider_name(self) -> str:
        return "cursor"

    def _resolve_target(self, path_or_id: Union[str, Path]) -> Tuple[Optional[Path], Optional[Path], Optional[Path], str]:
        """Resolve store.db, meta.json, prompt_history.json, or direct json file."""
        p = Path(path_or_id).expanduser()

        # If direct file
        if p.is_file():
            if p.name == "store.db":
                meta = p.parent / "meta.json"
                history = p.parent / "prompt_history.json"
                return p, (meta if meta.is_file() else None), (history if history.is_file() else None), p.parent.name
            return p, None, None, p.stem

        # If directory
        if p.is_dir():
            db = p / "store.db"
            meta = p / "meta.json"
            history = p / "prompt_history.json"
            return (db if db.is_file() else None), (meta if meta.is_file() else None), (history if history.is_file() else None), p.name

        # If session ID string given, search ~/.cursor/chats/
        cursor_chats = Path("~/.cursor/chats").expanduser()
        if cursor_chats.is_dir():
            target_str = str(path_or_id).strip()
            for cand_dir in cursor_chats.rglob(target_str):
                if cand_dir.is_dir() and (cand_dir / "store.db").is_file():
                    db = cand_dir / "store.db"
                    meta = cand_dir / "meta.json"
                    history = cand_dir / "prompt_history.json"
                    return db, (meta if meta.is_file() else None), (history if history.is_file() else None), cand_dir.name

        return None, None, None, str(path_or_id)

    def _extract_content_text(self, content_obj: Any) -> str:
        if isinstance(content_obj, str):
            return content_obj
        if isinstance(content_obj, list):
            texts: List[str] = []
            for item in content_obj:
                if isinstance(item, dict):
                    t = item.get("text") or item.get("content") or ""
                    if t:
                        texts.append(str(t))
                elif isinstance(item, str):
                    texts.append(item)
            return "\n".join(texts)
        return ""

    def parse_trajectory(self, path_or_id: Union[str, Path]) -> List[UnifiedTurn]:
        target_path, meta_path, history_path, session_id = self._resolve_target(path_or_id)

        if not target_path or not target_path.exists():
            raise FileNotFoundError(f"Cursor session not found: {path_or_id}")

        meta: Dict[str, Any] = {}
        if meta_path and meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # 1. Parse store.db (SQLite)
        if target_path.name == "store.db" or target_path.suffix == ".db":
            return self._parse_sqlite_store(target_path, meta, history_path, session_id)

        # 2. Parse JSON/JSONL export
        return self._parse_json_export(target_path, meta, session_id)

    def _parse_sqlite_store(
        self,
        db_path: Path,
        meta: Dict[str, Any],
        history_path: Optional[Path],
        session_id: str,
    ) -> List[UnifiedTurn]:
        turns: List[UnifiedTurn] = []
        created_at_ms = meta.get("createdAtMs")
        base_ts = self.normalize_timestamp(created_at_ms)

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT id, data FROM blobs ORDER BY rowid ASC")
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            # If SQLite locked or unreadable, fall back to prompt_history
            rows = []

        turn_counter = 0
        for blob_id, blob_data in rows:
            # blob_data may be bytes or str
            if isinstance(blob_data, bytes):
                try:
                    text_data = blob_data.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            else:
                text_data = str(blob_data)

            # Look for JSON records containing "role"
            if '"role":' in text_data and ('"user"' in text_data or '"assistant"' in text_data or '"system"' in text_data):
                # Try to extract the JSON segment
                start = text_data.find("{")
                end = text_data.rfind("}")
                if start != -1 and end != -1 and end > start:
                    candidate = text_data[start : end + 1]
                    try:
                        obj = json.loads(candidate)
                        raw_role = obj.get("role")
                        if raw_role in ("user", "assistant", "system"):
                            role = (
                                TurnRole.USER
                                if raw_role == "user"
                                else TurnRole.ASSISTANT
                                if raw_role == "assistant"
                                else TurnRole.SYSTEM
                            )
                            content = self._extract_content_text(obj.get("content"))
                            if content.strip():
                                turn_counter += 1
                                turn = UnifiedTurn(
                                    turn_id=f"cursor_turn_{turn_counter}",
                                    session_id=session_id,
                                    timestamp=base_ts,
                                    role=role,
                                    content=content,
                                    metadata={"blob_id": blob_id, "title": meta.get("title")},
                                )
                                turns.append(turn)
                    except Exception:
                        pass

        # If no blobs extracted but prompt_history.json exists, load prompts
        if not turns and history_path and history_path.is_file():
            try:
                prompts = json.loads(history_path.read_text(encoding="utf-8"))
                if isinstance(prompts, list):
                    for idx, p in enumerate(prompts):
                        turn = UnifiedTurn(
                            turn_id=f"cursor_prompt_{idx+1}",
                            session_id=session_id,
                            timestamp=base_ts,
                            role=TurnRole.USER,
                            content=str(p),
                            metadata={"source": "prompt_history"},
                        )
                        turns.append(turn)
            except Exception:
                pass

        return turns

    def _parse_json_export(
        self,
        json_path: Path,
        meta: Dict[str, Any],
        session_id: str,
    ) -> List[UnifiedTurn]:
        turns: List[UnifiedTurn] = []
        try:
            content = json_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception:
            # Try JSONL
            records = self.load_jsonl(json_path)
            data = records

        items: List[Dict[str, Any]] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for k in ("conversation", "messages", "turns", "history"):
                if k in data and isinstance(data[k], list):
                    items = data[k]
                    break

        for idx, item in enumerate(items):
            raw_role = str(item.get("role") or item.get("sender") or "user").lower()
            role = (
                TurnRole.USER
                if raw_role in ("user", "human")
                else TurnRole.ASSISTANT
                if raw_role in ("assistant", "model", "bot", "ai")
                else TurnRole.SYSTEM
            )
            text = self._extract_content_text(item.get("content") or item.get("text") or item.get("message"))
            ts = self.normalize_timestamp(item.get("timestamp") or item.get("createdAt"))

            turn = UnifiedTurn(
                turn_id=item.get("id") or f"cursor_turn_{idx+1}",
                session_id=session_id,
                timestamp=ts,
                role=role,
                content=text,
                metadata=item.get("metadata", {}),
            )
            turns.append(turn)

        return turns
