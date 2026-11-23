'''Configuration parameters for MES Conveyor Sorting System (Computer Vision + optional ESP32 Serial).'''

# Camera settings
CAMERA_INDEX = 1  # 0 = built-in webcam; 1 = first external webcam
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_BACKEND = "CAP_DSHOW"  # Windows DirectShow; set None to use OpenCV default

# ROI settings (relative percentages of the frame)
ROI_X_START_RATIO = 0.25
ROI_X_END_RATIO = 0.75
ROI_Y_START_RATIO = 0.20
ROI_Y_END_RATIO = 0.80

# Object detection settings
MIN_OBJECT_AREA = 800
MAX_OBJECT_AREA = 50000
ASPECT_RATIO_TOLERANCE = 0.3

# Red color HSV thresholds (OpenCV H range is 0..179)
LOWER_RED1 = (0, 80, 50)
UPPER_RED1 = (10, 255, 255)
LOWER_RED2 = (170, 80, 50)
UPPER_RED2 = (179, 255, 255)

# Strict classification is implemented by non_red_pixels == 0.
# Retained as a compatibility/config display value; it is not a tolerance.
RED_COVERAGE_THRESHOLD = 1.0

# Serial link: Python -> ESP32. Set SERIAL_ENABLED=False for CV-only operation.
SERIAL_ENABLED = True
SERIAL_PORT = "COM7"
SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT = 0.1
SERIAL_ACK_TIMEOUT = 2.0
SERIAL_RESULT_TIMEOUT = 15.0
SERIAL_MAX_RETRIES = 3
SERIAL_RETRY_DELAY = 0.5
SERIAL_RECONNECT_DELAY = 3.0
SERIAL_RESET_DELAY = 2.0

# Event management
EVENT_ID_PREFIX = "OBJ-"
EVENT_ID_PAD = 6

# Background calibration
CALIB_FRAME_COUNT = 30
CALIB_DIFF_THRESHOLD = 30

# Event gate
GATE_CONFIRM_FRAMES = 5
GATE_CLEAR_FRAMES = 10
GATE_MARGIN_RATIO = 0.05

# Inspection history
HISTORY_MAX_SIZE = 100

# Misc
DEBUG = True
