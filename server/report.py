"""Production report export (PDF or Excel) for the MES dashboard.

Report content: production summary, KPIs (cycle time, production rate,
sorting accuracy), OEE with downtime per reason (current session only) and
the detail of every inspection. KPI definitions are the same as on the
dashboard (web-dashboard/src/App.jsx) and in the proposal (section E.1).
"""
from __future__ import annotations

import io
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

EXPECTED_BIN = {"PERFECT": "BIN1", "DEFECT": "BIN2", "INVALID": "BIN2"}
SCOPES = {"session": "Sesi ini", "all": "Semua data"}


# ── data ──────────────────────────────────────────────────────────────────
def _fmt_time(ms: Optional[float], with_date: bool = True) -> str:
    if not ms:
        return "-"
    dt = datetime.fromtimestamp(float(ms) / 1000.0)
    return dt.strftime("%d-%m-%Y %H:%M:%S" if with_date else "%H:%M:%S")


def _fmt_duration(ms: Optional[float]) -> str:
    if ms is None:
        return "-"
    s = int(round(float(ms) / 1000))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}j {m:02d}m {s:02d}d" if h else f"{m}m {s:02d}d"


def _pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{v * 100:.1f}%"


def _event(key: str, e: Dict[str, Any]) -> Dict[str, Any]:
    cls = str(e.get("class") or "INVALID").upper()
    detected, sorted_at = e.get("detectedAtMs"), e.get("sortedAtMs")
    ct = ((sorted_at - detected) / 1000.0
          if detected and sorted_at and sorted_at >= detected else None)
    actual = e.get("actualBin")
    return {
        "eventId": e.get("eventId") or key,
        "sessionId": e.get("sessionId") or "",
        "detectedAtMs": detected,
        "class": cls,
        "redCoverage": float(e.get("redCoverage") or 0.0),
        "largestDefectArea": int(e.get("largestDefectArea") or 0),
        "sortAction": e.get("sortAction") or "",
        "cycleTimeS": ct,
        "expectedBin": EXPECTED_BIN.get(cls, "BIN2"),
        "actualBin": actual or "",
        "correct": None if not actual else actual == EXPECTED_BIN.get(cls, "BIN2"),
    }


