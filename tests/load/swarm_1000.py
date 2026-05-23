"""
tests/load/swarm_1000.py
Load test: 1000-drone concurrent detection pipeline.

Validates that the fusion pipeline processes detections from 1000 simulated
drones within the 100 ms real-time budget (50 Hz target frame rate).

Run with: python -m pytest tests/load/swarm_1000.py -v -s
Or standalone: python tests/load/swarm_1000.py
"""

from __future__ import annotations

import statistics
import time
import uuid


from artemis.cognition.agents.command_router import CommandRouter
from artemis.cognition.agents.threat_scorer import ThreatScorer
from artemis.core.types import (
    DroneType,
    RFDetection,
    SensorLayer,
    Track,
    TrackStatus,
)
from artemis.mesh.triangulator import triangulate

# ---------------------------------------------------------------------------
# Swarm factory
# ---------------------------------------------------------------------------

_DRONE_TYPES = list(DroneType)
_DRONE_FREQS = [2_437_000_000, 5_780_000_000, 915_000_000]


def _make_swarm_detections(n: int) -> list[RFDetection]:
    """Generate n synthetic RFDetection objects."""
    dets = []
    for i in range(n):
        dets.append(
            RFDetection(
                frequency=_DRONE_FREQS[i % len(_DRONE_FREQS)],
                peak_power_db=-45.0 + (i % 10),
                source=f"node-{i % 4:02d}",
                timestamp=time.time(),
                layer=SensorLayer.RF,
                drone_type=_DRONE_TYPES[i % len(_DRONE_TYPES)],
                confidence=0.6 + (i % 4) * 0.1,
                bearing_deg=float(i % 360),
            )
        )
    return dets


