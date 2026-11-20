
import cv2
import numpy as np
import logging
import config

_logger = logging.getLogger(__name__)


def get_red_mask(frame: np.ndarray) -> np.ndarray:
    """
    Menghasilkan binary mask untuk piksel berwarna merah.

    Input:
        frame: Gambar BGR dari OpenCV.

    Output:
        Mask uint8 dengan nilai:
        255 = piksel merah
        0   = bukan piksel merah
    """

    # Validasi input
    if not isinstance(frame, np.ndarray):
        raise ValueError("Input frame must be a NumPy array.")

    if frame.size == 0:
        raise ValueError("Input frame is empty.")

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Input frame must be a BGR image with 3 channels.")

    # Konversi BGR ke HSV
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Rentang warna merah pertama
    lower1 = np.array(config.LOWER_RED1, dtype=np.uint8)
    upper1 = np.array(config.UPPER_RED1, dtype=np.uint8)

    # Rentang warna merah kedua
    lower2 = np.array(config.LOWER_RED2, dtype=np.uint8)
    upper2 = np.array(config.UPPER_RED2, dtype=np.uint8)

    # Segmentasi kedua rentang merah
    mask1 = cv2.inRange(hsv, lower1, upper1)
    mask2 = cv2.inRange(hsv, lower2, upper2)

    # Gabungkan kedua mask
    mask = cv2.bitwise_or(mask1, mask2)

    # Pembersihan noise
    kernel = np.ones((3, 3), np.uint8)

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel
    )

    # PENTING: Kembalikan hasil mask
    return mask


def count_red_pixels(mask: np.ndarray) -> int:
    """
    Menghitung jumlah piksel merah dalam binary mask.
    """

    if not isinstance(mask, np.ndarray):
        raise ValueError("Mask must be a NumPy array.")

    if mask.size == 0:
        return 0

    return int(cv2.countNonZero(mask))
