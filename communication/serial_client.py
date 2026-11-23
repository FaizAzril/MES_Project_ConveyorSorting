"""Asynchronous JSON-Lines client for Python Computer Vision <-> ESP32.

The worker owns the serial port. The OpenCV main loop only enqueues inspection
records and drains notifications, so camera processing never waits on serial IO.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import serial
except ImportError:  # The CV-only mode can still run without pyserial.
    serial = None

_logger = logging.getLogger(__name__)


class SerialClient:
    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = 115200,
        read_timeout: float = 0.1,
        ack_timeout: float = 2.0,
        result_timeout: float = 15.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        reconnect_delay: float = 3.0,
        reset_delay: float = 2.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self.ack_timeout = ack_timeout
        self.result_timeout = result_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.reconnect_delay = reconnect_delay
        self.reset_delay = reset_delay

        self._outgoing: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._notifications: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._serial = None
        self._connected = False
        self._connection_lock = threading.Lock()
        self._active_ids = set()
        self._active_lock = threading.Lock()
        self._pending: Dict[str, Dict[str, Any]] = {}

    @property
    def connected(self) -> bool:
        with self._connection_lock:
            return self._connected

    @property
    def has_active_event(self) -> bool:
        with self._active_lock:
            return bool(self._active_ids)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker, name="ESP32SerialWorker", daemon=True
        )
        self._thread.start()

    def send_inspection(self, record: Dict[str, Any]) -> bool:
        """Queue one valid PERFECT/DEFECT record. Returns False if invalid/duplicate."""
        classification = str(record.get("classification", "")).upper()
        event_id = str(record.get("event_id", ""))
        object_pixels = int(record.get("object_pixels", 0))
        red_pixels = int(record.get("red_pixels", 0))
        red_coverage = float(record.get("red_coverage", 0.0))

        if classification not in ("PERFECT", "DEFECT"):
            _logger.warning("Serial skipped non-sortable classification: %s", classification)
            return False
        if not event_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in event_id):
            _logger.error("Serial skipped invalid event_id: %r", event_id)
            return False
        if object_pixels <= 0 or red_pixels < 0 or red_pixels > object_pixels:
            _logger.error("Serial skipped invalid pixel metrics for %s", event_id)
            return False
        if not 0.0 <= red_coverage <= 1.0:
            _logger.error("Serial skipped invalid red_coverage for %s", event_id)
            return False
        if classification == "PERFECT" and red_pixels != object_pixels:
            _logger.error("Inconsistent PERFECT metrics for %s", event_id)
            return False
        if classification == "DEFECT" and red_pixels == object_pixels:
            _logger.error("Inconsistent DEFECT metrics for %s", event_id)
            return False

        timestamp = str(record.get("timestamp") or "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.astimezone()
                timestamp = dt.isoformat(timespec="seconds")
            except ValueError:
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        else:
            timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

        payload = {
            "protocol_version": 1,
            "type": "inspection_result",
            "event_id": event_id,
            "classification": classification,
            "red_coverage": red_coverage,
            "red_pixels": red_pixels,
            "object_pixels": object_pixels,
            "timestamp": timestamp,
        }
        with self._active_lock:
            if event_id in self._active_ids:
                return False
            self._active_ids.add(event_id)
        self._outgoing.put(payload)
        self._notifications.put({"kind": "queued", "event_id": event_id})
        return True

    def get_events(self, max_items: int = 50) -> list[Dict[str, Any]]:
        events = []
        for _ in range(max_items):
            try:
                events.append(self._notifications.get_nowait())
            except queue.Empty:
                break
        return events

    def close(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._close_port()

    def _set_connected(self, value: bool, message: str = "") -> None:
        changed = False
        with self._connection_lock:
            if self._connected != value:
                self._connected = value
                changed = True
        if changed:
            self._notifications.put({
                "kind": "connection", "connected": value,
                "message": message or ("connected" if value else "disconnected"),
            })

    def _close_port(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._set_connected(False, "serial port closed")

    def _connect(self) -> bool:
        if serial is None:
            self._notifications.put({
                "kind": "error", "message": "pyserial is not installed; install requirements.txt"
            })
            return False
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.read_timeout,
                write_timeout=1.0,
            )
            # Opening an ESP32 serial port may reset the board. Allow boot before sending.
            time.sleep(self.reset_delay)
            try:
                self._serial.reset_input_buffer()
            except Exception:
                pass
            self._set_connected(True, f"connected to {self.port} at {self.baudrate}")
            _logger.info("Connected to ESP32 on %s", self.port)
            return True
        except Exception as exc:
            self._close_port()
            self._notifications.put({"kind": "connection_error", "message": str(exc)})
            _logger.warning("Cannot open serial port %s: %s", self.port, exc)
            return False

    def _worker(self) -> None:
        next_connect = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if self._serial is None:
                if now >= next_connect:
                    if not self._connect():
                        next_connect = time.monotonic() + self.reconnect_delay
                else:
                    time.sleep(0.05)
                self._collect_outgoing()
                continue

            self._collect_outgoing()
            self._read_one_line()
            self._send_due(now)
            self._check_timeouts(now)
            time.sleep(0.01)

        self._close_port()

    def _collect_outgoing(self) -> None:
        while True:
            try:
                payload = self._outgoing.get_nowait()
            except queue.Empty:
                return
            event_id = payload["event_id"]
            self._pending[event_id] = {
                "payload": payload,
                "attempts": 0,
                "accepted": False,
                "next_attempt": 0.0,
                "result_deadline": None,
            }

    def _read_one_line(self) -> None:
        if self._serial is None:
            return
        try:
            raw = self._serial.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                return
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # Ignore ESP32 boot text or non-JSON diagnostics; protocol is JSON-only.
                _logger.debug("Ignored non-JSON serial line: %s", line[:120])
                return
            self._handle_message(message)
        except Exception as exc:
            self._notifications.put({"kind": "serial_error", "message": str(exc)})
            self._close_port()

    def _handle_message(self, message: Dict[str, Any]) -> None:
        message_type = message.get("type")
        event_id = str(message.get("event_id", ""))
        status = str(message.get("status", ""))
        pending = self._pending.get(event_id)

        if message_type == "ack":
            self._notifications.put({"kind": "ack", **message})
            if not pending:
                return
            if status == "accepted":
                pending["accepted"] = True
                pending["result_deadline"] = time.monotonic() + self.result_timeout
            elif status == "busy":
                pending["accepted"] = False
                pending["next_attempt"] = time.monotonic() + self.retry_delay
            elif status == "duplicate":
                self._finish_event(event_id, {"kind": "ack", **message})
            return

        if message_type == "sorting_result":
            self._finish_event(event_id, {"kind": "sorting_result", **message})
            return

        if message_type == "error":
            self._finish_event(event_id, {"kind": "device_error", **message})
            return

        self._notifications.put({"kind": "unknown_message", "message": message})

    def _finish_event(self, event_id: str, notification: Dict[str, Any]) -> None:
        self._pending.pop(event_id, None)
        with self._active_lock:
            self._active_ids.discard(event_id)
        self._notifications.put(notification)

    def _send_due(self, now: float) -> None:
        if self._serial is None:
            return
        for event_id, pending in list(self._pending.items()):
            if pending["accepted"]:
                continue
            if pending["attempts"] > 0 and now < pending["next_attempt"]:
                continue
            if pending["attempts"] >= self.max_retries:
                self._finish_event(event_id, {
                    "kind": "send_failed", "event_id": event_id,
                    "message": "ACK timeout or ESP32 remained busy after retries",
                })
                continue
            try:
                line = json.dumps(pending["payload"], separators=(",", ":")) + "\n"
                self._serial.write(line.encode("utf-8"))
                self._serial.flush()
                pending["attempts"] += 1
                pending["next_attempt"] = now + self.ack_timeout
                self._notifications.put({
                    "kind": "sent", "event_id": event_id,
                    "attempt": pending["attempts"],
                })
            except Exception as exc:
                self._notifications.put({"kind": "serial_error", "message": str(exc)})
                self._close_port()
                return

    def _check_timeouts(self, now: float) -> None:
        for event_id, pending in list(self._pending.items()):
            deadline = pending.get("result_deadline")
            if pending["accepted"] and deadline is not None and now >= deadline:
                self._finish_event(event_id, {
                    "kind": "sorting_timeout", "event_id": event_id,
                    "message": "ESP32 accepted the event but no sorting_result arrived",
                })
