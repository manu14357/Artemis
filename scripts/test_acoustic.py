#!/usr/bin/env python3
"""
scripts/test_acoustic.py
Smoke test for the ReSpeaker 4-mic USB array.

Requires: ReSpeaker device connected via USB and seeed-voicecard driver installed.
Exit 0 = pass / device absent (skip), Exit 1 = hard failure.
"""
from __future__ import annotations


# Number of 16-kHz mono samples to read
BLOCK_SAMPLES = 1024


def main() -> int:
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError as exc:
        print(f"FAIL — missing dependency: {exc}")
        return 1

    # Find a suitable input device
    devices = sd.query_devices()
    input_devs = [
        d for d in devices if d["max_input_channels"] >= 1
    ]
    if not input_devs:
        print("SKIP — no audio input devices found")
        return 0

    # Prefer a ReSpeaker device; fall back to first available input
    device_idx = None
    for dev in input_devs:
        if "respeaker" in dev["name"].lower() or "seeed" in dev["name"].lower():
            device_idx = devices.index(dev)
            break
    if device_idx is None:
        device_idx = next(
            i for i, d in enumerate(devices) if d["max_input_channels"] >= 1
        )

    dev_name = devices[device_idx]["name"]
    n_channels = min(4, devices[device_idx]["max_input_channels"])

    try:
        audio = sd.rec(
            BLOCK_SAMPLES,
            samplerate=16_000,
            channels=n_channels,
            dtype="float32",
            device=device_idx,
            blocking=True,
        )
    except Exception as exc:
        print(f"FAIL — could not record from '{dev_name}': {exc}")
        return 1

    rms = float(np.sqrt(np.mean(audio ** 2)))
    print(
        f"PASS — device='{dev_name}', channels={n_channels}, "
        f"samples={BLOCK_SAMPLES}, RMS={rms:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
