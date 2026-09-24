"""Zero-Loss Agent-to-Agent (A2A) Handoff Envelope Generator.

Outputs lightweight, high-fidelity JSON/YAML handoff envelopes for downstream Agents,
containing effective Decision DAGs, Anti-pattern pitfall lists, and pending task queues.
Pure-Python zero-dependency implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Union
import uuid

from handoff.models import (
    AnchorRecord,
    AntiPatternRecord,
    DecisionEntity,
    DecisionState,
    DistillationResult,
)


class HandoffEnvelopeGenerator:
    """Generates machine-readable A2A Handoff Envelopes in JSON or YAML."""

    def __init__(self, schema_version: str = "1.0.0") -> None:
        self.schema_version = schema_version

    def build_envelope_dict(self, result: DistillationResult) -> Dict[str, Any]:
        """Construct the standardized structured dictionary for the handoff envelope."""
        now_iso = datetime.now(timezone.utc).isoformat()
        envelope_id = f"env_{uuid.uuid4().hex[:12]}"

        # 1. Build Decision DAG
        active_decisions: List[Dict[str, Any]] = []
        edges: List[Dict[str, str]] = []

        # Filter for accepted/active decisions
        prev_node_id: Optional[str] = None
        for d in result.decisions:
            if d.state in (DecisionState.ACCEPTED, DecisionState.PROPOSED):
                node_dict = {
                    "id": d.entity_id,
                    "topic": d.topic,
                    "status": d.state.value,
                    "decision": d.decision,
                    "rationale": d.rationale,
                    "turn_id": d.turn_id,
                    "tags": d.tags,
                }
                active_decisions.append(node_dict)

                # Connect chronological DAG edges
                if prev_node_id:
                    edges.append({"from": prev_node_id, "to": d.entity_id, "type": "sequence"})
                prev_node_id = d.entity_id

        # 2. Build Anti-Patterns List
        anti_patterns: List[Dict[str, Any]] = [ap.to_dict() for ap in result.anti_patterns]

        # 3. Build Anchors
        anchors: List[Dict[str, Any]] = [a.to_dict() for a in result.anchors]

        # 4. Compression Ratio
        comp_ratio = 0.0
        if result.raw_turns_count > 0:
            comp_ratio = round(
                (1.0 - len(result.cleaned_turns) / result.raw_turns_count) * 100, 1
            )

        # 4. Recovered Technical Signatures from Penetrated Logs
        recovered_parameters: List[str] = []
        for t in result.cleaned_turns:
            if t.metadata.get("penetrated"):
                for token in re.findall(r"`([a-zA-Z0-9_\-\.]{3,40})`", t.content):
                    if token not in recovered_parameters:
                        recovered_parameters.append(token)

        envelope: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "envelope_id": envelope_id,
            "generated_at": now_iso,
            "source_session": {
                "session_id": result.session_id,
                "provider": result.provider,
                "raw_turns_count": result.raw_turns_count,
                "distilled_turns_count": len(result.cleaned_turns),
                "compression_ratio_percent": comp_ratio,
                "parse_duration_ms": result.metrics.get("duration_ms", 0),
            },
            "decision_dag": {
                "nodes": active_decisions,
                "edges": edges,
            },
            "anti_patterns": anti_patterns,
            "anchors": anchors,
            "penetrated_recoveries": recovered_parameters[:500],
            "open_tasks": result.open_tasks,
            "context_digest": {
                "key_decisions_summary": [d["decision"] for d in active_decisions],
                "verified_anchors_count": len(anchors),
                "pending_tasks_count": len(result.open_tasks),
            },
        }
        return envelope

    def to_json(self, result: DistillationResult, indent: int = 2) -> str:
        """Serialize envelope to formatted JSON string."""
        data = self.build_envelope_dict(result)
        return json.dumps(data, indent=indent, ensure_ascii=False)

    def to_yaml(self, result: DistillationResult) -> str:
        """Serialize envelope to YAML string (uses PyYAML if installed, or pure-Python emitter)."""
        data = self.build_envelope_dict(result)
        try:
            import yaml  # type: ignore

            return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        except ImportError:
            return self._pure_python_yaml_dump(data)

    def _pure_python_yaml_dump(self, data: Any, indent_level: int = 0) -> str:
        """Simple recursive pure-Python YAML dumper."""
        indent = "  " * indent_level
        lines: List[str] = []

        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"{indent}{k}:")
                    sub = self._pure_python_yaml_dump(v, indent_level + 1)
                    lines.append(sub)
                elif v is None:
                    lines.append(f"{indent}{k}: null")
                elif isinstance(v, bool):
                    lines.append(f"{indent}{k}: {'true' if v else 'false'}")
                elif isinstance(v, (int, float)):
                    lines.append(f"{indent}{k}: {v}")
                else:
                    s = str(v).replace("\n", " ")
                    if any(ch in s for ch in (":", "#", "{", "}", "[", "]", ",", "&", "*")):
                        lines.append(f'{indent}{k}: "{s}"')
                    else:
                        lines.append(f"{indent}{k}: {s}")

        elif isinstance(data, list):
            if not data:
                return f"{indent}[]"
            for item in data:
                if isinstance(item, dict):
                    # First key goes on the '-' line
                    keys = list(item.keys())
                    if not keys:
                        lines.append(f"{indent}- {{}}")
                        continue
                    first_k = keys[0]
                    first_v = item[first_k]
                    if isinstance(first_v, (dict, list)):
                        lines.append(f"{indent}- {first_k}:")
                        sub = self._pure_python_yaml_dump(first_v, indent_level + 2)
                        lines.append(sub)
                    else:
                        lines.append(f"{indent}- {first_k}: {first_v}")
                    for rem_k in keys[1:]:
                        rem_v = item[rem_k]
                        if isinstance(rem_v, (dict, list)):
                            lines.append(f"{indent}  {rem_k}:")
                            sub = self._pure_python_yaml_dump(rem_v, indent_level + 2)
                            lines.append(sub)
                        else:
                            lines.append(f"{indent}  {rem_k}: {rem_v}")
                elif isinstance(item, (int, float, bool)):
                    lines.append(f"{indent}- {item}")
                else:
                    lines.append(f'{indent}- "{item}"')

        return "\n".join(lines)

    def write_to_file(self, result: DistillationResult, output_path: Union[str, Path]) -> Path:
        """Write handoff envelope to JSON or YAML based on file extension."""
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.suffix.lower() in (".yaml", ".yml"):
            content = self.to_yaml(result)
        else:
            content = self.to_json(result)

        path.write_text(content, encoding="utf-8")
        return path
