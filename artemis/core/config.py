"""
artemis/core/config.py
YAML config loader with typed wrapper classes for hub and node configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Low-level loader
# ---------------------------------------------------------------------------


def load_yaml(path: str | Path) -> dict:
    """Load and return a YAML file as a plain dict. Raises if file not found."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p.resolve()}")
    with p.open("r") as fh:
        data = yaml.safe_load(fh) or {}
    return data


# ---------------------------------------------------------------------------
# Hub config
# ---------------------------------------------------------------------------


@dataclass
class EKFConfig:
    process_noise_q: float = 0.1
    measurement_noise_r: float = 0.5
    max_coast_frames: int = 10


@dataclass
class AssignmentConfig:
    max_distance_m: float = 50.0


@dataclass
class SwarmConfig:
    eps_m: float = 100.0
    min_samples: int = 3


@dataclass
class ConfirmationConfig:
    min_sensor_layers: int = 2


@dataclass
class FusionConfig:
    ekf: EKFConfig = field(default_factory=EKFConfig)
    assignment: AssignmentConfig = field(default_factory=AssignmentConfig)
    swarm: SwarmConfig = field(default_factory=SwarmConfig)
    confirmation: ConfirmationConfig = field(default_factory=ConfirmationConfig)


@dataclass
class MQTTConfig:
    broker: str = "127.0.0.1"
    port: int = 1883
    keepalive: int = 60
    node_topic_prefix: str = "artemis/nodes"
    threats_topic: str = "artemis/threats"
    commands_topic_prefix: str = "artemis/commands"
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class APIConfig:
    ws_push_rate_hz: float = 10.0
    cors_origins: list = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:4173",
        ]
    )


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/artemis-hub.log"
    rotate_mb: int = 100
    keep_backups: int = 10