def events_of(data: Dict[str, Any], session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Inspections in time order; only one session's when session_id is given."""
    out = []
    for key, e in sorted((data.get("detections") or {}).items()):
        if not isinstance(e, dict):
            continue
        if session_id is not None and (e.get("sessionId") or "") != session_id:
            continue
        out.append(_event(key, e))
    return out


def _stats(events: List[Dict[str, Any]], start: Optional[float], end: Optional[float]) -> Dict[str, Any]:
    counts = {k: sum(1 for e in events if e["class"] == k) for k in ("PERFECT", "DEFECT", "INVALID")}
    total = len(events)
    cts = [e["cycleTimeS"] for e in events if e["cycleTimeS"] is not None]
    confirmed = [e for e in events if e["correct"] is not None]
    minutes = (end - start) / 60000.0 if start and end and end > start else None
    return {
        "counts": counts,
        "total": total,
        "kpi": {
            "avgCycleTimeS": sum(cts) / len(cts) if cts else None,
            "sortedCount": len(cts),
            "productionRate": total / minutes if minutes else None,
            "sortingAccuracy": (sum(1 for e in confirmed if e["correct"]) / len(confirmed)) if confirmed else None,
            "confirmedCount": len(confirmed),
            "correctCount": sum(1 for e in confirmed if e["correct"]),
        },
    }


def session_summaries(data: Dict[str, Any], exclude_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """One row per past session (newest first) for the history section."""
    archive = data.get("sessions") or {}
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events_of(data):
        groups.setdefault(ev["sessionId"], []).append(ev)
    for sid in archive:  # sessions without any inspection are history too
        groups.setdefault(sid, [])
    rows = []
    for sid, events in groups.items():
        if sid == exclude_id:
            continue
        meta = archive.get(sid) or {}
        times = [e["detectedAtMs"] for e in events if e["detectedAtMs"]]
        start = meta.get("startedAtMs") or (min(times) if times else None)
        end = meta.get("stoppedAtMs") or (max(times) if times else None)
        st = _stats(events, start, end)
        oee = meta.get("oee") or {}
        rows.append({
            "sessionId": sid or "(tanpa sesi)",
            "startedAtMs": start,
            "endedAtMs": end,
            "total": st["total"],
            **{k.lower(): v for k, v in st["counts"].items()},
            "avgCycleTimeS": st["kpi"]["avgCycleTimeS"],
            "sortingAccuracy": st["kpi"]["sortingAccuracy"],
            "oee": oee.get("oee"),
        })
    rows.sort(key=lambda r: r["startedAtMs"] or 0, reverse=True)
    return rows


def _norm_oee(o: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Archived OEE from Firebase drops null fields: restore every key."""
    if not o:
        return None
    full = {"state": "", "reason": "", "plannedMs": 0, "runMs": 0, "downtimeMs": 0,
            "downtimeByReason": {}, "totalCount": 0, "goodCount": 0, "idealCycleTimeS": 0,
            "availability": None, "performance": None, "quality": None, "oee": None}
    full.update(o)
    return full


def collect(ctx, scope: str = "session", session_id: Optional[str] = None) -> Dict[str, Any]:
    """Gather everything the report shows. scope=session reports the current
    session, or the past session ``session_id``; scope=all reports everything."""
    scope = scope if scope in SCOPES else "session"
    source, data = ctx.data()
    current = (data.get("session") or {}).get("id") or ctx.pipeline.session_id
    now_ms = int(time.time() * 1000)

    if scope == "session":
        sid = current if session_id is None else session_id
        events = events_of(data, sid)
        if sid == current:
            session = data.get("session") or {}
            start = session.get("startedAtMs") or getattr(ctx, "session_started_ms", None)
            end = session.get("stoppedAtMs") if session.get("status") == "stopped" else now_ms
            oee = ctx.oee.snapshot() if getattr(ctx, "oee", None) else None
        else:
            meta = (data.get("sessions") or {}).get(sid) or {}
            times = [e["detectedAtMs"] for e in events if e["detectedAtMs"]]
            start = meta.get("startedAtMs") or (min(times) if times else None)
            end = meta.get("stoppedAtMs") or (max(times) if times else None)
            oee = _norm_oee(meta.get("oee"))
    else:
        sid = None
        events = events_of(data)
        times = [e["detectedAtMs"] for e in events if e["detectedAtMs"]]
        start, end = (min(times), max(times)) if times else (None, None)
        oee = None

    st = _stats(events, start, end)
    return {
        "scope": scope,
        "scopeLabel": SCOPES[scope] if sid in (None, current) else "Sesi sebelumnya",
        "source": "Firebase" if source == "firebase" else "Lokal",
        "sessionId": sid or current,
        "periodStartMs": start,
        "periodEndMs": end,
        "generatedAtMs": now_ms,
        "counts": st["counts"],
        "total": st["total"],
        "kpi": st["kpi"],
        "oee": oee,
        "events": events,
    }


def filename(report: Dict[str, Any], ext: str) -> str:
    stamp = datetime.fromtimestamp(report["generatedAtMs"] / 1000).strftime("%Y%m%d-%H%M")
    part = report["sessionId"] if report["scope"] == "session" else "semua"
    return f"Laporan_ConveyorSorting_{part}_{stamp}.{ext}"


def _summary_rows(r: Dict[str, Any]) -> List[List[str]]:
    c, k, total = r["counts"], r["kpi"], r["total"]
    share = (lambda n: f"{n} ({n / total * 100:.1f}%)") if total else (lambda n: str(n))
    return [
        ["Total inspeksi", str(total)],
        ["PERFECT (merah polos, BIN1)", share(c["PERFECT"])],
        ["DEFECT (bercorak / bukan merah, BIN2)", share(c["DEFECT"])],
        ["INVALID (gagal dibaca, BIN2)", share(c["INVALID"])],
        ["Rata-rata cycle time", "-" if k["avgCycleTimeS"] is None
         else f"{k['avgCycleTimeS']:.2f} detik ({k['sortedCount']} objek tersortir)"],
        ["Production rate", "-" if k["productionRate"] is None else f"{k['productionRate']:.2f} objek/menit"],
        ["Sorting accuracy", "-" if k["sortingAccuracy"] is None
         else f"{_pct(k['sortingAccuracy'])} ({k['correctCount']}/{k['confirmedCount']} dikonfirmasi)"],
    ]


def _oee_rows(o: Dict[str, Any]) -> List[List[str]]:
    return [
        ["OEE", _pct(o["oee"])],
        ["Availability", f"{_pct(o['availability'])}  (berjalan {_fmt_duration(o['runMs'])} "
                         f"dari {_fmt_duration(o['plannedMs'])})"],
        ["Performance", f"{_pct(o['performance'])}  ({o['totalCount']} objek x CT ideal "
                        f"{o['idealCycleTimeS']} detik / waktu berjalan)"],
        ["Quality", f"{_pct(o['quality'])}  ({o['goodCount']} PERFECT dari {o['totalCount']})"],
        ["Total downtime", _fmt_duration(o["downtimeMs"])],
    ]


# ── PDF ───────────────────────────────────────────────────────────────────
def to_pdf(r: Dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font, bold = _register_fonts()
    ink, muted, line, head = (colors.HexColor("#1f2933"), colors.HexColor("#5b6670"),
                              colors.HexColor("#d0d5da"), colors.HexColor("#f2f4f6"))
    tone = {"PERFECT": colors.HexColor("#1e7b45"), "DEFECT": colors.HexColor("#b42318"),
            "INVALID": colors.HexColor("#a15c00")}
    base = ParagraphStyle("b", parent=getSampleStyleSheet()["Normal"], fontName=font, fontSize=9.5,
                          leading=13, textColor=ink)
    small = ParagraphStyle("s", parent=base, fontSize=8, leading=10.5, textColor=muted)
    h1 = ParagraphStyle("h1", parent=base, fontName=bold, fontSize=17, leading=21, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base, fontName=bold, fontSize=11.5, leading=15, spaceBefore=10,
                        spaceAfter=5)

    def kv_table(rows):
        t = Table([[Paragraph(a, base), Paragraph(b, base)] for a, b in rows], colWidths=[6 * cm, 11 * cm])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, line),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        return t

    story = [
        Paragraph("Laporan Produksi - Conveyor Sorting System", h1),
        Paragraph(f"Mini MES · {r['scopeLabel']} · sumber data {r['source']}", small),
        Spacer(1, 6),
        kv_table([
            ["ID sesi", r["sessionId"] if r["scope"] == "session" else "Semua sesi"],
            ["Periode", f"{_fmt_time(r['periodStartMs'])} s/d {_fmt_time(r['periodEndMs'])}"],
            ["Dibuat", _fmt_time(r["generatedAtMs"])],
        ]),
        Paragraph("Ringkasan produksi", h2),
        kv_table(_summary_rows(r)),
    ]
    o = r["oee"]
    story.append(Paragraph("OEE (Overall Equipment Effectiveness)", h2))
    if o:
        story.append(kv_table(_oee_rows(o)))
        if o.get("performance") and o["performance"] > 1:
            story += [Spacer(1, 4), Paragraph(
                "Catatan: Performance di atas 100% berarti cycle time ideal "
                "(IDEAL_CYCLE_TIME_S di config.py) lebih besar dari kemampuan nyata line; "
                "sesuaikan nilainya agar OEE bermakna.", small)]
        reasons = o.get("downtimeByReason") or {}
        if reasons:
            story += [Spacer(1, 4), Paragraph("Downtime per alasan: " + ", ".join(
                f"{k} {_fmt_duration(v)}" for k, v in reasons.items()), small)]
    else:
        story.append(Paragraph("OEE dihitung per sesi produksi; pilih cakupan \"Sesi ini\" untuk "
                               "menampilkannya.", small))

    story.append(Paragraph(f"Detail inspeksi ({r['total']} objek)", h2))
    header = ["No", "Event ID", "Waktu", "Hasil", "Red cov.", "Bercak px", "Aksi ESP32", "CT (s)", "Wadah"]
    rows = [header]
    for i, e in enumerate(r["events"], 1):
        actual = e["actualBin"] or "-"
        if e["correct"] is False:
            actual += " (salah)"
        rows.append([str(i), e["eventId"].split("-")[-1], _fmt_time(e["detectedAtMs"], with_date=False),
                     e["class"], f"{e['redCoverage'] * 100:.1f}%", str(e["largestDefectArea"]),
                     e["sortAction"] or "-", "-" if e["cycleTimeS"] is None else f"{e['cycleTimeS']:.2f}",
                     actual])
    if len(rows) == 1:
        rows.append(["-", "Belum ada inspeksi", "", "", "", "", "", "", ""])
    t = Table(rows, colWidths=[0.9 * cm, 1.8 * cm, 1.9 * cm, 1.9 * cm, 1.7 * cm, 1.8 * cm, 2.2 * cm,
                               1.5 * cm, 3.3 * cm], repeatRows=1)
    style = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8),
             ("FONTNAME", (0, 0), (-1, 0), bold), ("BACKGROUND", (0, 0), (-1, 0), head),
             ("LINEBELOW", (0, 0), (-1, 0), 0.8, ink), ("LINEBELOW", (0, 1), (-1, -1), 0.3, line),
             ("TEXTCOLOR", (0, 1), (-1, -1), ink), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    for i, e in enumerate(r["events"], 1):
        style.append(("TEXTCOLOR", (3, i), (3, i), tone.get(e["class"], ink)))
        style.append(("FONTNAME", (3, i), (3, i), bold))
    t.setStyle(TableStyle(style))
    story.append(t)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(2 * cm, 1.2 * cm, f"Laporan Conveyor Sorting System · {r['scopeLabel']} · "
                                            f"dibuat {_fmt_time(r['generatedAtMs'])}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Halaman {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.7 * cm,
                            bottomMargin=1.8 * cm, title="Laporan Produksi Conveyor Sorting System",
                            author="Mini MES Conveyor Sorting")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _register_fonts():
    """Arial (Windows) for full character support, Helvetica otherwise."""
    from pathlib import Path
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    regular, boldf = Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")
    if regular.is_file() and boldf.is_file():
        if "ReportArial" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ReportArial", str(regular)))
            pdfmetrics.registerFont(TTFont("ReportArial-Bold", str(boldf)))
        return "ReportArial", "ReportArial-Bold"
    return "Helvetica", "Helvetica-Bold"


# ── Excel ─────────────────────────────────────────────────────────────────
def to_xlsx(r: Dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="F2F4F6")
    tone = {"PERFECT": "1E7B45", "DEFECT": "B42318", "INVALID": "A15C00"}

    wb = Workbook()
    ws = wb.active
    ws.title = "Ringkasan"
    ws.append(["Laporan Produksi - Conveyor Sorting System"])
    ws["A1"].font = Font(bold=True, size=14)
    rows = [
        ("Cakupan", r["scopeLabel"]),
        ("ID sesi", r["sessionId"] if r["scope"] == "session" else "Semua sesi"),
        ("Sumber data", r["source"]),
        ("Periode mulai", _fmt_time(r["periodStartMs"])),
        ("Periode selesai", _fmt_time(r["periodEndMs"])),
        ("Dibuat", _fmt_time(r["generatedAtMs"])),
        (None, None),
        ("Total inspeksi", r["total"]),
        ("PERFECT", r["counts"]["PERFECT"]),
        ("DEFECT", r["counts"]["DEFECT"]),
        ("INVALID", r["counts"]["INVALID"]),
        ("Rata-rata cycle time (detik)", r["kpi"]["avgCycleTimeS"]),
        ("Production rate (objek/menit)", r["kpi"]["productionRate"]),
        ("Sorting accuracy", r["kpi"]["sortingAccuracy"]),
        ("Objek dikonfirmasi operator", r["kpi"]["confirmedCount"]),
    ]
    o = r["oee"]
    if o:
        rows += [
            (None, None),
            ("OEE", o["oee"]),
            ("Availability", o["availability"]),
            ("Performance", o["performance"]),
            ("Quality", o["quality"]),
            ("Waktu terencana (detik)", round(o["plannedMs"] / 1000)),
            ("Waktu berjalan (detik)", round(o["runMs"] / 1000)),
            ("Total downtime (detik)", round(o["downtimeMs"] / 1000)),
            ("Cycle time ideal (detik)", o["idealCycleTimeS"]),
        ]
    percent_keys = {"Sorting accuracy", "OEE", "Availability", "Performance", "Quality"}
    for key, value in rows:
        ws.append([key, value if value is not None or key is None else "-"])
        if key in percent_keys and isinstance(value, (int, float)):
            ws.cell(ws.max_row, 2).number_format = "0.0%"
        elif isinstance(value, float):
            ws.cell(ws.max_row, 2).number_format = "0.00"
        if key:
            ws.cell(ws.max_row, 1).font = bold
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 26

    di = wb.create_sheet("Inspeksi")
    header = ["No", "Event ID", "Waktu deteksi", "Hasil", "Red coverage", "Bercak terbesar (px)",
              "Aksi ESP32", "Cycle time (detik)", "Wadah seharusnya", "Wadah aktual", "Sortir benar"]
    di.append(header)
    for cell in di[1]:
        cell.font = bold
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for i, e in enumerate(r["events"], 1):
        di.append([
            i, e["eventId"],
            datetime.fromtimestamp(e["detectedAtMs"] / 1000) if e["detectedAtMs"] else None,
            e["class"], e["redCoverage"], e["largestDefectArea"], e["sortAction"] or None,
            e["cycleTimeS"], e["expectedBin"], e["actualBin"] or None,
            None if e["correct"] is None else ("Ya" if e["correct"] else "Tidak"),
        ])
        row = di.max_row
        di.cell(row, 3).number_format = "dd-mm-yyyy hh:mm:ss"
        di.cell(row, 5).number_format = "0.0%"
        di.cell(row, 8).number_format = "0.00"
        di.cell(row, 4).font = Font(bold=True, color=tone.get(e["class"], "000000"))
    widths = [6, 30, 20, 11, 13, 14, 12, 14, 14, 13, 12]
    for col, w in enumerate(widths, 1):
        di.column_dimensions[get_column_letter(col)].width = w
    di.freeze_panes = "A2"
    if r["events"]:
        di.auto_filter.ref = f"A1:{get_column_letter(len(header))}{di.max_row}"

    if o:
        dt = wb.create_sheet("Downtime")
        dt.append(["Alasan", "Durasi (detik)"])
        for cell in dt[1]:
            cell.font = bold
            cell.fill = head_fill
        for reason, ms in (o.get("downtimeByReason") or {}).items():
            dt.append([reason, round(ms / 1000)])
        dt.column_dimensions["A"].width = 22
        dt.column_dimensions["B"].width = 16

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
