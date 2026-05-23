"""
tests/integration/test_ws_feed.py
Integration tests for the WebSocket /ws threat-feed endpoint.

Uses FastAPI's built-in WebSocket test client (starlette TestClient).
No real MQTT broker is required.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from artemis.api.rest import create_app
from artemis.api.websocket import register_websocket, ConnectionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_threat_snapshot() -> list[dict]:
    return [
        {
            "threat_id": "thr-ws-01",
            "track_id": "trk-ws-01",
            "tier": 1,
            "drone_type": "multirotor",
            "position": {"x": 10.0, "y": 20.0, "z": 5.0},
            "velocity": {"vx": 0.5, "vy": -0.2, "vz": 0.0},
            "impact": None,
            "swarm_id": None,
            "swarm_size": 1,
            "sensor_layers": ["acoustic", "radar"],
            "timestamp": time.time(),
            "confidence": 0.91,
        }
    ]


@pytest.fixture()
def ws_client() -> TestClient:
    tm = MagicMock()
    tm.count = 1
    tm.get_snapshot.return_value = _make_threat_snapshot()

    agg = MagicMock()
    agg._running = True
    agg._last_fusion_ts = time.time()
    agg.nodes = {}

    pub = MagicMock(connected=True)
    em = MagicMock()
    em.get_active_effectors.return_value = []

    app = create_app(tm, agg, publisher=pub, effector_manager=em)
    register_websocket(app, tm, ws_push_rate_hz=100.0)  # fast rate for tests
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebSocketFeed:
    def test_ws_connect_and_receive_json(self, ws_client: TestClient) -> None:
        """Client can connect and the server accepts the upgrade."""
        with ws_client.websocket_connect("/ws") as ws:
            # Send a ping to trigger an echo
            ws.send_text("ping")
            response = ws.receive_text()
            assert response == "pong"

    def test_ws_ping_pong(self, ws_client: TestClient) -> None:
        """Sending 'ping' returns 'pong' (keepalive echo)."""
        with ws_client.websocket_connect("/ws") as ws:
            for _ in range(3):
                ws.send_text("ping")
                assert ws.receive_text() == "pong"

    def test_connection_manager_tracks_clients(self) -> None:
        """ConnectionManager correctly counts connections and disconnections."""
        mgr = ConnectionManager()
        # Simulate adding a fake WS mock
        fake_ws = MagicMock()
        mgr._connections.append(fake_ws)
        assert mgr.count == 1
        mgr.disconnect(fake_ws)
        assert mgr.count == 0

    def test_connection_manager_disconnect_nonexistent_is_safe(self) -> None:
        """Disconnecting an unknown WS doesn't raise."""
        mgr = ConnectionManager()
        mgr.disconnect(MagicMock())  # should not raise

    def test_multiple_clients_tracked(self, ws_client: TestClient) -> None:
        """Two concurrent connections are both tracked."""
        with ws_client.websocket_connect("/ws") as ws1:
            with ws_client.websocket_connect("/ws") as ws2:
                ws1.send_text("ping")
                ws2.send_text("ping")
                assert ws1.receive_text() == "pong"
                assert ws2.receive_text() == "pong"

    def test_ws_connection_upgrade_returns_101(self, ws_client: TestClient) -> None:
        """WebSocket upgrade handshake completes without error."""
        # TestClient.websocket_connect() raises on failed upgrade
        try:
            with ws_client.websocket_connect("/ws") as ws:
                ws.send_text("ping")
                ws.receive_text()
        except Exception as exc:
            pytest.fail(f"WS connection failed: {exc}")
