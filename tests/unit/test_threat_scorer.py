"""
tests/unit/test_threat_scorer.py
Unit tests for artemis.cognition.agents.threat_scorer.ThreatScorer
"""
from __future__ import annotations



from artemis.cognition.agents.threat_scorer import ThreatScorer
from artemis.core.types import DroneType, SensorLayer, Track, TrackStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_track(
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    vx: float = 0.0,
    vy: float = 0.0,
    vz: float = 0.0,
    drone_type: DroneType = DroneType.UNKNOWN,
    layers: set | None = None,
    status: TrackStatus = TrackStatus.CONFIRMED,
) -> Track:
    """Create a minimal Track for testing."""
    t = Track(status=status)
    t.state = [x, y, z, vx, vy, vz]
    t.sensor_layers = layers or set()
    if drone_type != DroneType.UNKNOWN:
        # Inject a mock detection so _infer_drone_type works
        from dataclasses import dataclass

        @dataclass
        class _MockDet:
            drone_type: DroneType

        t.last_detections = {"rf": _MockDet(drone_type=drone_type)}
    return t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestThreatScorerBasic:
    def setup_method(self) -> None:
        self.scorer = ThreatScorer(protected_origin_m=(0.0, 0.0))

    def test_dropped_track_excluded(self) -> None:
        t = _make_track(status=TrackStatus.DROPPED)
        scores = self.scorer.score([t])
        assert t.track_id not in scores

    def test_tentative_track_scored(self) -> None:
        t = _make_track(status=TrackStatus.TENTATIVE, x=500.0)
        scores = self.scorer.score([t])
        assert t.track_id in scores
        assert 0.0 <= scores[t.track_id] <= 1.0

    def test_confirmed_track_scored(self) -> None:
        t = _make_track(status=TrackStatus.CONFIRMED, x=100.0, y=50.0)
        scores = self.scorer.score([t])
        assert t.track_id in scores
        assert 0.0 <= scores[t.track_id] <= 1.0

    def test_score_clamped_to_unit_interval(self) -> None:
        """Extreme scenario: very close, very fast, FPV drone, 4 layers."""
        t = _make_track(
            x=10.0, y=5.0,
            vx=35.0, vy=20.0,   # high speed toward origin
            drone_type=DroneType.FPV_GENERIC,
            layers={SensorLayer.RF, SensorLayer.ACOUSTIC, SensorLayer.RADAR, SensorLayer.OPTICAL},
        )
        scores = self.scorer.score([t])
        score = scores[t.track_id]
        assert 0.0 <= score <= 1.0, f"Score out of bounds: {score}"

    def test_fpv_scores_higher_than_mini(self) -> None:
        """FPV_GENERIC base score > DJI_MINI base score."""
        fpv = _make_track(drone_type=DroneType.FPV_GENERIC, x=200.0)
        mini = _make_track(drone_type=DroneType.DJI_MINI, x=200.0)
        scores = self.scorer.score([fpv, mini])
        assert scores[fpv.track_id] > scores[mini.track_id]

    def test_closer_scores_higher(self) -> None:
        far = _make_track(x=1000.0)
        close = _make_track(x=30.0)
        scores = self.scorer.score([far, close])
        assert scores[close.track_id] > scores[far.track_id]

    def test_multi_layer_bonus(self) -> None:
        single = _make_track(x=200.0, layers={SensorLayer.RF})
        quad = _make_track(
            x=200.0,
            layers={SensorLayer.RF, SensorLayer.ACOUSTIC, SensorLayer.RADAR, SensorLayer.OPTICAL},
        )
        scores = self.scorer.score([single, quad])
        assert scores[quad.track_id] > scores[single.track_id]

    def test_approaching_scores_higher_than_receding(self) -> None:
        """Track at (-200, 0) moving toward (0,0) should score higher than moving away."""
        approaching = _make_track(x=-200.0, y=0.0, vx=15.0, vy=0.0)  # toward origin
        receding = _make_track(x=-200.0, y=0.0, vx=-15.0, vy=0.0)    # away from origin
        scores = self.scorer.score([approaching, receding])
        assert scores[approaching.track_id] > scores[receding.track_id]

    def test_coast_penalty(self) -> None:
        confirmed = _make_track(x=100.0, status=TrackStatus.CONFIRMED)
        coasted = _make_track(x=100.0, status=TrackStatus.COASTED)
        scores = self.scorer.score([confirmed, coasted])
        # Coasted tracks should score lower than confirmed
        assert scores[confirmed.track_id] > scores[coasted.track_id]

    def test_empty_tracks(self) -> None:
        scores = self.scorer.score([])
        assert scores == {}

    def test_multiple_tracks_all_scored(self) -> None:
        tracks = [_make_track(x=float(i * 50)) for i in range(5)]
        scores = self.scorer.score(tracks)
        assert len(scores) == 5
        for tid, s in scores.items():
            assert 0.0 <= s <= 1.0, f"track {tid} score={s} out of range"

    def test_score_deterministic(self) -> None:
        """Same input → same output across calls."""
        t = _make_track(x=150.0, y=100.0, vx=10.0, drone_type=DroneType.DJI_MAVIC)
        s1 = self.scorer.score([t])
        s2 = self.scorer.score([t])
        assert s1 == s2
