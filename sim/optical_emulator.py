#!/usr/bin/env python3
"""
sim/optical_emulator.py
Simulates camera-based optical detections (bounding box + velocity).

Uses a simple pinhole camera model:
  - Drone projected to pixel coordinates based on azimuth and elevation from node.
  - Bounding box size inversely proportional to slant range.
  - Pixel velocity derived from angular rate of change.

Camera config (mirrors node_default.yaml):
  resolution: [640, 480]
  fps: 30
  fov_deg: 90 (horizontal, typical wide-angle)
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional

from artemis.core.types import OpticalDetection

# Apparent size in pixels at reference distance
_REF_PIXELS_AT_10M: dict[str, tuple[int, int]] = {
    "DJI_Mini3": (40, 20),
    "DJI_Mavic3": (50, 25),
    "Autel_Evo2": (55, 28),
    "FPV_Generic": (30, 15),
    "unknown": (40, 20),
}

_IMAGE_W = 640
_IMAGE_H = 480
_FOV_H_DEG = 90.0  # horizontal field of view
_MAX_RANGE_M = 300.0


def _project(azimuth_deg: float, elevation_deg: float) -> tuple[float, float]:
    """
    Project (azimuth, elevation) angles to pixel coordinates.
    azimuth_deg=0 → centre of image.
    elevation_deg=0 → centre of image.
    """
    scale_x = _IMAGE_W / _FOV_H_DEG
    scale_y = scale_x  # square pixels
    px = _IMAGE_W / 2.0 + azimuth_deg * scale_x
    py = _IMAGE_H / 2.0 - elevation_deg * scale_y  # elevation up = pixel up
    return px, py


def _apparent_size(model: str, distance_m: float) -> tuple[int, int]:
    """Return (width_px, height_px) at a given slant range."""
    if distance_m <= 0:
        return _REF_PIXELS_AT_10M.get(model, (40, 20))
    ref_w, ref_h = _REF_PIXELS_AT_10M.get(model, (40, 20))
    # Size ∝ 1/distance
    w = int(ref_w * 10.0 / distance_m)
    h = int(ref_h * 10.0 / distance_m)
    return max(w, 2), max(h, 2)


@dataclass
class OpticalEmulatorState:
    drone_id: str
    model: str
    fps: float = 30.0
    min_blob_area: int = 80  # pixels²
    _next_frame: float = field(default=0.0, repr=False)
    _prev_px: Optional[tuple[float, float]] = field(default=None, repr=False)
    _prev_ts: float = field(default=0.0, repr=False)

    def sample(
        self,
        distance_m: float,
        azimuth_deg: float,  # degrees from camera boresight (0 = straight ahead)
        elevation_deg: float = 0.0,
    ) -> Optional[OpticalDetection]:
        now = time.monotonic()
        if now < self._next_frame:
            return None
        self._next_frame = now + 1.0 / self.fps + random.gauss(0, 0.001)

        if distance_m > _MAX_RANGE_M:
            self._prev_px = None
            return None

        # Clip to field of view
        if abs(azimuth_deg) > _FOV_H_DEG / 2.0:
            self._prev_px = None
            return None

        px, py = _project(azimuth_deg, elevation_deg)

        # Add pixel noise
        px += random.gauss(0, 1.5)
        py += random.gauss(0, 1.5)

        w, h = _apparent_size(self.model, distance_m)
        area = w * h

        if area < self.min_blob_area:
            return None

        x1 = int(max(px - w / 2, 0))
        y1 = int(max(py - h / 2, 0))
        x2 = int(min(px + w / 2, _IMAGE_W))
        y2 = int(min(py + h / 2, _IMAGE_H))
        bbox = (x1, y1, x2 - x1, y2 - y1)  # (x, y, w, h) format

        # Pixel velocity
        dt = now - self._prev_ts if self._prev_ts > 0 else 1.0 / self.fps
        if self._prev_px is not None and dt > 0:
            vx = (px - self._prev_px[0]) / dt
            vy = (py - self._prev_px[1]) / dt
        else:
            vx, vy = 0.0, 0.0

        self._prev_px = (px, py)
        self._prev_ts = now

        confidence = min(1.0, area / (200.0 + area))
        range_m = (
            distance_m + random.gauss(0, distance_m * 0.08)
            if distance_m < 250.0
            else None
        )

        return OpticalDetection(
            bbox=bbox,
            area=float(area),
            velocity=(round(vx, 2), round(vy, 2)),
            source=f"sim-optical-{self.drone_id}",
            timestamp=time.time(),
            confidence=round(confidence, 3),
            range_m=round(range_m, 1) if range_m else None,
        )


def make_optical_emulator(drone_id: str, model: str) -> OpticalEmulatorState:
    return OpticalEmulatorState(drone_id=drone_id, model=model)
