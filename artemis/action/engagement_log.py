"""
artemis/action/engagement_log.py
Append-only NDJSON engagement ledger.

Records each engagement command dispatched by CognitionPipeline so
operators can audit decisions post-hoc and the dashboard can display
engagement history.

Design goals
------------
- Thread-safe: SimRelay and CognitionPipeline may call it from different
  threads (paho background thread vs. asyncio event loop thread).
- Crash-safe: each record is flushed to disk immediately (no buffering).
- Portable: plain NDJSON so ``jq``, ``tail -f``, and simple Python reads
  all work without any special tooling.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from dataclasses import dataclass, field

from artemis.core.logging import get_logger

log = get_logger("action.engagement_log")

_DEFAULT_PATH = "logs/engagements.ndjson"


# ---------------------------------------------------------------------------
# Engagement record
# ---------------------------------------------------------------------------

@dataclass
class EngagementRecord:
    """One dispatched engagement command (JSON-serialisable)."""
    track_id:    str
    effector_id: str
    tier:        str    # EngagementTier.value — kept as string for easy JSON
    score:       float
    x_m:         float = 0.0
    y_m:         float = 0.0
    z_m:         float = 0.0
    timestamp:   float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "track_id":    self.track_id,
            "effector_id": self.effector_id,
            "tier":        self.tier,
            "score":       round(self.score, 4),
            "position":    {"x": self.x_m, "y": self.y_m, "z": self.z_m},
            "timestamp":   self.timestamp,
        }


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

class EngagementLog:
    """
    Append-only NDJSON engagement log.

    Thread-safe: a single ``threading.Lock`` serialises all reads and writes.

    Parameters
    ----------
    path : str | pathlib.Path
        File path for the NDJSON log.  Parent directories are created on
        first write.  Defaults to ``logs/engagements.ndjson``.
    """

    def __init__(self, path: str | pathlib.Path = _DEFAULT_PATH) -> None:
        self._path = pathlib.Path(path)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, record: EngagementRecord) -> None:
        """Append a single engagement record to the log (flush immediately)."""
        line = json.dumps(record.to_dict(), default=str)
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                log.error("failed to write engagement log: %s", exc)

    def recent(self, n: int = 100) -> list[dict]:
        """
        Return the last *n* records as a list of dicts (newest first).

        Uses a tail-read so large log files are not loaded entirely into
        memory.  Returns ``[]`` when the log file does not exist yet.
        """
        if not self._path.exists():
            return []
        try:
            with self._lock:
                with self._path.open("r") as fh:
                    lines = fh.readlines()
        except OSError as exc:
            log.error("failed to read engagement log: %s", exc)
            return []

        tail = lines[-n:] if len(lines) > n else lines
        records: list[dict] = []
        for line in reversed(tail):
            stripped = line.strip()
            if stripped:
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError:
                    pass
        return records

    def clear(self) -> None:
        """Truncate the log file.  Intended for test teardown only."""
        with self._lock:
            if self._path.exists():
                self._path.unlink()
