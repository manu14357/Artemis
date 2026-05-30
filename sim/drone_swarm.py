#!/usr/bin/env python3
"""
sim/drone_swarm.py
ARTEMIS drone swarm simulator.

Simulates N drones flying a configurable scenario (converging, line, grid, or
waypoint-following), and publishes realistic multi-sensor detections to an
MQTT broker via the MQTTPublisher.

Usage:
    python sim/drone_swarm.py \\
        --scenario sim/scenarios/10_drone_swarm.yaml \\
        --node-config node/config/node_default.yaml \\
        --broker 127.0.0.1 --port 1883

The simulator acts as one (or more) virtual sensor nodes.  By default it
presents itself as "sim-node-01" located at the hub origin.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import pathlib
import random
import time
from dataclasses import dataclass, field

import yaml

from artemis.core.logging import get_logger, setup_logging
from artemis.mesh.publisher import MQTTPublisher
from sim.acoustic_emulator import make_acoustic_emulator
from sim.optical_emulator import make_optical_emulator
from sim.radar_emulator import make_radar_emulator
from sim.rf_emulator import make_rf_emulator

log = get_logger("sim.drone_swarm")

_EARTH_R_M = 6_371_000.0


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def latlon_to_xyz(
    lat: float, lon: float, alt: float, ref_lat: float, ref_lon: float
) -> tuple[float, float, float]:
    """Convert GPS to local Cartesian (metres East, North, Up)."""
    dlat = math.radians(lat - ref_lat)
    dlon = math.radians(lon - ref_lon)
    x = dlon * _EARTH_R_M * math.cos(math.radians(ref_lat))
    y = dlat * _EARTH_R_M
    z = alt
    return x, y, z


def distance_and_bearing(
    node_lat: float,
    node_lon: float,
    drone_lat: float,
    drone_lon: float,
    drone_alt: float,
) -> tuple[float, float, float]:
    """
    Returns (slant_range_m, azimuth_deg, elevation_deg) from node to drone.
    azimuth_deg is degrees from North (clockwise).
    """
    dx, dy, dz = latlon_to_xyz(drone_lat, drone_lon, drone_alt, node_lat, node_lon)
    horizontal = math.hypot(dx, dy)
    slant = math.hypot(horizontal, dz)
    azimuth = math.degrees(math.atan2(dx, dy)) % 360.0  # E=90, N=0
    elevation = math.degrees(math.atan2(dz, horizontal))
    return slant, azimuth, elevation


# ---------------------------------------------------------------------------
# Drone state
# ---------------------------------------------------------------------------


@dataclass
class Drone:
    drone_id: str
    model: str
    lat: float
    lon: float
    alt_m: float
    vx_mps: float = 0.0  # East m/s
    vy_mps: float = 0.0  # North m/s
    vz_mps: float = 0.0  # Up m/s
    waypoints: list[dict] = field(default_factory=list)
    _wp_idx: int = field(default=0, repr=False)

    # Per-sensor emulators
    rf_emulator: object = field(default=None, repr=False)
    acoustic_emulator: object = field(default=None, repr=False)
    radar_emulator: object = field(default=None, repr=False)
    optical_emulator: object = field(default=None, repr=False)

    def step(self, dt: float) -> None:
        """Update position based on current velocity and waypoint target."""
        if self.waypoints and self._wp_idx < len(self.waypoints):
            wp = self.waypoints[self._wp_idx]
            tx, ty, tz = latlon_to_xyz(
                wp["lat"],
                wp["lon"],
                wp.get("alt_m", self.alt_m),
                self.lat,
                self.lon,
            )
            # tx, ty, tz are already in local frame relative to (self.lat, self.lon)
            dist = math.hypot(tx, ty, tz)

            speed = wp.get("speed_mps", 10.0)
            if dist < speed * dt:
                # Arrived at waypoint
                self.lat = wp["lat"]
                self.lon = wp["lon"]
                self.alt_m = wp.get("alt_m", self.alt_m)
                self._wp_idx += 1
                # Stop at final waypoint — prevents overshoot past the sensor
                if self._wp_idx >= len(self.waypoints):
                    self.vx_mps = 0.0
                    self.vy_mps = 0.0
                    self.vz_mps = 0.0
            else:
                scale = speed / dist
                self.vx_mps = tx * scale
                self.vy_mps = ty * scale
                self.vz_mps = tz * scale

        # Apply velocity → update lat/lon/alt
        dlat = self.vy_mps * dt / _EARTH_R_M
        dlon = self.vx_mps * dt / (_EARTH_R_M * math.cos(math.radians(self.lat)))
        self.lat += math.degrees(dlat)
        self.lon += math.degrees(dlon)
        self.alt_m += self.vz_mps * dt

    @property
    def speed_mps(self) -> float:
        return math.hypot(self.vx_mps, self.vy_mps, self.vz_mps)


# ---------------------------------------------------------------------------
# Scenario loader
# ---------------------------------------------------------------------------


def load_scenario(path: pathlib.Path) -> list[Drone]:
    """Parse a scenario YAML and return a list of Drone objects."""
    with path.open("r", encoding="utf-8") as f:
        scenario = yaml.safe_load(f)

    drones: list[Drone] = []
    swarm_cfg = scenario.get("swarm", {})
    center = swarm_cfg.get("center", {})
    center_lat = center.get("lat", 17.385)
    center_lon = center.get("lon", 78.487)
    center_alt = center.get("alt_m", 100)
    spread_m = swarm_cfg.get("spread_m", 200)
    formation = swarm_cfg.get("formation", "random")
    default_speed = swarm_cfg.get("speed_mps", 10.0)

    for i, entry in enumerate(scenario.get("drones", [])):
        drone_id = entry.get("id", f"drone-{i:03d}")
        model = entry.get("model", "unknown")
        freq = int(entry.get("rf_freq", 2437000000))

        # Starting position
        start = entry.get("start", {})
        if start:
            lat = start.get("lat", center_lat)
            lon = start.get("lon", center_lon)
            alt = start.get("alt_m", center_alt)
        else:
            # Spread around swarm center
            angle = (2 * math.pi * i) / max(len(scenario["drones"]), 1)
            fuzz = random.uniform(0.5, 1.0)
            dlat = math.cos(angle) * spread_m * fuzz / _EARTH_R_M
            dlon = (
                math.sin(angle)
                * spread_m
                * fuzz
                / (_EARTH_R_M * math.cos(math.radians(center_lat)))
            )
            lat = center_lat + math.degrees(dlat)
            lon = center_lon + math.degrees(dlon)
            alt = center_alt

        # Waypoints — converging formation: each drone targets a unique
        # loiter point 80 m from center in its own radial direction.
        # This keeps all 10 drones spatially separated so the track manager
        # maintains 10 individual tracks instead of collapsing them to 1.
        waypoints = entry.get("waypoints", [])
        if not waypoints and formation == "converging":
            loiter_r_m = 80.0  # metres from center; keeps drones >50 m apart
            loiter_dlat = math.cos(angle) * loiter_r_m / _EARTH_R_M
            loiter_dlon = (
                math.sin(angle)
                * loiter_r_m
                / (_EARTH_R_M * math.cos(math.radians(center_lat)))
            )
            waypoints = [
                {
                    "lat": center_lat + math.degrees(loiter_dlat),
                    "lon": center_lon + math.degrees(loiter_dlon),
                    "alt_m": center_alt,
                    "speed_mps": default_speed,
                }
            ]

        # Initial velocity (point toward swarm center)
        dlat_c = math.radians(center_lat - lat)
        dlon_c = math.radians(center_lon - lon)
        dx_c = dlon_c * _EARTH_R_M * math.cos(math.radians(lat))
        dy_c = dlat_c * _EARTH_R_M
        dist_c = math.hypot(dx_c, dy_c)
        if dist_c > 0 and formation == "converging":
            vx = dx_c / dist_c * default_speed
            vy = dy_c / dist_c * default_speed
        else:
            vx = vy = 0.0

        drone = Drone(
            drone_id=drone_id,
            model=model,
            lat=lat,
            lon=lon,
            alt_m=alt,
            vx_mps=vx,
            vy_mps=vy,
            waypoints=waypoints,
            rf_emulator=make_rf_emulator(drone_id, model, freq),
            acoustic_emulator=make_acoustic_emulator(drone_id, model),
            radar_emulator=make_radar_emulator(drone_id, model),
            optical_emulator=make_optical_emulator(drone_id, model),
        )
        drones.append(drone)
        log.debug(
            "loaded drone %s model=%s at (%.4f, %.4f, %.1fm)",
            drone_id,
            model,
            lat,
            lon,
            alt,
        )

    return drones


# ---------------------------------------------------------------------------
# Simulation loop
# ---------------------------------------------------------------------------


async def run_simulation(
    drones: list[Drone],
    publisher: MQTTPublisher,
    node_lat: float,
    node_lon: float,
    node_alt: float,
    node_id: str = "sim-node-01",
    tick_hz: float = 50.0,
    duration_s: float = 300.0,
) -> None:
    """Main async simulation loop."""
    tick_s = 1.0 / tick_hz
    end_time = time.monotonic() + duration_s
    tick_count = 0

    log.info(
        "simulation started drones=%d tick_hz=%.0f duration_s=%.0f node_id=%s",
        len(drones),
        tick_hz,
        duration_s,
        node_id,
    )

    while time.monotonic() < end_time:
        t0 = time.monotonic()

        for drone in drones:
            drone.step(tick_s)

            slant, azimuth, elevation = distance_and_bearing(
                node_lat,
                node_lon,
                drone.lat,
                drone.lon,
                drone.alt_m,
            )

            # Camera azimuth from boresight (assume boresight = North = 0°)
            cam_az = azimuth - 0.0  # adjust if camera is rotated

            # --- RF ---
            rf_det = drone.rf_emulator.sample(
                distance_m=slant,
                bearing_deg=azimuth,
            )
            if rf_det:
                rf_det.source = node_id
                publisher.publish_rf(rf_det)

            # --- Acoustic ---
            ac_det = drone.acoustic_emulator.sample(
                distance_m=slant,
                bearing_deg=azimuth,
            )
            if ac_det:
                ac_det.source = node_id
                publisher.publish_acoustic(ac_det)

            # --- Radar ---
            rd_det = drone.radar_emulator.sample(
                distance_m=slant,
                bearing_deg=azimuth,
                velocity_mps=drone.speed_mps,
            )
            if rd_det:
                rd_det.source = node_id
                publisher.publish_radar(rd_det)

            # --- Optical ---
            opt_det = drone.optical_emulator.sample(
                distance_m=slant,
                azimuth_deg=cam_az,
                elevation_deg=elevation,
            )
            if opt_det:
                opt_det.source = node_id
                publisher.publish_optical(opt_det)

        tick_count += 1
        if tick_count % 500 == 0:
            log.info("tick=%d  active_drones=%d", tick_count, len(drones))

        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(0.0, tick_s - elapsed))

    log.info("simulation complete  ticks=%d", tick_count)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARTEMIS drone swarm simulator")
    parser.add_argument("--scenario", required=True, help="Path to scenario YAML")
    parser.add_argument(
        "--node-config", default=None, help="Path to node config YAML (optional)"
    )
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--node-id", default="sim-node-01")
    parser.add_argument("--node-lat", type=float, default=17.385)
    parser.add_argument("--node-lon", type=float, default=78.487)
    parser.add_argument("--node-alt", type=float, default=100.0)
    parser.add_argument(
        "--duration", type=float, default=300.0, help="Simulation duration (s)"
    )
    parser.add_argument(
        "--tick-hz", type=float, default=50.0, help="Physics tick rate (Hz)"
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


async def _main_async() -> None:
    args = parse_args()
    setup_logging(level=args.log_level)

    # Override node position from config if provided
    node_lat, node_lon, node_alt = args.node_lat, args.node_lon, args.node_alt
    if args.node_config:
        from artemis.core.config import NodeConfig

        cfg = NodeConfig.from_yaml(args.node_config)
        node_lat = cfg.location.lat
        node_lon = cfg.location.lon
        node_alt = cfg.location.alt_m

    scenario_path = pathlib.Path(args.scenario)
    drones = load_scenario(scenario_path)

    publisher = MQTTPublisher(
        broker=args.broker,
        port=args.port,
        node_id=args.node_id,
    )
    publisher.connect()

    # Wait for broker connection
    for _ in range(30):
        if publisher.connected:
            break
        await asyncio.sleep(0.1)
    else:
        log.error("could not connect to broker %s:%d", args.broker, args.port)
        return

    try:
        await run_simulation(
            drones=drones,
            publisher=publisher,
            node_lat=node_lat,
            node_lon=node_lon,
            node_alt=node_alt,
            node_id=args.node_id,
            tick_hz=args.tick_hz,
            duration_s=args.duration,
        )
    finally:
        publisher.disconnect()


def main() -> int:
    asyncio.run(_main_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
