"""
artemis/action/effectors/audio_deterrent.py
Directional audio deterrent effector for drone countermeasures.

Uses parametric speaker array or high-SPL directional speaker to project
deterrent sounds toward detected drones:
- Predator calls (hawk, eagle, falcon)
- Disorienting tones (warbling, sweeping frequencies)
- Drone-specific alarm signals

Legal: Audio deterrents are legal in most jurisdictions for property protection.
Check local noise ordinances for maximum SPL and operating hours.

Hardware options:
- Parametric array (ultrasonic carrier + audible modulation) - highly directional
- Horn-loaded compression driver + waveguide - 120-140 dB SPL
- Commercial: LRAD, HyperSpike, or DIY with Dayton Audio drivers

GPIO mapping (via GPIORelayEffector):
- ENGAGE_SOFT → Pin 1: Audio deterrent activation
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt

from artemis.cognition.agents.command_router import EngagementTier
from artemis.core.logging import get_logger

log = get_logger("action.audio_deterrent")

# Try to import audio libraries
try:
    import sounddevice as sd
    import soundfile as sf
    _HAS_AUDIO = True
except ImportError:
    sd = None  # type: ignore
    sf = None  # type: ignore
    _HAS_AUDIO = False
    log.warning("sounddevice/soundfile not installed — AudioDeterrent running in simulation mode")


class DeterrentSound(Enum):
    """Pre-defined deterrent sound profiles."""
    HAWK_SCREECH = "hawk_screech"
    EAGLE_CALL = "eagle_call"
    FALCON_CRY = "falcon_cry"
    WARBLING_TONE = "warbling_tone"
    SWEEP_UP = "sweep_up"
    SWEEP_DOWN = "sweep_down"
    DRONE_ALARM = "drone_alarm"
    WHITE_NOISE_BURST = "white_noise_burst"


@dataclass
class AudioConfig:
    """Audio deterrent configuration."""
    device_index: int = 0
    sample_rate: int = 48000
    max_duration_s: float = 30.0
    default_volume_db: float = -6.0  # Relative to full scale
    sounds_dir: str = "assets/audio_deterrent"


class AudioDeterrent:
    """
    Directional audio deterrent effector.

    Subscribes to MQTT commands and plays deterrent sounds through
    a directional speaker array. Designed for ENGAGE_SOFT tier responses.

    Parameters
    ----------
    effector_id : str
    broker : str
    port : int
    config : AudioConfig
    username / password : MQTT credentials
    """

    def __init__(
        self,
        effector_id: str = "audio-deterrent-01",
        broker: str = "127.0.0.1",
        port: int = 1883,
        keepalive: int = 60,
        config: Optional[AudioConfig] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.effector_id = effector_id
        self._broker = broker
        self._port = port
        self._keepalive = keepalive
        self._config = config or AudioConfig()
        self._topic = f"artemis/commands/{effector_id}"
        self._stop_flag = threading.Event()

        # Sound cache
        self._sound_cache: dict[DeterrentSound, np.ndarray] = {}
        self._current_stream = None
        self._stream_lock = threading.Lock()

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"artemis-audio-{effector_id}",
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        # Load sounds if audio available
        if _HAS_AUDIO:
            self._load_sounds()

    def _load_sounds(self) -> None:
        """Load deterrent sound files from disk."""
        sounds_dir = Path(self._config.sounds_dir)
        if not sounds_dir.exists():
            log.warning("Audio deterrent sounds directory not found: %s", sounds_dir)
            self._generate_synthetic_sounds()
            return

        for sound in DeterrentSound:
            path = sounds_dir / f"{sound.value}.wav"
            if path.exists():
                try:
                    data, sr = sf.read(path, dtype='float32')
                    if sr != self._config.sample_rate:
                        # Resample
                        from scipy.signal import resample
                        data = resample(data, int(len(data) * self._config.sample_rate / sr))
                    # Ensure mono
                    if data.ndim > 1:
                        data = data[:, 0]
                    self._sound_cache[sound] = data
                    log.debug("Loaded sound: %s (%d samples)", sound.value, len(data))
                except Exception as e:
                    log.warning("Failed to load sound %s: %s", path, e)

        if not self._sound_cache:
            log.warning("No sound files loaded, generating synthetic")
            self._generate_synthetic_sounds()

    def _generate_synthetic_sounds(self) -> None:
        """Generate synthetic deterrent sounds if files not available."""
        import numpy as np
        sr = self._config.sample_rate
        duration = 3.0  # 3 second loops

        # Hawk screech: high frequency modulated tone
        t = np.arange(int(sr * duration)) / sr
        hawk = 0.5 * np.sin(2 * np.pi * 3000 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 8 * t))
        self._sound_cache[DeterrentSound.HAWK_SCREECH] = hawk.astype(np.float32)

        # Eagle call: descending frequency
        eagle = 0.5 * np.sin(2 * np.pi * (2500 - 1000 * t) * t)
        self._sound_cache[DeterrentSound.EAGLE_CALL] = eagle.astype(np.float32)

        # Warbling tone: frequency modulation
        warble = 0.5 * np.sin(2 * np.pi * (1000 + 500 * np.sin(2 * np.pi * 4 * t)) * t)
        self._sound_cache[DeterrentSound.WARBLING_TONE] = warble.astype(np.float32)

        # Sweep up
        sweep_up = 0.5 * np.sin(2 * np.pi * (500 + 2000 * t / duration) * t)
        self._sound_cache[DeterrentSound.SWEEP_UP] = sweep_up.astype(np.float32)

        # Sweep down
        sweep_down = 0.5 * np.sin(2 * np.pi * (2500 - 2000 * t / duration) * t)
        self._sound_cache[DeterrentSound.SWEEP_DOWN] = sweep_down.astype(np.float32)

        # Drone alarm: pulsed tone
        pulse = 0.5 * np.sin(2 * np.pi * 1500 * t) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 10 * t)))
        self._sound_cache[DeterrentSound.DRONE_ALARM] = pulse.astype(np.float32)

        # White noise burst
        noise = 0.3 * np.random.randn(int(sr * duration)).astype(np.float32)
        self._sound_cache[DeterrentSound.WHITE_NOISE_BURST] = noise

        log.info("Generated %d synthetic deterrent sounds", len(self._sound_cache))

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
        """Stop any playing sound and disconnect."""
        self._stop_flag.set()
        self._stop_sound()
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
            log.info("AudioDeterrent connected effector_id=%s", self.effector_id)
        else:
            log.error("AudioDeterrent MQTT connect failed rc=%s", reason_code)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None) -> None:
        rc = getattr(reason_code, "value", reason_code)
        log.info("AudioDeterrent disconnected rc=%s", rc)

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            log.error("AudioDeterrent bad payload: %s", exc)
            return

        try:
            tier = EngagementTier(payload.get("tier", "ignore"))
        except ValueError:
            log.warning("Unknown tier in command: %s", payload.get("tier"))
            return

        if tier != EngagementTier.ENGAGE_SOFT:
            # Audio deterrent only activates on ENGAGE_SOFT
            return

        duration_s = min(float(payload.get("duration_s", 10.0)), self._config.max_duration_s)
        sound_name = payload.get("sound", "warbling_tone")
        volume_db = float(payload.get("volume_db", self._config.default_volume_db))

        try:
            sound = DeterrentSound(sound_name)
        except ValueError:
            sound = DeterrentSound.WARBLING_TONE
            log.warning("Unknown sound %s, using default", sound_name)

        self._play_sound(sound, duration_s, volume_db)
        log.info(
            "Audio deterrent activated: sound=%s duration=%.1fs volume=%.1fdB",
            sound.value, duration_s, volume_db
        )

    # ------------------------------------------------------------------
    # Audio playback
    # ------------------------------------------------------------------

    def _play_sound(self, sound: DeterrentSound, duration_s: float, volume_db: float) -> None:
        """Play a deterrent sound for specified duration."""
        if not _HAS_AUDIO:
            log.info("[SIM] Would play %s for %.1fs at %.1fdB", sound.value, duration_s, volume_db)
            return

        if sound not in self._sound_cache:
            log.warning("Sound %s not in cache", sound.value)
            return

        audio_data = self._sound_cache[sound]
        # Apply volume
        gain = 10 ** (volume_db / 20.0)
        audio_data = audio_data * gain

        # Loop audio to fill duration
        if len(audio_data) / self._config.sample_rate < duration_s:
            repeats = int(np.ceil(duration_s * self._config.sample_rate / len(audio_data)))
            audio_data = np.tile(audio_data, repeats)

        # Trim to exact duration
        target_samples = int(duration_s * self._config.sample_rate)
        audio_data = audio_data[:target_samples]

        with self._stream_lock:
            self._stop_sound()
            try:
                self._current_stream = sd.play(
                    audio_data,
                    samplerate=self._config.sample_rate,
                    device=self._config.device_index,
                    blocking=False,
                )
            except Exception as e:
                log.error("Audio playback failed: %s", e)

    def _stop_sound(self) -> None:
        """Stop currently playing sound."""
        if not _HAS_AUDIO:
            return
        with self._stream_lock:
            if self._current_stream is not None:
                try:
                    sd.stop()
                except Exception:
                    pass
                self._current_stream = None


# Import numpy for synthetic sound generation
import numpy as np