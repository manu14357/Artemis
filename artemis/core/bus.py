"""
artemis/core/bus.py
Asyncio-based in-process pub/sub event bus.

Topics follow the MQTT topic schema but are used purely in-process:
  artemis/nodes/{node_id}/rf
  artemis/nodes/{node_id}/acoustic
  artemis/nodes/{node_id}/radar
  artemis/nodes/{node_id}/optical
  artemis/threats
  artemis/nodes/{node_id}/status

Subscribers receive events via asyncio.Queue so they never block the publisher.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

from artemis.core.logging import get_logger

log = get_logger("core.bus")

# Callback type: async function that takes one event argument
EventCallback = Callable[[Any], Coroutine]


class EventBus:
    """
    Lightweight asyncio pub/sub bus with MQTT-style wildcard topic matching.

    Supported wildcards:
      +  matches a single level      e.g. artemis/nodes/+/rf
      #  matches zero or more levels e.g. artemis/nodes/#
    """

    def __init__(self) -> None:
        # Map of topic_pattern → list of (callback, queue)
        self._subscriptions: dict[str, list[tuple[EventCallback, asyncio.Queue]]] = (
            defaultdict(list)
        )
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        topic_pattern: str,
        callback: EventCallback,
        queue_size: int = 256,
    ) -> asyncio.Queue:
        """
        Register *callback* for all events matching *topic_pattern*.
        Returns the backing queue so the caller can await directly if needed.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        async with self._lock:
            self._subscriptions[topic_pattern].append((callback, q))
        log.debug("subscribed topic_pattern=%s", topic_pattern)
        return q

    async def unsubscribe(self, topic_pattern: str, callback: EventCallback) -> None:
        async with self._lock:
            subs = self._subscriptions.get(topic_pattern, [])
            self._subscriptions[topic_pattern] = [
                (cb, q) for cb, q in subs if cb is not callback
            ]

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, topic: str, event: Any) -> None:
        """
        Deliver *event* to all subscribers whose pattern matches *topic*.
        Each subscriber receives the event via its asyncio.Queue, then its
        callback coroutine is scheduled as a fire-and-forget task.
        """
        matched = 0
        async with self._lock:
            patterns = list(self._subscriptions.keys())

        for pattern in patterns:
            if _topic_matches(pattern, topic):
                async with self._lock:
                    entries = list(self._subscriptions[pattern])
                for callback, q in entries:
                    try:
                        q.put_nowait(event)
                    except asyncio.QueueFull:
                        log.warning(
                            "queue full, dropping event topic=%s pattern=%s",
                            topic,
                            pattern,
                        )
                    # Schedule the callback as a task INSTEAD of also
                    # putting it on the queue — not in addition to it.
                    # Subscribers that use the queue should NOT also register
                    # the same callback here; the two delivery modes are
                    # mutually exclusive.  Here we only do queue delivery;
                    # callers that want task-based delivery should set
                    # queue_size=0 and only rely on the callback.
                    asyncio.ensure_future(callback(event))
                    matched += 1

        if matched == 0:
            log.debug("no subscribers for topic=%s", topic)

    # ------------------------------------------------------------------
    # Convenience: synchronous publish (schedules on the running loop)
    # ------------------------------------------------------------------

    def publish_sync(self, topic: str, event: Any) -> None:
        """Thread-safe publish: schedules a coroutine on the running event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — use run_coroutine_threadsafe via a stored reference.
            # This should not happen in normal operation; callers should ensure
            # the event loop is running before calling publish_sync.
            log.warning("publish_sync called with no running event loop; event dropped")
            return
        loop.call_soon_threadsafe(lambda: loop.create_task(self.publish(topic, event)))


# ---------------------------------------------------------------------------
# MQTT-style wildcard matching
# ---------------------------------------------------------------------------


def _topic_matches(pattern: str, topic: str) -> bool:
    """
    Match a topic against an MQTT-style pattern.
    + matches one level, # matches the rest.
    """
    if pattern == topic:
        return True
    # Convert MQTT wildcards to fnmatch glob
    pattern.replace("+", "[^/]+").replace("#", "**")
    # Use fnmatch with a regex-like approach
    parts_p = pattern.split("/")
    parts_t = topic.split("/")

    pi = 0
    ti = 0
    while pi < len(parts_p) and ti < len(parts_t):
        pp = parts_p[pi]
        if pp == "#":
            return True  # matches everything from here
        if pp == "+" or pp == parts_t[ti]:
            pi += 1
            ti += 1
        else:
            return False

    return pi == len(parts_p) and ti == len(parts_t)


# ---------------------------------------------------------------------------
# Module-level singleton bus
# ---------------------------------------------------------------------------

_default_bus: EventBus | None = None


def get_bus() -> EventBus:
    """Return the global singleton EventBus, creating it on first call."""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


def reset_bus() -> None:
    """Reset the singleton — useful in tests."""
    global _default_bus
    _default_bus = None
