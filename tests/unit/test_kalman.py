"""
tests/unit/test_kalman.py
Unit tests for the Extended Kalman Filter tracker (artemis.fusion.kalman).
"""

import numpy as np
import pytest

from artemis.fusion.kalman import EKFTracker


class TestEKFTracker:
    def test_init_sets_position(self):
        ekf = EKFTracker()
        z = [10.0, 20.0, 50.0]
        ekf.init(z)
        pos = ekf.position
        assert pos == pytest.approx(z)

    def test_predict_moves_forward(self):
        ekf = EKFTracker()
        ekf.init([0.0, 0.0, 100.0])
        # Manually set velocity
        ekf.x[3] = 10.0  # vx = 10 m/s
        ekf.predict(dt=1.0)
        # x should have advanced by 10 m
        assert ekf.position[0] == pytest.approx(10.0, abs=0.1)

    def test_update_converges_toward_measurement(self):
        ekf = EKFTracker(measurement_noise_r=1.0)
        ekf.init([0.0, 0.0, 100.0])
        # Push measurement 50 m away
        meas = [50.0, 0.0, 100.0]
        for _ in range(20):
            ekf.predict(dt=0.1)
            ekf.update(meas)
        pos = ekf.position
        # After many updates, position should be closer to measurement
        assert pos[0] > 10.0

    def test_velocity_property(self):
        ekf = EKFTracker()
        ekf.init([5.0, 5.0, 5.0])
        ekf.x[3] = 3.0
        ekf.x[4] = 4.0
        v = ekf.velocity
        assert len(v) == 3
        assert v[0] == pytest.approx(3.0)
        assert v[1] == pytest.approx(4.0)

    def test_covariance_grows_during_coast(self):
        ekf = EKFTracker(process_noise_q=1.0)
        ekf.init([0.0, 0.0, 0.0])
        p_before = float(np.trace(ekf.P))
        for _ in range(5):
            ekf.predict(dt=0.1)
        p_after = float(np.trace(ekf.P))
        assert p_after > p_before
