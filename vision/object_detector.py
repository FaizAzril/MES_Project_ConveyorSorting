import cv2
import numpy as np
import logging
from typing import List, Tuple, Optional
import config

_logger = logging.getLogger(__name__)


class ObjectDetector:
    """Detects cuboid objects in a frame using background subtraction."""

    def __init__(self):
        self._background: Optional[np.ndarray] = None
        self.kernel = np.ones((3, 3), np.uint8)
        self.calibrated = False

    def calibrate_background(self, frame: np.ndarray) -> None:
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Background frame must be a BGR image with 3 channels.")
        self._background = frame.copy()
        self.calibrated = True
        _logger.debug("Background manually calibrated (BGR).")

    def calibrate_from_frames(self, frames: List[np.ndarray]) -> None:
        """Build a median background from a list of frames."""
        if not frames:
            raise ValueError("No frames provided for calibration.")
        stack = np.stack([f.astype(np.float32) for f in frames], axis=0)
        median = np.median(stack, axis=0).astype(np.uint8)
        self._background = median
        self.calibrated = True
        _logger.info("Background calibrated from %d frames (median).", len(frames))

    def _ensure_background(self, frame: np.ndarray) -> None:
        if not self.calibrated or self._background is None:
            raise RuntimeError("Background not calibrated. Call calibrate_background(frame) first.")

    def detect(self, frame: np.ndarray) -> List[Tuple[Tuple[int, int, int, int], np.ndarray]]:
        if not self.calibrated or self._background is None:
            return []
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Input frame must be a BGR image with 3 channels.")
        if self._background.shape != frame.shape:
            raise ValueError("Input frame size does not match calibrated background size.")
        diff = cv2.absdiff(self._background, frame)
        diff_max = np.max(diff, axis=2).astype(np.uint8)
        _, thresh = cv2.threshold(diff_max, getattr(config, 'CALIB_DIFF_THRESHOLD', 30), 255, cv2.THRESH_BINARY)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self.kernel)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        results: List[Tuple[Tuple[int, int, int, int], np.ndarray]] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < config.MIN_OBJECT_AREA:
                continue
            max_area = getattr(config, "MAX_OBJECT_AREA", 1e6)
            if area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            if h == 0:
                continue
            aspect = w / float(h)
            if abs(aspect - 1.0) > config.ASPECT_RATIO_TOLERANCE:
                continue
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.drawContours(mask, [cnt], -1, 255, thickness=cv2.FILLED)
            if cv2.countNonZero(mask) == 0:
                continue
            results.append(((x, y, w, h), mask))
        _logger.debug("Detected %d objects.", len(results))
        return results

    def update_background(self, frame: np.ndarray) -> None:
        self.calibrate_background(frame)
