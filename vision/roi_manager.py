"""ROI Manager – consistent coordinate contract.

All coordinates use FULL-FRAME space unless explicitly stated otherwise.
The ROI crop gives a sub-image; bounding boxes from ObjectDetector are in
ROI-local space and must be converted to full-frame via abs_box().
"""
import cv2
import numpy as np
import logging
import config

_logger = logging.getLogger(__name__)


class ROIManager:
    def __init__(self, frame_width: int, frame_height: int):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.update_bounds()

    def update_bounds(self) -> None:
        self.x1 = max(0, int(config.ROI_X_START_RATIO * self.frame_width))
        self.x2 = min(self.frame_width, int(config.ROI_X_END_RATIO * self.frame_width))
        self.y1 = max(0, int(config.ROI_Y_START_RATIO * self.frame_height))
        self.y2 = min(self.frame_height, int(config.ROI_Y_END_RATIO * self.frame_height))
        _logger.debug("ROI bounds: (%d,%d)-(%d,%d)", self.x1, self.y1, self.x2, self.y2)

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    def get_roi(self, frame: np.ndarray) -> np.ndarray:
        """Return the ROI sub-image (view, not copy)."""
        return frame[self.y1:self.y2, self.x1:self.x2]

    def abs_box(self, roi_box) -> tuple:
        """Convert (x,y,w,h) in ROI-local space to full-frame space."""
        x, y, w, h = roi_box
        return (x + self.x1, y + self.y1, w, h)

    def crop_object(self, frame: np.ndarray, full_frame_box) -> tuple:
        """Return (roi_img, mask) cropped to the bounding box.

        full_frame_box is (x,y,w,h) in full-frame coordinates.
        mask is a uint8 255/0 image the same size as roi_img with all pixels
        inside the box set to 255 (rectangular mask).
        """
        x, y, w, h = full_frame_box
        x = max(0, x)
        y = max(0, y)
        x2 = min(self.frame_width, x + w)
        y2 = min(self.frame_height, y + h)
        roi_img = frame[y:y2, x:x2].copy()
        mask = np.full(roi_img.shape[:2], 255, dtype=np.uint8)
        return roi_img, mask

    def crop_object_with_mask(self, frame: np.ndarray, full_frame_box, full_frame_mask: np.ndarray) -> tuple:
        """Return (roi_img, object_mask) using the actual detection mask."""
        x, y, w, h = full_frame_box
        x = max(0, x)
        y = max(0, y)
        x2 = min(self.frame_width, x + w)
        y2 = min(self.frame_height, y + h)
        roi_img = frame[y:y2, x:x2].copy()
        object_mask = full_frame_mask[y:y2, x:x2].copy()
        return roi_img, object_mask

    def is_fully_inside_roi(self, full_frame_box) -> bool:
        """Check whether the box is fully within the ROI with margin."""
        margin_x = int(self.width * config.GATE_MARGIN_RATIO)
        margin_y = int(self.height * config.GATE_MARGIN_RATIO)
        x, y, w, h = full_frame_box
        return (
            x >= self.x1 + margin_x
            and y >= self.y1 + margin_y
            and x + w <= self.x2 - margin_x
            and y + h <= self.y2 - margin_y
        )

    def draw(self, frame: np.ndarray, color=(0, 255, 255), thickness=2) -> np.ndarray:
        cv2.rectangle(frame, (self.x1, self.y1), (self.x2, self.y2), color, thickness)
        return frame
