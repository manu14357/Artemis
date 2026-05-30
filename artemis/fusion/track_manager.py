"""
artemis/fusion/track_manager.py
Manages the lifecycle of all active tracks across sensor fusion cycles.

Track lifecycle
---------------
TENTATIVE  → receives first detection; must be confirmed within a window
CONFIRMED  → enough sensor layers agree; published to ThreatMap
COASTED    → no update for one or more frames; EKF predicts forward
DROPPED    → coasted too long; removed permanently

Detection-to-position mapping
------------------------------
Before calling update(), each raw Detection is converted to a Cartesian
measurement vector [x, y, z] by _detection_to_xyz().  For simulation the
conversion is straightforward (detections already carry range / bearing or
explicit x/y).  Acoustic and RF detections without explicit position
contribute only to layer confirmation, not to KF state updates.
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

import numpy as np

from artemis.core.logging import get_logger
from artemis.core.types import (
    AcousticDetection,
    Detection,
    OpticalDetection,
    RadarDetection,
    RFDetection,
    Track,
    TrackStatus,
)
from artemis.fusion.correlator import assign
from artemis.fusion.kalman import EKFTracker

log = get_logger("fusion.track_manager")


# ---------------------------------------------------------------------------
# Track record — internal wrapper around a Track dataclass + an EKFTracker
# ---------------------------------------------------------------------------


class _TrackRecord:
    def __init__(self, track: Track, kf: EKFTracker) -> None:
        self.track = track
        self.kf = kf

    @property
    def id(self) -> str:
        return self.track.track_id

    @property
    def predicted_xyz(self) -> np.ndarray:
        return self.kf.position


# ---------------------------------------------------------------------------
# TrackManager
# ---------------------------------------------------------------------------


class TrackManager:
    """
    Maintains a dict of active _TrackRecords and processes incoming Detections
    every fusion cycle.

    Parameters (all sourced from hub_default.yaml → FusionConfig)
    ----------
    process_noise_q : float
    measurement_noise_r : float
    max_coast_frames : int
    max_distance_m : float
    min_sensor_layers : int — number of unique layers before a track is CONFIRMED
    dt : float — fusion cycle period in seconds
    """

    def __init__(
        self,
        process_noise_q: float = 0.1,
        measurement_noise_r: float = 0.5,
        max_coast_frames: int = 10,
        max_distance_m: float = 50.0,
        min_sensor_layers: int = 2,
        dt: float = 0.1,
    ) -> None:
        self._q = process_noise_q
        self._r = measurement_noise_r
        self._max_coast = max_coast_frames
        self._max_dist = max_distance_m
        self._min_layers = min_sensor_layers
        self._dt = dt

        self._records: dict[str, _TrackRecord] = {}

    # ------------------------------------------------------------------
    # Main entry point — called every fusion cycle
    # ------------------------------------------------------------------

    def update(self, detections: list[Detection]) -> list[Track]:
        """
        Process a batch of raw detections:
          1. Predict all tracks forward by dt.
          2. Convert detections to Cartesian positions.
          3. Run Hungarian assignment.
          4. Update matched tracks; create new tentative tracks for unmatched dets.
          5. Coast / drop tracks with no matching detection.
          6. Promote tentative → confirmed tracks.
          7. Return all non-dropped Tracks.
        """
        # --- 1. Predict ---
        for rec in self._records.values():
            rec.kf.predict(self._dt)

        # --- 2. Filter detections that have position info ---
        positioned: list[tuple[Detection, np.ndarray]] = []
        layer_only: list[Detection] = []

        for det in detections:
            xyz = _detection_to_xyz(det)
            if xyz is not None:
                positioned.append((det, xyz))
            else:
                layer_only.append(det)

        # --- 3. Hungarian assignment ---
        det_xyz = [xyz for _, xyz in positioned]
        track_ids = list(self._records.keys())
        trk_xyz = [self._records[tid].predicted_xyz for tid in track_ids]

        matches, unmatched_dets, unmatched_trks = assign(
            det_xyz, trk_xyz, self._max_dist
        )

        # --- 4a. Update matched tracks ---
        for det_i, trk_i in matches:
            det, xyz = positioned[det_i]
            rec = self._records[track_ids[trk_i]]
            rec.kf.update(xyz)
            rec.track.state = rec.kf.x.tolist()
            rec.track.hit_count += 1
            rec.track.coast_frames = 0
            rec.track.last_update = time.time()
            rec.track.sensor_layers.add(det.layer.value)
            rec.track.last_detections[det.layer.value] = det

        # --- 4b. Absorb layer-only detections into the nearest confirmed track ---
        for det in layer_only:
            # Extract bearing hint from the detection for proximity matching
            bearing_deg = getattr(det, "bearing_deg", None)
            nearest = _find_nearest_track(
                self._records, max_dist=self._max_dist * 2, bearing_deg=bearing_deg
            )
            if nearest:
                nearest.track.sensor_layers.add(det.layer.value)
                nearest.track.last_detections[det.layer.value] = det

        # --- 4c. Create new tracks for unmatched detections ---
        for det_i in unmatched_dets:
            det, xyz = positioned[det_i]
            self._spawn_track(det, xyz)

        # --- 5. Coast / drop unmatched tracks ---
        to_drop = []
        for trk_i in unmatched_trks:
            tid = track_ids[trk_i]
            rec = self._records[tid]
            rec.track.coast_frames += 1
            if rec.track.coast_frames > self._max_coast:
                rec.track.status = TrackStatus.DROPPED
                to_drop.append(tid)
            elif rec.track.status == TrackStatus.CONFIRMED:
                rec.track.status = TrackStatus.COASTED

        for tid in to_drop:
            log.debug("dropping track %s", tid)
            del self._records[tid]

        # --- 6. Promote tentative → confirmed ---
        for rec in self._records.values():
            if rec.track.status == TrackStatus.TENTATIVE:
                n_layers = len(rec.track.sensor_layers)
                if n_layers >= self._min_layers or rec.track.hit_count >= 3:
                    rec.track.status = TrackStatus.CONFIRMED
                    log.info(
                        "track confirmed track_id=%s layers=%s",
                        rec.id,
                        rec.track.sensor_layers,
                    )

        return [rec.track for rec in self._records.values()]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _spawn_track(self, det: Detection, xyz: np.ndarray) -> _TrackRecord:
        kf = EKFTracker(
            process_noise_q=self._q,
            measurement_noise_r=self._r,
            dt=self._dt,
        )
        kf.init(xyz)

        track = Track(
            track_id=str(uuid.uuid4())[:8],
            status=TrackStatus.TENTATIVE,
            state=kf.x.tolist(),
            sensor_layers={det.layer.value},
            hit_count=1,
            last_detections={det.layer.value: det},
        )
        rec = _TrackRecord(track, kf)
        self._records[track.track_id] = rec
        log.debug("new track track_id=%s layer=%s", track.track_id, det.layer.value)
        return rec

    def get_confirmed_tracks(self) -> list[Track]:
        return [
            rec.track
            for rec in self._records.values()
            if rec.track.status in (TrackStatus.CONFIRMED, TrackStatus.COASTED)
        ]

    def all_tracks(self) -> list[Track]:
        return [rec.track for rec in self._records.values()]


# ---------------------------------------------------------------------------
# Detection → Cartesian position
# ---------------------------------------------------------------------------


def _detection_to_xyz(det: Detection) -> Optional[np.ndarray]:
    """
    Convert a raw Detection to a Cartesian [x, y, z] measurement in metres.

    Returns None for detections that don't carry enough position information
    (e.g. an RF detection with only a bearing but no range).
    """
    if isinstance(det, RadarDetection):
        # Radar gives range and optionally bearing.
        r = det.range_m
        bearing_rad = (
            np.radians(det.bearing_deg) if det.bearing_deg is not None else 0.0
        )
        x = r * np.sin(bearing_rad)
        y = r * np.cos(bearing_rad)
        z = 0.0  # radar is 2-D in this model
        return np.array([x, y, z])

    if isinstance(det, RFDetection) and det.bearing_deg is not None:
        # RF with bearing: use a crude range estimate from RSSI
        # FSPL rearranged: range ≈ 10^((FSPL_dB - path_loss_offset) / 20)
        # Without calibration we can't recover range, so treat as layer-only.
        return None

    if isinstance(det, AcousticDetection) and det.range_m is not None:
        r = det.range_m
        bearing_rad = np.radians(det.bearing_deg)
        x = r * np.sin(bearing_rad)
        y = r * np.cos(bearing_rad)
        return np.array([x, y, 0.0])

    if isinstance(det, OpticalDetection) and det.range_m is not None:
        # Optical gives a 2-D bounding box; range must come from another sensor.
        bx, by, bw, bh = det.bbox
        cx = bx + bw / 2
        cy = by + bh / 2  # noqa: F841  — reserved for elevation estimate
        r = det.range_m
        # Normalise pixel centre to rough bearing offset (assume 60° horizontal FOV)
        bearing_deg = (cx - 320) / 320 * 30.0
        bearing_rad = np.radians(bearing_deg)
        x = r * np.sin(bearing_rad)
        y = r * np.cos(bearing_rad)
        return np.array([x, y, 0.0])

    # Simulation detections may carry explicit x/y via range+bearing combination
    # handled above; anything else is layer-only.
    return None


def _find_nearest_track(
    records: dict[str, _TrackRecord],
    max_dist: float,
    bearing_deg: Optional[float] = None,
) -> Optional[_TrackRecord]:
    """
    Return the confirmed track that best matches a layer-only detection.

    If a bearing is available, selects the track whose angular position
    (from origin) is closest to the detection's bearing.  Otherwise falls
    back to the nearest confirmed track by Euclidean distance.
    """
    best: Optional[_TrackRecord] = None
    best_score = float("inf")

    for rec in records.values():
        if rec.track.status not in (TrackStatus.CONFIRMED, TrackStatus.COASTED):
            continue
        pos = rec.kf.position  # [x, y, z]
        d = float(np.linalg.norm(pos))
        if d > max_dist:
            continue

        if bearing_deg is not None and d > 0.1:
            # Compare bearing angles: track bearing from origin
            track_bearing = float(np.degrees(np.arctan2(pos[0], pos[1]))) % 360.0
            angle_diff = abs(track_bearing - (bearing_deg % 360.0))
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            score = angle_diff  # lower = better match
        else:
            score = d

        if score < best_score:
            best_score = score
            best = rec
    return best
