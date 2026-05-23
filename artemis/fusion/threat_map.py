"""
artemis/fusion/threat_map.py
Thread-safe live 3D spatial model of all confirmed threats.

The ThreatMap is the single source of truth for the API layer:
  - The hub's fusion loop calls update() after every cycle.
  - The WebSocket broadcaster calls get_snapshot() at ws_push_rate_hz.
  - The REST /threats endpoint also calls get_snapshot().
"""
from __future__ import annotations

import threading
import time
import uuid

from artemis.core.logging import get_logger
from artemis.core.types import (
    DroneType,
    SensorLayer,
    Threat,
    ThreatTier,
    Track,
    TrackStatus,
)
from artemis.fusion.swarm_analyzer import analyze_swarms, swarm_sizes

log = get_logger("fusion.threat_map")


# ---------------------------------------------------------------------------
# Tier assignment heuristic
# ---------------------------------------------------------------------------

def _assign_tier(track: Track, swarm_size: int) -> ThreatTier:
    """
    Heuristic threat tier based on speed, sensor layers, and swarm membership.
    Tier 5 = immediate lethal threat; Tier 1 = low concern.
    """
    speed = track.speed_mps
    n_layers = len(track.sensor_layers)

    # Swarm bonus
    if swarm_size >= 10:
        base = 5
    elif swarm_size >= 3:
        base = 4
    else:
        base = 1

    # Speed
    if speed > 20:
        base = max(base, 4)
    elif speed > 10:
        base = max(base, 3)
    elif speed > 5:
        base = max(base, 2)

    # Multi-layer confirmation increases confidence but not tier by itself
    if n_layers >= 3:
        base = min(base + 1, 5)

    return ThreatTier(max(1, min(base, 5)))


# ---------------------------------------------------------------------------
# ThreatMap
# ---------------------------------------------------------------------------

class ThreatMap:
    """
    Maintains a dict of {track_id: Threat} updated after every fusion cycle.
    All public methods are thread-safe.
    """

    def __init__(self) -> None:
        self._threats: dict[str, Threat] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Called by the fusion loop after each TrackManager.update()
    # ------------------------------------------------------------------

    def update(
        self,
        tracks: list[Track],
        eps_m: float = 100.0,
        min_swarm_samples: int = 3,
    ) -> None:
        """
        Rebuild the threat map from the latest confirmed tracks.
        Runs DBSCAN to assign swarm IDs, then upserts / removes threats.
        """
        confirmed = [
            t for t in tracks
            if t.status in (TrackStatus.CONFIRMED, TrackStatus.COASTED)
        ]

        # Swarm analysis
        swarm_assignment = analyze_swarms(confirmed, eps_m, min_swarm_samples)
        sizes = swarm_sizes(swarm_assignment)

        new_map: dict[str, Threat] = {}
        for track in confirmed:
            sid = swarm_assignment.get(track.track_id)
            sz  = sizes.get(sid, 0) if sid is not None else 0
            tier = _assign_tier(track, sz)

            # Determine most confident drone type from last detections
            dtype = DroneType.UNKNOWN
            for det in track.last_detections.values():
                if hasattr(det, "drone_type") and det.drone_type != DroneType.UNKNOWN:
                    dtype = det.drone_type
                    break

            # Confidence = ratio of layers seen over total possible
            confidence = len(track.sensor_layers) / len(SensorLayer)

            # Simple trajectory extrapolation: 10-second impact point
            vx, vy, _ = track.velocity_mps
            x, y, z   = track.position_m

            # Look up existing threat ID to keep stable across cycles
            existing = self._threats.get(track.track_id)
            threat_id = existing.threat_id if existing else str(uuid.uuid4())[:8]

            threat = Threat(
                threat_id=threat_id,
                track_id=track.track_id,
                tier=tier,
                drone_type=dtype,
                x_m=x,
                y_m=y,
                z_m=z,
                vx_mps=vx,
                vy_mps=vy,
                vz_mps=track.velocity_mps[2],
                impact_x_m=x + vx * 10,
                impact_y_m=y + vy * 10,
                sensor_layers=list(track.sensor_layers),
                swarm_id=sid,
                swarm_size=sz,
                timestamp=time.time(),
                confidence=round(confidence, 2),
            )
            new_map[track.track_id] = threat

        with self._lock:
            self._threats = new_map

        if new_map:
            log.debug("threat_map updated threats=%d", len(new_map))

    # ------------------------------------------------------------------
    # Called by API / WebSocket
    # ------------------------------------------------------------------

    def get_snapshot(self) -> list[dict]:
        """Return a JSON-serialisable snapshot of all current threats."""
        with self._lock:
            return [t.to_dict() for t in self._threats.values()]

    def get_threat(self, track_id: str) -> Threat | None:
        with self._lock:
            return self._threats.get(track_id)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._threats)
