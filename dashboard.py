"""Simple desktop dashboard for MES Conveyor Sorting CV inspection.

Run with: python dashboard.py
This dashboard uses the existing local OpenCV inspection pipeline. It does not
require Firebase, ESP32, or any additional third-party UI package.
"""
from __future__ import annotations

import base64
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from typing import Optional

import cv2
import numpy as np

import config
from camera.camera_manager import CameraManager
from vision.background_calibrator import BackgroundCalibrator
from vision.roi_manager import ROIManager
from vision.object_detector import ObjectDetector
from vision.quality_inspector import QualityInspector
from vision.object_tracker import EventGate, READY, WAIT_CLEAR
from vision.inspection_history import InspectionHistory
from firebase_sync import FirebaseSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dashboard")

# Minimal industrial palette; intentionally no large logo or decorative graphics.
BG = "#11171c"
PANEL = "#192229"
CARD = "#202b33"
BORDER = "#2a3943"
TEXT = "#edf2f4"
MUTED = "#94a4ad"
ACCENT = "#43b979"
YELLOW = "#e4b85c"
RED = "#e06b6b"
BLUE = "#76a9d1"


class ConveyorDashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Conveyor Sorting | Quality Inspection")
        self.root.geometry("1280x850")
        self.root.minsize(1060, 740)
        self.root.configure(bg=BG)

        self.camera = CameraManager()
        self.calibrator = BackgroundCalibrator()
        self.roi_manager: Optional[ROIManager] = None
        self.detector = ObjectDetector()
        self.inspector = QualityInspector()
        self.gate = EventGate()
        self.history = InspectionHistory()
        self.firebase = FirebaseSync()

        self.running = False
        self.debug = False
        self.closing = False
        self.wait_attempts = 0
        self.total = 0
        self.perfect = 0
        self.defect = 0
        self.invalid = 0
        self.last_result = None
        self.last_event_id = ""
        self._photo = None

        self._setup_styles()
        self._build_ui()
        self._set_camera_status(False, "KAMERA MATI")
        self._set_calibration_status("Belum dikalibrasi")
        self.root.after(500, self._refresh_firebase_status)
        self.firebase.set_vision_status("offline")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "History.Treeview",
            background=CARD,
            foreground=TEXT,
            fieldbackground=CARD,
            rowheight=30,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "History.Treeview.Heading",
            background=PANEL,
            foreground=MUTED,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
        )
        style.map("History.Treeview", background=[("selected", "#31444f")])
        style.configure(
            "Cal.Horizontal.TProgressbar",
            troughcolor=CARD,
            background=ACCENT,
            bordercolor=CARD,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )

    def _label(self, parent, text, *, size=10, color=TEXT, bold=False, **kwargs):
        return tk.Label(
            parent,
            text=text,
            bg=kwargs.pop("bg", parent.cget("bg")),
            fg=color,
            font=("Segoe UI", size, "bold" if bold else "normal"),
            **kwargs,
        )

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=BG, padx=24, pady=16)
        header.pack(fill="x")
        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", fill="y")
        self._label(title_box, "CONVEYOR SORTING SYSTEM", size=9, color=ACCENT, bold=True).pack(anchor="w")
        self._label(title_box, "Quality Inspection", size=22, bold=True).pack(anchor="w", pady=(2, 0))

        controls = tk.Frame(header, bg=BG)
        controls.pack(side="right", anchor="center")
        self.start_button = self._button(controls, "Start Camera", self.start_camera, primary=True)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = self._button(controls, "Stop", self.stop_camera)
        self.stop_button.pack(side="left", padx=(0, 8))
        self.calibrate_button = self._button(controls, "Recalibrate", self.recalibrate)
        self.calibrate_button.pack(side="left", padx=(0, 8))
        self.debug_button = self._button(controls, "Debug: Off", self.toggle_debug)
        self.debug_button.pack(side="left")

        separator = tk.Frame(self.root, height=1, bg=BORDER)
        separator.pack(fill="x", padx=24)

        body = tk.Frame(self.root, bg=BG, padx=24, pady=16)
        body.pack(fill="both", expand=True)

        # System status strip
        status_row = tk.Frame(body, bg=BG)
        status_row.pack(fill="x", pady=(0, 14))
        self.camera_status = self._status_pill(status_row, "KAMERA MATI", MUTED)
        self.camera_status.pack(side="left", padx=(0, 8))
        self.calibration_status = self._status_pill(status_row, "BELUM DIKALIBRASI", YELLOW)
        self.calibration_status.pack(side="left", padx=(0, 8))
        self.gate_status = self._status_pill(status_row, "GATE: READY", BLUE)
        self.gate_status.pack(side="left", padx=(0, 8))
        self.firebase_status = self._status_pill(status_row, f"FIREBASE: {self.firebase.status}", MUTED)
        self.firebase_status.pack(side="left")
        self.clock_label = self._label(status_row, "", color=MUTED, size=9)
        self.clock_label.pack(side="right")

        # Metric cards
        metrics = tk.Frame(body, bg=BG)
        metrics.pack(fill="x", pady=(0, 14))
        self.metric_values = {}
        metric_specs = [
            ("TOTAL INSPECTION", "total", TEXT),
            ("PERFECT", "perfect", ACCENT),
            ("DEFECT", "defect", RED),
            ("INVALID", "invalid", YELLOW),
        ]
        for index, (caption, key, color) in enumerate(metric_specs):
            card = tk.Frame(metrics, bg=CARD, highlightbackground=BORDER, highlightthickness=1, padx=16, pady=12)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 8, 0))
            metrics.grid_columnconfigure(index, weight=1, uniform="metric")
            self._label(card, caption, size=9, color=MUTED, bold=True).pack(anchor="w")
            value = self._label(card, "0", size=25, color=color, bold=True)
            value.pack(anchor="w", pady=(4, 0))
            self.metric_values[key] = value

        # Main workspace
        workspace = tk.Frame(body, bg=BG)
        workspace.pack(fill="both", expand=True, pady=(0, 14))
        workspace.grid_columnconfigure(0, weight=7)
        workspace.grid_columnconfigure(1, weight=3)
        workspace.grid_rowconfigure(0, weight=1)

        video_panel = tk.Frame(workspace, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        video_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self._label(video_panel, "LIVE CAMERA", size=9, color=MUTED, bold=True, bg=PANEL).pack(anchor="w", padx=14, pady=(12, 8))
        self.video_label = tk.Label(
            video_panel,
            text="Kamera belum dijalankan\n\nKlik Start Camera untuk memulai inspeksi",
            bg="#0c1115",
            fg=MUTED,
            font=("Segoe UI", 12),
            justify="center",
        )
        self.video_label.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        side = tk.Frame(workspace, bg=BG)
        side.grid(row=0, column=1, sticky="nsew")
        side.grid_columnconfigure(0, weight=1)

        current_panel = tk.Frame(side, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=16, pady=14)
        current_panel.pack(fill="x", pady=(0, 12))
        self._label(current_panel, "HASIL INSPEKSI TERAKHIR", size=9, color=MUTED, bold=True, bg=PANEL).pack(anchor="w")
        self.current_result = self._label(current_panel, "—", size=22, color=TEXT, bold=True, bg=PANEL)
        self.current_result.pack(anchor="w", pady=(9, 3))
        self.current_event = self._label(current_panel, "Belum ada objek diperiksa", size=9, color=MUTED, bg=PANEL)
        self.current_event.pack(anchor="w")
        self.current_coverage = self._label(current_panel, "Coverage: —", size=10, color=TEXT, bg=PANEL)
        self.current_coverage.pack(anchor="w", pady=(12, 0))

        calibration_panel = tk.Frame(side, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=16, pady=14)
        calibration_panel.pack(fill="x", pady=(0, 12))
        self._label(calibration_panel, "BACKGROUND CALIBRATION", size=9, color=MUTED, bold=True, bg=PANEL).pack(anchor="w")
        self.calibration_value = self._label(calibration_panel, "0%", size=17, color=TEXT, bold=True, bg=PANEL)
        self.calibration_value.pack(anchor="w", pady=(10, 7))
        self.progress = ttk.Progressbar(calibration_panel, maximum=100, style="Cal.Horizontal.TProgressbar")
        self.progress.pack(fill="x")
        self._label(
            calibration_panel,
            "Kosongkan belt saat proses kalibrasi.",
            size=9,
            color=MUTED,
            bg=PANEL,
            wraplength=240,
            justify="left",
        ).pack(anchor="w", pady=(9, 0))

        system_panel = tk.Frame(side, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=16, pady=14)
        system_panel.pack(fill="both", expand=True)
        self._label(system_panel, "SYSTEM INFORMATION", size=9, color=MUTED, bold=True, bg=PANEL).pack(anchor="w", pady=(0, 10))
        self.gate_value = self._info_line(system_panel, "Inspection gate", "READY")
        self.camera_value = self._info_line(system_panel, "Camera index", str(config.CAMERA_INDEX))
        self.roi_value = self._info_line(system_panel, "Region of interest", "—")
        self.last_time_value = self._info_line(system_panel, "Last inspection", "—")

        # History section
        history_panel = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=14, pady=12)
        history_panel.pack(fill="x")
        history_header = tk.Frame(history_panel, bg=PANEL)
        history_header.pack(fill="x", pady=(0, 8))
        self._label(history_header, "INSPECTION HISTORY", size=9, color=MUTED, bold=True, bg=PANEL).pack(side="left")
        self._label(history_header, "Terbaru di bagian atas", size=9, color=MUTED, bg=PANEL).pack(side="right")

        columns = ("event", "time", "result", "coverage")
        self.table = ttk.Treeview(history_panel, columns=columns, show="headings", height=4, style="History.Treeview")
        self.table.heading("event", text="EVENT ID")
        self.table.heading("time", text="TIME")
        self.table.heading("result", text="RESULT")
        self.table.heading("coverage", text="RED COVERAGE")
        self.table.column("event", width=170, anchor="w")
        self.table.column("time", width=180, anchor="w")
        self.table.column("result", width=150, anchor="w")
        self.table.column("coverage", width=140, anchor="w")
        self.table.pack(fill="x")

    def _button(self, parent, text, command, primary=False):
        bg = ACCENT if primary else CARD
        fg = "#08130d" if primary else TEXT
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground="#57c989" if primary else "#2b3942",
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=13,
            pady=9,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )

    def _status_pill(self, parent, text, color):
        label = tk.Label(parent, text=f"●  {text}", bg=CARD, fg=color, padx=10, pady=6, font=("Segoe UI", 8, "bold"))
        return label

    def _info_line(self, parent, caption, value):
        line = tk.Frame(parent, bg=PANEL)
        line.pack(fill="x", pady=4)
        self._label(line, caption, size=9, color=MUTED, bg=PANEL).pack(side="left")
        value_label = self._label(line, value, size=9, color=TEXT, bold=True, bg=PANEL)
        value_label.pack(side="right")
        return value_label

    def _set_camera_status(self, online: bool, text: str):
        if hasattr(self, "camera_status"):
            self.camera_status.configure(text=f"●  {text}", fg=ACCENT if online else MUTED)

    def _set_calibration_status(self, text: str):
        if hasattr(self, "calibration_status"):
            color = ACCENT if text == "KALIBRASI SELESAI" else YELLOW
            self.calibration_status.configure(text=f"●  {text.upper()}", fg=color)

    def start_camera(self):
        if self.running:
            return
        if not self.camera.start():
            messagebox.showerror(
                "Kamera tidak tersedia",
                "Kamera tidak dapat dibuka. Periksa CAMERA_INDEX di config.py dan pastikan kamera tidak sedang digunakan aplikasi lain.",
            )
            return
        self.running = True
        self.wait_attempts = 0
        self.start_button.configure(state="disabled")
        self._set_camera_status(True, "KAMERA TERHUBUNG")
        self.firebase.set_vision_status("online")
        self._begin_calibration()
        self.root.after(40, self._update_frame)

    def stop_camera(self):
        if not self.running:
            return
        self.running = False
        self.camera.stop()
        self.start_button.configure(state="normal")
        self._set_camera_status(False, "KAMERA MATI")
        self.firebase.set_vision_status("offline")
        self.video_label.configure(image="", text="Kamera dihentikan", fg=MUTED)
        self.video_label.image = None
        self._photo = None

    def _begin_calibration(self):
        self.calibrator.reset()
        self.roi_manager = None
        self.detector = ObjectDetector()
        self.gate.reset()
        self.progress.configure(value=0)
        self.calibration_value.configure(text="0%")
        self._set_calibration_status("Sedang dikalibrasi")

    def recalibrate(self):
        if not self.running:
            messagebox.showinfo("Kamera belum aktif", "Jalankan kamera terlebih dahulu sebelum melakukan kalibrasi.")
            return
        self._begin_calibration()

    def toggle_debug(self):
        self.debug = not self.debug
        self.debug_button.configure(text=f"Debug: {'On' if self.debug else 'Off'}")

    def _update_frame(self):
        if not self.running or self.closing:
            return
        frame = self.camera.get_frame()
        if frame is None:
            self.wait_attempts += 1
            if self.wait_attempts > 50:
                self.stop_camera()
                messagebox.showerror("Kamera", "Kamera terbuka tetapi tidak mengirim gambar.")
                return
            self.root.after(40, self._update_frame)
            return

        self.wait_attempts = 0
        if self.roi_manager is None:
            height, width = frame.shape[:2]
            self.roi_manager = ROIManager(width, height)
            self.roi_value.configure(text=f"{self.roi_manager.width} × {self.roi_manager.height}")

        display = frame.copy()
        roi = self.roi_manager.get_roi(frame)
        detected = False

        if not self.calibrator.calibrated:
            self.calibrator.add_frame(roi)
            pct = int(self.calibrator.progress * 100)
            self.progress.configure(value=pct)
            self.calibration_value.configure(text=f"{pct}%")
            self._set_calibration_status("Sedang dikalibrasi")
            if self.calibrator.calibrated and self.calibrator.background is not None:
                self.detector.calibrate_background(self.calibrator.background)
                self._set_calibration_status("Kalibrasi selesai")
                logger.info("Background calibration completed")
            self.roi_manager.draw(display, color=(0, 210, 230), thickness=2)
            self._put_text(display, f"KALIBRASI {pct}% - KOSONGKAN CONVEYOR", (12, 26), (0, 210, 230))
        else:
            detections = self.detector.detect(roi)
            best_box = None
            best_mask = None
            for roi_box, roi_mask in detections:
                full_box = self.roi_manager.abs_box(roi_box)
                if self.roi_manager.is_fully_inside_roi(full_box):
                    if best_box is None or (roi_box[2] * roi_box[3] > best_box[2] * best_box[3]):
                        best_box = full_box
                        full_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                        full_mask[self.roi_manager.y1:self.roi_manager.y2, self.roi_manager.x1:self.roi_manager.x2] = roi_mask
                        best_mask = full_mask

            detected = best_box is not None
            if best_box is not None:
                x, y, w, h = best_box
                cv2.rectangle(display, (x, y), (x + w, y + h), (70, 190, 240), 2)
                if self.debug and best_mask is not None:
                    overlay = np.zeros_like(display)
                    overlay[:, :, 1] = best_mask // 2
                    display = cv2.addWeighted(display, 1.0, overlay, 0.35, 0)

            event_id = self.gate.update(detected)
            if event_id and best_box is not None and best_mask is not None:
                obj_roi, obj_mask = self.roi_manager.crop_object_with_mask(frame, best_box, best_mask)
                result = self.inspector.inspect(obj_roi, obj_mask)
                record = self.history.add(event_id, result)
                self.last_result = result
                self.last_event_id = event_id
                self.gate.mark_inspection_done()
                self._register_result(record)
                logger.info("Inspection %s: %s (coverage=%.3f)", event_id, result["classification"], result.get("red_coverage", 0))

            roi_color = (0, 210, 230) if detected else (145, 160, 170)
            self.roi_manager.draw(display, color=roi_color, thickness=2)
            state_color = (0, 210, 230) if self.gate.state in (READY, WAIT_CLEAR) else (80, 220, 120)
            self._put_text(display, f"CALIBRATED  |  GATE: {self.gate.state}", (12, 26), state_color)
            if self.last_result:
                cls = self.last_result.get("classification", "—")
                cls_color = (50, 210, 100) if cls == "PERFECT" else (70, 70, 230) if cls == "DEFECT" else (0, 210, 230)
                self._put_text(display, f"{self.last_event_id}  {cls}", (12, 54), cls_color, 0.7, 2)
            else:
                self._put_text(display, "MENUNGGU OBJEK DI AREA INSPEKSI", (12, 54), (180, 185, 190), 0.5)
            if self.debug:
                self._put_text(display, "DEBUG MODE", (12, display.shape[0] - 12), (0, 210, 230), 0.45)
            self.gate_status.configure(text=f"●  GATE: {self.gate.state}")
            self.gate_value.configure(text=self.gate.state)

        self._render_frame(display)
        self.clock_label.configure(text=datetime.now().strftime("%d %b %Y  |  %H:%M:%S"))
        self.root.after(30, self._update_frame)

    @staticmethod
    def _put_text(image, text, position, color, scale=0.52, thickness=1):
        cv2.putText(image, text, position, cv2.FONT_HERSHEY_SIMPLEX, scale, (12, 16, 20), thickness + 2, cv2.LINE_AA)
        cv2.putText(image, text, position, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)

    def _render_frame(self, frame):
        # Scale to the available panel while keeping the full camera image visible.
        target_w = max(self.video_label.winfo_width() - 8, 320)
        target_h = max(self.video_label.winfo_height() - 8, 240)
        h, w = frame.shape[:2]
        scale = min(target_w / w, target_h / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        ppm = f"P6 {new_w} {new_h} 255\n".encode("ascii") + rgb.tobytes()
        photo = tk.PhotoImage(data=base64.b64encode(ppm))
        self._photo = photo
        self.video_label.configure(image=photo, text="")
        self.video_label.image = photo

    def _register_result(self, record):
        result = record["classification"]
        self.firebase.push_inspection(record)
        self.total += 1
        if result == "PERFECT":
            self.perfect += 1
        elif result == "DEFECT":
            self.defect += 1
        else:
            self.invalid += 1

        self.metric_values["total"].configure(text=str(self.total))
        self.metric_values["perfect"].configure(text=str(self.perfect))
        self.metric_values["defect"].configure(text=str(self.defect))
        self.metric_values["invalid"].configure(text=str(self.invalid))

        colors = {"PERFECT": ACCENT, "DEFECT": RED, "INVALID": YELLOW}
        self.current_result.configure(text=result, fg=colors.get(result, TEXT))
        self.current_event.configure(text=record["event_id"])
        self.current_coverage.configure(text=f"Red coverage: {record['red_coverage']:.1%}")
        time_text = datetime.fromisoformat(record["timestamp"]).strftime("%H:%M:%S")
        self.last_time_value.configure(text=time_text)
        self.table.insert(
            "",
            0,
            values=(record["event_id"], time_text, result, f"{record['red_coverage']:.1%}"),
            tags=(result,),
        )
        self.table.tag_configure("PERFECT", foreground=ACCENT)
        self.table.tag_configure("DEFECT", foreground=RED)
        self.table.tag_configure("INVALID", foreground=YELLOW)
        children = self.table.get_children()
        if len(children) > 8:
            for item in children[8:]:
                self.table.delete(item)

    def _refresh_firebase_status(self):
        if self.closing:
            return
        status = self.firebase.status
        color = ACCENT if status == "ONLINE" else YELLOW if status in {"READY", "ERROR"} else MUTED
        self.firebase_status.configure(text=f"●  FIREBASE: {status}", fg=color)
        self.root.after(500, self._refresh_firebase_status)

    def close(self):
        self.closing = True
        if self.running:
            self.running = False
            self.camera.stop()
        self.firebase.set_vision_status("offline")
        self.firebase.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    ConveyorDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
