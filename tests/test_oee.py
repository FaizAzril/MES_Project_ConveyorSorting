"""OEE tracker: availability from run/down time, performance from the ideal
cycle time, quality from PERFECT / total, OEE = A x P x Q."""
import unittest
from unittest import mock

import config
from server.oee import OEETracker


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakePipeline:
    def __init__(self):
        self.camera = {"running": True, "calibrated": True}
        self.counts = {"total": 0, "perfect": 0, "defect": 0, "invalid": 0}

    def snapshot(self):
        return dict(self.camera)


class FakeFirebase:
    def __init__(self, enabled=False, heartbeat_ms=0):
        self.enabled = enabled
        self.heartbeat_ms = heartbeat_ms
        self.published = []

    def mirror(self):
        return {"conveyor": {"lastHeartbeatMs": self.heartbeat_ms}}

    def update_session_oee(self, oee):
        self.published.append(oee)


def run(tracker, clock, seconds):
    """Tick once per second, like the background loop."""
    for _ in range(seconds):
        clock.advance(1)
        tracker.tick()


class TestOEE(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.pipe = FakePipeline()

    def make(self, firebase=None):
        tracker = OEETracker(self.pipe, firebase or FakeFirebase(), clock=self.clock,
                             started_ms=int(self.clock() * 1000))
        tracker.tick()
        return tracker

    @mock.patch.object(config, "IDEAL_CYCLE_TIME_S", 6.0)
    def test_course_style_example(self):
        # 480 s planned, 60 s down (camera stopped), 60 objects of which 54 good.
        t = self.make()
        run(t, self.clock, 420)
        self.pipe.camera["running"] = False
        run(t, self.clock, 60)
        self.pipe.counts.update(total=60, perfect=54)
        s = t.snapshot()
        self.assertEqual(s["plannedMs"], 480_000)
        self.assertEqual(s["runMs"], 420_000)
        self.assertEqual(s["downtimeByReason"], {"Kamera mati": 60_000})
        self.assertAlmostEqual(s["availability"], 420 / 480)          # 87.5 %
        self.assertAlmostEqual(s["performance"], 6 * 60 / 420)        # 85.7 %
        self.assertAlmostEqual(s["quality"], 54 / 60)                 # 90 %
        self.assertAlmostEqual(s["oee"], (420 / 480) * (360 / 420) * 0.9)
        self.assertEqual(s["state"], "DOWN")
        self.assertEqual(s["reason"], "Kamera mati")

    def test_no_objects_yet(self):
        t = self.make()
        run(t, self.clock, 30)
        s = t.snapshot()
        self.assertAlmostEqual(s["availability"], 1.0)
        self.assertIsNone(s["quality"])
        self.assertIsNone(s["oee"])

    def test_calibration_counts_as_downtime(self):
        self.pipe.camera["calibrated"] = False
        t = self.make()
        run(t, self.clock, 10)
        self.pipe.camera["calibrated"] = True
        run(t, self.clock, 30)
        s = t.snapshot()
        self.assertEqual(s["downtimeByReason"], {"Kalibrasi": 10_000})
        self.assertAlmostEqual(s["availability"], 30 / 40)

    def test_esp32_offline_is_downtime_when_firebase_is_used(self):
        fb = FakeFirebase(enabled=True, heartbeat_ms=int(self.clock() * 1000))
        t = self.make(fb)
        run(t, self.clock, 10)        # heartbeat fresh: running
        run(t, self.clock, 30)        # heartbeat now >20 s old: down
        s = t.snapshot()
        self.assertEqual(s["state"], "DOWN")
        self.assertEqual(s["reason"], "ESP32 offline")
        self.assertIn("ESP32 offline", s["downtimeByReason"])
        self.assertLess(s["availability"], 1.0)

    def test_esp32_ignored_without_firebase(self):
        t = self.make(FakeFirebase(enabled=False))
        run(t, self.clock, 30)
        self.assertEqual(t.snapshot()["state"], "RUNNING")

    def test_publish_to_firebase_on_stop(self):
        fb = FakeFirebase()
        t = self.make(fb)
        run(t, self.clock, 5)
        t.stop()
        self.assertTrue(fb.published)
        self.assertIn("oee", fb.published[-1])


if __name__ == "__main__":
    unittest.main()
