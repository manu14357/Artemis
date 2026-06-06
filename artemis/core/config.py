"""
artemis/core/config.py
YAML config loader with typed wrapper classes for hub and node configuration.
"""

from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

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
    tls_enabled: bool = False


@dataclass
class APIConfig:
    ws_push_rate_hz: float = 10.0
    cors_origins: list = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:4173",
        ]
    )
    require_auth: bool = False
    rate_limit_per_min: int = 60


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/artemis-hub.log"
    rotate_mb: int = 100
    keep_backups: int = 10


@dataclass
class CognitionConfig:
    classifier_timeout_ms: int = 50
    predictor_timeout_ms: int = 20
    scheduler_timeout_ms: int = 10
    spoof_timeout_ms: int = 30
    backend: str = "local"


@dataclass
class SimRelayConfig:
    enabled: bool = True
    effector_id: str = "sim-relay-01"


@dataclass
class GPIORelayConfig:
    enabled: bool = False
    effector_id: str = "gpio-relay-01"
    pins: list = field(default_factory=lambda: [17, 27, 22, 23])
    default_duration_s: float = 5.0


@dataclass
class AudioDeterrentConfig:
    enabled: bool = False
    effector_id: str = "audio-deterrent-01"
    device_index: int = 0
    sample_rate: int = 48000
    max_duration_s: float = 30.0
    default_volume_db: float = -6.0
    sounds_dir: str = "assets/audio_deterrent"


@dataclass
class VisualDeterrentConfig:
    enabled: bool = False
    effector_id: str = "visual-deterrent-01"
    strobe_pin: int = 22
    laser_pin: int = 23
    strobe_frequency_hz: float = 10.0
    strobe_duty_cycle: float = 0.5
    laser_pwm_frequency_hz: int = 1000
    laser_max_duty_cycle: float = 0.5
    max_duration_s: float = 60.0
    cooldown_s: float = 5.0


@dataclass
class EffectorsConfig:
    sim_relay: SimRelayConfig = field(default_factory=SimRelayConfig)
    gpio_relay: GPIORelayConfig = field(default_factory=GPIORelayConfig)
    audio_deterrent: AudioDeterrentConfig = field(default_factory=AudioDeterrentConfig)
    visual_deterrent: VisualDeterrentConfig = field(default_factory=VisualDeterrentConfig)


@dataclass
class EngagementLogConfig:
    path: str = "logs/engagements.ndjson"
    max_recent: int = 500


@dataclass
class NodeLocation:
    lat: float = 0.0
    lon: float = 0.0
    alt_m: float = 0.0


