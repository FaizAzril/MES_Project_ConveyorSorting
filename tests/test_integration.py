"""Integration tests for the full CV pipeline using synthetic frames.

No physical webcam required. All frames are generated programmatically.
Phase 1 unit tests are NOT touched by this file.
"""
import unittest
import numpy as np
import cv2
import config
from vision.background_calibrator import BackgroundCalibrator
from vision.object_detector import ObjectDetector
from vision.roi_manager import ROIManager
from vision.quality_inspector import QualityInspector
from vision.object_tracker import EventGate, READY, OBJECT_DETECTED, INSPECTION_COMPLETED
from vision.inspection_history import InspectionHistory

W = config.CAMERA_WIDTH
H = config.CAMERA_HEIGHT
BG_COLOR = (90, 90, 90)  # dark gray conveyor


def _make_bg():
    return np.full((H, W, 3), BG_COLOR, dtype=np.uint8)


def _make_frame_with_cube(color, top_left=(220, 160), size=80):
    frame = _make_bg()
    tl = top_left
    br = (tl[0] + size, tl[1] + size)
    cv2.rectangle(frame, tl, br, color, thickness=-1)
    return frame


def _run_pipeline(cube_color, top_left=(220, 160), size=80):
    """Helper: calibrate background, place cube, detect + inspect."""
    roi_mgr = ROIManager(W, H)
    bg_frames = [roi_mgr.get_roi(_make_bg()) for _ in range(config.CALIB_FRAME_COUNT)]
    detector = ObjectDetector()
    detector.calibrate_from_frames(bg_frames)

    inspector = QualityInspector()

    cube_frame = _make_frame_with_cube(cube_color, top_left, size)
    roi_img = roi_mgr.get_roi(cube_frame)
    detections = detector.detect(roi_img)
    return detections, roi_img, inspector, roi_mgr, cube_frame


