#!/usr/bin/env python3
"""ARTEMIS node entrypoint (scaffold)."""

import argparse
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ARTEMIS node daemon")
    parser.add_argument("--config", required=True, help="Path to node YAML config")
    parser.add_argument("--test-mode", action="store_true", help="Run short self-test loop")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = "test" if args.test_mode else "normal"
    print(f"[node] starting in {mode} mode with config={args.config}")

    if args.test_mode:
        print("[node] running quick self-test...")
        time.sleep(1)
        print("[node] self-test completed")
        return 0

    print("[node] daemon loop started (placeholder)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[node] shutdown requested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
