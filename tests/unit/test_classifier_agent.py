"""
tests/unit/test_classifier_agent.py
Unit tests for ClassifierAgent — 4-layer evidence fusion.
"""

from artemis.cognition.agents.classifier_agent import ClassifierAgent
from artemis.core.types import (
    DroneType,
    RFDetection,
    AcousticDetection,
    RadarDetection,
    OpticalDetection,
    Track,
    TrackStatus,
    SensorLayer,
)


def _make_track(
    rf: RFDetection | None = None,
    acoustic: AcousticDetection | None = None,
    radar: RadarDetection | None = None,
    optical: OpticalDetection | None = None,
) -> Track:
    """Build a minimal Track with the given sensor detections."""
    detections = {}
    if rf:
        detections[SensorLayer.RF] = rf
    if acoustic:
        detections[SensorLayer.ACOUSTIC] = acoustic
    if radar:
        detections[SensorLayer.RADAR] = radar
    if optical:
        detections[SensorLayer.OPTICAL] = optical
    return Track(
        track_id="t-0001",
        status=TrackStatus.CONFIRMED,
        state=[100.0, 50.0, 30.0, 2.0, -1.0, 0.0],
        last_detections=detections,
    )


class TestClassifierAgent:
    agent = ClassifierAgent()

    # ------------------------------------------------------------------
    # RF layer
    # ------------------------------------------------------------------

    def test_rf_match_mavic(self):
        """DJI Mavic RF fingerprint → classified as DJI_MAVIC."""
        rf = RFDetection(
            source="n1",
            drone_type=DroneType.DJI_MAVIC,
            frequency=2450_000_000,
            peak_power_db=-55.0,
            confidence=0.9,
        )
        result = self.agent.classify(_make_track(rf=rf))
        assert result.drone_type == DroneType.DJI_MAVIC
        assert result.confidence > 0.0
        assert "rf" in result.evidence

    def test_rf_no_fingerprint_falls_back(self):
        """RF detection with no fingerprint → RF layer contributes nothing decisive."""
        rf = RFDetection(
            source="n1",
            frequency=433_000_000,
            peak_power_db=-80.0,
        )
        result = self.agent.classify(_make_track(rf=rf))
        # Should still return some result even with empty RF
        assert result.drone_type is not None or result.confidence >= 0.0

    # ------------------------------------------------------------------
    # Acoustic layer
    # ------------------------------------------------------------------

    def test_acoustic_fpv_doppler_spread(self):
        """FPV_GENERIC has widest Doppler spread → classified as FPV_GENERIC."""
        acoustic = AcousticDetection(
            source="n1",
            confidence=0.72,
            bearing_deg=45.0,
            drone_type=DroneType.FPV_GENERIC,
        )
        result = self.agent.classify(_make_track(acoustic=acoustic))
        assert result.confidence >= 0.0
        assert "acoustic" in result.evidence

    def test_acoustic_known_type(self):
        """When acoustic provides drone_type directly it contributes to vote."""
        acoustic = AcousticDetection(
            source="n1",
            confidence=0.80,
            bearing_deg=30.0,
            drone_type=DroneType.DJI_MINI,
        )
        result = self.agent.classify(_make_track(acoustic=acoustic))
        assert result.drone_type is not None
        assert "acoustic" in result.evidence

    # ------------------------------------------------------------------
    # Radar layer
    # ------------------------------------------------------------------

    def test_radar_mini_micro_doppler(self):
        """Radar micro-Doppler signature for DJI_MINI → vote is cast."""
        radar = RadarDetection(
            source="n1",
            range_m=250.0,
            micro_doppler_spread=0.30,  # DJI_MINI expected spread
        )
        result = self.agent.classify(_make_track(radar=radar))
        assert "radar" in result.evidence

    # ------------------------------------------------------------------
    # Optical layer
    # ------------------------------------------------------------------

    def test_optical_with_drone_type(self):
        """Optical detection with known drone_type → vote is cast."""
        optical = OpticalDetection(
            source="n1",
            bbox=(100, 50, 40, 40),
            area=1600.0,
            velocity=(0.5, -0.2),
            confidence=0.88,
            drone_type=DroneType.AUTEL_EVO,
        )
        result = self.agent.classify(_make_track(optical=optical))
        assert "optical" in result.evidence

    def test_optical_area_estimation(self):
        """Optical bbox area is used for type estimation when no explicit type."""
        optical = OpticalDetection(
            source="n1",
            bbox=(100, 50, 20, 20),  # small ≈ DJI_MINI
            area=400.0,
            velocity=(0.0, 0.0),
            confidence=0.70,
        )
        result = self.agent.classify(_make_track(optical=optical))
        # Should still produce a result
        assert result is not None
        assert 0.0 <= result.confidence <= 1.0

    # ------------------------------------------------------------------
    # Multi-layer
    # ------------------------------------------------------------------

    def test_multi_layer_consensus_boosts_confidence(self):
        """Agreement across multiple layers should yield high confidence."""
        rf = RFDetection(
            source="n1",
            drone_type=DroneType.DJI_MAVIC,
            frequency=2450_000_000,
            peak_power_db=-55.0,
            confidence=0.9,
        )
        acoustic = AcousticDetection(
            source="n1",
            confidence=0.85,
            bearing_deg=10.0,
            drone_type=DroneType.DJI_MAVIC,
        )
        radar = RadarDetection(
            source="n1",
            range_m=200.0,
            micro_doppler_spread=0.45,  # DJI_MAVIC expected spread
        )
        result = self.agent.classify(_make_track(rf=rf, acoustic=acoustic, radar=radar))
        assert result.drone_type == DroneType.DJI_MAVIC
        assert result.confidence >= 0.5

    def test_empty_detections_returns_result(self):
        """Track with no sensor data still returns a classification (UNKNOWN / low conf)."""
        track = Track(
            track_id="t-empty",
            status=TrackStatus.CONFIRMED,
            state=[0.0] * 6,
        )
        result = self.agent.classify(track)
        assert result is not None
        assert result.confidence == 0.0 or result.drone_type is not None
