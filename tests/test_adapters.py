"""Tests for all 5 session adapters."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from handoff.adapters import (
    AntigravityAdapter,
    ClaudeCodeAdapter,
    CodexAdapter,
    CursorAdapter,
    GrokAdapter,
    detect_adapter,
    get_adapter,
)
from handoff.models import TurnRole


class TestAdapters(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_adapter_factory(self) -> None:
        self.assertIsInstance(get_adapter("antigravity"), AntigravityAdapter)
        self.assertIsInstance(get_adapter("claude-code"), ClaudeCodeAdapter)
        self.assertIsInstance(get_adapter("codex"), CodexAdapter)
        self.assertIsInstance(get_adapter("cursor"), CursorAdapter)
        self.assertIsInstance(get_adapter("grok"), GrokAdapter)

    def test_antigravity_adapter(self) -> None:
        session_dir = self.tmp_dir / "antigravity_session"
        logs_dir = session_dir / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        transcript = logs_dir / "transcript.jsonl"
        full = logs_dir / "transcript_full.jsonl"

        records = [
            {"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Hello Antigravity"},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I will inspect files", "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "/app/main.py"}}]},
            {"step_index": 3, "source": "MODEL", "type": "GENERIC", "content": "file contents here..."},
        ]
        full_records = [
            {"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Hello Antigravity"},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I will inspect files", "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "/app/main.py"}}]},
            {"step_index": 3, "source": "MODEL", "type": "GENERIC", "content": "full file contents here..."},
        ]

        with open(transcript, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        with open(full, "w", encoding="utf-8") as f:
            for r in full_records:
                f.write(json.dumps(r) + "\n")

        adapter = AntigravityAdapter()
        turns = adapter.parse_trajectory(session_dir)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0].role, TurnRole.USER)
        self.assertEqual(turns[1].role, TurnRole.ASSISTANT)
        self.assertEqual(turns[1].tool_calls[0].tool_name, "view_file")

    def test_claude_code_adapter(self) -> None:
        file_path = self.tmp_dir / "claude_session.jsonl"
        rows = [
            {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "c1", "message": {"content": "Build tool"}},
            {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": "c1", "message": {"content": [{"type": "text", "text": "Building tool now"}, {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "cargo build"}}]}},
            {"type": "user", "uuid": "u2", "parentUuid": "a1", "sessionId": "c1", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Compiling...\nFinished"}]}},
            {"type": "last-prompt", "leafUuid": "u2"},
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        adapter = ClaudeCodeAdapter()
        turns = adapter.parse_trajectory(file_path)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0].content, "Build tool")
        self.assertEqual(turns[1].tool_calls[0].tool_name, "Bash")
        self.assertEqual(turns[2].tool_results[0].content, "Compiling...\nFinished")

    def test_codex_adapter(self) -> None:
        file_path = self.tmp_dir / "rollout-2026-codex.jsonl"
        rows = [
            {"type": "session_meta", "payload": {"id": "codex-123"}},
            {"type": "response_item", "timestamp": "2026-03-11T04:24:18Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hello Codex"}]}},
            {"type": "response_item", "timestamp": "2026-03-11T04:24:19Z", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Hi there!"}]}},
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

        adapter = CodexAdapter()
        turns = adapter.parse_trajectory(file_path)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].role, TurnRole.USER)
        self.assertEqual(turns[0].content, "Hello Codex")
        self.assertEqual(turns[1].role, TurnRole.ASSISTANT)
        self.assertEqual(turns[1].content, "Hi there!")

    def test_cursor_adapter(self) -> None:
        cursor_dir = self.tmp_dir / "cursor_session"
        cursor_dir.mkdir()
        db_path = cursor_dir / "store.db"
        meta_path = cursor_dir / "meta.json"
        meta_path.write_text(json.dumps({"title": "Test Chat", "createdAtMs": 1789446464000}))

        # Create sqlite db
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE blobs (id TEXT, data BLOB)")
        cur.execute("INSERT INTO blobs VALUES ('b1', ?)", [b'{"role": "user", "content": "How to optimize Python code?"}'])
        cur.execute("INSERT INTO blobs VALUES ('b2', ?)", [b'{"role": "assistant", "content": "Use vectorization or C extensions."}'])
        conn.commit()
        conn.close()

        adapter = CursorAdapter()
        turns = adapter.parse_trajectory(cursor_dir)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].role, TurnRole.USER)
        self.assertIn("optimize", turns[0].content)
        self.assertEqual(turns[1].role, TurnRole.ASSISTANT)

    def test_grok_adapter(self) -> None:
        file_path = self.tmp_dir / "grok_export.json"
        grok_data = {
            "conversation_id": "grok-session-001",
            "messages": [
                {"sender": "human", "text": "What is the speed of light?", "timestamp": "2026-09-22T00:00:00Z"},
                {"sender": "grok", "text": "About 300,000 km/s.", "timestamp": "2026-09-22T00:00:01Z"},
            ],
        }
        file_path.write_text(json.dumps(grok_data), encoding="utf-8")

        adapter = GrokAdapter()
        turns = adapter.parse_trajectory(file_path)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].role, TurnRole.USER)
        self.assertEqual(turns[1].role, TurnRole.ASSISTANT)
        self.assertIn("300,000", turns[1].content)


if __name__ == "__main__":
    unittest.main()
