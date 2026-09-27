"""Session-search: FTS5 trigram, agentsview normalization, and RRF."""

from __future__ import annotations

import json
import resource
import socket
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from agent_handoff.cli import distill_main, handoff_main, main, search_main, session_main
from agent_handoff.search import agentsview as agentsview_mod
from agent_handoff.search.agentsview import AgentsViewAdapter, normalize_agentsview_payload
from agent_handoff.search.base import RRF_K, SEARCH_PROTOCOL
from agent_handoff.search.embedded import (
    EmbeddedSearchEngine,
    fuse_ranks,
    reciprocal_rank_fusion,
    reduce_record,
    sqlite_vec_usable,
)
from agent_handoff.search.router import search_sessions


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_trigram_indexes_chinese_and_code_symbols(tmp_path: Path) -> None:
    transcript = tmp_path / "logs" / "transcript.jsonl"
    _write_jsonl(
        transcript,
        [
            {
                "step_index": 4,
                "source": "USER",
                "type": "USER_INPUT",
                "created_at": "2026-09-24T18:30:00Z",
                "content": "请定位 BaseSessionAdapter 的实现，并说明异构 A2A 架构设计。",
            },
            {
                "step_index": 5,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-09-24T18:31:00Z",
                "content": "BaseSessionAdapter 是适配器基类，异构 A2A 架构设计留在 Mailbox。",
            },
            {
                "type": "tool_use",
                "content": "this tool frame mentions BaseSessionAdapter but must be dropped",
            },
        ],
    )
    engine = EmbeddedSearchEngine(db_path=tmp_path / ".handoff_index.db")
    indexed = engine.index_path(transcript, project="Arborist-Orca")
    assert indexed[0].skipped is False
    assert indexed[0].turns == 2

    symbol = engine.search("BaseSessionAdapter", project="Arborist-Orca")
    assert symbol.engine == "embedded_fts5"
    assert symbol.protocol == SEARCH_PROTOCOL
    assert symbol.total_hits == 1
    assert symbol.results[0].matched_turns == [5, 4] or 4 in symbol.results[0].matched_turns
    assert 4 in symbol.results[0].matched_turns
    assert 5 in symbol.results[0].matched_turns
    assert "<b>" in symbol.results[0].snippet
    assert symbol.results[0].turn_count == 2
    assert symbol.results[0].created_at == "2026-09-24T18:30:00Z"

    chinese = engine.search("架构设计", project="Arborist-Orca")
    assert chinese.total_hits == 1
    assert chinese.results[0].session_id == symbol.results[0].session_id

    other_project = engine.search("BaseSessionAdapter", project="missing-project")
    assert other_project.total_hits == 0

    again = engine.index_path(transcript, project="Arborist-Orca")
    assert again[0].skipped is True
    assert again[0].turns == 2


def test_physical_denoise_strips_base64_and_tool_dumps() -> None:
    dumped = reduce_record(
        {
            "type": "GENERIC",
            "content": "tool stdout " + ("x" * 2500),
        }
    )
    assert dumped is None
    noisy = "VISIBLE BaseSessionAdapter " + ("Q" * 300)
    cleaned = reduce_record({"role": "assistant", "content": noisy})
    assert cleaned is not None
    assert "BaseSessionAdapter" in cleaned
    assert "QQQ" not in cleaned


def test_incremental_reindex_replaces_stale_terms(tmp_path: Path) -> None:
    transcript = tmp_path / "session-a" / "transcript.jsonl"
    _write_jsonl(
        transcript,
        [{"step_index": 1, "role": "user", "content": "first term BaseSessionAdapter"}],
    )
    engine = EmbeddedSearchEngine(db_path=tmp_path / "index.db")
    engine.index_path(transcript)
    time.sleep(0.01)
    _write_jsonl(
        transcript,
        [{"step_index": 2, "role": "assistant", "content": "replaced by AnotherSymbolXX"}],
    )
    refreshed = engine.index_path(transcript)
    assert refreshed[0].skipped is False
    assert engine.search("BaseSessionAdapter").total_hits == 0
    found = engine.search("AnotherSymbolXX")
    assert found.total_hits == 1
    assert found.results[0].matched_turns == [2]


