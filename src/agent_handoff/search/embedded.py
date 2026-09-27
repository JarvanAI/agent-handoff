"""Tier 2 zero-daemon search: SQLite FTS5 trigram, optional sqlite-vec RRF.

L0 uses only the Python standard library. L1 runs when ``sqlite-vec`` imports
and the caller configured a vector source. Otherwise search stays on BM25.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from agent_handoff.search.base import RRF_K, BaseSearchEngine, SearchEnvelope, SearchHit

_MAX_INDEX_CHARS = 8000
_MAX_FILE_BYTES = 64 * 1024 * 1024
_SKIP_TYPES = {
    "queue-operation",
    "checkpoint",
    "mode",
    "permission-mode",
    "ide_state",
    "tool_use",
    "tool_result",
    "tool_call",
    "heartbeat",
    "ping",
}
_TOOL_DUMP_TYPES = {"generic", "tool", "tool_result", "tool_output"}
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_BASE64_RE = re.compile(
    r"(?:data:[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]{40,})"
    r"|(?:(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{240,}={0,2}(?![A-Za-z0-9+/]))"
)
_SKIP_DIRS = {
    ".git",
    ".hg",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
}

RRF_SQL = """
WITH fts_matches AS (
    SELECT rowid, fts_rank FROM rrf_fts_stage
),
vec_matches AS (
    SELECT rowid, vec_rank FROM rrf_vec_stage
)
SELECT
    COALESCE(f.rowid, v.rowid) AS rowid,
    (
        COALESCE(1.0 / (? + f.fts_rank), 0.0) * ? +
        COALESCE(1.0 / (? + v.vec_rank), 0.0) * ?
    ) AS rrf_score
FROM fts_matches f
FULL OUTER JOIN vec_matches v ON f.rowid = v.rowid
ORDER BY rrf_score DESC, rowid ASC
LIMIT ?
"""


@dataclass
class IndexResult:
    """Outcome of indexing one transcript file."""

    path: str
    session_id: str
    turns: int
    skipped: bool


@dataclass
class _TurnHit:
    session_id: str
    harness: str
    turn_id: int
    turn_count: Optional[int]
    created_at: Optional[str]
    snippet: str


def trigram_available() -> bool:
    """Return True when this Python's SQLite can create an FTS5 trigram table."""

    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE t USING fts5(content, tokenize = 'trigram')")
        finally:
            conn.close()
        return True
    except sqlite3.DatabaseError:
        return False


