"""
artemis/mesh/subscriber.py
MQTT subscriber — listens to all node sensor topics and deserialises
Detection objects, routing them into the internal EventBus.

Subscribed topics (hub side):
  artemis/nodes/+/rf
  artemis/nodes/+/acoustic
  artemis/nodes/+/radar
  artemis/nodes/+/optical
  artemis/nodes/+/status
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import paho.mqtt.client as mqtt

from artemis.core.bus import EventBus
from artemis.core.logging import get_logger
from artemis.core.types import (
    AcousticDetection,
    DroneType,
    NodeStatus,
    OpticalDetection,
    RadarDetection,
    RFDetection,
    SensorLayer,
)

log = get_logger("mesh.subscriber")

# Map sensor layer name → deserialiser
_LAYER_MAP = {
    "rf": SensorLayer.RF,
    "acoustic": SensorLayer.ACOUSTIC,
    "radar": SensorLayer.RADAR,
    "optical": SensorLayer.OPTICAL,
}


def _deserialise_detection(layer: str, node_id: str, payload: bytes):
    """Parse a raw MQTT payload into the appropriate Detection dataclass."""
    try:
        d = json.loads(payload)
    except json.JSONDecodeError:
        log.warning("invalid JSON from node=%s layer=%s", node_id, layer)
        return None

    try:
        if layer == "rf":
            return RFDetection(
                frequency=int(d.get("frequency", 0)),
                peak_power_db=float(d.get("peak_power_db", -100.0)),
                source=node_id,
                timestamp=float(d.get("timestamp", 0.0)),
                drone_type=DroneType(d.get("drone_type", "unknown")),
                confidence=float(d.get("confidence", 0.0)),
                bearing_deg=d.get("bearing_deg"),
            )

        if layer == "acoustic":
            return AcousticDetection(
                confidence=float(d.get("confidence", 0.0)),
                bearing_deg=float(d.get("bearing_deg", 0.0)),
                source=node_id,
                timestamp=float(d.get("timestamp", 0.0)),
                drone_type=DroneType(d.get("drone_type", "unknown")),
                range_m=d.get("range_m"),
            )

        if layer == "radar":
            return RadarDetection(
                range_m=float(d.get("range_m", 0.0)),
                micro_doppler_spread=float(d.get("micro_doppler_spread", 0.0)),
                source=node_id,
                timestamp=float(d.get("timestamp", 0.0)),
                velocity_mps=d.get("velocity_mps"),
                bearing_deg=d.get("bearing_deg"),
            )

        if layer == "optical":
            bbox_raw = d.get("bbox", [0, 0, 0, 0])
            bbox = tuple(bbox_raw) if isinstance(bbox_raw, list) else (0, 0, 0, 0)
            vel_raw = d.get("velocity", [0.0, 0.0])
            vel = tuple(vel_raw) if isinstance(vel_raw, list) else (0.0, 0.0)
            return OpticalDetection(
                bbox=bbox,
                area=float(d.get("area", 0.0)),
                velocity=vel,
                source=node_id,
                timestamp=float(d.get("timestamp", 0.0)),
                confidence=float(d.get("confidence", 1.0)),
                range_m=d.get("range_m"),
            )

    except (KeyError, ValueError, TypeError) as exc:
        log.warning("deserialise error layer=%s node=%s: %s", layer, node_id, exc)
        return None


def _deserialise_status(node_id: str, payload: bytes) -> Optional[NodeStatus]:
    try:
        d = json.loads(payload)
        loc = d.get("location", {})
        return NodeStatus(
            node_id=node_id,
            lat=float(loc.get("lat", 0.0)),
            lon=float(loc.get("lon", 0.0)),
            alt_m=float(loc.get("alt_m", 0.0)),
            sensors_active=d.get("sensors_active", []),
            last_heartbeat=float(d.get("last_heartbeat", 0.0)),
            online=bool(d.get("online", True)),
            cpu_percent=float(d.get("cpu_percent", 0.0)),
            mem_percent=float(d.get("mem_percent", 0.0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        log.warning("status deserialise error node=%s: %s", node_id, exc)
        return None


class MQTTSubscriber:
    """
    Subscribes to all node sensor topics and forwards parsed detections
    to the provided asyncio EventBus and/or a synchronous callback queue.

    Parameters
    ----------
    bus : EventBus | None
        If provided, publishes parsed detections to the bus.
    detection_queue : asyncio.Queue | None
        If provided, puts detections directly onto this queue (useful when
        the caller prefers a simpler pull-based approach).
    node_topic_prefix : str
    broker / port / keepalive / username / password : MQTT connection params
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        detection_queue: Optional[asyncio.Queue] = None,
        node_topic_prefix: str = "artemis/nodes",
        broker: str = "127.0.0.1",
        port: int = 1883,
        keepalive: int = 60,
        username: Optional[str] = None,
        password: Optional[str] = None,
        hub_id: str = "hub-01",
    ) -> None:
        self._bus = bus
        self._queue = detection_queue
        self._prefix = node_topic_prefix
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._client = mqtt.Client(
            client_id=f"artemis-sub-{hub_id}",
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._broker = broker
        self._port = port
        self._keepalive = keepalive
        self._connected = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Connect to broker and start the paho background thread."""
        self._loop = loop or asyncio.get_event_loop()
        self._client.connect(self._broker, self._port, self._keepalive)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    # ------------------------------------------------------------------
    # paho callbacks (called from paho background thread)
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc != 0:
            log.error("MQTT subscriber connect failed rc=%d", rc)
            return
        self._connected = True
        log.info("MQTT subscriber connected broker=%s", self._broker)

        # Subscribe to all node sensor + status topics
        for layer in ("rf", "acoustic", "radar", "optical", "status"):
            topic = f"{self._prefix}/+/{layer}"
            client.subscribe(topic, qos=0)
            log.debug("subscribed topic=%s", topic)

    def _on_disconnect(
        self, client, userdata, disconnect_flags, reason_code=None, properties=None
    ) -> None:
        """paho-mqtt v2 + MQTTv5 signature: 3rd arg is DisconnectFlags, not rc."""
        self._connected = False
        # reason_code is a ReasonCode object; rc == 0 means normal disconnect.
        rc = getattr(reason_code, "value", reason_code)
        if rc is not None and rc != 0:
            log.warning(
                "MQTT subscriber unexpected disconnect reason_code=%s", reason_code
            )

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        """Parse topic, deserialise payload, push to EventBus / queue."""
        topic = msg.topic
        parts = topic.split("/")
        # Expected format: artemis/nodes/{node_id}/{layer}
        if len(parts) < 4:
            return

        node_id = parts[2]
        layer = parts[3]

        if layer == "status":
            det = _deserialise_status(node_id, msg.payload)
        elif layer in _LAYER_MAP:
            det = _deserialise_detection(layer, node_id, msg.payload)
        else:
            return

        if det is None:
            return

        # Thread-safe delivery to asyncio world
        if self._loop and self._queue is not None:

            def _safe_put(q=self._queue, item=det):
                try:
                    q.put_nowait(item)
                except asyncio.QueueFull:
                    log.warning(
                        "detection queue full; dropping detection from node=%s", node_id
                    )

            self._loop.call_soon_threadsafe(_safe_put)

        if self._bus and self._loop:
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._bus.publish(topic, det),
            )

    @property
    def connected(self) -> bool:
        return self._connected
