#!/usr/bin/env python3
"""
sim/acoustic_emulator.py
Acoustic drone-detection emulator.

Models:
  - Rotor-noise SNR decays with distance (inverse square law + atmospheric absorption).
  - Bearing angle derived from drone azimuth relative to node position.
  - Range available when the drone is within max_range_m.
  - Confidence based on SNR vs. detection threshold.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from artemis.core.types import AcousticDetection, DroneType

# Reference SNR at 1 m (dB) per drone size category
_REF_SNR_1M: dict[str, float] = {
    "DJI_Mini3":   50.0,
    "DJI_Mavic3":  55.0,
    "Autel_Evo2":  55.0,
    "FPV_Generic": 60.0,
    "unknown":     50.0,
}

_MAX_RANGE_M = 200.0          # Beyond this, acoustic SNR too low for detection
_ATMOS_ABSORB_DB_PER_M = 0.001  # ~1 dB per km atmospheric absorption at 2 kHz

_MODEL_TO_DRONE_TYPE: dict[str, DroneType] = {
    "DJI_Mini3":   DroneType.DJI_MINI,
    "DJI_Mavic3":  DroneType.DJI_MAVIC,
    "Autel_Evo2":  DroneType.AUTEL,
    "FPV_Generic": DroneType.FPV,
}


def _snr_at_range(model: str, distance_m: float) -> float:
    """Compute received acoustic SNR (dB) at a given distance."""
    ref = _REF_SNR_1M.get(model, 50.0)
    if distance_m <= 0:
        return ref
    # Inverse square: 20*log10(d) drop from reference 1 m
    geometric_loss = 20.0 * math.log10(distance_m)
    atmos_loss = distance_m * _ATMOS_ABSORB_DB_PER_M
    return ref - geometric_loss - atmos_loss


@dataclass
class AcousticEmulatorState:
    """Per-drone acoustic emulator state."""
    drone_id:        str
    model:           str
    sample_rate_hz:  float = 16000.0    # controls detection periodicity
    threshold_snr:   float = 5.0        # min SNR to declare a detection
    noise_std_deg:   float = 5.0        # bearing angle noise (degrees)
    _next_sample:    float = field(default=0.0, repr=False)

    def sample(
        self,
        distance_m: float,
        bearing_deg: float,
    ) -> Optional[AcousticDetection]:
        """
        Generate an AcousticDetection given drone range/bearing from node.

        Uses window-based sampling: one detection per 500 ms window.
        """
        now = time.monotonic()
        window_s = 0.5   # 500 ms STFT window
        if now < self._next_sample:
            return None
        self._next_sample = now + window_s + random.uniform(-0.05, 0.05)

        if distance_m > _MAX_RANGE_M:
            return None

        snr = _snr_at_range(self.model, distance_m)
        if snr < self.threshold_snr:
            return None

        confidence = min(1.0, (snr - self.threshold_snr) / 20.0)
        noisy_bearing = bearing_deg + random.gauss(0, self.noise_std_deg)
        noisy_bearing = noisy_bearing % 360.0

        range_m = distance_m + random.gauss(0, distance_m * 0.05) if distance_m < 150.0 else None

        drone_type = _MODEL_TO_DRONE_TYPE.get(self.model, DroneType.UNKNOWN)

        return AcousticDetection(
            confidence=round(confidence, 3),
            bearing_deg=round(noisy_bearing, 2),
            source=f"sim-acoustic-{self.drone_id}",
            timestamp=time.time(),
            drone_type=drone_type,
            range_m=round(range_m, 1) if range_m else None,
        )


def make_acoustic_emulator(drone_id: str, model: str) -> AcousticEmulatorState:
    return AcousticEmulatorState(drone_id=drone_id, model=model)
