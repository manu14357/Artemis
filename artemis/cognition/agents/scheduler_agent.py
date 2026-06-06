"""
artemis/cognition/agents/scheduler_agent.py
Engagement deconfliction scheduler with effector-type awareness.

Matches effectors to threats based on:
- Engagement tier (TRACK_ONLY → visual, ENGAGE_SOFT → audio/visual, ENGAGE_HARD → physical)
- Effector capabilities (audio, visual, physical, simulation)
- Threat priority (score, proximity)

The scheduler performs intelligent 1:1 matching so that:
  - Each effector handles at most one target per cycle.
  - Each target is assigned to at most one effector per cycle.
  - IGNORE-tier commands are excluded.
  - Effectors are matched to appropriate tiers.
  - When there are more actionable commands than effectors the highest-
    scoring threats are assigned first; the remainder go into ``unassigned``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from artemis.cognition.agents.command_router import Command, EngagementTier
from artemis.core.logging import get_logger

log = get_logger("cognition.scheduler")


# ---------------------------------------------------------------------------
# Effector capability registry
# ---------------------------------------------------------------------------

# Maps effector_id prefix/type to capabilities
EFFECTOR_CAPABILITIES = {
    "audio": {
        "tiers": [EngagementTier.ENGAGE_SOFT],
        "description": "Directional audio deterrent (predator calls, tones)",
    },
    "visual": {
        "tiers": [EngagementTier.TRACK_ONLY, EngagementTier.ENGAGE_SOFT],
        "description": "Strobe lights and laser dazzler",
    },
    "gpio": {
        "tiers": [EngagementTier.ENGAGE_HARD, EngagementTier.ENGAGE_SOFT, EngagementTier.TRACK_ONLY],
        "description": "GPIO relay (physical barrier, net launcher, etc.)",
    },
    "sim": {
        "tiers": [EngagementTier.ENGAGE_HARD, EngagementTier.ENGAGE_SOFT, EngagementTier.TRACK_ONLY],
        "description": "Simulation effector (logs only)",
    },
}


def _get_effector_type(effector_id: str) -> str:
    """Determine effector type from ID prefix."""
    effector_id_lower = effector_id.lower()
    if "audio" in effector_id_lower:
        return "audio"
    if "visual" in effector_id_lower:
        return "visual"
    if "gpio" in effector_id_lower or "relay" in effector_id_lower:
        return "gpio"
    if "sim" in effector_id_lower:
        return "sim"
    return "unknown"


def _effector_supports_tier(effector_id: str, tier: EngagementTier) -> bool:
    """Check if an effector can handle a given engagement tier."""
    eff_type = _get_effector_type(effector_id)
    caps = EFFECTOR_CAPABILITIES.get(eff_type, {"tiers": []})
    return tier in caps["tiers"]


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
    Effector-aware engagement scheduler.

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
        Assign available effectors to engagement commands with type awareness.

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

            # 2. Sort: highest score first, then closest range
            actionable.sort(key=lambda c: (-c.score, c.x_m**2 + c.y_m**2))

            # 3. Group effectors by type for tier-appropriate assignment
            effectors_by_type = self._group_effectors_by_type(effectors)

            # 4. Assign with tier-effector matching
            assignments: dict[str, Command] = {}
            unassigned: list[Command] = []

            # Track which effectors are used
            used_effectors: set[str] = set()

            for cmd in actionable:
                effector_id = self._find_best_effector(cmd, effectors_by_type, used_effectors)
                if effector_id:
                    assignments[effector_id] = cmd
                    used_effectors.add(effector_id)
                    log.debug(
                        "assigned effector=%s → track=%s tier=%s score=%.3f",
                        effector_id,
                        cmd.track_id,
                        cmd.tier.value,
                        cmd.score,
                    )
                else:
                    unassigned.append(cmd)
                    log.debug(
                        "unassigned track=%s (no suitable effectors) tier=%s",
                        cmd.track_id,
                        cmd.tier.value,
                    )

            return EngagementSchedule(
                assignments=assignments,
                unassigned=unassigned,
            )

    def _group_effectors_by_type(self, effectors: list[str]) -> dict[str, list[str]]:
        """Group effector IDs by their capability type."""
        grouped: dict[str, list[str]] = {"audio": [], "visual": [], "gpio": [], "sim": [], "unknown": []}
        for eid in effectors:
            eff_type = _get_effector_type(eid)
            if eff_type in grouped:
                grouped[eff_type].append(eid)
            else:
                grouped["unknown"].append(eid)
        return grouped

    def _find_best_effector(
        self,
        cmd: Command,
        effectors_by_type: dict[str, list[str]],
        used: set[str],
    ) -> Optional[str]:
        """Find the best available effector for a command based on tier."""
        tier = cmd.tier

        # Define priority order of effector types for each tier
        tier_priority = {
            EngagementTier.TRACK_ONLY: ["visual", "gpio", "sim", "unknown"],
            EngagementTier.ENGAGE_SOFT: ["audio", "visual", "gpio", "sim", "unknown"],
            EngagementTier.ENGAGE_HARD: ["gpio", "sim", "unknown"],
        }

        priority = tier_priority.get(tier, ["sim", "gpio", "visual", "audio", "unknown"])

        for eff_type in priority:
            for eid in effectors_by_type.get(eff_type, []):
                if eid not in used and _effector_supports_tier(eid, tier):
                    return eid

        # Fallback: any unused effector that supports the tier
        for eff_type, eids in effectors_by_type.items():
            for eid in eids:
                if eid not in used and _effector_supports_tier(eid, tier):
                    return eid

        return None
