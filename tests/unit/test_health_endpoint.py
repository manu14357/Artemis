"""
tests/unit/test_health_endpoint.py
Unit tests for GET /health and GET /metrics REST endpoints.
"""
import time
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from artemis.api.rest import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(
    *,
    mqtt_connected: bool = True,
    agg_running: bool = True,
    last_fusion_ts: float | None = None,
    track_count: int = 0,
    publisher: bool = True,
):
    """Create a TestClient with configurable mock dependencies."""
    tm = MagicMock()
    tm.count = track_count
    tm.get_snapshot.return_value = []
    tm.get_threat.return_value = None

    agg = MagicMock()
    agg._running = agg_running
    agg._last_fusion_ts = last_fusion_ts
    agg.nodes = {}

    pub = None
    if publisher:
        pub = MagicMock()
        pub.connected = mqtt_connected

    app = create_app(tm, agg, publisher=pub)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /health tests
# ---------------------------------------------------------------------------

def test_health_ok_when_all_systems_nominal():
    """Returns status=ok when MQTT connected and fusion loop recent."""
    client = _make_app(
        mqtt_connected=True,
        agg_running=True,
        last_fusion_ts=time.time(),
        track_count=3,
    )
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mqtt_connected"] is True
    assert body["aggregator_running"] is True
    assert body["track_count"] == 3
    assert body["uptime_s"] >= 0


def test_health_degraded_when_mqtt_disconnected():
    """Returns status=degraded when publisher exists but MQTT is not connected."""
    client = _make_app(
        mqtt_connected=False,
        agg_running=True,
        last_fusion_ts=time.time(),
    )
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["mqtt_connected"] is False


def test_health_degraded_when_fusion_stale():
    """Returns status=degraded when last fusion timestamp is older than 5 s."""
    stale_ts = time.time() - 10.0   # 10 seconds ago
    client = _make_app(
        mqtt_connected=True,
        agg_running=True,
        last_fusion_ts=stale_ts,
    )
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["last_fusion_age_s"] is not None
    assert body["last_fusion_age_s"] > 5.0


def test_health_no_publisher_does_not_flag_degraded():
    """When no publisher is wired (dev mode), mqtt_connected=False does not degrade."""
    client = _make_app(publisher=False, last_fusion_ts=time.time())
    r = client.get("/health")
    body = r.json()
    # No publisher → mqtt_connected should be False but not cause degraded status
    assert body["mqtt_connected"] is False
    assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /metrics tests
# ---------------------------------------------------------------------------

def test_metrics_endpoint_returns_200():
    """GET /metrics returns 200 with Prometheus text content type."""
    client = _make_app()
    r = client.get("/metrics")
    assert r.status_code == 200


def test_metrics_endpoint_contains_artemis_prefix():
    """GET /metrics response body should contain 'artemis_' metric families."""
    client = _make_app()
    r = client.get("/metrics")
    assert "artemis_" in r.text


# ---------------------------------------------------------------------------
# GET /effectors tests
# ---------------------------------------------------------------------------

def test_effectors_returns_empty_list_when_no_manager():
    """GET /effectors returns [] when effector_manager is None."""
    client = _make_app()
    r = client.get("/effectors")
    assert r.status_code == 200
    assert r.json() == []


def test_effectors_returns_list_from_manager():
    """GET /effectors delegates to effector_manager.get_active_effectors()."""
    tm = MagicMock()
    tm.count = 0
    tm.get_snapshot.return_value = []
    tm.get_threat.return_value = None

    agg = MagicMock()
    agg._running = True
    agg._last_fusion_ts = None
    agg.nodes = {}

    em = MagicMock()
    em.get_active_effectors.return_value = ["jammer-01", "spoofer-01"]

    app = create_app(tm, agg, effector_manager=em)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.get("/effectors")
    assert r.status_code == 200
    assert r.json() == ["jammer-01", "spoofer-01"]
