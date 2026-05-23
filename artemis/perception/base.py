"""
artemis/perception/base.py
Abstract base class for all perception drivers (real hardware and emulators).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncGenerator

from artemis.core.types import Detection


class DriverStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    STOPPED = "stopped"


class PerceptionDriver(ABC):
    """
    Every sensor driver (or simulator emulator) implements this interface.
    The node daemon calls `stream()` and feeds detections to the event bus.
    """

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.status = DriverStatus.STARTING

    @abstractmethod
    async def stream(self) -> AsyncGenerator[Detection, None]:
        """
        Async generator that yields Detection objects indefinitely.
        Implementations should set self.status to RUNNING once initialised
        and to ERROR / STOPPED on exit.
        """
        ...

    async def start(self) -> None:
        """Optional hook called before streaming begins."""

    async def stop(self) -> None:
        """Optional hook to gracefully tear down hardware resources."""
        self.status = DriverStatus.STOPPED

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} node={self.node_id} status={self.status}>"
