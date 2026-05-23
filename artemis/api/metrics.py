"""
artemis/api/metrics.py
Prometheus metrics for the ARTEMIS hub.

Exposes a singleton ``ArtemisMetrics`` instance that instruments:
  - Detection throughput per sensor layer
  - Active track count (gauge)
  - Fusion cycle latency (histogram)
  - Engagement decisions by tier (counter)
  - WebSocket client count (gauge)
  - MQTT messages published (counter)
  - Hub up/healthy (gauge)

Usage
-----
    from artemis.api.metrics import get_metrics

    metrics = get_metrics()
    metrics.record_detection("rf")
    with metrics.fusion_latency_timer():
        ...

GET /metrics serves Prometheus text format via ``generate_text()``.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# ---------------------------------------------------------------------------
# Singleton registry — isolated from the default registry so tests can reset it
# ---------------------------------------------------------------------------

_registry = CollectorRegistry(auto_describe=True)


class ArtemisMetrics:
    """Prometheus instrumentation for the Artemis hub."""

    def __init__(self) -> None:
        # Counters — monotonically increasing
        self.detections_total = Counter(
            "artemis_detections_total",
            "Number of raw detections received from sensor nodes",
            ["layer"],
            registry=_registry,
        )
        self.engagements_total = Counter(
            "artemis_engagements_total",
            "Number of engagement decisions dispatched by the cognition pipeline",
            ["tier"],
            registry=_registry,
        )
        self.mqtt_messages_total = Counter(
            "artemis_mqtt_messages_total",
            "Number of MQTT messages published by the hub",
            ["topic_prefix"],
            registry=_registry,
        )

        # Gauges — current snapshot values
        self.active_tracks = Gauge(
            "artemis_active_tracks",
            "Number of currently tracked threats in the threat map",
            registry=_registry,
        )
        self.ws_clients_connected = Gauge(
            "artemis_ws_clients_connected",
            "Number of WebSocket clients currently connected to /ws",
            registry=_registry,
        )
        self.hub_up = Gauge(
            "artemis_up",
            "1 if the hub is running and MQTT is connected, 0 otherwise",
            registry=_registry,
        )

        # Histogram — fusion cycle duration
        self.fusion_latency = Histogram(
            "artemis_fusion_latency_seconds",
            "Duration of a single fusion cycle (EKF + Hungarian + threat map update)",
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            registry=_registry,
        )

        # Mark hub as up on creation
        self.hub_up.set(1)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def record_detection(self, layer: str) -> None:
        """Increment detection counter for a sensor layer."""
        self.detections_total.labels(layer=layer).inc()

    def record_engagement(self, tier: str) -> None:
        """Increment engagement counter for an engagement tier."""
        self.engagements_total.labels(tier=tier).inc()

    def record_mqtt_publish(self, topic_prefix: str) -> None:
        """Increment MQTT publish counter."""
        self.mqtt_messages_total.labels(topic_prefix=topic_prefix).inc()

    def set_active_tracks(self, count: int) -> None:
        """Update active track gauge."""
        self.active_tracks.set(count)

    def set_ws_clients(self, count: int) -> None:
        """Update WebSocket client gauge."""
        self.ws_clients_connected.set(count)

    def set_hub_up(self, up: bool) -> None:
        """Set the hub health gauge."""
        self.hub_up.set(1 if up else 0)

    @contextmanager
    def fusion_latency_timer(self) -> Iterator[None]:
        """Context manager that records fusion cycle latency automatically."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.fusion_latency.observe(elapsed)

    def generate_text(self) -> bytes:
        """Return Prometheus text-format metrics."""
        return generate_latest(_registry)

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: ArtemisMetrics | None = None


def get_metrics() -> ArtemisMetrics:
    """Return the module-level singleton, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = ArtemisMetrics()
    return _instance
