"""In-memory inspection history with bounded size."""
from collections import deque
from datetime import datetime
from typing import List, Dict, Any
import config


class InspectionHistory:
    def __init__(self):
        self._records: deque = deque(maxlen=config.HISTORY_MAX_SIZE)

    def add(self, event_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "event_id": event_id,
            "timestamp": datetime.now().isoformat(),
            "classification": result.get("classification", "INVALID"),
            "red_pixels": result.get("red_pixels", 0),
            "object_pixels": result.get("object_pixels", 0),
            "non_red_pixels": result.get("non_red_pixels", 0),
            "red_coverage": result.get("red_coverage", 0.0),
        }
        self._records.append(record)
        return record

    def latest(self, n: int = 5) -> List[Dict[str, Any]]:
        return list(self._records)[-n:]

    def __len__(self) -> int:
        return len(self._records)
