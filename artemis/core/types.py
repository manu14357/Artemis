"""
artemis/core/types.py
Shared dataclasses used across all ARTEMIS subsystems.
All field names intentionally match the YAML config parameter names.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SensorLayer(str, Enum):
    RF = "rf"
    ACOUSTIC = "acoustic"
    RADAR = "radar"
    OPTICAL = "optical"


class ThreatTier(int, Enum):
    """1 = low concern → 5 = immediate lethal threat."""

    T1 = 1
    T2 = 2
    T3 = 3
    T4 = 4
    T5 = 5


class TrackStatus(str, Enum):
    TENTATIVE = "tentative"  # Not enough hits to confirm
    CONFIRMED = "confirmed"  # Confirmed, publishing to threat map
    COASTED = "coasted"  # No recent update, predicting only
    DROPPED = "dropped"  # Removed from track manager


class DroneType(str, Enum):
    DJI_MAVIC = "dji_mavic"
    DJI_MINI = "dji_mini"
    AUTEL_EVO = "autel_evo"
    FPV_GENERIC = "fpv_generic"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Raw sensor detections (output of each perception driver / emulator)
# ---------------------------------------------------------------------------


@dataclass
class RFDetection:
    frequency: int  # Hz
    peak_power_db: float  # dBm
    source: str  # node_id that generated this
    timestamp: float = field(default_factory=time.time)
    layer: SensorLayer = SensorLayer.RF
    # Optional fingerprint match
    drone_type: DroneType = DroneType.UNKNOWN
    confidence: float = 0.0  # 0–1 fingerprint match confidence
    bearing_deg: Optional[float] = None  # if directional antenna present


@dataclass
class AcousticDetection:
    confidence: float  # 0–1 CNN classification confidence
    bearing_deg: float  # degrees from north (TDOA)
    source: str
    timestamp: float = field(default_factory=time.time)
    layer: SensorLayer = SensorLayer.ACOUSTIC
    drone_type: DroneType = DroneType.UNKNOWN
    range_m: Optional[float] = None  # estimated from signal level if known


@dataclass
class RadarDetection:
    range_m: float  # metres to target
    micro_doppler_spread: float  # std-dev of Doppler fan — proxy for rotor activity
    source: str
    timestamp: float = field(default_factory=time.time)
    layer: SensorLayer = SensorLayer.RADAR
    signature: str = "rotating_blades"
    velocity_mps: Optional[float] = None
    bearing_deg: Optional[float] = None


@dataclass
class OpticalDetection:
    bbox: tuple  # (x, y, w, h) in pixels
    area: float  # pixels²
    velocity: tuple  # (vx, vy) pixels/frame optical-flow vector
    source: str
    timestamp: float = field(default_factory=time.time)
    layer: SensorLayer = SensorLayer.OPTICAL
    confidence: float = 1.0  # presence confidence; background-sub is binary
    drone_type: DroneType = DroneType.UNKNOWN
    range_m: Optional[float] = None


# Union-style alias used in EventBus / queues
Detection = RFDetection | AcousticDetection | RadarDetection | OpticalDetection


# ---------------------------------------------------------------------------
# Track — fused multi-sensor persistent object
# ---------------------------------------------------------------------------


@dataclass
class Track:
    track_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TrackStatus = TrackStatus.TENTATIVE

    # State vector: [x, y, z, vx, vy, vz]  (metres, metres/sec in local Cartesian)
    state: list = field(default_factory=lambda: [0.0] * 6)

    # Which sensor layers have contributed hits
    sensor_layers: set = field(default_factory=set)

    # Hit / coast counters
    hit_count: int = 0
    coast_frames: int = 0

    # Time of last update
    last_update: float = field(default_factory=time.time)

    # The raw detections that last updated this track (one per layer max)
    last_detections: dict = field(default_factory=dict)

    # Swarm cluster id (None = not part of a swarm)
    swarm_id: Optional[int] = None

    @property
    def position_m(self) -> tuple:
        return (self.state[0], self.state[1], self.state[2])

    @property
    def velocity_mps(self) -> tuple:
        return (self.state[3], self.state[4], self.state[5])

    @property
    def speed_mps(self) -> float:
        vx, vy, vz = self.velocity_mps
        return (vx**2 + vy**2 + vz**2) ** 0.5


# ---------------------------------------------------------------------------
# Threat — confirmed track enriched with tier + intent assessment
# ---------------------------------------------------------------------------


@dataclass
class Threat:
    threat_id: str
    track_id: str
    tier: ThreatTier = ThreatTier.T1
    drone_type: DroneType = DroneType.UNKNOWN

    # Position (local Cartesian metres from hub reference point)
    x_m: float = 0.0
    y_m: float = 0.0
    z_m: float = 0.0

    # Velocity
    vx_mps: float = 0.0
    vy_mps: float = 0.0
    vz_mps: float = 0.0

    # Predicted impact point (if trajectory extrapolated)
    impact_x_m: Optional[float] = None
    impact_y_m: Optional[float] = None

    sensor_layers: list = field(default_factory=list)  # e.g. ["rf", "acoustic"]
    swarm_id: Optional[int] = None
    swarm_size: int = 0  # 0 = solo threat

    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.0  # overall track quality score

    def to_dict(self) -> dict:
        return {
            "threat_id": self.threat_id,
            "track_id": self.track_id,
            "tier": self.tier.value,
            "drone_type": self.drone_type.value,
            "position": {"x": self.x_m, "y": self.y_m, "z": self.z_m},
            "velocity": {"vx": self.vx_mps, "vy": self.vy_mps, "vz": self.vz_mps},
            "impact": (
                {"x": self.impact_x_m, "y": self.impact_y_m}
                if self.impact_x_m is not None
                else None
            ),
            "sensor_layers": self.sensor_layers,
            "swarm_id": self.swarm_id,
            "swarm_size": self.swarm_size,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# NodeStatus — heartbeat from each sensor node
# ---------------------------------------------------------------------------


@dataclass
class NodeStatus:
    node_id: str
    lat: float
    lon: float
    alt_m: float
    sensors_active: list  # e.g. ["rf", "acoustic"]
    last_heartbeat: float = field(default_factory=time.time)
    online: bool = True
    cpu_percent: float = 0.0
    mem_percent: float = 0.0

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "location": {"lat": self.lat, "lon": self.lon, "alt_m": self.alt_m},
            "sensors_active": self.sensors_active,
            "last_heartbeat": self.last_heartbeat,
            "online": self.online,
            "cpu_percent": self.cpu_percent,
            "mem_percent": self.mem_percent,
        }
