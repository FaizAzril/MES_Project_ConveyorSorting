import cv2
import numpy as np
import logging
import config

_logger = logging.getLogger(__name__)

class ROIManager:
    """Manages the region of interest for inspection.
    The ROI is defined as a relative rectangle of the frame based on
    configuration ratios.
    """

    def __init__(self, frame_width: int, frame_height: int):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.update_bounds()

    def update_bounds(self) -> None:
        self.x1 = int(config.ROI_X_START_RATIO * self.frame_width)
        self.x2 = int(config.ROI_X_END_RATIO * self.frame_width)
        self.y1 = int(config.ROI_Y_START_RATIO * self.frame_height)
        self.y2 = int(config.ROI_Y_END_RATIO * self.frame_height)
        _logger.debug(
            "ROI bounds updated: (%d, %d) - (%d, %d)",
            self.x1,
            self.y1,
            self.x2,
            self.y2,
        )

    def get_roi(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y1:self.y2, self.x1:self.x2]

    def draw(self, frame: np.ndarray) -> np.ndarray:
        cv2.rectangle(frame, (self.x1, self.y1), (self.x2, self.y2), (0, 255, 0), 2)
        return frame