def test_rrf_math_matches_sql() -> None:
    fts_ranks = {1: 1, 2: 2}
    vec_ranks = {2: 1, 3: 1}
    fused = reciprocal_rank_fusion(fts_ranks, vec_ranks)
    scores = dict(fused)
    assert scores[1] == pytest.approx(1.0 / (RRF_K + 1))
    assert scores[2] == pytest.approx(1.0 / (RRF_K + 2) + 1.0 / (RRF_K + 1))
    assert scores[3] == pytest.approx(1.0 / (RRF_K + 1))
    assert fused[0][0] == 2

    conn = sqlite3.connect(":memory:")
    try:
        sql_rows = fuse_ranks(
            conn,
            [(rowid, rank) for rowid, rank in fts_ranks.items()],
            [(rowid, rank) for rowid, rank in vec_ranks.items()],
            limit=10,
        )
    finally:
        conn.close()
    assert [rowid for rowid, _score in sql_rows] == [rowid for rowid, _score in fused]
    for (rowid, score), (_other, expected) in zip(sql_rows, fused):
        assert score == pytest.approx(expected)


def test_vector_source_without_sqlite_vec_stays_on_fts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_handoff.search.embedded.sqlite_vec_usable", lambda conn: False)
    transcript = tmp_path / "logs" / "transcript.jsonl"
    _write_jsonl(transcript, [{"role": "user", "content": "semantic fallback BaseSessionAdapter"}])

    class _HashVector:
        dimension = 8

        def embed(self, text: str) -> list[float]:
            return [float(len(text) % 7)] * self.dimension

    engine = EmbeddedSearchEngine(db_path=tmp_path / "index.db", vector_source=_HashVector())
    engine.index_path(transcript)
    envelope = engine.search("BaseSessionAdapter")
    assert envelope.engine == "embedded_fts5"
    assert envelope.total_hits == 1
    assert sqlite_vec_usable.__name__ == "sqlite_vec_usable"


def test_agentsview_payload_groups_matches() -> None:
    payload = {
        "matches": [
            {
                "session_id": "grok:abc",
                "agent": "grok",
                "project": "agent-handoff",
                "ordinal": 4,
                "ordinal_range": [4, 5],
                "timestamp": "2026-09-24T18:31:00Z",
                "snippet": "uses BaseSessionAdapter",
            },
            {
                "session_id": "abc",
                "agent": "claude",
                "match_ordinal": 9,
                "ended_at": "2026-09-24T18:00:00Z",
                "snippet": "earlier <mark>hit</mark>",
            },
            {
                "session_id": "grok:abc",
                "agent": "grok",
                "ordinal": 8,
                "timestamp": "2026-09-24T18:40:00Z",
                "snippet": "second hit should not replace the first snippet",
            },
        ]
    }
    envelope = normalize_agentsview_payload(payload, query="BaseSessionAdapter", project="agent-handoff", limit=10)
    assert envelope.engine == "agentsview"
    assert envelope.project == "agent-handoff"
    by_id = {hit.session_id: hit for hit in envelope.results}
    assert set(by_id) == {"grok:abc", "claude:abc"}
    grok = by_id["grok:abc"]
    assert grok.harness == "grok"
    assert grok.matched_turns == [4, 5, 8]
    assert grok.snippet == "uses BaseSessionAdapter"
    assert grok.created_at == "2026-09-24T18:31:00Z"
    assert grok.score == pytest.approx(1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 3))
    assert "<b>hit</b>" in by_id["claude:abc"].snippet
    assert by_id["claude:abc"].matched_turns == [9]


