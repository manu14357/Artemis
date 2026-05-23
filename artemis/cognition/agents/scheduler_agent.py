"""
artemis/cognition/agents/scheduler_agent.py
Engagement deconfliction scheduler.

Given the list of Commands produced by CommandRouter and the list of
currently available effector IDs, the scheduler performs a greedy 1:1
matching so that:
  - Each effector handles at most one target per cycle.
  - Each target is assigned to at most one effector per cycle.
  - IGNORE-tier commands are excluded from assignment.
  - When there are more actionable commands than effectors the highest-
    scoring threats are assigned first; the remainder go into ``unassigned``.

The scheduler is stateless within a cycle; call ``assign()`` once per
fusion cycle after CommandRouter.route().

Timeout: 10 ms (hub_default.yaml cognition.scheduler_timeout_ms)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from artemis.cognition.agents.command_router import Command, EngagementTier
from artemis.core.logging import get_logger

log = get_logger("cognition.scheduler")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EngagementSchedule:
    """Output of SchedulerAgent.assign()."""

    # effector_id → Command
    assignments: dict[str, Command]
    # Commands that could not be assigned (more threats than effectors)
    unassigned: list[Command]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class SchedulerAgent:
    """
    Greedy 1:1 engagement scheduler.

    Thread-safe via internal lock (CognitionPipeline calls this from the
    asyncio event loop but SimRelay can update state concurrently).

    Call ``assign(commands, effectors)`` each fusion cycle.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def assign(
        self,
        commands: list[Command],
        effectors: list[str],
    ) -> EngagementSchedule:
        """
        Assign available effectors to engagement commands.

        Parameters
        ----------
        commands  : list of Command objects from CommandRouter
        effectors : list of effector_id strings available this cycle

        Returns
        -------
        EngagementSchedule
        """
        with self._lock:
            # 1. Filter out IGNORE-tier commands
            actionable = [c for c in commands if c.tier != EngagementTier.IGNORE]

            if not actionable:
                return EngagementSchedule(assignments={}, unassigned=[])

            # 2. Sort: highest score first, then closest range (lowest x²+y²)
            actionable.sort(key=lambda c: (-c.score, c.x_m**2 + c.y_m**2))

            # 3. Greedy 1:1 assignment
            available = list(effectors)  # local copy — we pop from it
            assignments: dict[str, Command] = {}
            unassigned: list[Command] = []

            for cmd in actionable:
                if available:
                    eid = available.pop(0)
                    assignments[eid] = cmd
                    log.debug(
                        "assigned effector=%s → track=%s tier=%s score=%.3f",
                        eid,
                        cmd.track_id,
                        cmd.tier.value,
                        cmd.score,
                    )
                else:
                    unassigned.append(cmd)
                    log.debug(
                        "unassigned track=%s (no effectors left) tier=%s",
                        cmd.track_id,
                        cmd.tier.value,
                    )

            return EngagementSchedule(
                assignments=assignments,
                unassigned=unassigned,
            )