class TestBackgroundCalibration(unittest.TestCase):
    def test_calibration_produces_background(self):
        calib = BackgroundCalibrator()
        self.assertFalse(calib.calibrated)
        for _ in range(config.CALIB_FRAME_COUNT):
            done = calib.add_frame(_make_bg())
        self.assertTrue(done)
        self.assertTrue(calib.calibrated)
        self.assertIsNotNone(calib.background)

    def test_calibration_progress(self):
        calib = BackgroundCalibrator()
        for i in range(config.CALIB_FRAME_COUNT // 2):
            calib.add_frame(_make_bg())
        self.assertAlmostEqual(calib.progress, 0.5, delta=0.05)

    def test_reset(self):
        calib = BackgroundCalibrator()
        calib.add_frame(_make_bg())
        calib.reset()
        self.assertFalse(calib.calibrated)
        self.assertEqual(calib.progress, 0.0)


class TestPipelineDetection(unittest.TestCase):
    def _calibrate_detector(self):
        d = ObjectDetector()
        roi_mgr = self._roi()
        d.calibrate_from_frames([roi_mgr.get_roi(_make_bg()) for _ in range(config.CALIB_FRAME_COUNT)])
        return d

    def _roi(self):
        return ROIManager(W, H)

    def test_empty_frame_no_detection(self):
        d = self._calibrate_detector()
        roi_mgr = self._roi()
        roi = roi_mgr.get_roi(_make_bg())
        self.assertEqual(d.detect(roi), [])

    def _detect_color(self, color, tl=(220, 160), size=80):
        d = self._calibrate_detector()
        roi_mgr = self._roi()
        frame = _make_frame_with_cube(color, tl, size)
        roi = roi_mgr.get_roi(frame)
        return d.detect(roi)

    def test_detect_red_cube(self):
        dets = self._detect_color((0, 0, 255))
        self.assertEqual(len(dets), 1)

    def test_detect_blue_cube(self):
        dets = self._detect_color((255, 0, 0))
        self.assertEqual(len(dets), 1)

    def test_detect_yellow_cube(self):
        dets = self._detect_color((0, 255, 255))
        self.assertEqual(len(dets), 1)

    def test_detect_white_cube(self):
        dets = self._detect_color((255, 255, 255))
        self.assertEqual(len(dets), 1)

    def test_detect_black_cube(self):
        dets = self._detect_color((0, 0, 0))
        self.assertEqual(len(dets), 1)


class TestPipelineInspection(unittest.TestCase):
    def _full_pipeline(self, color, tl=(220, 160), size=80):
        detections, roi_img, inspector, roi_mgr, full_frame = _run_pipeline(color, tl, size)
        self.assertEqual(len(detections), 1, f"Expected 1 detection for color {color}, got {len(detections)}")
        roi_box, roi_mask = detections[0]
        full_box = roi_mgr.abs_box(roi_box)
        obj_roi, obj_mask = roi_mgr.crop_object_with_mask(full_frame, full_box, 
            _mask_to_full(roi_mask, roi_mgr, full_frame.shape[:2]))
        return inspector.inspect(obj_roi, obj_mask)

    def test_red_cube_perfect(self):
        res = self._full_pipeline((0, 0, 255))
        self.assertEqual(res["classification"], "PERFECT")
        self.assertAlmostEqual(res["red_coverage"], 1.0, delta=0.01)

    def test_blue_cube_defect(self):
        res = self._full_pipeline((255, 0, 0))
        self.assertEqual(res["classification"], "DEFECT")
        self.assertEqual(res["red_pixels"], 0)

    def test_yellow_cube_defect(self):
        res = self._full_pipeline((0, 255, 255))
        self.assertEqual(res["classification"], "DEFECT")

    def test_white_cube_defect(self):
        res = self._full_pipeline((255, 255, 255))
        self.assertEqual(res["classification"], "DEFECT")

    def test_black_cube_defect(self):
        res = self._full_pipeline((0, 0, 0))
        self.assertEqual(res["classification"], "DEFECT")

    def test_red_with_blue_patch_defect(self):
        # 80x80 red cube with a 10x10 blue patch
        frame = _make_frame_with_cube((0, 0, 255), (220, 160), 80)
        cv2.rectangle(frame, (225, 165), (235, 175), (255, 0, 0), thickness=-1)

        roi_mgr = ROIManager(W, H)
        d = ObjectDetector()
        d.calibrate_from_frames([roi_mgr.get_roi(_make_bg()) for _ in range(config.CALIB_FRAME_COUNT)])
        inspector = QualityInspector()

        roi = roi_mgr.get_roi(frame)
        dets = d.detect(roi)
        self.assertEqual(len(dets), 1)
        roi_box, roi_mask = dets[0]
        full_box = roi_mgr.abs_box(roi_box)
        full_mask = _mask_to_full(roi_mask, roi_mgr, frame.shape[:2])
        obj_roi, obj_mask = roi_mgr.crop_object_with_mask(frame, full_box, full_mask)
        res = inspector.inspect(obj_roi, obj_mask)
        self.assertEqual(res["classification"], "DEFECT")

    def test_red_with_yellow_patch_defect(self):
        frame = _make_frame_with_cube((0, 0, 255), (220, 160), 80)
        cv2.rectangle(frame, (225, 165), (235, 175), (0, 255, 255), thickness=-1)

        roi_mgr = ROIManager(W, H)
        d = ObjectDetector()
        d.calibrate_from_frames([roi_mgr.get_roi(_make_bg()) for _ in range(config.CALIB_FRAME_COUNT)])
        inspector = QualityInspector()

        roi = roi_mgr.get_roi(frame)
        dets = d.detect(roi)
        self.assertEqual(len(dets), 1)
        roi_box, roi_mask = dets[0]
        full_box = roi_mgr.abs_box(roi_box)
        full_mask = _mask_to_full(roi_mask, roi_mgr, frame.shape[:2])
        obj_roi, obj_mask = roi_mgr.crop_object_with_mask(frame, full_box, full_mask)
        res = inspector.inspect(obj_roi, obj_mask)
        self.assertEqual(res["classification"], "DEFECT")


def _mask_to_full(roi_mask, roi_mgr, full_shape):
    full = np.zeros(full_shape, dtype=np.uint8)
    full[roi_mgr.y1:roi_mgr.y2, roi_mgr.x1:roi_mgr.x2] = roi_mask
    return full


class TestEventGate(unittest.TestCase):
    def test_no_fire_before_confirm_frames(self):
        gate = EventGate()
        for _ in range(config.GATE_CONFIRM_FRAMES - 1):
            result = gate.update(True)
            self.assertIsNone(result)

    def test_fires_after_confirm_frames(self):
        gate = EventGate()
        result = None
        for _ in range(config.GATE_CONFIRM_FRAMES):
            result = gate.update(True)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith(config.EVENT_ID_PREFIX))

    def test_no_duplicate_events(self):
        gate = EventGate()
        events = []
        # Simulate one object present for many frames
        for _ in range(config.GATE_CONFIRM_FRAMES + 10):
            r = gate.update(True)
            if r:
                events.append(r)
        # Only one event should fire
        self.assertEqual(len(events), 1)

    def test_reset_after_clear(self):
        gate = EventGate()
        # Fire first event
        for _ in range(config.GATE_CONFIRM_FRAMES):
            gate.update(True)
        gate.mark_inspection_done()
        # Object disappears
        for _ in range(config.GATE_CLEAR_FRAMES + 2):
            gate.update(False)
        self.assertEqual(gate.state, READY)

    def test_second_object_fires_new_event(self):
        gate = EventGate()
        # First object
        for _ in range(config.GATE_CONFIRM_FRAMES):
            gate.update(True)
        gate.mark_inspection_done()
        # Clear
        for _ in range(config.GATE_CLEAR_FRAMES + 2):
            gate.update(False)
        # Second object
        result = None
        for _ in range(config.GATE_CONFIRM_FRAMES):
            result = gate.update(True)
        self.assertIsNotNone(result)

    def test_unique_event_ids(self):
        gate = EventGate()
        ids = set()
        for obj in range(3):
            for _ in range(config.GATE_CONFIRM_FRAMES):
                r = gate.update(True)
                if r:
                    ids.add(r)
            gate.mark_inspection_done()
            for _ in range(config.GATE_CLEAR_FRAMES + 2):
                gate.update(False)
        self.assertEqual(len(ids), 3)


