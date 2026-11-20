import cv2
import numpy as np
import logging
import config

_logger = logging.getLogger(__name__)

def get_red_mask(frame: np.ndarray) -> np.ndarray:
    """Return a binary mask where red pixels are 255.

    Two HSV ranges are combined because red wraps around the hue axis.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower1 = np.array(config.LOWER_RED1, dtype=np.uint8)
    upper1 = np.array(config.UPPER_RED1, dtype=np.uint8)
    lower2 = np.array(config.LOWER_RED2, dtype=np.uint8)
    upper2 = np.array(config.UPPER_RED2, dtype=np.uint8)
    mask1 = cv2.inRange(hsv, lower1, upper1)
    mask2 = cv2.inRange(hsv, lower2, upper2)
    mask = cv2.bitwise_or(mask1, mask2)
    # optional morphological cleaning
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask

def count_red_pixels(mask: np.ndarray) -> int:
    return int(cv2.countNonZero(mask))
