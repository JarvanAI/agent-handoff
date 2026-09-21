"""Tests for core/noise_filter.py."""

from __future__ import annotations

import unittest

from session_distill.core.noise_filter import NoiseFilter
from session_distill.models import (
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
    UnifiedTurn,
)


class TestNoiseFilter(unittest.TestCase):
    def setUp(self) -> None:
        self.filter = NoiseFilter(max_tool_output_lines=10, max_tool_output_chars=200)

    def test_clean_ansi_and_progress_bars(self) -> None:
        raw = "\x1b[31mRed Text\x1b[0m with progress [========  ] 80%\nNext line"
        cleaned = self.filter.clean_text(raw)
        self.assertNotIn("\x1b[31m", cleaned)
        self.assertNotIn("[========", cleaned)
        self.assertIn("Red Text", cleaned)
        self.assertIn("Next line", cleaned)

    def test_strip_injected_skills(self) -> None:
        raw = "<EXTREMELY_IMPORTANT>\nYou have superpowers.\n</EXTREMELY_IMPORTANT>\nPlease fix the bug."
        cleaned = self.filter.clean_text(raw)
        self.assertNotIn("superpowers", cleaned)
        self.assertEqual(cleaned, "Please fix the bug.")

    def test_compress_stdout_listing(self) -> None:
        long_listing = "\n".join(f"file_{i}.txt" for i in range(50))
        compressed = self.filter.compress_stdout(long_listing, command="ls -la /some/dir")
        self.assertIn("entries omitted", compressed)
        self.assertTrue(compressed.startswith("file_0.txt"))
        self.assertTrue(compressed.endswith("file_49.txt"))

    def test_filter_heartbeats_and_empty_frames(self) -> None:
        empty_turn = UnifiedTurn(
            turn_id="t1",
            session_id="s1",
            timestamp="2026-09-22T00:00:00Z",
            role=TurnRole.SYSTEM,
            content="   ",
            metadata={"type": "checkpoint"},
        )
        self.assertTrue(self.filter.is_heartbeat_or_empty(empty_turn))

        real_turn = UnifiedTurn(
            turn_id="t2",
            session_id="s1",
            timestamp="2026-09-22T00:00:01Z",
            role=TurnRole.USER,
            content="Implement feature X",
        )
        self.assertFalse(self.filter.is_heartbeat_or_empty(real_turn))

    def test_filter_trajectory(self) -> None:
        turns = [
            UnifiedTurn(
                turn_id="t1",
                session_id="s1",
                timestamp="2026-09-22T00:00:00Z",
                role=TurnRole.SYSTEM,
                content="",
                metadata={"type": "checkpoint"},
            ),
            UnifiedTurn(
                turn_id="t2",
                session_id="s1",
                timestamp="2026-09-22T00:00:01Z",
                role=TurnRole.USER,
                content="<EXTREMELY_IMPORTANT>Skill</EXTREMELY_IMPORTANT>Let's design the architecture.",
            ),
            UnifiedTurn(
                turn_id="t3",
                session_id="s1",
                timestamp="2026-09-22T00:00:02Z",
                role=TurnRole.ASSISTANT,
                content="I will run pwd",
                tool_calls=[ToolCallRecord(tool_name="run_command", tool_args={"command": "pwd"})],
                tool_results=[ToolResultRecord(content="/home/shenzhou/Codes/Arborist-Orca\n")],
            ),
        ]
        cleaned, stats = self.filter.filter_trajectory(turns)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(stats["filtered_heartbeats"], 1)
        self.assertEqual(cleaned[0].content, "Let's design the architecture.")


if __name__ == "__main__":
    unittest.main()
