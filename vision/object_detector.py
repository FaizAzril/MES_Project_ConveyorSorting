import cv2
import numpy as np
import logging
from typing import List, Tuple, Optional
import config

_logger = logging.getLogger(__name__)

class ObjectDetector:
    """Detects cuboid objects in a frame using contour analysis.

    The detector works independent of object colour; it relies on
    background subtraction (simple frame differencing) and contour
    filtering based on area and aspect ratio.
    """

    def __init__(self):
        # background model – the first successful frame will be used as reference
        self.background: Optional[np.ndarray] = None
        self.kernel = np.ones((5, 5), np.uint8)
        self.frame_counter = 0
        self.reset_interval = 200  # frames after which background is refreshed

    def _update_background(self, frame: np.ndarray):
        """Set or refresh the background reference (grayscale, blurred)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.background = cv2.GaussianBlur(gray, (7, 7), 0)
        _logger.debug("Background model updated.")

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Return a list of bounding boxes (x, y, w, h) for detected objects.

        If background is not set, initialise it and return an empty list.
        """
        if self.background is None:
            self._update_background(frame)
            return []
        # periodically refresh background to adapt to lighting changes
        self.frame_counter += 1
        if self.frame_counter % self.reset_interval == 0:
            self._update_background(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)
        diff = cv2.absdiff(self.background, gray)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        # clean noise
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self.kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self.kernel)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: List[Tuple[int, int, int, int]] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < config.MIN_OBJECT_AREA or area > getattr(config, "MAX_OBJECT_AREA", 1e6):
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # aspect ratio close to square (cube top view)
            if h == 0:
                continue
            aspect = w / float(h)
            if abs(aspect - 1.0) > config.ASPECT_RATIO_TOLERANCE:
                continue
            boxes.append((x, y, w, h))
        _logger.debug("Detected %d objects.", len(boxes))
        return boxes

    def update_background(self, frame: np.ndarray):
        """Set the background reference (grayscale)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.background = cv2.GaussianBlur(gray, (7, 7), 0)
        _logger.debug("Background model updated.")

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Return a list of bounding boxes (x, y, w, h) for detected objects.

        If background is not set, the current frame becomes the background
        and an empty list is returned.
        """
        if self.background is None:
            self.update_background(frame)
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)
        diff = cv2.absdiff(self.background, gray)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        # clean noise
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self.kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self.kernel)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes: List[Tuple[int, int, int, int]] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < config.MIN_OBJECT_AREA or area > getattr(config, "MAX_OBJECT_AREA", 1e6):
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # aspect ratio close to square (cube top view)
            aspect = w / float(h) if h != 0 else 0
            if abs(aspect - 1.0) > config.ASPECT_RATIO_TOLERANCE:
                continue
            boxes.append((x, y, w, h))
        _logger.debug("Detected %d objects.", len(boxes))
        return boxes
