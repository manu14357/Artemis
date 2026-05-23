"""
tests/unit/test_types.py
Unit tests for artemis.core.types — serialisation round-trips and enum guards.
"""
import time

import pytest

from artemis.core.types import (
    AcousticDetection,
    DroneType,
    NodeStatus,
    OpticalDetection,
    RadarDetection,
    RFDetection,
    SensorLayer,
    Threat,
    ThreatTier,
    Track,
    TrackStatus,
)


class TestRFDetection:
    def test_defaults(self):
        d = RFDetection(
            frequency=2437000000,
            peak_power_db=-48.5,
            source="node-01",
            timestamp=time.time(),
        )
        assert d.layer == SensorLayer.RF
        assert d.drone_type == DroneType.UNKNOWN
        assert d.confidence == 0.0
        assert d.bearing_deg is None

    def test_to_dict_contains_layer(self):
        d = RFDetection(frequency=915000000, peak_power_db=-55.0, source="n1", timestamp=1.0)
        import dataclasses
        raw = dataclasses.asdict(d)
        assert raw["layer"] == "rf"


class TestAcousticDetection:
    def test_layer_is_acoustic(self):
        d = AcousticDetection(confidence=0.8, bearing_deg=45.0, source="n1", timestamp=1.0)
        assert d.layer == SensorLayer.ACOUSTIC


class TestRadarDetection:
    def test_range_and_doppler(self):
        d = RadarDetection(
            range_m=5.5,
            micro_doppler_spread=22.0,
            source="n1",
            timestamp=1.0,
            velocity_mps=5.0,
            bearing_deg=90.0,
        )
        assert d.layer == SensorLayer.RADAR
        assert d.range_m == pytest.approx(5.5)


class TestOpticalDetection:
    def test_bbox_and_area(self):
        d = OpticalDetection(
            bbox=(10, 20, 60, 50),
            area=1500.0,
            velocity=(1.2, -0.5),
            source="n1",
            timestamp=1.0,
        )
        assert d.layer == SensorLayer.OPTICAL
        assert len(d.bbox) == 4


class TestTrack:
    def test_initial_status_tentative(self):
        t = Track(
            track_id="t-001",
            state=[0.0, 0.0, 50.0, 5.0, 0.0, 0.0],
        )
        assert t.status == TrackStatus.TENTATIVE
        assert t.hit_count == 0
        assert t.coast_frames == 0


class TestThreat:
    def test_to_dict_serialisable(self):
        import json
        threat = Threat(
            threat_id="thr-1",
            track_id="t-001",
            tier=ThreatTier.T3,
            x_m=100.0, y_m=200.0, z_m=80.0,
            vx_mps=5.0, vy_mps=3.0, vz_mps=0.0,
            sensor_layers=["rf", "radar"],
        )
        d = threat.to_dict()
        # Must be JSON-serialisable
        s = json.dumps(d)
        assert "tier" in s
        assert "sensor_layers" in s


class TestNodeStatus:
    def test_to_dict(self):
        ns = NodeStatus(
            node_id="node-01",
            lat=17.385,
            lon=78.487,
            alt_m=540.0,
            sensors_active=["rf", "acoustic"],
            last_heartbeat=time.time(),
            online=True,
        )
        d = ns.to_dict()
        assert d["node_id"] == "node-01"
        assert d["online"] is True
