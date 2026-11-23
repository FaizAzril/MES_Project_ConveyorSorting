"""Camera inspection pipeline running in a background thread.

Each loop: grab frame -> (calibrate | detect -> gate -> inspect) -> draw overlay
-> JPEG for the dashboard stream. Finished inspections are handed to
``on_record`` (Firebase sync + dashboard state).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

import cv2
import numpy as np

import config
from camera.camera_manager import CameraManager
from .background_calibrator import BackgroundCalibrator
from .inspection_history import InspectionHistory
from .object_detector import ObjectDetector
from .object_tracker import READY, WAIT_CLEAR, EventGate
from .quality_inspector import QualityInspector, shrink_mask
from .roi_manager import ROIManager

_logger = logging.getLogger(__name__)

CLR_PERFECT = (60, 200, 60)
CLR_DEFECT = (60, 60, 230)
CLR_WAIT = (0, 210, 230)
CLR_GRAY = (160, 160, 160)
CLR_WHITE = (255, 255, 255)
CLR_BLACK = (0, 0, 0)


def _put_text(img, text, pos, color=CLR_WHITE, scale=0.52, thickness=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, CLR_BLACK, thickness + 2, cv2.LINE_AA)
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


class InspectionPipeline:
    def __init__(self, on_record: Optional[Callable[[Dict[str, Any]], None]] = None,
                 camera: Optional[CameraManager] = None):
        self.on_record = on_record
        self.camera = camera or CameraManager()
        self.calibrator = BackgroundCalibrator()
        self.detector = ObjectDetector()
        self.inspector = QualityInspector()
        self.gate = EventGate()
        self.history = InspectionHistory()
        self.roi: Optional[ROIManager] = None
        self._warmup_left = 0

        self.debug = False
        self.camera_running = False
        self.camera_error = ""
        self.last_record: Optional[Dict[str, Any]] = None
        self.counts = {"total": 0, "perfect": 0, "defect": 0, "invalid": 0}

        self._jpeg: Optional[bytes] = None
        self._jpeg_seq = 0
        self._frame_cond = threading.Condition()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="cv-pipeline", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self.stop_camera()

    def start_camera(self) -> bool:
        with self._lock:
            if self.camera_running:
                return True
            if not self.camera.start():
                self.camera_error = f"Kamera index {config.CAMERA_INDEX} tidak dapat dibuka"
                return False
            self.camera_error = ""
            self.camera_running = True
            self._begin_calibration()
            return True

    def stop_camera(self) -> None:
        with self._lock:
            if not self.camera_running:
                return
            self.camera_running = False
            self.camera.stop()
            self.roi = None
        self._publish_jpeg(None)

    def recalibrate(self) -> bool:
        with self._lock:
            if not self.camera_running:
                return False
            self._begin_calibration()
            return True

    def _begin_calibration(self) -> None:
        self.calibrator.reset()
        self.detector = ObjectDetector()
        self.gate.reset()
        self._warmup_left = config.CALIB_WARMUP_FRAMES

    # ── state for the dashboard ───────────────────────────────────────────
    @property
    def session_id(self) -> str:
        return self.gate.session_id

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self.camera_running,
                "error": self.camera_error,
                "calibrated": self.calibrator.calibrated,
                "calibrationProgress": round(self.calibrator.progress, 3),
                "gate": self.gate.state,
                "debug": self.debug,
                "cameraIndex": config.CAMERA_INDEX,
            }

    # ── MJPEG frames ──────────────────────────────────────────────────────
    def _publish_jpeg(self, data: Optional[bytes]) -> None:
        with self._frame_cond:
            self._jpeg = data
            self._jpeg_seq += 1
            self._frame_cond.notify_all()

    def wait_jpeg(self, last_seq: int, timeout: float = 1.0):
        """Block until a frame newer than last_seq exists. Returns (seq, jpeg)."""
        with self._frame_cond:
            if self._jpeg_seq == last_seq:
                self._frame_cond.wait(timeout)
            return self._jpeg_seq, self._jpeg

    # ── main loop ─────────────────────────────────────────────────────────
    def _loop(self) -> None:
        frame_interval = 1.0 / 30.0
        stream_interval = 1.0 / max(1, config.STREAM_FPS)
        next_stream = 0.0
        while not self._stop.is_set():
            if not self.camera_running:
                time.sleep(0.1)
                continue
            started = time.monotonic()
            try:
                frame = self.camera.get_frame()
            except Exception:
                _logger.exception("Camera read failed")
                frame = None
            if frame is None:
                time.sleep(0.02)
                continue
            try:
                with self._lock:
                    display = self._process(frame)
            except Exception:
                _logger.exception("Pipeline error on frame")
                time.sleep(0.1)
                continue
            if started >= next_stream:
                next_stream = started + stream_interval
                ok, buf = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, config.STREAM_JPEG_QUALITY])
                if ok:
                    self._publish_jpeg(buf.tobytes())
            elapsed = time.monotonic() - started
            if elapsed < frame_interval:
                time.sleep(frame_interval - elapsed)

    def _process(self, frame: np.ndarray) -> np.ndarray:
        if self.roi is None:
            h, w = frame.shape[:2]
            self.roi = ROIManager(w, h)
        roi_mgr = self.roi
        display = frame.copy()

        if not self.calibrator.calibrated:
            if self._warmup_left > 0:
                self._warmup_left -= 1
            else:
                self.calibrator.add_frame(roi_mgr.get_roi(frame))
            if self.calibrator.calibrated:
                self.detector.calibrate_background(self.calibrator.background)
                _logger.info("Background calibration completed")
            roi_mgr.draw(display, color=CLR_WAIT)
            pct = int(self.calibrator.progress * 100)
            _put_text(display, f"KALIBRASI {pct}% - KOSONGKAN CONVEYOR", (10, 26), CLR_WAIT)
            return display

        best_box, best_mask, best_area = None, None, 0
        for roi_box, roi_mask in self.detector.detect(roi_mgr.get_roi(frame)):
            full_box = roi_mgr.abs_box(roi_box)
            area = int(roi_box[2]) * int(roi_box[3])
            if roi_mgr.is_fully_inside_roi(full_box) and area > best_area:
                best_box, best_area = full_box, area
                best_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                best_mask[roi_mgr.y1:roi_mgr.y2, roi_mgr.x1:roi_mgr.x2] = roi_mask

        detected = best_box is not None
        event_id = self.gate.update(detected)
        if event_id and detected:
            obj_roi, obj_mask = roi_mgr.crop_object_with_mask(frame, best_box, best_mask)
            result = self.inspector.inspect(obj_roi, shrink_mask(obj_mask))
            record = self.history.add(event_id, result, self.session_id)
            self.last_record = record
            cls = record["classification"].lower()
            self.counts["total"] += 1
            self.counts[cls] = self.counts.get(cls, 0) + 1
            self.gate.mark_inspection_done()
            _logger.info("Inspection %s: %s (coverage=%.4f, largest defect=%d px)",
                         event_id, record["classification"], record["red_coverage"],
                         record["largest_defect_area"])
            if self.on_record:
                try:
                    self.on_record(record)
                except Exception:
                    _logger.exception("on_record callback failed")

        # overlay
        roi_mgr.draw(display, color=CLR_WAIT if detected else CLR_GRAY)
        if detected:
            x, y, w, h = best_box
            color = CLR_WAIT
            if self.last_record and self.gate.state != READY:
                color = CLR_PERFECT if self.last_record["classification"] == "PERFECT" else CLR_DEFECT
            cv2.rectangle(display, (x, y), (x + w, y + h), color, 2)
            if self.debug:
                overlay = display[y:y + h, x:x + w]
                tint = np.zeros_like(overlay)
                tint[:, :, 1] = best_mask[y:y + h, x:x + w]
                display[y:y + h, x:x + w] = cv2.addWeighted(overlay, 1.0, tint, 0.3, 0)
        state_color = CLR_WAIT if self.gate.state in (READY, WAIT_CLEAR) else CLR_PERFECT
        _put_text(display, f"GATE: {self.gate.state}", (10, 26), state_color)
        if self.last_record:
            cls = self.last_record["classification"]
            color = CLR_PERFECT if cls == "PERFECT" else CLR_DEFECT if cls == "DEFECT" else CLR_WAIT
            _put_text(display, f"{self.last_record['event_id'][-6:]}  {cls}  "
                               f"{self.last_record['red_coverage']:.1%}", (10, 54), color, 0.62, 2)
        return display
