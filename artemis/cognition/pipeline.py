"""
artemis/cognition/pipeline.py
End-to-end synchronous cognition pipeline.

Wires ThreatScorer → CommandRouter → SchedulerAgent → MQTTPublisher + EngagementLog
into a single ``process(tracks)`` call that MeshAggregator invokes once per
fusion cycle after TrackManager and ThreatMap have been updated.

Architecture
------------
  tracks (list[Track])
      │
      ▼
  ThreatScorer.score(tracks)
      │  → scores: dict[track_id, float]
      ▼
  CommandRouter.route(tracks, scores)
      │  → commands: list[Command]  (only tier-changed commands)
      ▼
  SchedulerAgent.assign(commands, effectors)
      │  → schedule: EngagementSchedule
      ▼
  For each (effector_id, command) in schedule.assignments:
      MQTTPublisher.publish_command(effector_id, command.to_dict())
      EngagementLog.append(EngagementRecord(...))
"""
from __future__ import annotations

from typing import Optional

from artemis.action.engagement_log import EngagementLog, EngagementRecord
from artemis.cognition.agents.command_router import Command, CommandRouter
from artemis.cognition.agents.scheduler_agent import SchedulerAgent
from artemis.cognition.agents.threat_scorer import ThreatScorer
from artemis.core.logging import get_logger
from artemis.core.types import Track
from artemis.mesh.publisher import MQTTPublisher

log = get_logger("cognition.pipeline")


class CognitionPipeline:
    """
    Synchronous, single-cycle cognition pipeline.

    Designed to be called from ``MeshAggregator.run()`` after each fusion
    cycle completes — no asyncio, no threads.

    Parameters
    ----------
    scorer         : ThreatScorer
    router         : CommandRouter
    scheduler      : SchedulerAgent
    publisher      : MQTTPublisher — for dispatching commands over MQTT
    engagement_log : EngagementLog — for persisting dispatched commands
    effectors      : list of effector_id strings the scheduler may assign to
    """

    def __init__(
        self,
        scorer: ThreatScorer,
        router: CommandRouter,
        scheduler: SchedulerAgent,
        publisher: MQTTPublisher,
        engagement_log: EngagementLog,
        effectors: Optional[list[str]] = None,
    ) -> None:
        self._scorer = scorer
        self._router = router
        self._scheduler = scheduler
        self._publisher = publisher
        self._log = engagement_log
        self._effectors: list[str] = effectors or ["sim-relay-01"]

    # ------------------------------------------------------------------
    # Public API — called once per fusion cycle
    # ------------------------------------------------------------------

    def process(self, tracks: list[Track]) -> list[Command]:
        """
        Run one cognition cycle.

        Parameters
        ----------
        tracks : current confirmed tracks from TrackManager

        Returns
        -------
        list[Command] — all commands routed this cycle (including IGNORE);
        the dispatched subset is those whose tier != IGNORE.
        """
        if not tracks:
            return []

        try:
            # Step 1: Score all non-dropped tracks
            scores = self._scorer.score(tracks)

            # Step 2: Route to Commands (only tier-changed ones emitted)
            commands = self._router.route(tracks, scores)

            if not commands:
                return []

            log.debug(
                "cognition cycle: %d commands from %d tracks",
                len(commands), len(tracks),
            )

            # Step 3: Schedule 1:1 effector assignments
            schedule = self._scheduler.assign(commands, self._effectors)

            # Step 4 & 5: Dispatch + Log each assignment
            for effector_id, cmd in schedule.assignments.items():
                self._dispatch(effector_id, cmd)

            return commands

        except Exception as exc:
            log.error("cognition cycle error: %s", exc, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dispatch(self, effector_id: str, cmd: Command) -> None:
        """Publish command to MQTT (best-effort) and always record in log."""
        try:
            self._publisher.publish_command(effector_id, cmd.to_dict())
            log.info(
                "dispatched effector=%s track=%s tier=%s score=%.3f",
                effector_id, cmd.track_id, cmd.tier.value, cmd.score,
            )
        except Exception as exc:
            log.error("publish_command failed effector=%s: %s", effector_id, exc)

        # Always write the log record — even if MQTT publish failed —
        # so the engagement is auditable regardless of broker state.
        record = EngagementRecord(
            track_id=cmd.track_id,
            effector_id=effector_id,
            tier=cmd.tier.value,
            score=cmd.score,
            x_m=cmd.x_m,
            y_m=cmd.y_m,
            z_m=cmd.z_m,
        )
        self._log.append(record)
