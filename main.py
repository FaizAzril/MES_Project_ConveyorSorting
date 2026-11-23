"""MES Conveyor Sorting - Computer Vision + optional ESP32 SG90 Serial link.

Run from the UAS repository root:
    python main.py

Keyboard shortcuts:
    Q / Esc : quit
    B       : recalibrate background (conveyor must be empty)
    D       : toggle debug mask overlay

The Python application performs image inspection only. It sends valid
PERFECT/DEFECT events to ESP32 over USB Serial when SERIAL_ENABLED=True.
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
from vision.object_tracker import EventGate, READY, WAIT_CLEAR
from vision.inspection_history import InspectionHistory

try:
    from communication.serial_client import SerialClient
except ImportError:
    SerialClient = None

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_logger = logging.getLogger("main")

CLR_PERFECT = (0, 220, 0)
CLR_DEFECT = (0, 0, 220)
CLR_WAIT = (0, 220, 220)
CLR_GRAY = (160, 160, 160)
CLR_WHITE = (255, 255, 255)
CLR_BLACK = (0, 0, 0)
WINDOW = "MES CV - SG90 Conveyor Sorting"


def put_text(img, text, pos, color=CLR_WHITE, scale=0.52, thickness=1):
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, CLR_BLACK, thickness + 2)
    cv2.putText(img, text, pos, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)


def draw_overlay(frame, roi_mgr, gate, last_result, last_event_id,
                 calib, debug, detected, serial_state, serial_enabled):
    roi_color = CLR_WAIT if (not calib.calibrated or detected) else CLR_GRAY
    roi_mgr.draw(frame, color=roi_color)

    if not calib.calibrated:
        pct = int(calib.progress * 100)
        put_text(frame, f"CALIBRATING {pct}% - keep conveyor empty", (10, 24), CLR_WAIT)
    else:
        state_color = CLR_WAIT if gate.state in (READY, WAIT_CLEAR) else CLR_PERFECT
        put_text(frame, f"CALIB: OK | GATE: {gate.state}", (10, 24), state_color)

    if last_result:
        cls = last_result.get("classification", "")
        color = CLR_PERFECT if cls == "PERFECT" else CLR_DEFECT if cls == "DEFECT" else CLR_WAIT
        put_text(frame, f"[{last_event_id}] {cls}", (10, 52), color, scale=0.72, thickness=2)
        put_text(
            frame,
            f"Coverage: {last_result.get('red_coverage', 0):.2%} | "
            f"Red: {last_result.get('red_pixels', 0)} | "
            f"Object: {last_result.get('object_pixels', 0)} | "
            f"Non-red: {last_result.get('non_red_pixels', 0)}",
            (10, 76), CLR_WHITE, scale=0.44,
        )
    else:
        put_text(frame, "Waiting for cube in inspection ROI...", (10, 52), CLR_GRAY)

    if not serial_enabled:
        serial_text = "ESP32: CV-ONLY MODE (SERIAL DISABLED)"
        serial_color = CLR_GRAY
    else:
        serial_text = f"ESP32: {'CONNECTED' if serial_state['connected'] else 'DISCONNECTED'}"
        serial_text += f" | ACK: {serial_state['ack']} | SORT: {serial_state['sorting']}"
        serial_color = CLR_PERFECT if serial_state["connected"] else CLR_WAIT
    put_text(frame, serial_text, (10, 102), serial_color, scale=0.43)

    if serial_state.get("message"):
        put_text(frame, serial_state["message"][:90], (10, 124), CLR_WAIT, scale=0.40)

    footer = "Q: Quit | B: Recalibrate | D: Debug"
    put_text(frame, footer, (10, frame.shape[0] - 12), CLR_GRAY, scale=0.42)

    if debug:
        put_text(frame, "DEBUG MODE", (frame.shape[1] - 145, 24), CLR_WAIT, scale=0.45)


def run_calibration(cam, calib, roi_mgr, detector):
    """Collect calibration frames while the conveyor is empty."""
    calib.reset()
    frames_for_detector = []
    _logger.info("Background calibration started. Keep conveyor empty.")
    while not calib.calibrated:
        frame = cam.get_frame()
        if frame is None:
            cv2.waitKey(10)
            continue
        display = frame.copy()
        roi_mgr.draw(display, color=CLR_WAIT)
        put_text(display, f"CALIBRATING {int(calib.progress * 100)}% - keep conveyor empty", (10, 28), CLR_WAIT)
        cv2.imshow(WINDOW, display)
        key = cv2.waitKey(20) & 0xFF
        if key in (ord("q"), 27):
            return False
        roi_frame = roi_mgr.get_roi(frame).copy()
        calib.add_frame(roi_frame)
        frames_for_detector.append(roi_frame)
    detector.calibrate_from_frames(frames_for_detector)
    _logger.info("Background calibration completed.")
    return True


def drain_serial_events(client, state):
    if client is None:
        return
    for event in client.get_events():
        kind = event.get("kind")
        if kind == "connection":
            state["connected"] = bool(event.get("connected"))
            state["message"] = event.get("message", "")
        elif kind == "connection_error":
            state["connected"] = False
            state["message"] = f"COM reconnect: {event.get('message', '')}"
        elif kind == "queued":
            state["message"] = f"Queued {event.get('event_id')} for ESP32"
        elif kind == "sent":
            state["message"] = f"Sent {event.get('event_id')} (attempt {event.get('attempt')})"
        elif kind == "ack":
            state["ack"] = event.get("status", "unknown").upper()
            state["message"] = f"ACK {event.get('event_id')}: {event.get('status')}"
        elif kind == "sorting_result":
            state["sorting"] = event.get("sorting_action", "UNKNOWN").upper()
            state["ack"] = "COMPLETED"
            state["message"] = f"Sorting completed: {event.get('event_id')}"
        elif kind == "device_error":
            state["ack"] = "DEVICE ERROR"
            state["message"] = event.get("message", "ESP32 error")
        elif kind in ("send_failed", "sorting_timeout", "serial_error", "error"):
            state["ack"] = "FAILED"
            state["message"] = event.get("message", kind)
        elif kind == "unknown_message":
            state["message"] = "Ignored unknown ESP32 message"


def main():
    cam = CameraManager()
    serial_client = None
    serial_state = {
        "connected": False,
        "ack": "WAITING",
        "sorting": "-",
        "message": "",
    }
    serial_enabled = bool(getattr(config, "SERIAL_ENABLED", False))

    if serial_enabled:
        if SerialClient is None:
            _logger.error("SerialClient import failed. Install pyserial and check communication/serial_client.py")
            serial_state["message"] = "Serial module unavailable; CV can still run"
        else:
            serial_client = SerialClient(
                port=config.SERIAL_PORT,
                baudrate=config.SERIAL_BAUDRATE,
                read_timeout=config.SERIAL_TIMEOUT,
                ack_timeout=config.SERIAL_ACK_TIMEOUT,
                result_timeout=config.SERIAL_RESULT_TIMEOUT,
                max_retries=config.SERIAL_MAX_RETRIES,
                retry_delay=config.SERIAL_RETRY_DELAY,
                reconnect_delay=config.SERIAL_RECONNECT_DELAY,
                reset_delay=config.SERIAL_RESET_DELAY,
            )
            serial_client.start()

    if not cam.start():
        _logger.error("Cannot open webcam. Check CAMERA_INDEX in config.py.")
        if serial_client:
            serial_client.close()
        print("ERROR: Camera unavailable. Update CAMERA_INDEX in config.py and retry.")
        return 1

    try:
        frame = None
        for _ in range(50):
            frame = cam.get_frame()
            if frame is not None:
                break
            cv2.waitKey(50)
        if frame is None:
            _logger.error("No frame received from webcam.")
            return 1

        height, width = frame.shape[:2]
        roi_mgr = ROIManager(width, height)
        calib = BackgroundCalibrator()
        detector = ObjectDetector()
        inspector = QualityInspector()
        gate = EventGate()
        history = InspectionHistory()

        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        debug = False
        last_result = None
        last_event_id = ""

        if not run_calibration(cam, calib, roi_mgr, detector):
            return 0

        while True:
            drain_serial_events(serial_client, serial_state)
            frame = cam.get_frame()
            if frame is None:
                cv2.waitKey(10)
                continue

            display = frame.copy()
            roi_img = roi_mgr.get_roi(frame)
            detections = detector.detect(roi_img)

            best_box = None
            best_mask = None
            best_area = 0
            for roi_box, roi_mask in detections:
                full_box = roi_mgr.abs_box(roi_box)
                area = int(roi_box[2]) * int(roi_box[3])
                if roi_mgr.is_fully_inside_roi(full_box) and area > best_area:
                    best_box = full_box
                    best_area = area
                    full_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                    full_mask[roi_mgr.y1:roi_mgr.y2, roi_mgr.x1:roi_mgr.x2] = roi_mask
                    best_mask = full_mask

            detected = best_box is not None
            if best_box is not None:
                x, y, w, h = best_box
                box_color = CLR_WAIT
                if last_result:
                    box_color = CLR_PERFECT if last_result.get("classification") == "PERFECT" else CLR_DEFECT
                cv2.rectangle(display, (x, y), (x + w, y + h), box_color, 2)
                if debug and best_mask is not None:
                    mask_crop = best_mask[y:y+h, x:x+w]
                    if mask_crop.size:
                        overlay = display[y:y+h, x:x+w]
                        green = np.zeros_like(overlay)
                        green[:, :, 1] = mask_crop
                        display[y:y+h, x:x+w] = cv2.addWeighted(overlay, 1.0, green, 0.25, 0)

            allow_new_event = serial_client is None or not serial_client.has_active_event
            event_id = gate.update(detected, allow_new_event=allow_new_event)

            if event_id and best_box is not None and best_mask is not None:
                obj_roi, obj_mask = roi_mgr.crop_object_with_mask(frame, best_box, best_mask)
                result = inspector.inspect(obj_roi, obj_mask)
                history_record = history.add(event_id, result)
                last_result = result
                last_event_id = event_id

                if serial_client is not None and result.get("classification") in ("PERFECT", "DEFECT"):
                    queued = serial_client.send_inspection(history_record)
                    serial_state["ack"] = "QUEUED" if queued else "NOT QUEUED"
                    serial_state["sorting"] = "WAITING" if queued else serial_state["sorting"]
                    if not queued:
                        serial_state["message"] = "Inspection event was not queued; check metrics/event ID"
                elif serial_client is None:
                    serial_state["ack"] = "CV ONLY"
                else:
                    serial_state["ack"] = "INVALID - NOT SENT"

                gate.mark_inspection_done()
                _logger.info(
                    "Inspection %s: %s (coverage=%.4f, red=%d, object=%d)",
                    event_id, result.get("classification"), result.get("red_coverage", 0),
                    result.get("red_pixels", 0), result.get("object_pixels", 0),
                )

            draw_overlay(
                display, roi_mgr, gate, last_result, last_event_id,
                calib, debug, detected, serial_state, serial_enabled,
            )
            cv2.imshow(WINDOW, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("b"):
                if serial_client is not None and serial_client.has_active_event:
                    serial_state["message"] = "Cannot recalibrate while ESP32 has an active sorting event"
                else:
                    gate.reset()
                    last_result = None
                    last_event_id = ""
                    if not run_calibration(cam, calib, roi_mgr, detector):
                        break
            elif key == ord("d"):
                debug = not debug

        _logger.info("CV application stopped. Inspection records in memory: %d", len(history))
        return 0

    finally:
        if serial_client is not None:
            serial_client.close()
        cam.stop()
        cv2.destroyAllWindows()
        _logger.info("Application resources released.")


if __name__ == "__main__":
    raise SystemExit(main())
