"""Tests for core/anchor_engine.py."""

from __future__ import annotations

import unittest

from session_distill.core.anchor_engine import AnchorEngine
from session_distill.models import (
    AnchorType,
    DecisionEntity,
    DecisionState,
    ToolCallRecord,
    ToolResultRecord,
    TurnRole,
    UnifiedTurn,
)


class TestAnchorEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AnchorEngine()

    def test_reverse_test_pass_anchor_detection(self) -> None:
        turns = [
            UnifiedTurn(
                turn_id="t1",
                session_id="s1",
                timestamp="2026-09-22T00:00:00Z",
                role=TurnRole.USER,
                content="Please fix the bug.",
            ),
            UnifiedTurn(
                turn_id="t2",
                session_id="s1",
                timestamp="2026-09-22T00:00:01Z",
                role=TurnRole.ASSISTANT,
                content="Writing fix",
                tool_calls=[ToolCallRecord(tool_name="write_to_file", tool_args={"TargetFile": "/app/fix.py"})],
            ),
            UnifiedTurn(
                turn_id="t3",
                session_id="s1",
                timestamp="2026-09-22T00:00:02Z",
                role=TurnRole.TOOL,
                content="",
                tool_results=[ToolResultRecord(content="Ran 12 tests in 0.45s\nOK\n")],
            ),
            UnifiedTurn(
                turn_id="t4",
                session_id="s1",
                timestamp="2026-09-22T00:00:03Z",
                role=TurnRole.USER,
                content="好，完成",
            ),
        ]
        anchors, open_tasks = self.engine.analyze(turns)
        self.assertGreaterEqual(len(anchors), 1)
        anchor_types = [a.anchor_type for a in anchors]
        self.assertIn(AnchorType.TEST_VERIFIED, anchor_types)
        self.assertIn(AnchorType.USER_CONFIRMED, anchor_types)

        # Check causal chain backfill
        test_anchor = next(a for a in anchors if a.anchor_type == AnchorType.TEST_VERIFIED)
        self.assertIn("t1", test_anchor.causal_chain)
        self.assertIn("t2", test_anchor.causal_chain)
        self.assertIn("t3", test_anchor.causal_chain)

    def test_extract_open_tasks(self) -> None:
        turns = [
            UnifiedTurn(
                turn_id="t1",
                session_id="s1",
                timestamp="2026-09-22T00:00:00Z",
                role=TurnRole.ASSISTANT,
                content="核心逻辑已完成。\nTODO: 补充多线程并发压测脚本。\n待办: 完善文档。",
            ),
        ]
        tasks = self.engine.extract_open_tasks(turns)
        self.assertIn("补充多线程并发压测脚本。", tasks)
        self.assertIn("完善文档。", tasks)


if __name__ == "__main__":
    unittest.main()
