"""Tests for outputs/playbook_generator.py and outputs/handoff_envelope.py."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from session_distill.models import (
    AnchorRecord,
    AnchorType,
    AntiPatternRecord,
    DecisionEntity,
    DecisionState,
    DistillationResult,
    TurnRole,
    UnifiedTurn,
)
from session_distill.outputs.handoff_envelope import HandoffEnvelopeGenerator
from session_distill.outputs.playbook_generator import PlaybookGenerator


class TestOutputs(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

        self.mock_result = DistillationResult(
            session_id="test-session-123",
            provider="antigravity",
            raw_turns_count=100,
            cleaned_turns=[
                UnifiedTurn(
                    turn_id="t1",
                    session_id="test-session-123",
                    timestamp="2026-09-22T00:00:00Z",
                    role=TurnRole.USER,
                    content="Build a high performance session distillation engine.",
                ),
                UnifiedTurn(
                    turn_id="t2",
                    session_id="test-session-123",
                    timestamp="2026-09-22T00:00:01Z",
                    role=TurnRole.ASSISTANT,
                    content="We adopt zero-token pure Python parsing.",
                ),
            ],
            decisions=[
                DecisionEntity(
                    entity_id="ADR-001",
                    topic="parsing_engine",
                    state=DecisionState.ACCEPTED,
                    decision="Zero-token deterministic regex parsing",
                    rationale="Sub-millisecond speed and zero LLM billing cost.",
                    turn_id="t2",
                    alternatives_considered=["LLM Summarization prompt"],
                ),
            ],
            anchors=[
                AnchorRecord(
                    anchor_type=AnchorType.TEST_VERIFIED,
                    turn_id="t2",
                    description="Unit test suite 100% passed",
                    evidence="OK",
                    causal_chain=["t1", "t2"],
                )
            ],
            anti_patterns=[
                AntiPatternRecord(
                    topic="parsing_engine",
                    abandoned_proposal="LLM Summarization prompt",
                    pitfall_reason="High latency and token cost",
                    recommended_alternative="Deterministic regex FSM",
                )
            ],
            open_tasks=["Add performance benchmarks"],
            metrics={"duration_ms": 15.5},
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_playbook_generator(self) -> None:
        generator = PlaybookGenerator()
        md = generator.generate(self.mock_result)

        self.assertIn("# 架构决策与逐行防御复盘手册", md)
        self.assertIn("ADR-001", md)
        self.assertIn("Zero-token deterministic regex parsing", md)
        self.assertIn("LLM Summarization prompt", md)
        self.assertIn("Unit test suite 100% passed", md)

        # Test writing to file
        out_file = self.tmp_dir / "playbook.md"
        generator.write_to_file(self.mock_result, out_file)
        self.assertTrue(out_file.is_file())
        self.assertIn("ADR-001", out_file.read_text(encoding="utf-8"))

    def test_handoff_envelope_json(self) -> None:
        generator = HandoffEnvelopeGenerator()
        json_str = generator.to_json(self.mock_result)
        data = json.loads(json_str)

        self.assertEqual(data["schema_version"], "1.0.0")
        self.assertEqual(data["source_session"]["session_id"], "test-session-123")
        self.assertEqual(len(data["decision_dag"]["nodes"]), 1)
        self.assertEqual(data["decision_dag"]["nodes"][0]["id"], "ADR-001")
        self.assertEqual(len(data["anti_patterns"]), 1)
        self.assertEqual(data["anti_patterns"][0]["topic"], "parsing_engine")

        # Test writing to json file
        out_file = self.tmp_dir / "handoff.json"
        generator.write_to_file(self.mock_result, out_file)
        self.assertTrue(out_file.is_file())

    def test_handoff_envelope_yaml(self) -> None:
        generator = HandoffEnvelopeGenerator()
        yaml_str = generator.to_yaml(self.mock_result)
        self.assertIn("schema_version: 1.0.0", yaml_str)
        self.assertIn("session_id: test-session-123", yaml_str)
        self.assertIn("ADR-001", yaml_str)

        # Test writing to yaml file
        out_file = self.tmp_dir / "handoff.yaml"
        generator.write_to_file(self.mock_result, out_file)
        self.assertTrue(out_file.is_file())


if __name__ == "__main__":
    unittest.main()
