"""Dispatch a search to agentsview, then to the embedded engine."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from agent_handoff.search.agentsview import AgentsViewAdapter, AgentsViewError
from agent_handoff.search.base import SearchEnvelope
from agent_handoff.search.embedded import EmbeddedSearchEngine


def search_sessions(
    query: str,
    project: Optional[str] = None,
    *,
    limit: int = 10,
    paths: Optional[Sequence[Path | str]] = None,
    db_path: Optional[Path | str] = None,
    engine: str = "auto",
    discover: Optional[bool] = None,
    vector_source: object = None,
) -> SearchEnvelope:
    """Search sessions, preferring Tier 1 and falling back to Tier 2.

    ``engine`` is ``auto`` (Tier 1, then Tier 2), ``agentsview``, or
    ``embedded``. Tier 1 failures are silent in ``auto`` mode.
    """

    if engine not in {"auto", "agentsview", "embedded"}:
        raise ValueError("engine must be auto, agentsview, or embedded")
    if engine != "embedded":
        adapter = AgentsViewAdapter()
        try:
            if adapter.available():
                return adapter.search(query, project=project, limit=limit)
            if engine == "agentsview":
                raise AgentsViewError("agentsview CLI and service are not available")
        except Exception:
            if engine == "agentsview":
                raise
    embedded = EmbeddedSearchEngine(db_path=db_path, vector_source=vector_source)
    if paths:
        for path in paths:
            embedded.index_path(path, project=project)
    elif discover is None or discover:
        embedded.index_tree([Path.cwd()], project=project)
    return embedded.search(query, project=project, limit=limit)
