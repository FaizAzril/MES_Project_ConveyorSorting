"""Multi-frame median background calibrator."""
import cv2
import numpy as np
import logging
from typing import Optional
import config

_logger = logging.getLogger(__name__)


class BackgroundCalibrator:
    """Collect N frames and produce a median background image."""

    def __init__(self):
        self._frames = []
        self.background: Optional[np.ndarray] = None
        self.calibrated: bool = False

    def reset(self):
        self._frames.clear()
        self.background = None
        self.calibrated = False

    @property
    def progress(self) -> float:
        """0.0 – 1.0 fraction of frames collected."""
        return min(len(self._frames) / config.CALIB_FRAME_COUNT, 1.0)

    @property
    def is_collecting(self) -> bool:
        return not self.calibrated and len(self._frames) > 0

    def add_frame(self, frame: np.ndarray) -> bool:
        """Add a frame. Returns True when calibration is complete."""
        if self.calibrated:
            return True
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Frame must be a 3-channel BGR image.")
        self._frames.append(frame.copy())
        if len(self._frames) >= config.CALIB_FRAME_COUNT:
            stack = np.stack(self._frames, axis=0).astype(np.float32)
            self.background = np.median(stack, axis=0).astype(np.uint8)
            self.calibrated = True
            _logger.info("Background calibrated from %d frames.", config.CALIB_FRAME_COUNT)
            return True
        return False
