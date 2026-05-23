#!/usr/bin/env python3
"""
scripts/test_optical.py
Smoke test for the optical (camera) sensor.

Tries picamera2 first (Raspberry Pi with libcamera), then falls back to
OpenCV VideoCapture (any USB webcam).
Exit 0 = pass / device absent (skip), Exit 1 = hard failure.
"""
from __future__ import annotations


def _test_picamera() -> tuple[bool, str]:
    """Return (success, message). Raises ImportError if picamera2 absent."""
    from picamera2 import Picamera2  # noqa: PLC0415

    cam = Picamera2()
    config = cam.create_still_configuration(
        main={"size": (640, 480), "format": "RGB888"}
    )
    cam.configure(config)
    cam.start()
    try:
        frame = cam.capture_array()
        if frame is None or frame.size == 0:
            return False, "picamera2 returned empty frame"
        h, w = frame.shape[:2]
        return True, f"picamera2: {w}x{h} frame captured"
    finally:
        cam.stop()
        cam.close()


def _test_opencv() -> tuple[bool, str]:
    """Return (success, message). Raises ImportError if cv2 absent."""
    import cv2  # noqa: PLC0415

    for idx in range(3):
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            cap.release()
            continue
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            h, w = frame.shape[:2]
            return True, f"cv2.VideoCapture({idx}): {w}x{h} frame captured"
    return False, "no OpenCV-accessible camera found (indices 0-2 tried)"


def main() -> int:
    # Try picamera2 (RPi)
    try:
        ok, msg = _test_picamera()
        if ok:
            print(f"PASS — {msg}")
            return 0
        else:
            print(f"FAIL — {msg}")
            return 1
    except ImportError:
        pass
    except Exception as exc:
        print(f"WARN — picamera2 failed ({exc}), trying OpenCV fallback")

    # Fallback: OpenCV
    try:
        ok, msg = _test_opencv()
        if ok:
            print(f"PASS — {msg}")
            return 0
        else:
            print(f"SKIP — {msg}")
            return 0
    except ImportError:
        print("FAIL — neither picamera2 nor opencv-python is installed")
        return 1
    except Exception as exc:
        print(f"FAIL — OpenCV error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
