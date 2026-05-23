"""
artemis/perception/rf/rtlsdr_listener.py
RTL-SDR hardware driver — streams RFDetection objects from a real dongle.

Hardware: Any RTL2832U-based SDR (NooElec NESDR, RTL-SDR Blog V4, etc.)
Frequency ranges: configured via RFSensorConfig.frequencies
Scan cycle: round-robin over each configured frequency, sample FFT, detect peaks.

Usage:
    driver = RTLSDRListener(node_id="node-01", cfg=rf_cfg)
    async for det in driver.stream():
        publisher.publish_rf(det)

Import guard:
    pyrtlsdr is optional; if not installed the driver raises DriverUnavailableError
    so the node daemon can skip it gracefully without crashing.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import AsyncGenerator, Optional

import numpy as np

from artemis.core.logging import get_logger
from artemis.core.types import DroneType, RFDetection, SensorLayer
from artemis.perception.base import DriverStatus, PerceptionDriver

log = get_logger("perception.rf")

# ---------------------------------------------------------------------------
# Optional hardware import with graceful fallback
# ---------------------------------------------------------------------------
try:
    from rtlsdr import RtlSdr

    _HAS_RTLSDR = True
except ImportError:
    _HAS_RTLSDR = False
    log.warning("pyrtlsdr not installed — RTLSDRListener will raise on start()")


class DriverUnavailableError(RuntimeError):
    """Raised when required hardware library is not installed."""


# ---------------------------------------------------------------------------
# FSPL helpers (identical physics to sim/rf_emulator.py)
# ---------------------------------------------------------------------------
_LIGHT_SPEED = 2.998e8  # m/s
_NOISE_FLOOR_DBM = -90.0


def _fspl_db(distance_m: float, frequency_hz: float) -> float:
    """Free-Space Path Loss in dB (positive = loss)."""
    if distance_m <= 0:
        return 0.0
    wl = _LIGHT_SPEED / frequency_hz
    return 10 * math.log10(max((4 * math.pi * distance_m / wl) ** 2, 1e-30))


def _power_to_range_m(
    power_dbm: float, frequency_hz: float, tx_power_dbm: float = 20.0
) -> Optional[float]:
    """
    Invert FSPL to estimate range from received power.
    Returns None if power is below noise floor.
    """
    if power_dbm <= _NOISE_FLOOR_DBM:
        return None
    loss_db = tx_power_dbm - power_dbm
    wl = _LIGHT_SPEED / frequency_hz
    # FSPL(d) = 20*log10(4*pi*d/wl)  →  d = wl/(4*pi) * 10^(loss/20)
    d = (wl / (4 * math.pi)) * (10 ** (loss_db / 20.0))
    return max(d, 0.1)


# ---------------------------------------------------------------------------
# Drone-type fingerprinting via burst interval + frequency
# ---------------------------------------------------------------------------

# Known burst intervals (seconds) for each drone model
_BURST_INTERVAL_MAP: dict[str, tuple[float, DroneType]] = {
    # (expected burst interval, drone type)
    "dji_ocusync": (0.020, DroneType.DJI_MAVIC),
    "dji_mini": (0.020, DroneType.DJI_MINI),
    "autel": (0.033, DroneType.AUTEL_EVO),
    "fpv_generic": (0.008, DroneType.FPV_GENERIC),
}

_FREQ_BANDS: dict[str, list[tuple[int, int]]] = {
    # band name → list of (low_hz, high_hz) pairs
    "2.4GHz": [(2_400_000_000, 2_480_000_000)],
    "5.8GHz": [(5_725_000_000, 5_875_000_000)],
    "900MHz": [(902_000_000, 928_000_000)],
}


def _classify_frequency(freq_hz: int) -> str:
    for band_name, ranges in _FREQ_BANDS.items():
        for lo, hi in ranges:
            if lo <= freq_hz <= hi:
                return band_name
    return "unknown"


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


class RTLSDRListener(PerceptionDriver):
    """
    Real-hardware RTL-SDR continuous scan driver.

    Scans the configured frequency list in a round-robin loop. For each
    frequency, it captures `fft_size` IQ samples, computes the power
    spectrum, and emits an RFDetection when a peak exceeds threshold_db.

    Key fix (per docs/artemis.md §2): the original stub was one-shot.
    This implementation uses a continuous ``while True`` loop.
    """

    def __init__(
        self,
        node_id: str,
        *,
        frequencies: list[int] | None = None,
        fft_size: int = 1024,
        threshold_db: float = -50.0,
        sample_rate: int = 2_400_000,
        bearing_deg: float | None = None,
    ) -> None:
        super().__init__(node_id)
        self._frequencies = frequencies or [2_437_000_000, 5_780_000_000, 915_000_000]
        self._fft_size = fft_size
        self._threshold_db = threshold_db
        self._sample_rate = sample_rate
        self._bearing_deg = bearing_deg  # fixed mount bearing (None if omni)
        self._sdr: Optional["RtlSdr"] = None  # type: ignore[name-defined]
        # Per-frequency last-detection timestamp for burst interval fingerprinting
        self._last_detect_ts: dict[int, float] = {}

    async def start(self) -> None:
        if not _HAS_RTLSDR:
            raise DriverUnavailableError(
                "pyrtlsdr is not installed. Run: pip install pyrtlsdr"
            )
        log.info("RTLSDRListener starting node=%s", self.node_id)

    async def stop(self) -> None:
        if self._sdr is not None:
            try:
                self._sdr.close()
            except Exception:  # noqa: BLE001
                pass
            self._sdr = None
        self.status = DriverStatus.STOPPED
        log.info("RTLSDRListener stopped node=%s", self.node_id)

    async def stream(self) -> AsyncGenerator[RFDetection, None]:  # type: ignore[override]
        """
        Continuous round-robin scan over configured frequencies.
        Yields RFDetection when peak power exceeds threshold_db.
        """
        if not _HAS_RTLSDR:
            raise DriverUnavailableError("pyrtlsdr is not installed. Cannot stream.")

        # Open SDR on main thread before entering async loop
        self._sdr = await asyncio.to_thread(self._open_sdr)
        self.status = DriverStatus.RUNNING
        log.info(
            "RTLSDRListener running node=%s freqs=%s",
            self.node_id,
            [f // 1_000_000 for f in self._frequencies],
        )

        try:
            while True:
                for freq in self._frequencies:
                    det = await asyncio.to_thread(self._scan_frequency, freq)
                    if det is not None:
                        yield det
                # Brief yield so other coroutines can run between scan cycles
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.status = DriverStatus.ERROR
            log.error("RTLSDRListener error node=%s: %s", self.node_id, exc)
            raise
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Blocking helpers (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _open_sdr(self) -> "RtlSdr":  # type: ignore[name-defined]
        sdr = RtlSdr()
        sdr.sample_rate = self._sample_rate
        sdr.gain = "auto"
        log.debug("SDR device opened: %s", sdr.get_device_serial_addresses())
        return sdr

    def _scan_frequency(self, freq_hz: int) -> RFDetection | None:
        """
        Tune to freq_hz, capture one FFT window, return detection or None.
        This is a blocking call — must be run in a thread.
        """
        assert self._sdr is not None  # noqa: S101
        try:
            self._sdr.center_freq = freq_hz
            samples = self._sdr.read_samples(self._fft_size)
        except Exception as exc:  # noqa: BLE001
            log.warning("SDR read error at %d MHz: %s", freq_hz // 1_000_000, exc)
            return None

        # Compute power spectrum (dBm referenced to 1 mW at 50 Ω)
        window = np.hanning(len(samples))
        fft_mag = np.abs(np.fft.fft(samples * window))
        # Avoid log(0) — guard with max(x, 1e-30)
        power_db = 10.0 * np.log10(np.maximum(fft_mag**2 / len(samples), 1e-30))

        peak_db = float(np.max(power_db))
        if peak_db < self._threshold_db:
            return None

        # Drone-type fingerprinting via burst interval timing
        now = time.time()
        drone_type, confidence = self._fingerprint(freq_hz, peak_db, now)
        self._last_detect_ts[freq_hz] = now

        return RFDetection(
            frequency=freq_hz,
            peak_power_db=peak_db,
            source=self.node_id,
            timestamp=now,
            layer=SensorLayer.RF,
            drone_type=drone_type,
            confidence=confidence,
            bearing_deg=self._bearing_deg,
        )

    def _fingerprint(
        self,
        freq_hz: int,
        peak_db: float,
        now: float,
    ) -> tuple[DroneType, float]:
        """
        Heuristic drone classification based on frequency band + burst interval.
        Returns (DroneType, confidence 0–1).
        """
        band = _classify_frequency(freq_hz)
        last_ts = self._last_detect_ts.get(freq_hz, 0.0)
        interval = now - last_ts if last_ts > 0 else -1.0

        # 5.8 GHz band — likely DJI (OcuSync) or Autel
        if band == "5.8GHz":
            if 0.015 <= interval <= 0.025:
                return DroneType.DJI_MAVIC, 0.75
            if 0.025 <= interval <= 0.040:
                return DroneType.AUTEL_EVO, 0.70
            return DroneType.UNKNOWN, 0.30

        # 2.4 GHz band — DJI Mini or FPV
        if band == "2.4GHz":
            if 0.015 <= interval <= 0.025:
                return DroneType.DJI_MINI, 0.72
            if interval < 0.012:
                return DroneType.FPV_GENERIC, 0.65
            return DroneType.UNKNOWN, 0.30

        # 900 MHz band — FPV long-range
        if band == "900MHz":
            return DroneType.FPV_GENERIC, 0.60

        return DroneType.UNKNOWN, 0.20
