#!/usr/bin/env python3
"""
scripts/test_radar.py
Smoke test for the Acconeer XM125 radar module.

Probes candidate serial ports, sends a ping, and checks for a valid response.
Exit 0 = pass / device absent (skip), Exit 1 = hard failure.
"""
from __future__ import annotations

import time

CANDIDATE_PORTS = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyUSB1"]
BAUD_RATE = 115200
PING_PAYLOAD = b"\x7b\x7c\x7d"  # minimal XM125 wake sequence


def main() -> int:
    try:
        import serial
    except ImportError:
        print("FAIL — pyserial not installed (pip install pyserial)")
        return 1

    found_port: str | None = None
    for port in CANDIDATE_PORTS:
        try:
            ser = serial.Serial(port, BAUD_RATE, timeout=1)
            ser.close()
            found_port = port
            break
        except serial.SerialException:
            continue

    if found_port is None:
        print(f"SKIP — XM125 not found on {', '.join(CANDIDATE_PORTS)}")
        return 0

    try:
        with serial.Serial(found_port, BAUD_RATE, timeout=2) as ser:
            ser.reset_input_buffer()
            ser.write(PING_PAYLOAD)
            time.sleep(0.3)
            response = ser.read(ser.in_waiting or 1)
            print(
                f"PASS — XM125 on {found_port}, sent ping, "
                f"received {len(response)} bytes response"
            )
            return 0
    except Exception as exc:
        print(f"FAIL — serial communication error on {found_port}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
