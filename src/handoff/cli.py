"""Command-line interface (CLI) for session-distill.

Usage:
  session-distill run --from antigravity --session <id> --output-playbook <path> --output-handoff <path>
  session-distill run --from claude-code --file <path> --output-playbook <path>
  session-distill inspect <path_or_id>
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List, Optional

from handoff.engine import DistillationEngine
from handoff.outputs.handoff_envelope import HandoffEnvelopeGenerator
from handoff.outputs.playbook_generator import PlaybookGenerator


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handoff",
        description="Universal Multi-Agent Handoff Protocol & Trajectory Distillation Engine.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: run / distill (Receiver-side offline session distillation)
    for cmd_name, help_text in [
        ("run", "Distill a session and generate playbooks/envelopes (default)."),
        ("distill", "Receiver mode: Distill a messy predecessor session into ADRs and handoff envelopes."),
    ]:
        run_parser = subparsers.add_parser(cmd_name, help=help_text)
        run_parser.add_argument(
            "--from",
            dest="provider",
            choices=["antigravity", "claude", "claude-code", "codex", "cursor", "grok"],
            help="Source agent provider (auto-detected if omitted).",
        )
        run_parser.add_argument(
            "--session",
            "-s",
            help="Session ID or session folder name.",
        )
        run_parser.add_argument(
            "--file",
            help="Path to specific session transcript or export file.",
        )
        run_parser.add_argument(
            "--dir",
            help="Path to session directory.",
        )
        run_parser.add_argument(
            "--output-playbook",
            "-p",
            help="Output path for human-readable Markdown ADR Playbook.",
        )
        run_parser.add_argument(
            "--output-handoff",
            "-o",
            help="Output path for downstream Agent A2A Handoff Envelope (.json or .yaml).",
        )
        run_parser.add_argument(
            "--title",
            help="Custom title for the Markdown ADR Playbook.",
        )
        run_parser.add_argument(
            "--verbose",
            "-v",
            action="store_true",
            help="Print verbose distillation metrics to stdout.",
        )

    # Command: send / pack (Sender-side online handoff)
    send_parser = subparsers.add_parser(
        "send",
        help="Sender mode: Package current agent context/task into a zero-loss handoff envelope.",
    )
    send_parser.add_argument(
        "--task",
        "-t",
        default="TASK-ACTIVE",
        help="Current Task ID (e.g. TASK-123).",
    )
    send_parser.add_argument(
        "--from-agent",
        default="active-agent",
        help="Sending agent handle/role.",
    )
    send_parser.add_argument(
        "--to-agent",
        default="successor-agent",
        help="Target recipient agent handle/role.",
    )
    send_parser.add_argument(
        "--summary",
        "-m",
        required=True,
        help="Concise summary of progress and handoff reason.",
    )
    send_parser.add_argument(
        "--decision",
        action="append",
        default=[],
        help="Key decisions to record (can be specified multiple times).",
    )
    send_parser.add_argument(
        "--anti-pattern",
        action="append",
        default=[],
        help="Anti-patterns / discarded paths to avoid (can be specified multiple times).",
    )
    send_parser.add_argument(
        "--output",
        "-o",
        help="Path to output handoff envelope JSON/YAML. If omitted, prints to stdout.",
    )

    # Command: inspect
    inspect_parser = subparsers.add_parser("inspect", help="Quickly inspect a session without writing files.")
    inspect_parser.add_argument(
        "target",
        help="Path to file/directory or session ID to inspect.",
    )
    inspect_parser.add_argument(
        "--from",
        dest="provider",
        help="Optional provider override.",
    )

    return parser


def handle_run(args: argparse.Namespace) -> int:
    target = args.file or args.dir or args.session
    if not target:
        print("Error: Must specify one of --session, --file, or --dir", file=sys.stderr)
        return 1

    engine = DistillationEngine()
    try:
        result = engine.distill(target, provider=args.provider)
    except Exception as e:
        print(f"Error during distillation: {e}", file=sys.stderr)
        return 2

    # Print summary
    duration_ms = result.metrics.get("duration_ms", 0)
    print(f"[session-distill] Successfully distilled session '{result.session_id}' in {duration_ms:.2f}ms")
    print(f"  Provider: {result.provider}")
    print(f"  Raw turns: {result.raw_turns_count} -> Cleaned turns: {len(result.cleaned_turns)}")
    print(f"  Decisions extracted: {len(result.decisions)}")
    print(f"  Anti-patterns recorded: {len(result.anti_patterns)}")
    print(f"  Anchors identified: {len(result.anchors)}")

    # Write playbook if requested
    if args.output_playbook:
        playbook_gen = PlaybookGenerator(title=args.title)
        out_path = playbook_gen.write_to_file(result, args.output_playbook)
        print(f"  Playbook written to: {out_path}")

    # Write handoff envelope if requested
    if args.output_handoff:
        envelope_gen = HandoffEnvelopeGenerator()
        out_path = envelope_gen.write_to_file(result, args.output_handoff)
        print(f"  Handoff envelope written to: {out_path}")

    if args.verbose:
        print("\n--- Decision Entities ---")
        for d in result.decisions:
            print(f"  [{d.entity_id}] ({d.state.value}) {d.topic}: {d.decision}")
        if result.anti_patterns:
            print("\n--- Anti-patterns ---")
            for ap in result.anti_patterns:
                print(f"  [AVOID] {ap.topic}: {ap.abandoned_proposal} -> {ap.recommended_alternative}")

    return 0


def handle_inspect(args: argparse.Namespace) -> int:
    engine = DistillationEngine()
    try:
        result = engine.distill(args.target, provider=args.provider)
    except Exception as e:
        print(f"Error inspecting target: {e}", file=sys.stderr)
        return 2

    duration_ms = result.metrics.get("duration_ms", 0)
    print("========================================")
    print(f"  Session ID: {result.session_id}")
    print(f"  Provider:   {result.provider}")
    print(f"  Parse Time: {duration_ms:.2f} ms")
    print(f"  Raw Turns:  {result.raw_turns_count}")
    print(f"  Clean Turns:{len(result.cleaned_turns)}")
    print(f"  Decisions:  {len(result.decisions)}")
    print(f"  Anchors:    {len(result.anchors)}")
    print(f"  Anti-Patterns: {len(result.anti_patterns)}")
    print("========================================")
    for d in result.decisions:
        print(f"  * {d.entity_id} [{d.state.value}]: {d.topic} -> {d.decision}")
    for a in result.anchors:
        print(f"  # Anchor [{a.anchor_type.value}]: {a.description} (step {a.turn_id})")
    return 0


def handle_send(args: argparse.Namespace) -> int:
    import json
    from datetime import datetime, timezone

    envelope = {
        "schema_version": "1.0.0",
        "protocol": "A2A-Handoff-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "handoff_mode": "sender_online",
        "task_id": args.task,
        "from_agent": args.from_agent,
        "to_agent": args.to_agent,
        "summary": args.summary,
        "decisions": [
            {"id": f"DEC-{i+1:03d}", "description": dec, "state": "ACCEPTED"}
            for i, dec in enumerate(args.decision)
        ],
        "anti_patterns": [
            {"id": f"AVOID-{i+1:03d}", "avoid": ap, "reason": "superseded or failed"}
            for i, ap in enumerate(args.anti_pattern)
        ],
    }

    formatted = json.dumps(envelope, indent=2, ensure_ascii=False)
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted, encoding="utf-8")
        print(f"[handoff send] Handoff envelope successfully written to: {out_path}")
    else:
        print(formatted)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    if args.command in ("run", "distill"):
        return handle_run(args)
    elif args.command == "send":
        return handle_send(args)
    elif args.command == "inspect":
        return handle_inspect(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())

