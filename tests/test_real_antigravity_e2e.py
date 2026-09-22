"""End-to-end distillation test on real-world local Antigravity session."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest

from handoff.engine import DistillationEngine
from handoff.outputs.handoff_envelope import HandoffEnvelopeGenerator
from handoff.outputs.playbook_generator import PlaybookGenerator


class TestRealAntigravityE2E(unittest.TestCase):
    REAL_SESSION_PATH = Path("/home/shenzhou/.gemini/antigravity-cli/brain/e6129792-626d-48e2-bb79-be9d34b32829")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_real_antigravity_handoffation(self) -> None:
        if not self.REAL_SESSION_PATH.is_dir():
            self.skipTest(f"Real session path not found: {self.REAL_SESSION_PATH}")

        engine = DistillationEngine()

        t0 = time.perf_counter()
        result = engine.distill(self.REAL_SESSION_PATH, provider="antigravity")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Assertions on performance: zero-token parsing should finish in milliseconds
        self.assertLess(elapsed_ms, 5000.0, f"Expected < 5000ms, took {elapsed_ms:.2f}ms")
        self.assertEqual(result.provider, "antigravity")
        self.assertEqual(result.session_id, "e6129792-626d-48e2-bb79-be9d34b32829")

        # Check turn counts: original has 962 steps
        self.assertEqual(result.raw_turns_count, 962)
        self.assertGreater(len(result.cleaned_turns), 0)
        self.assertLess(len(result.cleaned_turns), result.raw_turns_count)

        # Check penetration: verify some previously truncated contents were restored
        penetrated_turns = [
            t for t in result.cleaned_turns if t.metadata.get("step_index") in (2, 4, 18, 20, 26)
        ]
        self.assertTrue(len(penetrated_turns) > 0)

        # Generate outputs
        playbook_path = self.tmp_dir / "playbook.md"
        handoff_json_path = self.tmp_dir / "handoff.json"
        handoff_yaml_path = self.tmp_dir / "handoff.yaml"

        playbook_gen = PlaybookGenerator()
        playbook_gen.write_to_file(result, playbook_path)
        self.assertTrue(playbook_path.is_file())
        playbook_content = playbook_path.read_text(encoding="utf-8")
        self.assertIn("架构决策与逐行防御复盘手册", playbook_content)
        self.assertIn("e6129792-626d-48e2-bb79-be9d34b32829", playbook_content)

        envelope_gen = HandoffEnvelopeGenerator()
        envelope_gen.write_to_file(result, handoff_json_path)
        envelope_gen.write_to_file(result, handoff_yaml_path)

        self.assertTrue(handoff_json_path.is_file())
        self.assertTrue(handoff_yaml_path.is_file())

        with open(handoff_json_path, "r", encoding="utf-8") as f:
            handoff_data = json.load(f)
        self.assertEqual(handoff_data["schema_version"], "1.0.0")
        self.assertEqual(handoff_data["source_session"]["session_id"], "e6129792-626d-48e2-bb79-be9d34b32829")
        self.assertEqual(handoff_data["source_session"]["raw_turns_count"], 962)


if __name__ == "__main__":
    unittest.main()
