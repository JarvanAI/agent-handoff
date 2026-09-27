"""Session-search: agentsview first, embedded SQLite FTS5 as the fallback."""

from agent_handoff.search.base import BaseSearchEngine, SearchEnvelope, SearchHit
from agent_handoff.search.router import search_sessions

__all__ = [
    "BaseSearchEngine",
    "SearchEnvelope",
    "SearchHit",
    "search_sessions",
]
