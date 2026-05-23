"""
artemis/fusion/correlator.py
Hungarian-algorithm detection-to-track assignment.

Given a set of detections (each with an estimated Cartesian position) and
a set of active tracks, computes the optimal 1-to-1 assignment that minimises
total Euclidean distance, subject to a maximum allowable gate distance.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment


def assign(
    detection_positions: list[np.ndarray],
    track_positions: list[np.ndarray],
    max_distance_m: float = 50.0,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """
    Optimal assignment of detections to tracks using the Hungarian algorithm.

    Parameters
    ----------
    detection_positions : list of np.ndarray shape (3,)
        Cartesian [x, y, z] of each new detection (metres).
    track_positions : list of np.ndarray shape (3,)
        Predicted Cartesian [x, y, z] of each existing track.
    max_distance_m : float
        Detections and tracks further apart than this are never matched.

    Returns
    -------
    matches : list[(det_idx, trk_idx)]
        Assigned pairs.
    unmatched_detections : list[int]
        Detection indices with no track assignment.
    unmatched_tracks : list[int]
        Track indices with no detection assignment.
    """
    n_det = len(detection_positions)
    n_trk = len(track_positions)

    if n_det == 0:
        return [], [], list(range(n_trk))
    if n_trk == 0:
        return [], list(range(n_det)), []

    # Build cost matrix (Euclidean distance)
    cost = np.full((n_det, n_trk), fill_value=1e9)
    for i, dp in enumerate(detection_positions):
        for j, tp in enumerate(track_positions):
            dist = float(np.linalg.norm(dp - tp))
            if dist <= max_distance_m:
                cost[i, j] = dist

    # Solve assignment
    row_ind, col_ind = linear_sum_assignment(cost)

    matches: list[tuple[int, int]] = []
    matched_det: set[int] = set()
    matched_trk: set[int] = set()

    for ri, ci in zip(row_ind, col_ind):
        if cost[ri, ci] <= max_distance_m:
            matches.append((int(ri), int(ci)))
            matched_det.add(ri)
            matched_trk.add(ci)

    unmatched_detections = [i for i in range(n_det) if i not in matched_det]
    unmatched_tracks     = [j for j in range(n_trk) if j not in matched_trk]

    return matches, unmatched_detections, unmatched_tracks
