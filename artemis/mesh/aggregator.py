"""
artemis/mesh/aggregator.py
Hub-side aggregator: collects detections from all nodes via MQTT,
batches them into fusion cycles, and feeds the TrackManager.

Architecture
------------
  MQTTSubscriber (paho background thread)
      │  puts Detection objects onto asyncio.Queue
      ▼
  MeshAggregator._detection_queue
      │  drained every fusion_cycle_s seconds
      ▼
  TrackManager.update(detections)
      │
      ▼
  ThreatMap.update(tracks)
      │
      ▼
  MQTTPublisher.publish_threats(snapshot)   ← publishes to artemis/threats
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Optional

from artemis.api.metrics import get_metrics
from artemis.core.config import HubConfig
from artemis.core.logging import get_logger
from artemis.core.types import NodeStatus
from artemis.fusion.threat_map import ThreatMap
from artemis.fusion.track_manager import TrackManager
from artemis.mesh.publisher import MQTTPublisher
from artemis.mesh.subscriber import MQTTSubscriber

if TYPE_CHECKING:
    from artemis.cognition.pipeline import CognitionPipeline

log = get_logger("mesh.aggregator")


class MeshAggregator:
    """
    Central hub component that:
      1. Subscribes to all node detection topics via MQTT.
      2. Runs a fusion loop at `fusion_cycle_hz` (default 10 Hz).
      3. Updates TrackManager and ThreatMap every cycle.
      4. Re-publishes the threat snapshot to `artemis/threats`.

    Parameters
    ----------
    config : HubConfig
    track_manager : TrackManager — pre-constructed with config parameters
    threat_map    : ThreatMap   — shared with the API layer
    publisher     : MQTTPublisher — for re-publishing threats
    fusion_cycle_hz : float — how often to run the fusion loop
    """

    def __init__(
        self,
        config: HubConfig,
        track_manager: TrackManager,
        threat_map: ThreatMap,
        publisher: MQTTPublisher,
        fusion_cycle_hz: float = 10.0,
        pipeline: Optional["CognitionPipeline"] = None,
    ) -> None:
        self._config = config
        self._track_manager = track_manager
        self._threat_map = threat_map
        self._publisher = publisher
        self._cycle_s = 1.0 / fusion_cycle_hz
        self._pipeline = pipeline

        # Node status registry {node_id: NodeStatus}
        self.nodes: dict[str, NodeStatus] = {}

        # Queue filled by MQTTSubscriber (thread-safe)
        self._detection_queue: asyncio.Queue = asyncio.Queue(maxsize=4096)

        self._subscriber: Optional[MQTTSubscriber] = None
        self._running = False
        # Timestamp of last successful fusion cycle — used by /health endpoint
        self._last_fusion_ts: Optional[float] = None
        self._metrics = get_metrics()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Initialise MQTT subscriber and connect to broker.
        Must be called before run().
        """
        cfg = self._config
        self._subscriber = MQTTSubscriber(
            detection_queue=self._detection_queue,
            node_topic_prefix=cfg.mqtt.node_topic_prefix,
            broker=cfg.mqtt.broker,
            port=cfg.mqtt.port,
            keepalive=cfg.mqtt.keepalive,
            username=cfg.mqtt.username,
            password=cfg.mqtt.password,
            hub_id=cfg.id,
        )
        self._subscriber.connect(loop=loop)
        log.info("MeshAggregator started, connected to broker=%s", cfg.mqtt.broker)

    def stop(self) -> None:
        self._running = False
        if self._subscriber:
            self._subscriber.disconnect()

    # ------------------------------------------------------------------
    # Fusion loop (async — run as asyncio task)
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Main async fusion loop.  Run with asyncio.create_task(aggregator.run()).
        """
        self._running = True
        log.info("fusion loop started cycle_s=%.3f", self._cycle_s)

        try:
            while self._running:
                try:
                    await asyncio.sleep(self._cycle_s)
                except asyncio.CancelledError:
                    # Propagate cleanly — marks the loop as stopped before exiting.
                    self._running = False
                    raise

                # Drain the detection queue, capped at 500 items per cycle to
                # avoid starving the event loop on burst traffic.
                detections = []
                _drained = 0
                while not self._detection_queue.empty() and _drained < 500:
                    det = self._detection_queue.get_nowait()
                    _drained += 1
                    if isinstance(det, NodeStatus):
                        self.nodes[det.node_id] = det
                    else:
                        detections.append(det)

                if not detections:
                    continue

                # Run fusion
                try:
                    with self._metrics.fusion_latency_timer():
                        tracks = self._track_manager.update(detections)
                        self._threat_map.update(
                            tracks,
                            eps_m=self._config.fusion.swarm.eps_m,
                            min_swarm_samples=self._config.fusion.swarm.min_samples,
                        )

                    self._last_fusion_ts = time.time()

                    # Record per-layer detection counts
                    for det in detections:
                        layer = getattr(det, "layer", None)
                        if layer is not None:
                            self._metrics.record_detection(str(layer))

                    # Update active tracks gauge
                    self._metrics.set_active_tracks(len(tracks))

                    # Re-publish threat snapshot over MQTT
                    snapshot = self._threat_map.get_snapshot()
                    if snapshot:
                        self._publisher.publish_threats(snapshot)
                        self._metrics.record_mqtt_publish("artemis/threats")
                        log.debug("published %d threats", len(snapshot))

                    # Run cognition pipeline (score → route → schedule → dispatch)
                    if self._pipeline:
                        self._pipeline.process(tracks)

                except Exception as exc:
                    log.error("fusion cycle error: %s", exc, exc_info=True)
        finally:
            self._running = False
