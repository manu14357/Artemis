#!/usr/bin/env python3
"""
scripts/verify_install.py
Post-installation verification for an ARTEMIS edge node.

Checks:
  - Python environment and key package imports
  - Mosquitto MQTT broker connectivity
  - RTL-SDR USB dongle detection
  - Sounddevice / audio input device detection
  - Acconeer XM125 radar serial port
  - Raspberry Pi Camera (picamera2 or OpenCV fallback)
  - Config file presence and basic parse

Exit codes:
  0 — all required checks passed (hardware checks may be SKIP on dev machines)
  1 — one or more required checks failed

Usage:
  python scripts/verify_install.py
  python scripts/verify_install.py --skip-hardware   # skip USB/serial/camera
  python scripts/verify_install.py --config path/to/node_default.yaml
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    WARN = "WARN"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str = ""


# ── ANSI colours ─────────────────────────────────────────────────────────────
_COLOURS = {
    Status.PASS: "\033[0;32m",
    Status.FAIL: "\033[0;31m",
    Status.SKIP: "\033[0;36m",
    Status.WARN: "\033[1;33m",
}
_NC = "\033[0m"


def _fmt(result: CheckResult) -> str:
    colour = _COLOURS.get(result.status, "")
    label = f"[{result.status.value:<4}]"
    detail = f"  {result.detail}" if result.detail else ""
    return f"{colour}{label}{_NC} {result.name}{detail}"


# ── Individual checks ─────────────────────────────────────────────────────────

def check_python() -> CheckResult:
    vi = sys.version_info
    ver = f"{vi.major}.{vi.minor}.{vi.micro}"
    if vi < (3, 11):
        return CheckResult("Python ≥ 3.11", Status.FAIL, f"Found {ver}")
    return CheckResult("Python ≥ 3.11", Status.PASS, ver)


def check_package(pkg: str, import_name: str | None = None) -> CheckResult:
    name = import_name or pkg
    try:
        __import__(name)
        return CheckResult(f"Package: {pkg}", Status.PASS)
    except ImportError as exc:
        return CheckResult(f"Package: {pkg}", Status.FAIL, str(exc))


def check_config(config_path: str) -> CheckResult:
    p = Path(config_path)
    if not p.exists():
        return CheckResult("Config file", Status.FAIL, f"Not found: {p}")
    try:
        import yaml
        with p.open() as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            return CheckResult("Config file", Status.FAIL, "YAML did not parse as dict")
        return CheckResult("Config file", Status.PASS, str(p))
    except Exception as exc:
        return CheckResult("Config file", Status.FAIL, str(exc))


def check_mosquitto(host: str = "127.0.0.1", port: int = 1883) -> CheckResult:
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return CheckResult("Mosquitto MQTT", Status.PASS, f"{host}:{port}")
    except OSError as exc:
        return CheckResult("Mosquitto MQTT", Status.FAIL, str(exc))


def check_rtlsdr(skip_hardware: bool) -> CheckResult:
    if skip_hardware:
        return CheckResult("RTL-SDR dongle", Status.SKIP, "--skip-hardware")
    try:
        import rtlsdr
        sdr = rtlsdr.RtlSdr()
        sdr.close()
        return CheckResult("RTL-SDR dongle", Status.PASS, "opened and closed")
    except Exception as exc:
        if "No supported" in str(exc) or "rtlsdr" in str(exc).lower():
            return CheckResult("RTL-SDR dongle", Status.WARN, "No RTL-SDR device found")
        return CheckResult("RTL-SDR dongle", Status.WARN, str(exc))


def check_audio(skip_hardware: bool) -> CheckResult:
    if skip_hardware:
        return CheckResult("Audio input device", Status.SKIP, "--skip-hardware")
    try:
        import sounddevice as sd
        devices = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        if not devices:
            return CheckResult("Audio input device", Status.WARN, "No input devices found")
        names = ", ".join(d["name"] for d in devices[:3])
        return CheckResult("Audio input device", Status.PASS, names)
    except Exception as exc:
        return CheckResult("Audio input device", Status.WARN, str(exc))


def check_radar_serial(skip_hardware: bool) -> CheckResult:
    if skip_hardware:
        return CheckResult("Radar serial port", Status.SKIP, "--skip-hardware")
    for port in ("/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyUSB1"):
        if os.path.exists(port):
            return CheckResult("Radar serial port", Status.PASS, port)
    return CheckResult("Radar serial port", Status.WARN, "No ttyUSB*/ttyACM* found")


def check_camera(skip_hardware: bool) -> CheckResult:
    if skip_hardware:
        return CheckResult("Camera", Status.SKIP, "--skip-hardware")
    try:
        import picamera2  # noqa: F401
        return CheckResult("Camera", Status.PASS, "picamera2 available")
    except ImportError:
        pass
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        ok = cap.isOpened()
        cap.release()
        if ok:
            return CheckResult("Camera", Status.PASS, "OpenCV VideoCapture(0)")
        return CheckResult("Camera", Status.WARN, "OpenCV found but VideoCapture(0) failed")
    except ImportError:
        return CheckResult("Camera", Status.WARN, "Neither picamera2 nor OpenCV available")


def check_acconeer(skip_hardware: bool) -> CheckResult:
    if skip_hardware:
        return CheckResult("Acconeer exptool", Status.SKIP, "--skip-hardware")
    try:
        import acconeer.exptool  # noqa: F401
        return CheckResult("Acconeer exptool", Status.PASS)
    except ImportError as exc:
        return CheckResult("Acconeer exptool", Status.FAIL, str(exc))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="ARTEMIS node install verifier")
    parser.add_argument("--skip-hardware", action="store_true",
                        help="Skip USB / serial / camera hardware checks")
    parser.add_argument("--config",
                        default="node/config/node_default.yaml",
                        help="Path to node config YAML")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    args = parser.parse_args()

    skip = args.skip_hardware or not os.path.exists("/dev/bus/usb")

    print("\nARTEMIS Node Installation Verification")
    print("=" * 46)

    checks: list[CheckResult] = [
        check_python(),
        check_package("pyyaml", "yaml"),
        check_package("numpy"),
        check_package("fastapi"),
        check_package("paho.mqtt.client", "paho"),
        check_package("sounddevice"),
        check_package("pyrtlsdr", "rtlsdr"),
        check_package("acconeer-exptool", "acconeer"),
        check_package("opencv-python", "cv2"),
        check_config(args.config),
        check_mosquitto(args.mqtt_host, args.mqtt_port),
        check_rtlsdr(skip),
        check_audio(skip),
        check_radar_serial(skip),
        check_camera(skip),
        check_acconeer(skip),
    ]

    for result in checks:
        print(_fmt(result))

    n_pass  = sum(1 for r in checks if r.status == Status.PASS)
    n_fail  = sum(1 for r in checks if r.status == Status.FAIL)
    n_warn  = sum(1 for r in checks if r.status == Status.WARN)
    n_skip  = sum(1 for r in checks if r.status == Status.SKIP)

    print("=" * 46)
    print(f"PASS={n_pass}  WARN={n_warn}  SKIP={n_skip}  FAIL={n_fail}")

    if n_fail > 0:
        print("\n\033[0;31mSome required checks FAILED. See above.\033[0m")
        return 1

    print("\n\033[0;32mAll required checks passed.\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
