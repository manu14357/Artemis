#!/usr/bin/env python3
"""
node/main.py
ARTEMIS edge-node daemon.

Responsibilities:
  1. Load NodeConfig from YAML (--config).
  2. Instantiate only *enabled* perception drivers.
  3. Run each driver's stream() loop in a concurrent asyncio task.
  4. Publish every Detection to the MQTT broker via MQTTPublisher.
  5. Emit a heartbeat (NodeStatus) every ~5 s with CPU/mem stats.
  6. Handle SIGTERM / SIGINT cleanly; notify systemd via sd_notify READY=1.

Usage:
    python node/main.py --config node/config/node_default.yaml

Test mode (--test-mode):
    Runs each enabled driver for 10 s then exits — useful for CI / hardware
    smoke-test without long-running loops.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional psutil (graceful fallback if not installed on bare metal)
# ---------------------------------------------------------------------------
try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

from artemis.core.config import NodeConfig
from artemis.core.config_validator import apply_node_env_overrides, validate_node_config
from artemis.core.logging import get_logger, setup_logging
from artemis.core.types import NodeStatus, SensorLayer
from artemis.mesh.publisher import MQTTPublisher
from artemis.perception.base import DriverStatus, PerceptionDriver

log = get_logger("node.main")

# Heartbeat interval in seconds
_HEARTBEAT_INTERVAL_S = 5.0
# Systemd sd_notify socket (optional)
_NOTIFY_SOCKET_ENV = "NOTIFY_SOCKET"


# ---------------------------------------------------------------------------
# sd_notify helper (no dependency on sdnotify package)
# ---------------------------------------------------------------------------


def _sd_notify(msg: str) -> None:
    """Send a sd_notify message if NOTIFY_SOCKET is set."""
    import os, socket  # noqa: E401

    sock_path = os.environ.get(_NOTIFY_SOCKET_ENV)
    if not sock_path:
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(msg.encode(), sock_path)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------------


def _build_drivers(cfg: NodeConfig) -> list[tuple[SensorLayer, PerceptionDriver]]:
    """
    Instantiate each enabled sensor driver.
    Returns list of (SensorLayer, driver) pairs.
    """
    drivers: list[tuple[SensorLayer, PerceptionDriver]] = []
    sensors = cfg.sensors
    node_id = cfg.id

    if sensors.rf.enabled:
        try:
            from artemis.perception.rf.rtlsdr_listener import RTLSDRListener

            drivers.append(
                (
                    SensorLayer.RF,
                    RTLSDRListener(
                        node_id,
                        frequencies=sensors.rf.frequencies,
                        fft_size=sensors.rf.fft_size,
                        threshold_db=sensors.rf.threshold_db,
                    ),
                )
            )
            log.info("RF driver enabled")
        except ImportError as exc:
            log.warning("RF driver skipped: %s", exc)

    if sensors.acoustic.enabled:
        try:
            from artemis.perception.acoustic.classifier import AcousticClassifier

            drivers.append(
                (
                    SensorLayer.ACOUSTIC,
                    AcousticClassifier(
                        node_id,
                        sample_rate=sensors.acoustic.sample_rate,
                        channels=sensors.acoustic.channels,
                        device_index=sensors.acoustic.device_index,
                        window_ms=sensors.acoustic.window_ms,
                        model_path=sensors.acoustic.model_path,
                        confidence_threshold=sensors.acoustic.confidence_threshold,
                    ),
                )
            )
            log.info("Acoustic driver enabled")
        except ImportError as exc:
            log.warning("Acoustic driver skipped: %s", exc)

    if sensors.radar.enabled:
        try:
            from artemis.perception.radar.xm125_processor import XM125Processor

            drivers.append(
                (
                    SensorLayer.RADAR,
                    XM125Processor(
                        node_id,
                        serial_port=sensors.radar.serial_port,
                        start_point=sensors.radar.start_point,
                        num_points=sensors.radar.num_points,
                        step_length=sensors.radar.step_length,
                        profile=sensors.radar.profile,
                    ),
                )
            )
            log.info("Radar driver enabled")
        except ImportError as exc:
            log.warning("Radar driver skipped: %s", exc)

    if sensors.optical.enabled:
        try:
            from artemis.perception.optical.detector import OpticalDetector

            resolution = tuple(sensors.optical.resolution[:2])
            drivers.append(
                (
                    SensorLayer.OPTICAL,
                    OpticalDetector(
                        node_id,
                        resolution=resolution,
                        fps=sensors.optical.fps,
                        mog2_learning_rate=sensors.optical.mog2_learning_rate,
                        min_blob_area=sensors.optical.min_blob_area,
                    ),
                )
            )
            log.info("Optical driver enabled")
        except ImportError as exc:
            log.warning("Optical driver skipped: %s", exc)

    return drivers


# ---------------------------------------------------------------------------
# Driver task runner
# ---------------------------------------------------------------------------


async def _run_driver(
    layer: SensorLayer,
    driver: PerceptionDriver,
    publisher: MQTTPublisher,
    stop_event: asyncio.Event,
) -> None:
    """
    Async task that streams detections from one driver and publishes them.
    Stops when stop_event is set or driver raises.
    """
    _publish_fn = {
        SensorLayer.RF: publisher.publish_rf,
        SensorLayer.ACOUSTIC: publisher.publish_acoustic,
        SensorLayer.RADAR: publisher.publish_radar,
        SensorLayer.OPTICAL: publisher.publish_optical,
    }[layer]

    try:
        await driver.start()
        async for detection in driver.stream():
            if stop_event.is_set():
                break
            _publish_fn(detection)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        log.error("Driver %s error: %s", layer.value, exc)
    finally:
        if driver.status != DriverStatus.STOPPED:
            await driver.stop()
        log.info("Driver %s stopped", layer.value)


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------


async def _heartbeat_loop(
    publisher: MQTTPublisher,
    cfg: NodeConfig,
    active_layers: list[SensorLayer],
    stop_event: asyncio.Event,
) -> None:
    """Emit NodeStatus every HEARTBEAT_INTERVAL_S seconds."""
    while not stop_event.is_set():
        cpu = psutil.cpu_percent(interval=None) if _HAS_PSUTIL else 0.0
        mem = psutil.virtual_memory().percent if _HAS_PSUTIL else 0.0

        status = NodeStatus(
            node_id=cfg.id,
            lat=cfg.location.lat,
            lon=cfg.location.lon,
            alt_m=cfg.location.alt_m,
            sensors_active=[layer.value for layer in active_layers],
            last_heartbeat=time.time(),
            online=True,
            cpu_percent=cpu,
            mem_percent=mem,
        )
        try:
            publisher.publish_status(status)
        except Exception as exc:  # noqa: BLE001
            log.warning("Heartbeat publish error: %s", exc)

        try:
            await asyncio.wait_for(
                asyncio.shield(stop_event.wait()),
                timeout=_HEARTBEAT_INTERVAL_S,
            )
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Main async entry-point
# ---------------------------------------------------------------------------


async def _async_main(cfg: NodeConfig, test_mode: bool) -> int:
    """
    Async main: wire up all drivers, publisher, and heartbeat.
    """
    log.info("ARTEMIS node starting: id=%s test_mode=%s", cfg.id, test_mode)

    # Build publisher and connect
    publisher = MQTTPublisher(
        node_id=cfg.id,
        broker=cfg.mqtt.broker,
        port=cfg.mqtt.port,
        keepalive=cfg.mqtt.keepalive,
        username=cfg.mqtt.username,
        password=cfg.mqtt.password,
        node_topic_prefix=cfg.mqtt.node_topic_prefix,
    )
    try:
        await asyncio.to_thread(publisher.connect)
        log.info("MQTT connected to %s:%d", cfg.mqtt.broker, cfg.mqtt.port)
    except Exception as exc:
        log.warning("MQTT connect failed (%s) — running in offline mode", exc)

    # Build drivers
    drivers = _build_drivers(cfg)
    if not drivers:
        log.warning("No drivers enabled — check sensor config")

    active_layers = [layer for layer, _ in drivers]

    # Stop event (shared across all tasks)
    stop_event = asyncio.Event()

    # Signal handlers (SIGTERM / SIGINT)
    loop = asyncio.get_running_loop()

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("Signal %d received — initiating shutdown", signum)
        loop.call_soon_threadsafe(stop_event.set)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Notify systemd we are ready
    _sd_notify("READY=1")

    # Assemble tasks
    tasks: list[asyncio.Task] = []

    for layer, driver in drivers:
        task = asyncio.create_task(
            _run_driver(layer, driver, publisher, stop_event),
            name=f"driver-{layer.value}",
        )
        tasks.append(task)

    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(publisher, cfg, active_layers, stop_event),
        name="heartbeat",
    )
    tasks.append(heartbeat_task)

    # In test mode, run for a short window then stop
    if test_mode:
        log.info("Test mode: running for 10 s then exiting")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass
        stop_event.set()

    # Wait for clean shutdown
    await stop_event.wait()
    _sd_notify("STOPPING=1")
    log.info("Stopping all tasks …")

    for task in tasks:
        task.cancel()

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
            log.error("Task raised during shutdown: %s", r)

    try:
        await asyncio.to_thread(publisher.disconnect)
    except Exception:  # noqa: BLE001
        pass

    log.info("ARTEMIS node %s shut down cleanly", cfg.id)
    return 0


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ARTEMIS sensor node daemon")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to node YAML config file",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run each driver for 10 s then exit (smoke test)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not Path(args.config).exists():
        print(f"Error: config file not found: {args.config}", file=sys.stderr)
        return 1

    try:
        cfg = NodeConfig.from_yaml(args.config)
    except Exception as exc:
        print(f"Error loading config: {exc}", file=sys.stderr)
        return 1

    cfg = apply_node_env_overrides(cfg)
    setup_logging()
    for _w in validate_node_config(cfg):
        log.warning("[config] %s", _w)

    return asyncio.run(_async_main(cfg, args.test_mode))


if __name__ == "__main__":
    raise SystemExit(main())
