"""
tests/integration/test_sim_to_hub.py
Integration test: drone_swarm simulator → MQTT → fusion → REST API.

Requires:
  - Mosquitto running on localhost:1883 (or pass ARTEMIS_BROKER env var)
  - All Python dependencies installed (paho-mqtt, fastapi, uvicorn, scipy, sklearn)

Run with:
    pytest tests/integration/test_sim_to_hub.py -v --timeout=30
"""

from __future__ import annotations

import os
import pathlib
import time

import pytest
import requests

# Skip if ARTEMIS_INTEGRATION env var is not set
pytestmark = pytest.mark.skipif(
    os.environ.get("ARTEMIS_INTEGRATION") != "1",
    reason="set ARTEMIS_INTEGRATION=1 to run integration tests",
)

HUB_CONFIG = pathlib.Path("hub/config/hub_default.yaml")
SCENARIO = pathlib.Path("sim/scenarios/single_drone.yaml")
BROKER_HOST = os.environ.get("ARTEMIS_BROKER", "127.0.0.1")
API_URL = "http://127.0.0.1:8080"
TIMEOUT_S = 20


@pytest.fixture(scope="module")
def hub_process():
    """Start hub/main.py as a subprocess."""
    import subprocess
    import sys

    proc = subprocess.Popen(
        [sys.executable, "hub/main.py", "--config", str(HUB_CONFIG), "--no-broker"],
        cwd=str(pathlib.Path(__file__).parent.parent.parent),
    )
    # Give the hub 3 s to start
    time.sleep(3)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture(scope="module")
def sim_process():
    """Start drone_swarm.py simulator as a subprocess."""
    import subprocess
    import sys

    proc = subprocess.Popen(
        [
            sys.executable,
            "sim/drone_swarm.py",
            "--scenario",
            str(SCENARIO),
            "--broker",
            BROKER_HOST,
            "--duration",
            "30",
            "--tick-hz",
            "20",
        ],
        cwd=str(pathlib.Path(__file__).parent.parent.parent),
    )
    time.sleep(2)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


class TestHubHealth:
    def test_hub_responds(self, hub_process):
        r = requests.get(f"{API_URL}/", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestThreatFlow:
    def test_threats_appear_after_sim_starts(self, hub_process, sim_process):
        """After the simulator runs for a few seconds, threats should appear in /threats."""
        # Wait up to TIMEOUT_S for at least 1 threat
        deadline = time.monotonic() + TIMEOUT_S
        threats = []
        while time.monotonic() < deadline:
            try:
                r = requests.get(f"{API_URL}/threats", timeout=2)
                if r.status_code == 200:
                    threats = r.json()
                    if threats:
                        break
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(0.5)

        assert len(threats) >= 1, f"No threats detected within {TIMEOUT_S}s"

    def test_threat_schema(self, hub_process, sim_process):
        r = requests.get(f"{API_URL}/threats", timeout=5)
        if r.status_code != 200:
            pytest.skip("hub not responding")
        threats = r.json()
        if not threats:
            pytest.skip("no threats available yet")
        t = threats[0]
        for key in ("threat_id", "track_id", "tier", "position", "sensor_layers"):
            assert key in t, f"missing key: {key}"
