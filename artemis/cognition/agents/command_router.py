"""
artemis/cognition/agents/command_router.py
Command router: translates scored threats into engagement Commands.

Routing rules (in priority order):
  1. Score ≥ 0.80  → ENGAGE_HARD   (kinetic / full electronic countermeasure)
  2. Score ≥ 0.60  → ENGAGE_SOFT   (GPS spoof / audio deterrent)
  3. Score ≥ 0.40  → TRACK_ONLY    (hold, continue monitoring)
  4. Score < 0.40  → IGNORE        (no action)

Deduplication: a command is only emitted if the tier has *changed* since the
last routing cycle.  This prevents flooding the effector topic.

Thread safety: this class is stateful (stores last tier per track_id).
Use one instance per hub process; it is not safe to share across threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Sequence

from artemis.core.logging import get_logger
from artemis.core.types import Track

log = get_logger("cognition.command_router")


# ---------------------------------------------------------------------------
# Command types
# ---------------------------------------------------------------------------


class EngagementTier(str, Enum):
    IGNORE = "ignore"
    TRACK_ONLY = "track_only"
    ENGAGE_SOFT = "engage_soft"
    ENGAGE_HARD = "engage_hard"


@dataclass
class Command:
    """An engagement command emitted by the router."""

    track_id: str
    tier: EngagementTier
    score: float
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "tier": self.tier.value,
            "score": round(self.score, 4),
            "position": {"x": self.x_m, "y": self.y_m, "z": self.z_m},
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Routing thresholds
# ---------------------------------------------------------------------------

_THRESHOLD_HARD: float = 0.80
_THRESHOLD_SOFT: float = 0.60
_THRESHOLD_TRACK: float = 0.40


def _tier_from_score(score: float) -> EngagementTier:
    if score >= _THRESHOLD_HARD:
        return EngagementTier.ENGAGE_HARD
    if score >= _THRESHOLD_SOFT:
        return EngagementTier.ENGAGE_SOFT
    if score >= _THRESHOLD_TRACK:
        return EngagementTier.TRACK_ONLY
    return EngagementTier.IGNORE


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class CommandRouter:
    """
    Stateful command router.

    Call ``route(tracks, scores)`` each fusion cycle.
    Returns only commands where the engagement tier has changed since the
    last cycle, avoiding repeated emissions for stable threats.
    """

    def __init__(self) -> None:
        # Maps track_id → last emitted EngagementTier
        self._last_tier: dict[str, EngagementTier] = {}

    def route(
        self,
        tracks: Sequence[Track],
        scores: dict[str, float],
    ) -> list[Command]:
        """
        Route scored threats to engagement commands.

        Parameters
        ----------
        tracks : confirmed tracks (from TrackManager)
        scores : dict from ThreatScorer.score() — track_id → float

        Returns
        -------
        list[Command] — only changed-tier commands (may be empty)
        """
        commands: list[Command] = []
        seen_ids: set[str] = set()

        for track in tracks:
            tid = track.track_id
            seen_ids.add(tid)

            score = scores.get(tid, 0.0)
            tier = _tier_from_score(score)

            # Skip if tier unchanged
            if self._last_tier.get(tid) == tier:
                continue

            self._last_tier[tid] = tier

            if tier == EngagementTier.IGNORE:
                # Still record but don't emit an active command
                log.debug("track=%s tier=IGNORE score=%.3f", tid, score)
                continue

            x, y, z = track.position_m
            cmd = Command(
                track_id=tid,
                tier=tier,
                score=score,
                x_m=x,
                y_m=y,
                z_m=z,
            )
            commands.append(cmd)
            log.info(
                "Command emitted track=%s tier=%s score=%.3f pos=(%.1f, %.1f, %.1f)",
                tid,
                tier.value,
                score,
                x,
                y,
                z,
            )

        # Clean up state for dropped tracks
        dropped = set(self._last_tier.keys()) - seen_ids
        for tid in dropped:
            del self._last_tier[tid]
            log.debug("Cleaned up dropped track=%s", tid)

        return commands
