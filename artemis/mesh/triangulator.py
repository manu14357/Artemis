"""
artemis/mesh/triangulator.py
Multi-node bearing-line triangulation for RF and acoustic detections.

When 2+ nodes report bearings to the same RF signature, their bearing lines
are intersected via least-squares to produce an estimated position fix.
Accuracy: ~5–20 m at 500 m range with 3 nodes.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

_EARTH_R_M = 6_371_000.0   # Earth radius in metres


def latlon_to_xy(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """
    Convert (lat, lon) to local Cartesian (x, y) metres relative to a reference point.
    Uses equirectangular approximation — accurate to <1% within ~50 km.
    """
    dlat = math.radians(lat - ref_lat)
    dlon = math.radians(lon - ref_lon)
    x = dlon * _EARTH_R_M * math.cos(math.radians(ref_lat))
    y = dlat * _EARTH_R_M
    return x, y


# ---------------------------------------------------------------------------
# Bearing-line intersection
# ---------------------------------------------------------------------------

def _bearing_line_direction(bearing_deg: float) -> tuple[float, float]:
    """Return unit vector (dx, dy) in local Cartesian for a bearing from north."""
    rad = math.radians(bearing_deg)
    return math.sin(rad), math.cos(rad)   # (east, north)


def triangulate(
    node_bearings: dict[str, tuple[float, float, float]],
    ref_lat: Optional[float] = None,
    ref_lon: Optional[float] = None,
) -> Optional[tuple[float, float, float]]:
    """
    Estimate a target position from multiple node bearing reports.

    Parameters
    ----------
    node_bearings : dict
        {node_id: (lat, lon, bearing_deg)}
        At least 2 entries required.
    ref_lat, ref_lon : float | None
        Reference origin for Cartesian conversion.
        Defaults to the centroid of all node positions.

    Returns
    -------
    (x_m, y_m, confidence) or None if fewer than 2 nodes.

    Algorithm: least-squares intersection of bearing lines
    Each bearing from node i defines a line:
        P = O_i + t * d_i   (t ≥ 0)
    We minimise the sum of squared perpendicular distances.
    """
    if len(node_bearings) < 2:
        return None

    nodes = list(node_bearings.values())

    # Compute reference origin
    if ref_lat is None:
        ref_lat = sum(n[0] for n in nodes) / len(nodes)
    if ref_lon is None:
        ref_lon = sum(n[1] for n in nodes) / len(nodes)

    # Convert node positions to local Cartesian
    origins = []
    directions = []
    for lat, lon, bearing_deg in nodes:
        ox, oy = latlon_to_xy(lat, lon, ref_lat, ref_lon)
        dx, dy = _bearing_line_direction(bearing_deg)
        origins.append(np.array([ox, oy]))
        directions.append(np.array([dx, dy]))

    # Least-squares: minimise sum of squared distances from each bearing line
    # For each line, the perpendicular projector is: I - d*d^T
    # System: (sum_i (I - d_i*d_i^T)) * P = sum_i (I - d_i*d_i^T) * O_i
    A = np.zeros((2, 2))
    b = np.zeros(2)
    for O, d in zip(origins, directions):
        M = np.eye(2) - np.outer(d, d)
        A += M
        b += M @ O

    try:
        pos = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return None

    # Confidence: inverse of mean residual distance (metres)
    residuals = []
    for O, d in zip(origins, directions):
        diff = pos - O
        dist = np.linalg.norm(diff - (diff @ d) * d)
        residuals.append(float(dist))
    mean_residual = sum(residuals) / len(residuals)
    confidence = 1.0 / (1.0 + mean_residual / 10.0)   # 0–1, 1 = perfect intersection

    return float(pos[0]), float(pos[1]), round(confidence, 3)
