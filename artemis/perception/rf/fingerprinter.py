"""
artemis/perception/rf/fingerprinter.py
Protocol-specific RF fingerprinting for drone detection.

Identifies drone communication protocols from raw IQ samples:
- DJI OcuSync / Lightbridge (2.4/5.8 GHz)
- DJI Mini (Enhanced WiFi)
- Autel (proprietary)
- FPV: ELRS, Crossfire, ExpressLRS, Ghost
- Analog FPV (5.8 GHz analog video)
- WiFi-based drones (Parrot, generic)
- LTE/4G/5G drones

Uses spectral correlation, burst timing, and modulation recognition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from artemis.core.logging import get_logger
from artemis.core.types import DroneType

log = get_logger("perception.rf.fingerprinter")


class Protocol(Enum):
    """Known drone RF protocols."""

    UNKNOWN = "unknown"
    DJI_OCUSYNC = "dji_ocusync"          # 20 ms burst, OFDM, 2.4/5.8 GHz
    DJI_LIGHTBRIDGE = "dji_lightbridge"  # 10 ms burst, OFDM, 2.4 GHz
    DJI_MINI_WIFI = "dji_mini_wifi"      # WiFi-based, 2.4 GHz
    AUTEL = "autel"                      # 33 ms burst, 2.4/5.8 GHz
    ELRS = "elrs"                        # LoRa-based, 868/915 MHz, 2.4 GHz
    CROSSFIRE = "crossfire"              # 900 MHz, frequency hopping
    EXPRESS_LRS = "expresslrs"           # 2.4 GHz, LoRa-based
    GHOST = "ghost"                      # 2.4 GHz, proprietary
    ANALOG_FPV = "analog_fpv"            # 5.8 GHz analog video (no bursts)
    WIFI_DRONE = "wifi_drone"            # Standard 802.11, 2.4/5 GHz
    LTE_DRONE = "lte_drone"              # Cellular, licensed bands


@dataclass
class FingerprintResult:
    """Result of protocol fingerprinting."""

    protocol: Protocol
    drone_type: DroneType
    confidence: float  # 0-1
    evidence: dict  # human-readable evidence


# ---------------------------------------------------------------------------
# Protocol signatures (burst interval, bandwidth, modulation hints)
# ---------------------------------------------------------------------------

_PROTOCOL_SIGNATURES: dict[Protocol, dict] = {
    Protocol.DJI_OCUSYNC: {
        "burst_interval_ms": (18, 22),      # ~20 ms
        "bandwidth_mhz": (10, 20),
        "freq_bands": ["2.4GHz", "5.8GHz"],
        "modulation": "OFDM",
        "drone_type": DroneType.DJI_MAVIC,
    },
    Protocol.DJI_LIGHTBRIDGE: {
        "burst_interval_ms": (8, 12),       # ~10 ms
        "bandwidth_mhz": (10, 20),
        "freq_bands": ["2.4GHz"],
        "modulation": "OFDM",
        "drone_type": DroneType.DJI_MAVIC,
    },
    Protocol.DJI_MINI_WIFI: {
        "burst_interval_ms": (18, 22),
        "bandwidth_mhz": (20, 40),
        "freq_bands": ["2.4GHz"],
        "modulation": "802.11n/ac",
        "drone_type": DroneType.DJI_MINI,
    },
    Protocol.AUTEL: {
        "burst_interval_ms": (30, 38),      # ~33 ms
        "bandwidth_mhz": (10, 20),
        "freq_bands": ["2.4GHz", "5.8GHz"],
        "modulation": "OFDM",
        "drone_type": DroneType.AUTEL_EVO,
    },
    Protocol.ELRS: {
        "burst_interval_ms": (10, 50),      # Variable, LoRa
        "bandwidth_mhz": (0.1, 1.0),        # Very narrow (LoRa)
        "freq_bands": ["900MHz", "2.4GHz"],
        "modulation": "LoRa",
        "drone_type": DroneType.FPV_GENERIC,
    },
    Protocol.CROSSFIRE: {
        "burst_interval_ms": (5, 20),
        "bandwidth_mhz": (0.5, 2.0),
        "freq_bands": ["900MHz"],
        "modulation": "LoRa/FHSS",
        "drone_type": DroneType.FPV_GENERIC,
    },
    Protocol.EXPRESS_LRS: {
        "burst_interval_ms": (10, 30),
        "bandwidth_mhz": (0.1, 1.0),
        "freq_bands": ["2.4GHz"],
        "modulation": "LoRa",
        "drone_type": DroneType.FPV_GENERIC,
    },
    Protocol.GHOST: {
        "burst_interval_ms": (4, 8),
        "bandwidth_mhz": (2, 4),
        "freq_bands": ["2.4GHz"],
        "modulation": "Proprietary FHSS",
        "drone_type": DroneType.FPV_GENERIC,
    },
    Protocol.ANALOG_FPV: {
        "burst_interval_ms": None,          # Continuous, no bursts
        "bandwidth_mhz": (10, 30),          # Wide FM video
        "freq_bands": ["5.8GHz"],
        "modulation": "FM",
        "drone_type": DroneType.FPV_GENERIC,
    },
    Protocol.WIFI_DRONE: {
        "burst_interval_ms": None,          # CSMA/CA, not periodic
        "bandwidth_mhz": (20, 80),
        "freq_bands": ["2.4GHz", "5.8GHz"],
        "modulation": "802.11",
        "drone_type": DroneType.UNKNOWN,
    },
    Protocol.LTE_DRONE: {
        "burst_interval_ms": (1, 10),       # Subframe structure
        "bandwidth_mhz": (5, 20),
        "freq_bands": ["licensed"],
        "modulation": "OFDMA/SC-FDMA",
        "drone_type": DroneType.UNKNOWN,
    },
}


# ---------------------------------------------------------------------------
# Spectral analysis helpers
# ---------------------------------------------------------------------------


def _compute_spectral_features(iq_samples: np.ndarray, sample_rate: float) -> dict:
    """
    Extract spectral features from IQ samples for protocol classification.

    Returns dict with: center_freq_est, bandwidth_est, peak_power_db,
    spectral_flatness, burst_detected, burst_interval_ms
    """
    n = len(iq_samples)
    if n < 256:
        return {}

    # Power spectral density
    window = np.hanning(n)
    fft = np.fft.fftshift(np.fft.fft(iq_samples * window))
    psd = np.abs(fft) ** 2
    freqs = np.fft.fftshift(np.fft.fftfreq(n, 1 / sample_rate))

    # Find peak
    peak_idx = np.argmax(psd)
    peak_power_db = 10 * np.log10(max(psd[peak_idx], 1e-30))

    # Estimate bandwidth (-3 dB points)
    half_max = psd[peak_idx] / 2
    above = psd >= half_max
    if np.any(above):
        bw_indices = np.where(above)[0]
        bandwidth_hz = (bw_indices[-1] - bw_indices[0]) * sample_rate / n
    else:
        bandwidth_hz = sample_rate

    # Spectral flatness (geometric mean / arithmetic mean)
    geom_mean = np.exp(np.mean(np.log(np.maximum(psd, 1e-30))))
    arith_mean = np.mean(psd)
    flatness = geom_mean / max(arith_mean, 1e-30)

    # Burst detection via envelope
    envelope = np.abs(iq_samples)
    # Downsample envelope for burst analysis
    env_ds = envelope[::max(1, n // 1000)]
    env_thresh = np.mean(env_ds) + 2 * np.std(env_ds)
    burst_mask = env_ds > env_thresh

    burst_interval_ms = None
    if np.sum(burst_mask) > 5:
        burst_indices = np.where(burst_mask)[0]
        intervals = np.diff(burst_indices) * (n / 1000) / sample_rate * 1000  # ms
        if len(intervals) > 0:
            burst_interval_ms = float(np.median(intervals))

    return {
        "center_freq_est": float(freqs[peak_idx]),
        "bandwidth_hz": float(bandwidth_hz),
        "peak_power_db": float(peak_power_db),
        "spectral_flatness": float(flatness),
        "burst_detected": bool(np.any(burst_mask)),
        "burst_interval_ms": burst_interval_ms,
    }


def _detect_modulation_type(iq_samples: np.ndarray, sample_rate: float) -> str:
    """
    Classify modulation type from IQ samples.
    Returns: 'OFDM', 'LoRa', 'FM', '802.11', 'FHSS', 'unknown'
    """
    n = len(iq_samples)
    if n < 512:
        return "unknown"

    # Instantaneous frequency
    phase = np.unwrap(np.angle(iq_samples))
    inst_freq = np.diff(phase) * sample_rate / (2 * np.pi)

    # Frequency variance (LoRa has chirps)
    freq_var = np.var(inst_freq)

    # Spectral correlation (OFDM has cyclic prefix)
    # Simplified: check for periodicity in autocorrelation
    autocorr = np.correlate(np.abs(iq_samples), np.abs(iq_samples), mode='full')
    autocorr = autocorr[len(autocorr)//2:]
    # Look for peaks at regular intervals (cyclic prefix)
    peaks = []
    for i in range(10, min(200, len(autocorr)//2)):
        if autocorr[i] > autocorr[i-1] and autocorr[i] > autocorr[i+1]:
            peaks.append(i)
    has_cyclic_prefix = len(peaks) > 2 and np.std(np.diff(peaks)) < 5 if len(peaks) > 2 else False

    # LoRa detection: chirp modulation shows linear frequency sweep
    # Check if frequency changes linearly over symbols
    is_lora = freq_var > 1e6  # High frequency variance suggests chirp

    # FM detection: constant envelope, frequency deviation
    envelope_var = np.var(np.abs(iq_samples))
    is_fm = envelope_var < 0.01 * np.mean(np.abs(iq_samples)) ** 2

    if is_lora:
        return "LoRa"
    if has_cyclic_prefix:
        return "OFDM"
    if is_fm:
        return "FM"
    # Default to 802.11 for WiFi-like
    return "802.11"


# ---------------------------------------------------------------------------
# Main fingerprinter class
# ---------------------------------------------------------------------------


class RFFingerprinter:
    """
    Protocol fingerprinting from raw IQ samples.

    Usage:
        fingerprinter = RFFingerprinter(sample_rate=2.4e6)
        result = fingerprinter.fingerprint(iq_samples, center_freq_hz)
    """

    def __init__(
        self,
        sample_rate: float = 2.4e6,
        min_confidence: float = 0.3,
    ) -> None:
        self._sample_rate = sample_rate
        self._min_confidence = min_confidence
        # History for burst interval tracking per frequency
        self._burst_history: dict[int, list[float]] = {}

    def fingerprint(
        self,
        iq_samples: np.ndarray,
        center_freq_hz: int,
        peak_power_db: float,
    ) -> FingerprintResult:
        """
        Identify protocol from IQ samples.

        Parameters
        ----------
        iq_samples : complex64 array
        center_freq_hz : center frequency in Hz
        peak_power_db : measured peak power in dBm

        Returns
        -------
        FingerprintResult
        """
        # Extract spectral features
        features = _compute_spectral_features(iq_samples, self._sample_rate)
        if not features:
            return FingerprintResult(
                protocol=Protocol.UNKNOWN,
                drone_type=DroneType.UNKNOWN,
                confidence=0.0,
                evidence={"error": "insufficient_samples"},
            )

        modulation = _detect_modulation_type(iq_samples, self._sample_rate)

        # Match against known protocols
        best_protocol = Protocol.UNKNOWN
        best_score = 0.0
        best_evidence = {}

        freq_band = self._classify_frequency(center_freq_hz)

        for protocol, sig in _PROTOCOL_SIGNATURES.items():
            score, evidence = self._score_protocol(
                protocol, sig, features, modulation, freq_band, center_freq_hz
            )
            if score > best_score:
                best_score = score
                best_protocol = protocol
                best_evidence = evidence

        # Apply minimum confidence threshold
        if best_score < self._min_confidence:
            best_protocol = Protocol.UNKNOWN

        drone_type = _PROTOCOL_SIGNATURES.get(best_protocol, {}).get("drone_type", DroneType.UNKNOWN)

        return FingerprintResult(
            protocol=best_protocol,
            drone_type=drone_type,
            confidence=round(best_score, 3),
            evidence=best_evidence,
        )

    def _classify_frequency(self, freq_hz: int) -> str:
        if 860_000_000 <= freq_hz <= 930_000_000:
            return "900MHz"
        if 2_400_000_000 <= freq_hz <= 2_485_000_000:
            return "2.4GHz"
        if 5_725_000_000 <= freq_hz <= 5_875_000_000:
            return "5.8GHz"
        return "other"

    def _score_protocol(
        self,
        protocol: Protocol,
        sig: dict,
        features: dict,
        modulation: str,
        freq_band: str,
        center_freq_hz: int,
    ) -> tuple[float, dict]:
        """Score how well features match a protocol signature."""
        score = 0.0
        evidence = {"protocol": protocol.value}

        # Frequency band match (strongest indicator)
        if freq_band in sig["freq_bands"]:
            score += 0.4
            evidence["freq_match"] = True
        else:
            evidence["freq_match"] = False

        # Modulation match
        if sig["modulation"] != "unknown" and modulation != "unknown":
            if sig["modulation"].lower() in modulation.lower() or modulation.lower() in sig["modulation"].lower():
                score += 0.25
                evidence["modulation_match"] = True
            else:
                evidence["modulation_match"] = False
                evidence["detected_modulation"] = modulation

        # Bandwidth match
        bw_mhz = features.get("bandwidth_hz", 0) / 1e6
        bw_min, bw_max = sig["bandwidth_mhz"]
        if bw_min <= bw_mhz <= bw_max:
            score += 0.15
            evidence["bandwidth_match"] = True
        else:
            evidence["bandwidth_match"] = False
            evidence["bandwidth_mhz"] = round(bw_mhz, 1)

        # Burst interval match (for protocols with periodic bursts)
        burst_interval = features.get("burst_interval_ms")
        sig_interval = sig["burst_interval_ms"]
        if sig_interval is not None and burst_interval is not None:
            lo, hi = sig_interval
            if lo <= burst_interval <= hi:
                score += 0.2
                evidence["burst_match"] = True
            else:
                evidence["burst_match"] = False
                evidence["burst_interval_ms"] = round(burst_interval, 1)
        elif sig_interval is None and burst_interval is None:
            # Both continuous (e.g., analog FPV)
            score += 0.15
            evidence["continuous_match"] = True

        evidence["detected_modulation"] = modulation
        evidence["spectral_flatness"] = round(features.get("spectral_flatness", 0), 3)

        return score, evidence


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def fingerprint_iq(
    iq_samples: np.ndarray,
    center_freq_hz: int,
    sample_rate: float = 2.4e6,
) -> FingerprintResult:
    """Convenience function for one-shot fingerprinting."""
    fingerprinter = RFFingerprinter(sample_rate=sample_rate)
    return fingerprinter.fingerprint(iq_samples, center_freq_hz, -50.0)