@dataclass
class HubConfig:
    id: str = "hub-01"
    host: str = "0.0.0.0"
    api_port: int = 8080
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    api: APIConfig = field(default_factory=APIConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "HubConfig":
        raw = load_yaml(path)
        hub_raw = raw.get("hub", {})
        mqtt_raw = raw.get("mqtt", {})
        fusion_raw = raw.get("fusion", {})
        api_raw = raw.get("api", {})
        log_raw = raw.get("logging", {})

        ekf_raw = fusion_raw.get("ekf", {})
        assign_raw = fusion_raw.get("assignment", {})
        swarm_raw = fusion_raw.get("swarm", {})
        confirm_raw = fusion_raw.get("confirmation", {})

        return cls(
            id=hub_raw.get("id", "hub-01"),
            host=hub_raw.get("host", "0.0.0.0"),
            api_port=hub_raw.get("api_port", 8080),
            mqtt=MQTTConfig(
                broker=mqtt_raw.get("broker", "127.0.0.1"),
                port=mqtt_raw.get("port", 1883),
                keepalive=mqtt_raw.get("keepalive", 60),
                node_topic_prefix=mqtt_raw.get("node_topic_prefix", "artemis/nodes"),
                threats_topic=mqtt_raw.get("threats_topic", "artemis/threats"),
                commands_topic_prefix=mqtt_raw.get(
                    "commands_topic_prefix", "artemis/commands"
                ),
                username=mqtt_raw.get("username"),
                password=mqtt_raw.get("password"),
            ),
            fusion=FusionConfig(
                ekf=EKFConfig(
                    process_noise_q=ekf_raw.get("process_noise_q", 0.1),
                    measurement_noise_r=ekf_raw.get("measurement_noise_r", 0.5),
                    max_coast_frames=ekf_raw.get("max_coast_frames", 10),
                ),
                assignment=AssignmentConfig(
                    max_distance_m=assign_raw.get("max_distance_m", 50.0),
                ),
                swarm=SwarmConfig(
                    eps_m=swarm_raw.get("eps_m", 100.0),
                    min_samples=swarm_raw.get("min_samples", 3),
                ),
                confirmation=ConfirmationConfig(
                    min_sensor_layers=confirm_raw.get("min_sensor_layers", 2),
                ),
            ),
            api=APIConfig(
                ws_push_rate_hz=api_raw.get("ws_push_rate_hz", 10.0),
                cors_origins=api_raw.get(
                    "cors_origins",
                    [
                        "http://localhost:3000",
                        "http://localhost:4173",
                    ],
                ),
            ),
            logging=LoggingConfig(
                level=log_raw.get("level", "INFO"),
                file=log_raw.get("file", "logs/artemis-hub.log"),
                rotate_mb=log_raw.get("rotate_mb", 100),
                keep_backups=log_raw.get("keep_backups", 10),
            ),
        )


# ---------------------------------------------------------------------------
# Node config
# ---------------------------------------------------------------------------


@dataclass
class NodeLocation:
    lat: float = 0.0
    lon: float = 0.0
    alt_m: float = 0.0


@dataclass
class RFSensorConfig:
    enabled: bool = True
    frequencies: list = field(
        default_factory=lambda: [2_437_000_000, 5_780_000_000, 915_000_000]
    )
    fft_size: int = 1024
    threshold_db: float = -50.0


@dataclass
class AcousticSensorConfig:
    enabled: bool = True
    sample_rate: int = 16_000
    channels: int = 4
    device_index: int = 0
    window_ms: int = 500
    model_path: str = "models/acoustic_drone_cnn.tflite"
    confidence_threshold: float = 0.75


@dataclass
class RadarSensorConfig:
    enabled: bool = True
    serial_port: str = "/dev/ttyUSB0"
    start_point: int = 50
    num_points: int = 100
    step_length: int = 2
    profile: str = "PROFILE_5"


@dataclass
class OpticalSensorConfig:
    enabled: bool = True
    resolution: list = field(default_factory=lambda: [640, 480])
    fps: int = 30
    mog2_learning_rate: float = 0.005
    min_blob_area: int = 80


@dataclass
class SensorsConfig:
    rf: RFSensorConfig = field(default_factory=RFSensorConfig)
    acoustic: AcousticSensorConfig = field(default_factory=AcousticSensorConfig)
    radar: RadarSensorConfig = field(default_factory=RadarSensorConfig)
    optical: OpticalSensorConfig = field(default_factory=OpticalSensorConfig)


@dataclass
class NodeConfig:
    id: str = "node-01"
    location: NodeLocation = field(default_factory=NodeLocation)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "NodeConfig":
        raw = load_yaml(path)
        node_raw = raw.get("node", {})
        loc_raw = node_raw.get("location", {})
        sensors_raw = raw.get("sensors", {})
        mqtt_raw = raw.get("mqtt", {})

        rf_raw = sensors_raw.get("rf", {})
        ac_raw = sensors_raw.get("acoustic", {})
        rd_raw = sensors_raw.get("radar", {})
        op_raw = sensors_raw.get("optical", {})

        return cls(
            id=node_raw.get("id", "node-01"),
            location=NodeLocation(
                lat=loc_raw.get("lat", 0.0),
                lon=loc_raw.get("lon", 0.0),
                alt_m=loc_raw.get("alt_m", 0.0),
            ),
            sensors=SensorsConfig(
                rf=RFSensorConfig(
                    enabled=rf_raw.get("enabled", True),
                    frequencies=rf_raw.get(
                        "frequencies", [2_437_000_000, 5_780_000_000, 915_000_000]
                    ),
                    fft_size=rf_raw.get("fft_size", 1024),
                    threshold_db=rf_raw.get("threshold_db", -50.0),
                ),
                acoustic=AcousticSensorConfig(
                    enabled=ac_raw.get("enabled", True),
                    sample_rate=ac_raw.get("sample_rate", 16_000),
                    channels=ac_raw.get("channels", 4),
                    device_index=ac_raw.get("device_index", 0),
                    window_ms=ac_raw.get("window_ms", 500),
                    model_path=ac_raw.get(
                        "model_path", "models/acoustic_drone_cnn.tflite"
                    ),
                    confidence_threshold=ac_raw.get("confidence_threshold", 0.75),
                ),
                radar=RadarSensorConfig(
                    enabled=rd_raw.get("enabled", True),
                    serial_port=rd_raw.get("serial_port", "/dev/ttyUSB0"),
                    start_point=rd_raw.get("start_point", 50),
                    num_points=rd_raw.get("num_points", 100),
                    step_length=rd_raw.get("step_length", 2),
                    profile=rd_raw.get("profile", "PROFILE_5"),
                ),
                optical=OpticalSensorConfig(
                    enabled=op_raw.get("enabled", True),
                    resolution=op_raw.get("resolution", [640, 480]),
                    fps=op_raw.get("fps", 30),
                    mog2_learning_rate=op_raw.get("mog2_learning_rate", 0.005),
                    min_blob_area=op_raw.get("min_blob_area", 80),
                ),
            ),
            mqtt=MQTTConfig(
                broker=mqtt_raw.get("broker", "127.0.0.1"),
                port=mqtt_raw.get("port", 1883),
                keepalive=mqtt_raw.get("keepalive", 60),
                username=mqtt_raw.get("username"),
                password=mqtt_raw.get("password"),
            ),
        )
