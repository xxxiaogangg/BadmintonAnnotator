import os
import sys
from pathlib import Path

import cv2
import numpy as np


class YoloPersonDetector:
    """Small optional YOLOv8 ONNX person detector using OpenCV DNN."""

    def __init__(self, model_path=None, confidence_threshold=0.25, iou_threshold=0.45):
        self.model_path = Path(model_path) if model_path else self.find_default_model_path()
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.net = None
        self.disabled = False
        self.last_error = None
        self.input_size = 640

    @staticmethod
    def find_default_model_path():
        env_path = os.environ.get("BADMINTON_YOLO_MODEL")
        if env_path:
            return Path(env_path)

        project_root = Path(__file__).resolve().parents[1]
        bundle_root = Path(getattr(sys, "_MEIPASS", project_root))
        executable_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else project_root
        candidates = [
            bundle_root / "ai" / "models" / "yolov8n.onnx",
            executable_root / "ai" / "models" / "yolov8n.onnx",
            project_root / "ai" / "models" / "yolov8n.onnx",
            project_root.parent / "cvat" / "yolov8_onnx_person_detector" / "yolov8n.onnx",
        ]
        if getattr(sys, "frozen", False) and sys.platform == "darwin":
            contents_root = executable_root.parent
            candidates.insert(1, contents_root / "Resources" / "ai" / "models" / "yolov8n.onnx")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    @staticmethod
    def _opencv_version_tuple():
        parts = []
        for token in cv2.__version__.split(".")[:3]:
            try:
                parts.append(int(token))
            except ValueError:
                parts.append(0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)

    @classmethod
    def _opencv_supports_model(cls):
        return cls._opencv_version_tuple() >= (4, 11, 0)

    def is_available(self):
        return bool(self.model_path and self.model_path.exists()) and not self.disabled

    def _ensure_loaded(self):
        if self.net is not None:
            return True
        if self.disabled:
            return False
        if not self.model_path or not self.model_path.exists():
            self.last_error = f"YOLO model not found: {self.model_path}"
            self.disabled = True
            return False
        if not self._opencv_supports_model():
            self.last_error = f"YOLO requires OpenCV 4.11+, current version is {cv2.__version__}"
            self.disabled = True
            return False
        try:
            self.net = cv2.dnn.readNetFromONNX(str(self.model_path))
        except Exception as exc:
            self.last_error = f"Failed to load YOLO model: {exc}"
            self.disabled = True
            self.net = None
            return False
        return True

    def detect(self, rgb_frame):
        if rgb_frame is None or not self._ensure_loaded():
            return []
        if not isinstance(rgb_frame, np.ndarray) or rgb_frame.ndim != 3:
            return []

        height, width = rgb_frame.shape[:2]
        if height <= 0 or width <= 0:
            return []

        try:
            blob = cv2.dnn.blobFromImage(
                rgb_frame,
                1 / 255.0,
                (self.input_size, self.input_size),
                swapRB=False,
                crop=False,
            )
            self.net.setInput(blob)
            output = self.net.forward()
        except Exception as exc:
            self.last_error = f"YOLO inference failed: {exc}"
            self.disabled = True
            return []

        predictions = np.squeeze(output)
        if predictions.ndim != 2:
            return []
        if predictions.shape[0] < predictions.shape[1]:
            predictions = predictions.T
        if predictions.shape[1] < 5:
            return []

        class_scores = predictions[:, 4:]
        scores = class_scores.max(axis=1)
        class_ids = class_scores.argmax(axis=1)
        mask = (scores >= self.confidence_threshold) & (class_ids == 0)
        predictions = predictions[mask]
        scores = scores[mask]
        if predictions.size == 0:
            return []

        x_factor = width / self.input_size
        y_factor = height / self.input_size
        boxes = []
        confidences = []
        for row, score in zip(predictions, scores):
            cx, cy, box_w, box_h = row[:4]
            x = int((cx - box_w / 2) * x_factor)
            y = int((cy - box_h / 2) * y_factor)
            w = int(box_w * x_factor)
            h = int(box_h * y_factor)
            boxes.append([x, y, w, h])
            confidences.append(float(score))

        indices = cv2.dnn.NMSBoxes(
            boxes,
            confidences,
            self.confidence_threshold,
            self.iou_threshold,
        )
        if len(indices) == 0:
            return []
        indices = np.array(indices).reshape(-1).tolist()

        detections = []
        for index in indices:
            x, y, box_w, box_h = boxes[index]
            x1 = max(0, min(width - 1, x))
            y1 = max(0, min(height - 1, y))
            x2 = max(0, min(width - 1, x + box_w))
            y2 = max(0, min(height - 1, y + box_h))
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append({
                "confidence": confidences[index],
                "bbox": [x1, y1, x2, y2],
                "foot": [int((x1 + x2) / 2), y2],
            })
        detections.sort(key=lambda item: item["confidence"], reverse=True)
        return detections
