"""Command-line interface (CLI) for session-distill.

Usage:
  session-distill run --from antigravity --session <id> --output-playbook <path> --output-handoff <path>
  session-distill run --from claude-code --file <path> --output-playbook <path>
  session-distill inspect <path_or_id>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List, Optional

from agent_handoff.version import __version__


_LEGACY_COMMANDS = {"run", "distill", "send", "inspect", "search"}


def _detect_prog() -> str:
    name = Path(sys.argv[0]).name
    if name in {
        "agent-handoff",
        "handoff",
        "session",
        "session-handoff",
        "session-distill",
        "session-search",
    }:
        return name
    return "session"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_detect_prog(),
        description=(
            "Universal Multi-Agent Handoff Protocol, Trajectory Distillation, "
            "and Session Search Engine."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Legacy names. run and distill call the same function. send is the handoff scenario.
    for cmd_name, help_text in [
        ("run", "Same as distill: the next session analyzes a known previous session."),
        ("distill", "Next session analyzes a known previous session."),
    ]:
        _add_distill_arguments(subparsers.add_parser(cmd_name, help=help_text))

    _add_handoff_arguments(
        subparsers.add_parser(
            "send",
            help="Previous session writes a short handoff. Prefer `session handoff`.",
        )
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

    search_parser = subparsers.add_parser(
        "search",
        help="Search session transcripts (agentsview, then embedded FTS5).",
    )
    _add_search_arguments(search_parser)

    return parser


def _add_distill_arguments(parser: argparse.ArgumentParser, *, with_inspect: bool = False) -> None:
    parser.add_argument(
        "--from",
        dest="provider",
        choices=["antigravity", "claude", "claude-code", "codex", "cursor", "grok"],
        help="Source agent provider (auto-detected if omitted).",
    )
    parser.add_argument("--session", "-s", help="Session ID or session folder name.")
    parser.add_argument("--file", help="Path to a session transcript or export file.")
    parser.add_argument("--dir", help="Path to a session directory.")
    parser.add_argument("--output-playbook", "-p", help="Write the human-readable playbook to this path.")
    parser.add_argument("--output-handoff", "-o", help="Write the distill envelope (.json or .yaml) to this path.")
    parser.add_argument("--title", help="Title for the playbook.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print decision and anti-pattern details.")
    if with_inspect:
        parser.add_argument(
            "--inspect",
            action="store_true",
            help="Print the analysis only. Requires a positional session path or id.",
        )
        parser.add_argument("target", nargs="?", help="Session path or id, used with --inspect.")


def _add_handoff_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task", "-t", default="TASK-ACTIVE", help="Task id.")
    parser.add_argument("--from-agent", default="active-agent", help="Sending agent.")
    parser.add_argument("--to-agent", default="successor-agent", help="Receiving agent.")
    parser.add_argument("--summary", "-m", required=True, help="What the next session needs to know.")
    parser.add_argument("--decision", action="append", default=[], help="Decision to carry forward. Repeatable.")
    parser.add_argument("--anti-pattern", action="append", default=[], help="Discarded path to avoid. Repeatable.")
    parser.add_argument("--output", "-o", help="Write the handoff JSON here. Default is stdout.")


def _dispatch_distill(args: argparse.Namespace) -> int:
    if getattr(args, "inspect", False):
        if not getattr(args, "target", None):
            print("Error: --inspect requires a session path or id", file=sys.stderr)
            return 2
        return handle_inspect(args)
    return handle_run(args)


def _add_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("query", help="Search query (at least 3 characters).")
    parser.add_argument("--project", help="Restrict results to one project name.")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="JSONL file or directory to index with the embedded engine. Repeatable.",
    )
    parser.add_argument(
        "--db",
        help="Embedded index path. Defaults to ./.handoff_index.db when Tier 2 runs.",
    )
    parser.add_argument("--limit", type=int, default=10, help="Maximum sessions to return.")
    parser.add_argument(
        "--engine",
        choices=["auto", "agentsview", "embedded"],
        default="auto",
        help="auto prefers agentsview and falls back to the embedded engine.",
    )
    parser.add_argument("--json", action="store_true", help="Print the search envelope as JSON.")


def format_search_text(envelope) -> str:
    """Render a search envelope as a short table plus snippets."""

    lines = [
        f"engine: {envelope.engine}  hits: {envelope.total_hits}  query: {envelope.query}",
    ]
    if envelope.project:
        lines.append(f"project: {envelope.project}")
    if not envelope.results:
        lines.append("(no matches)")
        return "\n".join(lines)
    for hit in envelope.results:
        turns = ",".join(str(turn) for turn in hit.matched_turns)
        created = f"  {hit.created_at}" if hit.created_at else ""
        lines.append("")
        lines.append(
            f"{hit.score:8.4f}  {hit.harness:<18}  {hit.session_id}  turns=[{turns}]{created}"
        )
        snippet = " ".join((hit.snippet or "").split())
        if len(snippet) > 240:
            snippet = snippet[:237] + "..."
        if snippet:
            lines.append(f"         {snippet}")
    return "\n".join(lines)


def handle_run(args: argparse.Namespace) -> int:
    from agent_handoff.engine import DistillationEngine
    from agent_handoff.outputs.handoff_envelope import HandoffEnvelopeGenerator
    from agent_handoff.outputs.playbook_generator import PlaybookGenerator
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
    from agent_handoff.engine import DistillationEngine

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


def handle_search(args: argparse.Namespace) -> int:
    from agent_handoff.search.router import search_sessions

    query = (args.query or "").strip()
    if len(query) < 3:
        print("Error: query must be at least 3 characters", file=sys.stderr)
        return 2
    paths = [Path(path) for path in (args.path or [])]
    if paths:
        discover = False
    elif args.db:
        discover = False
    else:
        discover = True
    try:
        envelope = search_sessions(
            query,
            project=args.project,
            limit=args.limit,
            paths=paths or None,
            db_path=Path(args.db) if args.db else None,
            engine=args.engine,
            discover=discover,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_search_text(envelope))
    return 0


def handle_send(args: argparse.Namespace) -> int:
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
    elif args.command == "search":
        return handle_search(args)

    return 0


def session_main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``session handoff|distill|search``."""

    parser = argparse.ArgumentParser(
        prog="session",
        description="Find a session, analyze it, or hand it to the next session.",
    )
    parser.add_argument("--version", action="version", version=f"session {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_handoff_arguments(commands.add_parser("handoff", help="Previous session writes a short handoff."))
    _add_distill_arguments(
        commands.add_parser("distill", help="Next session analyzes a known previous session."),
        with_inspect=True,
    )
    _add_search_arguments(commands.add_parser("search", help="Find sessions that match a query."))
    args = parser.parse_args(argv)
    if args.command == "handoff":
        return handle_send(args)
    if args.command == "distill":
        return _dispatch_distill(args)
    if args.command == "search":
        return handle_search(args)
    parser.print_help()
    return 1


def handoff_main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the ``session-handoff`` console script."""

    parser = argparse.ArgumentParser(
        prog="session-handoff",
        description="Previous session writes a short handoff for the next session.",
    )
    parser.add_argument("--version", action="version", version=f"session-handoff {__version__}")
    _add_handoff_arguments(parser)
    return handle_send(parser.parse_args(argv))


def distill_main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``session-distill``.

    A leading ``run``, ``inspect``, ``send``, or ``search`` keeps the older CLI.
    Any other invocation analyzes one known session.
    """

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in _LEGACY_COMMANDS:
        return main(args)
    parser = argparse.ArgumentParser(
        prog="session-distill",
        description="Next session analyzes a known previous session.",
    )
    parser.add_argument("--version", action="version", version=f"session-distill {__version__}")
    _add_distill_arguments(parser, with_inspect=True)
    return _dispatch_distill(parser.parse_args(args))


def search_main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the ``session-search`` console script."""

    parser = argparse.ArgumentParser(
        prog="session-search",
        description="Find sessions that match a query.",
    )
    parser.add_argument("--version", action="version", version=f"session-search {__version__}")
    _add_search_arguments(parser)
    return handle_search(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())

