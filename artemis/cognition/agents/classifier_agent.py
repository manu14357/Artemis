"""
artemis/cognition/agents/classifier_agent.py
Evidence-fusion drone-type classification agent.

Combines signals from all available sensor layers (RF, acoustic, radar,
optical) into a single DroneType estimate using a weighted-vote scheme.
Each layer casts a vote for a DroneType with a weight proportional to
its reliability and the detection's own confidence.

The overall confidence returned is the winning vote's share of total weight:
    confidence = votes[best] / sum(votes.values())

This is a fully local, rule-based classifier — no ML model or network
call is required.  It completes in < 1 ms for typical detection sets.

Timeout: 50 ms (hub_default.yaml cognition.classifier_timeout_ms)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from artemis.core.logging import get_logger
from artemis.core.types import (
    AcousticDetection,
    DroneType,
    OpticalDetection,
    RadarDetection,
    RFDetection,
    SensorLayer,
    Track,
)

log = get_logger("cognition.classifier")


# ---------------------------------------------------------------------------
# Per-drone-type priors from characterisation measurements
# ---------------------------------------------------------------------------

# XM125 micro-Doppler spread (m/s std-dev of Doppler fan) per drone type.
# Larger rotors → lower spread; FPV high-RPM motors → higher spread.
_DOPPLER_SPREAD: dict[DroneType, float] = {
    DroneType.DJI_MAVIC: 0.45,
    DroneType.DJI_MINI: 0.30,
    DroneType.AUTEL_EVO: 0.45,
    DroneType.FPV_GENERIC: 0.70,
    DroneType.UNKNOWN: 0.40,
}

# Optical: expected pixel-area range at ~100 m range for an 8 MP 1/2.3" sensor.
_OPTICAL_AREA_RANGES: dict[DroneType, tuple[float, float]] = {
    DroneType.DJI_MAVIC: (300.0, 2000.0),
    DroneType.DJI_MINI: (80.0, 600.0),
    DroneType.AUTEL_EVO: (300.0, 2000.0),
    DroneType.FPV_GENERIC: (60.0, 500.0),
}

# Vote weights per layer — layers with richer features get higher weight.
_LAYER_WEIGHT: dict[SensorLayer, float] = {
    SensorLayer.RF: 0.35,
    SensorLayer.ACOUSTIC: 0.25,
    SensorLayer.RADAR: 0.25,
    SensorLayer.OPTICAL: 0.15,
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    """Output of ClassifierAgent.classify()."""

    drone_type: DroneType
    confidence: float  # 0–1 agreement ratio across layers
    evidence: dict[str, str]  # human-readable per-layer evidence strings


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ClassifierAgent:
    """
    Evidence-fusion drone type classifier.

    Call ``classify(track)`` to obtain a ``ClassificationResult``.
    The agent is stateless and safe to call from multiple threads.

    Parameters
    ----------
    confidence_threshold : float
        Minimum confidence for the result to be considered reliable.
        The caller may use this to decide whether to update track.drone_type.
    """

    def __init__(self, confidence_threshold: float = 0.7) -> None:
        self._threshold = confidence_threshold

    def classify(self, track: Track) -> ClassificationResult:
        """
        Classify a track using evidence from all available sensor layers.

        Parameters
        ----------
        track : Track — must have ``last_detections`` populated

        Returns
        -------
        ClassificationResult
        """
        votes: dict[DroneType, float] = {}
        evidence: dict[str, str] = {}

        for layer, detection in track.last_detections.items():
            dtype, weight, note = self._vote_from_layer(detection)
            if dtype is not None and weight > 0:
                votes[dtype] = votes.get(dtype, 0.0) + weight
                evidence[str(layer.value if hasattr(layer, "value") else layer)] = note

        if not votes:
            return ClassificationResult(
                drone_type=DroneType.UNKNOWN,
                confidence=0.0,
                evidence={},
            )

        total_weight = sum(votes.values())
        best = max(votes, key=lambda k: votes[k])
        confidence = round(votes[best] / total_weight, 4) if total_weight > 0 else 0.0

        log.debug(
            "track=%s classified=%s conf=%.2f votes=%s",
            track.track_id,
            best.value,
            confidence,
            {k.value: round(v, 3) for k, v in votes.items()},
        )

        return ClassificationResult(
            drone_type=best,
            confidence=confidence,
            evidence=evidence,
        )

    # ------------------------------------------------------------------
    # Per-layer vote helpers
    # ------------------------------------------------------------------

    def _vote_from_layer(
        self,
        detection,
    ) -> tuple[Optional[DroneType], float, str]:
        """Return (drone_type, weight, evidence_note) for one layer detection."""
        if isinstance(detection, RFDetection):
            return self._vote_rf(detection)
        if isinstance(detection, AcousticDetection):
            return self._vote_acoustic(detection)
        if isinstance(detection, RadarDetection):
            return self._vote_radar(detection)
        if isinstance(detection, OpticalDetection):
            return self._vote_optical(detection)
        return None, 0.0, ""

    def _vote_rf(self, det: RFDetection) -> tuple[Optional[DroneType], float, str]:
        if det.drone_type == DroneType.UNKNOWN or det.confidence < 0.05:
            note = "RF: no fingerprint match"
            return DroneType.UNKNOWN, _LAYER_WEIGHT[SensorLayer.RF] * 0.3, note
        note = f"RF: {det.drone_type.value} @ {det.confidence:.0%} conf"
        return det.drone_type, _LAYER_WEIGHT[SensorLayer.RF] * det.confidence, note

    def _vote_acoustic(
        self, det: AcousticDetection
    ) -> tuple[Optional[DroneType], float, str]:
        if det.drone_type == DroneType.UNKNOWN or det.confidence < 0.05:
            note = "Acoustic: no match"
            return DroneType.UNKNOWN, _LAYER_WEIGHT[SensorLayer.ACOUSTIC] * 0.3, note
        note = f"Acoustic: {det.drone_type.value} @ {det.confidence:.0%} conf"
        return (
            det.drone_type,
            _LAYER_WEIGHT[SensorLayer.ACOUSTIC] * det.confidence,
            note,
        )

    def _vote_radar(
        self, det: RadarDetection
    ) -> tuple[Optional[DroneType], float, str]:
        spread = det.micro_doppler_spread
        best_type = DroneType.UNKNOWN
        best_delta = math.inf
        for dtype, expected in _DOPPLER_SPREAD.items():
            if dtype == DroneType.UNKNOWN:
                continue
            delta = abs(spread - expected)
            if delta < best_delta:
                best_delta = delta
                best_type = dtype
        # Map delta → confidence: 0 delta → 1.0; 0.4+ delta → ~0
        conf = max(0.0, 1.0 - best_delta / 0.4)
        note = f"Radar: mDoppler={spread:.2f} → {best_type.value} (Δ={best_delta:.2f})"
        return best_type, _LAYER_WEIGHT[SensorLayer.RADAR] * conf, note

    def _vote_optical(
        self, det: OpticalDetection
    ) -> tuple[Optional[DroneType], float, str]:
        if det.drone_type != DroneType.UNKNOWN and det.confidence >= 0.05:
            note = f"Optical: {det.drone_type.value} @ {det.confidence:.0%} conf"
            return (
                det.drone_type,
                _LAYER_WEIGHT[SensorLayer.OPTICAL] * det.confidence,
                note,
            )
        # Area-based fallback
        area = det.area
        for dtype, (lo, hi) in _OPTICAL_AREA_RANGES.items():
            if lo <= area <= hi:
                note = f"Optical: area={area:.0f}px² → {dtype.value}"
                return dtype, _LAYER_WEIGHT[SensorLayer.OPTICAL] * 0.5, note
        return (
            DroneType.UNKNOWN,
            _LAYER_WEIGHT[SensorLayer.OPTICAL] * 0.1,
            f"Optical: area={area:.0f}px² out-of-range",
        )
