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
        background = self._exposure_matched_background(frame)
        diff = cv2.absdiff(background, frame)
        diff_max = np.max(diff, axis=2).astype(np.uint8)
        _, thresh = cv2.threshold(diff_max, getattr(config, 'CALIB_DIFF_THRESHOLD', 30), 255, cv2.THRESH_BINARY)
        if getattr(config, "SHADOW_SUPPRESSION", True):
            thresh[self._shadow_mask(background, frame)] = 0
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self.kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self.kernel)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        results: List[Tuple[Tuple[int, int, int, int], np.ndarray]] = []
        self.rejected: List[Tuple[Tuple[int, int, int, int], str]] = []
        min_solidity = getattr(config, "MIN_SOLIDITY", 0.0)
        min_extent = getattr(config, "MIN_EXTENT", 0.0)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            box = cv2.boundingRect(cnt)
            x, y, w, h = box
            if area < config.MIN_OBJECT_AREA:
                if area >= config.MIN_OBJECT_AREA / 4:
                    self.rejected.append((box, "kecil"))
                continue
            if area > getattr(config, "MAX_OBJECT_AREA", 1e6):
                self.rejected.append((box, "besar"))
                continue
            if h == 0:
                continue
            if abs(w / float(h) - 1.0) > config.ASPECT_RATIO_TOLERANCE:
                self.rejected.append((box, "bukan persegi"))
                continue
            # A cube seen from above is one solid blob. Belt texture, lighting
            # flicker and hands give ragged shapes: reject those.
            hull_area = cv2.contourArea(cv2.convexHull(cnt))
            if hull_area and area / hull_area < min_solidity:
                self.rejected.append((box, "tidak padat"))
                continue
            if area / float(w * h) < min_extent:
                self.rejected.append((box, "tidak padat"))
                continue
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.drawContours(mask, [cnt], -1, 255, thickness=cv2.FILLED)
            if cv2.countNonZero(mask) == 0:
                continue
            results.append((box, mask))
        _logger.debug("Detected %d objects (%d rejected).", len(results), len(self.rejected))
        return results

    @staticmethod
    def _shadow_mask(background: np.ndarray, frame: np.ndarray) -> np.ndarray:
        """Pixels that are just a darker copy of the belt (the cube's shadow).

        Shadow keeps the belt's colour (same channel ratios) and only loses
        brightness; a dark object, even dark blue, changes the colour itself.
        """
        bg = background.astype(np.float32) + 1.0
        fr = frame.astype(np.float32) + 1.0
        ratio = fr / bg                              # per-channel brightness ratio
        mean = ratio.mean(axis=2)
        spread = np.abs(ratio - mean[..., None]).max(axis=2)
        return (mean > 0.3) & (mean < 0.92) & (spread < 0.12 * mean + 0.03)

    def _exposure_matched_background(self, frame: np.ndarray) -> np.ndarray:
        """Scale the stored background to the frame's current exposure.

        Webcams change exposure on their own (a dark object makes the whole
        picture brighter). Without this the whole belt differs from the
        calibration and a dark object merges with it. The gain is measured on
        a thin strip along the ROI border, which is belt (objects must be
        fully inside the ROI).
        """
        if not getattr(config, "EXPOSURE_COMPENSATION", True):
            return self._background
        h, w = frame.shape[:2]
        s = max(4, int(min(h, w) * 0.06))
        strip = np.zeros((h, w), bool)
        strip[:s, :] = strip[-s:, :] = True
        strip[:, :s] = strip[:, -s:] = True
        bg = self._background[strip].astype(np.float32)
        fr = frame[strip].astype(np.float32)
        gain = (np.median(fr, axis=0) + 1.0) / (np.median(bg, axis=0) + 1.0)
        gain = np.clip(gain, 0.5, 2.0)
        if np.all(np.abs(gain - 1.0) < 0.02):
            return self._background
        return np.clip(self._background.astype(np.float32) * gain, 0, 255).astype(np.uint8)

    def update_background(self, frame: np.ndarray) -> None:
        self.calibrate_background(frame)
