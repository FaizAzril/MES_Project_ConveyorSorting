import cv2
import threading
import time
from typing import Optional
import logging
import config

_logger = logging.getLogger(__name__)

class CameraManager:
    """Manages OpenCV video capture with graceful shutdown.

    Attributes
    ----------
    cap : cv2.VideoCapture
        The underlying OpenCV capture object.
    frame : Optional[any]
        Latest retrieved frame (BGR numpy array).
    running : bool
        Indicates whether the capture thread is active.
    """

    def __init__(self):
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame: Optional[any] = None
        self.running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _open_camera(self) -> bool:
        backend = getattr(cv2, config.CAMERA_BACKEND, None) if getattr(config, "CAMERA_BACKEND", None) else None
        if backend:
            self.cap = cv2.VideoCapture(config.CAMERA_INDEX, backend)
        else:
            self.cap = cv2.VideoCapture(config.CAMERA_INDEX)
        if not self.cap.isOpened():
            _logger.error("Failed to open camera index %s", config.CAMERA_INDEX)
            return False
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        _logger.info("Camera opened (index=%s, resolution=%dx%d)", config.CAMERA_INDEX, config.CAMERA_WIDTH, config.CAMERA_HEIGHT)
        return True

    def _capture_loop(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                _logger.warning("Failed to read frame from camera")
                time.sleep(0.01)
                continue
            with self._lock:
                self.frame = frame
        _logger.debug("Capture thread exiting")

    def start(self) -> bool:
        if self.running:
            return True
        if not self._open_camera():
            return False
        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self.cap:
            self.cap.release()
        _logger.info("Camera released")

    def get_frame(self) -> Optional[any]:
        with self._lock:
            return self.frame.copy() if self.frame is not None else None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
