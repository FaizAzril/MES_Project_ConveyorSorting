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
# With the camera ~11 cm above the belt a 3 cm cube is ~200 px wide, so the
# ROI must cover most of the frame or the cube never fits inside it (and on
# a running belt it must stay inside for a few frames). Keep only the belt in
# it: shrink these if the frame shows the conveyor's side rails.
ROI_X_START_RATIO = 0.10
ROI_X_END_RATIO = 0.90
ROI_Y_START_RATIO = 0.05
ROI_Y_END_RATIO = 0.95

# ── Object detection ──────────────────────────────────────────────────────
MIN_OBJECT_AREA = 800
MAX_OBJECT_AREA = 150000   # a 3 cm cube at 11 cm is ~40 000-55 000 px²
ASPECT_RATIO_TOLERANCE = 0.3
# Shape checks (top view of a cube = one solid blob). Belt texture, light
# flicker and hands give ragged blobs, which are rejected.
MIN_SOLIDITY = 0.85   # blob area / convex hull area
MIN_EXTENT = 0.45     # blob area / bounding box area (a square at 45 deg = 0.5)
# Follow the webcam's automatic exposure (a dark object brightens the whole
# picture, which otherwise hides it): match the background to each frame.
EXPOSURE_COMPENSATION = True
# Ignore the cube's shadow (a darker copy of the belt colour) so it does not
# stretch the object outline.
SHADOW_SUPPRESSION = True

# ── Red colour (HSV, OpenCV hue range 0..179) ────────────────────────────
# Tolerant ranges: also accept dull, dark or blurred red (lower saturation /
# brightness) and red that drifts slightly towards orange or magenta.
LOWER_RED1 = (0, 50, 40)
UPPER_RED1 = (12, 255, 255)
LOWER_RED2 = (165, 50, 40)
UPPER_RED2 = (179, 255, 255)

# ── Quality rule ──────────────────────────────────────────────────────────
# PERFECT = red object without pattern. DEFECT = another colour, or red with a
# pattern/spot. An object is PERFECT only when BOTH hold:
#   * red_coverage >= RED_COVERAGE_THRESHOLD
#   * no connected non-red region larger than
#     max(DEFECT_MIN_BLOB_AREA, DEFECT_MIN_BLOB_RATIO * object pixels)
# Smaller specks (noise, glare, blur at the edge) are ignored.
RED_COVERAGE_THRESHOLD = 0.85
DEFECT_MIN_BLOB_AREA = 40
DEFECT_MIN_BLOB_RATIO = 0.015
# The detection mask is shrunk before inspection so the blurred edge, shadow
# and belt pixels are not counted as non-red: at least MASK_ERODE_PX, or
# MASK_ERODE_RATIO of the object's smaller side (whichever is larger).
MASK_ERODE_PX = 3
MASK_ERODE_RATIO = 0.08
# Running belt: edges along the direction of travel are smeared with the belt
# colour (motion blur). They are eroded by this fraction of the distance the
# object moves per frame (0.5 = exposure about half a frame).
MOTION_BLUR_FRACTION = 0.5
# Red darker than this share of the object's own red surface brightness is
# counted as a dark pattern (marker dot/line), even if its hue is red.
RED_MIN_RELATIVE_V = 0.6
# Non-red strips along the outline thinner than this share of the object's
# side are the blurred edge mixing with the belt, not a pattern.
EDGE_BAND_RATIO = 0.05
# The cube's shadow can stay inside the outline as a very dark band along one
# edge. A band touching the outline, darker than EDGE_SHADOW_MAX_V of the
# surface brightness and reaching less than EDGE_SHADOW_DEPTH_RATIO of the
# side into the object, is shadow, not a pattern.
EDGE_SHADOW_MAX_V = 0.35
EDGE_SHADOW_DEPTH_RATIO = 0.25

# Save a picture of every inspected object (crop + verdict) to captures/
# so thresholds can be tuned from real images. Oldest files are pruned.
SAVE_CAPTURES = True
CAPTURES_MAX = 200

# ── Event management ─────────────────────────────────────────────────────
EVENT_ID_PREFIX = "OBJ-"
EVENT_ID_PAD = 6

# ── Background calibration ───────────────────────────────────────────────
CALIB_WARMUP_FRAMES = 45   # skip while webcam auto-exposure settles (~1.5 s)
CALIB_FRAME_COUNT = 30
CALIB_DIFF_THRESHOLD = 30

# ── Event gate ────────────────────────────────────────────────────────────
# A moving cube is only fully inside the ROI for a short time:
#   time = (ROI length along the belt - cube size) / belt speed
# e.g. ROI 6 cm, cube 3 cm, belt 20 cm/s -> 0.15 s = ~4 frames at 30 fps.
# The cube must be seen in GATE_CONFIRM_FRAMES consecutive frames.
GATE_CONFIRM_FRAMES = 2   # was 5: too slow for a running belt
GATE_CLEAR_FRAMES = 6     # frames without object before the next one counts
GATE_MARGIN_RATIO = 0.02  # min gap between object and ROI edge (fraction of ROI)

# ── Inspection history (in memory) ───────────────────────────────────────
HISTORY_MAX_SIZE = 100

# ── Dashboard / web server ───────────────────────────────────────────────
SERVER_HOST = "127.0.0.1"  # use "0.0.0.0" to open the dashboard from other devices
SERVER_PORT = 8765  # 8000 is often taken (php artisan serve, Django, ...)
OPEN_BROWSER = True
STREAM_FPS = 15
STREAM_JPEG_QUALITY = 75

# ── Firebase ──────────────────────────────────────────────────────────────
# Database URL and service-account path are read from .env
# (FIREBASE_DATABASE_URL, FIREBASE_CREDENTIALS). Without them the system runs
# locally: camera + dashboard work, but no data reaches the ESP32.

# Misc
DEBUG = False
