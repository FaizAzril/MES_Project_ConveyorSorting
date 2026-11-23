"""Unique event IDs and single-object event gate for the CV pipeline."""
from datetime import datetime
import secrets
import logging
import config

_logger = logging.getLogger(__name__)

READY = "READY"
OBJECT_DETECTED = "OBJECT_DETECTED"
INSPECTION_COMPLETED = "INSPECTION_COMPLETED"
WAIT_CLEAR = "WAIT_CLEAR"


class EventGate:
    """Fire one event per object and wait for object-clear + ESP32 result."""

    def __init__(self):
        self.state = READY
        self._confirm_count = 0
        self._clear_count = 0
        self.event_id = ""
        self._next_seq = 1
        self._session_id = datetime.now().strftime("%y%m%d%H%M%S") + secrets.token_hex(2).upper()

    def _new_id(self) -> str:
        event_id = f"{config.EVENT_ID_PREFIX}{self._session_id}-{self._next_seq:0{config.EVENT_ID_PAD}d}"
        self._next_seq += 1
        return event_id

    def update(self, detected: bool, allow_new_event: bool = True):
        """Update gate state. New events are suppressed until allow_new_event."""
        if self.state == READY:
            if detected and allow_new_event:
                self._confirm_count += 1
                if self._confirm_count >= config.GATE_CONFIRM_FRAMES:
                    self.state = OBJECT_DETECTED
                    self.event_id = self._new_id()
                    self._confirm_count = 0
                    _logger.info("Gate FIRED: %s", self.event_id)
                    return self.event_id
            else:
                self._confirm_count = 0

        elif self.state == OBJECT_DETECTED:
            self.state = INSPECTION_COMPLETED

        elif self.state == INSPECTION_COMPLETED:
            if not detected:
                self._clear_count += 1
                if self._clear_count >= config.GATE_CLEAR_FRAMES:
                    self.state = WAIT_CLEAR
            else:
                self._clear_count = 0

        elif self.state == WAIT_CLEAR:
            if allow_new_event:
                self.state = READY
                self._clear_count = 0
                _logger.info("Gate RESET to READY")

        return None

    def mark_inspection_done(self):
        if self.state == OBJECT_DETECTED:
            self.state = INSPECTION_COMPLETED
            self._clear_count = 0

    def reset(self):
        self.state = READY
        self._confirm_count = 0
        self._clear_count = 0
        self.event_id = ""
