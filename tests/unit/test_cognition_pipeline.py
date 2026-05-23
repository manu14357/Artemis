"""
tests/unit/test_cognition_pipeline.py
Unit tests for CognitionPipeline.process() — end-to-end cognition loop.
"""

from unittest.mock import MagicMock

from artemis.cognition.pipeline import CognitionPipeline
from artemis.cognition.agents.command_router import EngagementTier
from artemis.core.types import Track, TrackStatus


def _mock_pipeline(
    score: float = 0.85,
    tier: EngagementTier = EngagementTier.ENGAGE_HARD,
    effectors: list[str] | None = None,
) -> tuple[CognitionPipeline, MagicMock, MagicMock]:
    """
    Build a CognitionPipeline with mocked dependencies.

    Returns (pipeline, publisher_mock, engagement_log_mock).
    """
    from artemis.cognition.agents.command_router import Command

    # Build a mock Command returned by the router
    cmd = Command(
        track_id="t-0001",
        tier=tier,
        score=score,
        x_m=100.0,
        y_m=0.0,
        z_m=0.0,
    )

    scorer = MagicMock()
    scorer.score.return_value = {"t-0001": score}

    router = MagicMock()
    router.route.return_value = [cmd]

    from artemis.cognition.agents.scheduler_agent import EngagementSchedule

    schedule = EngagementSchedule(
        assignments={"sim-relay-01": cmd},
        unassigned=[],
    )
    scheduler = MagicMock()
    scheduler.assign.return_value = schedule

    publisher = MagicMock()
    engagement_log = MagicMock()
    engagement_log.append = MagicMock()

    pipeline = CognitionPipeline(
        scorer=scorer,
        router=router,
        scheduler=scheduler,
        publisher=publisher,
        engagement_log=engagement_log,
        effectors=effectors or ["sim-relay-01"],
    )
    return pipeline, publisher, engagement_log


def _track(track_id: str = "t-0001") -> Track:
    return Track(
        track_id=track_id,
        status=TrackStatus.CONFIRMED,
        state=[100.0, 0.0, 0.0, -5.0, 0.0, 0.0],
    )


class TestCognitionPipeline:

    def test_high_score_dispatches_command(self):
        """ENGAGE_HARD tier → publish_command is called once."""
        pipeline, publisher, _ = _mock_pipeline(
            score=0.9, tier=EngagementTier.ENGAGE_HARD
        )
        pipeline.process([_track()])
        publisher.publish_command.assert_called_once()

    def test_ignore_tier_no_publish(self):
        """IGNORE tier → publish_command must NOT be called."""
        pipeline, publisher, _ = _mock_pipeline(score=0.05, tier=EngagementTier.IGNORE)

        # Override scheduler to return IGNORE command
        from artemis.cognition.agents.command_router import Command
        from artemis.cognition.agents.scheduler_agent import EngagementSchedule

        ignore_cmd = Command(
            track_id="t-0001",
            tier=EngagementTier.IGNORE,
            score=0.05,
            x_m=0.0,
            y_m=0.0,
            z_m=0.0,
        )
        schedule = EngagementSchedule(assignments={}, unassigned=[ignore_cmd])
        pipeline._scheduler.assign.return_value = schedule

        pipeline.process([_track()])
        publisher.publish_command.assert_not_called()

    def test_log_written_on_dispatch(self):
        """Each dispatched command must produce one EngagementLog.append call."""
        pipeline, _, engagement_log = _mock_pipeline(
            score=0.9, tier=EngagementTier.ENGAGE_HARD
        )
        pipeline.process([_track()])
        engagement_log.append.assert_called_once()

    def test_empty_tracks_no_publish(self):
        """Passing zero tracks → no MQTT publish, no log append."""
        pipeline, publisher, engagement_log = _mock_pipeline()
        # Override scorer to return empty dict
        pipeline._scorer.score.return_value = {}
        pipeline._router.route.return_value = []
        from artemis.cognition.agents.scheduler_agent import EngagementSchedule

        pipeline._scheduler.assign.return_value = EngagementSchedule(
            assignments={}, unassigned=[]
        )

        pipeline.process([])
        publisher.publish_command.assert_not_called()
        engagement_log.append.assert_not_called()

    def test_multiple_tracks_multiple_dispatches(self):
        """Two effectors each receiving a command → two log appends."""
        from artemis.cognition.agents.command_router import Command
        from artemis.cognition.agents.scheduler_agent import EngagementSchedule

        cmd1 = Command(
            track_id="t1",
            tier=EngagementTier.ENGAGE_HARD,
            score=0.9,
            x_m=0.0,
            y_m=0.0,
            z_m=0.0,
        )
        cmd2 = Command(
            track_id="t2",
            tier=EngagementTier.ENGAGE_SOFT,
            score=0.7,
            x_m=0.0,
            y_m=0.0,
            z_m=0.0,
        )

        pipeline, publisher, engagement_log = _mock_pipeline()
        schedule = EngagementSchedule(
            assignments={"e1": cmd1, "e2": cmd2},
            unassigned=[],
        )
        pipeline._scheduler.assign.return_value = schedule

        pipeline.process([_track("t1"), _track("t2")])
        assert publisher.publish_command.call_count == 2
        assert engagement_log.append.call_count == 2

    def test_publisher_exception_does_not_crash_pipeline(self):
        """If publish_command raises, the pipeline must not propagate the exception."""
        pipeline, publisher, engagement_log = _mock_pipeline(
            score=0.9, tier=EngagementTier.ENGAGE_HARD
        )
        publisher.publish_command.side_effect = RuntimeError("broker down")

        # Should not raise
        pipeline.process([_track()])

        # Log must still be written despite the publish failure
        engagement_log.append.assert_called_once()
