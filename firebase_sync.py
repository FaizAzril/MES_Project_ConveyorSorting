"""Optional Firebase Realtime Database sync for the CV desktop dashboard.

Uses the Firebase Admin SDK and a local service-account JSON file. The key is
never embedded in source code or sent to the frontend. Network writes are queued
on a worker thread so camera rendering is not blocked by Firebase latency.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class FirebaseSync:
    def __init__(self, project_dir: Optional[Path] = None):
        self.project_dir = Path(project_dir or Path(__file__).resolve().parent)
        self._queue: queue.Queue = queue.Queue()
        self._stop_token = object()
        self._thread: Optional[threading.Thread] = None
        self._db = None
        self._status_lock = threading.Lock()
        self._status = "NOT CONFIGURED"
        self._last_error = ""

        # .env is optional; environment variables take precedence.
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

        if not database_url or "YOUR_" in database_url or not credential_path.is_file():
            missing = []
            if not database_url:
                missing.append("FIREBASE_DATABASE_URL")
            if not credential_path.is_file():
                missing.append(f"service account file ({credential_path.name})")
            self._set_status("NOT CONFIGURED", ", ".join(missing))
            return

        try:
            import firebase_admin
            from firebase_admin import credentials, db

            try:
                app = firebase_admin.get_app()
            except ValueError:
                cert = credentials.Certificate(str(credential_path))
                app = firebase_admin.initialize_app(cert, {"databaseURL": database_url})

            self._db = db
            self._app = app
            self._set_status("READY", "")
            self._thread = threading.Thread(target=self._worker, name="firebase-sync", daemon=True)
            self._thread.start()
        except ImportError:
            self._set_status("NOT CONFIGURED", "Install firebase-admin and python-dotenv")
            logger.exception("Firebase packages are not installed")
        except Exception as exc:
            self._set_status("ERROR", str(exc))
            logger.exception("Firebase initialization failed")

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

    @property
    def enabled(self) -> bool:
        return self._db is not None and self._thread is not None

    def set_vision_status(self, status: str) -> None:
        if self.enabled:
            self._queue.put(("vision_status", status))

    def push_inspection(self, record: Dict[str, Any]) -> None:
        if self.enabled:
            # Copy the record so later local changes cannot affect the queued job.
            self._queue.put(("inspection", dict(record)))

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is self._stop_token:
                    return
                kind, payload = job
                if kind == "vision_status":
                    self._write_vision_status(payload)
                elif kind == "inspection":
                    self._write_inspection(payload)
                self._set_status("ONLINE", "")
            except Exception as exc:  # Keep the CV dashboard alive if Firebase is unreachable.
                self._set_status("ERROR", str(exc))
                logger.exception("Firebase sync failed: %s", exc)
            finally:
                self._queue.task_done()

    def _write_vision_status(self, status: str) -> None:
        self._db.reference("vision", app=self._app).update({"status": status})

    def _write_inspection(self, record: Dict[str, Any]) -> None:
        classification = str(record.get("classification", "INVALID")).upper()
        if classification not in {"PERFECT", "DEFECT", "INVALID"}:
            classification = "INVALID"

        timestamp = str(record.get("timestamp", ""))
        red_coverage = float(record.get("red_coverage", 0.0) or 0.0)

        # Each inspection receives a unique Firebase push ID.
        self._db.reference("detections", app=self._app).push({
            "eventId": str(record.get("event_id", "")),
            "class": classification,
            "redCoverage": red_coverage,
            "redPixels": int(record.get("red_pixels", 0) or 0),
            "objectPixels": int(record.get("object_pixels", 0) or 0),
            "nonRedPixels": int(record.get("non_red_pixels", 0) or 0),
            "timestamp": timestamp,
        })

        # A transaction prevents lost increments if another writer updates stats.
        def increment_stats(current: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            stats = dict(current or {})
            stats["total"] = int(stats.get("total", 0) or 0) + 1
            counter_key = classification.lower()
            stats[counter_key] = int(stats.get(counter_key, 0) or 0) + 1
            return stats

        self._db.reference("statistics", app=self._app).transaction(increment_stats)

        # Do not overwrite "confidence": this CV model reports red coverage,
        # which is a different measurement and is saved under redCoverage.
        self._db.reference("vision", app=self._app).update({
            "status": "online",
            "lastClass": classification,
            "redCoverage": red_coverage,
            "lastDetection": timestamp,
        })

    def close(self, timeout: float = 2.0) -> None:
        if not self.enabled:
            return
        self._queue.put(self._stop_token)
        if self._thread:
            self._thread.join(timeout=timeout)