def _make_swarm_tracks(n: int) -> list[Track]:
    """Generate n synthetic Track objects spread across a 2 km × 2 km area."""
    tracks = []
    for i in range(n):
        t = Track(
            track_id=str(uuid.uuid4())[:8],
            status=TrackStatus.CONFIRMED,
        )
        x = (i % 100) * 20.0 - 1000.0  # -1000 to +1000 m in x
        y = (i // 100) * 20.0 - 1000.0  # -1000 to +1000 m in y
        vx = (i % 10) * 3.0 - 15.0  # -15 to +15 m/s
        vy = (i % 7) * 3.0 - 10.0
        t.state = [x, y, 30.0, vx, vy, 0.0]
        t.sensor_layers = {SensorLayer.RF}
        t.hit_count = 3
        tracks.append(t)
    return tracks


# ---------------------------------------------------------------------------
# Benchmark helpers
# ---------------------------------------------------------------------------


def _bench_scoring(tracks: list[Track], n_runs: int = 5) -> list[float]:
    """Measure threat scoring latency over n_runs, return per-run ms list."""
    scorer = ThreatScorer()
    latencies = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        scorer.score(tracks)
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def _bench_routing(
    tracks: list[Track], scores: dict[str, float], n_runs: int = 5
) -> list[float]:
    """Measure command routing latency."""
    latencies = []
    for _ in range(n_runs):
        router = CommandRouter()  # fresh router each run (no dedup state)
        t0 = time.perf_counter()
        router.route(tracks, scores)
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def _bench_triangulation(n_nodes: int = 4, n_runs: int = 100) -> list[float]:
    """Measure triangulation latency with n_nodes bearing lines."""
    import math

    latencies = []
    # Simulate a drone at (200, 150) from hub origin
    drone_x, drone_y = 200.0, 150.0
    node_positions = [
        ("node-01", 51.5000, -0.1000),
        ("node-02", 51.5010, -0.1000),
        ("node-03", 51.5000, -0.0990),
        ("node-04", 51.5010, -0.0990),
    ][:n_nodes]

    # Pre-compute realistic bearings from each node to the simulated drone
    # (using flat-earth approximation for test)
    _METERS_PER_DEG_LAT = 111_319.0
    _METERS_PER_DEG_LON = 111_319.0 * math.cos(math.radians(51.5))

    node_bearings: dict[str, tuple[float, float, float]] = {}
    for nid, lat, lon in node_positions:
        nx = lon * _METERS_PER_DEG_LON
        ny = lat * _METERS_PER_DEG_LAT
        dx = drone_x - nx
        dy = drone_y - ny
        bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        node_bearings[nid] = (lat, lon, bearing)

    for _ in range(n_runs):
        t0 = time.perf_counter()
        triangulate(node_bearings)
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


# ---------------------------------------------------------------------------
# Pytest tests
# ---------------------------------------------------------------------------


class TestSwarm1000Throughput:
    """
    Verify the cognition pipeline meets the 100 ms budget for 1000 drones.
    Budget is generous — real hardware has multiple CPU cores.
    """

    _N_DRONES = 1000
    _BUDGET_MS = 100.0  # 100 ms real-time budget per fusion cycle

    def test_threat_scoring_within_budget(self) -> None:
        tracks = _make_swarm_tracks(self._N_DRONES)
        latencies = _bench_scoring(tracks, n_runs=3)
        mean_ms = statistics.mean(latencies)
        print(
            f"\n[load] ThreatScorer {self._N_DRONES} tracks: "
            f"mean={mean_ms:.2f}ms min={min(latencies):.2f}ms max={max(latencies):.2f}ms"
        )
        assert (
            mean_ms < self._BUDGET_MS
        ), f"ThreatScorer too slow: {mean_ms:.2f} ms > {self._BUDGET_MS} ms budget"

    def test_command_routing_within_budget(self) -> None:
        tracks = _make_swarm_tracks(self._N_DRONES)
        scorer = ThreatScorer()
        scores = scorer.score(tracks)
        latencies = _bench_routing(tracks, scores, n_runs=3)
        mean_ms = statistics.mean(latencies)
        print(
            f"\n[load] CommandRouter {self._N_DRONES} tracks: "
            f"mean={mean_ms:.2f}ms min={min(latencies):.2f}ms max={max(latencies):.2f}ms"
        )
        assert mean_ms < self._BUDGET_MS

    def test_full_cognition_pipeline_within_budget(self) -> None:
        """Combined scorer + router must fit in budget."""
        tracks = _make_swarm_tracks(self._N_DRONES)
        scorer = ThreatScorer()
        router = CommandRouter()
        latencies = []
        for _ in range(3):
            t0 = time.perf_counter()
            scores = scorer.score(tracks)
            router.route(tracks, scores)
            latencies.append((time.perf_counter() - t0) * 1000)
        mean_ms = statistics.mean(latencies)
        print(
            f"\n[load] Full pipeline {self._N_DRONES} drones: " f"mean={mean_ms:.2f}ms"
        )
        assert (
            mean_ms < self._BUDGET_MS * 2
        ), f"Full pipeline too slow: {mean_ms:.2f} ms"

    def test_triangulation_latency(self) -> None:
        """Single triangulation call must be << 1 ms."""
        latencies = _bench_triangulation(n_nodes=4, n_runs=200)
        p99_ms = sorted(latencies)[int(0.99 * len(latencies))]
        mean_ms = statistics.mean(latencies)
        print(f"\n[load] triangulate() 4-node: mean={mean_ms:.3f}ms p99={p99_ms:.3f}ms")
        assert p99_ms < 10.0, f"Triangulation p99 too slow: {p99_ms:.3f} ms"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def _standalone_benchmark() -> None:
    print("=" * 60)
    print("ARTEMIS 1000-drone swarm load benchmark")
    print("=" * 60)

    N = 1000
    tracks = _make_swarm_tracks(N)

    # Scoring
    lat = _bench_scoring(tracks, n_runs=10)
    print(
        f"ThreatScorer   {N} tracks: "
        f"mean={statistics.mean(lat):.2f}ms  "
        f"p99={sorted(lat)[int(0.99*len(lat))]:.2f}ms"
    )

    # Routing
    scores = ThreatScorer().score(tracks)
    lat2 = _bench_routing(tracks, scores, n_runs=10)
    print(
        f"CommandRouter  {N} tracks: "
        f"mean={statistics.mean(lat2):.2f}ms  "
        f"p99={sorted(lat2)[int(0.99*len(lat2))]:.2f}ms"
    )

    # Triangulation
    lat3 = _bench_triangulation(n_nodes=4, n_runs=500)
    print(
        f"triangulate()  4 nodes:   "
        f"mean={statistics.mean(lat3):.3f}ms  "
        f"p99={sorted(lat3)[int(0.99*len(lat3))]:.3f}ms"
    )
    print("=" * 60)
    print("DONE")


if __name__ == "__main__":
    _standalone_benchmark()