class TestInspectionHistory(unittest.TestCase):
    def test_add_and_retrieve(self):
        h = InspectionHistory()
        result = {"classification": "PERFECT", "red_pixels": 100, "object_pixels": 100,
                  "non_red_pixels": 0, "red_coverage": 1.0}
        h.add("OBJ-000001", result)
        self.assertEqual(len(h), 1)
        latest = h.latest(1)
        self.assertEqual(latest[0]["classification"], "PERFECT")

    def test_bounded_size(self):
        h = InspectionHistory()
        result = {"classification": "DEFECT", "red_pixels": 0, "object_pixels": 100,
                  "non_red_pixels": 100, "red_coverage": 0.0}
        for i in range(config.HISTORY_MAX_SIZE + 20):
            h.add(f"OBJ-{i:06d}", result)
        self.assertLessEqual(len(h), config.HISTORY_MAX_SIZE)


class TestROIManager(unittest.TestCase):
    def test_abs_box(self):
        roi_mgr = ROIManager(W, H)
        roi_box = (10, 20, 50, 50)
        abs_box = roi_mgr.abs_box(roi_box)
        self.assertEqual(abs_box[0], 10 + roi_mgr.x1)
        self.assertEqual(abs_box[1], 20 + roi_mgr.y1)

    def test_fully_inside_roi(self):
        roi_mgr = ROIManager(W, H)
        # A box well inside ROI
        x = roi_mgr.x1 + 50
        y = roi_mgr.y1 + 50
        box = (x, y, 60, 60)
        self.assertTrue(roi_mgr.is_fully_inside_roi(box))

    def test_not_fully_inside_roi(self):
        roi_mgr = ROIManager(W, H)
        # A box that starts at ROI edge
        box = (roi_mgr.x1, roi_mgr.y1, 60, 60)
        self.assertFalse(roi_mgr.is_fully_inside_roi(box))


if __name__ == "__main__":
    unittest.main()
