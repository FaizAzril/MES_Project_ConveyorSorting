import logging
import datetime
from typing import Dict, Tuple
import config
from .red_segmentation import get_red_mask, count_red_pixels

_logger = logging.getLogger(__name__)

class QualityInspector:
    """Computes red coverage and classification for a given object ROI.

    The object ROI is supplied as a numpy array (BGR) and the bounding box
    coordinates are used only for logging / optional future mask refinement.
    """

    def __init__(self):
        self.coverage_threshold = config.RED_COVERAGE_THRESHOLD

    def inspect(self, roi: "np.ndarray") -> Dict[str, any]:
        """Return a dictionary with inspection results.
        Keys: red_pixels, object_pixels, red_coverage, classification.
        """
        import numpy as np
        if roi is None or roi.size == 0:
            _logger.warning("Empty ROI received for inspection.")
            return {
                "red_pixels": 0,
                "object_pixels": 0,
                "red_coverage": 0.0,
                "classification": "INVALID",
            }
        h, w = roi.shape[:2]
        object_pixels = int(w * h)
        red_mask = get_red_mask(roi)
        red_pixels = count_red_pixels(red_mask)
        red_coverage = red_pixels / float(object_pixels) if object_pixels else 0.0
        classification = (
            "PERFECT" if red_coverage >= self.coverage_threshold else "DEFECT"
        )
        _logger.debug(
            "QualityInspection: red=%d / total=%d => %.3f => %s",
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
