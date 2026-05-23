"""
artemis/action/effectors/sim_relay.py
Simulation relay effector — subscribes to artemis/commands/{node_id} and logs
every engagement command received from the hub.

In production, this module would be replaced by a hardware effector that drives:
  - Electronic countermeasure (ECM) transmitter
  - Audio deterrent speaker
  - Net launcher

For simulation / testing, SimRelay simply logs the command and records it in
an in-memory ledger accessible via `SimRelay.history`.

Usage (standalone):
    relay = SimRelay(effector_id="sim-relay-01", broker="127.0.0.1")
    relay.start()   # blocks; call relay.stop() from another thread to exit

Usage (async / hub integration):
    relay = SimRelay(effector_id="sim-relay-01", broker=cfg.mqtt.broker)
    asyncio.get_event_loop().run_in_executor(None, relay.start)
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import paho.mqtt.client as mqtt

from artemis.cognition.agents.command_router import EngagementTier
from artemis.core.logging import get_logger

log = get_logger("action.sim_relay")


# ---------------------------------------------------------------------------
# Engagement record
# ---------------------------------------------------------------------------


@dataclass
class EngagementRecord:
    """Immutable record of one engagement command that was received + acted on."""

    effector_id: str
    track_id: str
    tier: EngagementTier
    score: float
    position: dict
    received_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "effector_id": self.effector_id,
            "track_id": self.track_id,
            "tier": self.tier.value,
            "score": self.score,
            "position": self.position,
            "received_at": self.received_at,
        }


# ---------------------------------------------------------------------------
# SimRelay effector
# ---------------------------------------------------------------------------


class SimRelay:
    """
    MQTT-subscribing simulation effector.

    Subscribes to ``artemis/commands/{effector_id}`` and logs each command.
    Thread-safe history list allows test assertions to inspect engagements.
    """

    def __init__(
        self,
        effector_id: str = "sim-relay-01",
        broker: str = "127.0.0.1",
        port: int = 1883,
        keepalive: int = 60,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.effector_id = effector_id
        self._broker = broker
        self._port = port
        self._topic = f"artemis/commands/{effector_id}"
        self._stop_flag = threading.Event()

        self._history: list[EngagementRecord] = []
        self._history_lock = threading.Lock()

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"artemis-relay-{effector_id}",
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def history(self) -> list[EngagementRecord]:
        """Thread-safe copy of engagement history."""
        with self._history_lock:
            return list(self._history)

    def start(self) -> None:
        """Connect to broker and start processing loop (blocks until stop())."""
        log.info(
            "SimRelay %s connecting to %s:%d topic=%s",
            self.effector_id,
            self._broker,
            self._port,
            self._topic,
        )
        self._client.connect(
            self._broker,
            self._port,
            self._keepalive if hasattr(self, "_keepalive") else 60,
        )
        self._client.loop_start()

        # Block until stop() is called
        self._stop_flag.wait()
        self._client.loop_stop()
        self._client.disconnect()
        log.info("SimRelay %s stopped", self.effector_id)

    def stop(self) -> None:
        """Signal the blocking start() call to return."""
        self._stop_flag.set()

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: dict,
        reason_code: object,
        properties: object = None,
    ) -> None:
        log.info("SimRelay %s connected to broker", self.effector_id)
        client.subscribe(self._topic, qos=1)
        log.info("SimRelay subscribed to %s", self._topic)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: object,
        reason_code: object,
        properties: object = None,
    ) -> None:
        log.warning("SimRelay %s disconnected (rc=%s)", self.effector_id, reason_code)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Handle an incoming command message."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.error("SimRelay bad payload on %s: %s", msg.topic, exc)
            return

        track_id = payload.get("track_id", "unknown")
        tier_str = payload.get("tier", "ignore")
        score = float(payload.get("score", 0.0))
        position = payload.get("position", {})

        try:
            tier = EngagementTier(tier_str)
        except ValueError:
            log.warning("SimRelay unknown tier '%s'", tier_str)
            tier = EngagementTier.IGNORE

        record = EngagementRecord(
            effector_id=self.effector_id,
            track_id=track_id,
            tier=tier,
            score=score,
            position=position,
        )

        with self._history_lock:
            self._history.append(record)

        self._execute(record)

    # ------------------------------------------------------------------
    # Simulated execution
    # ------------------------------------------------------------------

    def _execute(self, record: EngagementRecord) -> None:
        """
        Simulate the physical response to a command.
        In production, replace this with hardware actuation.
        """
        if record.tier == EngagementTier.ENGAGE_HARD:
            log.warning(
                "[SIM] HARD ENGAGE track=%s score=%.3f pos=%s",
                record.track_id,
                record.score,
                record.position,
            )
        elif record.tier == EngagementTier.ENGAGE_SOFT:
            log.info(
                "[SIM] SOFT ENGAGE (GPS spoof / audio) track=%s score=%.3f",
                record.track_id,
                record.score,
            )
        elif record.tier == EngagementTier.TRACK_ONLY:
            log.info(
                "[SIM] TRACK ONLY track=%s score=%.3f",
                record.track_id,
                record.score,
            )
        # IGNORE tier is filtered upstream — should not reach here
