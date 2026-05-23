#!/usr/bin/env python3
"""
hub/main.py
ARTEMIS hub daemon — entry point.

Starts:
  1. Mosquitto MQTT broker (via subprocess, unless --no-broker)
  2. MeshAggregator (MQTT subscriber + fusion loop)
  3. MQTTPublisher (for outbound threat/command messages)
  4. FastAPI REST + WebSocket server (uvicorn)

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

from artemis.api.rest import create_app
from artemis.api.websocket import register_websocket
from artemis.core.config import HubConfig
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
        log.warning("mosquitto not found in PATH — assuming broker is running externally")
        return None


async def _run(cfg: HubConfig, manage_broker: bool) -> None:
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

    # Mesh aggregator + fusion loop
    loop = asyncio.get_running_loop()
    aggregator = MeshAggregator(
        config=cfg,
        track_manager=track_manager,
        threat_map=threat_map,
        publisher=publisher,
        fusion_cycle_hz=cfg.api.ws_push_rate_hz,
    )
    aggregator.start(loop=loop)

    # FastAPI
    app = create_app(
        threat_map=threat_map,
        aggregator=aggregator,
        cors_origins=cfg.api.cors_origins,
    )
    register_websocket(app, threat_map, ws_push_rate_hz=cfg.api.ws_push_rate_hz)

    server_cfg = uvicorn.Config(
        app=app,
        host=cfg.host,
        port=cfg.api_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(server_cfg)

    log.info(
        "hub ready  id=%s  api=http://%s:%d  broker=%s:%d",
        cfg.id, cfg.host, cfg.api_port, cfg.mqtt.broker, cfg.mqtt.port,
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
        publisher.disconnect()
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
    setup_logging(
        level=cfg.logging.level,
        log_file=cfg.logging.file,
        rotate_mb=cfg.logging.rotate_mb,
        keep_backups=cfg.logging.keep_backups,
    )
    log.info("loaded config %s", cfg_path)

    try:
        asyncio.run(_run(cfg, manage_broker=not args.no_broker))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