@dataclass
class HubConfig:
    id: str = "hub-01"
    host: str = "0.0.0.0"
    api_port: int = 8080
    location: NodeLocation = field(default_factory=NodeLocation)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    api: APIConfig = field(default_factory=APIConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    cognition: CognitionConfig = field(default_factory=CognitionConfig)
    effectors: EffectorsConfig = field(default_factory=EffectorsConfig)
    engagement_log: EngagementLogConfig = field(default_factory=EngagementLogConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "HubConfig":
        raw = load_yaml(path)
        hub_raw = raw.get("hub", {})
        loc_raw = hub_raw.get("location", {})
        mqtt_raw = raw.get("mqtt", {})
        fusion_raw = raw.get("fusion", {})
        api_raw = raw.get("api", {})
        log_raw = raw.get("logging", {})
        cognition_raw = raw.get("cognition", {})
        effectors_raw = raw.get("effectors", {})
        engagement_log_raw = raw.get("engagement_log", {})

        ekf_raw = fusion_raw.get("ekf", {})
        assign_raw = fusion_raw.get("assignment", {})
        swarm_raw = fusion_raw.get("swarm", {})
        confirm_raw = fusion_raw.get("confirmation", {})

        sim_raw = effectors_raw.get("sim_relay", {})
        gpio_raw = effectors_raw.get("gpio_relay", {})
        audio_raw = effectors_raw.get("audio_deterrent", {})
        visual_raw = effectors_raw.get("visual_deterrent", {})

        return cls(
            id=hub_raw.get("id", "hub-01"),
            host=hub_raw.get("host", "0.0.0.0"),
            api_port=hub_raw.get("api_port", 8080),
            location=NodeLocation(
                lat=loc_raw.get("lat", 0.0),
                lon=loc_raw.get("lon", 0.0),
                alt_m=loc_raw.get("alt_m", 0.0),
            ),
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
                tls_enabled=mqtt_raw.get("tls_enabled", False),
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
                require_auth=api_raw.get("require_auth", False),
                rate_limit_per_min=api_raw.get("rate_limit_per_min", 60),
            ),
            logging=LoggingConfig(
                level=log_raw.get("level", "INFO"),
                file=log_raw.get("file", "logs/artemis-hub.log"),
                rotate_mb=log_raw.get("rotate_mb", 100),
                keep_backups=log_raw.get("keep_backups", 10),
            ),
            cognition=CognitionConfig(
                classifier_timeout_ms=cognition_raw.get("classifier_timeout_ms", 50),
                predictor_timeout_ms=cognition_raw.get("predictor_timeout_ms", 20),
                scheduler_timeout_ms=cognition_raw.get("scheduler_timeout_ms", 10),
                spoof_timeout_ms=cognition_raw.get("spoof_timeout_ms", 30),
                backend=cognition_raw.get("backend", "local"),
            ),
            effectors=EffectorsConfig(
                sim_relay=SimRelayConfig(
                    enabled=sim_raw.get("enabled", True),
                    effector_id=sim_raw.get("effector_id", "sim-relay-01"),
                ),
                gpio_relay=GPIORelayConfig(
                    enabled=gpio_raw.get("enabled", False),
                    effector_id=gpio_raw.get("effector_id", "gpio-relay-01"),
                    pins=gpio_raw.get("pins", [17, 27, 22, 23]),
                    default_duration_s=gpio_raw.get("default_duration_s", 5.0),
                ),
                audio_deterrent=AudioDeterrentConfig(
                    enabled=audio_raw.get("enabled", False),
                    effector_id=audio_raw.get("effector_id", "audio-deterrent-01"),
                    device_index=audio_raw.get("device_index", 0),
                    sample_rate=audio_raw.get("sample_rate", 48000),
                    max_duration_s=audio_raw.get("max_duration_s", 30.0),
                    default_volume_db=audio_raw.get("default_volume_db", -6.0),
                    sounds_dir=audio_raw.get("sounds_dir", "assets/audio_deterrent"),
                ),
                visual_deterrent=VisualDeterrentConfig(
                    enabled=visual_raw.get("enabled", False),
                    effector_id=visual_raw.get("effector_id", "visual-deterrent-01"),
                    strobe_pin=visual_raw.get("strobe_pin", 22),
                    laser_pin=visual_raw.get("laser_pin", 23),
                    strobe_frequency_hz=visual_raw.get("strobe_frequency_hz", 10.0),
                    strobe_duty_cycle=visual_raw.get("strobe_duty_cycle", 0.5),
                    laser_pwm_frequency_hz=visual_raw.get("laser_pwm_frequency_hz", 1000),
                    laser_max_duty_cycle=visual_raw.get("laser_max_duty_cycle", 0.5),
                    max_duration_s=visual_raw.get("max_duration_s", 60.0),
                    cooldown_s=visual_raw.get("cooldown_s", 5.0),
                ),
            ),
            engagement_log=EngagementLogConfig(
                path=engagement_log_raw.get("path", "logs/engagements.ndjson"),
                max_recent=engagement_log_raw.get("max_recent", 500),
            ),
        )


# ---------------------------------------------------------------------------
# Node config
# ---------------------------------------------------------------------------


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
    detector: str = "classical"  # "classical" or "yolo"
    resolution: list = field(default_factory=lambda: [640, 480])
    fps: int = 30
    # Classical detector params
    mog2_learning_rate: float = 0.005
    min_blob_area: int = 80
    # YOLO detector params
    yolo_model_path: str = "models/yolov8n_drone"
    yolo_confidence_threshold: float = 0.4
    yolo_backend: str = "auto"  # "ncnn", "onnx", "ultralytics", "auto"


@dataclass
class SensorsConfig:
    rf: RFSensorConfig = field(default_factory=RFSensorConfig)
    acoustic: AcousticSensorConfig = field(default_factory=AcousticSensorConfig)
    radar: RadarSensorConfig = field(default_factory=RadarSensorConfig)
    optical: OpticalSensorConfig = field(default_factory=OpticalSensorConfig)


@dataclass
class NodeEffectorsConfig:
    gpio_relay: GPIORelayConfig = field(default_factory=GPIORelayConfig)
    rf_jammer: dict = field(default_factory=dict)
    gps_spoofer: dict = field(default_factory=dict)


@dataclass
class NodeConfig:
    id: str = "node-01"
    location: NodeLocation = field(default_factory=NodeLocation)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    effectors: NodeEffectorsConfig = field(default_factory=NodeEffectorsConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "NodeConfig":
        raw = load_yaml(path)
        node_raw = raw.get("node", {})
        loc_raw = node_raw.get("location", {})
        sensors_raw = raw.get("sensors", {})
        mqtt_raw = raw.get("mqtt", {})
        logging_raw = raw.get("logging", {})
        effectors_raw = raw.get("effectors", {})

        rf_raw = sensors_raw.get("rf", {})
        ac_raw = sensors_raw.get("acoustic", {})
        rd_raw = sensors_raw.get("radar", {})
        op_raw = sensors_raw.get("optical", {})

        gpio_raw = effectors_raw.get("gpio_relay", {})

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
                    detector=op_raw.get("detector", "classical"),
                    resolution=op_raw.get("resolution", [640, 480]),
                    fps=op_raw.get("fps", 30),
                    mog2_learning_rate=op_raw.get("mog2_learning_rate", 0.005),
                    min_blob_area=op_raw.get("min_blob_area", 80),
                    yolo_model_path=op_raw.get("yolo_model_path", "models/yolov8n_drone"),
                    yolo_confidence_threshold=op_raw.get("yolo_confidence_threshold", 0.4),
                    yolo_backend=op_raw.get("yolo_backend", "auto"),
                ),
            ),
            mqtt=MQTTConfig(
                broker=mqtt_raw.get("broker", "127.0.0.1"),
                port=mqtt_raw.get("port", 1883),
                keepalive=mqtt_raw.get("keepalive", 60),
                username=mqtt_raw.get("username"),
                password=mqtt_raw.get("password"),
            ),
            logging=LoggingConfig(
                level=logging_raw.get("level", "INFO"),
                file=logging_raw.get("file", "logs/artemis-node.log"),
                rotate_mb=logging_raw.get("rotate_mb", 50),
                keep_backups=logging_raw.get("keep_backups", 5),
            ),
            effectors=NodeEffectorsConfig(
                gpio_relay=GPIORelayConfig(
                    enabled=gpio_raw.get("enabled", False),
                    effector_id=gpio_raw.get("effector_id", "gpio-relay-01"),
                    pins=gpio_raw.get("pins", [17, 27, 22, 23]),
                    default_duration_s=gpio_raw.get("default_duration_s", 5.0),
                ),
                rf_jammer=effectors_raw.get("rf_jammer", {}),
                gps_spoofer=effectors_raw.get("gps_spoofer", {}),
            ),
        )


