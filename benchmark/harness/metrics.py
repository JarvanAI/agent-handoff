"""Evaluation metrics for session-distill-bench (Opus 4.6 validated).

Includes:
- CER (Context Efficiency Ratio)
- wFDR (Weighted Final Decision Recall)
- NKR (Negative Knowledge Retention)
- Hard SHR (State Hallucination Rate)
- TRA (Truncation Recovery Accuracy)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MetricResult:
    score: float
    details: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class BenchmarkScorecard:
    strategy_name: str
    sample_id: str
    input_tokens: int
    output_tokens: int
    context_window_size: int = 200_000
    tcsr: float = 1.0  # Task Continuation Success Rate [0.0 - 1.0]
    cer: float = 0.0   # Context Efficiency Ratio
    wfdr: float = 0.0  # Weighted Final Decision Recall
    nkr: float = 0.0   # Negative Knowledge Retention
    hard_shr: float = 0.0 # Hard State Hallucination Rate (0.0 is best)
    tra: float = 0.0   # Truncation Recovery Accuracy
    raw_metrics: Dict[str, Any] = field(default_factory=dict)

    def calculate_cer(self) -> float:
        token_ratio = max(self.output_tokens, 1) / self.context_window_size
        self.cer = round(self.tcsr / token_ratio, 2)
        return self.cer

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "sample_id": self.sample_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "compression_ratio": round(self.output_tokens / max(self.input_tokens, 1), 4),
            "cer": self.cer,
            "wfdr": round(self.wfdr, 4),
            "nkr": round(self.nkr, 4),
            "hard_shr": round(self.hard_shr, 4),
            "tra": round(self.tra, 4),
            "tcsr": round(self.tcsr, 4),
            "raw_metrics": self.raw_metrics,
        }


def compute_wfdr(
    extracted_decisions: List[str],
    ground_truth_decisions: List[Dict[str, Any]],
) -> MetricResult:
    """Compute Weighted Final Decision Recall (wFDR).

    Each ground-truth decision has a weight (fan-out dependency impact).
    """
    if not ground_truth_decisions:
        return MetricResult(score=1.0, description="No ground truth decisions provided.")

    total_weight = sum(item.get("weight", 1.0) for item in ground_truth_decisions)
    recalled_weight = 0.0
    matched_items = []
    unmatched_items = []

    combined_extracted = " \n ".join(extracted_decisions).lower()

    for item in ground_truth_decisions:
        keywords = [k.lower() for k in item.get("keywords", [])]
        concept = item.get("concept", "").lower()
        w = item.get("weight", 1.0)

        # Check match if concept or majority of keywords are present
        matched = False
        if concept and concept in combined_extracted:
            matched = True
        elif keywords:
            matched_kw = sum(1 for kw in keywords if kw in combined_extracted)
            if matched_kw >= max(1, len(keywords) // 2):
                matched = True

        if matched:
            recalled_weight += w
            matched_items.append(item.get("id", concept))
        else:
            unmatched_items.append(item.get("id", concept))

    score = round(recalled_weight / total_weight, 4) if total_weight > 0 else 0.0
    return MetricResult(
        score=score,
        details={"matched": matched_items, "unmatched": unmatched_items, "total_weight": total_weight},
        description="Weighted Final Decision Recall",
    )


def compute_nkr(
    extracted_anti_patterns: List[str],
    ground_truth_anti_patterns: List[Dict[str, Any]],
) -> MetricResult:
    """Compute Negative Knowledge Retention (NKR).

    Proportion of rejected drafts/mistakes properly flagged as to-be-avoided.
    """
    if not ground_truth_anti_patterns:
        return MetricResult(score=1.0, description="No anti-patterns in ground truth.")

    combined_ap = " \n ".join(extracted_anti_patterns).lower()
    flagged = []
    missed = []

    for ap in ground_truth_anti_patterns:
        concept = ap.get("concept", "").lower()
        keywords = [k.lower() for k in ap.get("keywords", [])]

        matched = False
        if concept and concept in combined_ap:
            matched = True
        elif keywords and any(kw in combined_ap for kw in keywords):
            matched = True

        if matched:
            flagged.append(ap.get("id", concept))
        else:
            missed.append(ap.get("id", concept))

    score = round(len(flagged) / len(ground_truth_anti_patterns), 4)
    return MetricResult(
        score=score,
        details={"flagged": flagged, "missed": missed, "total": len(ground_truth_anti_patterns)},
        description="Negative Knowledge Retention",
    )


def compute_hard_shr(
    extracted_accepted_decisions: List[str],
    ground_truth_anti_patterns: List[Dict[str, Any]],
) -> MetricResult:
    """Compute Hard State Hallucination Rate (Hard SHR).

    Checks whether any superseded/abandoned proposal was falsely asserted
    as an accepted/current decision.
    """
    if not ground_truth_anti_patterns or not extracted_accepted_decisions:
        return MetricResult(score=0.0, description="Zero hallucination.")

    combined_accepted = " \n ".join(extracted_accepted_decisions).lower()
    poisoned_items = []

    for ap in ground_truth_anti_patterns:
        keywords = [k.lower() for k in ap.get("keywords", [])]
        concept = ap.get("concept", "").lower()

        # If an anti-pattern concept appears in ACCEPTED decisions without negation
        if concept and concept in combined_accepted:
            poisoned_items.append(ap.get("id", concept))
        elif keywords and all(kw in combined_accepted for kw in keywords[:2]):
            poisoned_items.append(ap.get("id", concept))

    score = round(len(poisoned_items) / max(len(ground_truth_anti_patterns), 1), 4)
    return MetricResult(
        score=score,
        details={"poisoned_items": poisoned_items},
        description="Hard State Hallucination Rate (0.0 is ideal)",
    )


def compute_tra(
    extracted_texts: List[str],
    ground_truth_truncations: List[Dict[str, Any]],
) -> MetricResult:
    """Compute Truncation Recovery Accuracy (TRA).

    Verifies whether formulas, configs, or parameters truncated in raw logs
    were successfully penetrated and recovered.
    """
    if not ground_truth_truncations:
        return MetricResult(score=1.0, description="No truncations in ground truth.")

    combined_text = " \n ".join(extracted_texts).lower()
    recovered = []
    lost = []

    for tr in ground_truth_truncations:
        signature = tr.get("signature", "").lower()
        if signature and signature in combined_text:
            recovered.append(tr.get("id", signature))
        else:
            lost.append(tr.get("id", signature))

    score = round(len(recovered) / len(ground_truth_truncations), 4)
    return MetricResult(
        score=score,
        details={"recovered": recovered, "lost": lost, "total": len(ground_truth_truncations)},
        description="Truncation Recovery Accuracy",
    )
