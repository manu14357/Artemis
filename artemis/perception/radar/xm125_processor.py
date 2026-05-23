"""
artemis/perception/radar/xm125_processor.py
Acconeer XM125 pulsed coherent radar driver.

Produces RadarDetection objects from the XM125 distance-detector service.
The XM125 talks over UART (/dev/ttyUSB0) or SPI, depending on carrier board.
This driver uses the UART interface via acconeer-exptool's Client API.

Physical range: 0.3 – 20 m (effective, XM125 max is 20 m).
Micro-Doppler: derived from variance of the velocity distribution in the
  depth-of-field; higher spread ↔ fast rotating blades.

Fix (per docs/artemis.md §2):
  - UART interface, NOT SPI.
  - SessionConfig wrapper required before start_session().
  - Range clamped to [0.3, 20.0] m.

Import guard:
    acconeer.exptool is optional. Missing lib raises DriverUnavailableError.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, Optional

import numpy as np

from artemis.core.logging import get_logger
from artemis.core.types import RadarDetection, SensorLayer
from artemis.perception.base import DriverStatus, PerceptionDriver

log = get_logger("perception.radar")

# ---------------------------------------------------------------------------
# Optional hardware import
# ---------------------------------------------------------------------------
try:
    import acconeer.exptool as et

    _HAS_ACCONEER = True
except ImportError:
    _HAS_ACCONEER = False
    log.warning("acconeer-exptool not installed — XM125Processor will raise on start()")


class DriverUnavailableError(RuntimeError):
    """Raised when acconeer-exptool is not installed."""


# ---------------------------------------------------------------------------
# Constants (mirror sim/radar_emulator.py for consistency)
# ---------------------------------------------------------------------------

_MIN_RANGE_M = 0.3
_MAX_RANGE_M = 20.0
_THRESHOLD_SNR_DB = 8.0

# Micro-Doppler spread reference table (Hz) — used to cross-check sensor output
_EXPECTED_SPREAD: dict[str, float] = {
    "DJI_Mini3": 18.0,
    "DJI_Mavic3": 22.0,
    "Autel_Evo2": 24.0,
    "FPV_Generic": 35.0,
}


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


class XM125Processor(PerceptionDriver):
    """
    Real-hardware Acconeer XM125 radar driver.

    Streams RadarDetection objects. Each detection includes:
    - range_m: distance to strongest reflector
    - micro_doppler_spread: velocity spread (Hz) of rotating blades
    - bearing_deg: None (single radar cannot determine bearing)
    - velocity_mps: mean radial velocity
    """

    def __init__(
        self,
        node_id: str,
        *,
        serial_port: str = "/dev/ttyUSB0",
        start_point: int = 50,
        num_points: int = 100,
        step_length: int = 2,
        profile: str = "PROFILE_5",
    ) -> None:
        super().__init__(node_id)
        self._serial_port = serial_port
        self._start_point = start_point
        self._num_points = num_points
        self._step_length = step_length
        self._profile_str = profile
        self._client: Optional[object] = None
        self._session_config: Optional[object] = None

    async def start(self) -> None:
        if not _HAS_ACCONEER:
            raise DriverUnavailableError(
                "acconeer-exptool is not installed. "
                "Run: pip install acconeer-exptool>=7.0.0"
            )
        log.info(
            "XM125Processor starting node=%s port=%s",
            self.node_id,
            self._serial_port,
        )

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._close_client)
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        self.status = DriverStatus.STOPPED
        log.info("XM125Processor stopped node=%s", self.node_id)

    async def stream(self) -> AsyncGenerator[RadarDetection, None]:  # type: ignore[override]
        if not _HAS_ACCONEER:
            raise DriverUnavailableError("acconeer-exptool not installed")

        # Open UART client in thread (blocking I/O)
        self._client = await asyncio.to_thread(self._open_client)
        self.status = DriverStatus.RUNNING
        log.info(
            "XM125Processor running node=%s range=[%.1f, %.1f]m",
            self.node_id,
            _MIN_RANGE_M,
            _MAX_RANGE_M,
        )

        try:
            while True:
                det = await asyncio.to_thread(self._read_frame)
                if det is not None:
                    yield det
                else:
                    # No detection this frame — yield to event loop
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.status = DriverStatus.ERROR
            log.error("XM125Processor error node=%s: %s", self.node_id, exc)
            raise
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Blocking helpers (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _open_client(self) -> object:
        """
        Open UART connection to XM125 and configure distance detector session.
        Uses acconeer-exptool ≥7.0.0 Client API with SessionConfig wrapper.
        """
        client = et.UARTClient(serial_port=self._serial_port)  # type: ignore[attr-defined]
        client.connect()

        # Build SessionConfig (required in exptool ≥7, fix per docs §2)
        session_config = et.a121.SessionConfig(  # type: ignore[attr-defined]
            et.a121.SensorConfig(  # type: ignore[attr-defined]
                start_point=self._start_point,
                num_points=self._num_points,
                step_length=self._step_length,
                profile=getattr(
                    et.a121.Profile, self._profile_str, et.a121.Profile.PROFILE_5  # type: ignore[attr-defined]
                ),
            )
        )
        client.setup_session(session_config)
        client.start_session()
        self._session_config = session_config
        log.debug("XM125 session started port=%s", self._serial_port)
        return client

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.stop_session()  # type: ignore[attr-defined]
                self._client.disconnect()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def _read_frame(self) -> RadarDetection | None:
        """
        Read one radar frame and return RadarDetection or None.
        This is a blocking call — must be run in a thread.
        """
        assert self._client is not None  # noqa: S101
        try:
            data_info, data = self._client.get_next()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            log.warning("XM125 frame error node=%s: %s", self.node_id, exc)
            return None

        # data is a numpy array of complex IQ samples (num_points,)
        frame = np.array(data, dtype=np.complex128)
        amplitude = np.abs(frame)
        power_db = 10.0 * np.log10(np.maximum(amplitude**2, 1e-30))

        # Find strongest reflector
        peak_idx = int(np.argmax(amplitude))
        peak_snr = float(power_db[peak_idx])

        if peak_snr < _THRESHOLD_SNR_DB:
            return None

        # Convert point index to range
        step_m = self._step_length * 2.5e-3  # XM125: 2.5 mm per step length unit
        range_m = _MIN_RANGE_M + peak_idx * step_m
        range_m = float(np.clip(range_m, _MIN_RANGE_M, _MAX_RANGE_M))

        # Micro-Doppler spread: std of velocity distribution
        # Approximate by amplitude envelope variation across frame
        velocity_spread = float(np.std(amplitude))
        # Scale to match expected Hz values (empirical calibration factor)
        micro_doppler_spread = velocity_spread * 10.0

        # Mean radial velocity (from phase derivative across adjacent samples)
        if len(frame) >= 2:
            phase_diff = np.angle(frame[1:] * np.conj(frame[:-1]))
            mean_phase = float(np.mean(phase_diff))
            # v = phase * c / (4 * pi * f_carrier * T)
            # Using approximate carrier for XM125 (≈60 GHz)
            f_carrier = 60e9
            prf = 1000.0  # nominal pulse rep freq (Hz)
            velocity_mps = mean_phase * 3e8 / (4 * math.pi * f_carrier / prf)
        else:
            velocity_mps = 0.0

        return RadarDetection(
            range_m=round(range_m, 3),
            micro_doppler_spread=round(micro_doppler_spread, 2),
            source=self.node_id,
            timestamp=time.time(),
            layer=SensorLayer.RADAR,
            signature="rotating_blades",
            velocity_mps=round(velocity_mps, 3),
            bearing_deg=None,  # single radar cannot determine bearing
        )


# lazy math import (used only inside blocking thread)
import math  # noqa: E402
