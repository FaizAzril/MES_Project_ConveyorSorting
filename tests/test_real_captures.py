"""Regression test on real webcam captures from the team's conveyor
(camera ~11 cm above the belt, out-of-focus edges, shaded cube sides).

Each fixture is a capture tile saved by vision.pipeline.save_capture:
[object crop | mask overlay] under a 22 px label bar. The expected class is
the file-name prefix (PERFECT__..., DEFECT__...).
"""
import unittest
from pathlib import Path

import cv2
import numpy as np

from vision.quality_inspector import QualityInspector

FIXTURES = Path(__file__).parent / "fixtures" / "real"


def load_capture(path):
    tile = cv2.imread(str(path))[22:]
    used = np.where(tile.max(axis=0).max(axis=1) > 0)[0].max() + 1
    width = used // 2
    obj = tile[:, :width]
    mask = (tile[:, width:2 * width].max(axis=2) > 60).astype(np.uint8) * 255
    return obj, mask


class TestRealCaptures(unittest.TestCase):
    def test_real_objects(self):
        files = sorted(FIXTURES.glob("*.jpg"))
        self.assertGreaterEqual(len(files), 6)
        inspector = QualityInspector()
        for path in files:
            expected = path.name.split("__")[0]
            with self.subTest(fixture=path.name):
                result = inspector.inspect(*load_capture(path))
                self.assertEqual(result["classification"], expected, result)


if __name__ == "__main__":
    unittest.main()
