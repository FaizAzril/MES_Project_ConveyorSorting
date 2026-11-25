"""System tests: pipeline thread, dashboard server API, camera stream and
Firebase mirror logic. No webcam, network or Firebase account needed."""
import json
import threading
import time
import unittest
import urllib.request

import cv2
import numpy as np

import config
from communication.firebase_sync import FirebaseSync, _set_path
from server.web_server import AppContext, DashboardServer
from vision.pipeline import InspectionPipeline

W, H = config.CAMERA_WIDTH, config.CAMERA_HEIGHT
BG = (90, 90, 90)


class FakeCamera:
    """Empty belt for calibration, then a cube that enters and leaves the ROI."""

    def __init__(self):
        self.color = None
        self.running = False

    def start(self):
        self.running = True
        return True

    def stop(self):
        self.running = False

    def get_frame(self):
        if not self.running:
            return None
        frame = np.full((H, W, 3), BG, dtype=np.uint8)
        if self.color == "pattern":  # red cube with a white spot
            cv2.rectangle(frame, (280, 200), (360, 280), (0, 0, 255), -1)
            cv2.rectangle(frame, (300, 220), (315, 235), (255, 255, 255), -1)
        elif self.color is not None:
            cv2.rectangle(frame, (280, 200), (360, 280), self.color, -1)
        return frame


class OfflineFirebase(FirebaseSync):
    """FirebaseSync that never connects (simulates missing .env)."""

    def __init__(self):  # noqa: D401 - skip real initialisation
        import queue
        self._queue = queue.Queue()
        self._thread = None
        self._db = None
        self._status_lock = threading.Lock()
        self._status = "NOT CONFIGURED"
        self._last_error = "test"


