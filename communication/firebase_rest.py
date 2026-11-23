"""Minimal Firebase Realtime Database client over REST (standard library only).

Used when no service-account key is present. It mimics the parts of the
firebase_admin ``db.reference`` API that FirebaseSync uses: set, update,
transaction (read-modify-write, fine for a single writer) and listen
(Server-Sent Events stream with automatic reconnect).

Access is governed by the database rules; set FIREBASE_AUTH in .env to a
database secret when the rules are closed.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

_logger = logging.getLogger(__name__)
TIMEOUT = 10


@dataclass
class Event:
    event_type: str
    path: str
    data: Any


class _Registration:
    def __init__(self):
        self._stop = threading.Event()
        self._response = None

    def close(self) -> None:
        self._stop.set()
        resp = self._response
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass


class RestRef:
    def __init__(self, db: "RestDb", path: str):
        self._db = db
        self._path = "/" + path.strip("/")

    def _url(self) -> str:
        url = self._db.base_url + ("/" if self._path == "/" else self._path) + ".json"
        if self._db.auth:
            url += "?auth=" + urllib.parse.quote(self._db.auth)
        return url

    def _request(self, method: str, data: Any = None) -> Any:
        body = None if data is None else json.dumps(data).encode("utf-8")
        req = urllib.request.Request(self._url(), data=body, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def get(self) -> Any:
        return self._request("GET")

    def set(self, value: Any) -> None:
        self._request("PUT", value)

    def update(self, value: dict) -> None:
        self._request("PATCH", value)

    def transaction(self, fn: Callable[[Any], Any]) -> Any:
        value = fn(self.get())
        self.set(value)
        return value

    def listen(self, callback: Callable[[Event], None]) -> _Registration:
        reg = _Registration()
        threading.Thread(target=self._stream, args=(callback, reg), name="firebase-rest-stream",
                         daemon=True).start()
        return reg

    def _stream(self, callback: Callable[[Event], None], reg: _Registration) -> None:
        backoff = 1.0
        while not reg._stop.is_set():
            try:
                req = urllib.request.Request(self._url(), headers={"Accept": "text/event-stream"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    reg._response = resp
                    backoff = 1.0
                    event_type = None
                    for raw in resp:
                        if reg._stop.is_set():
                            return
                        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:") and event_type in ("put", "patch"):
                            payload = json.loads(line[5:].strip())
                            callback(Event(event_type, payload.get("path", "/"), payload.get("data")))
                        elif line.startswith("data:") and event_type in ("cancel", "auth_revoked"):
                            _logger.warning("Firebase stream %s: %s", event_type, line[5:].strip())
            except Exception as exc:  # network drop, timeout (keep-alive is 30 s)
                if reg._stop.is_set():
                    return
                _logger.debug("Firebase stream reconnect: %s", exc)
            reg._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)


class RestDb:
    def __init__(self, database_url: str, auth: str = ""):
        self.base_url = database_url.rstrip("/")
        self.auth = auth

    def reference(self, path: str = "/", app: Optional[object] = None) -> RestRef:
        return RestRef(self, path)
