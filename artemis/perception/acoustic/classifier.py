"""
artemis/perception/acoustic/classifier.py
Acoustic drone-detection driver for ReSpeaker 4-mic USB array.

Pipeline:
  1. Capture 500 ms audio chunks (4-channel, 16 kHz) via sounddevice.
  2. Compute mel spectrogram on each chunk.
  3. Run MobileNetV2 TFLite inference to classify drone vs. background.
  4. Estimate bearing via GCC-PHAT inter-channel time difference (TDOA).
  5. Yield AcousticDetection when confidence exceeds threshold.

Hardware: ReSpeaker 4-Mic Array for Raspberry Pi (USB or HAT)
Model: models/acoustic_drone_cnn.tflite (MobileNetV2, trained externally)

Import guard:
    sounddevice and tflite_runtime are optional. Missing libs cause
    DriverUnavailableError so the node daemon skips gracefully.
"""

from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import numpy as np

from artemis.core.logging import get_logger
from artemis.core.types import AcousticDetection, DroneType, SensorLayer
from artemis.perception.base import DriverStatus, PerceptionDriver

log = get_logger("perception.acoustic")

# ---------------------------------------------------------------------------
# Optional hardware / ML library imports
# ---------------------------------------------------------------------------
try:
    import sounddevice as sd

    _HAS_SD = True
except ImportError:
    _HAS_SD = False

try:
    import tflite_runtime.interpreter as tflite

    _HAS_TFLITE = True
except ImportError:
    try:
        # Fallback: full TensorFlow on x86 dev machines
        import tensorflow.lite as tflite  # type: ignore[no-redef]

        _HAS_TFLITE = True
    except ImportError:
        _HAS_TFLITE = False


class DriverUnavailableError(RuntimeError):
    """Raised when required hardware/ML libraries are not installed."""


# ---------------------------------------------------------------------------
# Mel spectrogram helpers (pure numpy, no librosa dependency)
# ---------------------------------------------------------------------------

_N_MELS = 64
_N_FFT = 512


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * math.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank(
    n_mels: int, n_fft: int, sr: int, fmin: float = 0.0, fmax: float | None = None
) -> np.ndarray:
    """Return a (n_mels, n_fft//2+1) mel filterbank matrix."""
    if fmax is None:
        fmax = sr / 2.0
    mel_min = _hz_to_mel(fmin)
    mel_max = _hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = np.array([_mel_to_hz(m) for m in mel_points])
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    n_freq = n_fft // 2 + 1
    fb = np.zeros((n_mels, n_freq))
    for m in range(1, n_mels + 1):
        start, center, end = bin_points[m - 1], bin_points[m], bin_points[m + 1]
        for k in range(start, center):
            if center != start:
                fb[m - 1, k] = (k - start) / (center - start)
        for k in range(center, end):
            if end != center:
                fb[m - 1, k] = (end - k) / (end - center)
    return fb


def _compute_mel_spectrogram(
    audio: np.ndarray,
    sr: int,
    n_fft: int = _N_FFT,
    n_mels: int = _N_MELS,
    hop_length: int = 160,
) -> np.ndarray:
    """
    Compute log-mel spectrogram from mono audio array.
    Returns shape (n_mels, time_frames).
    """
    # Short-time Fourier transform
    window = np.hanning(n_fft)
    frames = []
    for start in range(0, len(audio) - n_fft, hop_length):
        frame = audio[start : start + n_fft] * window
        spectrum = np.abs(np.fft.rfft(frame)) ** 2
        frames.append(spectrum)

    if not frames:
        return np.zeros((n_mels, 1))

    power_spec = np.array(frames).T  # (n_freq, time)
    fb = _mel_filterbank(n_mels, n_fft, sr)
    mel_spec = fb @ power_spec
    log_mel = 10.0 * np.log10(np.maximum(mel_spec, 1e-10))
    return log_mel.astype(np.float32)


