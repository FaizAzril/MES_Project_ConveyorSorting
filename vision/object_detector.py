import cv2
import numpy as np
import logging
from typing import List, Tuple, Optional
import config

_logger = logging.getLogger(__name__)


class ObjectDetector:
    """Detects cuboid objects in a frame using background subtraction.

    The detector works independent of object colour; it relies on background
    subtraction (simple frame differencing) and contour filtering based on area
    and aspect ratio. For each valid contour a binary mask (uint8) of the same
    size as the input frame is returned together with its bounding box.
    """

    def __init__(self):
        # Background model – will be set explicitly via calibrate_background.
        self._background: Optional[np.ndarray] = None
        self.kernel = np.ones((5, 5), np.uint8)
        self.calibrated = False

    # ---------------------------------------------------------------------
    # Background handling
    # ---------------------------------------------------------------------
    def calibrate_background(self, frame: np.ndarray) -> None:
        """Manually set the background reference in BGR space.

        The caller must ensure the conveyor is clear and the frame size matches the
        desired detection size. The background is stored as a blurred BGR image so
        that later detection can compute per‑channel differences.
        """
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Background frame must be a BGR image with 3 channels.")
        # Apply Gaussian blur to reduce noise; keep BGR channels.
        self._background = cv2.GaussianBlur(frame, (7, 7), 0)
        self.calibrated = True
        _logger.debug("Background manually calibrated (BGR).")

    def _ensure_background(self, frame: np.ndarray) -> None:
        """Helper that raises an informative error if background is not set.
        """
        if not self.calibrated or self._background is None:
            raise RuntimeError(
                "Background not calibrated. Call calibrate_background(frame) first."
            )

    # ---------------------------------------------------------------------
    # Detection
    # ---------------------------------------------------------------------
    def detect(self, frame: np.ndarray) -> List[Tuple[Tuple[int, int, int, int], np.ndarray]]:
        """Detect objects and return a list of ``(box, mask)`` tuples.

        * ``box`` – (x, y, w, h) of the bounding rectangle.
        * ``mask`` – binary ``uint8`` mask of the same height/width as ``frame``
          where the object pixels are 255 and all other pixels are 0.
        Returns an empty list if no valid objects are found or if the detector
        has not been calibrated.
        """
        if not self.calibrated or self._background is None:
            # No background calibrated – nothing to detect.
            return []

                # Validate frame format and size.
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Input frame must be a BGR image with 3 channels.")
        if self._background.shape != frame.shape:
            raise ValueError("Input frame size does not match calibrated background size.")
        # Apply Gaussian blur to current frame for noise reduction.
        blurred = cv2.GaussianBlur(frame, (7, 7), 0)

        # Background subtraction per channel.
        diff = cv2.absdiff(self._background, blurred)
        # Use the maximum channel difference as the intensity measure.
        diff_max = np.max(diff, axis=2).astype(np.uint8)
        _, thresh = cv2.threshold(diff_max, 30, 255, cv2.THRESH_BINARY)

        # Morphological clean‑up.
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, self.kernel)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, self.kernel)

        # Find external contours.
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

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
            # Build mask for this single object.
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            cv2.drawContours(mask, [cnt], -1, 255, thickness=cv2.FILLED)
            if cv2.countNonZero(mask) == 0:
                continue
            results.append(((x, y, w, h), mask))

        _logger.debug("Detected %d objects with valid masks.", len(results))
        return results

    # ---------------------------------------------------------------------
    # Compatibility helper (optional – not required by the current spec).
    # ---------------------------------------------------------------------
    def update_background(self, frame: np.ndarray) -> None:
        """Legacy alias for :meth:`calibrate_background`.

        Keeping this method preserves backward compatibility with older code
        that may still call ``update_background``.
        """
        self.calibrate_background(frame)
