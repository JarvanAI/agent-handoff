"""session-continue prints the shared crop and session-distill does not."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_handoff.cli import continue_main, distill_main


class TestContinueCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_session(self) -> Path:
        path = self.tmp_dir / "chat_history.jsonl"
        rows = [
            {
                "type": "user",
                "content": [{"type": "text", "text": "<user_info>host</user_info><user_query>决定采用 PostgreSQL.</user_query>"}],
            },
            {
                "type": "reasoning",
                "encrypted_content": "SECRETREASONING",
                "summary": [{"type": "summary_text", "text": "private plan"}],
            },
            {
                "type": "assistant",
                "content": "",
                "tool_calls": [{"name": "read_file", "id": "c1", "arguments": {"target_file": "a.py"}}],
            },
            {"type": "tool_result", "tool_call_id": "c1", "content": "ENTIRE_FILE_DUMP_SHOULD_NOT_APPEAR"},
            {"type": "assistant", "content": "PostgreSQL stays."},
            {
                "type": "user",
                "synthetic_reason": "system_reminder",
                "content": [{"type": "text", "text": "<system-reminder>catalog</system-reminder>"}],
            },
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        return path

    def test_continue_prints_dialogue_only(self) -> None:
        path = self._write_session()
        from io import StringIO
        import contextlib

        stdout = StringIO()
        with contextlib.redirect_stdout(stdout):
            code = continue_main(["--from", "grok", "--file", str(path)])
        text = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[user]\n决定采用 PostgreSQL.", text)
        self.assertIn("[assistant]\nPostgreSQL stays.", text)
        self.assertNotIn("ENTIRE_FILE_DUMP_SHOULD_NOT_APPEAR", text)
        self.assertNotIn("SECRETREASONING", text)
        self.assertNotIn("private plan", text)
        self.assertNotIn("catalog", text)
        self.assertNotIn("host", text)

    def test_distill_stdout_omits_tool_dump(self) -> None:
        path = self._write_session()
        from io import StringIO
        import contextlib

        stdout = StringIO()
        with contextlib.redirect_stdout(stdout):
            code = distill_main(["--from", "grok", "--file", str(path)])
        text = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[session-distill]", text)
        self.assertNotIn("ENTIRE_FILE_DUMP_SHOULD_NOT_APPEAR", text)
        self.assertNotIn("SECRETREASONING", text)
        self.assertNotIn("[user]", text)
        self.assertNotIn("[assistant]", text)


if __name__ == "__main__":
    unittest.main()
