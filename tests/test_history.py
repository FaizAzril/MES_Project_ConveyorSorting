"""Session history: live numbers are per session, older sessions stay
available as summaries, details and per-session reports."""
import unittest

from server import report


def det(session, n, cls, detected, sorted_at=None, actual=None):
    e = {"eventId": f"OBJ-{session}-{n:06d}", "sessionId": session, "class": cls,
         "redCoverage": 1.0 if cls == "PERFECT" else 0.0, "detectedAtMs": detected}
    if sorted_at:
        e["sortedAtMs"] = sorted_at
    if actual:
        e["actualBin"] = actual
    return e["eventId"], e


OLD, CURRENT = "261124100000AAAA", "261125090000BBBB"
DATA = {
    "session": {"id": CURRENT, "status": "running", "startedAtMs": 3_000_000},
    "sessions": {
        OLD: {"id": OLD, "status": "stopped", "startedAtMs": 1_000_000, "stoppedAtMs": 1_120_000,
              # Firebase drops null fields: no "performance" key here
              "oee": {"oee": 0.5, "availability": 0.9, "quality": 0.5, "plannedMs": 120000,
                      "runMs": 108000, "downtimeMs": 12000, "totalCount": 2, "goodCount": 1}},
        CURRENT: {"id": CURRENT, "status": "running", "startedAtMs": 3_000_000},
    },
    "detections": dict([
        det(OLD, 1, "PERFECT", 1_010_000, 1_014_000, "BIN1"),
        det(OLD, 2, "DEFECT", 1_060_000, 1_066_000, "BIN1"),   # wrong bin
        det(CURRENT, 1, "PERFECT", 3_010_000),
    ]),
}


class FakeCtx:
    def __init__(self):
        class P:
            session_id = CURRENT
        self.pipeline = P()
        self.oee = None

    def data(self, camera=None):
        return "firebase", DATA


class TestHistory(unittest.TestCase):
    def test_summaries_exclude_current_session(self):
        rows = report.session_summaries(DATA, exclude_id=CURRENT)
        self.assertEqual([r["sessionId"] for r in rows], [OLD])
        old = rows[0]
        self.assertEqual((old["total"], old["perfect"], old["defect"], old["invalid"]), (2, 1, 1, 0))
        self.assertAlmostEqual(old["avgCycleTimeS"], 5.0)        # (4 s + 6 s) / 2
        self.assertAlmostEqual(old["sortingAccuracy"], 0.5)      # one of two in the right bin
        self.assertEqual(old["oee"], 0.5)
        self.assertEqual((old["startedAtMs"], old["endedAtMs"]), (1_000_000, 1_120_000))

    def test_report_for_past_session(self):
        r = report.collect(FakeCtx(), "session", OLD)
        self.assertEqual(r["sessionId"], OLD)
        self.assertEqual(r["scopeLabel"], "Sesi sebelumnya")
        self.assertEqual(r["total"], 2)
        self.assertEqual(r["oee"]["oee"], 0.5)
        self.assertIsNone(r["oee"]["performance"])               # restored missing key
        self.assertTrue(report.to_pdf(r).startswith(b"%PDF"))
        self.assertTrue(report.to_xlsx(r).startswith(b"PK"))

    def test_report_current_session_only_has_its_events(self):
        r = report.collect(FakeCtx(), "session")
        self.assertEqual(r["sessionId"], CURRENT)
        self.assertEqual(r["total"], 1)

    def test_events_of_session(self):
        self.assertEqual(len(report.events_of(DATA, OLD)), 2)
        self.assertEqual(len(report.events_of(DATA)), 3)
        self.assertEqual(report.events_of(DATA, ""), [])


if __name__ == "__main__":
    unittest.main()
