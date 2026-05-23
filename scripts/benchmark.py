#!/usr/bin/env python3
"""
ARTEMIS pipeline benchmark.

Measures end-to-end latency across every in-process stage:
  1. Triangulation        — bearing → estimated position (per detection pair)
  2. Threat scoring       — scored risk for N tracks
  3. Command routing      — tier decisions + dedup
  4. Full pipeline cycle  — all stages sequentially

Run:
  python scripts/benchmark.py [--drones N] [--runs R] [--json]

Defaults: 100 drones, 50 warm-up + 100 timed runs each.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Lazy imports (avoids failing if hardware deps absent)
# ---------------------------------------------------------------------------
try:
    from artemis.cognition.agents.command_router import CommandRouter
    from artemis.cognition.agents.threat_scorer import ThreatScorer
    from artemis.core.types import SensorLayer, Track, TrackStatus
    from artemis.mesh.triangulator import triangulate
except ImportError as exc:
    print(f"ERROR: Cannot import ARTEMIS modules: {exc}", file=sys.stderr)
    print("Run: pip install -e .", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Swarm builder
# ---------------------------------------------------------------------------

def _make_tracks(n: int) -> list[Track]:
    tracks = []
    for i in range(n):
        t = Track(track_id=str(uuid.uuid4())[:8], status=TrackStatus.CONFIRMED)
        x = (i % 100) * 20.0 - 1000.0
        y = (i // 100) * 20.0 - 1000.0
        vx = (i % 10) * 3.0 - 15.0
        vy = (i % 7) * 3.0 - 10.0
        t.state = [x, y, 30.0, vx, vy, 0.0]
        t.sensor_layers = {SensorLayer.RF}
        tracks.append(t)
    return tracks


def _make_node_bearings(n_nodes: int = 4) -> dict[str, tuple[float, float, float]]:
    """Generate synthetic bearing observations pointing toward a drone at (200, 150) m."""
    _MLAT = 111_319.0
    _MLON = 111_319.0 * math.cos(math.radians(51.5))
    base_positions = [
        ("node-01", 51.5000, -0.1000),
        ("node-02", 51.5010, -0.1000),
        ("node-03", 51.5000, -0.0990),
        ("node-04", 51.5010, -0.0990),
    ][:n_nodes]
    drone_x, drone_y = 200.0, 150.0
    out = {}
    for nid, lat, lon in base_positions:
        nx = lon * _MLON
        ny = lat * _MLAT
        bearing = (math.degrees(math.atan2(drone_x - nx, drone_y - ny)) + 360) % 360
        out[nid] = (lat, lon, bearing)
    return out


# ---------------------------------------------------------------------------
# Bench runner
# ---------------------------------------------------------------------------

class BenchResult:
    def __init__(self, label: str, n_items: int, latencies_ms: list[float]) -> None:
        self.label = label
        self.n_items = n_items
        self.latencies = sorted(latencies_ms)
        self.mean_ms = statistics.mean(latencies_ms)
        self.p50_ms = self.latencies[len(self.latencies) // 2]
        self.p95_ms = self.latencies[int(0.95 * len(self.latencies))]
        self.p99_ms = self.latencies[int(0.99 * len(self.latencies))]
        self.min_ms = self.latencies[0]
        self.max_ms = self.latencies[-1]

    def throughput(self) -> float:
        """Items processed per second (at mean latency)."""
        if self.mean_ms == 0:
            return float("inf")
        return self.n_items / (self.mean_ms / 1000)

    def print(self) -> None:
        print(
            f"  {self.label:<35s}  "
            f"mean={self.mean_ms:6.2f}ms  "
            f"p50={self.p50_ms:6.2f}ms  "
            f"p95={self.p95_ms:6.2f}ms  "
            f"p99={self.p99_ms:6.2f}ms  "
            f"tput={self.throughput():,.0f}/s"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "n_items": self.n_items,
            "mean_ms": self.mean_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "throughput_per_sec": self.throughput(),
        }


def _measure(fn, n_warmup: int, n_runs: int) -> list[float]:
    for _ in range(n_warmup):
        fn()
    latencies = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        fn()
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


# ---------------------------------------------------------------------------
# Individual stage benchmarks
# ---------------------------------------------------------------------------

def bench_triangulation(n_nodes: int, n_warmup: int, n_runs: int) -> BenchResult:
    bearings = _make_node_bearings(n_nodes)

    def fn() -> None:
        triangulate(bearings)

    latencies = _measure(fn, n_warmup, n_runs)
    return BenchResult(f"triangulate({n_nodes} nodes)", 1, latencies)


def bench_threat_scoring(n_drones: int, n_warmup: int, n_runs: int) -> BenchResult:
    tracks = _make_tracks(n_drones)
    scorer = ThreatScorer()

    def fn() -> None:
        scorer.score(tracks)

    latencies = _measure(fn, n_warmup, n_runs)
    return BenchResult(f"ThreatScorer ({n_drones} tracks)", n_drones, latencies)


def bench_command_routing(n_drones: int, n_warmup: int, n_runs: int) -> BenchResult:
    tracks = _make_tracks(n_drones)
    scores = ThreatScorer().score(tracks)

    def fn() -> None:
        # Fresh router each call to avoid dedup state masking timing
        CommandRouter().route(tracks, scores)

    latencies = _measure(fn, n_warmup, n_runs)
    return BenchResult(f"CommandRouter ({n_drones} tracks)", n_drones, latencies)


def bench_full_pipeline(n_drones: int, n_warmup: int, n_runs: int) -> BenchResult:
    """Score → route (back-to-back, shared scorer state)."""
    tracks = _make_tracks(n_drones)
    scorer = ThreatScorer()

    def fn() -> None:
        scores = scorer.score(tracks)
        CommandRouter().route(tracks, scores)

    latencies = _measure(fn, n_warmup, n_runs)
    return BenchResult(f"Full pipeline ({n_drones} drones)", n_drones, latencies)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ARTEMIS pipeline benchmark")
    parser.add_argument("--drones", type=int, default=100,
                        help="Number of simulated drones (default: 100)")
    parser.add_argument("--runs", type=int, default=100,
                        help="Number of timed iterations (default: 100)")
    parser.add_argument("--warmup", type=int, default=20,
                        help="Warm-up iterations before timing (default: 20)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON instead of human-readable table")
    args = parser.parse_args(argv)

    n_drones = args.drones
    n_runs = args.runs
    n_warmup = args.warmup

    if not args.json:
        print("=" * 80)
        print(f"  ARTEMIS Pipeline Benchmark — {n_drones} drones, {n_runs} timed runs")
        print("=" * 80)

    results = [
        bench_triangulation(4, n_warmup, n_runs),
        bench_threat_scoring(n_drones, n_warmup, n_runs),
        bench_command_routing(n_drones, n_warmup, n_runs),
        bench_full_pipeline(n_drones, n_warmup, n_runs),
    ]

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        for r in results:
            r.print()
        print("=" * 80)

        # Simple pass/fail budget check (100 ms for N drones)
        budget_ms = 100.0
        fails = [r for r in results if r.mean_ms > budget_ms and r.n_items > 1]
        if fails:
            print(f"\nWARNING: {len(fails)} stage(s) exceed {budget_ms} ms budget:")
            for r in fails:
                print(f"  {r.label}: {r.mean_ms:.2f} ms")
            return 1
        else:
            print(f"\nAll stages within {budget_ms} ms budget.")
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
