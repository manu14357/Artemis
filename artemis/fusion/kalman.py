"""
artemis/fusion/kalman.py
Extended Kalman Filter tracker.

State vector: [x, y, z, vx, vy, vz]  — local Cartesian metres / metres·s⁻¹
Measurements: [x, y, z]  (range + bearing converted to Cartesian before calling update)

Uses a constant-velocity motion model (linear, so technically a plain KF,
but the class is named EKFTracker for future extensibility with nonlinear
sensor models such as range-bearing measurements).
"""
from __future__ import annotations

import numpy as np


class EKFTracker:
    """
    Kalman filter with 6-D state [x, y, z, vx, vy, vz].

    Parameters
    ----------
    process_noise_q : float
        Scalar multiplier for the process noise covariance.
        Higher → filter trusts dynamics less → tracks fast-manoeuvring targets better.
    measurement_noise_r : float
        Scalar multiplier for the measurement noise covariance.
        Higher → filter trusts sensor less → smoother but slower to respond.
    dt : float
        Default time step in seconds used when predict() is called without an argument.
    """

    DIM_STATE = 6
    DIM_MEAS  = 3

    def __init__(
        self,
        process_noise_q: float = 0.1,
        measurement_noise_r: float = 0.5,
        dt: float = 0.1,
    ) -> None:
        self.dt = dt
        self._q = process_noise_q
        self._r = measurement_noise_r

        # State estimate and covariance
        self.x = np.zeros(self.DIM_STATE)           # [x, y, z, vx, vy, vz]
        self.P = np.eye(self.DIM_STATE) * 100.0     # Large initial uncertainty

        # State transition matrix (constant velocity)
        self.F = self._make_F(dt)

        # Process noise covariance
        self.Q = self._make_Q(dt, process_noise_q)

        # Observation matrix: extract [x, y, z] from state
        self.H = np.zeros((self.DIM_MEAS, self.DIM_STATE))
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0
        self.H[2, 2] = 1.0

        # Measurement noise covariance
        self.R = np.eye(self.DIM_MEAS) * measurement_noise_r

    # ------------------------------------------------------------------
    # Initialise from first measurement
    # ------------------------------------------------------------------

    def init(self, z: np.ndarray) -> None:
        """Initialise state from a 3-D measurement [x, y, z]."""
        self.x[:3] = z
        self.x[3:] = 0.0
        self.P = np.eye(self.DIM_STATE) * 100.0

    # ------------------------------------------------------------------
    # Predict step
    # ------------------------------------------------------------------

    def predict(self, dt: float | None = None) -> np.ndarray:
        """
        Propagate state forward by *dt* seconds.
        Returns the predicted state vector (copy).
        """
        if dt is not None and dt != self.dt:
            self.F = self._make_F(dt)
            self.Q = self._make_Q(dt, self._q)
            self.dt = dt

        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x.copy()

    # ------------------------------------------------------------------
    # Update step
    # ------------------------------------------------------------------

    def update(self, z: np.ndarray) -> np.ndarray:
        """
        Incorporate a 3-D measurement [x, y, z] and return the updated state.
        """
        # Innovation
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        # Regularise S to prevent singular-matrix errors caused by numerical
        # drift of the covariance P (e.g. when observations arrive very fast).
        S += np.eye(self.DIM_MEAS) * 1e-8
        # Kalman gain
        K = self.P @ self.H.T @ np.linalg.inv(S)
        # Update state
        self.x = self.x + K @ y
        I = np.eye(self.DIM_STATE)
        self.P = (I - K @ self.H) @ self.P
        return self.x.copy()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def position(self) -> np.ndarray:
        return self.x[:3].copy()

    @property
    def velocity(self) -> np.ndarray:
        return self.x[3:].copy()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_F(dt: float) -> np.ndarray:
        F = np.eye(6)
        F[0, 3] = dt
        F[1, 4] = dt
        F[2, 5] = dt
        return F

    @staticmethod
    def _make_Q(dt: float, q: float) -> np.ndarray:
        """Discrete Wiener process noise for constant-velocity model."""
        dt2 = dt ** 2
        dt3 = dt ** 3
        dt4 = dt ** 4
        Q = np.array([
            [dt4 / 4, 0,       0,       dt3 / 2, 0,       0      ],
            [0,       dt4 / 4, 0,       0,       dt3 / 2, 0      ],
            [0,       0,       dt4 / 4, 0,       0,       dt3 / 2],
            [dt3 / 2, 0,       0,       dt2,     0,       0      ],
            [0,       dt3 / 2, 0,       0,       dt2,     0      ],
            [0,       0,       dt3 / 2, 0,       0,       dt2    ],
        ]) * q
        return Q
