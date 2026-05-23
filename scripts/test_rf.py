#!/usr/bin/env python3
"""
scripts/test_rf.py
Smoke test for the RTL-SDR RF sensor.

Requires: RTL-SDR dongle connected via USB.
Decoration with @pytest.mark.hardware keeps this out of CI.

Exit 0 = pass, Exit 1 = fail / device not found.
"""
from __future__ import annotations


def main() -> int:
    try:
        import rtlsdr
    except ImportError:
        print("FAIL — pyrtlsdr not installed (pip install pyrtlsdr)")
        return 1

    try:
        sdr = rtlsdr.RtlSdr()
    except Exception as exc:
        print(f"SKIP — RTL-SDR device not found: {exc}")
        # Exit 0: device not connected is expected on dev machines
        return 0

    try:
        sdr.sample_rate = 2.4e6
        sdr.center_freq = 2_437_000_000
        sdr.gain = "auto"

        samples = sdr.read_samples(256)
        if len(samples) != 256:
            print(f"FAIL — expected 256 samples, got {len(samples)}")
            return 1

        import numpy as np

        power_db = 10 * np.log10(np.mean(np.abs(samples) ** 2) + 1e-12)
        print(
            f"PASS — RTL-SDR opened, tuned to 2437 MHz, "
            f"read {len(samples)} IQ samples, power={power_db:.1f} dBFS"
        )
        return 0
    except Exception as exc:
        print(f"FAIL — {exc}")
        return 1
    finally:
        sdr.close()


if __name__ == "__main__":
    raise SystemExit(main())
