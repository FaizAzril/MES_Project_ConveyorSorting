import cv2
import numpy as np
import logging
from typing import Dict, Tuple, List
import config

_logger = logging.getLogger(__name__)

class ObjectTracker:
    """Tracks objects across frames and generates unique event IDs.

    Simple centroid‑based tracking suitable for a single object in the ROI.
    Maintains a dictionary ``active`` mapping event_id -> centroid.
    When a new detection appears far from any existing centroid, a new
    event_id is created. When a previously seen object disappears for more
    than ``max_missing`` frames it is removed.
    """

    def __init__(self):
        self.active: Dict[str, Tuple[int, int]] = {}
        self.missing_counter: Dict[str, int] = {}
        self.next_id: int = 1
        self.max_missing: int = 10
        self.distance_thresh: float = 50.0  # pixels

    def _centroid(self, box: Tuple[int, int, int, int]) -> Tuple[int, int]:
        x, y, w, h = box
        return (int(x + w / 2), int(y + h / 2))

    def update(self, boxes: List[Tuple[int, int, int, int]]) -> Dict[str, Tuple[int, int, int, int]]:
        """Update tracker with the current list of bounding boxes.

        Returns a mapping ``event_id -> box`` for objects that are newly
        detected (i.e., have not been reported before). Existing objects are
        ignored so that the main loop does not send duplicate events.
        """
        assignments: Dict[str, Tuple[int, int, int, int]] = {}
        used_ids = set()
        # First, try to match each detection to an existing active object
        for box in boxes:
            c = self._centroid(box)
            best_id = None
            best_dist = float('inf')
            for eid, centroid in self.active.items():
                dist = np.linalg.norm(np.array(c) - np.array(centroid))
                if dist < self.distance_thresh and dist < best_dist:
                    best_dist = dist
                    best_id = eid
            if best_id and best_id not in used_ids:
                # Existing object – update centroid and reset missing counter
                self.active[best_id] = c
                self.missing_counter[best_id] = 0
                used_ids.add(best_id)
                # No new event for already known object
            else:
                # New object – assign new ID
                eid = f"{config.EVENT_ID_PREFIX}{self.next_id:0{config.EVENT_ID_PAD}d}"
                self.next_id += 1
                self.active[eid] = c
                self.missing_counter[eid] = 0
                assignments[eid] = box
                used_ids.add(eid)
        # Increment missing counters for objects not seen this frame
        for eid in list(self.active.keys()):
            if eid not in used_ids:
                self.missing_counter[eid] += 1
                if self.missing_counter[eid] > self.max_missing:
                    # Remove stale entry
                    del self.active[eid]
                    del self.missing_counter[eid]
        return assignments
