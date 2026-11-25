"""MES Conveyor Sorting System - single entry point.

    python main.py            # camera + inspection + Firebase + dashboard
    python main.py --no-browser

Starts the computer-vision pipeline, syncs every inspection to Firebase
(the ESP32 reads it from there and drives the SG90 servo), and serves the web
dashboard with the live camera feed at http://127.0.0.1:8765.
"""
import argparse
import logging
import threading
import time
import webbrowser

import config
from communication.firebase_sync import FirebaseSync
from server.web_server import AppContext, DashboardServer
from vision.pipeline import InspectionPipeline

logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_logger = logging.getLogger("main")


def main() -> int:
    parser = argparse.ArgumentParser(description="MES Conveyor Sorting System")
    parser.add_argument("--no-browser", action="store_true", help="do not open the dashboard automatically")
    parser.add_argument("--port", type=int, default=config.SERVER_PORT)
    parser.add_argument("--host", default=config.SERVER_HOST)
    args = parser.parse_args()

    firebase = FirebaseSync()
    pipeline = InspectionPipeline(on_record=firebase.push_inspection)
    ctx = AppContext(pipeline, firebase)
    ctx.session_started_ms = int(time.time() * 1000)

    try:
        server = DashboardServer(ctx, args.host, args.port)
    except OSError as exc:
        _logger.error("Port %d-%d sedang dipakai semua (%s). Pakai --port lain.", args.port, args.port + 9, exc)
        firebase.close()
        return 1

    firebase.start_session(pipeline.session_id)
    firebase.start_mirror()
    pipeline.start()
    if config.AUTO_START_CAMERA:
        if pipeline.start_camera():
            firebase.set_vision_status("online")
        else:
            _logger.error("%s. Ubah CAMERA_INDEX di config.py lalu klik Start Camera di dashboard.",
                          pipeline.camera_error)

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{server.port}"
    _logger.info("Dashboard: %s  (Ctrl+C untuk berhenti)", url)
    _logger.info("Firebase: %s %s", firebase.status, firebase.last_error)
    if config.OPEN_BROWSER and not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _logger.info("Stopping...")
    finally:
        server.shutdown()
        pipeline.shutdown()
        firebase.set_vision_status("offline")
        firebase.stop_session(pipeline.session_id)
        firebase.close()
        _logger.info("Selesai. Inspeksi tercatat: %d", pipeline.counts["total"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
