"""
artemis/api/websocket.py
FastAPI WebSocket endpoint for real-time threat feed.

The dashboard connects to ws://host:8080/ws and receives JSON threat
snapshots at ws_push_rate_hz (default 10 Hz from hub_default.yaml).

Message format: JSON array of threat objects (same as GET /threats).
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import WebSocket, WebSocketDisconnect

from artemis.core.logging import get_logger

if TYPE_CHECKING:
    from artemis.fusion.threat_map import ThreatMap

log = get_logger("api.websocket")


class ConnectionManager:
    """Tracks all active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        log.info("WS client connected  total=%d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        log.info("WS client disconnected  total=%d", len(self._connections))

    async def broadcast(self, payload: str) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


_manager = ConnectionManager()


def register_websocket(app, threat_map, ws_push_rate_hz: float = 10.0) -> None:
    """
    Register the /ws endpoint and a background broadcaster task on *app*.

    Call this after create_app() in hub/main.py:
        register_websocket(app, threat_map, cfg.api.ws_push_rate_hz)
    """
    push_interval = 1.0 / ws_push_rate_hz

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await _manager.connect(ws)
        try:
            # Keep connection alive; we push to client from the broadcaster task
            while True:
                # Echo any received message (ping/pong keepalive)
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            _manager.disconnect(ws)

    # register_websocket() is called after the app is constructed, so we
    # can't use the lifespan= parameter.  app.router.on_startup is the
    # non-deprecated equivalent of @app.on_event("startup") for this pattern.
    async def _start_broadcaster():
        asyncio.create_task(_broadcaster(threat_map, push_interval))

    app.router.on_startup.append(_start_broadcaster)


async def _broadcaster(threat_map, interval: float) -> None:
    """Push threat snapshots to all connected WebSocket clients."""
    while True:
        await asyncio.sleep(interval)
        if _manager.count == 0:
            continue
        try:
            snapshot = threat_map.get_snapshot()
            payload = json.dumps(snapshot, default=str)
            await _manager.broadcast(payload)
        except Exception as exc:
            log.error("broadcaster error: %s", exc)
