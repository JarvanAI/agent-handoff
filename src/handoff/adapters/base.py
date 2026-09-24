"""Base abstract adapter definition for multi-agent session logs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from handoff.models import UnifiedTurn


class BaseSessionAdapter(ABC):
    """Abstract base class for all agent session adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Normalized provider identifier, e.g. 'antigravity', 'claude-code', etc."""
        ...

    @abstractmethod
    def parse_trajectory(self, path_or_id: Union[str, Path]) -> List[UnifiedTurn]:
        """Parse raw session logs into a normalized, chronological list of UnifiedTurns.

        Args:
            path_or_id: File path, directory path, or session ID string.

        Returns:
            List[UnifiedTurn] sorted in deterministic chronological order.
        """
        ...

    @staticmethod
    def normalize_timestamp(raw_ts: Any) -> str:
        """Convert varying timestamp formats (epoch ms, epoch s, ISO string) to standard ISO 8601 UTC."""
        if raw_ts is None:
            return datetime.now(timezone.utc).isoformat()

        if isinstance(raw_ts, (int, float)):
            # Distinguish milliseconds vs seconds
            # 1e11 ms is ~1973, 1e11 s is far future
            val = float(raw_ts)
            if val > 1e11:  # epoch milliseconds
                dt = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            else:  # epoch seconds
                dt = datetime.fromtimestamp(val, tz=timezone.utc)
            return dt.isoformat()

        if isinstance(raw_ts, str):
            clean = raw_ts.strip()
            if not clean:
                return datetime.now(timezone.utc).isoformat()
            # If string is all digits
            if clean.isdigit():
                val = float(clean)
                if val > 1e11:
                    return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc).isoformat()
                return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
            return clean

        return str(raw_ts)

    @staticmethod
    def load_jsonl(file_path: Union[str, Path]) -> List[Dict[str, Any]]:
        """Safely load JSONL file, ignoring empty lines."""
        path = Path(file_path)
        if not path.is_file():
            return []

        rows: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        rows.append(data)
                except Exception:
                    continue
        return rows
