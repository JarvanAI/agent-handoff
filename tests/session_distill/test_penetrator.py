"""Tests for core/penetrator.py."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from session_distill.core.penetrator import LogPenetrator


class TestLogPenetrator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)
        self.full_log = self.tmp_dir / "transcript_full.jsonl"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_penetration_restores_truncated_content(self) -> None:
        full_records = [
            {"step_index": 1, "type": "USER_INPUT", "content": "hello"},
            {"step_index": 2, "type": "PLANNER_RESPONSE", "content": "very long content that was truncated previously"},
        ]
        with open(self.full_log, "w", encoding="utf-8") as f:
            for r in full_records:
                f.write(json.dumps(r) + "\n")

        penetrator = LogPenetrator(self.full_log)
        self.assertTrue(penetrator.is_available())

        compact_record = {
            "step_index": 2,
            "type": "PLANNER_RESPONSE",
            "content": "very long ...",
            "truncated_fields": ["content"],
        }

        restored = penetrator.penetrate_record(compact_record, line_no=1)
        self.assertEqual(restored["content"], "very long content that was truncated previously")
        self.assertTrue(restored.get("_penetrated"))
        self.assertNotIn("truncated_fields", restored)

    def test_clean_truncation_artifacts(self) -> None:
        raw = "Line 1\n<truncated 45000 bytes>\nLine 2\nNOTE: The output was truncated because it was too long. Use a more targeted query."
        cleaned = LogPenetrator.clean_truncation_artifacts(raw)
        self.assertNotIn("<truncated", cleaned)
        self.assertNotIn("NOTE: The output was truncated", cleaned)
        self.assertIn("Line 1", cleaned)
        self.assertIn("Line 2", cleaned)


if __name__ == "__main__":
    unittest.main()
