# session-distill-bench: Benchmark for Multi-Agent Handoff & Trajectory Distillation

`session-distill-bench` is a specialized benchmark suite designed and open-sourced to rigorously evaluate **Handoff-direction** skills, tools, and multi-agent coordination frameworks.

## Why `session-distill-bench`?

Traditional long-context benchmarks (such as LongBench, BAMBOO, InfiniteBench, or MeetingBank) focus primarily on *needle-in-a-haystack retrieval* or *prose meeting summarization*. They fail to evaluate the real-world friction of agentic workflows:

1. **Non-Monotonic Belief Revision**: In multi-turn coding sessions (100–1000 turns), agents constantly propose, debate, reject, and supersede technical plans. Standard summarizers suffer from **Superseded Draft Poisoning** by mixing discarded proposals with final decisions.
2. **Log Truncation & Penetration**: Production agents (Antigravity, Claude Code, Cursor) aggressively truncate verbose tool outputs (e.g. `[truncated 45KB]`), hiding vital configs, URLs, and formula parameters.
3. **Downstream Task Continuation (A2A Handoff)**: A handoff artifact is only useful if a successor agent can successfully execute the remainder of the task without context blowup or hallucination.

`session-distill-bench` evaluates how well a Handoff tool or skill transforms messy, hundred-turn execution trajectories into high-fidelity, minimal-token handover envelopes and action playbooks.

---

## Metric Specification (Opus 4.6 Validated)

The metric suite was peer-reviewed and validated by Claude Opus 4.6 (Thinking), introducing the killer efficiency metric **CER**:

### 1. Context Efficiency Ratio (CER)
$$\text{CER} = \frac{\text{TCSR}}{\text{Handoff Tokens} / \text{Context Window Size}}$$
- **TCSR (Task Continuation Success Rate)**: Whether the downstream agent completes the subsequent goal without asking for prior context.
- **CER Interpretation**: Measures the return on context investment. A high CER proves that a tool delivers 90%+ task completion with only 1% context footprint.

### 2. Weighted Final Decision Recall (wFDR)
$$\text{wFDR} = \frac{\sum_{d \in D_{\text{final}}} w(d) \cdot \mathbb{I}(d \in \text{Extracted})}{\sum_{d \in D_{\text{final}}} w(d)}$$
- Weights $w(d)$ reflect causal dependency fan-out (e.g., losing a foundational database architecture decision penalizes 5x more than an isolated variable rename).

### 3. Negative Knowledge Retention (NKR-Depth)
$$\text{NKR} = \frac{|\text{Anti-Patterns Correctly Flagged}|}{|\text{Total Abandoned / Rejected Proposals}|}$$
- Measures whether the downstream agent is protected against repeating discarded mistakes (e.g., rejected schemas, deprecated models, failed dependencies).

### 4. Hard State Hallucination Rate (Hard-SHR)
$$\text{Hard-SHR} = \frac{|\text{Superseded Drafts Asserted as Current Truth}|}{|\text{Total Extracted Statements}|}$$
- Strict 0% tolerance for declaring a rolled-back or overruled draft as the final consensus.

### 5. Truncation Recovery Accuracy (TRA)
$$\text{TRA} = \frac{|\text{Key Parameters Recovered from Truncated Logs}|}{|\text{Total Ground-Truth Hidden Parameters}|}$$
- Tests deep log penetration through system logs or secondary transcript layers.

---

## Baselines & Comparison

| Strategy | Description | Token Footprint | CER | Anti-Pattern Awareness | Zero-Token Parsing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Raw History** | Feeding all 1000 turns to successor | 100% (High risk of overflow) | ~1.0 | Implicit only | N/A |
| **Sliding Pager** | Last $K$ turns (default windowing) | 10–20% | Low (Loses early roots) | Low | Yes |
| **Naive LLM Summary**| Recursive map-reduce prose summary | 5–10% | Medium (Prone to drift) | Hallucination prone| No (Burns tokens) |
| **Handoff Distill** | Deterministic FSM + Reverse Anchor | **< 1%** | **High (> 10.0)** | **Explicit anti-pattern DAG** | **Yes (0 tokens)** |

---

## Dataset Layout

```text
benchmark/
├── README.md                          # Benchmark specification & usage
├── run_bench.py                       # Evaluation runner & scorecard generator
├── harness/
│   ├── metrics.py                     # Quantitative metrics implementation
│   └── evaluators.py                  # Ground-truth alignment evaluators
├── datasets/
│   └── sample_001_dogfood/            # Sample 001: 962-turn Antigravity session
│       ├── metadata.json              # Provider, turns, domain, complexity
│       ├── raw_trajectory.jsonl       # Original session transcript (or pointer)
│       └── ground_truth.json          # Explicit Engineering Belief State (EEBS)
└── results/
    └── sample_001_scorecard.json      # Generated benchmark results
```

## Running the Benchmark

```bash
# Run benchmark on sample-001
python benchmark/run_bench.py --sample sample_001_dogfood

# Run across all datasets with verbose breakdown
python benchmark/run_bench.py --all --verbose
```
