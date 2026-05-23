"""
tests/unit/test_command_router.py
Unit tests for artemis.cognition.agents.command_router.CommandRouter
"""
from __future__ import annotations

import pytest

from artemis.cognition.agents.command_router import (
    Command,
    CommandRouter,
    EngagementTier,
    _tier_from_score,
)
from artemis.core.types import Track, TrackStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_track(
    x: float = 0.0, y: float = 0.0,
    vx: float = 0.0, vy: float = 0.0,
    status: TrackStatus = TrackStatus.CONFIRMED,
) -> Track:
    t = Track(status=status)
    t.state = [x, y, 0.0, vx, vy, 0.0]
    return t


# ---------------------------------------------------------------------------
# tier_from_score
# ---------------------------------------------------------------------------

class TestTierFromScore:
    def test_below_track_is_ignore(self) -> None:
        assert _tier_from_score(0.0) == EngagementTier.IGNORE
        assert _tier_from_score(0.39) == EngagementTier.IGNORE

    def test_track_only_range(self) -> None:
        assert _tier_from_score(0.40) == EngagementTier.TRACK_ONLY
        assert _tier_from_score(0.59) == EngagementTier.TRACK_ONLY

    def test_soft_engage_range(self) -> None:
        assert _tier_from_score(0.60) == EngagementTier.ENGAGE_SOFT
        assert _tier_from_score(0.79) == EngagementTier.ENGAGE_SOFT

    def test_hard_engage_range(self) -> None:
        assert _tier_from_score(0.80) == EngagementTier.ENGAGE_HARD
        assert _tier_from_score(1.00) == EngagementTier.ENGAGE_HARD


# ---------------------------------------------------------------------------
# CommandRouter
# ---------------------------------------------------------------------------

class TestCommandRouter:
    def setup_method(self) -> None:
        self.router = CommandRouter()

    def test_ignore_produces_no_command(self) -> None:
        t = _make_track()
        cmds = self.router.route([t], {t.track_id: 0.10})
        assert cmds == []

    def test_track_only_emits_command(self) -> None:
        t = _make_track()
        cmds = self.router.route([t], {t.track_id: 0.45})
        assert len(cmds) == 1
        assert cmds[0].tier == EngagementTier.TRACK_ONLY

    def test_soft_engage_emits_command(self) -> None:
        t = _make_track()
        cmds = self.router.route([t], {t.track_id: 0.65})
        assert len(cmds) == 1
        assert cmds[0].tier == EngagementTier.ENGAGE_SOFT

    def test_hard_engage_emits_command(self) -> None:
        t = _make_track()
        cmds = self.router.route([t], {t.track_id: 0.90})
        assert len(cmds) == 1
        assert cmds[0].tier == EngagementTier.ENGAGE_HARD

    def test_no_duplicate_emissions_same_tier(self) -> None:
        """Router should NOT re-emit when tier is unchanged."""
        t = _make_track()
        cmds1 = self.router.route([t], {t.track_id: 0.65})
        cmds2 = self.router.route([t], {t.track_id: 0.67})   # same tier
        assert len(cmds1) == 1
        assert len(cmds2) == 0   # tier unchanged — no emission

    def test_tier_escalation_emits_new_command(self) -> None:
        """Track escalating from SOFT to HARD should emit one more command."""
        t = _make_track()
        self.router.route([t], {t.track_id: 0.65})   # ENGAGE_SOFT
        cmds = self.router.route([t], {t.track_id: 0.85})   # escalate to HARD
        assert len(cmds) == 1
        assert cmds[0].tier == EngagementTier.ENGAGE_HARD

    def test_tier_de_escalation_emits_command(self) -> None:
        """Score dropping from HARD to SOFT should emit a new SOFT command."""
        t = _make_track()
        self.router.route([t], {t.track_id: 0.90})   # ENGAGE_HARD
        cmds = self.router.route([t], {t.track_id: 0.65})   # de-escalate
        assert len(cmds) == 1
        assert cmds[0].tier == EngagementTier.ENGAGE_SOFT

    def test_command_has_position(self) -> None:
        t = _make_track(x=100.0, y=200.0)
        cmds = self.router.route([t], {t.track_id: 0.90})
        assert cmds[0].x_m == pytest.approx(100.0)
        assert cmds[0].y_m == pytest.approx(200.0)

    def test_dropped_track_cleaned_from_state(self) -> None:
        t = _make_track()
        self.router.route([t], {t.track_id: 0.65})
        # Next cycle: track not present (dropped) — state should be pruned
        cmds = self.router.route([], {})
        assert t.track_id not in self.router._last_tier

    def test_command_to_dict(self) -> None:
        t = _make_track(x=50.0, y=30.0)
        cmds = self.router.route([t], {t.track_id: 0.85})
        d = cmds[0].to_dict()
        assert d["tier"] == "engage_hard"
        assert "position" in d
        assert "timestamp" in d

    def test_empty_inputs(self) -> None:
        cmds = self.router.route([], {})
        assert cmds == []

    def test_multiple_tracks_independent(self) -> None:
        t1 = _make_track()
        t2 = _make_track()
        scores = {t1.track_id: 0.90, t2.track_id: 0.45}
        cmds = self.router.route([t1, t2], scores)
        tiers = {c.track_id: c.tier for c in cmds}
        assert tiers[t1.track_id] == EngagementTier.ENGAGE_HARD
        assert tiers[t2.track_id] == EngagementTier.TRACK_ONLY
