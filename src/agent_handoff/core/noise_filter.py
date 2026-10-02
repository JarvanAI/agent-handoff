"""Physical syntax noise filter for session trajectories.

Pure-Python deterministic cleaning running in sub-milliseconds:
- Filters empty content / pure no-op tool_call frames
- Compresses unsemantic bash/ls/find verbose stdout
- Removes ANSI codes, progress bars, and HTTP polling noise
- Strips system heartbeats and injected skill boilerplate

`crop_dialogue` is the cut shared by session-distill and session-continue:
user messages and public assistant replies only. Tool calls, tool output,
reasoning, and harness reminders are dropped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Pattern, Set, Tuple

from agent_handoff.models import ToolCallRecord, ToolResultRecord, TurnRole, UnifiedTurn


class NoiseFilter:
    """Fast deterministic noise filter for multi-agent trajectories."""

    # ANSI escape code pattern
    _ANSI_RE: Pattern[str] = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    # Progress bar patterns
    _PROGRESS_RE: Pattern[str] = re.compile(r"(\r|\n)?(?:\[[=\-#\s]{5,}\]|\b\d{1,3}%\b).*?(\r|\n)")

    # Read-only exploratory commands
    _EXPLORATORY_COMMANDS: Set[str] = {
        "pwd",
        "whoami",
        "date",
        "which",
        "whereis",
        "echo",
        "clear",
    }

    # Harness blocks. Attributes are allowed on the opening tag. The body goes too.
    _HARNESS_TAGS: Tuple[str, ...] = (
        "EXTREMELY_IMPORTANT",
        "EXTREMELY-IMPORTANT",
        "SUBAGENT-STOP",
        "INSTRUCTIONS",
        "user_info",
        "user_rules",
        "rules",
        "user_rule",
        "system-reminder",
        "thinking",
        "think",
        "git_status",
        "agent_transcripts",
        "agent_skills",
        "available_skills",
        "agent_skill",
        "available_subagent_types",
        "available_subagent_models",
        "dynamic_tools",
        "dynamic_tool_namespaces",
        "hooks_context",
        "always_applied_workspace_rules",
        "always_applied_workspace_rule",
    )
    _INJECTED_SKILL_PATTERNS: List[Pattern[str]] = [
        re.compile(rf"<{name}\b[^>]*>.*?</{name}>", re.DOTALL | re.IGNORECASE)
        for name in _HARNESS_TAGS
    ] + [
        re.compile(r"Base directory for this skill:.*?\n", re.IGNORECASE),
    ]

    _USER_QUERY_RE: Pattern[str] = re.compile(
        r"<user_query>(.*?)</user_query>", re.DOTALL | re.IGNORECASE
    )

    _REASONING_MARKERS: Set[str] = {
        "reasoning",
        "thinking",
        "redacted_thinking",
        "agent_internal_thinking",
        "internal_thinking",
        "thought",
    }

    _HARNESS_REASONS: Set[str] = {
        "system_reminder",
        "skill_injection",
    }

    _BLANK_RUN_RE: Pattern[str] = re.compile(r"\n{3,}")

    def __init__(
        self,
        max_tool_output_lines: int = 25,
        max_tool_output_chars: int = 2000,
        strip_injected_skills: bool = True,
    ) -> None:
        self.max_tool_output_lines = max_tool_output_lines
        self.max_tool_output_chars = max_tool_output_chars
        self.strip_injected_skills = strip_injected_skills

    def clean_text(self, text: str) -> str:
        """Strip ANSI escapes, progress bars, and trailing whitespace."""
        if not text:
            return ""
        # 1. Strip ANSI escapes
        text = self._ANSI_RE.sub("", text)
        # 2. Strip progress bars
        text = self._PROGRESS_RE.sub("\n", text)
        # 3. Strip skill injection boilerplate if requested
        if self.strip_injected_skills:
            for pat in self._INJECTED_SKILL_PATTERNS:
                text = pat.sub("", text)
        text = self._BLANK_RUN_RE.sub("\n\n", text)
        return text.strip()

    def _marker_values(self, turn: UnifiedTurn) -> Set[str]:
        values: Set[str] = set()
        for key in ("type", "source", "provenance", "synthetic_reason"):
            raw = turn.metadata.get(key)
            if raw:
                values.add(str(raw).lower())
        return values

    def is_reasoning(self, turn: UnifiedTurn) -> bool:
        """True when the turn is private model reasoning, not a public reply."""
        if self._marker_values(turn) & self._REASONING_MARKERS:
            return True
        return bool(turn.metadata.get("thinking")) and not (turn.content or "").strip()

    def is_harness_turn(self, turn: UnifiedTurn) -> bool:
        """True for injected reminders that are stored on the user channel."""
        return bool(self._marker_values(turn) & self._HARNESS_REASONS)

    def public_text(self, turn: UnifiedTurn) -> str:
        """User text and public assistant text after harness wrappers are removed."""
        text = turn.content or ""
        if turn.role == TurnRole.USER:
            queries = [part.strip() for part in self._USER_QUERY_RE.findall(text)]
            queries = [part for part in queries if part]
            if queries:
                text = "\n\n".join(queries)
        return self.clean_text(text)

    def crop_dialogue(
        self, turns: List[UnifiedTurn]
    ) -> Tuple[List[UnifiedTurn], Dict[str, Any]]:
        """Keep user messages and public replies. Drop tools and reasoning.

        session-distill and session-continue both call this. Decision pruning
        stays in the distill state machine and does not happen here.
        """
        kept: List[UnifiedTurn] = []
        stats: Dict[str, int] = {
            "total_input_turns": len(turns),
            "dropped_tools": 0,
            "dropped_reasoning": 0,
            "dropped_system": 0,
            "dropped_empty": 0,
            "kept_turns": 0,
        }

        for turn in turns:
            if self.is_reasoning(turn):
                stats["dropped_reasoning"] += 1
                continue
            if turn.role == TurnRole.TOOL or (
                not (turn.content or "").strip() and (turn.tool_calls or turn.tool_results)
            ):
                stats["dropped_tools"] += 1
                continue
            if turn.role == TurnRole.SYSTEM or self.is_harness_turn(turn):
                stats["dropped_system"] += 1
                continue
            if turn.role not in (TurnRole.USER, TurnRole.ASSISTANT):
                stats["dropped_system"] += 1
                continue

            content = self.public_text(turn)
            if not content:
                stats["dropped_empty"] += 1
                continue

            metadata = {
                key: value
                for key, value in turn.metadata.items()
                if key not in {"thinking", "reasoning", "encrypted_content"}
            }
            kept.append(
                UnifiedTurn(
                    turn_id=turn.turn_id,
                    session_id=turn.session_id,
                    timestamp=turn.timestamp,
                    role=turn.role,
                    content=content,
                    tool_calls=[],
                    tool_results=[],
                    metadata=metadata,
                )
            )

        stats["kept_turns"] = len(kept)
        return kept, stats

    def compress_stdout(self, stdout: str, command: str = "") -> str:
        """Compress unsemantic verbose stdout (e.g. ls, find, tree) while keeping signal."""
        clean = self.clean_text(stdout)
        if not clean:
            return ""

        cmd_lower = command.lower().strip()
        lines = clean.splitlines()

        # Check if this is a directory listing or find command
        is_listing = any(
            cmd_lower.startswith(prefix)
            for prefix in ("ls ", "ls -", "find ", "dir ", "tree")
        )

        if is_listing and len(lines) > 20:
            head = lines[:8]
            tail = lines[-5:]
            omitted = len(lines) - 13
            return "\n".join(head + [f"... [{omitted} entries omitted] ..."] + tail)

        # General length capping for other tool outputs
        if len(lines) > self.max_tool_output_lines:
            head = lines[: self.max_tool_output_lines - 5]
            tail = lines[-5:]
            omitted = len(lines) - (len(head) + len(tail))
            return "\n".join(head + [f"... [{omitted} lines omitted] ..."] + tail)

        if len(clean) > self.max_tool_output_chars:
            omitted_chars = len(clean) - self.max_tool_output_chars
            return clean[: self.max_tool_output_chars] + f"\n... [{omitted_chars} chars omitted] ..."

        return clean

    def is_heartbeat_or_empty(self, turn: UnifiedTurn) -> bool:
        """Check if turn is a system heartbeat, empty notification, or no-op frame."""
        # Check metadata
        turn_type = str(turn.metadata.get("type", "")).lower()
        if turn_type in ("queue-operation", "checkpoint", "mode", "permission-mode", "ide_state"):
            return True

        # Check Claude startup hook attachment outputting just empty json
        if turn.metadata.get("attachment", {}).get("hookName") == "SessionStart:startup":
            stdout = str(turn.metadata.get("attachment", {}).get("stdout", "")).strip()
            if stdout in ("{}", ""):
                return True

        # Check empty content with no tool calls and no tool results
        content = turn.content.strip() if turn.content else ""
        if not content and not turn.tool_calls and not turn.tool_results:
            return True

        # Pure system confirmation with no semantic value (e.g. "{}")
        if content in ("{}", "null", "OK", "ping", "pong") and not turn.tool_calls:
            if turn.role in (TurnRole.SYSTEM, TurnRole.TOOL):
                return True

        return False

    def is_pure_exploratory_frame(self, turn: UnifiedTurn) -> bool:
        """Check if turn is purely a trivial exploratory command with no rationale.

        e.g. `pwd` or `whoami` called with zero explanation in turn content.
        """
        if turn.content.strip():
            return False
        if len(turn.tool_calls) == 1:
            tc = turn.tool_calls[0]
            cmd = str(tc.tool_args.get("command", "") or tc.tool_args.get("CommandLine", "")).strip()
            if cmd in self._EXPLORATORY_COMMANDS:
                return True
        return False

    def filter_trajectory(
        self, turns: List[UnifiedTurn]
    ) -> Tuple[List[UnifiedTurn], Dict[str, Any]]:
        """Run physical cleaning on the trajectory and return cleaned turns + stats."""
        cleaned: List[UnifiedTurn] = []
        stats: Dict[str, int] = {
            "total_input_turns": len(turns),
            "filtered_heartbeats": 0,
            "filtered_empty_frames": 0,
            "filtered_exploratory_spams": 0,
            "compressed_outputs": 0,
            "retained_turns": 0,
        }

        for turn in turns:
            # 1. Filter heartbeats and empty frames
            if self.is_heartbeat_or_empty(turn):
                stats["filtered_heartbeats"] += 1
                continue

            # 2. Filter pure exploratory no-op frames
            if self.is_pure_exploratory_frame(turn):
                stats["filtered_exploratory_spams"] += 1
                continue

            # 3. Clean content
            cleaned_content = self.clean_text(turn.content)

            # 4. Clean and compress tool results
            cleaned_tool_results: List[ToolResultRecord] = []
            for tr in turn.tool_results:
                original_len = len(tr.content)
                compressed = self.compress_stdout(tr.content)
                if len(compressed) < original_len:
                    stats["compressed_outputs"] += 1
                cleaned_tool_results.append(
                    ToolResultRecord(
                        tool_name=tr.tool_name,
                        content=compressed,
                        status=tr.status,
                        call_id=tr.call_id,
                    )
                )

            # If cleaning reduced content to empty and there are no valid tool calls/results, skip
            if not cleaned_content and not turn.tool_calls and not cleaned_tool_results:
                stats["filtered_empty_frames"] += 1
                continue

            # Create clean copy
            turn_copy = UnifiedTurn(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                timestamp=turn.timestamp,
                role=turn.role,
                content=cleaned_content,
                raw_content=turn.content if cleaned_content != turn.content else None,
                tool_calls=turn.tool_calls,
                tool_results=cleaned_tool_results,
                metadata=turn.metadata,
            )
            cleaned.append(turn_copy)

        stats["retained_turns"] = len(cleaned)
        return cleaned, stats