# ---------------------------------------------------------------------------
# GCC-PHAT bearing estimation
# ---------------------------------------------------------------------------


def _gcc_phat_tdoa(
    sig_a: np.ndarray, sig_b: np.ndarray, sr: int, max_delay_samples: int = 50
) -> float:
    """
    Generalised Cross-Correlation with Phase Transform (GCC-PHAT).
    Returns the time-delay-of-arrival (TDOA) in seconds between two channels.
    """
    n = len(sig_a) + len(sig_b)
    fa = np.fft.rfft(sig_a, n=n)
    fb = np.fft.rfft(sig_b, n=n)
    cc = fa * np.conj(fb)
    denom = np.abs(cc)
    # Avoid division by zero
    cc_phat = cc / np.maximum(denom, 1e-10)
    gcc = np.fft.irfft(cc_phat)
    # Restrict search to plausible microphone separation lags
    half = min(max_delay_samples, n // 2)
    gcc_trimmed = np.concatenate([gcc[:half], gcc[n - half :]])
    lag = int(np.argmax(gcc_trimmed))
    if lag >= half:
        lag -= n
    return lag / sr  # seconds


def _bearing_from_tdoa(tdoa_s: float, mic_spacing_m: float = 0.065) -> float:
    """
    Convert TDOA (seconds) to bearing angle (degrees from forward-facing axis).
    mic_spacing_m: inter-microphone distance (ReSpeaker 4-mic = 65 mm default).
    Uses far-field approximation: tdoa = spacing * sin(theta) / c
    """
    _c = 343.0  # speed of sound m/s
    # Clamp to valid range to avoid arcsin domain error
    ratio = np.clip(tdoa_s * _c / mic_spacing_m, -1.0, 1.0)
    theta_rad = math.asin(ratio)
    return math.degrees(theta_rad)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


class AcousticClassifier(PerceptionDriver):
    """
    Real-hardware acoustic drone classifier using mic array + TFLite CNN.

    Streams AcousticDetection objects when the model confidence exceeds
    the configured threshold.
    """

    def __init__(
        self,
        node_id: str,
        *,
        sample_rate: int = 16_000,
        channels: int = 4,
        device_index: int | None = None,
        window_ms: int = 500,
        model_path: str = "models/acoustic_drone_cnn.tflite",
        confidence_threshold: float = 0.75,
        mic_spacing_m: float = 0.065,
    ) -> None:
        super().__init__(node_id)
        self._sr = sample_rate
        self._channels = channels
        self._device_index = device_index
        self._window_samples = int(sample_rate * window_ms / 1000)
        self._model_path = Path(model_path)
        self._confidence_threshold = confidence_threshold
        self._mic_spacing_m = mic_spacing_m
        self._interpreter: Optional[object] = None

    async def start(self) -> None:
        if not _HAS_SD:
            raise DriverUnavailableError(
                "sounddevice is not installed. Run: pip install sounddevice"
            )
        if not _HAS_TFLITE:
            raise DriverUnavailableError(
                "tflite_runtime is not installed. Run: pip install tflite-runtime"
            )
        if not self._model_path.exists():
            raise FileNotFoundError(
                f"TFLite model not found: {self._model_path.resolve()}\n"
                "Train it first with: python scripts/train_acoustic_model.py"
            )
        # Load interpreter in thread (I/O bound)
        self._interpreter = await asyncio.to_thread(self._load_interpreter)
        log.info(
            "AcousticClassifier ready node=%s model=%s",
            self.node_id,
            self._model_path.name,
        )

    async def stop(self) -> None:
        self._interpreter = None
        self.status = DriverStatus.STOPPED
        log.info("AcousticClassifier stopped node=%s", self.node_id)

    async def stream(self) -> AsyncGenerator[AcousticDetection, None]:  # type: ignore[override]
        if not _HAS_SD or not _HAS_TFLITE:
            raise DriverUnavailableError("Missing sounddevice or tflite_runtime")

        if self._interpreter is None:
            await self.start()

        self.status = DriverStatus.RUNNING
        log.info(
            "AcousticClassifier streaming node=%s sr=%d ch=%d window=%dms",
            self.node_id,
            self._sr,
            self._channels,
            self._window_samples * 1000 // self._sr,
        )

        try:
            while True:
                chunk = await asyncio.to_thread(self._capture_chunk)
                if chunk is None:
                    await asyncio.sleep(0.01)
                    continue

                det = await asyncio.to_thread(self._process_chunk, chunk)
                if det is not None:
                    yield det

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.status = DriverStatus.ERROR
            log.error("AcousticClassifier error node=%s: %s", self.node_id, exc)
            raise
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Blocking helpers (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _load_interpreter(self) -> object:
        interp = tflite.Interpreter(model_path=str(self._model_path))  # type: ignore[attr-defined]
        interp.allocate_tensors()
        return interp

    def _capture_chunk(self) -> np.ndarray | None:
        """Capture one audio window. Returns (window_samples, channels) array."""
        try:
            chunk = sd.rec(
                self._window_samples,
                samplerate=self._sr,
                channels=self._channels,
                device=self._device_index,
                dtype="float32",
            )
            sd.wait()
            return chunk
        except Exception as exc:  # noqa: BLE001
            log.warning("Audio capture error node=%s: %s", self.node_id, exc)
            return None

    def _process_chunk(self, chunk: np.ndarray) -> AcousticDetection | None:
        """
        Run CNN inference + GCC-PHAT bearing on a captured chunk.
        Returns AcousticDetection or None if below threshold.
        """
        # Use channel 0 for classification (best SNR assumed)
        mono = chunk[:, 0] if chunk.ndim > 1 else chunk

        # Mel spectrogram
        mel = _compute_mel_spectrogram(mono, self._sr)
        # Resize to model expected input (64 x 32 by default)
        from scipy.signal import resample  # lazy import

        n_time_expected = 32
        if mel.shape[1] != n_time_expected:
            mel_resized = resample(mel, n_time_expected, axis=1)
        else:
            mel_resized = mel

        # Normalise to [-1, 1]
        m = mel_resized.max()
        if m > 0:
            mel_norm = mel_resized / m
        else:
            mel_norm = mel_resized
        input_data = mel_norm[np.newaxis, :, :, np.newaxis].astype(np.float32)

        # TFLite inference
        interp = self._interpreter
        input_details = interp.get_input_details()  # type: ignore[attr-defined]
        output_details = interp.get_output_details()  # type: ignore[attr-defined]
        interp.set_tensor(input_details[0]["index"], input_data)  # type: ignore[attr-defined]
        interp.invoke()  # type: ignore[attr-defined]
        output = interp.get_tensor(output_details[0]["index"])  # type: ignore[attr-defined]

        # output shape: (1, n_classes) — class 0 = background, 1 = drone
        confidence = float(output[0, 1]) if output.shape[1] > 1 else float(output[0, 0])
        if confidence < self._confidence_threshold:
            return None

        # GCC-PHAT bearing (channels 0 and 1)
        bearing_deg = 0.0
        if self._channels >= 2:
            tdoa = _gcc_phat_tdoa(chunk[:, 0], chunk[:, 1], self._sr)
            bearing_deg = _bearing_from_tdoa(tdoa, self._mic_spacing_m)

        # Rough drone type from confidence pattern (placeholder — refine post training)
        drone_type = DroneType.UNKNOWN

        return AcousticDetection(
            confidence=round(confidence, 3),
            bearing_deg=round(bearing_deg, 1),
            source=self.node_id,
            timestamp=time.time(),
            layer=SensorLayer.ACOUSTIC,
            drone_type=drone_type,
            range_m=None,  # acoustic ranging requires calibration data
        )
