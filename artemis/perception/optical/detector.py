"""
artemis/perception/optical/detector.py
Camera-based optical drone detector using MOG2 background subtraction
and Lucas-Kanade optical flow.

Pipeline:
  1. Grab frame via PiCamera2 (Raspberry Pi) or cv2.VideoCapture (fallback).
  2. Apply MOG2 background subtractor → foreground mask.
  3. Find contours; filter by min_blob_area.
  4. Track blobs across frames with Lucas-Kanade sparse optical flow → velocity.
  5. Estimate range via pinhole model: range_m = focal_px * real_size_m / sqrt(area)
  6. Yield OpticalDetection for each blob.

Calibration:
  - focal_px: derive from camera intrinsics (default: 554 px for 90° HFOV at 640 px)
  - real_size_m: average drone frontal projection ≈ 0.35 m

Import guard:
    cv2 is optional; picamera2 is optional. Missing libs raise DriverUnavailableError.
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, Optional

import numpy as np

from artemis.core.logging import get_logger
from artemis.core.types import DroneType, OpticalDetection, SensorLayer
from artemis.perception.base import DriverStatus, PerceptionDriver

log = get_logger("perception.optical")

# ---------------------------------------------------------------------------
# Optional hardware imports
# ---------------------------------------------------------------------------
try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

try:
    from picamera2 import Picamera2  # type: ignore[import]
    _HAS_PICAMERA2 = True
except ImportError:
    _HAS_PICAMERA2 = False


class DriverUnavailableError(RuntimeError):
    """Raised when cv2 is not installed."""


# ---------------------------------------------------------------------------
# Camera abstraction
# ---------------------------------------------------------------------------

class _PiCamera2Source:
    """Picamera2-backed frame source."""

    def __init__(self, resolution: tuple[int, int], fps: int) -> None:
        self._cam = Picamera2()
        cfg = self._cam.create_video_configuration(
            main={"size": resolution, "format": "RGB888"},
        )
        self._cam.configure(cfg)
        self._cam.set_controls({"FrameRate": fps})

    def open(self) -> None:
        self._cam.start()

    def read(self) -> tuple[bool, np.ndarray | None]:
        try:
            frame = self._cam.capture_array()
            # PiCamera2 returns RGB; convert to BGR for cv2 compatibility
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return True, bgr
        except Exception as exc:  # noqa: BLE001
            log.warning("PiCamera2 read error: %s", exc)
            return False, None

    def release(self) -> None:
        self._cam.stop()


class _CV2Source:
    """OpenCV VideoCapture-backed frame source (USB cam, RTSP, etc.)."""

    def __init__(self, resolution: tuple[int, int], fps: int,
                 index: int = 0) -> None:
        self._idx = index
        self._resolution = resolution
        self._fps = fps
        self._cap: Optional[cv2.VideoCapture] = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self._idx)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera index={self._idx}")
        w, h = self._resolution
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None:
            return False, None
        ret, frame = self._cap.read()
        return ret, frame if ret else None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()


# ---------------------------------------------------------------------------
# Pinhole range estimation
# ---------------------------------------------------------------------------

_DRONE_REAL_SIZE_M = 0.35   # approximate frontal span for a typical drone
_FOCAL_PX_DEFAULT = 554.0   # focal length (px) for 90° HFOV at 640 px wide


def _estimate_range_m(blob_area_px: float, focal_px: float = _FOCAL_PX_DEFAULT,
                      real_size_m: float = _DRONE_REAL_SIZE_M) -> float:
    """
    Pinhole range estimate using blob area.
    Apparent width w_px ≈ sqrt(area) for a roughly square blob.
    range = focal * real_size / w_px
    """
    w_px = max(blob_area_px ** 0.5, 1.0)
    return round(focal_px * real_size_m / w_px, 2)


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

class OpticalDetector(PerceptionDriver):
    """
    Camera-based drone detector using MOG2 background subtraction.

    Attempts to use PiCamera2 first; falls back to cv2.VideoCapture.
    """

    def __init__(
        self,
        node_id: str,
        *,
        resolution: tuple[int, int] = (640, 480),
        fps: int = 30,
        mog2_learning_rate: float = 0.005,
        min_blob_area: int = 80,
        focal_px: float = _FOCAL_PX_DEFAULT,
        camera_index: int = 0,
    ) -> None:
        super().__init__(node_id)
        self._resolution = resolution
        self._fps = fps
        self._mog2_lr = mog2_learning_rate
        self._min_blob_area = min_blob_area
        self._focal_px = focal_px
        self._camera_index = camera_index
        self._source: Optional[_PiCamera2Source | _CV2Source] = None
        self._fgbg: Optional[object] = None  # cv2.BackgroundSubtractorMOG2
        # Lucas-Kanade tracking state
        self._prev_gray: Optional[np.ndarray] = None
        self._prev_pts: Optional[np.ndarray] = None   # (N, 1, 2) float32
        self._prev_blobs: list[tuple[float, float, float]] = []  # (cx, cy, area)

    async def start(self) -> None:
        if not _HAS_CV2:
            raise DriverUnavailableError(
                "opencv-python is not installed. Run: pip install opencv-python"
            )
        log.info("OpticalDetector starting node=%s", self.node_id)

    async def stop(self) -> None:
        if self._source is not None:
            try:
                self._source.release()
            except Exception:  # noqa: BLE001
                pass
            self._source = None
        self.status = DriverStatus.STOPPED
        log.info("OpticalDetector stopped node=%s", self.node_id)

    async def stream(self) -> AsyncGenerator[OpticalDetection, None]:  # type: ignore[override]
        if not _HAS_CV2:
            raise DriverUnavailableError("opencv-python not installed")

        self._source, self._fgbg = await asyncio.to_thread(self._open_camera)
        self.status = DriverStatus.RUNNING
        log.info(
            "OpticalDetector running node=%s res=%s fps=%d",
            self.node_id, self._resolution, self._fps,
        )

        try:
            while True:
                detections = await asyncio.to_thread(self._process_frame)
                for det in detections:
                    yield det
                if not detections:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.status = DriverStatus.ERROR
            log.error("OpticalDetector error node=%s: %s", self.node_id, exc)
            raise
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Blocking helpers (run via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _open_camera(self) -> tuple[object, object]:
        if _HAS_PICAMERA2:
            log.debug("OpticalDetector using PiCamera2")
            src: _PiCamera2Source | _CV2Source = _PiCamera2Source(
                self._resolution, self._fps
            )
        else:
            log.debug("OpticalDetector using cv2.VideoCapture index=%d", self._camera_index)
            src = _CV2Source(self._resolution, self._fps, self._camera_index)

        src.open()
        fgbg = cv2.createBackgroundSubtractorMOG2(
            history=500,
            varThreshold=16,
            detectShadows=False,
        )
        return src, fgbg

    def _process_frame(self) -> list[OpticalDetection]:
        """
        Grab one frame, run MOG2 + contour detection + LK flow.
        Returns a list of OpticalDetection (0 or more).
        """
        assert self._source is not None  # noqa: S101
        assert self._fgbg is not None    # noqa: S101

        ret, frame = self._source.read()
        if not ret or frame is None:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Background subtraction
        fg_mask = self._fgbg.apply(frame, learningRate=self._mog2_lr)

        # Morphological cleanup
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_clean = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_clean = cv2.dilate(fg_clean, kernel, iterations=2)

        # Contour detection
        contours, _ = cv2.findContours(
            fg_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        detections: list[OpticalDetection] = []
        curr_blobs: list[tuple[float, float, float]] = []
        curr_pts: list[list[float]] = []

        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < self._min_blob_area:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            cx = x + w / 2.0
            cy = y + h / 2.0
            curr_blobs.append((cx, cy, area))
            curr_pts.append([[cx, cy]])

        # Lucas-Kanade optical flow for velocity estimation
        velocities: list[tuple[float, float]] = []
        if (
            self._prev_gray is not None
            and self._prev_pts is not None
            and len(self._prev_pts) > 0
            and len(curr_pts) > 0
        ):
            np.array(curr_pts, dtype=np.float32)
            lk_params = {
                "winSize": (15, 15),
                "maxLevel": 2,
                "criteria": (
                    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                    10, 0.03,
                ),
            }
            prev_pts_arr = self._prev_pts
            new_pts, status, _ = cv2.calcOpticalFlowPyrLK(
                self._prev_gray, gray, prev_pts_arr, None, **lk_params
            )
            # Match tracked points to current blobs
            for i, (cx, cy, _area) in enumerate(curr_blobs):
                vx, vy = 0.0, 0.0
                if new_pts is not None and status is not None:
                    for j, (nx, ny) in enumerate(new_pts.reshape(-1, 2)):
                        if status[j, 0] == 1:
                            ox, oy = prev_pts_arr[j, 0]
                            # match by proximity
                            if abs(nx - cx) < 20 and abs(ny - cy) < 20:
                                vx = float(nx - ox)
                                vy = float(ny - oy)
                                break
                velocities.append((vx, vy))
        else:
            velocities = [(0.0, 0.0)] * len(curr_blobs)

        # Update LK state
        self._prev_gray = gray
        if curr_pts:
            self._prev_pts = np.array(curr_pts, dtype=np.float32)
        self._prev_blobs = curr_blobs

        # Emit detections
        now = time.time()
        for i, (cx, cy, area) in enumerate(curr_blobs):
            x_bb = int(cx - (area ** 0.5) / 2)
            y_bb = int(cy - (area ** 0.5) / 2)
            side = int(area ** 0.5)
            bbox = (x_bb, y_bb, side, side)
            vx, vy = velocities[i] if i < len(velocities) else (0.0, 0.0)
            range_m = _estimate_range_m(area, self._focal_px)

            detections.append(
                OpticalDetection(
                    bbox=bbox,
                    area=round(area, 1),
                    velocity=(round(vx, 2), round(vy, 2)),
                    source=self.node_id,
                    timestamp=now,
                    layer=SensorLayer.OPTICAL,
                    confidence=1.0,
                    drone_type=DroneType.UNKNOWN,
                    range_m=range_m,
                )
            )

        return detections
