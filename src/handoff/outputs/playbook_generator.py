"""Markdown Architecture Decision Record (ADR) and Defense Playbook Generator.

Produces human-readable ADR playbooks resolving compact memory loss and code review inquiries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from handoff.models import (
    AnchorRecord,
    AnchorType,
    AntiPatternRecord,
    DecisionEntity,
    DecisionState,
    DistillationResult,
    UnifiedTurn,
)


class PlaybookGenerator:
    """Generates comprehensive human-readable Markdown ADR & Defense Playbooks."""

    def __init__(self, title: Optional[str] = None) -> None:
        self.title = title

    def generate(self, result: DistillationResult) -> str:
        """Generate complete Markdown Playbook from DistillationResult."""
        lines: List[str] = []

        # 1. Header & Metadata
        display_title = self.title or f"架构决策与逐行防御复盘手册: {result.session_id}"
        lines.append(f"# {display_title}\n")

        compression_ratio = 0.0
        if result.raw_turns_count > 0:
            compression_ratio = round(
                (1.0 - len(result.cleaned_turns) / result.raw_turns_count) * 100, 1
            )

        duration_ms = result.metrics.get("duration_ms", 0)
        lines.append("> [!NOTE]")
        lines.append(f"> **会话 ID**: `{result.session_id}` | **源 Provider**: `{result.provider}`")
        lines.append(f"> **提纯时间**: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}` | **解析耗时**: `{duration_ms:.2f} ms`")
        lines.append(f"> **原始帧数**: `{result.raw_turns_count}` | **提纯后帧数**: `{len(result.cleaned_turns)}` | **无损压缩比**: `{compression_ratio}%`\n")

        # 2. Executive Summary / ADR Table
        lines.append("## 一、 架构决策总览 (ADR Summary)\n")
        if not result.decisions:
            lines.append("*本会话未检测到显著的显式架构决策实体。*\n")
        else:
            lines.append("| ADR 编号 | 决策主题 (Topic) | 最终裁决 (Decision) | 状态 (Status) | 关键依据 (Rationale) | 始发步骤 |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for d in result.decisions:
                status_badge = (
                    "✅ `ACCEPTED`"
                    if d.state == DecisionState.ACCEPTED
                    else "⚠️ `SUPERSEDED`"
                    if d.state == DecisionState.SUPERSEDED
                    else f"`{d.state.value}`"
                )
                safe_decision = d.decision.replace("|", "\\|")
                safe_rationale = (d.rationale[:60] + "..." if len(d.rationale) > 60 else d.rationale).replace("|", "\\|")
                lines.append(
                    f"| **{d.entity_id}** | `{d.topic}` | **{safe_decision}** | {status_badge} | {safe_rationale} | `{d.turn_id}` |"
                )
            lines.append("")

        # 3. Detailed Architecture Decision Records (ADRs)
        lines.append("## 二、 核心架构决策详情 (Architecture Decision Records)\n")
        if not result.decisions:
            lines.append("*暂无详细决策记录。*\n")
        else:
            for d in result.decisions:
                lines.append(f"### {d.entity_id}: 采纳 `{d.decision}` ({d.topic})\n")
                lines.append(f"- **当前状态**: **{d.state.value}**" + (f" (由 `{d.superseded_by}` 替代)" if d.superseded_by else ""))
                lines.append(f"- **始发位置**: `{d.turn_id}`")
                lines.append(f"- **决策动因与背景**: {d.rationale}")

                if d.alternatives_considered:
                    lines.append("- **评估过的备选/废弃方案**:")
                    for alt in d.alternatives_considered:
                        lines.append(f"  - ❌ *{alt}*")

                if d.consequences:
                    lines.append("- **技术影响与收益**:")
                    for c in d.consequences:
                        lines.append(f"  - 💡 {c}")

                if d.evidence_snippets:
                    lines.append("- **核心上下文佐证**:")
                    for snip in d.evidence_snippets[:2]:
                        clean_snip = snip.replace("\n", " ").strip()
                        lines.append(f"  > \"{clean_snip}\"")

                lines.append("")

        # 4. Anti-Patterns & Pitfall Guide
        lines.append("## 三、 废案避坑清单 (Anti-Patterns & Deprecated Drafts)\n")
        if not result.anti_patterns:
            lines.append("✅ *本次提纯未发现被推翻或产生隐患的废案，决策路径保持高度收敛。*\n")
        else:
            lines.append("> [!WARNING]")
            lines.append("> 以下方案在开发演进中已被明确废弃或证明存在隐患，下游开发及后续审查严禁重新引入：\n")
            for idx, ap in enumerate(result.anti_patterns, 1):
                lines.append(f"#### 3.{idx} 避坑点: 废弃 `{ap.abandoned_proposal}`")
                lines.append(f"- **涉及领域**: `{ap.topic}`")
                lines.append(f"- **被淘汰原因 / 踩坑风险**: {ap.pitfall_reason}")
                lines.append(f"- **正确替代路径**: **{ap.recommended_alternative}**")
                lines.append("")

        # 5. Reverse Anchor & Causal Chain Backfill
        lines.append("## 四、 终局锚定与因果链 (Reverse Anchor & Causal Chain)\n")
        if not result.anchors:
            lines.append("*未定位到终局锚点。*\n")
        else:
            for idx, anchor in enumerate(result.anchors, 1):
                type_name = (
                    "自动化测试验证"
                    if anchor.anchor_type == AnchorType.TEST_VERIFIED
                    else "用户/专家明确确认"
                    if anchor.anchor_type == AnchorType.USER_CONFIRMED
                    else "核心代码交付落盘"
                    if anchor.anchor_type == AnchorType.CODE_COMMITTED
                    else "目标交付总结"
                )
                lines.append(f"### 4.{idx} 终局锚点: [{type_name}] `{anchor.turn_id}`\n")
                lines.append(f"- **锚点描述**: {anchor.description}")
                if anchor.evidence:
                    lines.append(f"- **硬核事实证据**: `{anchor.evidence[:120]}`")

                if anchor.causal_chain:
                    lines.append("- **因果溯源链条 (Forward Causal Chain)**:")
                    chain_str = " ➔ ".join(f"`{cid}`" for cid in anchor.causal_chain)
                    lines.append(f"  {chain_str}")
                lines.append("")

        # 6. Defensive Implementation Review
        lines.append("## 五、 逐行防御与实现复盘 (Implementation Defense)\n")
        lines.append("- **确定性解析与零 Token 架构**: 核心管道全由物理解析器与正则状态机驱动，避免因 LLM 幻觉产生漏项或高昂的上下文开销。")
        lines.append("- **穿透截断保护**: 遇到 `truncated_fields` 时自动从全量日志中恢复原始上下文，保证关键断言与代码段无损。")
        lines.append("- **Latest-Wins 冲突仲裁**: 状态机支持多轮会话中架构思路的演进与替换，确保输出的手册始终呈现最终生效方案。")
        lines.append("")

        # 7. Open Tasks & Queue
        lines.append("## 六、 未决任务与后续待办队列 (Pending Tasks)\n")
        if not result.open_tasks:
            lines.append("🎉 *所有已知任务均已在本次会话中闭环，无遗留挂起项。*\n")
        else:
            for task in result.open_tasks:
                lines.append(f"- [ ] {task}")
            lines.append("")

        return "\n".join(lines)

    def write_to_file(self, result: DistillationResult, output_path: Union[str, Path]) -> Path:
        """Render and save playbook markdown file."""
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.generate(result)
        path.write_text(content, encoding="utf-8")
        return path
