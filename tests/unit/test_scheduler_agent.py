"""
tests/unit/test_scheduler_agent.py
Unit tests for SchedulerAgent — greedy 1-to-1 command/effector matching.
"""
import pytest

from artemis.cognition.agents.scheduler_agent import SchedulerAgent
from artemis.cognition.agents.command_router import EngagementTier


def _cmd(track_id: str, tier: EngagementTier, score: float, x: float = 0.0, y: float = 0.0):
    """Create a minimal Command-like object using the real Command dataclass."""
    from artemis.cognition.agents.command_router import Command
    return Command(
        track_id=track_id,
        tier=tier,
        score=score,
        x_m=x,
        y_m=y,
        z_m=0.0,
    )


class TestSchedulerAgent:
    agent = SchedulerAgent()

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_no_effectors_all_unassigned(self):
        """With no effectors every command ends up in unassigned."""
        cmds = [_cmd("t1", EngagementTier.ENGAGE_HARD, 0.9)]
        schedule = self.agent.assign(cmds, effectors=[])
        assert len(schedule.assignments) == 0
        assert len(schedule.unassigned) == 1

    def test_ignore_tier_excluded(self):
        """IGNORE-tier commands must never be assigned."""
        cmds = [_cmd("t1", EngagementTier.IGNORE, 0.1)]
        schedule = self.agent.assign(cmds, effectors=["effector-01"])
        assert "effector-01" not in schedule.assignments
        assert len(schedule.unassigned) == 0  # IGNORE is filtered entirely

    def test_all_ignore_produces_empty_schedule(self):
        """All IGNORE commands → completely empty schedule."""
        cmds = [_cmd(f"t{i}", EngagementTier.IGNORE, 0.05) for i in range(5)]
        schedule = self.agent.assign(cmds, effectors=["effector-01", "effector-02"])
        assert len(schedule.assignments) == 0
        assert len(schedule.unassigned) == 0

    # ------------------------------------------------------------------
    # Greedy priority
    # ------------------------------------------------------------------

    def test_one_effector_gets_highest_score(self):
        """With 1 effector and 3 commands the highest-scoring command wins."""
        cmds = [
            _cmd("t1", EngagementTier.ENGAGE_HARD, 0.6),
            _cmd("t2", EngagementTier.ENGAGE_HARD, 0.95),   # highest
            _cmd("t3", EngagementTier.ENGAGE_SOFT, 0.4),
        ]
        schedule = self.agent.assign(cmds, effectors=["effector-01"])
        assert "effector-01" in schedule.assignments
        assert schedule.assignments["effector-01"].track_id == "t2"
        assert len(schedule.unassigned) == 2

    def test_three_effectors_full_assignment(self):
        """3 effectors and 3 equal-tier commands → all 3 assigned."""
        cmds = [
            _cmd(f"t{i}", EngagementTier.ENGAGE_HARD, 0.9 - i * 0.1)
            for i in range(3)
        ]
        schedule = self.agent.assign(cmds, effectors=[f"e{i}" for i in range(3)])
        assert len(schedule.assignments) == 3
        assert len(schedule.unassigned) == 0

    def test_no_double_assignment(self):
        """Each effector must appear at most once in assignments."""
        cmds = [_cmd(f"t{i}", EngagementTier.ENGAGE_HARD, 0.8) for i in range(10)]
        effectors = ["e0", "e1", "e2"]
        schedule = self.agent.assign(cmds, effectors=effectors)
        assigned_effectors = list(schedule.assignments.keys())
        assert len(assigned_effectors) == len(set(assigned_effectors))

    def test_empty_commands(self):
        """No commands → empty schedule."""
        schedule = self.agent.assign([], effectors=["e0"])
        assert len(schedule.assignments) == 0
        assert len(schedule.unassigned) == 0

    def test_range_tiebreak(self):
        """When scores are equal the closer drone (smaller sqrt(x²+y²)) wins."""
        cmds = [
            _cmd("far",   EngagementTier.ENGAGE_HARD, 0.9, x=400.0),  # farther
            _cmd("close", EngagementTier.ENGAGE_HARD, 0.9, x=50.0),   # closer
        ]
        schedule = self.agent.assign(cmds, effectors=["e0"])
        assert schedule.assignments["e0"].track_id == "close"
