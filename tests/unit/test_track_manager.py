"""
tests/unit/test_track_manager.py
Unit tests for TrackManager lifecycle (TENTATIVE → CONFIRMED → COASTED → DROPPED).
"""
import time


from artemis.core.types import RadarDetection, TrackStatus
from artemis.fusion.track_manager import TrackManager


def _radar(x: float, y: float, z: float, source: str = "n1") -> RadarDetection:
    """Helper: radar detection at approx Cartesian position (via range/bearing)."""
    import math
    range_m = math.sqrt(x**2 + y**2)
    bearing_deg = math.degrees(math.atan2(x, y)) % 360.0
    return RadarDetection(
        range_m=max(range_m, 0.1),
        micro_doppler_spread=20.0,
        source=source,
        timestamp=time.time(),
        bearing_deg=bearing_deg,
        velocity_mps=0.0,
    )


class TestTrackManager:
    def setup_method(self):
        self.mgr = TrackManager(
            process_noise_q=0.1,
            measurement_noise_r=0.5,
            max_coast_frames=3,
            max_distance_m=100.0,
            min_sensor_layers=1,
        )

    def test_new_detection_creates_track(self):
        tracks = self.mgr.update([_radar(10.0, 20.0, 50.0)])
        assert len(tracks) == 1
        # min_sensor_layers=1 so single detection may confirm immediately
        assert tracks[0].status in (TrackStatus.TENTATIVE, TrackStatus.CONFIRMED)

    def test_repeated_detections_confirm_track(self):
        det = _radar(10.0, 20.0, 50.0)
        tracks = None
        for _ in range(5):
            tracks = self.mgr.update([det])
        assert any(t.status == TrackStatus.CONFIRMED for t in tracks)

    def test_coasted_track_increments(self):
        det = _radar(10.0, 20.0, 50.0)
        for _ in range(5):
            self.mgr.update([det])
        # Now stop sending detections — track should coast
        tracks = self.mgr.update([])
        coasted = [t for t in tracks if t.coast_frames > 0]
        assert len(coasted) > 0

    def test_track_dropped_after_max_coast(self):
        det = _radar(10.0, 20.0, 50.0)
        for _ in range(5):
            self.mgr.update([det])
        # Coast until dropped
        for _ in range(10):
            tracks = self.mgr.update([])
        [t for t in tracks if t.status == TrackStatus.DROPPED]
        # After many empty frames, track should be dropped (removed from active list)
        # all_tracks includes dropped until next cycle
        assert len(self.mgr.get_confirmed_tracks()) == 0

    def test_multiple_targets_tracked_independently(self):
        d1 = _radar(10.0, 0.0, 50.0, source="n1")
        d2 = _radar(-200.0, 0.0, 50.0, source="n2")  # far apart
        tracks = self.mgr.update([d1, d2])
        assert len(tracks) == 2
