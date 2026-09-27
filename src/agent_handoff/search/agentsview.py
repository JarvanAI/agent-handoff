"""Tier 1 adapter: agentsview CLI, with an MCP fallback.

The CLI invocation follows the architecture contract::

    agentsview session search "<QUERY>" --project "<PROJECT>" --json

When the CLI is missing or returns a non-zero status, and the ``agentsview``
binary can still speak MCP, the adapter calls the ``search_sessions`` tool
(and the RFC alias ``session_search`` if the server only exposes that name).
"""

from __future__ import annotations

import json
import os
import select
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

from agent_handoff.search.base import RRF_K, SearchEnvelope, SearchHit, BaseSearchEngine

DEFAULT_PORT = 59090
_MCP_TOOLS = ("search_sessions", "session_search")


class AgentsViewError(RuntimeError):
    """agentsview was reachable but the search call failed."""


class AgentsViewUnavailable(AgentsViewError):
    """Neither the agentsview CLI nor its local service is usable."""


def cli_installed(command: str = "agentsview") -> bool:
    """Return True when ``command`` resolves on PATH or is an executable file."""

    if os.path.sep in command:
        return os.path.isfile(command) and os.access(command, os.X_OK)
    return shutil.which(command) is not None


def service_listening(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 0.2) -> bool:
    """Return True when a TCP listener accepts connections on the agentsview port."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _snippet(text: str) -> str:
    return (
        text.replace("<mark>", "<b>")
        .replace("</mark>", "</b>")
        .replace("[MATCH]", "<b>")
        .replace("[/MATCH]", "</b>")
    )


def _as_int_list(value: Any) -> List[int]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        turns: List[int] = []
        for item in value:
            if isinstance(item, int) and not isinstance(item, bool):
                turns.append(item)
            elif isinstance(item, str) and item.lstrip("-").isdigit():
                turns.append(int(item))
        return turns
    return []


def _extract_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Accept CLI matches, MCP structured content, and a ready-made envelope."""

    if isinstance(payload.get("structuredContent"), dict):
        return _extract_rows(payload["structuredContent"])
    for key in ("matches", "results"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    content = payload.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if not isinstance(text, str) or not text.lstrip().startswith("{"):
                continue
            try:
                nested = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(nested, dict):
                return _extract_rows(nested)
    return []


def normalize_agentsview_payload(
    payload: Dict[str, Any],
    *,
    query: str,
    project: Optional[str] = None,
    limit: int = 10,
) -> SearchEnvelope:
    """Map an agentsview JSON object onto a :class:`SearchEnvelope`."""

    rows = _extract_rows(payload)
    grouped: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for rank, row in enumerate(rows, start=1):
        raw_sid = str(row.get("session_id") or row.get("sessionId") or row.get("id") or "").strip()
        if not raw_sid:
            continue
        agent = str(row.get("agent") or row.get("harness") or row.get("provider") or "").strip()
        session_id = raw_sid if (":" in raw_sid or not agent) else f"{agent}:{raw_sid}"
        harness = agent or (session_id.split(":", 1)[0] if ":" in session_id else "agentsview")
        bucket = grouped.get(session_id)
        if bucket is None:
            turn_count = row.get("turn_count")
            bucket = {
                "session_id": session_id,
                "harness": harness,
                "score": 0.0,
                "used_explicit_score": False,
                "snippet": "",
                "turns": [],
                "turn_count": turn_count if isinstance(turn_count, int) else None,
                "created_at": None,
            }
            grouped[session_id] = bucket
            order.append(session_id)
        explicit = row.get("score")
        if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
            bucket["score"] = max(float(bucket["score"]), float(explicit))
            bucket["used_explicit_score"] = True
        elif not bucket["used_explicit_score"]:
            bucket["score"] = float(bucket["score"]) + (1.0 / (RRF_K + rank))
        if not bucket["snippet"]:
            snippet = row.get("snippet") or row.get("highlight") or row.get("content") or ""
            bucket["snippet"] = _snippet(str(snippet))
        turns = _as_int_list(row.get("matched_turns"))
        turns.extend(_as_int_list(row.get("ordinal")))
        turns.extend(_as_int_list(row.get("match_ordinal")))
        turns.extend(_as_int_list(row.get("ordinal_range")))
        bucket["turns"].extend(turns)
        created = row.get("created_at") or row.get("timestamp") or row.get("started_at") or row.get("ended_at")
        if isinstance(created, str) and created:
            current = bucket["created_at"]
            if current is None or created < current:
                bucket["created_at"] = created
    order.sort(key=lambda sid: float(grouped[sid]["score"]), reverse=True)
    hits: List[SearchHit] = []
    for sid in order[: max(1, limit)]:
        bucket = grouped[sid]
        matched = list(dict.fromkeys(bucket["turns"]))
        hits.append(
            SearchHit(
                session_id=bucket["session_id"],
                harness=bucket["harness"],
                score=float(bucket["score"]),
                snippet=bucket["snippet"],
                matched_turns=matched,
                turn_count=bucket["turn_count"],
                created_at=bucket["created_at"],
            )
        )
    return SearchEnvelope(query=query, engine="agentsview", project=project, results=hits)


def _parse_json_document(stdout: str) -> Dict[str, Any]:
    start = stdout.find("{")
    if start < 0:
        raise AgentsViewError("agentsview did not return JSON")
    try:
        payload, _ = json.JSONDecoder().raw_decode(stdout[start:])
    except json.JSONDecodeError as exc:
        raise AgentsViewError("agentsview returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AgentsViewError("agentsview JSON root was not an object")
    return payload


class AgentsViewAdapter(BaseSearchEngine):
    """Search through a local agentsview installation."""

    name = "agentsview"

    def __init__(self, command: str = "agentsview", port: int = DEFAULT_PORT, timeout: float = 20.0) -> None:
        self.command = command
        self.port = port
        self.timeout = timeout

    def cli_installed(self) -> bool:
        return cli_installed(self.command)

    def service_listening(self) -> bool:
        return service_listening(port=self.port)

    def available(self) -> bool:
        if self.cli_installed():
            return True
        return self.service_listening()

    def search(
        self,
        query: str,
        project: Optional[str] = None,
        *,
        limit: int = 10,
    ) -> SearchEnvelope:
        if not self.available():
            raise AgentsViewUnavailable("agentsview CLI and service are not available")
        if not self.cli_installed():
            raise AgentsViewUnavailable(
                f"agentsview is listening on port {self.port} but the CLI is not installed"
            )
        try:
            return self.search_cli(query, project=project, limit=limit)
        except AgentsViewError:
            return self.search_mcp(query, project=project, limit=limit)

    def search_cli(
        self,
        query: str,
        project: Optional[str] = None,
        *,
        limit: int = 10,
    ) -> SearchEnvelope:
        """Run ``agentsview session search`` and normalize ``--json`` output."""

        match_limit = max(limit, min(limit * 5, 50))
        command: List[str] = [
            self.command,
            "session",
            "search",
            query,
            "--json",
            "--limit",
            str(match_limit),
        ]
        if project:
            command.extend(["--project", project])
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AgentsViewError(str(exc)) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise AgentsViewError(detail or f"agentsview exited {completed.returncode}")
        payload = _parse_json_document(completed.stdout)
        return normalize_agentsview_payload(payload, query=query, project=project, limit=limit)

    def search_mcp(
        self,
        query: str,
        project: Optional[str] = None,
        *,
        limit: int = 10,
    ) -> SearchEnvelope:
        """Call agentsview's MCP search tool over stdio."""

        try:
            proc = subprocess.Popen(
                [self.command, "mcp"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise AgentsViewError(str(exc)) from exc
        try:
            self._mcp_send(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "agent-handoff", "version": "0.2.0"},
                    },
                },
            )
            init = self._mcp_read_id(proc, 1)
            if "error" in init:
                raise AgentsViewError(f"mcp initialize failed: {init['error']}")
            self._mcp_send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            arguments: Dict[str, Any] = {"query": query, "limit": limit, "include_active": True}
            if project:
                arguments["project"] = project
            last_error = "mcp search failed"
            for offset, tool_name in enumerate(_MCP_TOOLS):
                call_id = 2 + offset
                self._mcp_send(
                    proc,
                    {
                        "jsonrpc": "2.0",
                        "id": call_id,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    },
                )
                message = self._mcp_read_id(proc, call_id)
                if "error" in message and _unknown_tool(message["error"]) and tool_name != _MCP_TOOLS[-1]:
                    last_error = str(message["error"])
                    continue
                if "error" in message:
                    raise AgentsViewError(str(message["error"]))
                result = message.get("result")
                if not isinstance(result, dict):
                    raise AgentsViewError("mcp search returned an empty result")
                payload = result.get("structuredContent")
                if not isinstance(payload, dict):
                    payload = result
                return normalize_agentsview_payload(payload, query=query, project=project, limit=limit)
            raise AgentsViewError(last_error)
        finally:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

    def _mcp_send(self, proc: subprocess.Popen, message: Dict[str, Any]) -> None:
        if proc.stdin is None:
            raise AgentsViewError("mcp stdin is closed")
        data = json.dumps(message).encode("utf-8") + b"\n"
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AgentsViewError("mcp stdin closed") from exc

    def _mcp_read_id(self, proc: subprocess.Popen, expected: int) -> Dict[str, Any]:
        if proc.stdout is None:
            raise AgentsViewError("mcp stdout is closed")
        fd = proc.stdout.fileno()
        os.set_blocking(fd, False)
        buf = b""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise AgentsViewError("mcp returned invalid JSON") from exc
                if message.get("id") == expected:
                    return message
                continue
            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if not ready:
                if proc.poll() is not None:
                    raise AgentsViewError("agentsview mcp exited")
                continue
            try:
                chunk = proc.stdout.read(65536)
            except BlockingIOError:
                continue
            if not chunk:
                if proc.poll() is not None:
                    raise AgentsViewError("agentsview mcp closed the pipe")
                continue
            buf += chunk
        raise AgentsViewError("agentsview mcp timed out")


def _unknown_tool(error: object) -> bool:
    text = json.dumps(error, ensure_ascii=False) if not isinstance(error, str) else error
    lowered = text.lower()
    return "unknown tool" in lowered or "not found" in lowered or "invalid tool" in lowered
