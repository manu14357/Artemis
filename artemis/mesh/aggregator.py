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
  Triangulation (RF/Acoustic multi-node bearing intersection)
      │
      ▼
  TrackManager.update(detections + triangulated positions)
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
from collections import defaultdict
from typing import TYPE_CHECKING, Optional

import numpy as np

from artemis.api.metrics import get_metrics
from artemis.core.config import HubConfig
from artemis.core.logging import get_logger
from artemis.core.types import (
    AcousticDetection,
    NodeStatus,
    RFDetection,
    SensorLayer,
)
from artemis.fusion.threat_map import ThreatMap
from artemis.fusion.track_manager import TrackManager
from artemis.mesh.publisher import MQTTPublisher
from artemis.mesh.subscriber import MQTTSubscriber
from artemis.mesh.triangulator import triangulate

if TYPE_CHECKING:
    from artemis.cognition.pipeline import CognitionPipeline

log = get_logger("mesh.aggregator")

# Time window (seconds) to correlate detections across nodes for triangulation
_TRIANGULATION_WINDOW_S = 0.5
# Minimum nodes required for triangulation
_MIN_TRIANGULATION_NODES = 2


class MeshAggregator:
    """
    Central hub component that:
      1. Subscribes to all node detection topics via MQTT.
      2. Runs a fusion loop at `fusion_cycle_hz` (default 10 Hz).
      3. Performs multi-node triangulation on RF/Acoustic bearings.
      4. Updates TrackManager and ThreatMap every cycle.
      5. Re-publishes the threat snapshot to `artemis/threats`.

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

        # Buffers for triangulation: {layer: {signature_key: [(node_id, lat, lon, bearing, timestamp), ...]}}
        self._bearing_buffers: dict[SensorLayer, dict[str, list[tuple]]] = {
            SensorLayer.RF: defaultdict(list),
            SensorLayer.ACOUSTIC: defaultdict(list),
        }

        self._subscriber: Optional[MQTTSubscriber] = None
        self._running = False
        # Timestamp of last successful fusion cycle — used by /health endpoint
        self._last_fusion_ts: Optional[float] = None
        self._metrics = get_metrics()

        # Reference position for triangulation (hub location)
        self._ref_lat = config.location.lat if hasattr(config, 'location') else 0.0
        self._ref_lon = config.location.lon if hasattr(config, 'location') else 0.0

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

                # Run triangulation on RF/Acoustic bearings before fusion
                triangulated_detections = self._run_triangulation(detections)
                all_detections = detections + triangulated_detections

                # Run fusion
                try:
                    with self._metrics.fusion_latency_timer():
                        tracks = self._track_manager.update(all_detections)
                        self._threat_map.update(
                            tracks,
                            eps_m=self._config.fusion.swarm.eps_m,
                            min_swarm_samples=self._config.fusion.swarm.min_samples,
                        )

                    self._last_fusion_ts = time.time()

                    # Record per-layer detection counts
                    for det in all_detections:
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

    # ------------------------------------------------------------------
    # Multi-node triangulation
    # ------------------------------------------------------------------

    def _run_triangulation(self, detections: list) -> list:
        """
        Correlate RF/Acoustic bearings across nodes and produce triangulated positions.

        Returns a list of synthetic detections with position (x, y) from triangulation.
        """
        if not self.nodes:
            return []

        now = time.time()
        cutoff = now - _TRIANGULATION_WINDOW_S
        new_triangulated = []

        # Process each layer that supports triangulation
        for layer in (SensorLayer.RF, SensorLayer.ACOUSTIC):
            buffer = self._bearing_buffers[layer]

            # Add new bearings to buffer
            for det in detections:
                if getattr(det, 'layer', None) != layer:
                    continue
                if not hasattr(det, 'bearing_deg') or det.bearing_deg is None:
                    continue
                node_id = det.source
                node = self.nodes.get(node_id)
                if not node or not node.online:
                    continue
                # Create signature key for correlation (frequency for RF, bearing bin for acoustic)
                if layer == SensorLayer.RF:
                    sig_key = f"freq_{det.frequency}"
                else:
                    sig_key = f"bearing_{int(det.bearing_deg // 10) * 10}"  # 10-degree bins
                buffer[sig_key].append((node_id, node.lat, node.lon, det.bearing_deg, det.timestamp))

            # Attempt triangulation for each signature
            to_remove = []
            for sig_key, bearings in buffer.items():
                # Filter recent bearings
                recent = [(nid, lat, lon, brg, ts) for nid, lat, lon, brg, ts in bearings if ts >= cutoff]
                if len(recent) < _MIN_TRIANGULATION_NODES:
                    # Keep old ones for a bit longer in case more arrive
                    buffer[sig_key] = recent
                    continue

                # Group by node (take latest per node)
                by_node = {}
                for nid, lat, lon, brg, ts in recent:
                    if nid not in by_node or ts > by_node[nid][4]:
                        by_node[nid] = (nid, lat, lon, brg, ts)

                if len(by_node) >= _MIN_TRIANGULATION_NODES:
                    node_bearings = {nid: (lat, lon, brg) for nid, lat, lon, brg, ts in by_node.values()}
                    result = triangulate(node_bearings, self._ref_lat, self._ref_lon)
                    if result:
                        x, y, confidence = result
                        # Create a synthetic detection with triangulated position
                        # Use the most recent timestamp
                        latest_ts = max(ts for _, _, _, _, ts in by_node.values())
                        if layer == SensorLayer.RF:
                            from artemis.core.types import RFDetection, DroneType
                            new_triangulated.append(RFDetection(
                                frequency=0,  # Will be filled from signature
                                peak_power_db=-50.0,
                                source="triangulator",
                                timestamp=latest_ts,
                                drone_type=DroneType.UNKNOWN,
                                confidence=confidence,
                                bearing_deg=None,  # Position known, bearing not needed
                            ))
                            # Override with position - hack via adding custom attribute
                            new_triangulated[-1]._triangulated_pos = (x, y, 0.0)
                        else:
                            from artemis.core.types import AcousticDetection, DroneType
                            new_triangulated.append(AcousticDetection(
                                confidence=confidence,
                                bearing_deg=0.0,
                                source="triangulator",
                                timestamp=latest_ts,
                                drone_type=DroneType.UNKNOWN,
                                range_m=None,
                            ))
                            new_triangulated[-1]._triangulated_pos = (x, y, 0.0)

                        log.debug("Triangulated %s: x=%.1f y=%.1f conf=%.2f nodes=%d",
                                 layer.value, x, y, confidence, len(by_node))

                to_remove.append(sig_key)

            # Clean up processed signatures
            for sig_key in to_remove:
                del buffer[sig_key]

            # Also clean old entries periodically
            for sig_key in list(buffer.keys()):
                buffer[sig_key] = [b for b in buffer[sig_key] if b[4] >= cutoff]
                if not buffer[sig_key]:
                    del buffer[sig_key]

        return new_triangulated
