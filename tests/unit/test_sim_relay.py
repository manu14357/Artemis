"""
tests/unit/test_sim_relay.py
Unit tests for artemis.action.effectors.sim_relay.SimRelay

These tests inject MQTT messages directly via the _on_message callback
(no broker required — pure unit test).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from artemis.action.effectors.sim_relay import EngagementRecord, SimRelay
from artemis.cognition.agents.command_router import EngagementTier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mqtt_message(payload: dict) -> MagicMock:
    """Build a mock paho MQTTMessage with a JSON payload."""
    msg = MagicMock()
    msg.topic = "artemis/commands/sim-relay-01"
    msg.payload = json.dumps(payload).encode("utf-8")
    return msg


def _inject(relay: SimRelay, payload: dict) -> None:
    """Directly invoke the _on_message callback without a real broker."""
    relay._on_message(MagicMock(), None, _make_mqtt_message(payload))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSimRelayMessageHandling:
    def setup_method(self) -> None:
        # Create relay without connecting to a real broker
        self.relay = SimRelay(effector_id="sim-relay-01", broker="127.0.0.1")

    def test_hard_engage_recorded(self) -> None:
        _inject(
            self.relay,
            {
                "track_id": "abc123",
                "tier": "engage_hard",
                "score": 0.92,
                "position": {"x": 100.0, "y": 50.0, "z": 10.0},
            },
        )
        history = self.relay.history
        assert len(history) == 1
        rec = history[0]
        assert rec.track_id == "abc123"
        assert rec.tier == EngagementTier.ENGAGE_HARD
        assert rec.score == pytest.approx(0.92)

    def test_soft_engage_recorded(self) -> None:
        _inject(
            self.relay,
            {
                "track_id": "xyz789",
                "tier": "engage_soft",
                "score": 0.65,
                "position": {},
            },
        )
        assert self.relay.history[-1].tier == EngagementTier.ENGAGE_SOFT

    def test_track_only_recorded(self) -> None:
        _inject(
            self.relay,
            {
                "track_id": "t001",
                "tier": "track_only",
                "score": 0.50,
                "position": {},
            },
        )
        assert self.relay.history[-1].tier == EngagementTier.TRACK_ONLY

    def test_ignore_tier_recorded(self) -> None:
        _inject(
            self.relay,
            {
                "track_id": "t002",
                "tier": "ignore",
                "score": 0.10,
                "position": {},
            },
        )
        assert self.relay.history[-1].tier == EngagementTier.IGNORE

    def test_unknown_tier_defaults_to_ignore(self) -> None:
        _inject(
            self.relay,
            {
                "track_id": "t003",
                "tier": "not_a_real_tier",
                "score": 0.50,
                "position": {},
            },
        )
        assert self.relay.history[-1].tier == EngagementTier.IGNORE

    def test_malformed_json_does_not_crash(self) -> None:
        msg = MagicMock()
        msg.topic = "artemis/commands/sim-relay-01"
        msg.payload = b"not valid json {{{"
        self.relay._on_message(MagicMock(), None, msg)
        # Should not raise; history unchanged from previous state
        # (we haven't asserted history length here since setup_method is per-test)

    def test_missing_fields_use_defaults(self) -> None:
        _inject(self.relay, {})  # empty payload
        rec = self.relay.history[-1]
        assert rec.track_id == "unknown"
        assert rec.tier == EngagementTier.IGNORE
        assert rec.score == pytest.approx(0.0)

    def test_history_is_append_only(self) -> None:
        for i in range(5):
            _inject(
                self.relay,
                {
                    "track_id": f"track-{i}",
                    "tier": "track_only",
                    "score": 0.50,
                    "position": {},
                },
            )
        assert len(self.relay.history) == 5

    def test_history_returns_copy(self) -> None:
        """Mutating the returned history list should not affect internal state."""
        _inject(
            self.relay,
            {"track_id": "t", "tier": "track_only", "score": 0.5, "position": {}},
        )
        h1 = self.relay.history
        h1.clear()
        assert len(self.relay.history) == 1  # internal list unaffected

    def test_effector_id_in_record(self) -> None:
        _inject(
            self.relay,
            {"track_id": "t", "tier": "engage_hard", "score": 0.9, "position": {}},
        )
        assert self.relay.history[-1].effector_id == "sim-relay-01"


class TestEngagementRecord:
    def test_to_dict(self) -> None:
        rec = EngagementRecord(
            effector_id="relay-01",
            track_id="t001",
            tier=EngagementTier.ENGAGE_HARD,
            score=0.91,
            position={"x": 10.0, "y": 20.0, "z": 5.0},
        )
        d = rec.to_dict()
        assert d["tier"] == "engage_hard"
        assert d["score"] == pytest.approx(0.91)
        assert "received_at" in d
        assert d["effector_id"] == "relay-01"
