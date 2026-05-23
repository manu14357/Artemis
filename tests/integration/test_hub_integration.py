"""
tests/integration/test_hub_integration.py
Integration-level smoke tests for the ARTEMIS hub.

These tests spin up the real FastAPI app (without a live MQTT broker)
and exercise the full HTTP stack including routing, CORS, middleware, and
the key API contracts expected by the dashboard and sensor nodes.

All heavy I/O (MQTT, sensors) is replaced with MagicMock stubs.
"""
import time
from unittest.mock import MagicMock, patch
import os
import importlib

import pytest
from fastapi.testclient import TestClient

from artemis.api.rest import create_app
from artemis.api.metrics import get_metrics


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Minimal hub app with all external dependencies mocked out."""
    tm = MagicMock()
    tm.count = 2
    tm.get_snapshot.return_value = [
        {
            "threat_id": "t-001",
            "track_id": "k-001",
            "tier": 3,
            "drone_type": "multirotor",
            "position": {"x": 100, "y": 50, "z": 20},
            "velocity": {"vx": -1.0, "vy": 0.5, "vz": 0.0},
            "impact": None,
            "swarm_id": None,
            "swarm_size": 1,
            "sensor_layers": ["rf", "acoustic"],
            "timestamp": time.time(),
            "confidence": 0.87,
        }
    ]
    tm.get_threat.return_value = None

    agg = MagicMock()
    agg._running = True
    agg._last_fusion_ts = time.time()
    agg.nodes = {}

    pub = MagicMock()
    pub.connected = True

    em = MagicMock()
    em.get_active_effectors.return_value = ["jammer-01", "relay-01"]

    app = create_app(tm, agg, publisher=pub, effector_manager=em)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_root_returns_ok(client):
    """GET / returns {"status": "ok", "service": "artemis-hub"}."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "artemis-hub"


def test_health_endpoint_structure(client):
    """GET /health response contains all required keys."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for key in ("status", "mqtt_connected", "aggregator_running", "track_count", "uptime_s"):
        assert key in body, f"Missing key: {key}"


def test_threats_endpoint_returns_list(client):
    """GET /threats returns a JSON array (even if empty)."""
    r = client.get("/threats")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


def test_metrics_scrape_contains_artemis_labels(client):
    """GET /metrics Prometheus output contains artemis namespace."""
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "artemis_" in r.text


def test_effectors_endpoint_returns_list(client):
    """GET /effectors returns the list from effector_manager."""
    r = client.get("/effectors")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert "jammer-01" in data


def test_command_without_auth_allowed_in_open_mode(client):
    """In open mode (no ARTEMIS_API_KEYS), POST /commands succeeds without a key."""
    # Reload auth in open mode
    import artemis.api.auth as auth_mod
    clean_env = {k: v for k, v in os.environ.items() if k != "ARTEMIS_API_KEYS"}
    with patch.dict(os.environ, clean_env, clear=True):
        importlib.reload(auth_mod)

    r = client.post("/commands/jammer-01", json={"action": "activate", "duration_s": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["effector_id"] == "jammer-01"


def test_classifier_agent_importable():
    """ClassifierAgent can be imported and instantiated (Bug #5 regression guard)."""
    from artemis.cognition.agents.classifier_agent import ClassifierAgent
    agent = ClassifierAgent()
    assert agent is not None


def test_cognition_pipeline_accepts_classifier():
    """CognitionPipeline.__init__ accepts a ClassifierAgent without error."""
    from unittest.mock import MagicMock
    from artemis.cognition.pipeline import CognitionPipeline
    from artemis.cognition.agents.classifier_agent import ClassifierAgent
    pipeline = CognitionPipeline(
        scorer=MagicMock(),
        router=MagicMock(),
        scheduler=MagicMock(),
        publisher=MagicMock(),
        engagement_log=MagicMock(),
        classifier=ClassifierAgent(),
    )
    assert pipeline is not None
