"""
artemis/api/rest.py
FastAPI REST endpoints for the ARTEMIS hub.

Endpoints
---------
GET  /           — health check
GET  /status     — hub status + node registry
GET  /threats    — current threat snapshot (JSON list)
GET  /threats/{track_id}  — single threat by track id
GET  /nodes      — registered node statuses
POST /commands/{effector_id}  — dispatch engagement command via MQTT
GET  /engagements             — recent engagement history (last 100)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from artemis.action.engagement_log import EngagementLog
    from artemis.mesh.aggregator import MeshAggregator
    from artemis.mesh.publisher import MQTTPublisher
    from artemis.fusion.threat_map import ThreatMap


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
) -> FastAPI:
    """
    Factory that creates and configures the FastAPI application.

    Parameters
    ----------
    threat_map     : ThreatMap
    aggregator     : MeshAggregator (provides node registry)
    cors_origins   : list of allowed CORS origins
    publisher      : MQTTPublisher — for dispatching manual commands
    engagement_log : EngagementLog — for GET /engagements
    """
    app = FastAPI(
        title="ARTEMIS Hub API",
        description="Counter-drone multi-sensor fusion REST API",
        version="0.1.0",
    )

    # CORS — allow dashboard origins
    origins = cors_origins or ["http://localhost:3000", "http://localhost:4173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/")
    async def health():
        return {"status": "ok", "service": "artemis-hub"}

    @app.get("/status")
    async def status():
        return {
            "status": "running",
            "threat_count": threat_map.count,
            "node_count": len(aggregator.nodes),
        }

    @app.get("/threats")
    async def get_threats():
        """Return all currently tracked threats as a JSON array."""
        return threat_map.get_snapshot()

    @app.get("/threats/{track_id}")
    async def get_threat(track_id: str):
        threat = threat_map.get_threat(track_id)
        if threat is None:
            raise HTTPException(status_code=404, detail="Threat not found")
        return threat.to_dict()

    @app.get("/nodes")
    async def get_nodes():
        """Return status for all known sensor nodes."""
        return [ns.to_dict() for ns in aggregator.nodes.values()]

    @app.post("/commands/{effector_id}")
    async def send_command(effector_id: str, body: CommandBody):
        """
        Dispatch an engagement command to an effector via MQTT.

        If no publisher is wired (test mode) the command is echoed back with
        status ``queued_simulation``.
        """
        command_dict = {
            "effector_id": effector_id,
            **body.model_dump(),
        }
        if publisher is not None:
            publisher.publish_command(effector_id, command_dict)
            return {
                "effector_id": effector_id,
                "command": body.model_dump(),
                "status": "dispatched",
            }
        # Fallback: simulation mode (no publisher wired)
        return {
            "effector_id": effector_id,
            "command": body.model_dump(),
            "status": "queued_simulation",
        }

    @app.get("/engagements")
    async def get_engagements(limit: int = 100):
        """Return the most recent engagement records (newest first)."""
        if engagement_log is None:
            return {"engagements": []}
        n = max(1, min(limit, 500))   # clamp to [1, 500]
        return {"engagements": engagement_log.recent(n)}

    return app
