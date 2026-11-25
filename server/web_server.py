"""Local HTTP server: dashboard files, live camera stream and control API.

GET  /video_feed      MJPEG stream of the annotated camera image
GET  /api/state       everything the dashboard shows (camera, Firebase, data)
POST /api/control     {"action": "start" | "stop" | "recalibrate" | "debug"}
POST /api/confirm     {"eventId": "...", "actualBin": "BIN1" | "BIN2"}
GET  /*               built React dashboard (web-dashboard/dist)

Standard library only, so no extra web framework is needed.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

_logger = logging.getLogger(__name__)

DIST_DIR = Path(__file__).resolve().parent.parent / "web-dashboard" / "dist"
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VALID_BINS = {"BIN1", "BIN2"}

NOT_BUILT_PAGE = """<!doctype html><html lang="id"><meta charset="utf-8">
<title>Dashboard belum di-build</title>
<body style="font-family:sans-serif;background:#101010;color:#eee;padding:40px">
<h2>Dashboard web belum di-build</h2>
<p>Jalankan sekali:</p>
<pre style="background:#222;padding:12px">cd web-dashboard
npm install
npm run build</pre>
<p>lalu muat ulang halaman ini. Stream kamera tetap tersedia di <a style="color:#9cf" href="/video_feed">/video_feed</a>.</p>
</body></html>"""


def record_to_db(record: Dict[str, Any]) -> Dict[str, Any]:
    """Local inspection record -> same shape the dashboard reads from Firebase."""
    out = {
        "eventId": record["event_id"],
        "sessionId": record.get("session_id", ""),
        "class": record["classification"],
        "redCoverage": record["red_coverage"],
        "redPixels": record["red_pixels"],
        "objectPixels": record["object_pixels"],
        "nonRedPixels": record["non_red_pixels"],
        "largestDefectArea": record.get("largest_defect_area", 0),
        "timestamp": record["timestamp"],
        "detectedAtMs": record["detected_at_ms"],
    }
    if record.get("actual_bin"):
        out["actualBin"] = record["actual_bin"]
        out["confirmedAtMs"] = record.get("confirmed_at_ms")
    return out


class AppContext:
    """Glue between the HTTP handler, the CV pipeline and Firebase."""

    def __init__(self, pipeline, firebase):
        self.pipeline = pipeline
        self.firebase = firebase

    def state(self) -> Dict[str, Any]:
        camera = self.pipeline.snapshot()
        mirror = self.firebase.mirror() if self.firebase.enabled else None
        if mirror is not None:
            data = mirror
            source = "firebase"
        else:
            records = self.pipeline.history.latest(100)
            last = self.pipeline.last_record
            data = {
                "session": {"id": self.pipeline.session_id,
                            "status": "running" if camera["running"] else "stopped",
                            "startedAtMs": getattr(self, "session_started_ms", None)},
                "vision": {
                    "status": "online" if camera["running"] else "offline",
                    "lastClass": last["classification"] if last else "",
                    "lastEventId": last["event_id"] if last else "",
                    "lastDetectionMs": last["detected_at_ms"] if last else None,
                    "redCoverage": last["red_coverage"] if last else 0,
                },
                "statistics": dict(self.pipeline.counts),
                "detections": {r["event_id"]: record_to_db(r) for r in records},
            }
            source = "local"
        detections = data.get("detections") or {}
        if len(detections) > 200:  # newest first by time-ordered key
            data["detections"] = {k: detections[k] for k in sorted(detections)[-200:]}
        return {
            "source": source,
            "camera": camera,
            "firebase": {"status": self.firebase.status, "error": self.firebase.last_error},
            "data": data,
        }

    def control(self, action: str) -> Dict[str, Any]:
        p = self.pipeline
        if action == "start":
            ok = p.start_camera()
            if ok:
                self.firebase.set_vision_status("online")
            return {"ok": ok, "error": p.camera_error}
        if action == "stop":
            p.stop_camera()
            self.firebase.set_vision_status("offline")
            return {"ok": True}
        if action == "recalibrate":
            ok = p.recalibrate()
            return {"ok": ok, "error": "" if ok else "Kamera belum berjalan"}
        if action == "debug":
            p.debug = not p.debug
            return {"ok": True, "debug": p.debug}
        return {"ok": False, "error": f"Aksi tidak dikenal: {action}"}

    def confirm(self, event_id: str, actual_bin: str) -> Dict[str, Any]:
        if not EVENT_ID_RE.match(event_id or ""):
            return {"ok": False, "error": "eventId tidak valid"}
        if actual_bin not in VALID_BINS:
            return {"ok": False, "error": "actualBin harus BIN1 atau BIN2"}
        record = self.pipeline.history.find(event_id)
        if record is not None:
            import time
            record["actual_bin"] = actual_bin
            record["confirmed_at_ms"] = int(time.time() * 1000)
        if self.firebase.enabled:
            self.firebase.confirm_actual_bin(event_id, actual_bin)
        elif record is None:
            return {"ok": False, "error": "Event tidak ditemukan"}
        return {"ok": True}


def make_handler(ctx: AppContext):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MESConveyor/1.0"

        def log_message(self, fmt, *args):  # keep the console quiet
            _logger.debug("%s - %s", self.address_string(), fmt % args)

        # ── helpers ──
        def _json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Optional[Dict[str, Any]]:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 10_000:
                    return None
                data = json.loads(self.rfile.read(length) or b"{}")
                return data if isinstance(data, dict) else None
            except (ValueError, json.JSONDecodeError):
                return None

        # ── routes ──
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                return self._json(ctx.state())
            if path == "/video_feed":
                return self._stream()
            return self._static(path)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            body = self._read_json()
            if body is None:
                return self._json({"ok": False, "error": "JSON tidak valid"}, 400)
            if path == "/api/control":
                return self._json(ctx.control(str(body.get("action", ""))))
            if path == "/api/confirm":
                result = ctx.confirm(str(body.get("eventId", "")), str(body.get("actualBin", "")))
                return self._json(result, 200 if result["ok"] else 400)
            return self._json({"ok": False, "error": "Not found"}, 404)

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seq = -1
            try:
                while True:
                    seq, jpeg = ctx.pipeline.wait_jpeg(seq, timeout=1.0)
                    if jpeg is None:
                        if not ctx.pipeline.camera_running:
                            break  # browser shows the placeholder; it reconnects on start
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _static(self, path: str):
            if not DIST_DIR.is_dir():
                body = NOT_BUILT_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            target = (DIST_DIR / path.lstrip("/")).resolve()
            if DIST_DIR.resolve() not in target.parents and target != DIST_DIR.resolve():
                return self._json({"error": "Not found"}, 404)
            if not target.is_file():
                target = DIST_DIR / "index.html"  # single-page app fallback
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".js":
                ctype = "text/javascript"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class _ExclusiveHTTPServer(ThreadingHTTPServer):
    """HTTP server that owns its port exclusively.

    http.server enables SO_REUSEADDR, which on Windows lets two programs bind
    the same port: the browser then reaches whichever answers (e.g. another
    project's dev server on 8000). Here binding fails instead if it is taken.
    """

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows only
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DashboardServer:
    def __init__(self, ctx: AppContext, host: str, port: int, tries: int = 10):
        """Bind to port, or the next free one (up to `tries` ports). port 0 = any."""
        last_error: Optional[OSError] = None
        for candidate in ([port] if port == 0 else range(port, port + tries)):
            try:
                self.httpd = _ExclusiveHTTPServer((host, candidate), make_handler(ctx))
                break
            except OSError as exc:
                last_error = exc
                _logger.warning("Port %d sedang dipakai program lain, mencoba port berikutnya", candidate)
        else:
            raise last_error
        self.port = self.httpd.server_address[1]

    def serve_forever(self) -> None:
        self.httpd.serve_forever(poll_interval=0.5)

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