def sqlite_vec_usable(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec into ``conn`` when the optional package is installed."""

    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except (sqlite3.Error, AttributeError, OSError):
        return False


def fts_match_query(query: str) -> str:
    """Quote a user query so FTS5 treats it as one trigram phrase."""

    text = query.strip()
    if len(text) < 3:
        raise ValueError("query must be at least 3 characters")
    return '"' + text.replace('"', '""') + '"'


def reciprocal_rank_fusion(
    fts_ranks: Dict[int, int],
    vec_ranks: Dict[int, int],
    *,
    k: int = RRF_K,
    weight_fts: float = 1.0,
    weight_vec: float = 1.0,
) -> List[Tuple[int, float]]:
    """Fuse 1-based ranks with Reciprocal Rank Fusion.

    ``score(id) = weight_fts / (k + fts_rank) + weight_vec / (k + vec_rank)``.
    A missing list contributes 0. Higher scores rank first.
    """

    scores: List[Tuple[int, float]] = []
    for rowid in set(fts_ranks) | set(vec_ranks):
        score = 0.0
        if rowid in fts_ranks:
            score += weight_fts / (k + fts_ranks[rowid])
        if rowid in vec_ranks:
            score += weight_vec / (k + vec_ranks[rowid])
        scores.append((rowid, score))
    scores.sort(key=lambda item: (-item[1], item[0]))
    return scores


def fuse_ranks(
    conn: sqlite3.Connection,
    fts_rows: Sequence[Tuple[int, int]],
    vec_rows: Sequence[Tuple[int, int]],
    *,
    limit: int = 50,
    k: int = RRF_K,
    weight_fts: float = 1.0,
    weight_vec: float = 1.0,
) -> List[Tuple[int, float]]:
    """Run the RRF CTE. Falls back to :func:`reciprocal_rank_fusion` if needed."""

    conn.execute("DROP TABLE IF EXISTS rrf_fts_stage")
    conn.execute("DROP TABLE IF EXISTS rrf_vec_stage")
    conn.execute("CREATE TEMP TABLE rrf_fts_stage(rowid INTEGER PRIMARY KEY, fts_rank INTEGER)")
    conn.execute("CREATE TEMP TABLE rrf_vec_stage(rowid INTEGER PRIMARY KEY, vec_rank INTEGER)")
    conn.executemany("INSERT INTO rrf_fts_stage(rowid, fts_rank) VALUES (?, ?)", list(fts_rows))
    conn.executemany("INSERT INTO rrf_vec_stage(rowid, vec_rank) VALUES (?, ?)", list(vec_rows))
    try:
        rows = conn.execute(RRF_SQL, (k, weight_fts, k, weight_vec, limit)).fetchall()
    except sqlite3.OperationalError:
        fused = reciprocal_rank_fusion(
            {rowid: rank for rowid, rank in fts_rows},
            {rowid: rank for rowid, rank in vec_rows},
            k=k,
            weight_fts=weight_fts,
            weight_vec=weight_vec,
        )
        return fused[:limit]
    return [(int(row[0]), float(row[1])) for row in rows]


def discover_transcripts(
    roots: Sequence[Path],
    *,
    max_files: int = 100,
    max_depth: int = 4,
) -> List[Path]:
    """Find JSONL transcripts under ``roots`` without walking dependency directories."""

    found: List[Path] = []
    for root in roots:
        root = Path(root).expanduser()
        if root.is_file() and root.suffix == ".jsonl":
            found.append(root)
            if len(found) >= max_files:
                return found
            continue
        if not root.is_dir():
            continue
        base = root.resolve()
        for dirpath, dirnames, filenames in os.walk(base):
            current = Path(dirpath)
            depth = len(current.relative_to(base).parts)
            if depth >= max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [
                    name
                    for name in dirnames
                    if name not in _SKIP_DIRS and not name.startswith(".")
                ]
            for name in sorted(filenames):
                if name.endswith(".jsonl"):
                    found.append(current / name)
                    if len(found) >= max_files:
                        return found
    return found


def infer_harness(path: Path) -> str:
    """Guess the agent harness from a transcript path."""

    text = str(path).lower()
    if "antigravity" in text or "gemini" in text:
        return "antigravity-cli"
    if "claude" in text:
        return "claude-code"
    if "codex" in text:
        return "codex"
    if "cursor" in text:
        return "cursor"
    if "grok" in text:
        return "grok"
    if path.name.lower().startswith("transcript"):
        return "transcript"
    return "jsonl"


def infer_identity(path: Path, harness: Optional[str] = None) -> Tuple[str, str]:
    """Return ``(session_id, harness)`` for a transcript file.

    UUID-like parent directories keep the ``harness:id`` form used by agentsview.
    Any other file includes its parent and stem so two transcripts cannot overwrite
    each other.
    """

    harness_name = harness or infer_harness(path)
    parent = path.parent.name
    parent_is_id = len(parent) >= 8 and any(ch.isdigit() for ch in parent)
    if parent_is_id and path.stem.lower() in {"transcript", "transcript_full"}:
        session_id = f"{harness_name}:{parent}"
    elif parent_is_id:
        session_id = f"{harness_name}:{parent}:{path.stem}"
    else:
        session_id = f"{harness_name}:{parent}:{path.stem}"
    return session_id, harness_name


def reduce_record(record: Dict[str, Any]) -> Optional[str]:
    """Physically denoise one transcript record.

    Tool-call frames, heartbeats, base64 blobs, and oversized tool dumps are
    dropped. Dialogue text is kept and capped.
    """

    kind = str(record.get("type") or "").strip().lower()
    if kind in _SKIP_TYPES:
        return None
    text = _extract_text(record)
    if not text:
        return None
    if kind in _TOOL_DUMP_TYPES and len(text) > 2000:
        return None
    text = _denoise_text(text)
    if not text:
        return None
    if len(text) > _MAX_INDEX_CHARS:
        text = text[:_MAX_INDEX_CHARS]
    return text


def iter_records(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield JSON objects from a JSONL file or a small JSON document."""

    produced = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        first = ""
        while True:
            char = handle.read(1)
            if not char:
                break
            if not char.isspace():
                first = char
                break
        handle.seek(0)
        if first == "[":
            try:
                data = json.load(handle)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        produced += 1
                        yield item
            return
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                produced += 1
                yield item
            elif isinstance(item, list):
                for sub in item:
                    if isinstance(sub, dict):
                        produced += 1
                        yield sub
    if produced == 0 and path.stat().st_size <= 8_000_000:
        yield from _iter_json_document(path)


class EmbeddedSearchEngine(BaseSearchEngine):
    """File-backed FTS5 engine. The connection is closed before each call returns."""

    name = "embedded"

    def __init__(
        self,
        db_path: Optional[os.PathLike[str] | str] = None,
        *,
        vector_source: Any = None,
        max_file_bytes: int = _MAX_FILE_BYTES,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path.cwd() / ".handoff_index.db"
        self.vector_source = vector_source
        self.max_file_bytes = max_file_bytes

    def available(self) -> bool:
        return trigram_available()

    def prepare(self) -> None:
        """Create the index schema if it does not exist yet."""

        with self._connect() as conn:
            self._ensure_schema(conn)

    def index_path(
        self,
        path: os.PathLike[str] | str,
        *,
        project: Optional[str] = None,
        harness: Optional[str] = None,
    ) -> List[IndexResult]:
        """Index a JSONL file or every transcript under a directory."""

        target = Path(path).expanduser()
        if target.is_dir():
            results: List[IndexResult] = []
            for found in discover_transcripts([target]):
                results.extend(self.index_path(found, project=project, harness=harness))
            return results
        if not target.is_file():
            raise FileNotFoundError(target)
        if target.stat().st_size > self.max_file_bytes:
            return [IndexResult(str(target), "", 0, True)]
        if not self.available():
            raise RuntimeError("SQLite FTS5 trigram is not available in this Python build")

        resolved = str(target.resolve())
        fingerprint = f"{target.stat().st_size}:{target.stat().st_mtime_ns}"
        session_id, harness_name = infer_identity(target, harness)
        with self._connect() as conn:
            self._ensure_schema(conn)
            existing = conn.execute(
                "SELECT fingerprint, session_id, project FROM index_sources WHERE path = ?",
                (resolved,),
            ).fetchone()
            stored_project = project if project is not None else (existing["project"] if existing else None)
            if (
                existing
                and existing["fingerprint"] == fingerprint
                and (project is None or existing["project"] == project)
            ):
                row = conn.execute(
                    "SELECT turn_count FROM sessions WHERE session_id = ?",
                    (existing["session_id"],),
                ).fetchone()
                turns = int(row["turn_count"]) if row else 0
                return [IndexResult(resolved, existing["session_id"], turns, True)]

            if existing:
                self._delete_session(conn, existing["session_id"])
            if not existing or existing["session_id"] != session_id:
                self._delete_session(conn, session_id)

            use_vec = self._prepare_vec(conn)
            created_at: Optional[str] = None
            written = 0
            for index, record in enumerate(iter_records(target)):
                text = reduce_record(record)
                if not text:
                    continue
                turn_id = _turn_id(record, index)
                timestamp = _timestamp(record)
                if timestamp and (created_at is None or timestamp < created_at):
                    created_at = timestamp
                cursor = conn.execute(
                    """
                    INSERT INTO conversation_turns(session_id, turn_id, role, timestamp, content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, turn_id, _role_of(record), timestamp, text),
                )
                written += 1
                if use_vec and cursor.lastrowid is not None:
                    vector = self._embed(text)
                    if vector is not None:
                        conn.execute(
                            "INSERT INTO turns_vec(rowid, embedding) VALUES (?, ?)",
                            (int(cursor.lastrowid), vector),
                        )
            conn.execute(
                """
                INSERT INTO sessions(session_id, harness, project, source_path, turn_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    harness = excluded.harness,
                    project = excluded.project,
                    source_path = excluded.source_path,
                    turn_count = excluded.turn_count,
                    created_at = excluded.created_at
                """,
                (session_id, harness_name, stored_project, resolved, written, created_at),
            )
            conn.execute(
                """
                INSERT INTO index_sources(path, fingerprint, session_id, project)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    session_id = excluded.session_id,
                    project = excluded.project
                """,
                (resolved, fingerprint, session_id, stored_project),
            )
        return [IndexResult(resolved, session_id, written, False)]

    def index_tree(
        self,
        roots: Sequence[os.PathLike[str] | str],
        *,
        project: Optional[str] = None,
    ) -> List[IndexResult]:
        results: List[IndexResult] = []
        for root in roots:
            results.extend(self.index_path(root, project=project))
        return results

    def refresh(self) -> None:
        """Reindex changed sources and drop entries whose files disappeared."""

        if not Path(self.db_path).exists():
            return
        with self._connect() as conn:
            self._ensure_schema(conn)
            rows = list(conn.execute("SELECT path, session_id, project FROM index_sources"))
        for row in rows:
            file_path = Path(row["path"])
            if not file_path.is_file():
                with self._connect() as conn:
                    self._ensure_schema(conn)
                    self._delete_session(conn, row["session_id"])
                    conn.execute("DELETE FROM index_sources WHERE path = ?", (row["path"],))
                    conn.execute("DELETE FROM sessions WHERE session_id = ?", (row["session_id"],))
                continue
            self.index_path(file_path, project=row["project"])

    def search(
        self,
        query: str,
        project: Optional[str] = None,
        *,
        limit: int = 10,
    ) -> SearchEnvelope:
        text = query.strip()
        if len(text) < 3:
            raise ValueError("query must be at least 3 characters")
        limit = max(1, min(int(limit), 100))
        self.refresh()
        with self._connect() as conn:
            self._ensure_schema(conn)
            if self._hybrid_ready(conn):
                hits = self._search_hybrid(conn, text, project, limit)
                engine = "embedded_hybrid"
            else:
                hits = self._search_fts(conn, text, project, limit)
                engine = "embedded_fts5"
        return SearchEnvelope(query=text, engine=engine, project=project, results=hits)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                harness TEXT NOT NULL,
                project TEXT,
                source_path TEXT,
                turn_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                timestamp TEXT,
                content TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
                content,
                content='conversation_turns',
                content_rowid='id',
                tokenize = 'trigram'
            );

            CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON conversation_turns BEGIN
                INSERT INTO turns_fts(rowid, content) VALUES (new.id, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON conversation_turns BEGIN
                INSERT INTO turns_fts(turns_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END;

            CREATE TABLE IF NOT EXISTS index_sources (
                path TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                session_id TEXT NOT NULL,
                project TEXT
            );

            CREATE TABLE IF NOT EXISTS index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

    def _delete_session(self, conn: sqlite3.Connection, session_id: str) -> None:
        if _table_exists(conn, "turns_vec"):
            conn.execute(
                """
                DELETE FROM turns_vec
                WHERE rowid IN (SELECT id FROM conversation_turns WHERE session_id = ?)
                """,
                (session_id,),
            )
        conn.execute("DELETE FROM conversation_turns WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    def _dimension(self) -> Optional[int]:
        source = self.vector_source
        if source is None:
            return None
        declared = getattr(source, "dimension", None)
        if isinstance(declared, int) and declared > 0:
            return declared
        sample = self._embed_values("dimension probe")
        if not sample:
            return None
        return len(sample)

    def _prepare_vec(self, conn: sqlite3.Connection) -> bool:
        if self.vector_source is None or not sqlite_vec_usable(conn):
            return False
        dimension = self._dimension()
        if not dimension:
            return False
        current = conn.execute(
            "SELECT value FROM index_meta WHERE key = 'vec_dimension'"
        ).fetchone()
        if current is not None and int(current["value"]) != dimension and _table_exists(conn, "turns_vec"):
            conn.execute("DROP TABLE turns_vec")
        if not _table_exists(conn, "turns_vec"):
            conn.execute(
                f"CREATE VIRTUAL TABLE turns_vec USING vec0("
                f"embedding float[{int(dimension)}] distance_metric=cosine)"
            )
        conn.execute(
            """
            INSERT INTO index_meta(key, value) VALUES ('vec_dimension', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(int(dimension)),),
        )
        return True

    def _hybrid_ready(self, conn: sqlite3.Connection) -> bool:
        if self.vector_source is None or not _table_exists(conn, "turns_vec"):
            return False
        if not sqlite_vec_usable(conn):
            return False
        row = conn.execute("SELECT 1 FROM turns_vec LIMIT 1").fetchone()
        return row is not None

    def _embed(self, text: str) -> Optional[bytes]:
        values = self._embed_values(text)
        dimension = self._dimension()
        if not values or dimension is None or len(values) != dimension:
            return None
        return _serialize_f32(values)

    def _embed_query(self, text: str) -> Optional[bytes]:
        source = self.vector_source
        if source is None:
            return None
        embed_query = getattr(source, "embed_query", None)
        if callable(embed_query):
            values = [float(item) for item in embed_query(text)]
        else:
            values = self._embed_values(text)
        dimension = self._dimension()
        if not values or dimension is None or len(values) != dimension:
            return None
        return _serialize_f32(values)

    def _embed_values(self, text: str) -> Optional[List[float]]:
        source = self.vector_source
        if source is None:
            return None
        embed = getattr(source, "embed", None)
        if not callable(embed):
            return None
        return [float(item) for item in embed(text)]

    def _search_fts(
        self,
        conn: sqlite3.Connection,
        query: str,
        project: Optional[str],
        limit: int,
    ) -> List[SearchHit]:
        rows = conn.execute(
            """
            SELECT
                t.session_id AS session_id,
                t.turn_id AS turn_id,
                s.harness AS harness,
                s.turn_count AS turn_count,
                s.created_at AS created_at,
                snippet(turns_fts, 0, '<b>', '</b>', '...', 12) AS snippet,
                bm25(turns_fts) AS bm25_score
            FROM turns_fts
            JOIN conversation_turns t ON t.id = turns_fts.rowid
            JOIN sessions s ON s.session_id = t.session_id
            WHERE turns_fts MATCH ?
              AND (? IS NULL OR s.project = ?)
            ORDER BY bm25_score ASC
            LIMIT ?
            """,
            (fts_match_query(query), project, project, max(limit * 8, 40)),
        ).fetchall()
        scored = [
            (
                _TurnHit(
                    session_id=row["session_id"],
                    harness=row["harness"],
                    turn_id=int(row["turn_id"]),
                    turn_count=row["turn_count"],
                    created_at=row["created_at"],
                    snippet=row["snippet"] or "",
                ),
                -float(row["bm25_score"] or 0.0),
            )
            for row in rows
        ]
        return _aggregate(scored, limit)

    def _search_hybrid(
        self,
        conn: sqlite3.Connection,
        query: str,
        project: Optional[str],
        limit: int,
    ) -> List[SearchHit]:
        match = fts_match_query(query)
        try:
            fts_rows = conn.execute(
                """
                SELECT rowid AS rowid, ROW_NUMBER() OVER (ORDER BY rank) AS fts_rank
                FROM turns_fts
                WHERE turns_fts MATCH ?
                LIMIT 50
                """,
                (match,),
            ).fetchall()
            blob = self._embed_query(query)
            if blob is None:
                return self._search_fts(conn, query, project, limit)
            vec_rows = conn.execute(
                """
                SELECT rowid AS rowid, ROW_NUMBER() OVER (ORDER BY distance ASC) AS vec_rank
                FROM turns_vec
                WHERE embedding MATCH ?
                  AND k = 50
                """,
                (blob,),
            ).fetchall()
        except sqlite3.DatabaseError:
            return self._search_fts(conn, query, project, limit)
        fused = fuse_ranks(
            conn,
            [(int(row["rowid"]), int(row["fts_rank"])) for row in fts_rows],
            [(int(row["rowid"]), int(row["vec_rank"])) for row in vec_rows],
            limit=50,
        )
        scored: List[Tuple[_TurnHit, float]] = []
        for rowid, score in fused:
            hit = self._load_hit(conn, rowid, match, project)
            if hit is not None:
                scored.append((hit, score))
        if not scored:
            return self._search_fts(conn, query, project, limit)
        return _aggregate(scored, limit)

    def _load_hit(
        self,
        conn: sqlite3.Connection,
        rowid: int,
        match: str,
        project: Optional[str],
    ) -> Optional[_TurnHit]:
        row = conn.execute(
            """
            SELECT
                t.session_id AS session_id,
                t.turn_id AS turn_id,
                t.content AS content,
                s.harness AS harness,
                s.turn_count AS turn_count,
                s.created_at AS created_at,
                snippet(turns_fts, 0, '<b>', '</b>', '...', 12) AS snippet
            FROM turns_fts
            JOIN conversation_turns t ON t.id = turns_fts.rowid
            JOIN sessions s ON s.session_id = t.session_id
            WHERE turns_fts MATCH ? AND t.id = ?
              AND (? IS NULL OR s.project = ?)
            """,
            (match, rowid, project, project),
        ).fetchone()
        if row is None:
            row = conn.execute(
                """
                SELECT
                    t.session_id AS session_id,
                    t.turn_id AS turn_id,
                    t.content AS content,
                    s.harness AS harness,
                    s.turn_count AS turn_count,
                    s.created_at AS created_at,
                    NULL AS snippet
                FROM conversation_turns t
                JOIN sessions s ON s.session_id = t.session_id
                WHERE t.id = ?
                  AND (? IS NULL OR s.project = ?)
                """,
                (rowid, project, project),
            ).fetchone()
        if row is None:
            return None
        snippet = row["snippet"] or _clip(row["content"] or "")
        return _TurnHit(
            session_id=row["session_id"],
            harness=row["harness"],
            turn_id=int(row["turn_id"]),
            turn_count=row["turn_count"],
            created_at=row["created_at"],
            snippet=snippet,
        )


def _aggregate(scored: Sequence[Tuple[_TurnHit, float]], limit: int) -> List[SearchHit]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for hit, score in scored:
        bucket = buckets.get(hit.session_id)
        if bucket is None:
            buckets[hit.session_id] = {
                "hit": hit,
                "score": score,
                "snippet": hit.snippet,
                "turns": [(score, hit.turn_id)],
            }
            continue
        if score > bucket["score"]:
            bucket["score"] = score
            if hit.snippet:
                bucket["snippet"] = hit.snippet
        bucket["turns"].append((score, hit.turn_id))
    ordered = sorted(buckets.values(), key=lambda item: (-item["score"], item["hit"].session_id))
    results: List[SearchHit] = []
    for bucket in ordered[:limit]:
        hit: _TurnHit = bucket["hit"]
        turns = [turn for _, turn in sorted(bucket["turns"], key=lambda item: (-item[0], item[1]))]
        results.append(
            SearchHit(
                session_id=hit.session_id,
                harness=hit.harness,
                score=float(bucket["score"]),
                snippet=bucket["snippet"] or "",
                matched_turns=list(dict.fromkeys(turns)),
                turn_count=hit.turn_count,
                created_at=hit.created_at,
            )
        )
    return results


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
        (name,),
    ).fetchone()
    return row is not None


def _serialize_f32(values: Sequence[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(list(values))


def _clip(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _extract_text(record: Dict[str, Any]) -> str:
    content = record.get("content")
    if content is None and isinstance(record.get("message"), dict):
        message = record["message"]
        content = message.get("content", message.get("text"))
    if content is None:
        content = record.get("text")
    return _stringify_content(content).strip()


def _stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                kind = str(block.get("type") or "").lower()
                if kind in {"tool_use", "tool_result", "tool_call", "image", "image_url"}:
                    continue
                if "text" in block:
                    parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        return _stringify_content(content.get("text") or content.get("content"))
    return ""


def _denoise_text(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    text = _BASE64_RE.sub(" ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _role_of(record: Dict[str, Any]) -> str:
    role = str(record.get("role") or "").lower()
    if role in {"user", "assistant", "system", "tool"}:
        return role
    source = str(record.get("source") or "").upper()
    kind = str(record.get("type") or "").upper()
    if "USER" in source or "USER" in kind:
        return "user"
    if "SYSTEM" in kind:
        return "system"
    if "TOOL" in kind:
        return "tool"
    return "assistant"


def _turn_id(record: Dict[str, Any], fallback: int) -> int:
    for key in ("step_index", "step_num", "ordinal", "turn_index", "turn_id"):
        value = record.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lstrip("-").isdigit():
            return int(value)
    return fallback


def _timestamp(record: Dict[str, Any]) -> Optional[str]:
    for key in ("created_at", "timestamp", "createdAt", "time", "ended_at"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    message = record.get("message")
    if isinstance(message, dict):
        return _timestamp(message)
    return None


def _iter_json_document(path: Path) -> Iterator[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(data, dict):
        return
    for key in ("messages", "turns", "conversation"):
        nested = data.get(key)
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    yield item
            return
    yield data
