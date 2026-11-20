"""MES Conveyor Sorting – Computer Vision Main Application.

Usage:
    python main.py

Keyboard shortcuts:
    Q  – quit
    B  – recalibrate background
    D  – toggle debug overlay
"""
import logging
import sys
import cv2
import numpy as np
import config
from camera.camera_manager import CameraManager
from vision.background_calibrator import BackgroundCalibrator
from vision.roi_manager import ROIManager
from vision.object_detector import ObjectDetector
from vision.quality_inspector import QualityInspector
from vision.object_tracker import EventGate, READY, OBJECT_DETECTED, INSPECTION_COMPLETED, WAIT_CLEAR
from vision.inspection_history import InspectionHistory

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_logger = logging.getLogger("main")

# ── Colour constants (BGR) ─────────────────────────────────────────────────
CLR_PERFECT = (0, 220, 0)
CLR_DEFECT  = (0, 0, 220)
CLR_WAIT    = (0, 220, 220)
CLR_GRAY    = (160, 160, 160)
CLR_WHITE   = (255, 255, 255)
CLR_BLACK   = (0, 0, 0)

WINDOW = "MES CV – Quality Inspection"


def put_text(img, text, pos, color=CLR_WHITE, scale=0.55, thickness=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, CLR_BLACK, thickness + 2)
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)


def draw_overlay(frame, roi_mgr, gate, last_result, last_event_id, calib, debug, detected):
    # ROI border
    roi_color = CLR_WAIT if not calib.calibrated else (CLR_WAIT if detected else CLR_GRAY)
    roi_mgr.draw(frame, color=roi_color)

    # Calibration & Gate status banner
    if not calib.calibrated:
        pct = int(calib.progress * 100)
        put_text(frame, f"CALIBRATING... {pct}%  (keep conveyor empty)", (10, 25), CLR_WAIT)
    else:
        state_color = CLR_WAIT if gate.state in (READY, WAIT_CLEAR) else CLR_PERFECT
        put_text(frame, f"Calib: OK | Gate: {gate.state} | Event: {gate.event_id or '-'}", (10, 25), state_color)

    # Inspection metrics
    if last_result:
        cls = last_result.get("classification", "")
        clr = CLR_PERFECT if cls == "PERFECT" else CLR_DEFECT
        put_text(frame, f"[{last_event_id}] {cls}", (10, 52), clr, scale=0.75, thickness=2)
        put_text(frame, (
            f"Coverage: {last_result['red_coverage']:.1%} | "
            f"Red: {last_result['red_pixels']} | "
            f"Obj: {last_result['object_pixels']} | "
            f"Non-Red: {last_result['non_red_pixels']}"
        ), (10, 75), CLR_WHITE, scale=0.48)
    else:
        put_text(frame, "Waiting for cube in ROI...", (10, 52), CLR_GRAY, scale=0.55)

    if debug:
        put_text(frame, "DEBUG MODE (Mask visible) | Q: Quit | B: Recalibrate | D: Toggle Debug", (10, frame.shape[0] - 12), CLR_WAIT, scale=0.42)
    else:
        put_text(frame, "Q: Quit | B: Recalibrate | D: Toggle Debug", (10, frame.shape[0] - 12), CLR_GRAY, scale=0.42)


def run_calibration(cam, calib, roi_mgr, detector):
    """Blocking calibration loop – returns when calibration is done."""
    calib.reset()
    _logger.info("Starting background calibration. Keep conveyor empty.")
    frames_for_detector = []
    while not calib.calibrated:
        frame = cam.get_frame()
        if frame is None:
            continue
        display = frame.copy()
        pct = int(calib.progress * 100)
        put_text(display, f"CALIBRATING {pct}% – keep conveyor empty (B to cancel)", (10, 30), CLR_WAIT)
        roi_mgr.draw(display, color=CLR_WAIT)
        cv2.imshow(WINDOW, display)
        key = cv2.waitKey(30) & 0xFF
        if key in (ord('q'), 27):
            return False  # user quit during calibration
        roi_frame = roi_mgr.get_roi(frame)
        calib.add_frame(roi_frame)
        frames_for_detector.append(roi_frame)
    # Feed median to detector
    detector.calibrate_from_frames(frames_for_detector)
    _logger.info("Calibration complete.")
    return True


