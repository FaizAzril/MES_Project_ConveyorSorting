# MES Conveyor Sorting System – Visual Quality Inspection (Computer Vision)

## 📋 Project Overview
The **MES Conveyor Sorting System** is a prototype that performs **real‑time visual quality inspection** of cubes moving on a conveyor belt. A single **top‑view USB webcam** captures each cube, the Python‑based computer‑vision pipeline analyses the image, and the result is sent to an **ESP32** controller over **USB serial**.

- **Target object**: Cubes that should be uniformly **red** on the top face.
- **Classification**:
  - **PERFECT** – red coverage ≥ configurable threshold (default 98 %).
  - **DEFECT** – any deviation (different colour, coloured patches, or non‑red surface).
- **Communication**: Python sends a JSON line to the ESP32; ESP32 replies with an ACK.

> **Note** – The ESP32 firmware (Arduino/PlatformIO) is **not** part of this repository; it will be developed later.

---

## 🗂 Repository Structure
```
MES_Project_ConveyorSorting/
│
├─ config.py                 # Global, user‑editable parameters
├─ requirements.txt          # Python dependencies
├─ README.md                 # **You are here**
│
├─ camera/                   # Camera handling utilities
│   ├─ __init__.py
│   └─ camera_manager.py     # Threaded VideoCapture with graceful shutdown
│
├─ vision/                   # Core CV modules
│   ├─ __init__.py
│   ├─ object_detector.py    # Colour‑agnostic cube detection (background subtraction)
│   ├─ roi_manager.py        # Configurable ROI handling
│   ├─ red_segmentation.py   # HSV red mask (to be implemented)
│   ├─ quality_inspector.py  # Red‑coverage calc & classification (to be implemented)
│   └─ object_tracker.py     # Event‑ID generation & duplicate suppression (to be implemented)
│
├─ communication/            # Serial communication with ESP32
│   ├─ __init__.py
│   └─ serial_client.py      # Non‑blocking JSON‑line protocol (stub)
│
├─ models/                   # Data‑model definitions
│   └─ inspection_event.py   # InspectionEvent dataclass (stub)
│
├─ dataset/                  # Image dataset for future model training
│   ├─ perfect/   (empty – collect with the new tool)
│   └─ defect/    (empty – collect with the new tool)
│
├─ tests/                    # Unit‑test skeletons (future implementation)
│   ├─ __init__.py
│   └─ …
│
├─ K1_MES_CONVEYOR SORTING SYSTEM BERBASIS IoT DAN MES.docx   # Project report (reference)
└─ K1_MES_CONVEYOR SORTING SYSTEM BERBASIS IoT DAN MES.pdf   # Same report in PDF
```

**All legacy scripts (`camera_test.py`, `green_detection.py`, `object_detection.py`, `collect_dataset.py`, `roi_camera.py`) have been removed** because their functionality is now provided by the modular code above.

---

## ⚙️ Installation
1. **Clone the repo** and switch to the development branch:
   ```bash
   git clone https://github.com/FaizAzril/MES_Project_ConveyorSorting.git
   cd MES_Project_ConveyorSorting
   git checkout computer-vision
   ```
2. **Create a virtual environment** (highly recommended on Windows):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1   # PowerShell
   ```
3. **Install required packages**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure the system** – edit `config.py` if you need to change:
   - Camera index (`CAMERA_INDEX`)
   - Resolution (`CAMERA_WIDTH`, `CAMERA_HEIGHT`)
   - ROI ratios
   - HSV red thresholds
   - Serial port (`SERIAL_PORT`) and baudrate
   - Red‑coverage threshold (`RED_COVERAGE_THRESHOLD`)

---

## 🎞 Running the Application (Phase 1 – Core Modules)
The full inspection pipeline will be launched via `main.py` (to be added in a later phase). For now you can test the individual building blocks:

### 1. Camera sanity‑check
```python
from camera.camera_manager import CameraManager

cam = CameraManager()
if cam.start():
    import time
    time.sleep(2)   # grab a couple of frames
    cam.stop()
