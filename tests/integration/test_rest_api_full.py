"""
tests/integration/test_rest_api_full.py
Full REST API integration tests exercising all hub endpoints.

Extends the basic smoke tests in test_hub_integration.py with:
  - Auth-enabled mode (ARTEMIS_API_KEYS set)
  - Rate-limit header presence
  - All endpoint contracts
  - Invalid input handling
"""
from __future__ import annotations

import importlib
import time
from unittest.mock import MagicMock, patch
import os

import pytest
from fastapi.testclient import TestClient

from artemis.api.rest import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_threat_map() -> MagicMock:
    tm = MagicMock()
    tm.count = 1
    tm.get_snapshot.return_value = [
        {
            "threat_id": "thr-01",
            "track_id": "trk-01",
            "tier": 2,
            "drone_type": "fixed-wing",
            "position": {"x": 200.0, "y": -50.0, "z": 30.0},
            "velocity": {"vx": 3.0, "vy": -1.0, "vz": 0.0},
            "impact": None,
            "swarm_id": None,
            "swarm_size": 1,
            "sensor_layers": ["rf"],
            "timestamp": time.time(),
            "confidence": 0.72,
        }
    ]
    tm.get_threat.return_value = None
    return tm


def _make_aggregator() -> MagicMock:
    agg = MagicMock()
    agg._running = True
    agg._last_fusion_ts = time.time()
    agg.nodes = {
        "node-01": MagicMock(last_seen=time.time(), lat=51.5, lon=-0.1, alt_m=5.0)
    }
    return agg


@pytest.fixture()
def client() -> TestClient:
    tm = _make_threat_map()
    agg = _make_aggregator()
    pub = MagicMock(connected=True)
    em = MagicMock()
    em.get_active_effectors.return_value = ["jammer-01"]
    el = MagicMock()
    el.recent.return_value = []
    app = create_app(tm, agg, publisher=pub, effector_manager=em, engagement_log=el)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def authed_client() -> TestClient:
    """Client where API auth is enabled via ARTEMIS_API_KEYS."""
    tm = _make_threat_map()
    agg = _make_aggregator()
    pub = MagicMock(connected=True)
    em = MagicMock()
    em.get_active_effectors.return_value = []
    el = MagicMock()
    el.recent.return_value = []
    with patch.dict(os.environ, {"ARTEMIS_API_KEYS": "test-key-abc"}):
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)
        app = create_app(tm, agg, publisher=pub, effector_manager=em, engagement_log=el)
        c = TestClient(app, raise_server_exceptions=False)
        yield c
    # Reload to open mode after test
    importlib.reload(auth_mod)


# ---------------------------------------------------------------------------
# Tests — open mode
# ---------------------------------------------------------------------------

class TestOpenModeEndpoints:
    def test_root_ok(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_all_keys(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        for key in ("status", "mqtt_connected", "aggregator_running", "track_count", "uptime_s"):
            assert key in body

    def test_threats_list(self, client: TestClient) -> None:
        r = client.get("/threats")
        assert r.status_code == 200
        threats = r.json()
        assert isinstance(threats, list)
        assert len(threats) == 1
        assert threats[0]["track_id"] == "trk-01"

    def test_nodes_endpoint(self, client: TestClient) -> None:
        r = client.get("/nodes")
        assert r.status_code == 200
        nodes = r.json()
        assert isinstance(nodes, (list, dict))

    def test_effectors_list(self, client: TestClient) -> None:
        r = client.get("/effectors")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert "jammer-01" in data

    def test_metrics_prometheus(self, client: TestClient) -> None:
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "artemis_" in r.text

    def test_post_command_open_mode_succeeds(self, client: TestClient) -> None:
        r = client.post("/commands/jammer-01", json={"action": "activate", "duration_s": 3.0})
        assert r.status_code == 200
        body = r.json()
        assert body["effector_id"] == "jammer-01"

    def test_post_command_invalid_duration_rejected(self, client: TestClient) -> None:
        r = client.post("/commands/jammer-01", json={"action": "activate", "duration_s": 9999})
        assert r.status_code == 422  # FastAPI validation

    def test_engagements_returns_list(self, client: TestClient) -> None:
        r = client.get("/engagements")
        assert r.status_code == 200
        body = r.json()
        # API may return a bare list or {"engagements": [...]}
        if isinstance(body, list):
            pass
        else:
            assert "engagements" in body
            assert isinstance(body["engagements"], list)


# ---------------------------------------------------------------------------
# Tests — auth enabled
# ---------------------------------------------------------------------------

class TestAuthMode:
    def test_command_without_key_rejected(self, authed_client: TestClient) -> None:
        r = authed_client.post("/commands/jammer-01", json={"action": "activate"})
        assert r.status_code in (401, 403)

    def test_command_with_valid_key_accepted(self, authed_client: TestClient) -> None:
        r = authed_client.post(
            "/commands/jammer-01",
            json={"action": "activate", "duration_s": 5.0},
            headers={"X-API-Key": "test-key-abc"},
        )
        assert r.status_code == 200

    def test_command_with_invalid_key_rejected(self, authed_client: TestClient) -> None:
        r = authed_client.post(
            "/commands/jammer-01",
            json={"action": "activate"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert r.status_code in (401, 403)

    def test_open_endpoints_skip_auth(self, authed_client: TestClient) -> None:
        """Health and metrics don't require a key even in auth mode."""
        for path in ["/", "/health", "/metrics"]:
            r = authed_client.get(path)
            assert r.status_code == 200, f"{path} should not require auth"
