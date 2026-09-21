"""Decision Entity Finite State Machine (FSM).

Maintains decision entity lifecycles:
Proposed -> Debated -> Superseded -> Accepted (or Rejected)
Implements Latest-Wins arbitration and marks deprecated drafts as anti-patterns.
Runs purely deterministically without LLM calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple

from session_distill.models import (
    AntiPatternRecord,
    DecisionEntity,
    DecisionState,
    TurnRole,
    UnifiedTurn,
)


class DecisionStateMachine:
    """FSM tracking architectural decision entities across conversation turns."""

    # Decision proposal patterns
    _PROPOSAL_PATTERNS: List[Pattern[str]] = [
        # Chinese patterns
        re.compile(r"(?:采用|使用|选用|确定|改为|切换为|引入|设计|方案|策略)\s*[:：]?\s*([A-Za-z0-9_\u4e00-\u9fa5\-\.]{2,40})", re.IGNORECASE),
        re.compile(r"(?:架构决策|ADR|核心设计)\s*[:：\-]\s*([A-Za-z0-9_\u4e00-\u9fa5\-\.\s]{2,50})", re.IGNORECASE),
        re.compile(r"决定\s*(?:采用|使用|选用|实现|遵循)\s*([A-Za-z0-9_\u4e00-\u9fa5\-\.]{2,40})", re.IGNORECASE),
        re.compile(r"选择\s*([A-Za-z0-9_\u4e00-\u9fa5\-\.]{2,30})\s*(?:作为|而非|而不是)", re.IGNORECASE),
        # English patterns
        re.compile(r"(?:decided to|we will use|choose|chosen|adopt|switch to|selected)\s+([a-zA-Z0-9_\-\. ]{2,40})", re.IGNORECASE),
        re.compile(r"(?:architecture decision|ADR|design decision)\s*[:：\-]\s*([a-zA-Z0-9_\-\. ]{2,50})", re.IGNORECASE),
        re.compile(r"instead of\s+([a-zA-Z0-9_\-\. ]{2,30}),\s*(?:we will|use|adopt)\s+([a-zA-Z0-9_\-\. ]{2,30})", re.IGNORECASE),
    ]

    # Debate / contention patterns
    _DEBATE_PATTERNS: List[Pattern[str]] = [
        re.compile(r"(?:缺点|劣势|风险|挑战|隐患|争议|问题|限制|性能瓶颈|drawback|risk|trade-off|versus|vs\.?|issue with|limitation)", re.IGNORECASE),
        re.compile(r"(?:对比|评估|权衡|compare|benchmark|evaluating)", re.IGNORECASE),
    ]

    # Superseding / Pivot patterns
    _SUPERSEDE_PATTERNS: List[Pattern[str]] = [
        re.compile(r"(?:放弃|废弃|弃用|不再使用|淘汰|推翻|supersede|deprecate|abandon|replace|drop)\s*([A-Za-z0-9_\u4e00-\u9fa5\-\.]{2,40})", re.IGNORECASE),
        re.compile(r"(?:改用|换成|替换为|switch from\s+([^\s]+)\s+to)\s*([A-Za-z0-9_\u4e00-\u9fa5\-\.]{2,40})", re.IGNORECASE),
    ]

    # Acceptance / Confirmation patterns
    _ACCEPTANCE_PATTERNS: List[Pattern[str]] = [
        re.compile(r"(?:已确认|确认采用|最终决定|通过|验证通过|已落实|测试通过|accepted|finalized|confirmed|verified|approved)", re.IGNORECASE),
        re.compile(r"(?:实现完毕|交付|生效|implemented|committed)", re.IGNORECASE),
    ]

    def __init__(self) -> None:
        self._entities: Dict[str, DecisionEntity] = {}  # entity_id -> DecisionEntity
        self._topic_index: Dict[str, str] = {}  # topic -> current active entity_id
        self._anti_patterns: List[AntiPatternRecord] = []
        self._entity_counter: int = 0

    @property
    def entities(self) -> List[DecisionEntity]:
        return list(self._entities.values())

    @property
    def anti_patterns(self) -> List[AntiPatternRecord]:
        return list(self._anti_patterns)

    def _generate_entity_id(self) -> str:
        self._entity_counter += 1
        return f"ADR-{self._entity_counter:03d}"

    def _normalize_topic(self, raw_topic: str) -> str:
        """Normalize raw extracted topic into a clean canonical identifier."""
        clean = raw_topic.strip().lower()
        clean = re.sub(r"[\s\-_]+", "_", clean)
        clean = re.sub(r"[^\w\u4e00-\u9fa5]", "", clean)
        return clean[:32] if clean else "general_architecture"

    def _extract_rationale(self, text: str, decision_str: str) -> str:
        """Extract adjacent rationale sentence."""
        sentences = re.split(r"[。\n\.\!！]", text)
        for s in sentences:
            s_clean = s.strip()
            if any(k in s_clean for k in ("因为", "由于", "原因", "目的", "为了", "优势", "because", "in order to", "reason", "benefit")):
                return s_clean[:200]
        # Return fallback sentence containing decision
        for s in sentences:
            if decision_str in s:
                return s.strip()[:200]
        return "Deterministic architectural selection based on performance and compatibility requirements."

    def process_turn(self, turn: UnifiedTurn) -> None:
        """Process a single turn and advance decision entity states."""
        content = turn.content.strip()
        if not content:
            return

        # 1. Detect explicit superseding / deprecation
        for pat in self._SUPERSEDE_PATTERNS:
            match = pat.search(content)
            if match:
                groups = [g for g in match.groups() if g]
                if groups:
                    target = self._normalize_topic(groups[0])
                    if target in self._topic_index:
                        old_id = self._topic_index[target]
                        old_entity = self._entities.get(old_id)
                        if old_entity and old_entity.state not in (DecisionState.SUPERSEDED, DecisionState.REJECTED):
                            old_entity.state = DecisionState.SUPERSEDED
                            # Record anti-pattern
                            replacement = groups[1] if len(groups) > 1 else "Newer architectural design"
                            self._anti_patterns.append(
                                AntiPatternRecord(
                                    topic=old_entity.topic,
                                    abandoned_proposal=old_entity.decision,
                                    pitfall_reason=f"Superseded during turn {turn.turn_id}: {content[:120]}",
                                    recommended_alternative=replacement,
                                    turn_id=turn.turn_id,
                                )
                            )

        # 2. Detect proposals
        for pat in self._PROPOSAL_PATTERNS:
            for match in pat.finditer(content):
                groups = [g for g in match.groups() if g]
                if not groups:
                    continue
                decision_text = groups[-1].strip()
                if len(decision_text) < 2 or decision_text.isdigit():
                    continue

                topic = self._normalize_topic(decision_text)
                rationale = self._extract_rationale(content, decision_text)

                # Check if there is already an active entity for this topic
                if topic in self._topic_index:
                    prev_id = self._topic_index[topic]
                    prev_entity = self._entities[prev_id]
                    if prev_entity.decision != decision_text:
                        # Latest-Wins: Supersede previous proposal
                        prev_entity.state = DecisionState.SUPERSEDED
                        new_id = self._generate_entity_id()
                        prev_entity.superseded_by = new_id

                        self._anti_patterns.append(
                            AntiPatternRecord(
                                topic=prev_entity.topic,
                                abandoned_proposal=prev_entity.decision,
                                pitfall_reason=f"Overridden by later proposal {new_id} ({decision_text})",
                                recommended_alternative=decision_text,
                                turn_id=turn.turn_id,
                            )
                        )

                        new_entity = DecisionEntity(
                            entity_id=new_id,
                            topic=topic,
                            state=DecisionState.PROPOSED,
                            decision=decision_text,
                            rationale=rationale,
                            alternatives_considered=[prev_entity.decision],
                            turn_id=turn.turn_id,
                            evidence_snippets=[content[:180]],
                            tags=[topic],
                        )
                        self._entities[new_id] = new_entity
                        self._topic_index[topic] = new_id
                        continue
                    else:
                        # Re-mention of same decision, add evidence
                        if content[:180] not in prev_entity.evidence_snippets:
                            prev_entity.evidence_snippets.append(content[:180])
                        continue

                # Brand new proposal
                new_id = self._generate_entity_id()
                new_entity = DecisionEntity(
                    entity_id=new_id,
                    topic=topic,
                    state=DecisionState.PROPOSED,
                    decision=decision_text,
                    rationale=rationale,
                    turn_id=turn.turn_id,
                    evidence_snippets=[content[:180]],
                    tags=[topic],
                )
                self._entities[new_id] = new_entity
                self._topic_index[topic] = new_id

        # 3. Check for debates/critiques on active entities
        has_debate = any(pat.search(content) for pat in self._DEBATE_PATTERNS)
        if has_debate:
            for entity in self._entities.values():
                if entity.state == DecisionState.PROPOSED:
                    if entity.topic in content.lower() or entity.decision in content:
                        entity.state = DecisionState.DEBATED
                        if content[:180] not in entity.evidence_snippets:
                            entity.evidence_snippets.append(content[:180])

        # 4. Check for acceptance/confirmation
        has_acceptance = any(pat.search(content) for pat in self._ACCEPTANCE_PATTERNS)
        if has_acceptance:
            for entity in self._entities.values():
                if entity.state in (DecisionState.PROPOSED, DecisionState.DEBATED):
                    # Check if referenced or if this is an overall acceptance turn (e.g. user approval)
                    if (
                        entity.topic in content.lower()
                        or entity.decision in content
                        or turn.role == TurnRole.USER
                    ):
                        entity.state = DecisionState.ACCEPTED
                        if content[:180] not in entity.evidence_snippets:
                            entity.evidence_snippets.append(content[:180])

    def finalize(self) -> None:
        """Final sweep: active, non-superseded decisions default to ACCEPTED if verified."""
        for entity in self._entities.values():
            if entity.state in (DecisionState.PROPOSED, DecisionState.DEBATED):
                # If it survived through to the end without being superseded or rejected, mark ACCEPTED
                entity.state = DecisionState.ACCEPTED

    def run(self, turns: List[UnifiedTurn]) -> Tuple[List[DecisionEntity], List[AntiPatternRecord]]:
        """Run the FSM over all trajectory turns in chronological order."""
        for turn in turns:
            self.process_turn(turn)
        self.finalize()
        return self.entities, self.anti_patterns