# ---------------------------------------------------------------------------
# Config hot-reload watcher (polling-based, no external deps)
# ---------------------------------------------------------------------------


class ConfigWatcher:
    """
    Watches a YAML config file for changes and invokes a callback on reload.

    Uses mtime polling at ``poll_interval_s`` (default 2 s).
    Runs in a daemon thread — safe to start without affecting process lifecycle.

    Usage
    -----
        def on_reload(path: Path) -> None:
            new_cfg = HubConfig.from_yaml(path)
            # apply changes...

        watcher = ConfigWatcher("hub/config/hub_default.yaml", on_reload)
        watcher.start()   # non-blocking
        ...
        watcher.stop()    # clean shutdown
    """

    def __init__(
        self,
        path: str | Path,
        callback: Callable[[Path], None],
        poll_interval_s: float = 2.0,
    ) -> None:
        self._path = Path(path)
        self._callback = callback
        self._poll_interval = poll_interval_s
        self._last_mtime: float = 0.0
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start the background watcher thread."""
        if self._running:
            return
        try:
            self._last_mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._last_mtime = 0.0
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True, name="config-watcher")
        self._thread.start()

    def stop(self) -> None:
        """Stop the watcher thread (best-effort)."""
        self._running = False

    def _poll(self) -> None:
        while self._running:
            _time.sleep(self._poll_interval)
            try:
                mtime = self._path.stat().st_mtime
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    try:
                        self._callback(self._path)
                    except Exception as exc:  # noqa: BLE001
                        # Never let callback errors kill the watcher thread
                        import logging as _logging
                        _logging.getLogger("artemis.core.config_watcher").error(
                            "Config reload callback error: %s", exc
                        )
            except FileNotFoundError:
                pass  # File temporarily missing during atomic writes