def test_agentsview_cli_shape_and_mcp_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "agentsview":
            seen["cmd"] = list(cmd)

            class _Completed:
                returncode = 0
                stdout = json.dumps(
                    {
                        "matches": [
                            {
                                "session_id": "grok:cli",
                                "agent": "grok",
                                "ordinal": 1,
                                "snippet": "from cli",
                                "timestamp": "2026-09-26T00:00:00Z",
                            }
                        ]
                    }
                )
                stderr = ""

            return _Completed()
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(agentsview_mod.subprocess, "run", fake_run)
    adapter = AgentsViewAdapter(command="agentsview")
    monkeypatch.setattr(adapter, "cli_installed", lambda: True)
    monkeypatch.setattr(adapter, "service_listening", lambda: False)
    envelope = adapter.search("异构 A2A", project="Arborist-Orca", limit=4)
    assert seen["cmd"][:4] == ["agentsview", "session", "search", "异构 A2A"]
    assert "--json" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--project") + 1] == "Arborist-Orca"
    assert envelope.results[0].session_id == "grok:cli"

    script = tmp_path / "agentsview"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import sys

            if sys.argv[1:3] == ["session", "search"]:
                sys.stderr.write("cli down\\n")
                sys.exit(2)
            if len(sys.argv) > 1 and sys.argv[1] == "mcp":
                for line in sys.stdin:
                    msg = json.loads(line)
                    if msg.get("method") == "initialize":
                        sys.stdout.write(json.dumps({
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "agentsview", "version": "v0"}},
                        }) + "\\n")
                        sys.stdout.flush()
                    elif msg.get("method") == "tools/call":
                        payload = {"results": [{
                            "session_id": "abc",
                            "agent": "grok",
                            "snippet": "mcp <mark>BaseSessionAdapter</mark>",
                            "match_ordinal": 7,
                            "ended_at": "2026-09-24T18:30:00Z",
                        }]}
                        sys.stdout.write(json.dumps({
                            "jsonrpc": "2.0",
                            "id": msg["id"],
                            "result": {"structuredContent": payload},
                        }) + "\\n")
                        sys.stdout.flush()
                        break
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    mcp_adapter = AgentsViewAdapter(command=str(script), timeout=5)
    fallback = mcp_adapter.search("BaseSessionAdapter", project=None)
    assert fallback.engine == "agentsview"
    assert fallback.results[0].session_id == "grok:abc"
    assert fallback.results[0].matched_turns == [7]
    assert "<b>BaseSessionAdapter</b>" in fallback.results[0].snippet


def test_service_probe_uses_tcp() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    open_port = server.getsockname()[1]
    closed = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        assert AgentsViewAdapter(port=open_port).service_listening() is True
        assert AgentsViewAdapter(port=closed_port).service_listening() is False
    finally:
        server.close()


def test_router_prefers_tier1_and_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = tmp_path / "logs" / "transcript.jsonl"
    _write_jsonl(transcript, [{"step_index": 3, "role": "assistant", "content": "embedded only BaseSessionAdapter"}])
    db_path = tmp_path / "index.db"

    class _Tier1:
        def available(self) -> bool:
            return True

        def search(self, query: str, project=None, *, limit: int = 10):
            from agent_handoff.search.base import SearchEnvelope, SearchHit

            return SearchEnvelope(
                query=query,
                engine="agentsview",
                project=project,
                results=[
                    SearchHit(
                        session_id="grok:tier1",
                        harness="grok",
                        score=1.0,
                        snippet="tier1",
                        matched_turns=[1],
                    )
                ],
            )

    monkeypatch.setattr("agent_handoff.search.router.AgentsViewAdapter", lambda: _Tier1())
    preferred = search_sessions("BaseSessionAdapter", project="demo", db_path=db_path, paths=[transcript])
    assert preferred.engine == "agentsview"
    assert preferred.results[0].session_id == "grok:tier1"
    assert not db_path.exists()

    class _Down:
        def available(self) -> bool:
            return True

        def search(self, query: str, project=None, *, limit: int = 10):
            raise RuntimeError("agentsview down")

    monkeypatch.setattr("agent_handoff.search.router.AgentsViewAdapter", lambda: _Down())
    fallback = search_sessions(
        "BaseSessionAdapter",
        paths=[transcript],
        db_path=db_path,
        discover=False,
    )
    assert fallback.engine == "embedded_fts5"
    assert fallback.results[0].matched_turns == [3]

    class _Missing:
        def available(self) -> bool:
            return False

        def search(self, *args, **kwargs):
            raise AssertionError("unavailable engine must not be called")

    monkeypatch.setattr("agent_handoff.search.router.AgentsViewAdapter", lambda: _Missing())
    with pytest.raises(Exception):
        search_sessions("BaseSessionAdapter", engine="agentsview", db_path=db_path)


