"""
artemis/perception/calibration.py
Sensor health monitoring and auto-calibration for ARTEMIS nodes.

Features
--------
- Per-sensor health scoring (0–1) based on recent detection quality.
- Degradation detection: RF noise floor rise, acoustic SNR drop, optical FPS drop.
- Bearing offset calibration using known reference beacons or GPS satellites.
- Publishes NodeStatus with sensor health via the MQTT publisher.

Architecture
------------
    SensorHealthMonitor collects rolling statistics from sensor drivers.
    CalibrationManager manages bearing offsets for RF and acoustic sensors.
    Both are optional; the node daemon runs fine without them.
"""

from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

from artemis.core.logging import get_logger

log = get_logger("perception.calibration")

# ---------------------------------------------------------------------------
# Rolling stat window
# ---------------------------------------------------------------------------

_WINDOW = 60  # Keep last N samples per sensor


class _RollingStats:
    """Thread-safe rolling statistics over a fixed-size deque."""

    def __init__(self, maxlen: int = _WINDOW) -> None:
        self._data: Deque[float] = deque(maxlen=maxlen)

    def push(self, value: float) -> None:
        self._data.append(value)

    @property
    def mean(self) -> Optional[float]:
        if not self._data:
            return None
        return statistics.mean(self._data)

    @property
    def stdev(self) -> Optional[float]:
        if len(self._data) < 2:
            return None
        return statistics.stdev(self._data)

    @property
    def count(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        self._data.clear()


# ---------------------------------------------------------------------------
# Health report
# ---------------------------------------------------------------------------


@dataclass
class SensorHealth:
    """Per-sensor health snapshot."""

    layer: str
    health_score: float  # 0.0 (dead) – 1.0 (perfect)
    degraded: bool
    reason: str  # Human-readable reason if degraded
    noise_floor_db: Optional[float] = None  # RF only
    snr_db: Optional[float] = None          # Acoustic / radar
    fps: Optional[float] = None             # Optical only
    last_detection_age_s: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "health_score": round(self.health_score, 3),
            "degraded": self.degraded,
            "reason": self.reason,
            "noise_floor_db": self.noise_floor_db,
            "snr_db": self.snr_db,
            "fps": self.fps,
            "last_detection_age_s": (
                round(self.last_detection_age_s, 1)
                if self.last_detection_age_s is not None
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Per-sensor monitors
# ---------------------------------------------------------------------------


class RFHealthMonitor:
    """
    Monitors RTL-SDR health by tracking noise floor and detection rate.

    Degradation indicators:
    - Noise floor rising above nominal + 10 dB (interference / hardware fault)
    - No detections for > 30 s when the scan loop should be active
    """

    _NOMINAL_NOISE_FLOOR_DB = -90.0
    _NOISE_RISE_THRESHOLD_DB = 10.0

    def __init__(self) -> None:
        self._peak_powers = _RollingStats()
        self._last_detection_ts: Optional[float] = None

    def record(self, peak_power_db: float) -> None:
        self._peak_powers.push(peak_power_db)
        self._last_detection_ts = time.time()

    def health(self) -> SensorHealth:
        now = time.time()
        noise = self._peak_powers.mean
        age = (now - self._last_detection_ts) if self._last_detection_ts else None

        # Score components
        noise_score = 1.0
        if noise is not None:
            excess = noise - self._NOMINAL_NOISE_FLOOR_DB
            if excess > self._NOISE_RISE_THRESHOLD_DB:
                noise_score = max(0.0, 1.0 - (excess - self._NOISE_RISE_THRESHOLD_DB) / 20.0)

        activity_score = 1.0
        degraded = False
        reason = "OK"
        if age is not None and age > 30.0:
            activity_score = max(0.0, 1.0 - (age - 30.0) / 60.0)
            degraded = True
            reason = f"No detections for {age:.0f}s"
        elif noise is not None and noise_score < 0.7:
            degraded = True
            reason = f"Noise floor elevated ({noise:.1f} dBm)"

        return SensorHealth(
            layer="rf",
            health_score=round((noise_score + activity_score) / 2.0, 3),
            degraded=degraded,
            reason=reason,
            noise_floor_db=round(noise, 1) if noise is not None else None,
            last_detection_age_s=round(age, 1) if age is not None else None,
        )


class AcousticHealthMonitor:
    """
    Monitors acoustic sensor health via SNR and detection rate.

    Degradation indicators:
    - SNR dropping below 6 dB (wind noise, mic obstruction)
    - Classification confidence < 0.3 sustained
    """

    _MIN_HEALTHY_SNR_DB = 6.0

    def __init__(self) -> None:
        self._snr_vals = _RollingStats()
        self._confidence_vals = _RollingStats()
        self._last_detection_ts: Optional[float] = None

    def record(self, confidence: float, snr_db: Optional[float] = None) -> None:
        self._confidence_vals.push(confidence)
        if snr_db is not None:
            self._snr_vals.push(snr_db)
        self._last_detection_ts = time.time()

    def health(self) -> SensorHealth:
        now = time.time()
        snr = self._snr_vals.mean
        conf = self._confidence_vals.mean
        age = (now - self._last_detection_ts) if self._last_detection_ts else None

        snr_score = 1.0
        if snr is not None and snr < self._MIN_HEALTHY_SNR_DB:
            snr_score = max(0.0, snr / self._MIN_HEALTHY_SNR_DB)

        conf_score = conf if conf is not None else 0.5

        degraded = snr_score < 0.5 or conf_score < 0.3
        reason = "OK"
        if snr is not None and snr < self._MIN_HEALTHY_SNR_DB:
            reason = f"Low SNR ({snr:.1f} dB — check mic array / wind)"
        elif conf is not None and conf < 0.3:
            reason = "Low classification confidence — retrain model?"

        return SensorHealth(
            layer="acoustic",
            health_score=round((snr_score + conf_score) / 2.0, 3),
            degraded=degraded,
            reason=reason,
            snr_db=round(snr, 1) if snr is not None else None,
            last_detection_age_s=round(age, 1) if age is not None else None,
        )


class RadarHealthMonitor:
    """
    Monitors radar (XM125/IWR6843) health via SNR and frame rate.

    Degradation indicators:
    - SNR < 5 dB sustained (sensor obstruction, hardware fault)
    - No frames received for > 1 s
    """

    def __init__(self) -> None:
        self._snr_vals = _RollingStats()
        self._last_detection_ts: Optional[float] = None

    def record(self, micro_doppler_spread: float) -> None:
        # Use Doppler spread as SNR proxy; wider spread = stronger signal
        self._snr_vals.push(micro_doppler_spread)
        self._last_detection_ts = time.time()

    def health(self) -> SensorHealth:
        now = time.time()
        snr = self._snr_vals.mean
        age = (now - self._last_detection_ts) if self._last_detection_ts else None

        snr_score = 1.0
        if snr is not None and snr < 0.01:
            snr_score = 0.3  # Very weak signal

        age_score = 1.0
        degraded = False
        reason = "OK"
        if age is not None and age > 1.0:
            age_score = max(0.0, 1.0 - (age - 1.0) / 5.0)
            if age > 2.0:
                degraded = True
                reason = f"No radar frames for {age:.1f}s — check XM125 connection"

        return SensorHealth(
            layer="radar",
            health_score=round((snr_score + age_score) / 2.0, 3),
            degraded=degraded,
            reason=reason,
            snr_db=round(snr * 100.0, 1) if snr is not None else None,
            last_detection_age_s=round(age, 1) if age is not None else None,
        )


class OpticalHealthMonitor:
    """
    Monitors camera health via effective frame rate and detection frequency.

    Degradation indicators:
    - Effective FPS < 15 (CPU overload or camera disconnect)
    - No detections for > 5 s in daytime (lens dirt, obstruction)
    """

    _TARGET_FPS = 30.0

    def __init__(self) -> None:
        self._frame_timestamps: Deque[float] = deque(maxlen=90)  # 3 s at 30fps
        self._last_detection_ts: Optional[float] = None

    def record_frame(self) -> None:
        self._frame_timestamps.append(time.time())

    def record_detection(self) -> None:
        self._last_detection_ts = time.time()

    def health(self) -> SensorHealth:
        now = time.time()
        fps: Optional[float] = None
        if len(self._frame_timestamps) >= 2:
            span = self._frame_timestamps[-1] - self._frame_timestamps[0]
            if span > 0:
                fps = (len(self._frame_timestamps) - 1) / span

        fps_score = 1.0
        if fps is not None:
            fps_score = min(1.0, fps / self._TARGET_FPS)

        age = (now - self._last_detection_ts) if self._last_detection_ts else None
        degraded = False
        reason = "OK"
        if fps is not None and fps < 15.0:
            degraded = True
            reason = f"Low FPS ({fps:.1f}) — CPU overload or camera disconnect"
        elif age is not None and age > 5.0:
            reason = f"No detections for {age:.0f}s (may be normal if no targets)"

        return SensorHealth(
            layer="optical",
            health_score=round(fps_score, 3),
            degraded=degraded,
            reason=reason,
            fps=round(fps, 1) if fps is not None else None,
            last_detection_age_s=round(age, 1) if age is not None else None,
        )


# ---------------------------------------------------------------------------
# Bearing offset calibration
# ---------------------------------------------------------------------------


@dataclass
class BearingCalibration:
    """
    Bearing offset correction for a sensor.

    offset_deg is added to all raw bearing measurements.
    Positive = clockwise correction.
    """

    layer: str
    offset_deg: float = 0.0
    calibrated_at: Optional[float] = None
    reference_type: str = "unknown"   # "gps_satellite" | "known_beacon" | "manual"

    def correct(self, raw_bearing_deg: float) -> float:
        """Apply offset correction, wrapping to [0, 360)."""
        return (raw_bearing_deg + self.offset_deg) % 360.0

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "offset_deg": round(self.offset_deg, 2),
            "calibrated_at": self.calibrated_at,
            "reference_type": self.reference_type,
        }


class CalibrationManager:
    """
    Manages bearing offset calibrations for all sensor layers.

    Auto-calibration from a known beacon:
        manager.calibrate_from_beacon(layer="rf", known_bearing_deg=45.0, measured_bearing_deg=47.3)
        # → saves offset of -2.3° for RF

    Manual override:
        manager.set_offset(layer="acoustic", offset_deg=5.0)
    """

    def __init__(self) -> None:
        self._calibrations: dict[str, BearingCalibration] = {
            layer: BearingCalibration(layer=layer)
            for layer in ("rf", "acoustic", "radar", "optical")
        }

    def calibrate_from_beacon(
        self,
        layer: str,
        known_bearing_deg: float,
        measured_bearing_deg: float,
        reference_type: str = "known_beacon",
    ) -> BearingCalibration:
        """
        Compute and store bearing offset from a known reference measurement.

        Parameters
        ----------
        layer : sensor layer name
        known_bearing_deg : true bearing to the reference target
        measured_bearing_deg : bearing reported by the sensor
        """
        offset = known_bearing_deg - measured_bearing_deg
        # Wrap to (-180, 180]
        while offset > 180:
            offset -= 360
        while offset <= -180:
            offset += 360

        cal = BearingCalibration(
            layer=layer,
            offset_deg=offset,
            calibrated_at=time.time(),
            reference_type=reference_type,
        )
        self._calibrations[layer] = cal
        log.info(
            "Bearing calibration: layer=%s offset=%.2f° reference=%s",
            layer,
            offset,
            reference_type,
        )
        return cal

    def set_offset(self, layer: str, offset_deg: float) -> None:
        """Manually set bearing offset for a layer."""
        self._calibrations[layer] = BearingCalibration(
            layer=layer,
            offset_deg=offset_deg,
            calibrated_at=time.time(),
            reference_type="manual",
        )
        log.info("Manual bearing offset: layer=%s offset=%.2f°", layer, offset_deg)

    def correct_bearing(self, layer: str, raw_bearing_deg: float) -> float:
        """Apply calibration offset to a raw bearing measurement."""
        cal = self._calibrations.get(layer)
        if cal is None:
            return raw_bearing_deg
        return cal.correct(raw_bearing_deg)

    def get_calibration(self, layer: str) -> Optional[BearingCalibration]:
        return self._calibrations.get(layer)

    def all_calibrations(self) -> list[dict]:
        return [c.to_dict() for c in self._calibrations.values()]


# ---------------------------------------------------------------------------
# Unified sensor health monitor
# ---------------------------------------------------------------------------


class SensorHealthMonitor:
    """
    Aggregates health information for all four sensor layers.

    Usage
    -----
        monitor = SensorHealthMonitor()

        # Call from sensor drivers as data arrives:
        monitor.record_rf(peak_power_db=-55.0)
        monitor.record_acoustic(confidence=0.82, snr_db=12.0)
        monitor.record_radar(micro_doppler_spread=0.15)
        monitor.record_optical_frame()

        # Poll health any time:
        report = monitor.get_health_report()
    """

    def __init__(self) -> None:
        self._rf = RFHealthMonitor()
        self._acoustic = AcousticHealthMonitor()
        self._radar = RadarHealthMonitor()
        self._optical = OpticalHealthMonitor()
        self._calibration = CalibrationManager()

    # -- Recording helpers --

    def record_rf(self, peak_power_db: float) -> None:
        self._rf.record(peak_power_db)

    def record_acoustic(self, confidence: float, snr_db: Optional[float] = None) -> None:
        self._acoustic.record(confidence, snr_db)

    def record_radar(self, micro_doppler_spread: float) -> None:
        self._radar.record(micro_doppler_spread)

    def record_optical_frame(self) -> None:
        self._optical.record_frame()

    def record_optical_detection(self) -> None:
        self._optical.record_detection()

    # -- Health queries --

    def get_health_report(self) -> list[SensorHealth]:
        return [
            self._rf.health(),
            self._acoustic.health(),
            self._radar.health(),
            self._optical.health(),
        ]

    def get_health_dict(self) -> dict:
        return {
            h.layer: h.to_dict()
            for h in self.get_health_report()
        }

    # -- Calibration --

    @property
    def calibration(self) -> CalibrationManager:
        return self._calibration

    def overall_health_score(self) -> float:
        """Weighted average health across all four layers."""
        report = self.get_health_report()
        return sum(h.health_score for h in report) / len(report)
