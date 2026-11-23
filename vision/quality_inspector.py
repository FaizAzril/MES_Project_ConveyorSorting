"""Quality rule: red without pattern = PERFECT, anything else = DEFECT."""
import logging
from typing import Any, Dict

import cv2
import numpy as np

import config
from .red_segmentation import get_red_mask

_logger = logging.getLogger(__name__)


def _invalid(object_pixels: int = 0) -> Dict[str, Any]:
    return {
        "red_pixels": 0,
        "object_pixels": object_pixels,
        "red_coverage": 0.0,
        "non_red_pixels": object_pixels,
        "largest_defect_area": 0,
        "classification": "INVALID",
    }


def shrink_mask(mask: np.ndarray, pixels: int = None) -> np.ndarray:
    """Erode a binary object mask so edge/shadow pixels are excluded."""
    pixels = config.MASK_ERODE_PX if pixels is None else pixels
    if pixels <= 0:
        return mask
    kernel = np.ones((2 * pixels + 1, 2 * pixels + 1), np.uint8)
    return cv2.erode((mask > 0).astype(np.uint8) * 255, kernel)


class QualityInspector:
    """Classify one object from its BGR crop and binary object mask.

    * ``PERFECT`` – red coverage >= RED_COVERAGE_THRESHOLD and no non-red
      region as large as DEFECT_MIN_BLOB_AREA (no pattern / spot).
    * ``DEFECT``  – other colour, or red with a pattern.
    * ``INVALID`` – bad input (empty mask, wrong shape, ...).
    """

    def __init__(self):
        self.coverage_threshold = config.RED_COVERAGE_THRESHOLD
        self.min_blob_area = config.DEFECT_MIN_BLOB_AREA

    def inspect(self, roi: "np.ndarray", object_mask: "np.ndarray") -> Dict[str, Any]:
        if roi is None or object_mask is None:
            return _invalid()
        if not isinstance(roi, np.ndarray) or not isinstance(object_mask, np.ndarray):
            return _invalid()
        if roi.size == 0 or object_mask.size == 0:
            return _invalid()
        if roi.ndim != 3 or roi.shape[2] != 3:
            return _invalid()
        if object_mask.shape != roi.shape[:2]:
            return _invalid()

        mask_bin = (object_mask > 0).astype(np.uint8) * 255
        object_pixels = int(cv2.countNonZero(mask_bin))
        if object_pixels == 0:
            return _invalid()

        red_mask = get_red_mask(roi)
        red_in_object = cv2.bitwise_and(red_mask, mask_bin)
        red_pixels = int(cv2.countNonZero(red_in_object))
        non_red_pixels = object_pixels - red_pixels
        red_coverage = red_pixels / float(object_pixels)

        # Largest connected non-red region inside the object = pattern / spot size.
        non_red_mask = cv2.bitwise_and(cv2.bitwise_not(red_mask), mask_bin)
        largest_defect_area = 0
        if non_red_pixels:
            count, _, stats, _ = cv2.connectedComponentsWithStats(non_red_mask, connectivity=8)
            if count > 1:
                largest_defect_area = int(stats[1:, cv2.CC_STAT_AREA].max())

        perfect = (
            red_coverage >= self.coverage_threshold
            and largest_defect_area < self.min_blob_area
        )
        classification = "PERFECT" if perfect else "DEFECT"
        _logger.debug(
            "inspect: red=%d object=%d coverage=%.4f largest_defect=%d -> %s",
            red_pixels, object_pixels, red_coverage, largest_defect_area, classification,
        )
        return {
            "red_pixels": red_pixels,
            "object_pixels": object_pixels,
            "red_coverage": red_coverage,
            "non_red_pixels": non_red_pixels,
            "largest_defect_area": largest_defect_area,
            "classification": classification,
        }
