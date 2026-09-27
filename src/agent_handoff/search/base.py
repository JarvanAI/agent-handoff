"""Search contract shared by the agentsview adapter and the embedded engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

SEARCH_PROTOCOL = "agent-handoff:search:v1"
RRF_K = 60


@dataclass
class SearchHit:
    """One session recalled for a query."""

    session_id: str
    harness: str
    score: float
    snippet: str
    matched_turns: List[int] = field(default_factory=list)
    turn_count: Optional[int] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "harness": self.harness,
            "score": round(float(self.score), 6),
            "snippet": self.snippet,
            "matched_turns": list(self.matched_turns),
            "turn_count": self.turn_count,
            "created_at": self.created_at,
        }


@dataclass
class SearchEnvelope:
    """Deterministic search response used by the CLI and the Python API."""

    query: str
    engine: str
    project: Optional[str]
    results: List[SearchHit] = field(default_factory=list)
    protocol: str = SEARCH_PROTOCOL

    @property
    def total_hits(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "engine": self.engine,
            "query": self.query,
            "project": self.project,
            "total_hits": self.total_hits,
            "results": [hit.to_dict() for hit in self.results],
        }


class BaseSearchEngine(ABC):
    """Tier adapter that returns a :class:`SearchEnvelope`."""

    name: str

    @abstractmethod
    def available(self) -> bool:
        """Return whether this engine can answer a query in the current process."""

    @abstractmethod
    def search(
        self,
        query: str,
        project: Optional[str] = None,
        *,
        limit: int = 10,
    ) -> SearchEnvelope:
        """Search sessions and return the protocol envelope."""
