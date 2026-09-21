"""Log truncation deep penetration and restoration module.

Restores truncated frames from corresponding full log files (e.g. Antigravity's
transcript_full.jsonl) deterministically without external LLM dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class LogPenetrator:
    """Restores truncated entries in session transcripts."""

    def __init__(self, full_log_path: Optional[Union[str, Path]] = None) -> None:
        self.full_log_path = Path(full_log_path) if full_log_path else None
        self._index: Optional[Dict[int, int]] = None  # step_index -> line_number
        self._full_lines_cache: Optional[List[str]] = None

    def set_full_log(self, full_log_path: Union[str, Path]) -> None:
        """Set or update the target full log path."""
        self.full_log_path = Path(full_log_path)
        self._index = None
        self._full_lines_cache = None

    def is_available(self) -> bool:
        """Return True if the full log file exists and is readable."""
        return bool(self.full_log_path and self.full_log_path.is_file())

    def _ensure_cache_or_index(self) -> None:
        """Lazily read full log lines or build index for fast random access."""
        if self._full_lines_cache is not None or not self.is_available():
            return

        assert self.full_log_path is not None
        # For typical log sizes (< 50MB), reading lines into memory is fast (< 100ms)
        try:
            with open(self.full_log_path, "r", encoding="utf-8", errors="replace") as f:
                self._full_lines_cache = f.readlines()
        except OSError:
            self._full_lines_cache = []

        self._index = {}
        for line_no, raw_line in enumerate(self._full_lines_cache):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                # Fast probe for "step_index": int without full JSON parsing if possible
                if '"step_index":' in raw_line:
                    record = json.loads(raw_line)
                    step_idx = record.get("step_index")
                    if step_idx is not None:
                        self._index[int(step_idx)] = line_no
            except Exception:
                continue

    def penetrate_record(
        self, record: Dict[str, Any], line_no: Optional[int] = None
    ) -> Dict[str, Any]:
        """Restore truncated fields in a single transcript record.

        Args:
            record: Parsed dict from compact transcript.jsonl.
            line_no: 0-indexed line number in the transcript file (optional).

        Returns:
            The enriched record with truncated fields restored from full log.
        """
        truncated_fields = record.get("truncated_fields")
        if not truncated_fields or not self.is_available():
            return record

        self._ensure_cache_or_index()
        if not self._full_lines_cache:
            return record

        target_line_no: Optional[int] = None
        step_index = record.get("step_index")

        # 1. Look up by step_index in index
        if step_index is not None and self._index and int(step_index) in self._index:
            target_line_no = self._index[int(step_index)]
        # 2. Fall back to identical line number
        elif line_no is not None and 0 <= line_no < len(self._full_lines_cache):
            target_line_no = line_no

        if target_line_no is None or target_line_no >= len(self._full_lines_cache):
            return record

        try:
            full_record = json.loads(self._full_lines_cache[target_line_no])
        except Exception:
            return record

        # Merge restored fields
        enriched = dict(record)
        for field in truncated_fields:
            if field in full_record:
                enriched[field] = full_record[field]

        # Remove or mark truncated_fields as restored
        enriched["_penetrated"] = True
        enriched.pop("truncated_fields", None)
        return enriched

    @staticmethod
    def clean_truncation_artifacts(text: str) -> str:
        """Strip internal truncation markers if present."""
        if not text:
            return ""
        # Remove truncation boilerplate
        import re

        text = re.sub(
            r"\n?<truncated \d+ bytes>\n?",
            "\n",
            text,
        )
        text = re.sub(
            r"\nNOTE: The output was truncated because it was too long\..*?(\n|$)",
            "",
            text,
        )
        return text.strip()
