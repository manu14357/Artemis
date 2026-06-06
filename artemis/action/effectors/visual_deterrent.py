"""
artemis/action/effectors/visual_deterrent.py
Visual deterrent effector for drone countermeasures.

Uses high-intensity strobe lights and/or laser dazzlers to disorient
drone operators and/or onboard cameras.

Legal considerations:
- Strobe lights: Generally legal for property protection
- Laser dazzlers: Regulated in many jurisdictions
  * USA: FDA regulates laser products; dazzlers may require authorization
  * EU: EN 60825 laser safety standards
  * India: Similar regulations
- Maximum permissible exposure (MPE) must be calculated for laser use
- Class 3R (<5mW visible) generally permitted for non-eye-safe distances
- Never aim at manned aircraft or people

Hardware options:
- High-power LED strobe (10,000-100,000 lumens) - legal, effective at night
- Green laser dazzler (532nm, 5mW, Class 3R) - effective against cameras
- Commercial: Nightstick, Laser Genetics, or DIY with CREE LEDs + driver

GPIO mapping (via GPIORelayEffector):
- TRACK_ONLY → Pin 2: Visual alert/strobe activation
- ENGAGE_SOFT → Pin 1: Laser dazzler (if separate from audio)
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import paho.mqtt.client as mqtt

from artemis.cognition.agents.command_router import EngagementTier
from artemis.core.logging import get_logger

log = get_logger("action.visual_deterrent")

# Try to import GPIO
try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
except ImportError:
    GPIO = None  # type: ignore
    _HAS_GPIO = False
    log.warning("RPi.GPIO not installed — VisualDeterrent running in simulation mode")


class VisualMode(Enum):
    """Visual deterrent modes."""
    STROBE_WHITE = "strobe_white"       # High-intensity white strobe
    STROBE_RED_BLUE = "strobe_red_blue" # Emergency-style red/blue
    STROBE_GREEN = "strobe_green"       # Green strobe (laser-like)
    LASER_DAZZLE = "laser_dazzle"       # Continuous laser dazzler
    LASER_SCAN = "laser_scan"           # Scanning laser pattern
    COMBINED = "combined"               # Strobe + laser


@dataclass
class VisualConfig:
    """Visual deterrent configuration."""
    # GPIO pins (BCM numbering)
    strobe_pin: int = 22        # White/color strobe LED
    laser_pin: int = 23         # Laser dazzler
    # Strobe parameters
    strobe_frequency_hz: float = 10.0
    strobe_duty_cycle: float = 0.5
    # Laser parameters (if using PWM for intensity control)
    laser_pwm_frequency_hz: int = 1000
    laser_max_duty_cycle: float = 0.5  # Limit to 50% for safety
    # Safety
    max_duration_s: float = 60.0
    cooldown_s: float = 5.0


class VisualDeterrent:
    """
    Visual deterrent effector (strobe + laser dazzler).

    Subscribes to MQTT commands and activates visual deterrents.
    Designed for TRACK_ONLY and ENGAGE_SOFT tier responses.

    Parameters
    ----------
    effector_id : str
    broker : str
    port : int
    config : VisualConfig
    username / password : MQTT credentials
    """

    def __init__(
        self,
        effector_id: str = "visual-deterrent-01",
        broker: str = "127.0.0.1",
        port: int = 1883,
        keepalive: int = 60,
        config: Optional[VisualConfig] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.effector_id = effector_id
        self._broker = broker
        self._port = port
        self._keepalive = keepalive
        self._config = config or VisualConfig()
        self._topic = f"artemis/commands/{effector_id}"
        self._stop_flag = threading.Event()

        # State
        self._active_mode: Optional[VisualMode] = None
        self._active_timer: Optional[threading.Timer] = None
        self._cooldown_timer: Optional[threading.Timer] = None
        self._strobe_pwm = None
        self._laser_pwm = None
        self._lock = threading.Lock()

        # Initialize GPIO if available
        if _HAS_GPIO and GPIO is not None:
            self._init_gpio()

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"artemis-visual-{effector_id}",
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    def _init_gpio(self) -> None:
        """Initialize GPIO pins for strobe and laser."""
        if not _HAS_GPIO or GPIO is None:
            return

        # Strobe pin - simple on/off
        GPIO.setup(self._config.strobe_pin, GPIO.OUT, initial=GPIO.LOW)

        # Laser pin - PWM for intensity control
        GPIO.setup(self._config.laser_pin, GPIO.OUT, initial=GPIO.LOW)
        self._laser_pwm = GPIO.PWM(self._config.laser_pin, self._config.laser_pwm_frequency_hz)
        self._laser_pwm.start(0)

        # Strobe PWM
        self._strobe_pwm = GPIO.PWM(self._config.strobe_pin, self._config.strobe_frequency_hz)
        self._strobe_pwm.start(0)

        log.info("VisualDeterrent GPIO initialized: strobe_pin=%d, laser_pin=%d",
                self._config.strobe_pin, self._config.laser_pin)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Connect to broker and block until stop() is called."""
        self._client.connect(self._broker, self._port, self._keepalive)
        self._client.loop_start()
        self._stop_flag.wait()
        self._client.loop_stop()
        self._client.disconnect()

    def stop(self) -> None:
        """Stop all visual outputs and disconnect."""
        self._stop_flag.set()
        self._deactivate_all()
        try:
            self._client.disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, connect_flags, reason_code, properties=None) -> None:
        if reason_code.value == 0:
            client.subscribe(self._topic, qos=1)
            log.info("VisualDeterrent connected effector_id=%s", self.effector_id)
        else:
            log.error("VisualDeterrent MQTT connect failed rc=%s", reason_code)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None) -> None:
        rc = getattr(reason_code, "value", reason_code)
        log.info("VisualDeterrent disconnected rc=%s", rc)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.error("VisualDeterrent bad payload: %s", exc)
            return

        try:
            tier = EngagementTier(payload.get("tier", "ignore"))
        except ValueError:
            log.warning("Unknown tier in command: %s", payload.get("tier"))
            return

        # Visual deterrent activates on TRACK_ONLY (strobe) and ENGAGE_SOFT (laser)
        if tier not in (EngagementTier.TRACK_ONLY, EngagementTier.ENGAGE_SOFT):
            return

        duration_s = min(float(payload.get("duration_s", 10.0)), self._config.max_duration_s)
        mode_name = payload.get("mode", "strobe_white" if tier == EngagementTier.TRACK_ONLY else "laser_dazzle")

        try:
            mode = VisualMode(mode_name)
        except ValueError:
            mode = VisualMode.STROBE_WHITE if tier == EngagementTier.TRACK_ONLY else VisualMode.LASER_DAZZLE
            log.warning("Unknown mode %s, using default", mode_name)

        self._activate_mode(mode, duration_s)
        log.info(
            "Visual deterrent activated: mode=%s duration=%.1fs tier=%s",
            mode.value, duration_s, tier.value
        )

    # ------------------------------------------------------------------
    # Visual output control
    # ------------------------------------------------------------------

    def _activate_mode(self, mode: VisualMode, duration_s: float) -> None:
        """Activate a visual deterrent mode for specified duration."""
        with self._lock:
            # Cancel any existing timers
            if self._active_timer:
                self._active_timer.cancel()
            if self._cooldown_timer:
                self._cooldown_timer.cancel()

            self._deactivate_all()

            if not _HAS_GPIO or GPIO is None:
                log.info("[SIM] Visual deterrent: %s for %.1fs", mode.value, duration_s)
                self._active_mode = mode
                self._active_timer = threading.Timer(duration_s, self._deactivate_all)
                self._active_timer.daemon = True
                self._active_timer.start()
                return

            # Activate hardware
            if mode in (VisualMode.STROBE_WHITE, VisualMode.STROBE_RED_BLUE, VisualMode.STROBE_GREEN):
                # Strobe mode
                duty = self._config.strobe_duty_cycle * 100
                self._strobe_pwm.ChangeFrequency(self._config.strobe_frequency_hz)
                self._strobe_pwm.ChangeDutyCycle(duty)

            elif mode == VisualMode.LASER_DAZZLE:
                # Continuous laser at limited power
                duty = self._config.laser_max_duty_cycle * 100
                self._laser_pwm.ChangeDutyCycle(duty)

            elif mode == VisualMode.LASER_SCAN:
                # Scanning pattern - vary PWM duty cycle
                self._start_laser_scan()

            elif mode == VisualMode.COMBINED:
                # Both strobe and laser
                duty = self._config.strobe_duty_cycle * 100
                self._strobe_pwm.ChangeFrequency(self._config.strobe_frequency_hz)
                self._strobe_pwm.ChangeDutyCycle(duty)
                laser_duty = self._config.laser_max_duty_cycle * 100
                self._laser_pwm.ChangeDutyCycle(laser_duty)

            self._active_mode = mode

            # Auto-deactivate after duration
            self._active_timer = threading.Timer(duration_s, self._deactivate_all)
            self._active_timer.daemon = True
            self._active_timer.start()

            # Cooldown period before next activation
            self._cooldown_timer = threading.Timer(
                duration_s + self._config.cooldown_s,
                lambda: None  # Just a placeholder
            )
            self._cooldown_timer.daemon = True
            self._cooldown_timer.start()

    def _start_laser_scan(self) -> None:
        """Start a scanning laser pattern (simulated via PWM variation)."""
        # In a real implementation, this would drive a servo/galvo
        # Here we simulate by varying PWM duty cycle
        def scan_loop():
            import numpy as np
            start = time.time()
            while self._active_mode == VisualMode.LASER_SCAN and not self._stop_flag.is_set():
                elapsed = time.time() - start
                # Sinusoidal scan pattern
                duty = (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * elapsed)) * self._config.laser_max_duty_cycle * 100
                if _HAS_GPIO and self._laser_pwm:
                    self._laser_pwm.ChangeDutyCycle(duty)
                time.sleep(0.02)  # 50 Hz update

        import threading
        scan_thread = threading.Thread(target=scan_loop, daemon=True)
        scan_thread.start()

    def _deactivate_all(self) -> None:
        """Turn off all visual outputs."""
        with self._lock:
            if _HAS_GPIO and GPIO is not None:
                if self._strobe_pwm:
                    self._strobe_pwm.ChangeDutyCycle(0)
                if self._laser_pwm:
                    self._laser_pwm.ChangeDutyCycle(0)
                try:
                    GPIO.output(self._config.strobe_pin, GPIO.LOW)
                    GPIO.output(self._config.laser_pin, GPIO.LOW)
                except Exception:
                    pass
            self._active_mode = None
            log.debug("Visual deterrent deactivated")