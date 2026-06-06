"""
artemis/action/effectors — Effector package.

Exports:
- EffectorManager: Registry and lifecycle manager
- SimRelay: Simulation effector (logs commands)
- GPIORelayEffector: GPIO relay for physical effectors
- AudioDeterrent: Directional audio deterrent (predator calls, tones)
- VisualDeterrent: Strobe lights and laser dazzler
"""

from artemis.action.effectors.effector_manager import EffectorManager, EffectorBase
from artemis.action.effectors.sim_relay import SimRelay, EngagementRecord
from artemis.action.effectors.gpio_relay import GPIORelayEffector

try:
    from artemis.action.effectors.audio_deterrent import AudioDeterrent, AudioConfig, DeterrentSound
    __all__ = ["EffectorManager", "EffectorBase", "SimRelay", "EngagementRecord",
               "GPIORelayEffector", "AudioDeterrent", "AudioConfig", "DeterrentSound"]
except ImportError:
    __all__ = ["EffectorManager", "EffectorBase", "SimRelay", "EngagementRecord",
               "GPIORelayEffector"]

try:
    from artemis.action.effectors.visual_deterrent import VisualDeterrent, VisualConfig, VisualMode
    __all__.extend(["VisualDeterrent", "VisualConfig", "VisualMode"])
except ImportError:
    pass