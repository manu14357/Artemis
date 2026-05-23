"""
artemis/cognition/agents/threat_scorer.py
Threat-scoring agent: converts confirmed tracks into weighted threat scores.

Scoring factors:
  - Speed: fast-approaching targets score higher
  - Sensor coverage: tracks confirmed by more sensor layers score higher
  - Drone type: heavier / more capable drones score higher base threat
  - Proximity: closer tracks score higher
  - Bearing trajectory: targets approaching a protected zone score higher

Output: dict mapping track_id → float score in [0, 1].
A score ≥ 0.8 should be escalated to Tier 4/5 (immediate response).
"""

from __future__ import annotations

import math
from typing import Sequence

from artemis.core.logging import get_logger
from artemis.core.types import DroneType, Track, TrackStatus

log = get_logger("cognition.threat_scorer")


# ---------------------------------------------------------------------------
# Drone type base scores
# ---------------------------------------------------------------------------

_DRONE_BASE_SCORE: dict[DroneType, float] = {
    DroneType.DJI_MAVIC: 0.35,  # mid-weight, camera / payload capable
    DroneType.DJI_MINI: 0.20,  # lightweight, limited payload
    DroneType.AUTEL_EVO: 0.35,  # similar to Mavic class
    DroneType.FPV_GENERIC: 0.50,  # high-speed, often used in kinetic attacks
    DroneType.UNKNOWN: 0.30,  # conservative default
}

# Per-layer bonus: each extra sensor layer adds evidence → higher confidence
_LAYER_BONUS_PER_LAYER: float = 0.05
_MAX_LAYER_BONUS: float = 0.20  # capped at 4 layers × 0.05

# Speed scoring: above 30 m/s counts as full speed threat
_SPEED_MAX_MPS: float = 30.0

# Range scoring: below this distance (metres) triggers full proximity score
_CLOSE_RANGE_M: float = 200.0
_VERY_CLOSE_M: float = 50.0


class ThreatScorer:
    """
    Stateless threat scorer.  Call ``score(tracks)`` to get per-track scores.

    Parameters
    ----------
    protected_origin_m : tuple[float, float]
        (x_m, y_m) of the protected asset in local Cartesian coords.
        Defaults to (0, 0) — the hub reference point.
    approach_weight : float
        Extra weight for tracks whose velocity vector points toward the
        protected origin.  0 = ignore, 1 = full weighting.
    """

    def __init__(
        self,
        protected_origin_m: tuple[float, float] = (0.0, 0.0),
        approach_weight: float = 0.30,
    ) -> None:
        self._origin = protected_origin_m
        self._approach_weight = approach_weight

    def score(self, tracks: Sequence[Track]) -> dict[str, float]:
        """
        Score each confirmed track.

        Parameters
        ----------
        tracks : sequence of Track objects

        Returns
        -------
        dict mapping track_id → score in [0, 1]
        Only confirmed (non-dropped) tracks are scored.
        """
        scores: dict[str, float] = {}
        for track in tracks:
            if track.status == TrackStatus.DROPPED:
                continue
            s = self._score_one(track)
            scores[track.track_id] = round(min(max(s, 0.0), 1.0), 4)
            log.debug(
                "track=%s status=%s score=%.3f",
                track.track_id,
                track.status.value,
                scores[track.track_id],
            )
        return scores

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _score_one(self, track: Track) -> float:
        """Compute raw score for a single track (may exceed 1 before clamping)."""
        x, y, _ = track.position_m
        vx, vy, _ = track.velocity_mps

        # 1. Drone type base score
        drone_type = self._infer_drone_type(track)
        base = _DRONE_BASE_SCORE.get(drone_type, 0.30)

        # 2. Sensor layer bonus
        n_layers = len(track.sensor_layers)
        layer_bonus = min(n_layers * _LAYER_BONUS_PER_LAYER, _MAX_LAYER_BONUS)

        # 3. Speed component (0–1)
        speed = track.speed_mps
        speed_score = min(speed / _SPEED_MAX_MPS, 1.0)

        # 4. Proximity component (0–1)
        ox, oy = self._origin
        dist = math.sqrt((x - ox) ** 2 + (y - oy) ** 2)
        if dist <= _VERY_CLOSE_M:
            prox_score = 1.0
        elif dist <= _CLOSE_RANGE_M:
            prox_score = 1.0 - (dist - _VERY_CLOSE_M) / (_CLOSE_RANGE_M - _VERY_CLOSE_M)
        else:
            # Linear decay beyond close range; effectively 0 at 2 km
            prox_score = max(0.0, 1.0 - dist / 2000.0)

        # 5. Approach component: dot product of velocity toward origin
        approach_score = 0.0
        if speed > 0.1:
            # Unit vector from track to origin
            dx, dy = ox - x, oy - y
            d = math.sqrt(dx**2 + dy**2) or 1.0
            # Cosine similarity between velocity vector and approach direction
            cos_theta = (vx * dx + vy * dy) / (speed * d)
            # Map [-1, +1] → [0, 1] and scale by weight
            approach_score = self._approach_weight * max(cos_theta, 0.0)

        # 6. Coast penalty: coasting tracks are less certain
        coast_penalty = 0.0
        if track.status == TrackStatus.COASTED:
            coast_penalty = 0.10

        total = (
            base
            + layer_bonus
            + 0.15 * speed_score
            + 0.25 * prox_score
            + approach_score
            - coast_penalty
        )
        return total

    @staticmethod
    def _infer_drone_type(track: Track) -> DroneType:
        """Extract drone type from the track's most recent detections."""
        for det in track.last_detections.values():
            dt = getattr(det, "drone_type", DroneType.UNKNOWN)
            if dt != DroneType.UNKNOWN:
                return dt
        return DroneType.UNKNOWN
