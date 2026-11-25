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


def shrink_mask(mask: np.ndarray, pixels: int = None, motion=(0.0, 0.0)) -> np.ndarray:
    """Erode a binary object mask so edge/shadow pixels are excluded.

    Default depth: MASK_ERODE_PX or MASK_ERODE_RATIO of the object's smaller
    side, whichever is larger (a blurred object has a wider soft edge).
    ``motion`` is the object's movement in px per frame (dx, dy): on a running
    belt the front and back edges are smeared with the belt colour, so those
    edges are eroded further, only along the direction of travel.
    """
    if pixels is None:
        pixels = config.MASK_ERODE_PX
        ys, xs = np.nonzero(mask)
        if len(xs):
            side = min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1)
            pixels = max(pixels, int(side * getattr(config, "MASK_ERODE_RATIO", 0)))
    fraction = getattr(config, "MOTION_BLUR_FRACTION", 0.0)
    extra_x = int(round(abs(motion[0]) * fraction))
    extra_y = int(round(abs(motion[1]) * fraction))
    if pixels <= 0 and not (extra_x or extra_y):
        return mask
    ry, rx = max(pixels, 0) + extra_y, max(pixels, 0) + extra_x
    kernel = np.ones((2 * ry + 1, 2 * rx + 1), np.uint8)
    binary = (mask > 0).astype(np.uint8) * 255
    # The crop ends exactly at the object, so the mask touches the image
    # border, and cv2.erode never erodes from the border by default: pad with
    # background first so every edge is eroded.
    padded = cv2.copyMakeBorder(binary, ry, ry, rx, rx, cv2.BORDER_CONSTANT, value=0)
    eroded = cv2.erode(padded, kernel)
    return eroded[ry:ry + binary.shape[0], rx:rx + binary.shape[1]]


class QualityInspector:
    """Classify one object from its BGR crop and binary object mask.

    * ``PERFECT`` – red coverage >= RED_COVERAGE_THRESHOLD and no non-red
      region larger than the blob limit (no pattern / spot).
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
        # Dark patterns (marker dots, lines) blurred into the red can still
        # have a red hue: count pixels much darker than the object's red
        # surface as pattern, not red. A uniformly dull red object is
        # unaffected because the reference is its own brightness.
        # Dark areas that touch the object's outline are NOT patterns: with
        # the camera close above, the cube's shaded side faces show along its
        # edge. Only dark areas inside the surface count.
        value = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)[:, :, 2]
        red_v = value[(red_mask > 0) & (mask_bin > 0)]
        # Brightness of the object's (red) surface; for a non-red object use
        # the object itself.
        surface = float(np.percentile(red_v if red_v.size else value[mask_bin > 0], 75))
        rel_v = getattr(config, "RED_MIN_RELATIVE_V", 0.0)
        if rel_v > 0:
            if red_v.size:
                dark_red = ((value < rel_v * surface) & (red_mask > 0) & (mask_bin > 0)).astype(np.uint8)
                count, labels = cv2.connectedComponents(dark_red, connectivity=8)
                if count > 1:
                    outline = cv2.copyMakeBorder(mask_bin, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
                    outline = cv2.dilate(255 - outline, np.ones((5, 5), np.uint8))[1:-1, 1:-1] > 0
                    touching = np.unique(labels[outline & (dark_red > 0)])
                    interior = (labels > 0) & ~np.isin(labels, touching)
                    if interior.any():
                        red_mask = red_mask.copy()
                        red_mask[interior] = 0
        red_in_object = cv2.bitwise_and(red_mask, mask_bin)
        red_pixels = int(cv2.countNonZero(red_in_object))
        non_red_pixels = object_pixels - red_pixels
        red_coverage = red_pixels / float(object_pixels)

        # Largest connected non-red region inside the object = pattern / spot size.
        # A thin strip along the outline is the out-of-focus edge mixed with
        # the belt colour, not a pattern: blobs that reach less than
        # EDGE_BAND_RATIO of the object's side into the surface are ignored.
        non_red_mask = cv2.bitwise_and(cv2.bitwise_not(red_mask), mask_bin)
        largest_defect_area = 0
        if non_red_pixels:
            count, labels, stats, _ = cv2.connectedComponentsWithStats(non_red_mask, connectivity=8)
            if count > 1:
                ys, xs = np.nonzero(mask_bin)
                side = min(np.ptp(xs) + 1, np.ptp(ys) + 1)
                edge_band = max(3.0, getattr(config, "EDGE_BAND_RATIO", 0.0) * side)
                shadow_depth = getattr(config, "EDGE_SHADOW_DEPTH_RATIO", 0.0) * side
                shadow_v = getattr(config, "EDGE_SHADOW_MAX_V", 0.0) * surface
                depth = cv2.distanceTransform(
                    cv2.copyMakeBorder(mask_bin, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0),
                    cv2.DIST_L2, 5)[1:-1, 1:-1]
                for i in range(1, count):
                    blob = labels == i
                    blob_depth = float(depth[blob].max())
                    if blob_depth < edge_band:
                        continue  # thin out-of-focus edge strip
                    touches_outline = float(depth[blob].min()) <= 1.5
                    if (touches_outline and blob_depth < shadow_depth
                            and float(np.median(value[blob])) < shadow_v):
                        continue  # very dark band along the edge = the cube's shadow
                    largest_defect_area = max(largest_defect_area, int(stats[i, cv2.CC_STAT_AREA]))

        # A spot must be bigger than a fixed minimum AND a share of the object,
        # so blur/glare specks on a large object do not count as a pattern.
        blob_limit = max(self.min_blob_area,
                         int(getattr(config, "DEFECT_MIN_BLOB_RATIO", 0) * object_pixels))
        perfect = (
            red_coverage >= self.coverage_threshold
            and largest_defect_area < blob_limit
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
