"""
artemis/perception/optical/yolo_detector.py
YOLOv8-based optical drone detector for Raspberry Pi 5.

Provides ML-based drone detection as an upgrade to classical MOG2+optical flow.
Optimized for edge deployment: NCNN, ONNX Runtime, or TensorRT.

Classes: drone, bird, plane, helicopter (configurable)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import AsyncGenerator, Optional

import numpy as np

from artemis.core.logging import get_logger
from artemis.core.types import DroneType, OpticalDetection, SensorLayer
from artemis.perception.base import DriverStatus, PerceptionDriver

log = get_logger("perception.optical.yolo")

# ---------------------------------------------------------------------------
# Optional inference backends
# ---------------------------------------------------------------------------

_HAS_NCNN = False
_HAS_ONNX = False
_HAS_ULTRALYTICS = False

try:
    import ncnn
    _HAS_NCNN = True
except ImportError:
    pass

try:
    import onnxruntime as ort
    _HAS_ONNX = True
except ImportError:
    pass

try:
    from ultralytics import YOLO
    _HAS_ULTRALYTICS = True
except ImportError:
    pass


class DriverUnavailableError(RuntimeError):
    """Raised when no inference backend is available."""


# ---------------------------------------------------------------------------
# Model wrappers for different backends
# ---------------------------------------------------------------------------


class _NCNNModel:
    """NCNN inference wrapper (fastest on ARM CPU)."""

    def __init__(self, param_path: str, bin_path: str, input_size: tuple[int, int]):
        self._net = ncnn.Net()
        self._net.load_param(param_path)
        self._net.load_model(bin_path)
        self._input_size = input_size
        self._mean_vals = [0, 0, 0]
        self._norm_vals = [1/255.0, 1/255.0, 1/255.0]

    def infer(self, frame: np.ndarray) -> list[dict]:
        """Run inference on BGR frame. Returns list of detections."""
        h, w = frame.shape[:2]
        # Letterbox resize
        inp_h, inp_w = self._input_size
        scale = min(inp_w / w, inp_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h))
        # Pad
        padded = np.full((inp_h, inp_w, 3), 114, dtype=np.uint8)
        padded[:new_h, :new_w] = resized

        # Create ncnn Mat
        mat = ncnn.Mat.from_pixels(padded, ncnn.Mat.PixelType.PIXEL_BGR2RGB, inp_w, inp_h)
        mat.substract_mean_normalize(self._mean_vals, self._norm_vals)

        # Inference
        ex = self._net.create_extractor()
        ex.input("in0", mat)
        ret, out = ex.extract("out0")
        if ret != 0:
            return []

        # Parse YOLOv8 output (84, 8400) -> [x, y, w, h, conf, cls...]
        out_np = np.array(out).reshape(-1, 84).T  # (8400, 84)
        return self._postprocess(out_np, scale, (w, h))

    def _postprocess(self, preds: np.ndarray, scale: float, orig_shape: tuple) -> list[dict]:
        """Non-max suppression and coordinate transform."""
        # Simplified postprocess - in practice use ultralytics' ops
        detections = []
        conf_thresh = 0.25
        iou_thresh = 0.45

        for pred in preds:
            conf = pred[4]
            if conf < conf_thresh:
                continue
            cls_scores = pred[5:]
            cls_id = int(np.argmax(cls_scores))
            cls_conf = cls_scores[cls_id]
            if cls_conf < conf_thresh:
                continue

            # Convert center-x, center-y, w, h to x1, y1, x2, y2
            cx, cy, w, h = pred[0], pred[1], pred[2], pred[3]
            x1 = (cx - w/2) / scale
            y1 = (cy - h/2) / scale
            x2 = (cx + w/2) / scale
            y2 = (cy + h/2) / scale

            detections.append({
                "bbox": (float(x1), float(y1), float(x2-x1), float(y2-y1)),
                "confidence": float(conf * cls_conf),
                "class_id": cls_id,
            })

        # NMS (simplified)
        return self._nms(detections, iou_thresh)

    def _nms(self, dets: list[dict], iou_thresh: float) -> list[dict]:
        if not dets:
            return []
        dets = sorted(dets, key=lambda x: x["confidence"], reverse=True)
        keep = []
        while dets:
            best = dets.pop(0)
            keep.append(best)
            dets = [d for d in dets if self._iou(best["bbox"], d["bbox"]) < iou_thresh]
        return keep

    def _iou(self, box1, box2) -> float:
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[0]+box1[2], box2[0]+box2[2])
        y2 = min(box1[1]+box1[3], box2[1]+box2[3])
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2-x1) * (y2-y1)
        area1 = box1[2] * box1[3]
        area2 = box2[2] * box2[3]
        return inter / (area1 + area2 - inter)


class _ONNXModel:
    """ONNX Runtime inference wrapper."""

    def __init__(self, model_path: str, input_size: tuple[int, int]):
        self._session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        self._input_name = self._session.get_inputs()[0].name
        self._input_size = input_size

    def infer(self, frame: np.ndarray) -> list[dict]:
        h, w = frame.shape[:2]
        inp_h, inp_w = self._input_size

        # Preprocess
        scale = min(inp_w / w, inp_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (new_w, new_h))
        padded = np.full((inp_h, inp_w, 3), 114, dtype=np.uint8)
        padded[:new_h, :new_w] = resized

        # Normalize and convert to CHW
        inp = padded.astype(np.float32) / 255.0
        inp = np.transpose(inp, (2, 0, 1))[np.newaxis, ...]

        # Inference
        outputs = self._session.run(None, {self._input_name: inp})
        preds = outputs[0][0].T  # (8400, 84)

        return self._postprocess(preds, scale, (w, h))

    def _postprocess(self, preds: np.ndarray, scale: float, orig_shape: tuple) -> list[dict]:
        # Same as NCNN
        detections = []
        conf_thresh = 0.25
        for pred in preds:
            conf = pred[4]
            if conf < conf_thresh:
                continue
            cls_scores = pred[5:]
            cls_id = int(np.argmax(cls_scores))
            cls_conf = cls_scores[cls_id]
            if cls_conf < conf_thresh:
                continue
            cx, cy, w, h = pred[0], pred[1], pred[2], pred[3]
            x1 = (cx - w/2) / scale
            y1 = (cy - h/2) / scale
            detections.append({
                "bbox": (float(x1), float(y1), float(w/scale), float(h/scale)),
                "confidence": float(conf * cls_conf),
                "class_id": cls_id,
            })
        return self._nms(detections, 0.45)

    def _nms(self, dets: list[dict], iou_thresh: float) -> list[dict]:
        if not dets:
            return []
        dets = sorted(dets, key=lambda x: x["confidence"], reverse=True)
        keep = []
        while dets:
            best = dets.pop(0)
            keep.append(best)
            dets = [d for d in dets if self._iou(best["bbox"], d["bbox"]) < iou_thresh]
        return keep

    def _iou(self, box1, box2) -> float:
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[0]+box1[2], box2[0]+box2[2])
        y2 = min(box1[1]+box1[3], box2[1]+box2[3])
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2-x1) * (y2-y1)
        area1 = box1[2] * box1[3]
        area2 = box2[2] * box2[3]
        return inter / (area1 + area2 - inter)


class _UltralyticsModel:
    """Ultralytics YOLO wrapper (easiest to use, slower)."""

    def __init__(self, model_path: str, input_size: tuple[int, int]):
        self._model = YOLO(model_path)
        self._input_size = input_size

    def infer(self, frame: np.ndarray) -> list[dict]:
        results = self._model(frame, imgsz=self._input_size[0], verbose=False)[0]
        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            detections.append({
                "bbox": (float(x1), float(y1), float(x2-x1), float(y2-y1)),
                "confidence": conf,
                "class_id": cls_id,
            })
        return detections


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


class YOLODetector(PerceptionDriver):
    """
    YOLOv8-based drone detector.

    Supports multiple backends in priority order:
    1. NCNN (fastest on ARM, requires ncnn python bindings)
    2. ONNX Runtime (fast, cross-platform)
    3. Ultralytics (easiest, pure Python)

    Model must be exported to the appropriate format:
    - NCNN: yolo export format=ncnn
    - ONNX: yolo export format=onnx
    - Ultralytics: .pt file directly
    """

    # COCO class IDs we care about (custom model should remap)
    TARGET_CLASSES = {
        0: DroneType.FPV_GENERIC,   # drone (generic)
        # Add more mappings for specific drone types if model supports
    }

    def __init__(
        self,
        node_id: str,
        *,
        model_path: str = "models/yolov8n_drone",
        input_size: tuple[int, int] = (640, 640),
        confidence_threshold: float = 0.4,
        fps: int = 30,
        resolution: tuple[int, int] = (640, 480),
        backend: str = "auto",  # "ncnn", "onnx", "ultralytics", "auto"
        camera_index: int = 0,
    ) -> None:
        super().__init__(node_id)
        self._model_path = Path(model_path)
        self._input_size = input_size
        self._conf_thresh = confidence_threshold
        self._fps = fps
        self._resolution = resolution
        self._backend_pref = backend
        self._camera_index = camera_index
        self._model = None
        self._source = None
        self._focal_px = 554.0  # Same as OpticalDetector

    async def start(self) -> None:
        if not _HAS_CV2:
            raise DriverUnavailableError("opencv-python not installed")

        # Load model with preferred backend
        self._model = await asyncio.to_thread(self._load_model)
        if self._model is None:
            raise DriverUnavailableError(
                f"No inference backend available for {self._model_path}. "
                "Install ncnn, onnxruntime, or ultralytics."
            )

        # Open camera
        self._source = await asyncio.to_thread(self._open_camera)
        self.status = DriverStatus.RUNNING
        log.info(
            "YOLODetector started node=%s model=%s backend=%s",
            self.node_id,
            self._model_path,
            type(self._model).__name__,
        )

    async def stop(self) -> None:
        if self._source:
            try:
                self._source.release()
            except Exception:
                pass
            self._source = None
        self._model = None
        self.status = DriverStatus.STOPPED
        log.info("YOLODetector stopped node=%s", self.node_id)

    async def stream(self) -> AsyncGenerator[OpticalDetection, None]:  # type: ignore[override]
        if not _HAS_CV2:
            raise DriverUnavailableError("opencv-python not installed")

        self.status = DriverStatus.RUNNING

        try:
            while True:
                detections = await asyncio.to_thread(self._process_frame)
                for det in detections:
                    yield det
                # Frame rate control
                await asyncio.sleep(1.0 / self._fps)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.status = DriverStatus.ERROR
            log.error("YOLODetector error node=%s: %s", self.node_id, exc)
            raise
        finally:
            await self.stop()

    def _load_model(self):
        """Load model with best available backend."""
        # Try backends in priority order
        backends = []
        if self._backend_pref == "auto":
            backends = ["ncnn", "onnx", "ultralytics"]
        else:
            backends = [self._backend_pref]

        for backend in backends:
            try:
                if backend == "ncnn" and _HAS_NCNN:
                    param = self._model_path.with_suffix(".param")
                    bin_file = self._model_path.with_suffix(".bin")
                    if param.exists() and bin_file.exists():
                        log.info("Loading NCNN model from %s", self._model_path)
                        return _NCNNModel(str(param), str(bin_file), self._input_size)
                elif backend == "onnx" and _HAS_ONNX:
                    onnx_path = self._model_path.with_suffix(".onnx")
                    if onnx_path.exists():
                        log.info("Loading ONNX model from %s", onnx_path)
                        return _ONNXModel(str(onnx_path), self._input_size)
                elif backend == "ultralytics" and _HAS_ULTRALYTICS:
                    pt_path = self._model_path.with_suffix(".pt")
                    if pt_path.exists():
                        log.info("Loading Ultralytics model from %s", pt_path)
                        return _UltralyticsModel(str(pt_path), self._input_size)
            except Exception as e:
                log.warning("Backend %s failed: %s", backend, e)

        return None

    def _open_camera(self):
        """Open camera using PiCamera2 or cv2.VideoCapture."""
        try:
            from picamera2 import Picamera2
            cam = Picamera2()
            cfg = cam.create_video_configuration(
                main={"size": self._resolution, "format": "RGB888"},
            )
            cam.configure(cfg)
            cam.set_controls({"FrameRate": self._fps})
            cam.start()
            log.debug("Using PiCamera2")
            return _PiCamera2Source(cam)
        except ImportError:
            pass

        # Fallback to cv2
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {self._camera_index}")
        w, h = self._resolution
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        cap.set(cv2.CAP_PROP_FPS, self._fps)
        log.debug("Using cv2.VideoCapture index=%d", self._camera_index)
        return _CV2Source(cap)

    def _process_frame(self) -> list[OpticalDetection]:
        """Grab frame, run YOLO inference, return detections."""
        assert self._source is not None
        assert self._model is not None

        ret, frame = self._source.read()
        if not ret or frame is None:
            return []

        # YOLO expects RGB, but OpenCV gives BGR
        # Ultralytics handles this internally; NCNN/ONNX need RGB
        if isinstance(self._model, _UltralyticsModel):
            rgb_frame = frame
        else:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Run inference
        results = self._model.infer(rgb_frame)

        # Convert to OpticalDetection
        detections = []
        now = time.time()
        for r in results:
            bbox = r["bbox"]  # (x, y, w, h)
            conf = r["confidence"]
            cls_id = r["class_id"]

            if conf < self._conf_thresh:
                continue

            drone_type = self.TARGET_CLASSES.get(cls_id, DroneType.UNKNOWN)
            x, y, w, h = bbox
            area = w * h
            range_m = self._estimate_range(area)

            detections.append(OpticalDetection(
                bbox=(int(x), int(y), int(w), int(h)),
                area=round(area, 1),
                velocity=(0.0, 0.0),  # No tracking in YOLO-only mode
                source=self.node_id,
                timestamp=now,
                layer=SensorLayer.OPTICAL,
                confidence=round(conf, 3),
                drone_type=drone_type,
                range_m=range_m,
            ))

        return detections

    def _estimate_range(self, area_px: float) -> float:
        """Pinhole range estimate from blob area."""
        w_px = max(area_px ** 0.5, 1.0)
        return round(self._focal_px * 0.35 / w_px, 2)


class _PiCamera2Source:
    def __init__(self, cam):
        self._cam = cam

    def read(self):
        try:
            frame = self._cam.capture_array()
            return True, frame
        except Exception:
            return False, None

    def release(self):
        self._cam.stop()


class _CV2Source:
    def __init__(self, cap):
        self._cap = cap

    def read(self):
        ret, frame = self._cap.read()
        return ret, frame if ret else None

    def release(self):
        self._cap.release()