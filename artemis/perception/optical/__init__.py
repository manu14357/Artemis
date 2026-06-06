"""
artemis/perception/optical — Optical perception package.

Exports:
- OpticalDetector: Classical MOG2 + Lucas-Kanade detector
- YOLODetector: YOLOv8-based ML detector (NCNN/ONNX/Ultralytics backends)
"""

from artemis.perception.optical.detector import OpticalDetector

try:
    from artemis.perception.optical.yolo_detector import YOLODetector
    __all__ = ["OpticalDetector", "YOLODetector"]
except ImportError:
    __all__ = ["OpticalDetector"]