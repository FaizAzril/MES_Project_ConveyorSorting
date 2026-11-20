'''Configuration parameters for MES Conveyor Sorting System (Computer Vision)'''

# Camera settings
CAMERA_INDEX = 1  # default external webcam index; adjust as needed
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_BACKEND = "CAP_DSHOW"  # OpenCV backend for Windows; can be None

# ROI settings (relative percentages of the frame)
ROI_X_START_RATIO = 0.25
ROI_X_END_RATIO = 0.75
ROI_Y_START_RATIO = 0.20
ROI_Y_END_RATIO = 0.80

# Object detection settings
MIN_OBJECT_AREA = 800  # minimum contour area to be considered an object
MAX_OBJECT_AREA = 50000  # optional upper limit
ASPECT_RATIO_TOLERANCE = 0.3  # allowed deviation from square shape (0.0 = perfect square)

# Red color HSV thresholds (two ranges for hue wrapping)
LOWER_RED1 = (0, 80, 50)
UPPER_RED1 = (10, 255, 255)
LOWER_RED2 = (170, 80, 50)
UPPER_RED2 = (179, 255, 255)

# Quality inspection thresholds
RED_COVERAGE_THRESHOLD = 0.98

# Serial communication settings
SERIAL_ENABLED = True
SERIAL_PORT = "COM3"
SERIAL_BAUDRATE = 115200
SERIAL_TIMEOUT = 1  # seconds
SERIAL_MAX_RETRIES = 3
SERIAL_RETRY_DELAY = 0.5  # seconds

# Event management
EVENT_ID_PREFIX = "OBJ-"
EVENT_ID_PAD = 6

# Misc
DEBUG = True  # set False to reduce console output
