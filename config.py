"""Configuration for the MES Conveyor Sorting System.

Architecture: webcam -> Python computer vision -> Firebase Realtime Database
-> ESP32 + SG90 servo, with the web dashboard (and its live camera feed)
served by the same Python process.
"""

# ── Camera ────────────────────────────────────────────────────────────────
CAMERA_INDEX = 1  # 0 = built-in webcam; 1 = first external webcam
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_BACKEND = "CAP_DSHOW"  # Windows DirectShow; set None to use OpenCV default
AUTO_START_CAMERA = True      # start camera + calibration when main.py launches

# ── ROI (relative fractions of the frame) ────────────────────────────────
ROI_X_START_RATIO = 0.25
ROI_X_END_RATIO = 0.75
ROI_Y_START_RATIO = 0.20
ROI_Y_END_RATIO = 0.80

# ── Object detection ──────────────────────────────────────────────────────
MIN_OBJECT_AREA = 800
MAX_OBJECT_AREA = 50000
ASPECT_RATIO_TOLERANCE = 0.3

# ── Red colour (HSV, OpenCV hue range 0..179) ────────────────────────────
LOWER_RED1 = (0, 80, 50)
UPPER_RED1 = (10, 255, 255)
LOWER_RED2 = (170, 80, 50)
UPPER_RED2 = (179, 255, 255)

# ── Quality rule ──────────────────────────────────────────────────────────
# PERFECT = red object without pattern. DEFECT = another colour, or red with a
# pattern/spot. An object is PERFECT only when BOTH hold:
#   * red_coverage >= RED_COVERAGE_THRESHOLD
#   * no connected non-red region >= DEFECT_MIN_BLOB_AREA pixels
# Tiny specks (camera noise, glare) below DEFECT_MIN_BLOB_AREA are ignored.
RED_COVERAGE_THRESHOLD = 0.98
DEFECT_MIN_BLOB_AREA = 40
# The detection mask is shrunk by this many pixels before inspection so the
# object's edge / shadow / belt pixels are not counted as non-red.
MASK_ERODE_PX = 3

# ── Event management ─────────────────────────────────────────────────────
EVENT_ID_PREFIX = "OBJ-"
EVENT_ID_PAD = 6

# ── Background calibration ───────────────────────────────────────────────
CALIB_WARMUP_FRAMES = 45   # skip while webcam auto-exposure settles (~1.5 s)
CALIB_FRAME_COUNT = 30
CALIB_DIFF_THRESHOLD = 30

# ── Event gate ────────────────────────────────────────────────────────────
GATE_CONFIRM_FRAMES = 5
GATE_CLEAR_FRAMES = 10
GATE_MARGIN_RATIO = 0.05

# ── Inspection history (in memory) ───────────────────────────────────────
HISTORY_MAX_SIZE = 100

# ── Dashboard / web server ───────────────────────────────────────────────
SERVER_HOST = "127.0.0.1"  # use "0.0.0.0" to open the dashboard from other devices
SERVER_PORT = 8000
OPEN_BROWSER = True
STREAM_FPS = 15
STREAM_JPEG_QUALITY = 75

# ── Firebase ──────────────────────────────────────────────────────────────
# Database URL and service-account path are read from .env
# (FIREBASE_DATABASE_URL, FIREBASE_CREDENTIALS). Without them the system runs
# locally: camera + dashboard work, but no data reaches the ESP32.

# Misc
DEBUG = False
