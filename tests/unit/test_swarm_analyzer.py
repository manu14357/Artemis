"""
tests/unit/test_swarm_analyzer.py
Unit tests for DBSCAN-based swarm detection.
"""

from artemis.core.types import Track, TrackStatus
from artemis.fusion.swarm_analyzer import analyze_swarms, swarm_sizes


def _track(track_id: str, x: float, y: float, z: float = 50.0) -> Track:
    return Track(
        track_id=track_id,
        state=[x, y, z, 0.0, 0.0, 0.0],
        status=TrackStatus.CONFIRMED,
    )


class TestAnalyzeSwarms:
    def test_cluster_detected(self):
        tracks = [
            _track("t1", 0, 0),
            _track("t2", 10, 5),
            _track("t3", -5, 8),
        ]
        result = analyze_swarms(tracks, eps_m=50.0, min_samples=2)
        swarm_ids = set(v for v in result.values() if v is not None)
        assert len(swarm_ids) >= 1

    def test_isolated_drone_not_in_swarm(self):
        tracks = [
            _track("t1", 0, 0),
            _track("t2", 10, 5),
            _track("t3", -5, 8),
            _track("isolated", 5000, 5000),  # far away
        ]
        result = analyze_swarms(tracks, eps_m=50.0, min_samples=2)
        assert result["isolated"] is None

    def test_empty_input(self):
        result = analyze_swarms([], eps_m=50.0, min_samples=2)
        assert result == {}

    def test_swarm_sizes(self):
        assignment = {"t1": "sw0", "t2": "sw0", "t3": None}
        sizes = swarm_sizes(assignment)
        assert sizes["sw0"] == 2
