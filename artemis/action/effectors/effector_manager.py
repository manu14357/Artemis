"""
artemis/action/effectors/effector_manager.py
Registry and lifecycle manager for all ARTEMIS effectors.

Provides a unified interface for:
  - Registering effectors (SimRelay, GPIORelayEffector, any future type).
  - Starting all effectors concurrently in background threads (non-blocking).
  - Stopping all effectors on shutdown.
  - Querying the list of active effector IDs for SchedulerAgent.

Usage
-----
    manager = EffectorManager()
    manager.register(SimRelay(effector_id="sim-relay-01", broker=cfg.mqtt.broker))
    manager.start_all()   # returns immediately; each effector runs in its thread

    # During hub run:
    effectors = manager.get_active_effectors()   # → ["sim-relay-01"]

    # On shutdown:
    manager.stop_all()
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol, runtime_checkable

from artemis.core.logging import get_logger

log = get_logger("action.effector_manager")


# ---------------------------------------------------------------------------
# Structural interface
# ---------------------------------------------------------------------------

@runtime_checkable
class EffectorBase(Protocol):
    """
    Structural protocol all effectors must satisfy.

    Any class with an ``effector_id`` attribute and ``start()`` / ``stop()``
    methods qualifies — no inheritance required.
    """
    effector_id: str

    def start(self) -> None: ...
    def stop(self) -> None: ...


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class EffectorManager:
    """
    Registry and lifecycle manager for all active effectors.

    Thread-safe: registration and queries are protected by a single lock.
    ``start_all()`` / ``stop_all()`` are idempotent (calling them twice
    logs a warning and returns early).
    """

    def __init__(self) -> None:
        self._registry: dict[str, EffectorBase] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def register(self, effector: EffectorBase) -> None:
        """
        Register an effector.  May be called before or after ``start_all()``.

        If an effector with the same ID is already registered the old entry
        is overwritten (with a warning).
        """
        with self._lock:
            if effector.effector_id in self._registry:
                log.warning(
                    "effector %s already registered — overwriting",
                    effector.effector_id,
                )
            self._registry[effector.effector_id] = effector
            log.info(
                "registered effector id=%s type=%s",
                effector.effector_id, type(effector).__name__,
            )

    def get_active_effectors(self) -> list[str]:
        """Return a copy of the currently registered effector ID list."""
        with self._lock:
            return list(self._registry.keys())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_all(self) -> None:
        """
        Start all registered effectors in background daemon threads.

        This call returns immediately; each effector runs its ``start()``
        (blocking) loop in a separate thread.  Calling this twice is a
        no-op (with a warning).
        """
        with self._lock:
            if self._executor is not None:
                log.warning("EffectorManager.start_all() called twice — ignored")
                return
            n = len(self._registry)
            self._executor = ThreadPoolExecutor(
                max_workers=max(n, 1),
                thread_name_prefix="effector",
            )
            for effector in self._registry.values():
                self._executor.submit(self._run_effector, effector)
            log.info("started %d effector(s)", n)

    def stop_all(self) -> None:
        """Stop all effectors and shut down the thread pool."""
        with self._lock:
            for effector in self._registry.values():
                try:
                    effector.stop()
                except Exception as exc:
                    log.error(
                        "error stopping effector %s: %s",
                        effector.effector_id, exc,
                    )
            if self._executor:
                self._executor.shutdown(wait=False)
                self._executor = None
        log.info("all effectors stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_effector(self, effector: EffectorBase) -> None:
        try:
            effector.start()
        except Exception as exc:
            log.error(
                "effector %s crashed: %s",
                effector.effector_id, exc, exc_info=True,
            )
