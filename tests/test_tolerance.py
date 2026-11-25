"""Tolerance tests: realistic camera conditions (blur, dull red, glare,
soft edges) must still give PERFECT for a plain red object, while patterns
and other colours stay DEFECT. Runs the same detector -> shrink -> inspect
chain as vision/pipeline.py."""
import unittest

import cv2
import numpy as np

import config
from vision.object_detector import ObjectDetector
from vision.quality_inspector import QualityInspector, shrink_mask
from vision.roi_manager import ROIManager

W, H = config.CAMERA_WIDTH, config.CAMERA_HEIGHT
BG = (95, 130, 95)  # greenish-grey belt


def inspect_frame(draw, blur=0):
    """Draw an object on the belt, optionally blur the camera image, inspect it."""
    roi_mgr = ROIManager(W, H)
    background = np.full((H, W, 3), BG, np.uint8)
    frame = background.copy()
    draw(frame)
    if blur:
        frame = cv2.GaussianBlur(frame, (0, 0), blur)
        background = cv2.GaussianBlur(background, (0, 0), blur)
    detector = ObjectDetector()
    detector.calibrate_background(roi_mgr.get_roi(background))
    detections = detector.detect(roi_mgr.get_roi(frame))
    if not detections:
        return None
    roi_box, roi_mask = max(detections, key=lambda d: d[0][2] * d[0][3])
    full_box = roi_mgr.abs_box(roi_box)
    full_mask = np.zeros((H, W), np.uint8)
    full_mask[roi_mgr.y1:roi_mgr.y2, roi_mgr.x1:roi_mgr.x2] = roi_mask
    obj, mask = roi_mgr.crop_object_with_mask(frame, full_box, full_mask)
    return QualityInspector().inspect(obj, shrink_mask(mask))


def square(color, size=110, x=265, y=185):
    return lambda f: cv2.rectangle(f, (x, y), (x + size, y + size), color, -1)


class TestTolerance(unittest.TestCase):
    def assertClass(self, res, expected):
        self.assertIsNotNone(res, "object not detected")
        self.assertEqual(res["classification"], expected, res)

    def test_sharp_red_perfect(self):
        self.assertClass(inspect_frame(square((30, 30, 200))), "PERFECT")

    def test_blurred_red_perfect(self):
        self.assertClass(inspect_frame(square((30, 30, 200)), blur=4), "PERFECT")

    def test_very_blurred_red_perfect(self):
        self.assertClass(inspect_frame(square((30, 30, 200)), blur=8), "PERFECT")

    def test_dull_dark_red_perfect(self):
        # dark, low-saturation red (paper in weak light): H~0, S~110, V~120
        self.assertClass(inspect_frame(square((70, 70, 120)), blur=3), "PERFECT")

    def test_red_with_small_glare_perfect(self):
        def draw(f):
            square((30, 30, 200))(f)
            cv2.circle(f, (300, 210), 4, (235, 235, 245), -1)  # light reflection
        self.assertClass(inspect_frame(draw, blur=2), "PERFECT")

    def test_blurred_red_with_dark_spot_defect(self):
        def draw(f):
            square((30, 30, 200))(f)
            cv2.circle(f, (320, 240), 12, (20, 20, 20), -1)  # marker dot ~5 mm
        self.assertClass(inspect_frame(draw, blur=3), "DEFECT")

    def test_red_with_stripe_defect(self):
        def draw(f):
            square((30, 30, 200))(f)
            cv2.rectangle(f, (265, 230), (375, 242), (240, 240, 240), -1)
        self.assertClass(inspect_frame(draw, blur=3), "DEFECT")

    def test_blurred_blue_defect(self):
        self.assertClass(inspect_frame(square((200, 60, 30)), blur=4), "DEFECT")

    def test_blurred_orange_defect(self):
        self.assertClass(inspect_frame(square((0, 140, 255)), blur=4), "DEFECT")

    def test_pink_defect(self):
        self.assertClass(inspect_frame(square((200, 120, 255)), blur=3), "DEFECT")


if __name__ == "__main__":
    unittest.main()