def main():
    cam = CameraManager()
    if not cam.start():
        _logger.error("Cannot open webcam. Check CAMERA_INDEX in config.py.")
        print("ERROR: Camera unavailable. Update CAMERA_INDEX in config.py and retry.")
        sys.exit(1)

    # Wait for first frame to determine resolution
    frame = None
    for _ in range(50):
        frame = cam.get_frame()
        if frame is not None:
            break
        cv2.waitKey(50)
    if frame is None:
        _logger.error("No frame received from camera.")
        cam.stop()
        sys.exit(1)

    h, w = frame.shape[:2]
    roi_mgr  = ROIManager(w, h)
    calib    = BackgroundCalibrator()
    detector = ObjectDetector()
    inspector = QualityInspector()
    gate     = EventGate()
    history  = InspectionHistory()

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)

    debug       = False
    last_result = None
    last_event_id = ""

    # ── Initial calibration ────────────────────────────────────────────────
    if not run_calibration(cam, calib, roi_mgr, detector):
        cam.stop()
        cv2.destroyAllWindows()
        return

    # ── Main loop ──────────────────────────────────────────────────────────
    while True:
        frame = cam.get_frame()
        if frame is None:
            cv2.waitKey(10)
            continue

        display = frame.copy()
        roi_img = roi_mgr.get_roi(frame)

        # Detect objects inside ROI
        detections = detector.detect(roi_img)

        # Find the largest valid detection that is fully inside ROI
        best_box = None
        best_mask = None
        for roi_box, roi_mask in detections:
            full_box = roi_mgr.abs_box(roi_box)
            if roi_mgr.is_fully_inside_roi(full_box):
                if best_box is None or (roi_box[2] * roi_box[3] > best_box[2] * best_box[3]):
                    best_box = full_box
                    # Translate mask from roi space to full frame space
                    full_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                    full_mask[roi_mgr.y1:roi_mgr.y2, roi_mgr.x1:roi_mgr.x2] = roi_mask
                    best_mask = full_mask

        detected = best_box is not None

        # Draw bounding box
        if best_box is not None:
            bx, by, bw, bh = best_box
            clr = CLR_WAIT if gate.state in (READY, WAIT_CLEAR) else CLR_PERFECT if (last_result and last_result.get("classification") == "PERFECT") else CLR_DEFECT
            cv2.rectangle(display, (bx, by), (bx+bw, by+bh), clr, 2)
            if debug and best_mask is not None:
                mask_overlay = cv2.merge([np.zeros_like(best_mask), best_mask // 2, np.zeros_like(best_mask)])
                display = cv2.addWeighted(display, 1.0, mask_overlay, 0.4, 0)

        # Event gate
        event_id = gate.update(detected)
        if event_id and best_box is not None and best_mask is not None:
            obj_roi, obj_mask = roi_mgr.crop_object_with_mask(frame, best_box, best_mask)
            result = inspector.inspect(obj_roi, obj_mask)
            history.add(event_id, result)
            last_result = result
            last_event_id = event_id
            gate.mark_inspection_done()
            _logger.info("Inspection %s: %s (coverage=%.3f)", event_id, result["classification"], result["red_coverage"])

        draw_overlay(display, roi_mgr, gate, last_result, last_event_id, calib, debug, detected)
        cv2.imshow(WINDOW, display)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord('q'), 27):
            break
        elif key == ord('b'):
            gate.reset()
            last_result = None
            last_event_id = ""
            if not run_calibration(cam, calib, roi_mgr, detector):
                break
        elif key == ord('d'):
            debug = not debug

    cam.stop()
    cv2.destroyAllWindows()
    _logger.info("Application shut down cleanly.")


if __name__ == "__main__":
    main()
