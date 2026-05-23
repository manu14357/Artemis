"""
artemis/fusion/swarm_analyzer.py
DBSCAN-based swarm detection.

Given a list of confirmed tracks, clusters them spatially.
Clusters with >= min_samples members are labelled as swarms.
"""

from __future__ import annotations

import numpy as np
from sklearn.cluster import DBSCAN

from artemis.core.types import Track


def analyze_swarms(
    tracks: list[Track],
    eps_m: float = 100.0,
    min_samples: int = 3,
) -> dict[str, int | None]:
    """
    Cluster confirmed tracks and return a mapping of track_id → swarm_id.

    Parameters
    ----------
    tracks : confirmed tracks to cluster
    eps_m  : DBSCAN neighbourhood radius in metres
    min_samples : minimum cluster size to be declared a swarm

    Returns
    -------
    dict mapping track_id to:
      - int swarm_id  (≥0) if the track belongs to a swarm cluster
      - None          if the track is not part of any swarm (noise in DBSCAN terms)
    """
    if len(tracks) < min_samples:
        return {t.track_id: None for t in tracks}

    positions = np.array([[t.state[0], t.state[1], t.state[2]] for t in tracks])

    db = DBSCAN(eps=eps_m, min_samples=min_samples, metric="euclidean")
    labels = db.fit_predict(positions)  # -1 = noise

    result: dict[str, int | None] = {}
    for track, label in zip(tracks, labels):
        result[track.track_id] = int(label) if label >= 0 else None

    return result


def swarm_sizes(swarm_assignment: dict[str, int | None]) -> dict[int, int]:
    """Return a mapping of swarm_id → number of tracks in that swarm."""
    counts: dict[int, int] = {}
    for sid in swarm_assignment.values():
        if sid is not None:
            counts[sid] = counts.get(sid, 0) + 1
    return counts
