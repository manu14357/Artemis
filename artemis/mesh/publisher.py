"""
artemis/mesh/publisher.py
MQTT publisher — serialises Detection / NodeStatus objects and publishes them
to the broker under the artemis topic hierarchy.

Topic schema (from hub_default.yaml):
  artemis/nodes/{node_id}/rf
  artemis/nodes/{node_id}/acoustic
  artemis/nodes/{node_id}/radar
  artemis/nodes/{node_id}/optical
  artemis/nodes/{node_id}/status
  artemis/threats             ← hub publishes here
  artemis/commands/{id}       ← hub publishes engagement commands here
"""
from __future__ import annotations

import dataclasses
import json
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt

from artemis.core.logging import get_logger
from artemis.core.types import (
    AcousticDetection,
    NodeStatus,
    OpticalDetection,
    RadarDetection,
    RFDetection,
)

log = get_logger("mesh.publisher")


def _serialise(obj: Any) -> str:
    """Convert a dataclass (or dict) to a compact JSON string."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = dataclasses.asdict(obj)
    elif isinstance(obj, dict):
        d = obj
    else:
        d = {"value": str(obj)}
    return json.dumps(d, default=str)


class MQTTPublisher:
    """
    Wraps a paho MQTT client for publishing sensor detections.

    Parameters
    ----------
    node_id : str           — node identifier, used in topic paths
    broker  : str           — MQTT broker hostname / IP
    port    : int           — MQTT broker port (default 1883)
    keepalive : int         — keepalive interval in seconds
    username / password     — optional broker authentication
    node_topic_prefix : str — e.g. 'artemis/nodes'
    """

    def __init__(
        self,
        node_id: str,
        broker: str = "127.0.0.1",
        port: int = 1883,
        keepalive: int = 60,
        username: Optional[str] = None,
        password: Optional[str] = None,
        node_topic_prefix: str = "artemis/nodes",
    ) -> None:
        self.node_id = node_id
        self._prefix = f"{node_topic_prefix}/{node_id}"
        self._threats_topic = "artemis/threats"
        self._commands_prefix = "artemis/commands"

        self._client = mqtt.Client(
            client_id=f"artemis-pub-{node_id}",
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_publish = self._on_publish

        self._broker = broker
        self._port = port
        self._keepalive = keepalive
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._client.connect(self._broker, self._port, self._keepalive)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    # ------------------------------------------------------------------
    # Publish helpers
    # ------------------------------------------------------------------

    def publish_rf(self, det: RFDetection) -> None:
        self._publish(f"{self._prefix}/rf", det)

    def publish_acoustic(self, det: AcousticDetection) -> None:
        self._publish(f"{self._prefix}/acoustic", det)

    def publish_radar(self, det: RadarDetection) -> None:
        self._publish(f"{self._prefix}/radar", det)

    def publish_optical(self, det: OpticalDetection) -> None:
        self._publish(f"{self._prefix}/optical", det)

    def publish_status(self, status: NodeStatus) -> None:
        self._publish(f"{self._prefix}/status", status)

    def publish_threats(self, threats: list[dict]) -> None:
        payload = json.dumps(threats, default=str)
        self._client.publish(self._threats_topic, payload, qos=0)

    def publish_command(self, effector_id: str, command: dict) -> None:
        topic = f"{self._commands_prefix}/{effector_id}"
        self._publish(topic, command)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _publish(self, topic: str, obj: Any) -> None:
        if not self._connected:
            log.warning("not connected, dropping publish to %s", topic)
            return
        payload = _serialise(obj)
        result = self._client.publish(topic, payload, qos=0)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            log.error("publish failed topic=%s rc=%d", topic, result.rc)

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc == 0:
            self._connected = True
            log.info("MQTT publisher connected broker=%s node_id=%s",
                     self._broker, self.node_id)
        else:
            log.error("MQTT publisher connect failed rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc, properties=None) -> None:
        self._connected = False
        if rc != 0:
            log.warning("MQTT publisher unexpected disconnect rc=%d", rc)

    def _on_publish(self, client, userdata, mid, properties=None) -> None:
        pass   # no-op; retained for debug hook

    @property
    def connected(self) -> bool:
        return self._connected
