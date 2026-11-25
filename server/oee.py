"""OEE (Overall Equipment Effectiveness) for the current production session.

Definitions follow the MES course material:
    Availability = run time / planned production time
    Performance  = (ideal cycle time x total count) / run time
    Quality      = good count / total count
    OEE          = Availability x Performance x Quality

Planned production time = time since the session started. Every second the
line is classified as RUNNING or DOWN; DOWN time is kept per reason so the
dashboard can show why the line stopped (camera off, calibrating, ESP32
offline). Counts are the session's own inspections (PERFECT = good).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

import config

REASONS = {
    "camera_off": "Kamera mati",
    "calibrating": "Kalibrasi",
    "esp32_offline": "ESP32 offline",
}


def _ratio(num: float, den: float) -> Optional[float]:
    return num / den if den > 0 else None


class OEETracker:
    def __init__(self, pipeline, firebase, started_ms: Optional[int] = None,
                 clock: Callable[[], float] = time.time):
        self.pipeline = pipeline
        self.firebase = firebase
        self.clock = clock
        self.started_ms = started_ms or int(clock() * 1000)
        self.run_ms = 0
        self.down_ms: Dict[str, int] = {key: 0 for key in REASONS}
        self.state = "DOWN"
        self.reason = "camera_off"
        self._last_tick_ms = self.started_ms
        self._last_publish = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── line state ────────────────────────────────────────────────────────
    def _esp32_online(self, now_ms: int) -> bool:
        if not (self.firebase.enabled and getattr(config, "OEE_REQUIRE_ESP32", True)):
            return True  # no Firebase: CV-only mode, the ESP32 cannot be checked
        mirror = self.firebase.mirror() or {}
        heartbeat = int((mirror.get("conveyor") or {}).get("lastHeartbeatMs") or 0)
        return heartbeat > 0 and now_ms - heartbeat < getattr(config, "OEE_ESP32_TIMEOUT_S", 20) * 1000

    def _classify(self, now_ms: int):
        camera = self.pipeline.snapshot()
        if not camera.get("running"):
            return "DOWN", "camera_off"
        if not camera.get("calibrated"):
            return "DOWN", "calibrating"
        if not self._esp32_online(now_ms):
            return "DOWN", "esp32_offline"
        return "RUNNING", ""

    def tick(self) -> None:
        """Add the time since the previous tick to the state seen now
        (sampled once per second, so state changes are counted to ±1 s)."""
        now_ms = int(self.clock() * 1000)
        state, reason = self._classify(now_ms)
        with self._lock:
            elapsed = max(0, now_ms - self._last_tick_ms)
            self._last_tick_ms = now_ms
            self.state, self.reason = state, reason
            if state == "RUNNING":
                self.run_ms += elapsed
            else:
                self.down_ms[reason] = self.down_ms.get(reason, 0) + elapsed

    # ── numbers ───────────────────────────────────────────────────────────
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            run_ms = self.run_ms
            down = dict(self.down_ms)
            state, reason = self.state, self.reason
            planned_ms = max(0, self._last_tick_ms - self.started_ms)
        counts = self.pipeline.counts
        total = int(counts.get("total", 0))
        good = int(counts.get("perfect", 0))
        ideal_ct_s = float(getattr(config, "IDEAL_CYCLE_TIME_S", 0) or 0)

        availability = _ratio(run_ms, planned_ms)
        performance = _ratio(ideal_ct_s * 1000 * total, run_ms) if ideal_ct_s else None
        quality = _ratio(good, total)
        oee = (availability * performance * quality
               if None not in (availability, performance, quality) else None)
        return {
            "state": state,
            "reason": REASONS.get(reason, ""),
            "plannedMs": planned_ms,
            "runMs": run_ms,
            "downtimeMs": sum(down.values()),
            "downtimeByReason": {REASONS[k]: v for k, v in down.items() if v},
            "totalCount": total,
            "goodCount": good,
            "idealCycleTimeS": ideal_ct_s,
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "oee": oee,
        }

    # ── background loop ───────────────────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="oee-tracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.tick()
        self._publish(force=True)

    def _loop(self) -> None:
        while not self._stop.wait(1.0):
            self.tick()
            self._publish()

    def _publish(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < 5.0:
            return
        self._last_publish = now
        self.firebase.update_session_oee(self.snapshot())
