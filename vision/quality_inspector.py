import logging
import config
import cv2
import numpy as np
from typing import Dict, Any
from .red_segmentation import get_red_mask


_logger = logging.getLogger(__name__)


class QualityInspector:
    """Computes red coverage and classification for a given ROI and mask.

    The API expects:
    * ``roi`` – BGR image region of the detected object.
    * ``object_mask`` – binary mask (0/255 or 0/1) with the same height/width as ``roi``.
    """

    def __init__(self):
        self.coverage_threshold = config.RED_COVERAGE_THRESHOLD

    def inspect(self, roi: "np.ndarray", object_mask: "np.ndarray") -> Dict[str, Any]:
        """Inspect an object and return inspection metrics.

        Returns a dict with keys:
        * ``red_pixels`` – number of red pixels inside the object.
        * ``object_pixels`` – total non‑zero object pixels.
        * ``red_coverage`` – red_pixels / object_pixels.
        * ``classification`` – ``PERFECT``, ``DEFECT`` or ``INVALID``.
        """


        # ---------- Validation ----------
        if roi is None or object_mask is None:
            _logger.warning("ROI or object mask is None.")
            return {"red_pixels": 0, "object_pixels": 0, "red_coverage": 0.0, "classification": "INVALID"}
        if not isinstance(roi, np.ndarray) or not isinstance(object_mask, np.ndarray):
            _logger.warning("ROI and mask must be numpy arrays.")
            return {"red_pixels": 0, "object_pixels": 0, "red_coverage": 0.0, "classification": "INVALID"}
        if roi.size == 0 or object_mask.size == 0:
            _logger.warning("Empty ROI or mask.")
            return {"red_pixels": 0, "object_pixels": 0, "red_coverage": 0.0, "classification": "INVALID"}
        if roi.ndim != 3 or roi.shape[2] != 3:
            _logger.warning("ROI must be a BGR image with 3 channels.")
            return {"red_pixels": 0, "object_pixels": 0, "red_coverage": 0.0, "classification": "INVALID"}
        if object_mask.shape != roi.shape[:2]:
            _logger.warning("Mask dimensions do not match ROI.")
            return {"red_pixels": 0, "object_pixels": 0, "red_coverage": 0.0, "classification": "INVALID"}

        # Normalize mask to binary 0/255 uint8
        mask_bin = (object_mask > 0).astype(np.uint8) * 255
        object_pixels = int(cv2.countNonZero(mask_bin))
        if object_pixels == 0:
            _logger.warning("Mask contains no foreground pixels.")
            return {"red_pixels": 0, "object_pixels": 0, "red_coverage": 0.0, "classification": "INVALID"}

        # Red segmentation on ROI
        red_mask = get_red_mask(roi)
        # Ensure masks have the same shape before intersection
        if red_mask.shape != mask_bin.shape:
            _logger.warning("Red mask and object mask dimensions do not match.")
            return {"red_pixels": 0, "object_pixels": object_pixels, "red_coverage": 0.0, "classification": "INVALID"}
        # Intersection of red and object mask using NumPy for safety
        intersect = np.bitwise_and(red_mask, mask_bin)
        red_pixels = int(cv2.countNonZero(intersect))

        red_coverage = red_pixels / float(object_pixels) if object_pixels else 0.0
        classification = "PERFECT" if red_coverage >= self.coverage_threshold else "DEFECT"
        _logger.debug(
            "QualityInspection: red=%d / object=%d => %.3f => %s",
            red_pixels,
            object_pixels,
            red_coverage,
            classification,
        )
        return {
            "red_pixels": red_pixels,
            "object_pixels": object_pixels,
            "red_coverage": red_coverage,
            "classification": classification,
        }
