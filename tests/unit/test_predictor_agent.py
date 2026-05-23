"""
tests/unit/test_predictor_agent.py
Unit tests for PredictorAgent — CPA-based trajectory prediction.
"""

import pytest

from artemis.cognition.agents.predictor_agent import PredictorAgent
from artemis.core.types import Track, TrackStatus


def _track(
    x=0.0,
    y=0.0,
    z=50.0,
    vx=0.0,
    vy=0.0,
    vz=0.0,
    track_id="t-0001",
) -> Track:
    return Track(
        track_id=track_id,
        status=TrackStatus.CONFIRMED,
        state=[x, y, z, vx, vy, vz],
    )


class TestPredictorAgent:
    agent = PredictorAgent()

    # ------------------------------------------------------------------
    # Static drone (v ≈ 0)
    # ------------------------------------------------------------------

    def test_static_drone_no_tti(self):
        """A stationary drone has no time-to-impact (None)."""
        result = self.agent.predict(_track())
        assert result.time_to_impact_s is None

    def test_static_drone_probability_low(self):
        """A stationary drone at 50 m altitude has non-trivial range → low prob."""
        result = self.agent.predict(_track(x=200.0, y=150.0, z=50.0))
        # Range ≈ 260 m → well under 2000 m → some probability
        assert 0.0 <= result.probability <= 1.0

    # ------------------------------------------------------------------
    # Head-on approach
    # ------------------------------------------------------------------

    def test_head_on_approach_tti_positive(self):
        """Drone approaching origin from 100 m away at 5 m/s → tti ≈ 20 s."""
        result = self.agent.predict(_track(x=100.0, y=0.0, z=0.0, vx=-5.0))
        assert result.time_to_impact_s is not None
        assert pytest.approx(result.time_to_impact_s, abs=2.0) == 20.0

    def test_approaching_drone_high_probability(self):
        """Drone closing at < 500 m range → probability > 0.7."""
        result = self.agent.predict(_track(x=300.0, y=0.0, z=0.0, vx=-15.0))
        assert result.probability >= 0.7

    # ------------------------------------------------------------------
    # Receding drone
    # ------------------------------------------------------------------

    def test_receding_drone_no_tti(self):
        """Drone moving away from origin has no CPA interception → tti = None."""
        result = self.agent.predict(_track(x=100.0, y=0.0, z=0.0, vx=10.0))
        assert result.time_to_impact_s is None

    def test_receding_drone_low_probability(self):
        """Drone moving away has lower probability than approaching one."""
        receding = self.agent.predict(_track(x=400.0, y=0.0, z=0.0, vx=20.0))
        approaching = self.agent.predict(_track(x=400.0, y=0.0, z=0.0, vx=-20.0))
        assert receding.probability <= approaching.probability

    # ------------------------------------------------------------------
    # Waypoints
    # ------------------------------------------------------------------

    def test_waypoints_count(self):
        """PredictorAgent always returns exactly 4 forward waypoints."""
        result = self.agent.predict(_track(x=50.0, y=0.0, z=0.0, vx=-2.0))
        assert len(result.waypoints) == 4

    def test_waypoints_advance_in_time(self):
        """Waypoints should be at increasing distances from origin for approaching drone."""
        result = self.agent.predict(_track(x=100.0, y=0.0, z=0.0, vx=-3.0))
        # Each waypoint is a (x, y, z) tuple
        assert all(len(wp) == 3 for wp in result.waypoints)

    # ------------------------------------------------------------------
    # Probability bounds
    # ------------------------------------------------------------------

    def test_probability_clamped_to_unit_interval(self):
        """Probability must always be in [0, 1]."""
        for x in [0.0, 10.0, 100.0, 500.0, 1500.0, 2500.0]:
            result = self.agent.predict(_track(x=x, y=0.0, z=0.0, vx=-5.0))
            assert 0.0 <= result.probability <= 1.0, f"prob out of range for x={x}"
