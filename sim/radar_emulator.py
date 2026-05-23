#!/usr/bin/env python3
"""
sim/radar_emulator.py
Simulates Acconeer XM125 pulsed coherent radar detections.

Physical model:
  - Radar cross-section (RCS) per drone model drives SNR.
  - Range gate: 0.3 – 20 m (XM125 practical limits).
  - Micro-Doppler spread derived from rotor-tip velocity.
  - Bearing angle from drone azimuth relative to node.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from artemis.core.types import RadarDetection

# Radar cross-section per model (m²)
_RCS_M2: dict[str, float] = {
    "DJI_Mini3":   0.005,
    "DJI_Mavic3":  0.010,
    "Autel_Evo2":  0.012,
    "FPV_Generic": 0.003,
    "unknown":     0.005,
}

# Rotor tip speed ≈ 0.3 * diameter_m * RPM / 60  (m/s)
# Micro-Doppler spread ≈ 2 * v_tip / lambda; approximated empirically.
_MICRO_DOPPLER_SPREAD: dict[str, float] = {
    "DJI_Mini3":   18.0,   # Hz spread at 77 GHz equivalent model
    "DJI_Mavic3":  22.0,
    "Autel_Evo2":  24.0,
    "FPV_Generic": 35.0,
    "unknown":     20.0,
}

_MAX_RANGE_M    = 20.0   # XM125 effective range
_MIN_RANGE_M    = 0.3
_TX_POWER_DB    = 10.0   # dBm (nominal XM125 output)
_THRESHOLD_SNR  = 8.0    # dB
_NOISE_FLOOR    = -90.0  # dBm


def _radar_snr(rcs: float, distance_m: float) -> float:
    """Simplified radar range equation → SNR in dB."""
    if distance_m <= 0:
        return 100.0
    # SNR ∝ RCS / d^4 (monostatic radar equation)
    signal = _TX_POWER_DB + 10 * math.log10(max(rcs, 1e-9)) - 40 * math.log10(distance_m)
    return signal - _NOISE_FLOOR


@dataclass
class RadarEmulatorState:
    drone_id:   str
    model:      str
    update_hz:  float = 20.0    # XM125 typical update rate
    range_noise_m: float = 0.05
    bearing_noise_deg: float = 2.0
    _next_update: float = field(default=0.0, repr=False)

    def sample(
        self,
        distance_m: float,
        bearing_deg: float,
        velocity_mps: float = 0.0,
    ) -> Optional[RadarDetection]:
        now = time.monotonic()
        if now < self._next_update:
            return None
        self._next_update = now + 1.0 / self.update_hz + random.gauss(0, 0.002)

        if not (_MIN_RANGE_M <= distance_m <= _MAX_RANGE_M):
            return None

        rcs = _RCS_M2.get(self.model, 0.005)
        snr = _radar_snr(rcs, distance_m)
        if snr < _THRESHOLD_SNR:
            return None

        noisy_range   = distance_m + random.gauss(0, self.range_noise_m)
        noisy_bearing = (bearing_deg + random.gauss(0, self.bearing_noise_deg)) % 360.0
        noisy_velocity = velocity_mps + random.gauss(0, 0.1)

        spread = _MICRO_DOPPLER_SPREAD.get(self.model, 20.0)
        noisy_spread = spread + random.gauss(0, spread * 0.05)

        return RadarDetection(
            range_m=round(max(noisy_range, _MIN_RANGE_M), 3),
            micro_doppler_spread=round(noisy_spread, 2),
            source=f"sim-radar-{self.drone_id}",
            timestamp=time.time(),
            velocity_mps=round(noisy_velocity, 2),
            bearing_deg=round(noisy_bearing, 2),
        )


def make_radar_emulator(drone_id: str, model: str) -> RadarEmulatorState:
    return RadarEmulatorState(drone_id=drone_id, model=model)
