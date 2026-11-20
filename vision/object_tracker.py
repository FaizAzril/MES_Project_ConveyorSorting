"""Event gate – state machine that fires one inspection per object."""
import logging
import uuid
import config

_logger = logging.getLogger(__name__)

# States
READY = "READY"
OBJECT_DETECTED = "OBJECT_DETECTED"
INSPECTION_COMPLETED = "INSPECTION_COMPLETED"
WAIT_CLEAR = "WAIT_CLEAR"


class EventGate:
    """Single-object state machine.

    Call update(detected) each frame with bool whether a valid object is
    present in the ROI. When the gate fires it returns a unique event_id
    string; otherwise returns None.
    """

    def __init__(self):
        self.state = READY
        self._confirm_count = 0
        self._clear_count = 0
        self.event_id: str = ""
        self._next_seq = 1

    def _new_id(self) -> str:
        seq = f"{config.EVENT_ID_PREFIX}{self._next_seq:0{config.EVENT_ID_PAD}d}"
        self._next_seq += 1
        return seq

    def update(self, detected: bool) -> str | None:
        """Feed detection state for one frame.

        Returns a new event_id string when an inspection should be triggered,
        otherwise returns None.
        """
        if self.state == READY:
            if detected:
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
            # Inspection was triggered; transition immediately
            self.state = INSPECTION_COMPLETED

        elif self.state == INSPECTION_COMPLETED:
            if not detected:
                self._clear_count += 1
                if self._clear_count >= config.GATE_CLEAR_FRAMES:
                    self.state = WAIT_CLEAR
            else:
                self._clear_count = 0

        elif self.state == WAIT_CLEAR:
            self.state = READY
            self._clear_count = 0
            _logger.info("Gate RESET to READY")

        return None

    def mark_inspection_done(self):
        """Call after inspection result is recorded to advance state."""
        if self.state == OBJECT_DETECTED:
            self.state = INSPECTION_COMPLETED
            self._clear_count = 0

    def reset(self):
        self.state = READY
        self._confirm_count = 0
        self._clear_count = 0
        self.event_id = ""
