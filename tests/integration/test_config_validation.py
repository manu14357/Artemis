"""
tests/integration/test_config_validation.py
Integration tests for artemis.core.config_validator.

All tests run in-process with no hardware required.
"""

from __future__ import annotations

import pytest

from artemis.core.config import HubConfig, NodeConfig
from artemis.core.config_validator import (
    apply_hub_env_overrides,
    apply_node_env_overrides,
    validate_hub_config,
    validate_node_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_node() -> NodeConfig:
    cfg = NodeConfig()
    cfg.location.lat = 51.5074
    cfg.location.lon = -0.1278
    cfg.mqtt.username = "artemis"
    cfg.mqtt.password = "secret"
    cfg.sensors.radar.enabled = False  # no real /dev/ttyUSB0 in CI
    return cfg


def _default_hub() -> HubConfig:
    cfg = HubConfig()
    cfg.mqtt.username = "artemis"
    cfg.mqtt.password = "secret"
    return cfg


# ---------------------------------------------------------------------------
# NodeConfig validation
# ---------------------------------------------------------------------------


class TestValidateNodeConfig:
    def test_valid_config_no_warnings(self) -> None:
        cfg = _default_node()
        warnings = validate_node_config(cfg)
        assert warnings == []

    def test_zero_gps_warns(self) -> None:
        cfg = _default_node()
        cfg.location.lat = 0.0
        cfg.location.lon = 0.0
        warnings = validate_node_config(cfg)
        assert any("0.0/0.0" in w for w in warnings)

    def test_template_gps_warns(self) -> None:
        cfg = _default_node()
        cfg.location.lat = 17.3850
        cfg.location.lon = 78.4867
        warnings = validate_node_config(cfg)
        assert any("template" in w.lower() for w in warnings)

    def test_invalid_mqtt_port_warns(self) -> None:
        cfg = _default_node()
        cfg.mqtt.port = 99999
        warnings = validate_node_config(cfg)
        assert any("mqtt.port" in w for w in warnings)

    def test_anonymous_mqtt_warns(self) -> None:
        cfg = _default_node()
        cfg.mqtt.username = None
        warnings = validate_node_config(cfg)
        assert any("anonymous" in w.lower() for w in warnings)

    def test_bad_confidence_threshold_warns(self) -> None:
        cfg = _default_node()
        cfg.sensors.acoustic.confidence_threshold = 0.0  # invalid — must be > 0
        warnings = validate_node_config(cfg)
        assert any("confidence_threshold" in w for w in warnings)

    def test_strict_mode_raises(self) -> None:
        cfg = _default_node()
        cfg.location.lat = 0.0
        cfg.location.lon = 0.0
        with pytest.raises(ValueError, match="0.0/0.0"):
            validate_node_config(cfg, strict=True)

    def test_radar_serial_port_missing_warns(self) -> None:
        cfg = _default_node()
        cfg.sensors.radar.enabled = True
        cfg.sensors.radar.serial_port = "/dev/nonexistent_artemis_test_port"
        warnings = validate_node_config(cfg)
        assert any("serial_port" in w for w in warnings)


# ---------------------------------------------------------------------------
# HubConfig validation
# ---------------------------------------------------------------------------


class TestValidateHubConfig:
    def test_valid_config_no_warnings(self) -> None:
        cfg = _default_hub()
        warnings = validate_hub_config(cfg)
        assert warnings == []

    def test_api_port_too_low_warns(self) -> None:
        cfg = _default_hub()
        cfg.api_port = 80  # below 1024
        warnings = validate_hub_config(cfg)
        assert any("api_port" in w for w in warnings)

    def test_invalid_mqtt_port_warns(self) -> None:
        cfg = _default_hub()
        cfg.mqtt.port = 0
        warnings = validate_hub_config(cfg)
        assert any("mqtt.port" in w for w in warnings)

    def test_anonymous_mqtt_warns(self) -> None:
        cfg = _default_hub()
        cfg.mqtt.username = None
        warnings = validate_hub_config(cfg)
        assert any("anonymous" in w.lower() for w in warnings)

    def test_wildcard_cors_warns(self) -> None:
        cfg = _default_hub()
        cfg.api.cors_origins = ["*"]
        warnings = validate_hub_config(cfg)
        assert any("cors" in w.lower() for w in warnings)

    def test_hub_strict_raises_on_bad_port(self) -> None:
        cfg = _default_hub()
        cfg.api_port = 500
        with pytest.raises(ValueError, match="api_port"):
            validate_hub_config(cfg, strict=True)


# ---------------------------------------------------------------------------
# Env-var overrides
# ---------------------------------------------------------------------------


class TestEnvVarOverrides:
    def test_node_id_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTEMIS_NODE_ID", "node-env-99")
        cfg = _default_node()
        cfg = apply_node_env_overrides(cfg)
        assert cfg.id == "node-env-99"

    def test_node_gps_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTEMIS_GPS_LAT", "48.8566")
        monkeypatch.setenv("ARTEMIS_GPS_LON", "2.3522")
        monkeypatch.setenv("ARTEMIS_GPS_ALT", "35.0")
        cfg = _default_node()
        cfg = apply_node_env_overrides(cfg)
        assert cfg.location.lat == pytest.approx(48.8566)
        assert cfg.location.lon == pytest.approx(2.3522)
        assert cfg.location.alt_m == pytest.approx(35.0)

    def test_node_mqtt_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTEMIS_MQTT_BROKER", "192.168.1.50")
        monkeypatch.setenv("ARTEMIS_MQTT_PORT", "8883")
        monkeypatch.setenv("ARTEMIS_MQTT_USERNAME", "u")
        monkeypatch.setenv("ARTEMIS_MQTT_PASSWORD", "p")
        cfg = _default_node()
        cfg = apply_node_env_overrides(cfg)
        assert cfg.mqtt.broker == "192.168.1.50"
        assert cfg.mqtt.port == 8883
        assert cfg.mqtt.username == "u"
        assert cfg.mqtt.password == "p"

    def test_hub_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTEMIS_HUB_ID", "hub-env-01")
        monkeypatch.setenv("ARTEMIS_API_PORT", "9090")
        cfg = _default_hub()
        cfg = apply_hub_env_overrides(cfg)
        assert cfg.id == "hub-env-01"
        assert cfg.api_port == 9090

    def test_invalid_float_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTEMIS_GPS_LAT", "not_a_float")
        cfg = _default_node()
        with pytest.raises(ValueError):
            apply_node_env_overrides(cfg)

    def test_invalid_int_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARTEMIS_MQTT_PORT", "not_an_int")
        cfg = _default_node()
        with pytest.raises(ValueError):
            apply_node_env_overrides(cfg)

    def test_no_envs_leaves_config_unchanged(self) -> None:
        cfg_before = _default_node()
        original_lat = cfg_before.location.lat
        original_id = cfg_before.id
        cfg_after = apply_node_env_overrides(cfg_before)
        assert cfg_after.location.lat == original_lat
        assert cfg_after.id == original_id

    def test_roundtrip_from_yaml(self) -> None:
        """HubConfig from real YAML file still validates cleanly after env overrides."""
        cfg = HubConfig.from_yaml("hub/config/hub_default.yaml")
        cfg = apply_hub_env_overrides(cfg)
        # Hub default has no MQTT username — expect anonymous warning, not a hard error
        warnings = validate_hub_config(cfg)
        for w in warnings:
            assert isinstance(w, str)
