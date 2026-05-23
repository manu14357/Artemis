"""
artemis/api/rest.py
FastAPI REST endpoints for the ARTEMIS hub.

Endpoints
---------
GET  /           — root ping (no auth)
GET  /health     — detailed hub health (no auth)
GET  /metrics    — Prometheus text format (no auth)
GET  /status     — hub status + node registry
GET  /threats    — current threat snapshot (JSON list)
GET  /threats/{track_id}  — single threat by track id
GET  /nodes      — registered node statuses
GET  /effectors  — list of currently registered effector IDs
POST /commands/{effector_id}  — dispatch engagement command via MQTT [auth]
GET  /engagements             — recent engagement history (last 100)
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from artemis.api.auth import require_auth
from artemis.api.metrics import get_metrics

if TYPE_CHECKING:
    pass


class CommandBody(BaseModel):
    """Validated request body for POST /commands/{effector_id}."""
    action: str = Field(..., description="Action to execute, e.g. 'activate', 'deactivate'")
    duration_s: float = Field(5.0, ge=0.0, le=300.0, description="Engagement duration in seconds")


def create_app(
    threat_map,
    aggregator,
    cors_origins: list[str] | None = None,
    publisher=None,
    engagement_log=None,
    effector_manager=None,
    rate_limit_per_min: int = 60,
) -> FastAPI:
    """
    Factory that creates and configures the FastAPI application.

    Parameters
    ----------
    threat_map         : ThreatMap
    aggregator         : MeshAggregator (provides node registry + health)
    cors_origins       : list of allowed CORS origins
    publisher          : MQTTPublisher — for dispatching manual commands
    engagement_log     : EngagementLog — for GET /engagements
    effector_manager   : EffectorManager — for GET /effectors
    rate_limit_per_min : int — requests per IP per minute on rate-limited routes
    """
    metrics = get_metrics()

    # ── Rate limiter ────────────────────────────────────────────────────────
    limiter = Limiter(key_func=get_remote_address)
    limit_str = f"{rate_limit_per_min}/minute"

    app = FastAPI(
        title="ARTEMIS Hub API",
        description="Counter-drone multi-sensor fusion REST API",
        version="0.2.0",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── CORS ────────────────────────────────────────────────────────────────
    origins = cors_origins or ["http://localhost:3000", "http://localhost:4173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Track startup time for uptime reporting
    _start_time = time.time()

    # ------------------------------------------------------------------
    # Routes — open (no auth required)
    # ------------------------------------------------------------------

    @app.get("/")
    async def root():
        return {"status": "ok", "service": "artemis-hub"}

    @app.get("/health")
    async def health():
        """
        Detailed hub health check.

        Returns status='ok' when MQTT is connected and the fusion loop
        has run recently.  Returns status='degraded' if either condition
        fails.
        """
        mqtt_connected = publisher.connected if publisher is not None else False
        agg_running = getattr(aggregator, "_running", False)

        last_fusion_ts = getattr(aggregator, "_last_fusion_ts", None)
        last_fusion_age_s: Optional[float] = (
            round(time.time() - last_fusion_ts, 2) if last_fusion_ts is not None else None
        )

        track_count = threat_map.count if threat_map is not None else 0

        is_degraded = (
            (publisher is not None and not mqtt_connected)
            or (last_fusion_age_s is not None and last_fusion_age_s > 5.0)
        )

        return {
            "status": "degraded" if is_degraded else "ok",
            "mqtt_connected": mqtt_connected,
            "aggregator_running": agg_running,
            "last_fusion_age_s": last_fusion_age_s,
            "track_count": track_count,
            "uptime_s": round(time.time() - _start_time, 1),
        }

    @app.get("/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics():
        """Prometheus text-format metrics for scraping."""
        return Response(
            content=metrics.generate_text(),
            media_type=metrics.content_type,
        )

    # ------------------------------------------------------------------
    # Routes — rate-limited (read endpoints)
    # ------------------------------------------------------------------

    @app.get("/status")
    @limiter.limit(limit_str)
    async def status(request: Request):
        return {
            "status": "running",
            "threat_count": threat_map.count,
            "node_count": len(aggregator.nodes),
        }

    @app.get("/threats")
    @limiter.limit(limit_str)
    async def get_threats(request: Request):
        """Return all currently tracked threats as a JSON array."""
        return threat_map.get_snapshot()

    @app.get("/threats/{track_id}")
    @limiter.limit(limit_str)
    async def get_threat(track_id: str, request: Request):
        threat = threat_map.get_threat(track_id)
        if threat is None:
            raise HTTPException(status_code=404, detail="Threat not found")
        return threat.to_dict()

    @app.get("/nodes")
    @limiter.limit(limit_str)
    async def get_nodes(request: Request):
        """Return status for all known sensor nodes."""
        return [ns.to_dict() for ns in aggregator.nodes.values()]

    @app.get("/effectors")
    @limiter.limit(limit_str)
    async def get_effectors(request: Request):
        """Return the list of currently registered effector IDs."""
        if effector_manager is None:
            return []
        return effector_manager.get_active_effectors()

    @app.get("/engagements")
    @limiter.limit(limit_str)
    async def get_engagements(request: Request, limit: int = 100):
        """Return the most recent engagement records (newest first)."""
        if engagement_log is None:
            return {"engagements": []}
        n = max(1, min(limit, 500))
        return {"engagements": engagement_log.recent(n)}

    # ------------------------------------------------------------------
    # Routes — protected write endpoint (auth required)
    # ------------------------------------------------------------------

    @app.post("/commands/{effector_id}")
    async def send_command(
        effector_id: str,
        body: CommandBody,
        request: Request,
        _key: Optional[str] = Depends(require_auth),
    ):
        """
        Dispatch an engagement command to an effector via MQTT.

        Requires X-API-Key header when authentication is enabled.
        If no publisher is wired (test mode) the command is echoed back
        with status ``queued_simulation``.
        """
        command_dict = {
            "effector_id": effector_id,
            **body.model_dump(),
        }
        if publisher is not None:
            publisher.publish_command(effector_id, command_dict)
            metrics.record_mqtt_publish("artemis/commands")
            return {
                "effector_id": effector_id,
                "command": body.model_dump(),
                "status": "dispatched",
            }
        return {
            "effector_id": effector_id,
            "command": body.model_dump(),
            "status": "queued_simulation",
        }

    return app
