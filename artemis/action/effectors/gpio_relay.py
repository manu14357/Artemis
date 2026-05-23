"""
artemis/action/effectors/gpio_relay.py
GPIO relay effector for Raspberry Pi hardware.

Subscribes to ``artemis/commands/{effector_id}`` via MQTT and activates
GPIO pins to trigger physical countermeasures:

  ENGAGE_HARD → pin[0]  (siren / physical barrier)
  ENGAGE_SOFT → pin[1]  (audio deterrent)
  TRACK_ONLY  → pin[2]  (visual alert / strobe light)
  IGNORE      → no activation

Safety constraints
------------------
- Maximum activation duration is hard-capped at 300 s regardless of the
  value sent in the command.  This prevents an accidental config error
  from leaving countermeasures on indefinitely.
- Auto-reset: a ``threading.Timer`` fires after ``duration_s`` to release
  the pin.
- Graceful degradation: if ``RPi.GPIO`` is not installed (e.g. on a
  development laptop) the class still instantiates and subscribes to MQTT,
  but all GPIO calls are silently skipped with a debug log.  This lets
  the full hub run and be tested without RPi hardware.

Legal note
----------
This effector only controls physical barriers, alarms, and deterrents.
RF jamming is intentionally absent from this implementation — it is
illegal in most jurisdictions without specific authorisation.
"""
from __future__ import annotations

import json
import threading
from typing import Optional

import paho.mqtt.client as mqtt

from artemis.cognition.agents.command_router import EngagementTier
from artemis.core.logging import get_logger

log = get_logger("action.gpio_relay")

_MAX_DURATION_S: float = 300.0

# Attempt to import RPi.GPIO; degrade gracefully on non-RPi systems.
try:
    import RPi.GPIO as GPIO  # type: ignore[import]
    _GPIO_AVAILABLE = True
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
except ImportError:
    GPIO = None  # type: ignore[assignment]
    _GPIO_AVAILABLE = False
    log.warning("RPi.GPIO not installed — GPIORelayEffector running in no-op mode")

# Tier → pin list index
_TIER_PIN_INDEX: dict[EngagementTier, int] = {
    EngagementTier.ENGAGE_HARD: 0,
    EngagementTier.ENGAGE_SOFT: 1,
    EngagementTier.TRACK_ONLY:  2,
}


class GPIORelayEffector:
    """
    MQTT-subscribing GPIO relay effector.

    Parameters
    ----------
    effector_id : str
    broker      : str  MQTT broker hostname / IP
    port        : int
    keepalive   : int
    pins        : list[int]  BCM GPIO pin numbers [hard, soft, alert, spare]
    username / password — optional MQTT broker credentials
    """

    def __init__(
        self,
        effector_id: str = "gpio-relay-01",
        broker: str = "127.0.0.1",
        port: int = 1883,
        keepalive: int = 60,
        pins: Optional[list[int]] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.effector_id = effector_id
        self._broker = broker
        self._port = port
        self._keepalive = keepalive
        self._topic = f"artemis/commands/{effector_id}"
        self._stop_flag = threading.Event()
        self._pins: list[int] = pins or [17, 27, 22, 23]

        # Active release timers keyed by pin number
        self._timers: dict[int, threading.Timer] = {}
        self._timer_lock = threading.Lock()

        # Initialise GPIO outputs (no-op if library unavailable)
        if _GPIO_AVAILABLE and GPIO is not None:
            for pin in self._pins:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"artemis-gpio-{effector_id}",
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect    = self._on_connect
        self._client.on_message    = self._on_message
        self._client.on_disconnect = self._on_disconnect

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to broker and block until ``stop()`` is called."""
        self._client.connect(self._broker, self._port, self._keepalive)
        self._client.loop_forever()

    def stop(self) -> None:
        """Cancel all active timers, release all pins, disconnect from broker."""
        self._stop_flag.set()
        with self._timer_lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
        self._release_all()
        try:
            self._client.disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc == 0:
            client.subscribe(self._topic, qos=1)
            log.info("GPIORelayEffector connected effector_id=%s", self.effector_id)
        else:
            log.error("GPIO relay MQTT connect failed rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc, properties=None, reason=None) -> None:
        log.info("GPIO relay disconnected rc=%d", rc)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.error("GPIO relay bad payload: %s", exc)
            return

        try:
            tier = EngagementTier(payload.get("tier", "ignore"))
        except ValueError:
            log.warning("unknown tier in command: %s", payload.get("tier"))
            return

        duration_s = float(payload.get("duration_s", 5.0))
        duration_s = min(duration_s, _MAX_DURATION_S)

        pin_idx = _TIER_PIN_INDEX.get(tier)
        if pin_idx is not None and pin_idx < len(self._pins):
            self._activate(self._pins[pin_idx], duration_s)
            log.info(
                "GPIO activate pin=%d tier=%s duration=%.1fs",
                self._pins[pin_idx], tier.value, duration_s,
            )
        else:
            log.debug("tier=%s → no activation", tier.value)

    # ------------------------------------------------------------------
    # GPIO helpers
    # ------------------------------------------------------------------

    def _activate(self, pin: int, duration_s: float) -> None:
        """Set pin HIGH; schedule auto-release after ``duration_s`` seconds."""
        if not _GPIO_AVAILABLE or GPIO is None:
            log.debug("GPIO no-op: would activate pin=%d for %.1fs", pin, duration_s)
            return
        GPIO.output(pin, GPIO.HIGH)
        with self._timer_lock:
            existing = self._timers.pop(pin, None)
            if existing:
                existing.cancel()
            t = threading.Timer(duration_s, self._release_pin, args=[pin])
            t.daemon = True
            t.start()
            self._timers[pin] = t

    def _release_pin(self, pin: int) -> None:
        if not _GPIO_AVAILABLE or GPIO is None:
            return
        try:
            GPIO.output(pin, GPIO.LOW)
        except Exception as exc:
            log.error("GPIO release pin=%d failed: %s", pin, exc)
        with self._timer_lock:
            self._timers.pop(pin, None)
        log.debug("GPIO released pin=%d", pin)

    def _release_all(self) -> None:
        if not _GPIO_AVAILABLE or GPIO is None:
            return
        for pin in self._pins:
            try:
                GPIO.output(pin, GPIO.LOW)
            except Exception:
                pass
