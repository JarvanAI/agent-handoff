"""Tests for core/state_machine.py."""

from __future__ import annotations

import unittest

from handoff.core.state_machine import DecisionStateMachine
from handoff.models import DecisionState, TurnRole, UnifiedTurn


class TestDecisionStateMachine(unittest.TestCase):
    def setUp(self) -> None:
        self.fsm = DecisionStateMachine()

    def test_proposal_lifecycle_to_accepted(self) -> None:
        turns = [
            UnifiedTurn(
                turn_id="turn_1",
                session_id="s1",
                timestamp="2026-09-22T00:00:00Z",
                role=TurnRole.ASSISTANT,
                content="我们决定采用SQLite作为本地元数据持久化引擎，因为性能优异且零配置。",
            ),
            UnifiedTurn(
                turn_id="turn_2",
                session_id="s1",
                timestamp="2026-09-22T00:00:01Z",
                role=TurnRole.USER,
                content="很好，测试通过，已确认采用此方案！",
            ),
        ]
        entities, anti_patterns = self.fsm.run(turns)
        self.assertGreaterEqual(len(entities), 1)
        accepted = [e for e in entities if e.state == DecisionState.ACCEPTED]
        self.assertGreaterEqual(len(accepted), 1)
        self.assertIn("sqlite", accepted[0].topic.lower())

    def test_latest_wins_arbitration_and_anti_patterns(self) -> None:
        turns = [
            UnifiedTurn(
                turn_id="turn_1",
                session_id="s1",
                timestamp="2026-09-22T00:00:00Z",
                role=TurnRole.ASSISTANT,
                content="采用 JSON-RPC 作为进程间通信协议。",
            ),
            UnifiedTurn(
                turn_id="turn_2",
                session_id="s1",
                timestamp="2026-09-22T00:00:01Z",
                role=TurnRole.ASSISTANT,
                content="JSON-RPC存在协议开销大和复杂度问题，我们放弃 JSON-RPC，改用 Unix Domain Socket。",
            ),
            UnifiedTurn(
                turn_id="turn_3",
                session_id="s1",
                timestamp="2026-09-22T00:00:02Z",
                role=TurnRole.USER,
                content="确认通过 Unix Domain Socket 方案！",
            ),
        ]
        entities, anti_patterns = self.fsm.run(turns)
        # Should have captured superseded entity
        superseded = [e for e in entities if e.state == DecisionState.SUPERSEDED]
        self.assertGreaterEqual(len(superseded), 1)

        # Anti-patterns should record the abandoned proposal
        self.assertGreaterEqual(len(anti_patterns), 1)
        self.assertTrue(any("json" in ap.abandoned_proposal.lower() for ap in anti_patterns))

    def test_debate_state_transition(self) -> None:
        turn1 = UnifiedTurn(
            turn_id="turn_1",
            session_id="s1",
            timestamp="2026-09-22T00:00:00Z",
            role=TurnRole.ASSISTANT,
            content="引入 RocksDB 作为存储层。",
        )
        self.fsm.process_turn(turn1)
        self.assertEqual(self.fsm.entities[0].state, DecisionState.PROPOSED)

        turn2 = UnifiedTurn(
            turn_id="turn_2",
            session_id="s1",
            timestamp="2026-09-22T00:00:01Z",
            role=TurnRole.ASSISTANT,
            content="RocksDB 的编译依赖较重，存在跨平台构建风险与缺点。",
        )
        self.fsm.process_turn(turn2)
        self.assertEqual(self.fsm.entities[0].state, DecisionState.DEBATED)


if __name__ == "__main__":
    unittest.main()
