# MES Conveyor Sorting – Computer Vision System

A standalone computer-vision quality-inspection system that uses a laptop webcam to inspect cube-shaped objects on a conveyor belt, classifying each object as **PERFECT**, **DEFECT**, or **INVALID**.

> **Scope**: This module covers only the Computer Vision pipeline. IoT, ESP32, Firebase, and serial communication are out of scope for this branch.

---

## Project Structure

```
UAS/
├── camera/
│   ├── __init__.py
│   └── camera_manager.py       # Threaded webcam capture
├── vision/
│   ├── __init__.py
│   ├── background_calibrator.py # Median multi-frame background calibration
│   ├── object_detector.py      # Colour-independent background-subtraction detector
│   ├── quality_inspector.py    # PERFECT / DEFECT / INVALID classifier
│   ├── red_segmentation.py     # HSV two-range red mask
│   ├── roi_manager.py          # ROI crop and coordinate management
│   ├── object_tracker.py       # Single-object state-machine event gate
│   └── inspection_history.py  # In-memory bounded inspection log
├── tests/
│   ├── test_quality_inspector.py  # Phase 1 unit tests (26 tests)
│   ├── test_object_detector.py    # Detector unit tests
│   └── test_integration.py        # End-to-end synthetic pipeline tests
├── config.py                   # All tuneable parameters
├── main.py                     # Application entry point
├── requirements.txt
└── README.md
```

---

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

---

## Configuration (`config.py`)

| Key | Default | Description |
|-----|---------|-------------|
| `CAMERA_INDEX` | `1` | Webcam index (0 = built-in, 1 = first external) |
| `CAMERA_WIDTH` | `640` | Capture width in pixels |
| `CAMERA_HEIGHT` | `480` | Capture height in pixels |
| `ROI_X_START_RATIO` | `0.25` | ROI left edge as fraction of frame width |
| `ROI_X_END_RATIO` | `0.75` | ROI right edge |
| `ROI_Y_START_RATIO` | `0.20` | ROI top edge as fraction of frame height |
| `ROI_Y_END_RATIO` | `0.80` | ROI bottom edge |
| `MIN_OBJECT_AREA` | `800` | Minimum contour area (px²) to be an object |
| `CALIB_FRAME_COUNT` | `30` | Frames captured to build median background |
| `CALIB_DIFF_THRESHOLD` | `30` | Pixel brightness threshold for background subtraction |
| `GATE_CONFIRM_FRAMES` | `5` | Consecutive frames with object before inspection fires |
| `GATE_CLEAR_FRAMES` | `10` | Empty frames before gate resets to READY |

---

## Running the Application

```bash
python main.py
```

**Startup sequence:**

1. Camera opens.
2. Yellow banner prompts you to **keep the conveyor empty**.
3. Application collects `CALIB_FRAME_COUNT` frames and computes a median background.
4. Normal inspection loop begins.

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `Q` or `Esc` | Quit |
| `B` | Recalibrate background (clear conveyor first) |
| `D` | Toggle debug overlay (object mask) |

---

## Background Calibration

Calibration captures `CALIB_FRAME_COUNT` (default 30) frames while the conveyor is empty and computes the **per-pixel median** to build a robust background model. This tolerates minor belt motion and lighting flicker.

Re-calibrate (press **B**) whenever:
- Lighting conditions change significantly.
- The camera is moved.
- Belt texture changes.

---

## Classification Rules

| Classification | Condition |
|----------------|-----------|
| `PERFECT` | All foreground pixels inside the object mask are red (`non_red_pixels == 0`) |
| `DEFECT` | At least one foreground pixel is not red |
| `INVALID` | Input is `None`, empty, wrong type, or object mask is empty |

- Background pixels **outside** the object mask are never counted.
- `object_pixels` = `cv2.countNonZero(mask_bin)` (not bounding-box area).
- `red_pixels` = `cv2.countNonZero(bitwise_and(red_mask, mask_bin))`.

---

## Running Tests

```bash
# All tests (Phase 1 unit + integration)
python -m unittest discover -s tests -v

# Phase 1 quality inspector only
python -m unittest tests.test_quality_inspector -v

# Integration tests only
python -m unittest tests.test_integration -v
```

---

## Camera Selection

If the wrong camera opens, change `CAMERA_INDEX` in `config.py`:
- `0` = built-in webcam
- `1` = first external USB webcam

---

## Limitations

- Inspection only analyses the **top surface** of the cube.
- One cube at a time is supported (single-object gate).
- Classification is based on colour only (red = PERFECT, any other = DEFECT).
- Hardware IoT integration (ESP32, servo, Firebase) is out of scope for this branch.
