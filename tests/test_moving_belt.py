"""Running belt: a cube crosses the camera view at belt speed and must be
inspected exactly once, with the right result.

Camera 11 cm above the belt: ~45 px per cm, 30 fps.
"""
import unittest

import cv2
import numpy as np

import config
from vision.pipeline import InspectionPipeline

W, H = config.CAMERA_WIDTH, config.CAMERA_HEIGHT
BELT = (148, 166, 101)
PX_PER_CM = 45
FPS = 30


def belt_frame(rng):
    frame = np.full((H, W, 3), BELT, np.uint8)
    return np.clip(frame.astype(int) + rng.normal(0, 3, frame.shape), 0, 255).astype(np.uint8)


def run_belt(speed_cm_s, color=(40, 40, 210), cube_cm=3, spot=False):
    """Feed frames of one cube travelling left -> right; return the records."""
    rng = np.random.default_rng(0)
    records = []
    pipe = InspectionPipeline(on_record=records.append)
    for _ in range(config.CALIB_WARMUP_FRAMES + config.CALIB_FRAME_COUNT + 1):
        pipe._process(belt_frame(rng))
    size = int(cube_cm * PX_PER_CM)
    step = speed_cm_s * PX_PER_CM / FPS               # px per frame
    blur = max(1, int(step * 0.5))                    # motion blur ~ half a frame of travel
    y = H // 2 - size // 2
    x = -size
    while x < W + size:
        frame = belt_frame(rng)
        x0 = int(x)
        cv2.rectangle(frame, (x0, y), (x0 + size, y + size), color, -1)
        if spot:
            cv2.circle(frame, (x0 + size // 2, y + size // 2), 12, (20, 20, 20), -1)
        frame = cv2.blur(frame, (blur, 1))
        pipe._process(frame)
        x += step
    for _ in range(config.GATE_CLEAR_FRAMES + 2):       # belt empty again
        pipe._process(belt_frame(rng))
    return records


class TestMovingBelt(unittest.TestCase):
    def test_red_cube_at_belt_speeds(self):
        for speed in (5, 10, 20, 30):
            with self.subTest(speed_cm_s=speed):
                records = run_belt(speed)
                self.assertEqual(len(records), 1, f"{speed} cm/s: {len(records)} inspections")
                self.assertEqual(records[0]["classification"], "PERFECT", records[0])

    def test_dark_blue_cube_running_belt(self):
        records = run_belt(20, color=(100, 45, 25))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["classification"], "DEFECT")

    def test_red_cube_with_spot_running_belt(self):
        records = run_belt(20, spot=True)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["classification"], "DEFECT")

    def test_small_cube_fast_belt(self):
        records = run_belt(30, cube_cm=2)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["classification"], "PERFECT")


if __name__ == "__main__":
    unittest.main()
