"""Firebase Realtime Database writer (Python side).

Data contract shared with the ESP32 firmware and the web dashboard:

/session                     {id, status: running|stopped, startedAtMs, stoppedAtMs}
/vision                      {status: online|offline, lastClass, lastEventId,
                              lastDetectionMs, redCoverage}
/detections/{eventId}        written here: eventId, sessionId, class, redCoverage,
                              redPixels, objectPixels, nonRedPixels,
                              largestDefectArea, timestamp, detectedAtMs
                              written by ESP32: sortAction (STRAIGHT|DIVERT), sortedAtMs
                              written by operator (dashboard): actualBin (BIN1|BIN2),
                              confirmedAtMs
/statistics                  {total, perfect, defect, invalid}
/conveyor                    written by ESP32 heartbeat (deviceOnline, lastHeartbeatMs, ...)

Event IDs are time-ordered, so the ESP32 can poll the newest detections with
orderBy="$key"&limitToLast=N. Writes run on a worker thread so the camera loop
never waits on the network.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _now_ms() -> int:
    return int(time.time() * 1000)


def _set_path(tree: Any, parts: list, value: Any) -> Any:
    """Return tree with value placed at parts (None deletes), like an RTDB put."""
    if not parts:
        return value if value is not None else {}
    node = dict(tree) if isinstance(tree, dict) else {}
    head, rest = parts[0], parts[1:]
    if rest:
        child = _set_path(node.get(head), rest, value)
        if child in (None, {}):
            node.pop(head, None)
        else:
            node[head] = child
    elif value is None:
        node.pop(head, None)
    else:
        node[head] = value
    return node


class FirebaseSync:
    def __init__(self, project_dir: Optional[Path] = None):
        self.project_dir = Path(project_dir or PROJECT_DIR)
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._db = None
        self._app = None
        self._status_lock = threading.Lock()
        self._status = "NOT CONFIGURED"
        self._last_error = ""

        try:
            from dotenv import load_dotenv
            load_dotenv(self.project_dir / ".env", override=False)
        except ImportError:
            pass

        database_url = os.getenv("FIREBASE_DATABASE_URL", "").strip()
        credential_setting = os.getenv("FIREBASE_CREDENTIALS", "serviceAccountKey.json").strip()
        credential_path = Path(credential_setting)
        if not credential_path.is_absolute():
            credential_path = self.project_dir / credential_path

        missing = []
        if not database_url or "PASTE_" in database_url:
            missing.append("FIREBASE_DATABASE_URL di .env")
        if not credential_path.is_file():
            missing.append(f"file {credential_path.name}")
        if missing:
            self._set_status("NOT CONFIGURED", "Belum ada " + " dan ".join(missing))
            _logger.warning("Firebase disabled: %s", self.last_error)
            return

        try:
            import firebase_admin
            from firebase_admin import credentials, db

            try:
                self._app = firebase_admin.get_app()
            except ValueError:
                cert = credentials.Certificate(str(credential_path))
                self._app = firebase_admin.initialize_app(cert, {"databaseURL": database_url})
            self._db = db
            self._set_status("READY")
            self._thread = threading.Thread(target=self._worker, name="firebase-sync", daemon=True)
            self._thread.start()
        except ImportError:
            self._set_status("NOT CONFIGURED", "Install firebase-admin dan python-dotenv (requirements.txt)")
        except Exception as exc:
            self._set_status("ERROR", str(exc))
            _logger.exception("Firebase initialization failed")

    # ── status ────────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._db is not None and self._thread is not None

    @property
    def status(self) -> str:
        with self._status_lock:
            return self._status

    @property
    def last_error(self) -> str:
        with self._status_lock:
            return self._last_error

    def _set_status(self, status: str, error: str = "") -> None:
        with self._status_lock:
            self._status = status
            self._last_error = error

    # ── public API (non-blocking) ─────────────────────────────────────────
    def start_session(self, session_id: str) -> None:
        self._put("session", {"id": session_id, "status": "running",
                              "startedAtMs": _now_ms(), "stoppedAtMs": None})

    def stop_session(self, session_id: str) -> None:
        self._put("session_stop", {"id": session_id, "status": "stopped", "stoppedAtMs": _now_ms()})

    def set_vision_status(self, status: str) -> None:
        self._put("vision_status", status)

    def push_inspection(self, record: Dict[str, Any]) -> None:
        self._put("inspection", dict(record))

    def confirm_actual_bin(self, event_id: str, actual_bin: str) -> None:
        self._put("confirm", {"event_id": event_id, "actual_bin": actual_bin})

    # ── read mirror (for the dashboard) ───────────────────────────────────
    def start_mirror(self) -> None:
        """Stream the database into memory so the dashboard sees ESP32 writes."""
        if not self.enabled or getattr(self, "_listener", None):
            return
        self._mirror: Dict[str, Any] = {}
        self._mirror_lock = threading.Lock()
        try:
            self._listener = self._ref("/").listen(self._on_db_event)
        except Exception as exc:
            self._listener = None
            self._set_status("ERROR", f"listener: {exc}")
            _logger.warning("Firebase listener failed: %s", exc)

    def _on_db_event(self, event) -> None:
        parts = [p for p in (event.path or "/").split("/") if p]
        with self._mirror_lock:
            if event.event_type == "put":
                self._mirror = _set_path(self._mirror, parts, event.data)
            elif event.event_type == "patch" and isinstance(event.data, dict):
                for key, value in event.data.items():
                    self._mirror = _set_path(self._mirror, parts + [p for p in key.split("/") if p], value)

    def mirror(self) -> Optional[Dict[str, Any]]:
        """Copy of the mirrored database, or None when not mirroring."""
        if not getattr(self, "_listener", None):
            return None
        import copy
        with self._mirror_lock:
            return copy.deepcopy(self._mirror)

    def close(self, timeout: float = 3.0) -> None:
        if not self.enabled:
            return
        listener = getattr(self, "_listener", None)
        if listener:
            try:
                listener.close()
            except Exception:
                pass
            self._listener = None
        self._queue.put(None)
        self._thread.join(timeout=timeout)

    def _put(self, kind: str, payload: Any) -> None:
        if self.enabled:
            self._queue.put((kind, payload))

    # ── worker ────────────────────────────────────────────────────────────
    def _ref(self, path: str):
        return self._db.reference(path, app=self._app)

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            kind, payload = job
            try:
                if kind == "session":
                    self._ref("session").set(payload)
                elif kind == "session_stop":
                    self._ref("session").update(payload)
                elif kind == "vision_status":
                    self._ref("vision").update({"status": payload})
                elif kind == "inspection":
                    self._write_inspection(payload)
                elif kind == "confirm":
                    self._ref(f"detections/{payload['event_id']}").update({
                        "actualBin": payload["actual_bin"],
                        "confirmedAtMs": _now_ms(),
                    })
                self._set_status("ONLINE")
            except Exception as exc:  # keep the camera alive when the network fails
                self._set_status("ERROR", str(exc))
                _logger.warning("Firebase write failed (%s): %s", kind, exc)

    def _write_inspection(self, record: Dict[str, Any]) -> None:
        classification = str(record.get("classification", "INVALID")).upper()
        if classification not in {"PERFECT", "DEFECT", "INVALID"}:
            classification = "INVALID"
        event_id = str(record["event_id"])
        coverage = float(record.get("red_coverage", 0.0) or 0.0)
        detected_at = int(record.get("detected_at_ms") or _now_ms())

        self._ref(f"detections/{event_id}").set({
            "eventId": event_id,
            "sessionId": str(record.get("session_id", "")),
            "class": classification,
            "redCoverage": coverage,
            "redPixels": int(record.get("red_pixels", 0) or 0),
            "objectPixels": int(record.get("object_pixels", 0) or 0),
            "nonRedPixels": int(record.get("non_red_pixels", 0) or 0),
            "largestDefectArea": int(record.get("largest_defect_area", 0) or 0),
            "timestamp": str(record.get("timestamp", "")),
            "detectedAtMs": detected_at,
        })

        def increment(current: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            stats = dict(current or {})
            stats["total"] = int(stats.get("total", 0) or 0) + 1
            key = classification.lower()
            stats[key] = int(stats.get(key, 0) or 0) + 1
            return stats

        self._ref("statistics").transaction(increment)
        self._ref("vision").update({
            "status": "online",
            "lastClass": classification,
            "lastEventId": event_id,
            "lastDetectionMs": detected_at,
            "redCoverage": coverage,
        })
