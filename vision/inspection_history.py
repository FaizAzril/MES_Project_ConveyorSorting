"""In-memory inspection history with bounded size."""
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

import config


class InspectionHistory:
    def __init__(self):
        self._records: deque = deque(maxlen=config.HISTORY_MAX_SIZE)

    def add(self, event_id: str, result: Dict[str, Any], session_id: str = "") -> Dict[str, Any]:
        now = time.time()
        record = {
            "event_id": event_id,
            "session_id": session_id,
            "timestamp": datetime.fromtimestamp(now).astimezone().isoformat(timespec="milliseconds"),
            "detected_at_ms": int(now * 1000),
            "classification": result.get("classification", "INVALID"),
            "red_pixels": result.get("red_pixels", 0),
            "object_pixels": result.get("object_pixels", 0),
            "non_red_pixels": result.get("non_red_pixels", 0),
            "red_coverage": result.get("red_coverage", 0.0),
            "largest_defect_area": result.get("largest_defect_area", 0),
        }
        self._records.append(record)
        return record

    def find(self, event_id: str) -> Optional[Dict[str, Any]]:
        for record in self._records:
            if record["event_id"] == event_id:
                return record
        return None

    def latest(self, n: int = 5) -> List[Dict[str, Any]]:
        return list(self._records)[-n:]

    def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)
