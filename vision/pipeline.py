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

from pathlib import Path

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


CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"


def save_capture(event_id: str, roi: np.ndarray, mask: np.ndarray, result: Dict[str, Any]) -> None:
    """Save [object | red pixels (red) and non-red pixels (blue)] for tuning."""
    if not getattr(config, "SAVE_CAPTURES", False) or roi is None or roi.size == 0:
        return
    try:
        from .red_segmentation import get_red_mask
        CAPTURES_DIR.mkdir(exist_ok=True)
        red = get_red_mask(roi)
        inside = mask > 0
        overlay = np.zeros_like(roi)
        overlay[inside & (red > 0)] = (0, 0, 255)
        overlay[inside & (red == 0)] = (255, 120, 0)
        scale = max(1, 160 // max(1, min(roi.shape[:2])))
        tile = np.hstack([roi, overlay])
        tile = cv2.resize(tile, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        label = (f"{result['classification']} cov={result['red_coverage']:.2f} "
                 f"spot={result.get('largest_defect_area', 0)}")
        canvas = np.zeros((tile.shape[0] + 22, max(tile.shape[1], 300), 3), np.uint8)
        canvas[22:, :tile.shape[1]] = tile
        cv2.putText(canvas, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, CLR_WHITE, 1, cv2.LINE_AA)
        cv2.imwrite(str(CAPTURES_DIR / f"{event_id}_{result['classification']}.jpg"), canvas)
        files = sorted(CAPTURES_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        for old in files[:-getattr(config, "CAPTURES_MAX", 200)]:
            old.unlink(missing_ok=True)
    except Exception:
        _logger.exception("Could not save capture for %s", event_id)


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
        self._prev_center = None
        self._motion = (0.0, 0.0)

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
                "fps": round(getattr(self.camera, "fps", 0.0), 1),
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
        last_seq = None
        while not self._stop.is_set():
            if not self.camera_running:
                time.sleep(0.1)
                continue
            started = time.monotonic()
            # Only process new webcam frames, so "N consecutive frames" means
            # N real images (the webcam may deliver fewer than 30 fps).
            seq = getattr(self.camera, "frame_seq", None)
            if seq is not None and seq == last_seq:
                time.sleep(0.003)
                continue
            last_seq = seq
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
            # Real webcams are paced by frame_seq above; only throttle sources
            # without it (test cameras) so no webcam frame is ever skipped.
            elapsed = time.monotonic() - started
            if seq is None and elapsed < frame_interval:
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
            if not roi_mgr.is_fully_inside_roi(full_box):
                # still entering / leaving, or too big for the ROI: show it in Debug
                self.detector.rejected.append((roi_box, "tepi ROI"))
                continue
            if area > best_area:
                best_box, best_area = full_box, area
                best_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                best_mask[roi_mgr.y1:roi_mgr.y2, roi_mgr.x1:roi_mgr.x2] = roi_mask

        detected = best_box is not None
        # Object speed in px/frame (from the previous frame) for motion-blur
        # aware inspection on a running belt.
        if detected:
            cx, cy = best_box[0] + best_box[2] / 2.0, best_box[1] + best_box[3] / 2.0
            if self._prev_center is not None:
                self._motion = (cx - self._prev_center[0], cy - self._prev_center[1])
            self._prev_center = (cx, cy)
        else:
            self._prev_center, self._motion = None, (0.0, 0.0)
        event_id = self.gate.update(detected)
        if event_id and detected:
            obj_roi, obj_mask = roi_mgr.crop_object_with_mask(frame, best_box, best_mask)
            inspect_mask = shrink_mask(obj_mask, motion=self._motion)
            result = self.inspector.inspect(obj_roi, inspect_mask)
            record = self.history.add(event_id, result, self.session_id)
            save_capture(event_id, obj_roi, inspect_mask, result)
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
        if self.debug:  # show blobs the detector ignored, and why
            for (rx, ry, rw, rh), reason in getattr(self.detector, "rejected", []):
                ax, ay, _, _ = roi_mgr.abs_box((rx, ry, rw, rh))
                cv2.rectangle(display, (ax, ay), (ax + rw, ay + rh), (255, 0, 255), 1)
                _put_text(display, reason, (ax, max(12, ay - 4)), (255, 0, 255), 0.4)
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
        fps = getattr(self.camera, "fps", 0.0)
        _put_text(display, f"GATE: {self.gate.state}   {fps:.0f} FPS", (10, 26), state_color)
        if self.last_record:
            cls = self.last_record["classification"]
            color = CLR_PERFECT if cls == "PERFECT" else CLR_DEFECT if cls == "DEFECT" else CLR_WAIT
            _put_text(display, f"{self.last_record['event_id'][-6:]}  {cls}  "
                               f"{self.last_record['red_coverage']:.1%}", (10, 54), color, 0.62, 2)
        return display
