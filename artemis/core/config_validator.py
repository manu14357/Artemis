"""
artemis/core/config_validator.py
Runtime validation and environment-variable override for ARTEMIS config objects.

Validation rules:
  - GPS coordinates must be non-zero (warns when left at template defaults)
  - MQTT port in 1–65535
  - API port in 1024–65535
  - Confidence thresholds in (0, 1]
  - Insecure defaults are flagged (anonymous MQTT, wildcard CORS, no-auth API)

Env-var overrides (all optional):
  ARTEMIS_NODE_ID         → node.id
  ARTEMIS_GPS_LAT         → node.location.lat
  ARTEMIS_GPS_LON         → node.location.lon
  ARTEMIS_GPS_ALT         → node.location.alt_m
  ARTEMIS_MQTT_BROKER     → mqtt.broker
  ARTEMIS_MQTT_PORT       → mqtt.port
  ARTEMIS_MQTT_USERNAME   → mqtt.username
  ARTEMIS_MQTT_PASSWORD   → mqtt.password
  ARTEMIS_HUB_ID          → hub.id
  ARTEMIS_API_PORT        → hub.api_port

Usage::

    from artemis.core.config import NodeConfig
    from artemis.core.config_validator import apply_node_env_overrides, validate_node_config

    cfg = NodeConfig.from_yaml("node/config/node_default.yaml")
    cfg = apply_node_env_overrides(cfg)
    warnings = validate_node_config(cfg)
    for w in warnings:
        log.warning("[config] %s", w)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from artemis.core.config import HubConfig, NodeConfig

# Template GPS coordinates used in node_default.yaml (Hyderabad, India)
_TEMPLATE_LAT = 17.3850
_TEMPLATE_LON = 78.4867


# ---------------------------------------------------------------------------
# Env-var helpers
# ---------------------------------------------------------------------------


def _env_str(key: str) -> str | None:
    return os.environ.get(key) or None


def _env_float(key: str) -> float | None:
    val = os.environ.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except ValueError as exc:
        raise ValueError(f"Env var {key}={val!r} is not a valid float") from exc


def _env_int(key: str) -> int | None:
    val = os.environ.get(key)
    if val is None:
        return None
    try:
        return int(val)
    except ValueError as exc:
        raise ValueError(f"Env var {key}={val!r} is not a valid integer") from exc


# ---------------------------------------------------------------------------
# Env-var overrides
# ---------------------------------------------------------------------------


def apply_node_env_overrides(cfg: "NodeConfig") -> "NodeConfig":
    """Apply ARTEMIS_* environment variables onto a NodeConfig in-place."""
    if (v := _env_str("ARTEMIS_NODE_ID")) is not None:
        cfg.id = v
    if (v := _env_float("ARTEMIS_GPS_LAT")) is not None:
        cfg.location.lat = v
    if (v := _env_float("ARTEMIS_GPS_LON")) is not None:
        cfg.location.lon = v
    if (v := _env_float("ARTEMIS_GPS_ALT")) is not None:
        cfg.location.alt_m = v
    if (v := _env_str("ARTEMIS_MQTT_BROKER")) is not None:
        cfg.mqtt.broker = v
    if (v := _env_int("ARTEMIS_MQTT_PORT")) is not None:
        cfg.mqtt.port = v
    if (v := _env_str("ARTEMIS_MQTT_USERNAME")) is not None:
        cfg.mqtt.username = v
    if (v := _env_str("ARTEMIS_MQTT_PASSWORD")) is not None:
        cfg.mqtt.password = v
    return cfg


def apply_hub_env_overrides(cfg: "HubConfig") -> "HubConfig":
    """Apply ARTEMIS_* environment variables onto a HubConfig in-place."""
    if (v := _env_str("ARTEMIS_HUB_ID")) is not None:
        cfg.id = v
    if (v := _env_int("ARTEMIS_API_PORT")) is not None:
        cfg.api_port = v
    if (v := _env_str("ARTEMIS_MQTT_BROKER")) is not None:
        cfg.mqtt.broker = v
    if (v := _env_int("ARTEMIS_MQTT_PORT")) is not None:
        cfg.mqtt.port = v
    if (v := _env_str("ARTEMIS_MQTT_USERNAME")) is not None:
        cfg.mqtt.username = v
    if (v := _env_str("ARTEMIS_MQTT_PASSWORD")) is not None:
        cfg.mqtt.password = v
    return cfg


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_node_config(cfg: "NodeConfig", strict: bool = False) -> list[str]:
    """
    Validate a NodeConfig and return a list of warning strings.
    In strict mode, raises ValueError on the first critical issue.
    """
    warnings: list[str] = []

    def _warn(msg: str) -> None:
        if strict:
            raise ValueError(msg)
        warnings.append(msg)

    # GPS
    lat, lon = cfg.location.lat, cfg.location.lon
    if lat == 0.0 and lon == 0.0:
        _warn(
            "GPS coordinates are 0.0/0.0 — set node.location.lat/lon in config or via env"
        )
    if abs(lat - _TEMPLATE_LAT) < 0.001 and abs(lon - _TEMPLATE_LON) < 0.001:
        _warn(
            "GPS coordinates still at template defaults (Hyderabad). "
            "Update node.location.lat/lon for your deployment."
        )

    # MQTT port
    if not (1 <= cfg.mqtt.port <= 65535):
        _warn(f"mqtt.port={cfg.mqtt.port} is out of range [1, 65535]")

    # Insecure: anonymous MQTT
    if cfg.mqtt.username is None:
        _warn(
            "mqtt.username is not set — broker is accessed anonymously. "
            "Set ARTEMIS_MQTT_USERNAME and ARTEMIS_MQTT_PASSWORD for production."
        )

    # Confidence thresholds
    ct = cfg.sensors.acoustic.confidence_threshold
    if not (0.0 < ct <= 1.0):
        _warn(f"sensors.acoustic.confidence_threshold={ct} must be in (0, 1]")

    # Radar serial port
    import os as _os

    port = cfg.sensors.radar.serial_port
    if cfg.sensors.radar.enabled and not _os.path.exists(port):
        warnings.append(
            f"sensors.radar.serial_port={port!r} does not exist. "
            "Use /dev/ttyUSB0 or /dev/ttyACM0 — or disable radar if not connected."
        )

    return warnings


def validate_hub_config(cfg: "HubConfig", strict: bool = False) -> list[str]:
    """
    Validate a HubConfig and return a list of warning strings.
    In strict mode, raises ValueError on the first critical issue.
    """
    warnings: list[str] = []

    def _warn(msg: str) -> None:
        if strict:
            raise ValueError(msg)
        warnings.append(msg)

    # API port
    if not (1024 <= cfg.api_port <= 65535):
        _warn(f"hub.api_port={cfg.api_port} should be in range [1024, 65535]")

    # MQTT port
    if not (1 <= cfg.mqtt.port <= 65535):
        _warn(f"mqtt.port={cfg.mqtt.port} is out of range [1, 65535]")

    # Insecure: anonymous MQTT
    if cfg.mqtt.username is None:
        _warn(
            "mqtt.username is not set — broker is accessed anonymously. "
            "Set ARTEMIS_MQTT_USERNAME and ARTEMIS_MQTT_PASSWORD for production."
        )

    # CORS wildcard
    origins = cfg.api.cors_origins
    if "*" in origins:
        _warn(
            "api.cors_origins contains '*' — this allows any origin. "
            "Restrict to known dashboard origins in production."
        )

    # ws_push_rate sanity
    rate = cfg.api.ws_push_rate_hz
    if not (0.1 <= rate <= 100.0):
        _warn(f"api.ws_push_rate_hz={rate} is outside sensible range [0.1, 100]")

    return warnings
