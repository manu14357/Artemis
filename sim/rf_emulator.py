#!/usr/bin/env python3
"""
sim/rf_emulator.py
RF emission simulator — models Free-Space Path Loss (FSPL) and per-brand
burst timing to generate realistic RFDetection objects.

Supported models (matched to scenario YAML "model" field):
  DJI_Mini3   — 2.4 GHz / 5.8 GHz OcuSync 3.0
  DJI_Mavic3  — 2.4 GHz / 5.8 GHz OcuSync 3.0
  Autel_Evo2  — 5.8 GHz
  FPV_Generic — 915 MHz or 5.8 GHz
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from artemis.core.types import DroneType, RFDetection

# ---------------------------------------------------------------------------
# FSPL: received_power = transmitted_power - FSPL(d, f)
# ---------------------------------------------------------------------------
_LIGHT_SPEED = 2.998e8  # m/s


def free_space_path_loss_db(distance_m: float, frequency_hz: float) -> float:
    """Return FSPL in dB (always positive — represents loss)."""
    if distance_m <= 0:
        return 0.0
    wavelength = _LIGHT_SPEED / frequency_hz
    fspl = (4 * math.pi * distance_m / wavelength) ** 2
    return 10 * math.log10(max(fspl, 1e-12))


# Transmit power per model (dBm)
_TX_POWER_DBM: dict[str, float] = {
    "DJI_Mini3":   20.0,
    "DJI_Mavic3":  23.0,
    "Autel_Evo2":  20.0,
    "FPV_Generic": 27.0,
    "unknown":     20.0,
}

# Burst interval per model (seconds between RF bursts)
_BURST_INTERVAL_S: dict[str, float] = {
    "DJI_Mini3":   0.02,
    "DJI_Mavic3":  0.02,
    "Autel_Evo2":  0.033,
    "FPV_Generic": 0.008,
    "unknown":     0.05,
}

_MODEL_TO_DRONE_TYPE: dict[str, DroneType] = {
    "DJI_Mini3":   DroneType.DJI_MINI,
    "DJI_Mavic3":  DroneType.DJI_MAVIC,
    "Autel_Evo2":  DroneType.AUTEL,
    "FPV_Generic": DroneType.FPV,
}


@dataclass
class RFEmulatorState:
    """Per-drone RF emulator state (updated each physics tick)."""
    drone_id:     str
    model:        str
    frequency:    int       # Hz
    tx_power_dbm: float
    _next_burst:  float = field(default=0.0, repr=False)

    def sample(
        self,
        distance_m: float,
        bearing_deg: Optional[float],
        threshold_db: float = -80.0,
        noise_std_db: float = 2.0,
    ) -> Optional[RFDetection]:
        """Generate an RFDetection if a burst occurs at this moment."""
        now = time.monotonic()
        if now < self._next_burst:
            return None

        burst_interval = _BURST_INTERVAL_S.get(self.model, 0.05)
        self._next_burst = now + burst_interval + random.gauss(0, burst_interval * 0.05)

        loss_db = free_space_path_loss_db(distance_m, self.frequency)
        rx_power = self.tx_power_dbm - loss_db + random.gauss(0, noise_std_db)

        if rx_power < threshold_db:
            return None

        drone_type = _MODEL_TO_DRONE_TYPE.get(self.model, DroneType.UNKNOWN)
        confidence = min(1.0, (rx_power - threshold_db) / 30.0)

        return RFDetection(
            frequency=self.frequency,
            peak_power_db=round(rx_power, 2),
            source=f"sim-rf-{self.drone_id}",
            timestamp=time.time(),
            drone_type=drone_type,
            confidence=round(confidence, 3),
            bearing_deg=bearing_deg,
        )


def make_rf_emulator(drone_id: str, model: str, frequency: int) -> RFEmulatorState:
    """Construct an RFEmulatorState for a simulated drone."""
    return RFEmulatorState(
        drone_id=drone_id,
        model=model,
        frequency=frequency,
        tx_power_dbm=_TX_POWER_DBM.get(model, 20.0),
    )
