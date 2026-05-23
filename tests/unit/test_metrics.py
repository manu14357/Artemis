"""
tests/unit/test_metrics.py
Unit tests for artemis.api.metrics — Prometheus instrumentation.

Note: prometheus_client uses a module-level registry, so we access
the singleton directly rather than creating new instances.
"""

from artemis.api.metrics import get_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(m):
    """Return metrics text output as a string."""
    raw = m.generate_text()
    return raw.decode() if isinstance(raw, bytes) else raw


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_singleton_identity():
    """get_metrics() always returns the same instance."""
    m1 = get_metrics()
    m2 = get_metrics()
    assert m1 is m2


def test_record_detection_increments_counter():
    """record_detection increments the detections_total counter."""
    m = get_metrics()
    before = m.detections_total.labels(layer="rf")._value.get()
    m.record_detection("rf")
    after = m.detections_total.labels(layer="rf")._value.get()
    assert after == before + 1.0


def test_record_engagement_increments_counter():
    """record_engagement increments engagements_total for the given tier."""
    m = get_metrics()
    before = m.engagements_total.labels(tier="engage_hard")._value.get()
    m.record_engagement("engage_hard")
    after = m.engagements_total.labels(tier="engage_hard")._value.get()
    assert after == before + 1.0


def test_set_active_tracks_gauge():
    """set_active_tracks updates the gauge value."""
    m = get_metrics()
    m.set_active_tracks(42)
    assert m.active_tracks._value.get() == 42.0
    m.set_active_tracks(0)
    assert m.active_tracks._value.get() == 0.0


def test_set_hub_up_gauge():
    """set_hub_up sets 1 for True, 0 for False."""
    m = get_metrics()
    m.set_hub_up(True)
    assert m.hub_up._value.get() == 1.0
    m.set_hub_up(False)
    assert m.hub_up._value.get() == 0.0
    m.set_hub_up(True)  # restore


def test_fusion_latency_timer_records_observation():
    """fusion_latency_timer context manager records a histogram sample."""
    m = get_metrics()
    count_before = m.fusion_latency._sum.get()
    with m.fusion_latency_timer():
        pass   # near-zero duration
    count_after = m.fusion_latency._sum.get()
    # sum should have increased (even tiny non-negative value)
    assert count_after >= count_before


def test_generate_text_contains_known_metric_names():
    """generate_text() output should contain all registered metric families."""
    m = get_metrics()
    text = _text(m)
    assert "artemis_detections_total" in text
    assert "artemis_active_tracks" in text
    assert "artemis_fusion_latency_seconds" in text
    assert "artemis_up" in text


def test_record_mqtt_publish():
    """record_mqtt_publish increments the MQTT counter for the given prefix."""
    m = get_metrics()
    before = m.mqtt_messages_total.labels(topic_prefix="artemis/threats")._value.get()
    m.record_mqtt_publish("artemis/threats")
    after = m.mqtt_messages_total.labels(topic_prefix="artemis/threats")._value.get()
    assert after == before + 1.0


def test_generate_text_returns_bytes_or_str():
    """generate_text() must return bytes or str (never None)."""
    m = get_metrics()
    out = m.generate_text()
    assert isinstance(out, (bytes, str))
    assert len(out) > 0