else:
    print("Unable to open camera – check CAMERA_INDEX in config.py")
```

### 2. Object detection demo
```python
import cv2
from camera.camera_manager import CameraManager
from vision.object_detector import ObjectDetector
from vision.roi_manager import ROIManger

cam = CameraManager()
cam.start()
obj_det = ObjectDetector()

while True:
    frame = cam.get_frame()
    if frame is None:
        continue
    boxes = obj_det.detect(frame)
    for (x, y, w, h) in boxes:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
    cv2.imshow("Detection Demo", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cam.stop()
cv2.destroyAllWindows()
```

When the full pipeline (`red_segmentation`, `quality_inspector`, `object_tracker`, `serial_client`) is ready, a single `python main.py` will perform the complete inspection loop.

---

## 📂 Dataset Collection (Phase 2)
A new dataset collector will store images under `dataset/perfect/` and `dataset/defect/`.
- Press **P** to save the current ROI crop as a **perfect** sample.
- Press **D** to save it as a **defect** sample.
- Press **Q** to quit.
The script will automatically create non‑colliding filenames and display the number of images stored for each class.
*(The collector script will be added in a later commit.)*

---

## 🔌 Serial Communication Protocol (Python ↔ ESP32)
All messages are **single‑line JSON** terminated by a newline (`\n`).
### Outgoing inspection result
```json
{
  "protocol_version": 1,
  "type": "inspection_result",
  "event_id": "OBJ-000001",
  "classification": "PERFECT",
  "red_coverage": 0.995,
  "red_pixels": 9950,
  "object_pixels": 10000,
  "timestamp": "2026-11-20T14:45:00+07:00"
}
```
### Incoming ACK (ESP32 → Python)
```json
{
  "protocol_version": 1,
  "type": "ack",
  "event_id": "OBJ-000001",
  "status": "accepted"
}
```
The Python side will:
1. Queue each inspection result.
2. Send it over the serial port (default `COM3`, 115200 bps).
3. Wait for an ACK (timeout configurable via `SERIAL_TIMEOUT`).
4. Retry up to `SERIAL_MAX_RETRIES` before marking the event as failed.
5. Continue processing frames **without blocking**.

---

## 🧪 Testing
The `tests/` directory contains skeleton unit‑tests that will be fleshed out in future phases:
- `test_red_segmentation.py` – synthetic red/blue/yellow images.
- `test_quality_inspector.py` – verifies red‑coverage calculation and classification.
- `test_event_manager.py` – unique ID generation and duplicate suppression.
- `test_serial_protocol.py` – JSON serialization, ACK parsing, retry logic.
Run them with:
```bash
python -m unittest discover -s tests
```
All current tests pass (they are placeholders).

---

## 🚧 Current Limitations & Next Steps
| Limitation | Planned improvement |
|------------|----------------------|
| No `red_segmentation.py` implementation yet | Add HSV masking, combine two hue ranges, expose configurable thresholds. |
| No quality‑inspection logic | Compute red coverage, apply threshold, return `PERFECT`/`DEFECT`. |
| No event tracking | Generate unique IDs, keep a short‑term history to avoid duplicate events. |
| Serial client is a stub | Implement non‑blocking queue, JSON line protocol, ACK handling, retries. |
| No `main.py` orchestrator | Build a single entry‑point that wires camera → detector → ROI → mask → segmentation → classification → serial. |
| No dataset collector script | Provide a user‑friendly CLI that saves crops into `dataset/perfect/` and `dataset/defect/`. |
| Tests are placeholders | Write synthetic‑image tests for colour detection, coverage, and protocol handling. |

---

## 🤝 Contributing
Feel free to fork, create a feature branch, and submit pull requests. When adding new modules, keep the **separation‑of‑concerns** principle:
- Camera → `camera/`
- Vision → `vision/`
- Communication → `communication/`
- Data models → `models/`

---

## 📜 License
The project is released under the **MIT License** – see the `LICENSE` file for details.

---

*End of README*