#!/usr/bin/env python3
"""
hub/main.py
ARTEMIS hub daemon — entry point.

Starts:
  1. Mosquitto MQTT broker (via subprocess, unless --no-broker)
  2. MeshAggregator (MQTT subscriber + fusion loop)
  3. MQTTPublisher (for outbound threat/command messages)
  4. CognitionPipeline (ThreatScorer → CommandRouter → SchedulerAgent)
  5. EffectorManager (SimRelay; GPIO relay if enabled in config)
  6. FastAPI REST + WebSocket server (uvicorn)

Usage:
    python hub/main.py --config hub/config/hub_default.yaml [--no-broker]
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import subprocess
import sys

import uvicorn

from artemis.action.effectors.effector_manager import EffectorManager
from artemis.action.effectors.sim_relay import SimRelay
from artemis.action.engagement_log import EngagementLog
from artemis.api.metrics import get_metrics
from artemis.api.rest import create_app
from artemis.api.websocket import register_websocket
from artemis.cognition.agents.classifier_agent import ClassifierAgent
from artemis.cognition.agents.command_router import CommandRouter
from artemis.cognition.agents.scheduler_agent import SchedulerAgent
from artemis.cognition.agents.threat_scorer import ThreatScorer
from artemis.cognition.pipeline import CognitionPipeline
from artemis.core.config import ConfigWatcher, HubConfig
from artemis.core.config_validator import apply_hub_env_overrides, validate_hub_config
from artemis.core.logging import get_logger, setup_logging
from artemis.fusion.threat_map import ThreatMap
from artemis.fusion.track_manager import TrackManager
from artemis.mesh.aggregator import MeshAggregator
from artemis.mesh.publisher import MQTTPublisher

log = get_logger("hub.main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARTEMIS Hub Daemon")
    parser.add_argument(
        "--config",
        default="hub/config/hub_default.yaml",
        help="Path to hub config YAML",
    )
    parser.add_argument(
        "--no-broker",
        action="store_true",
        help="Do not start Mosquitto (broker already running externally)",
    )
    return parser.parse_args()


def _start_mosquitto() -> subprocess.Popen | None:
    try:
        proc = subprocess.Popen(
            ["mosquitto"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log.info("mosquitto started pid=%d", proc.pid)
        return proc
    except FileNotFoundError:
        log.warning(
            "mosquitto not found in PATH — assuming broker is running externally"
        )
        return None


async def _run(cfg: HubConfig, manage_broker: bool, cfg_path: pathlib.Path | None = None) -> None:
    mosquitto_proc: subprocess.Popen | None = None

    if manage_broker:
        mosquitto_proc = _start_mosquitto()
        if mosquitto_proc:
            await asyncio.sleep(0.5)

    # Shared state
    threat_map = ThreatMap()
    track_manager = TrackManager(
        process_noise_q=cfg.fusion.ekf.process_noise_q,
        measurement_noise_r=cfg.fusion.ekf.measurement_noise_r,
        max_coast_frames=cfg.fusion.ekf.max_coast_frames,
        max_distance_m=cfg.fusion.assignment.max_distance_m,
        min_sensor_layers=cfg.fusion.confirmation.min_sensor_layers,
    )

    # MQTT publisher
    publisher = MQTTPublisher(
        broker=cfg.mqtt.broker,
        port=cfg.mqtt.port,
        node_id=cfg.id,
        keepalive=cfg.mqtt.keepalive,
        username=cfg.mqtt.username,
        password=cfg.mqtt.password,
    )
    publisher.connect()
    for _ in range(30):
        if publisher.connected:
            break
        await asyncio.sleep(0.1)

    # Engagement log
    engagement_log = EngagementLog(path=cfg.engagement_log.path)

    # Effector manager — register SimRelay by default
    effector_manager = EffectorManager()
    if cfg.effectors.sim_relay.enabled:
        sim_relay = SimRelay(
            effector_id=cfg.effectors.sim_relay.effector_id,
            broker=cfg.mqtt.broker,
            port=cfg.mqtt.port,
            username=cfg.mqtt.username,
            password=cfg.mqtt.password,
        )
        effector_manager.register(sim_relay)
    if cfg.effectors.gpio_relay.enabled:
        from artemis.action.effectors.gpio_relay import GPIORelayEffector

        gpio_relay = GPIORelayEffector(
            effector_id=cfg.effectors.gpio_relay.effector_id,
            broker=cfg.mqtt.broker,
            port=cfg.mqtt.port,
            pins=cfg.effectors.gpio_relay.pins,
            username=cfg.mqtt.username,
            password=cfg.mqtt.password,
        )
        effector_manager.register(gpio_relay)
    if cfg.effectors.audio_deterrent.enabled:
        from artemis.action.effectors.audio_deterrent import AudioDeterrent, AudioConfig

        audio_config = AudioConfig(
            device_index=cfg.effectors.audio_deterrent.device_index,
            sample_rate=cfg.effectors.audio_deterrent.sample_rate,
            max_duration_s=cfg.effectors.audio_deterrent.max_duration_s,
            default_volume_db=cfg.effectors.audio_deterrent.default_volume_db,
            sounds_dir=cfg.effectors.audio_deterrent.sounds_dir,
        )
        audio_deterrent = AudioDeterrent(
            effector_id=cfg.effectors.audio_deterrent.effector_id,
            broker=cfg.mqtt.broker,
            port=cfg.mqtt.port,
            username=cfg.mqtt.username,
            password=cfg.mqtt.password,
            config=audio_config,
        )
        effector_manager.register(audio_deterrent)
    if cfg.effectors.visual_deterrent.enabled:
        from artemis.action.effectors.visual_deterrent import VisualDeterrent, VisualConfig

        visual_config = VisualConfig(
            strobe_pin=cfg.effectors.visual_deterrent.strobe_pin,
            laser_pin=cfg.effectors.visual_deterrent.laser_pin,
            strobe_frequency_hz=cfg.effectors.visual_deterrent.strobe_frequency_hz,
            strobe_duty_cycle=cfg.effectors.visual_deterrent.strobe_duty_cycle,
            laser_pwm_frequency_hz=cfg.effectors.visual_deterrent.laser_pwm_frequency_hz,
            laser_max_duty_cycle=cfg.effectors.visual_deterrent.laser_max_duty_cycle,
            max_duration_s=cfg.effectors.visual_deterrent.max_duration_s,
            cooldown_s=cfg.effectors.visual_deterrent.cooldown_s,
        )
        visual_deterrent = VisualDeterrent(
            effector_id=cfg.effectors.visual_deterrent.effector_id,
            broker=cfg.mqtt.broker,
            port=cfg.mqtt.port,
            username=cfg.mqtt.username,
            password=cfg.mqtt.password,
            config=visual_config,
        )
        effector_manager.register(visual_deterrent)
    effector_manager.start_all()

    # Metrics singleton — mark hub as up
    metrics = get_metrics()
    metrics.set_hub_up(True)

    # Cognition pipeline — ClassifierAgent wired in
    cognition_pipeline = CognitionPipeline(
        scorer=ThreatScorer(),
        router=CommandRouter(),
        scheduler=SchedulerAgent(),
        classifier=ClassifierAgent(),
        publisher=publisher,
        engagement_log=engagement_log,
        effector_manager=effector_manager,
        effectors=effector_manager.get_active_effectors(),
    )

    # Mesh aggregator + fusion loop (pipeline injected here)
    loop = asyncio.get_running_loop()
    aggregator = MeshAggregator(
        config=cfg,
        track_manager=track_manager,
        threat_map=threat_map,
        publisher=publisher,
        fusion_cycle_hz=cfg.api.ws_push_rate_hz,
        pipeline=cognition_pipeline,
    )
    aggregator.start(loop=loop)

    # Config hot-reload watcher — updates fusion thresholds on YAML change
    _cfg_path = cfg_path

    def _on_config_change(path) -> None:
        try:
            new_cfg = HubConfig.from_yaml(path)
            new_cfg = apply_hub_env_overrides(new_cfg)
            track_manager._max_coast = new_cfg.fusion.ekf.max_coast_frames
            track_manager._max_dist = new_cfg.fusion.assignment.max_distance_m
            track_manager._min_layers = new_cfg.fusion.confirmation.min_sensor_layers
            log.info("Config hot-reloaded from %s", path)
        except Exception as exc:
            log.error("Config reload failed: %s", exc)

    config_watcher: ConfigWatcher | None = None
    if _cfg_path and _cfg_path.exists():
        config_watcher = ConfigWatcher(_cfg_path, _on_config_change)
        config_watcher.start()
        log.info("Config watcher started, watching %s", _cfg_path)

    # FastAPI (publisher + engagement_log + effector_manager wired in)
    app = create_app(
        threat_map=threat_map,
        aggregator=aggregator,
        cors_origins=cfg.api.cors_origins,
        publisher=publisher,
        engagement_log=engagement_log,
        effector_manager=effector_manager,
        rate_limit_per_min=cfg.api.rate_limit_per_min,
    )
    register_websocket(app, threat_map, ws_push_rate_hz=cfg.api.ws_push_rate_hz)

    server_cfg = uvicorn.Config(
        app=app,
        host=cfg.host,
        port=cfg.api_port,
        log_level="warning",
        loop="auto",
    )
    server = uvicorn.Server(server_cfg)

    log.info(
        "hub ready  id=%s  api=http://%s:%d  broker=%s:%d",
        cfg.id,
        cfg.host,
        cfg.api_port,
        cfg.mqtt.broker,
        cfg.mqtt.port,
    )

    try:
        await asyncio.gather(
            aggregator.run(),
            server.serve(),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("shutdown requested")
    finally:
        aggregator.stop()
        effector_manager.stop_all()
        publisher.disconnect()
        if config_watcher:
            config_watcher.stop()
        if mosquitto_proc:
            mosquitto_proc.terminate()
            try:
                mosquitto_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                mosquitto_proc.kill()
        log.info("hub stopped")


def main() -> int:
    args = parse_args()
    cfg_path = pathlib.Path(args.config)
    if not cfg_path.exists():
        print(f"[hub] config not found: {cfg_path}", file=sys.stderr)
        return 1

    cfg = HubConfig.from_yaml(cfg_path)
    cfg = apply_hub_env_overrides(cfg)
    setup_logging(
        level=cfg.logging.level,
        log_file=cfg.logging.file,
        rotate_mb=cfg.logging.rotate_mb,
        keep_backups=cfg.logging.keep_backups,
    )
    log.info("loaded config %s", cfg_path)
    for _w in validate_hub_config(cfg):
        log.warning("[config] %s", _w)

    try:
        asyncio.run(_run(cfg, manage_broker=not args.no_broker, cfg_path=pathlib.Path(cfg_path)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