def wait_until(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class TestMirror(unittest.TestCase):
    def test_put_and_patch_semantics(self):
        tree = _set_path({}, [], {"vision": {"status": "offline"}, "detections": {}})
        tree = _set_path(tree, ["detections", "OBJ-1"], {"class": "PERFECT"})
        tree = _set_path(tree, ["detections", "OBJ-1", "sortAction"], "STRAIGHT")
        tree = _set_path(tree, ["vision", "status"], "online")
        self.assertEqual(tree["detections"]["OBJ-1"], {"class": "PERFECT", "sortAction": "STRAIGHT"})
        self.assertEqual(tree["vision"]["status"], "online")
        tree = _set_path(tree, ["detections", "OBJ-1"], None)
        self.assertNotIn("OBJ-1", tree.get("detections", {}))


class FakeRef:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def set(self, value):
        self.store.setdefault("set", {})[self.path] = value

    def update(self, value):
        self.store.setdefault("update", {}).setdefault(self.path, {}).update(value)

    def transaction(self, fn):
        self.store.setdefault("tx", {})[self.path] = fn(self.store.get("tx", {}).get(self.path))


class FakeDb:
    def __init__(self):
        self.store = {}

    def reference(self, path, app=None):
        return FakeRef(self.store, path)


class TestFirebaseContract(unittest.TestCase):
    """Fields written by Python must match what the ESP32 firmware reads."""

    def test_inspection_and_confirm_paths(self):
        fb = OfflineFirebase()
        fb._db, fb._app = FakeDb(), None
        fb._thread = threading.Thread(target=fb._worker, daemon=True)
        fb._thread.start()
        record = {"event_id": "OBJ-2611230000AAAA-000001", "session_id": "2611230000AAAA",
                  "classification": "DEFECT", "red_coverage": 0.5, "red_pixels": 50,
                  "object_pixels": 100, "non_red_pixels": 50, "largest_defect_area": 50,
                  "timestamp": "t", "detected_at_ms": 1764000000000}
        fb.push_inspection(record)
        fb.confirm_actual_bin(record["event_id"], "BIN2")
        fb.close()
        store = fb._db.store
        det = store["set"]["detections/OBJ-2611230000AAAA-000001"]
        self.assertEqual(det["class"], "DEFECT")            # firmware: ev["class"]
        self.assertEqual(det["detectedAtMs"], 1764000000000)  # firmware: ev["detectedAtMs"]
        self.assertEqual(store["tx"]["statistics"], {"total": 1, "defect": 1})
        self.assertEqual(store["update"]["vision"]["lastEventId"], record["event_id"])
        self.assertEqual(store["update"]["detections/OBJ-2611230000AAAA-000001"]["actualBin"], "BIN2")
        self.assertEqual(fb.status, "ONLINE")


class TestSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cam = FakeCamera()
        cls.records = []
        cls.pipeline = InspectionPipeline(on_record=cls.records.append, camera=cls.cam)
        cls.ctx = AppContext(cls.pipeline, OfflineFirebase())
        cls.server = DashboardServer(cls.ctx, "127.0.0.1", 0)
        cls.port = cls.server.httpd.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pipeline.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.pipeline.shutdown()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as r:
            return json.loads(r.read())

    def _post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())

    def _pass_cube(self, color):
        before = len(self.records)
        self.cam.color = color
        self.assertTrue(wait_until(lambda: len(self.records) > before), f"no inspection for {color}")
        self.cam.color = None
        self.assertTrue(wait_until(lambda: self.pipeline.gate.state == "READY"))
        return self.records[-1]

    def test_full_flow(self):
        self.assertTrue(self._post("/api/control", {"action": "start"})["ok"])
        self.assertTrue(wait_until(lambda: self._get("/api/state")["camera"]["calibrated"]))

        # live stream delivers JPEG frames
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/video_feed", timeout=5) as r:
            self.assertIn("multipart/x-mixed-replace", r.headers["Content-Type"])
            chunk = r.read(4096)
            self.assertIn(b"\xff\xd8", chunk)  # JPEG start marker

        self.assertEqual(self._pass_cube((0, 0, 255))["classification"], "PERFECT")
        self.assertEqual(self._pass_cube((255, 0, 0))["classification"], "DEFECT")
        self.assertEqual(self._pass_cube("pattern")["classification"], "DEFECT")

        state = self._get("/api/state")
        self.assertEqual(state["source"], "local")
        self.assertEqual(state["sessionStats"], {"total": 3, "perfect": 1, "defect": 2, "invalid": 0})
        self.assertEqual(state["history"], [])  # local mode: only the current session
        hist = self._get(f"/api/history?session={self.pipeline.session_id}")
        self.assertEqual(len(hist["events"]), 3)
        self.assertEqual(state["data"]["statistics"]["total"], 3)
        self.assertEqual(state["data"]["statistics"]["perfect"], 1)
        self.assertEqual(state["data"]["statistics"]["defect"], 2)
        ids = sorted(state["data"]["detections"])
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids, sorted(ids, key=lambda k: state["data"]["detections"][k]["detectedAtMs"]))

        # operator confirms the actual bin
        self.assertTrue(self._post("/api/confirm", {"eventId": ids[0], "actualBin": "BIN1"})["ok"])
        self.assertEqual(self._get("/api/state")["data"]["detections"][ids[0]]["actualBin"], "BIN1")
        self.assertFalse(self._post("/api/confirm", {"eventId": ids[0], "actualBin": "BIN9"})["ok"])
        self.assertFalse(self._post("/api/confirm", {"eventId": "../x", "actualBin": "BIN1"})["ok"])

        # report export: PDF and Excel with the 3 inspections
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/report?format=pdf&scope=session",
                                    timeout=10) as r:
            self.assertEqual(r.headers["Content-Type"], "application/pdf")
            self.assertIn(".pdf", r.headers["Content-Disposition"])
            self.assertTrue(r.read().startswith(b"%PDF"))
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/report?format=xlsx&scope=all",
                                    timeout=10) as r:
            body = r.read()
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(body))
        self.assertEqual(wb["Inspeksi"].max_row, 1 + 3)
        summary = {row[0]: row[1] for row in wb["Ringkasan"].iter_rows(values_only=True) if row[0]}
        self.assertEqual(summary["Total inspeksi"], 3)
        self.assertEqual(summary["PERFECT"], 1)
        self.assertEqual(summary["Sorting accuracy"], 1.0)  # 1 confirmed, correct (PERFECT in BIN1)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/report?format=doc", timeout=10)

        self.assertTrue(self._post("/api/control", {"action": "stop"})["ok"])
        self.assertFalse(self._get("/api/state")["camera"]["running"])


if __name__ == "__main__":
    unittest.main()
