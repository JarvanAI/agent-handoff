"""Reverse Endpoint Anchor Engine and Causal Chain Backfill.

Scans the trajectory backwards (以终为始) to anchor:
- Final test verification
- User confirmation
- Code delivery / commits
- Final goal achievement

Then performs forward causal chain backfill to reconstruct the exact path from
problem formulation to verified outcome.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple

from session_distill.models import (
    AnchorRecord,
    AnchorType,
    DecisionEntity,
    TurnRole,
    UnifiedTurn,
)


class AnchorEngine:
    """Engine for reverse endpoint anchoring and causal chain reconstruction."""

    # Test pass patterns
    _TEST_PASS_PATTERNS: List[Pattern[str]] = [
        re.compile(r"Ran \d+ tests in [0-9\.]+s\s+OK", re.IGNORECASE),
        re.compile(r"PASSED.*?(?:100%|\d+ passed)", re.IGNORECASE),
        re.compile(r"\b\d+ passed(?:, \d+ skipped)? in [0-9\.]+s\b", re.IGNORECASE),
        re.compile(r"All tests passed", re.IGNORECASE),
        re.compile(r"测试(?:全部)?通过", re.IGNORECASE),
        re.compile(r"exit code 0\b", re.IGNORECASE),
    ]

    # User confirmation patterns
    _USER_CONFIRM_PATTERNS: List[Pattern[str]] = [
        re.compile(
            r"^(?:好|好的|可以|没问题|通过|已确认|完成|LGTM|lgtm|proceed|approved|looks good|great|nice job|thanks)[!！\.\s，,、]*(?:完成|通过|可以|没问题|感谢|谢谢)?[!！\.\s]*$",
            re.IGNORECASE,
        ),
        re.compile(r"(?:确认通过|验收完成|符合预期|没有问题|已验证|测试通过)", re.IGNORECASE),
    ]

    # File modification tools
    _CODE_MOD_TOOLS: Set[str] = {
        "write_to_file",
        "replace_file_content",
        "edit_file",
        "create_file",
        "write",
        "edit",
        "patch",
        "str_replace_editor",
    }

    # Open task / TODO patterns
    _OPEN_TASK_PATTERNS: List[Pattern[str]] = [
        re.compile(r"(?:TODO|FIXME|待办|后续|待优化|未决事项)[:：\s]+([^\n]+)", re.IGNORECASE),
        re.compile(r"(?:下一步|后续计划)[:：\s]+([^\n]+)", re.IGNORECASE),
    ]

    def __init__(self, max_anchors: int = 5) -> None:
        self.max_anchors = max_anchors

    def is_test_verified_turn(self, turn: UnifiedTurn) -> Tuple[bool, str]:
        """Check if turn contains successful test execution evidence."""
        # Check tool results
        for tr in turn.tool_results:
            content = tr.content
            for pat in self._TEST_PASS_PATTERNS:
                m = pat.search(content)
                if m:
                    return True, m.group(0)

        # Check turn content
        for pat in self._TEST_PASS_PATTERNS:
            m = pat.search(turn.content)
            if m:
                return True, m.group(0)

        return False, ""

    def is_user_confirmed_turn(self, turn: UnifiedTurn) -> Tuple[bool, str]:
        """Check if turn is a user confirmation / acceptance turn."""
        if turn.role != TurnRole.USER:
            return False, ""
        content = turn.content.strip()
        for pat in self._USER_CONFIRM_PATTERNS:
            m = pat.search(content)
            if m:
                return True, m.group(0)
        return False, ""

    def is_code_delivery_turn(self, turn: UnifiedTurn) -> Tuple[bool, str]:
        """Check if turn contains code artifact generation or modification."""
        for tc in turn.tool_calls:
            if tc.tool_name.lower() in self._CODE_MOD_TOOLS:
                target = (
                    tc.tool_args.get("TargetFile")
                    or tc.tool_args.get("path")
                    or tc.tool_args.get("file_path")
                    or tc.tool_name
                )
                return True, f"Modified {target}"
            # Check git commit in bash commands
            cmd = str(tc.tool_args.get("command", "") or tc.tool_args.get("CommandLine", ""))
            if "git commit" in cmd:
                return True, f"Git commit: {cmd[:60]}"
        return False, ""

    def extract_open_tasks(self, turns: List[UnifiedTurn]) -> List[str]:
        """Extract uncompleted tasks or pending items from turns."""
        tasks: List[str] = []
        seen: Set[str] = set()

        for turn in turns:
            content = turn.content
            for pat in self._OPEN_TASK_PATTERNS:
                for m in pat.finditer(content):
                    task_text = m.group(1).strip()
                    if task_text and task_text not in seen:
                        seen.add(task_text)
                        tasks.append(task_text)

        return tasks

    def find_reverse_anchors(self, turns: List[UnifiedTurn]) -> List[AnchorRecord]:
        """Find terminal anchors by inspecting turns in reverse chronological order."""
        anchors: List[AnchorRecord] = []
        found_types: Set[AnchorType] = set()

        for turn in reversed(turns):
            if len(anchors) >= self.max_anchors:
                break

            # 1. Test verification (highest priority)
            if AnchorType.TEST_VERIFIED not in found_types:
                is_test, evidence = self.is_test_verified_turn(turn)
                if is_test:
                    anchors.append(
                        AnchorRecord(
                            anchor_type=AnchorType.TEST_VERIFIED,
                            turn_id=turn.turn_id,
                            description=f"Deterministic test suite passed ({evidence})",
                            evidence=evidence,
                        )
                    )
                    found_types.add(AnchorType.TEST_VERIFIED)
                    continue

            # 2. User confirmation
            if AnchorType.USER_CONFIRMED not in found_types:
                is_user, evidence = self.is_user_confirmed_turn(turn)
                if is_user:
                    anchors.append(
                        AnchorRecord(
                            anchor_type=AnchorType.USER_CONFIRMED,
                            turn_id=turn.turn_id,
                            description=f"User approved and confirmed outcome ({evidence})",
                            evidence=evidence,
                        )
                    )
                    found_types.add(AnchorType.USER_CONFIRMED)
                    continue

            # 3. Final code delivery
            if AnchorType.CODE_COMMITTED not in found_types:
                is_code, evidence = self.is_code_delivery_turn(turn)
                if is_code:
                    anchors.append(
                        AnchorRecord(
                            anchor_type=AnchorType.CODE_COMMITTED,
                            turn_id=turn.turn_id,
                            description=f"Final code artifact delivered ({evidence})",
                            evidence=evidence,
                        )
                    )
                    found_types.add(AnchorType.CODE_COMMITTED)
                    continue

        # If no specific anchors found, use the final assistant turn as GOAL_ACHIEVED
        if not anchors and turns:
            last_turn = turns[-1]
            anchors.append(
                AnchorRecord(
                    anchor_type=AnchorType.GOAL_ACHIEVED,
                    turn_id=last_turn.turn_id,
                    description="Session completed with final response delivered",
                    evidence=last_turn.content[:100],
                )
            )

        return anchors

    def backfill_causal_chains(
        self,
        anchors: List[AnchorRecord],
        turns: List[UnifiedTurn],
        decisions: Optional[List[DecisionEntity]] = None,
    ) -> List[AnchorRecord]:
        """Backfill forward causal chain for each anchor."""
        if not turns:
            return anchors

        # Find initial requirement turn (first user turn)
        root_turn_id = next(
            (t.turn_id for t in turns if t.role == TurnRole.USER),
            turns[0].turn_id,
        )

        turn_index = {t.turn_id: idx for idx, t in enumerate(turns)}
        decision_turns = {d.turn_id for d in (decisions or []) if d.turn_id}

        for anchor in anchors:
            target_idx = turn_index.get(anchor.turn_id, len(turns) - 1)
            chain: List[str] = [root_turn_id]

            # Add key decision turns occurring before this anchor
            for turn in turns[:target_idx]:
                if turn.turn_id in decision_turns and turn.turn_id not in chain:
                    chain.append(turn.turn_id)

                # Add key code modification turns
                is_code, _ = self.is_code_delivery_turn(turn)
                if is_code and turn.turn_id not in chain:
                    chain.append(turn.turn_id)

            # Finally add the anchor itself
            if anchor.turn_id not in chain:
                chain.append(anchor.turn_id)

            anchor.causal_chain = chain

        return anchors

    def analyze(
        self,
        turns: List[UnifiedTurn],
        decisions: Optional[List[DecisionEntity]] = None,
    ) -> Tuple[List[AnchorRecord], List[str]]:
        """Run complete reverse anchoring and forward causal chain backfill."""
        anchors = self.find_reverse_anchors(turns)
        anchors = self.backfill_causal_chains(anchors, turns, decisions)
        open_tasks = self.extract_open_tasks(turns)
        return anchors, open_tasks
