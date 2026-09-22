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

from session_distill.engine import DistillationEngine
from session_distill.outputs.handoff_envelope import HandoffEnvelopeGenerator
from session_distill.outputs.playbook_generator import PlaybookGenerator


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handoff",
        description="Universal Multi-Agent Handoff Protocol & Trajectory Distillation Engine.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Distill a session and generate playbooks/envelopes.")
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "run":
        return handle_run(args)
    elif args.command == "inspect":
        return handle_inspect(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
