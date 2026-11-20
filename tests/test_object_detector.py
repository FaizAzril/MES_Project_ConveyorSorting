import unittest
import numpy as np
import cv2
from vision.object_detector import ObjectDetector
import config

class TestObjectDetector(unittest.TestCase):
    def setUp(self):
        # Neutral gray background (BGR 127,127,127)
        self.bg_color = (127, 127, 127)
        self.blank = np.full((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3), self.bg_color, dtype=np.uint8)
        self.detector = ObjectDetector()

    def test_detect_without_calibration(self):
        result = self.detector.detect(self.blank)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def _draw_square(self, frame, top_left, size, color):
        bottom_right = (top_left[0] + size, top_left[1] + size)
        cv2.rectangle(frame, top_left, bottom_right, color, thickness=-1)
        return (top_left, size)

    def test_detect_red_square(self):
        self.detector.calibrate_background(self.blank)
        frame = self.blank.copy()
        tl, sz = self._draw_square(frame, (100, 100), 50, (0, 0, 255))  # Red BGR
        detections = self.detector.detect(frame)
        self.assertEqual(len(detections), 1)
        (box, mask) = detections[0]
        x, y, w, h = box
        self.assertTrue(abs(x - tl[0]) <= 2)
        self.assertTrue(abs(y - tl[1]) <= 2)
        self.assertTrue(abs(w - sz) <= 4)
        self.assertTrue(abs(h - sz) <= 4)
        self.assertEqual(mask.shape, self.blank.shape[:2])
        self.assertGreater(cv2.countNonZero(mask), 0)
        self.assertTrue(set(np.unique(mask)).issubset({0, 255}))

    def test_detect_multiple_colors(self):
        self.detector.calibrate_background(self.blank)
        frame = self.blank.copy()
        # Red square
        self._draw_square(frame, (50, 50), 40, (0, 0, 255))
        # Blue square
        self._draw_square(frame, (150, 70), 45, (255, 0, 0))
        # Yellow square (BGR 0,255,255)
        self._draw_square(frame, (80, 150), 30, (0, 255, 255))
        # White square
        self._draw_square(frame, (200, 200), 35, (255, 255, 255))
        # Black square (BGR 0,0,0)
        self._draw_square(frame, (300, 300), 38, (0, 0, 0))
        detections = self.detector.detect(frame)
        self.assertEqual(len(detections), 5)
        # Verify masks are distinct and contain only 0/255
        combined = np.zeros(self.blank.shape[:2], dtype=np.uint16)
        for _, mask in detections:
            self.assertEqual(mask.shape, self.blank.shape[:2])
            self.assertTrue(set(np.unique(mask)).issubset({0, 255}))
            combined += mask // 255
        self.assertTrue(np.all(combined <= 1))

    def test_background_without_objects_returns_empty(self):
        self.detector.calibrate_background(self.blank)
        detections = self.detector.detect(self.blank)
        self.assertEqual(len(detections), 0)

    def test_invalid_frame_type(self):
        self.detector.calibrate_background(self.blank)
        with self.assertRaises(ValueError):
            self.detector.detect("not an array")

    def test_mismatched_frame_size(self):
        self.detector.calibrate_background(self.blank)
        smaller = np.full((200, 200, 3), self.bg_color, dtype=np.uint8)
        with self.assertRaises(ValueError):
            self.detector.detect(smaller)

    def test_reject_small_object(self):
        self.detector.calibrate_background(self.blank)
        frame = self.blank.copy()
        cv2.rectangle(frame, (10, 10), (20, 20), (0, 255, 0), thickness=-1)
        detections = self.detector.detect(frame)
        self.assertEqual(len(detections), 0)

    def test_reject_non_square_aspect(self):
        self.detector.calibrate_background(self.blank)
        frame = self.blank.copy()
        cv2.rectangle(frame, (50, 50), (150, 80), (255, 0, 0), thickness=-1)
        detections = self.detector.detect(frame)
        self.assertEqual(len(detections), 0)

if __name__ == "__main__":
    unittest.main()
