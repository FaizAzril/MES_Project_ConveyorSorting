import unittest
import numpy as np
import cv2
from vision.quality_inspector import QualityInspector
from vision.red_segmentation import get_red_mask, count_red_pixels
import config

class TestQualityInspector(unittest.TestCase):
    def setUp(self):
        # neutral gray background (BGR 127,127,127)
        self.bg = (127, 127, 127)
        self.height = config.CAMERA_HEIGHT
        self.width = config.CAMERA_WIDTH
        self.blank = np.full((self.height, self.width, 3), self.bg, dtype=np.uint8)
        self.inspector = QualityInspector()

    def _mask_from_roi(self, roi):
        # Use object detector style mask: zero outside object, 255 inside
        # Simple: threshold non-background pixels
        diff = cv2.absdiff(roi, self.blank)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
        return mask

    # ---------- PERFECT ----------
    def test_perfect_full_red(self):
        roi = np.full((100, 100, 3), (0, 0, 255), dtype=np.uint8)  # red BGR
        mask = np.full((100, 100), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "PERFECT")
        self.assertAlmostEqual(res["red_coverage"], 1.0)

    def test_perfect_98_percent(self):
        # 98% red coverage (threshold is 0.98)
        size = 100
        roi = np.full((size, size, 3), (0,0,255), dtype=np.uint8)
        mask = np.full((size, size), 255, dtype=np.uint8)
        # turn 2% of pixels to blue (2% of area)
        num = int(size*size*0.02)
        # set top-left corner
        roi[:int(np.sqrt(num)), :int(np.sqrt(num))] = (255,0,0)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "PERFECT")
        self.assertGreaterEqual(res["red_coverage"], config.RED_COVERAGE_THRESHOLD)

    # ---------- DEFECT ----------
    def test_defect_blue(self):
        roi = np.full((80,80,3), (255,0,0), dtype=np.uint8)  # blue
        mask = np.full((80,80), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "DEFECT")
        self.assertEqual(res["red_pixels"], 0)

    def test_defect_yellow(self):
        roi = np.full((70,70,3), (0,255,255), dtype=np.uint8)  # yellow BGR
        mask = np.full((70,70), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "DEFECT")
        self.assertEqual(res["red_pixels"], 0)

    def test_defect_white(self):
        roi = np.full((60,60,3), (255,255,255), dtype=np.uint8)  # white
        mask = np.full((60,60), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "DEFECT")
        self.assertEqual(res["red_pixels"], 0)

    def test_defect_black(self):
        roi = np.full((50,50,3), (0,0,0), dtype=np.uint8)  # black
        mask = np.full((50,50), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "DEFECT")
        self.assertEqual(res["red_pixels"], 0)

    def test_defect_red_with_blue_patch(self):
        size = 100
        roi = np.full((size, size, 3), (0,0,255), dtype=np.uint8)  # red
        # add blue patch covering 5% area
        patch = int(size*0.05)
        roi[:patch, :patch] = (255,0,0)
        mask = np.full((size,size), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "DEFECT")
        self.assertLess(res["red_coverage"], config.RED_COVERAGE_THRESHOLD)

    def test_defect_just_below_threshold(self):
        size = 100
        roi = np.full((size, size, 3), (0,0,255), dtype=np.uint8)
        mask = np.full((size,size), 255, dtype=np.uint8)
        # make coverage just below threshold (e.g., 0.979)
        target = config.RED_COVERAGE_THRESHOLD - 0.001
        red_needed = int(size*size*target)
        total = size*size
        non_red = total - red_needed
        # set a block of non‑red pixels
        side = int(np.sqrt(non_red))
        roi[:side, :side] = (255,0,0)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "DEFECT")
        self.assertLess(res["red_coverage"], config.RED_COVERAGE_THRESHOLD)

    # ---------- MASK handling ----------
    def test_mask_0_and_255(self):
        roi = np.full((80,80,3), (0,0,255), dtype=np.uint8)
        mask = np.zeros((80,80), dtype=np.uint8)
        cv2.rectangle(mask, (10,10), (70,70), 255, -1)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["object_pixels"], cv2.countNonZero(mask))
        self.assertEqual(res["classification"], "PERFECT")

    def test_mask_0_and_1(self):
        roi = np.full((80,80,3), (0,0,255), dtype=np.uint8)
        mask = np.zeros((80,80), dtype=np.uint8)
        cv2.rectangle(mask, (20,20), (60,60), 1, -1)  # values 1
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["object_pixels"], cv2.countNonZero(mask))
        self.assertEqual(res["classification"], "PERFECT")

    def test_background_red_not_counted(self):
        # background red outside mask should not affect coverage
        roi = np.full((100,100,3), (0,0,255), dtype=np.uint8)  # all red
        mask = np.zeros((100,100), dtype=np.uint8)
        cv2.rectangle(mask, (30,30), (70,70), 255, -1)
        res = self.inspector.inspect(roi, mask)
        # object_pixels = area of rectangle
        self.assertEqual(res["object_pixels"], (70-30)*(70-30))
        self.assertAlmostEqual(res["red_coverage"], 1.0)
        self.assertEqual(res["classification"], "PERFECT")

    # ---------- INVALID ----------
    def test_invalid_none_roi(self):
        mask = np.full((10,10), 255, dtype=np.uint8)
        res = self.inspector.inspect(None, mask)
        self.assertEqual(res["classification"], "INVALID")

    def test_invalid_empty_roi(self):
        roi = np.array([])
        mask = np.full((1,1), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "INVALID")

    def test_invalid_none_mask(self):
        roi = np.full((10,10,3), (0,0,255), dtype=np.uint8)
        res = self.inspector.inspect(roi, None)
        self.assertEqual(res["classification"], "INVALID")

    def test_invalid_empty_mask(self):
        roi = np.full((10,10,3), (0,0,255), dtype=np.uint8)
        mask = np.array([])
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "INVALID")

    def test_invalid_mismatched_dimensions(self):
        roi = np.full((20,20,3), (0,0,255), dtype=np.uint8)
        mask = np.full((10,10), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "INVALID")

    def test_invalid_wrong_roi_type(self):
        roi = "not an array"
        mask = np.full((10,10), 255, dtype=np.uint8)
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "INVALID")

    def test_invalid_wrong_mask_type(self):
        roi = np.full((10,10,3), (0,0,255), dtype=np.uint8)
        mask = "not an array"
        res = self.inspector.inspect(roi, mask)
        self.assertEqual(res["classification"], "INVALID")

if __name__ == "__main__":
    unittest.main()
