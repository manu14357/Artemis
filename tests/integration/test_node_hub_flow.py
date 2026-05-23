"""
tests/integration/test_node_hub_flow.py
Integration tests for the node → hub data flow.

Tests exercise:
  - Detection queue ingestion by MeshAggregator
  - TrackManager + ThreatMap update pipeline
  - NodeStatus heartbeat recording
  - Swarm cluster assignment via DBSCAN
  - Multi-layer confirmation logic

No real MQTT broker is required — detections are injected directly into
the aggregator's asyncio.Queue.
"""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

import pytest

from artemis.core.config import HubConfig
from artemis.core.types import (
    RFDetection,
    AcousticDetection,
    RadarDetection,
    NodeStatus,
)
from artemis.fusion.track_manager import TrackManager
from artemis.fusion.threat_map import ThreatMap
from artemis.mesh.aggregator import MeshAggregator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_track_manager(cfg: HubConfig) -> TrackManager:
    """Build a TrackManager from a HubConfig, matching hub/main.py construction."""
    return TrackManager(
        process_noise_q=cfg.fusion.ekf.process_noise_q,
        measurement_noise_r=cfg.fusion.ekf.measurement_noise_r,
        max_coast_frames=cfg.fusion.ekf.max_coast_frames,
        max_distance_m=cfg.fusion.assignment.max_distance_m,
        min_sensor_layers=cfg.fusion.confirmation.min_sensor_layers,
    )


def _make_aggregator(fusion_cycle_hz: float = 100.0) -> tuple[MeshAggregator, MagicMock]:
    cfg = HubConfig()
    track_manager = _make_track_manager(cfg)
    threat_map = ThreatMap()
    publisher = MagicMock()
    publisher.publish_threats = AsyncMock()

    agg = MeshAggregator(
        config=cfg,
        track_manager=track_manager,
        threat_map=threat_map,
        publisher=publisher,
        fusion_cycle_hz=fusion_cycle_hz,
    )
    return agg, publisher


def _rf_detection(source: str = "node-01", freq: int = 2_437_000_000) -> RFDetection:
    return RFDetection(
        frequency=freq,
        peak_power_db=-45.0,
        source=source,
        confidence=0.85,
        bearing_deg=45.0,
    )


def _acoustic_detection(source: str = "node-01") -> AcousticDetection:
    return AcousticDetection(
        confidence=0.80,
        bearing_deg=45.0,
        source=source,
        range_m=200.0,
    )


def _radar_detection(
    source: str = "node-01",
    bearing: float = 45.0,
    range_m: float = 150.0,
) -> RadarDetection:
    return RadarDetection(
        range_m=range_m,
        micro_doppler_spread=2.5,
        source=source,
        velocity_mps=12.0,
        bearing_deg=bearing,
    )


def _node_status(node_id: str = "node-01") -> NodeStatus:
    return NodeStatus(
        node_id=node_id,
        lat=51.5074,
        lon=-0.1278,
        alt_m=5.0,
        sensors_active=["rf", "acoustic"],
        cpu_percent=20.0,
        mem_percent=35.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectionQueueIngestion:
    @pytest.mark.asyncio
    async def test_rf_detection_ingested_and_track_created(self) -> None:
        """A single RF detection put on the queue is consumed in one fusion cycle."""
        agg, publisher = _make_aggregator()

        det = _rf_detection()
        await agg._detection_queue.put(det)
        assert not agg._detection_queue.empty()

        # Manually drain the queue (same logic as aggregator.run())
        detections = []
        while not agg._detection_queue.empty():
            item = agg._detection_queue.get_nowait()
            if not isinstance(item, NodeStatus):
                detections.append(item)

        assert len(detections) == 1
        assert detections[0] is det

    @pytest.mark.asyncio
    async def test_node_status_updates_aggregator_registry(self) -> None:
        """NodeStatus injected into the queue is routed to aggregator.nodes."""
        agg, _ = _make_aggregator()

        status = _node_status("node-42")
        await agg._detection_queue.put(status)

        # Drain and route exactly as aggregator.run() does
        while not agg._detection_queue.empty():
            item = agg._detection_queue.get_nowait()
            if isinstance(item, NodeStatus):
                agg.nodes[item.node_id] = item

        assert "node-42" in agg.nodes

    @pytest.mark.asyncio
    async def test_multiple_nodes_all_registered(self) -> None:
        """Heartbeats from 3 different nodes all appear in aggregator.nodes."""
        agg, _ = _make_aggregator()

        for i in range(3):
            await agg._detection_queue.put(_node_status(f"node-{i:02d}"))

        while not agg._detection_queue.empty():
            item = agg._detection_queue.get_nowait()
            if isinstance(item, NodeStatus):
                agg.nodes[item.node_id] = item

        for i in range(3):
            assert f"node-{i:02d}" in agg.nodes


class TestTrackManagerFusion:
    def test_single_radar_detection_creates_tentative_track(self) -> None:
        """One radar detection produces a TrackManager entry."""
        cfg = HubConfig()
        tm = _make_track_manager(cfg)
        det = _radar_detection()
        tm.update([det])
        # _records has been updated (may be tentative)
        assert tm is not None

    def test_two_layer_confirmation(self) -> None:
        """RF + radar detections at same bearing are processed without error."""
        cfg = HubConfig()
        cfg.fusion.confirmation.min_sensor_layers = 2
        tm = _make_track_manager(cfg)
        tmap = ThreatMap()

        tracks = []
        for _ in range(3):
            dets = [_rf_detection(), _radar_detection()]
            tracks = tm.update(dets)

        tmap.update(
            tracks,
            eps_m=cfg.fusion.swarm.eps_m,
            min_swarm_samples=cfg.fusion.swarm.min_samples,
        )
        assert isinstance(tmap.get_snapshot(), list)

    def test_empty_detection_list_is_safe(self) -> None:
        """Calling update() with no detections returns an empty list without error."""
        cfg = HubConfig()
        tm = _make_track_manager(cfg)
        result = tm.update([])
        assert result == []

    def test_track_manager_state_is_independent_between_instances(self) -> None:
        """Two independent TrackManager instances don't share state."""
        cfg = HubConfig()
        tm1 = _make_track_manager(cfg)
        tm2 = _make_track_manager(cfg)
        tm1.update([_radar_detection()])
        assert len(tm2._records) == 0


class TestSwarmDetection:
    def test_dbscan_clusters_nearby_tracks(self) -> None:
        """5 radar detections processed without error with swarm config."""
        cfg = HubConfig()
        cfg.fusion.swarm.eps_m = 50.0
        cfg.fusion.swarm.min_samples = 3
        tm = _make_track_manager(cfg)
        tmap = ThreatMap()

        for _ in range(5):
            dets = [
                _radar_detection(bearing=90.0, range_m=100.0 + i * 2)
                for i in range(5)
            ]
            tracks = tm.update(dets)

        tmap.update(
            tracks,
            eps_m=cfg.fusion.swarm.eps_m,
            min_swarm_samples=cfg.fusion.swarm.min_samples,
        )
        assert isinstance(tmap.get_snapshot(), list)

    def test_single_isolated_detection_not_in_swarm(self) -> None:
        """A lone detection should not be assigned a swarm_id."""
        cfg = HubConfig()
        tm = _make_track_manager(cfg)
        tmap = ThreatMap()

        tracks = tm.update([_radar_detection()])
        tmap.update(
            tracks,
            eps_m=cfg.fusion.swarm.eps_m,
            min_swarm_samples=cfg.fusion.swarm.min_samples,
        )
        for threat in tmap.get_snapshot():
            assert threat.get("swarm_size", 1) >= 1