def test_cli_json_human_and_session_search(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    transcript = tmp_path / "logs" / "transcript.jsonl"
    _write_jsonl(
        transcript,
        [{"step_index": 6, "role": "user", "content": "查找 BaseSessionAdapter 与架构设计"}],
    )
    db_path = tmp_path / "index.db"
    code = main(
        [
            "search",
            "BaseSessionAdapter",
            "--engine",
            "embedded",
            "--path",
            str(transcript),
            "--db",
            str(db_path),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["protocol"] == SEARCH_PROTOCOL
    assert payload["engine"] == "embedded_fts5"
    assert payload["total_hits"] == 1
    assert payload["results"][0]["matched_turns"] == [6]

    code = main(
        [
            "search",
            "架构设计",
            "--engine",
            "embedded",
            "--path",
            str(transcript),
            "--db",
            str(db_path),
        ]
    )
    assert code == 0
    human = capsys.readouterr().out
    assert "embedded_fts5" in human
    assert "架构设计" in human

    code = search_main(
        [
            "BaseSessionAdapter",
            "--engine",
            "embedded",
            "--path",
            str(transcript),
            "--db",
            str(db_path),
            "--json",
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["session_id"]

    assert main(["search", "ab", "--engine", "embedded", "--db", str(db_path)]) == 2
    capsys.readouterr()
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert "0.2.0" in capsys.readouterr().out


def test_session_commands_match_the_three_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    code = session_main(["handoff", "--summary", "PG stays, ES stays discarded", "--decision", "use PG"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["protocol"] == "A2A-Handoff-v1"
    assert payload["summary"] == "PG stays, ES stays discarded"
    assert payload["decisions"][0]["description"] == "use PG"

    code = handoff_main(["--summary", "PG stays, ES stays discarded", "--decision", "use PG"])
    assert code == 0
    direct = json.loads(capsys.readouterr().out)
    assert direct["protocol"] == payload["protocol"]
    assert direct["summary"] == payload["summary"]
    assert direct["decisions"] == payload["decisions"]

    assert session_main(["distill", "--inspect"]) == 2

    assert distill_main(["search", "ab"]) == 2
    capsys.readouterr()


def test_point_query_is_fast_on_ten_thousand_rows(tmp_path: Path) -> None:
    transcript = tmp_path / "bulk" / "transcript.jsonl"
    transcript.parent.mkdir()
    with transcript.open("w", encoding="utf-8") as handle:
        for index in range(10_000):
            content = f"ordinary turn {index} with filler text"
            if index == 7777:
                content = "unique symbol BaseSessionAdapter appears once"
            handle.write(json.dumps({"step_index": index, "role": "assistant", "content": content}) + "\n")
    engine = EmbeddedSearchEngine(db_path=tmp_path / "index.db")
    engine.index_path(transcript)
    started = time.perf_counter()
    envelope = engine.search("BaseSessionAdapter")
    elapsed = time.perf_counter() - started
    assert envelope.total_hits == 1
    assert envelope.results[0].matched_turns == [7777]
    assert elapsed < 0.05


def test_search_process_exits_without_a_daemon(tmp_path: Path) -> None:
    transcript = tmp_path / "logs" / "transcript.jsonl"
    _write_jsonl(transcript, [{"role": "user", "content": "cold BaseSessionAdapter"}])
    db_path = tmp_path / ".handoff_index.db"
    script = tmp_path / "run_search.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            import resource
            import sqlite3
            import threading
            import time
            from pathlib import Path

            started = time.perf_counter()
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(content, tokenize='trigram')")
            conn.execute("INSERT INTO t(content) VALUES ('BaseSessionAdapter')")
            conn.execute("SELECT rowid FROM t WHERE t MATCH ?", ('"BaseSessionAdapter"',)).fetchone()
            conn.close()
            cold_ms = (time.perf_counter() - started) * 1000

            from agent_handoff.search.embedded import EmbeddedSearchEngine
            engine = EmbeddedSearchEngine(db_path=Path({str(db_path)!r}))
            engine.index_path(Path({str(transcript)!r}))
            found = engine.search("BaseSessionAdapter")
            assert found.results, "expected a hit"
            print(f"cold_ms {{cold_ms:.2f}}")
            print("threads", len(threading.enumerate()))
            print("rss_kb", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            """
        ),
        encoding="utf-8",
    )
    before = {thread.ident for thread in threading.enumerate()}
    completed = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    fields = {}
    for line in completed.stdout.splitlines():
        key, value = line.split(maxsplit=1)
        fields[key] = value
    assert int(fields["threads"]) == 1
    assert int(fields["rss_kb"]) < 150_000
    assert float(fields["cold_ms"]) < 10
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("ROLLBACK")
    finally:
        conn.close()
    assert {thread.ident for thread in threading.enumerate()} == before
    started = time.perf_counter()
    help_run = subprocess.run(
        [sys.executable, "-m", "agent_handoff.cli", "search", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert help_run.returncode == 0
    assert "query" in help_run.stdout
    # Interpreter startup is most of this wall time; the engine cold start is cold_ms.
    assert time.perf_counter() - started < 0.2
