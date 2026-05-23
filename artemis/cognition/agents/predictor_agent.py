"""
artemis/cognition/agents/predictor_agent.py
Linear-extrapolation trajectory predictor.

Given a Track's 6-DOF state [x, y, z, vx, vy, vz], the agent:
  1. Projects the position at each waypoint horizon (5, 10, 20, 30 s).
  2. Finds the closest point of approach (CPA) to the protected origin
     using the analytical parametric formula (no iteration needed).
  3. Estimates the time to reach the CPA.
  4. Computes an impact probability proportional to how close the CPA is
     to the origin (linear decay from 1.0 at 0 m to 0.0 at 2000 m).

The predictor is stateless, CPU-only, and completes in < 0.1 ms.

Timeout: 20 ms (hub_default.yaml cognition.predictor_timeout_ms)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from artemis.core.logging import get_logger
from artemis.core.types import Track

log = get_logger("cognition.predictor")


_WAYPOINT_HORIZONS_S: tuple[float, ...] = (5.0, 10.0, 20.0, 30.0)

# Probability of impact → 1.0 at CPA distance = 0 m, → 0.0 at 2000 m.
_MAX_SAFE_RANGE_M: float = 2000.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PredictionResult:
    """Output of PredictorAgent.predict()."""
    # (x, y, z) position tuples at each waypoint horizon
    waypoints:        list[tuple]
    # Closest approach coordinates (metres, XY plane)
    impact_x_m:       float
    impact_y_m:       float
    # Time from now until CPA; None when drone is receding or stationary
    time_to_impact_s: float | None
    # Impact probability in [0, 1]
    probability:      float


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class PredictorAgent:
    """
    Stateless linear-extrapolation trajectory predictor.

    Call ``predict(track)`` to obtain a ``PredictionResult``.

    Parameters
    ----------
    protected_origin_m : tuple[float, float]
        (x_m, y_m) of the protected asset.  Defaults to hub reference (0, 0).
    horizon_s : float
        Maximum extrapolation horizon in seconds.  Default 30 s.
    """

    def __init__(
        self,
        protected_origin_m: tuple[float, float] = (0.0, 0.0),
        horizon_s: float = 30.0,
    ) -> None:
        self._ox, self._oy = protected_origin_m
        self._horizon_s = horizon_s

    def predict(self, track: Track) -> PredictionResult:
        """
        Predict trajectory for a single track.

        Parameters
        ----------
        track : Track — state[0:6] = [x, y, z, vx, vy, vz]

        Returns
        -------
        PredictionResult
        """
        x, y, z, vx, vy, vz = track.state

        # 1. Waypoints
        waypoints = [
            (x + vx * t, y + vy * t, z + vz * t)
            for t in _WAYPOINT_HORIZONS_S
        ]

        # 2. Closest point of approach in XY plane
        # P(t) = (x + vx*t, y + vy*t)
        # Minimise distance²: d/dt |P(t) - O|² = 0
        # → t* = -[(P0 - O) · V] / |V|²
        ox, oy = self._ox, self._oy
        v_sq = vx * vx + vy * vy

        if v_sq < 1e-9:
            # Stationary — CPA is current position
            cpa_x, cpa_y = x, y
            tti: float | None = None
        else:
            t_star = -((x - ox) * vx + (y - oy) * vy) / v_sq
            if t_star < 0:
                # Already passed CPA (receding)
                cpa_x, cpa_y = x, y
                tti = None
            else:
                t_clamped = min(t_star, self._horizon_s)
                cpa_x = x + vx * t_clamped
                cpa_y = y + vy * t_clamped
                tti = t_clamped if t_star <= self._horizon_s else None

        # 3. Impact probability
        cpa_dist = math.sqrt((cpa_x - ox) ** 2 + (cpa_y - oy) ** 2)
        probability = round(max(0.0, min(1.0, 1.0 - cpa_dist / _MAX_SAFE_RANGE_M)), 4)

        log.debug(
            "track=%s cpa=(%.1f,%.1f) tti=%s prob=%.3f",
            track.track_id, cpa_x, cpa_y,
            f"{tti:.1f}s" if tti is not None else "N/A",
            probability,
        )

        return PredictionResult(
            waypoints=waypoints,
            impact_x_m=round(cpa_x, 2),
            impact_y_m=round(cpa_y, 2),
            time_to_impact_s=round(tti, 2) if tti is not None else None,
            probability=probability,
        )
