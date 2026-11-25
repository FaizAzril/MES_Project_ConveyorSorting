"""Detection under real webcam conditions on the real belt colour:
auto-exposure changes, cube shadows, dark objects and ragged belt blobs."""
import unittest

import cv2
import numpy as np

import config
from vision.object_detector import ObjectDetector
from vision.roi_manager import ROIManager

W, H = config.CAMERA_WIDTH, config.CAMERA_HEIGHT
BELT = (148, 166, 101)  # measured from the team's webcam image of the belt


def detect(draw=None, exposure=1.0, shadow=False, seed=0):
    rng = np.random.default_rng(seed)
    noise = lambda im: np.clip(im.astype(int) + rng.normal(0, 4, im.shape), 0, 255).astype(np.uint8)
    roi = ROIManager(W, H)
    bg = np.full((H, W, 3), BELT, np.uint8)
    frame = bg.copy()
    if shadow:
        frame[205:305, 360:410] = (np.array(BELT) * 0.5).astype(np.uint8)
    if draw:
        draw(frame)
    frame = np.clip(frame.astype(float) * exposure, 0, 255).astype(np.uint8)
    detector = ObjectDetector()
    detector.calibrate_background(roi.get_roi(noise(bg)))
    return [box for box, _ in detector.detect(roi.get_roi(noise(frame)))]


def cube(color):
    return lambda f: cv2.rectangle(f, (260, 200), (360, 300), color, -1)


class TestDetectionRobust(unittest.TestCase):
    def assertOneCube(self, boxes):
        self.assertEqual(len(boxes), 1, boxes)
        x, y, w, h = boxes[0]
        self.assertLessEqual(abs(w - 101), 6, boxes)  # shadow not included
        self.assertLessEqual(abs(h - 101), 6, boxes)

    def test_dark_blue(self):
        self.assertOneCube(detect(cube((100, 45, 25))))

    def test_dark_blue_when_webcam_brightens(self):
        for exposure in (1.2, 1.4, 1.6):
            with self.subTest(exposure=exposure):
                self.assertOneCube(detect(cube((100, 45, 25)), exposure=exposure))

    def test_light_object_when_webcam_darkens(self):
        self.assertOneCube(detect(cube((240, 240, 240)), exposure=0.7))

    def test_shadow_not_part_of_object(self):
        for color in [(100, 45, 25), (25, 25, 25), (60, 60, 220)]:
            with self.subTest(color=color):
                self.assertOneCube(detect(cube(color), shadow=True, exposure=1.3))

    def test_empty_belt_exposure_change_no_object(self):
        for exposure in (0.7, 1.3, 1.6):
            with self.subTest(exposure=exposure):
                self.assertEqual(detect(exposure=exposure), [])

    def test_ragged_belt_blob_rejected(self):
        def blob(f):
            pts = np.array([[290, 200], [390, 210], [320, 245], [395, 300], [285, 290], [335, 250]])
            cv2.fillPoly(f, [pts], (185, 205, 140))
        self.assertEqual(detect(blob), [])


if __name__ == "__main__":
    unittest.main()
