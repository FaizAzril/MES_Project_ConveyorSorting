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
        self.frame_seq = 0          # increments on every new camera frame
        self.fps = 0.0              # measured webcam frame rate
        self._fps_count = 0
        self._fps_since = time.monotonic()

    def _open_camera(self) -> bool:
        backend = getattr(cv2, config.CAMERA_BACKEND, None) if getattr(config, "CAMERA_BACKEND", None) else None
        try:
            if backend is not None:
                self.cap = cv2.VideoCapture(config.CAMERA_INDEX, backend)
            else:
                self.cap = cv2.VideoCapture(config.CAMERA_INDEX)
        except Exception as e:
            _logger.error("Exception opening camera index %s: %s", config.CAMERA_INDEX, e)
            return False

        if self.cap is None or not self.cap.isOpened():
            _logger.error("Failed to open camera index %s", config.CAMERA_INDEX)
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        _logger.info("Camera opened (index=%s, resolution=%dx%d)", config.CAMERA_INDEX, config.CAMERA_WIDTH, config.CAMERA_HEIGHT)
        return True

    def _capture_loop(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(0.05)
                continue
            ret, frame = self.cap.read()
            if not ret or frame is None:
                _logger.warning("Failed to read frame from camera")
                time.sleep(0.01)
                continue
            with self._lock:
                self.frame = frame
                self.frame_seq += 1
            # Real frame rate delivered by the webcam (drops in dim light).
            self._fps_count += 1
            now = time.monotonic()
            if now - self._fps_since >= 1.0:
                self.fps = self._fps_count / (now - self._fps_since)
                self._fps_count, self._fps_since = 0, now
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
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception as e:
                _logger.warning("Error releasing camera: %s", e)
            self.cap = None
        with self._lock:
            self.frame = None
        _logger.info("Camera released")

    @property
    def is_opened(self) -> bool:
        return self.cap is not None and self.cap.isOpened()

    def get_frame(self) -> Optional[any]:
        with self._lock:
            return self.frame.copy() if self.frame is not None else None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def __del__(self):
        self.stop()
