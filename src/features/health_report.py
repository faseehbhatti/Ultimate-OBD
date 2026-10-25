"""One-click health report: gathers every module, writes a PDF into logs/.

Executed from main.py via run_health, and from the GUI OBD tab.
Filename mirrors the session logs: Make_Model_Year_YYYYMMDD_HHMMSS_health-report.pdf
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def _safe(text: str | None, fallback: str = "Unknown") -> str:
    s = (text or "").strip() or fallback
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or fallback


def logs_dir() -> Path:
    """Project-root logs/ (this file lives in src/features/, so root is two up)."""
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    d = root if (root / "src").is_dir() else Path.cwd()
    d = d / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def report_filename(profile: dict, when: datetime | None = None) -> str:
    when = when or datetime.now()
    return (f"{_safe(profile.get('make'))}_{_safe(profile.get('model'), 'NoModel')}_"
            f"{profile.get('year') or 'NoYear'}_{when:%Y%m%d_%H%M%S}_health-report.pdf")


def gather_health(client) -> dict:
    """Run every reader; each step is isolated so one failure can't sink the report."""
    out: dict = {"at": datetime.now().isoformat(timespec="seconds"),
                 "vin": client.vin, "profile": dict(client.profile)}

    def _try(name, fn):
        try:
            out[name] = {"ok": True, "data": fn()}
        except Exception as e:
            out[name] = {"ok": False, "error": str(e)}

    _try("engine", client.read_dtcs)
    _try("abs", client.read_abs_dtcs)
    _try("tpms", client.read_tpms_dtcs)
    _try("im", client.im_readiness)
    _try("mode06", client.read_mode06)
    _try("freeze", client.read_freeze_frame)
    _try("ecu", client.read_ecu_info)

    issues = 0
    eng = out["engine"]
    if eng["ok"]:
        dtcs, info = eng["data"]
        issues += len(dtcs) + len(info.get("pending", []))
        if info.get("mil"):
            issues += 1
    for key in ("abs", "tpms"):
        if out[key]["ok"]:
            issues += len(out[key]["data"][0])
    if out["im"]["ok"] and not out["im"]["data"]["ready"]:
        issues += len(out["im"]["data"]["incomplete"])
    if out["mode06"]["ok"]:
        issues += sum(1 for m in out["mode06"]["data"]["mids"]
                      for t in m["tests"] if not t["passed"])
    out["issue_count"] = issues
    out["verdict"] = ("PASS — no issues found" if issues == 0
                      else f"ATTENTION — {issues} issue(s) found (see detail)")
    return out


def write_health_pdf(data: dict, path: Path) -> Path:
    """Render the gathered data to PDF with reportlab. Returns path."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    story = []
    prof = data["profile"]
    title = (f"OBD-II Health Report — {prof.get('make', '?')} "
             f"{prof.get('model') or ''} {prof.get('year') or ''}".strip())
    story += [Paragraph(title, styles["Title"]),
              Paragraph(f"VIN {data.get('vin') or '-'} &nbsp;&nbsp; {data['at']}",
                        styles["Normal"]),
              Paragraph(f"<b>{data['verdict']}</b>", styles["Heading2"]),
              Spacer(1, 6)]

    def section(name, rows):
        story.append(Paragraph(name, styles["Heading3"]))
        if not rows:
            story.append(Paragraph("No issues.", styles["Normal"]))
        else:
            t = Table([["Item", "Detail"]] + rows, colWidths=[170, 320], repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007AFF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E5EA")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]))
            story.append(t)
        story.append(Spacer(1, 8))

    eng, info = ([], {}) if not data["engine"]["ok"] else data["engine"]["data"]
    rows = []
    if not data["engine"]["ok"]:
        rows.append(["Engine read", data["engine"]["error"]])
    else:
        rows.append(["MIL", "ON — fault present" if info.get("mil") else "off"])
        for d in eng:
            rows.append([d.code, d.description or "—"])
        for p in info.get("pending", []):
            rows.append([f"{p} (pending)", "unconfirmed — monitor"])
        for p in info.get("permanent", []):
            rows.append([f"{p} (permanent)", "cannot be cleared until fixed + driven"])
    section("Engine (Mode 03/07)", rows)

    for key, label in (("abs", "ABS / chassis"), ("tpms", "TPMS")):
        rows = []
        if not data[key]["ok"]:
            rows.append([label, data[key]["error"]])
        else:
            codes, _info = data[key]["data"]
            for d in codes:
                rows.append([d.code, d.description or "—"])
        section(f"{label} codes", rows)

    rows = []
    if data["im"]["ok"]:
        im = data["im"]["data"]
        for m in im["monitors"]:
            st = "n/a" if not m["available"] else ("complete" if m["complete"] else "INCOMPLETE")
            rows.append([m["label"], st])
    else:
        rows.append(["I/M", data["im"]["error"]])
    section("I/M readiness", rows)

    rows = []
    if data["mode06"]["ok"]:
        for mid in data["mode06"]["data"]["mids"]:
            for t in mid["tests"]:
                rows.append([f"{mid['mid']} / {t['name']}",
                             f"{t['value']} (limits {t['limit_min']}..{t['limit_max']}) "
                             f"{'PASS' if t['passed'] else 'FAIL'}"])
    else:
        rows.append(["Mode 06", data["mode06"]["error"]])
    section("Mode 06 monitor tests", rows)

    rows = []
    if data["freeze"]["ok"]:
        fz = data["freeze"]["data"]
        rows.append(["Trigger DTC", fz.get("trigger") or "none stored"])
        for k, v in fz["pids"].items():
            rows.append([k, str(v)])
    else:
        rows.append(["Freeze frame", data["freeze"]["error"]])
    section("Freeze frame (Mode 02)", rows)

    rows = []
    if data["ecu"]["ok"]:
        e = data["ecu"]["data"]
        rows.append(["VIN", e.get("vin") or "-"])
        rows.append(["Calibration IDs", ", ".join(e["cal_ids"]) or "(unanswered)"])
        rows.append(["CVNs", ", ".join(e["cvns"]) or "(unanswered)"])
    else:
        rows.append(["ECU info", data["ecu"]["error"]])
    section("ECU info (Mode 09)", rows)

    SimpleDocTemplate(str(path), pagesize=A4,
                      title="OBD-II Health Report").build(story)
    return path


def run_health(client, args) -> int:
    """--health. Returns process exit code."""
    import sys
    print("\nGathering health report (this polls every module — up to a minute)…")
    try:
        data = gather_health(client)
    except Exception as e:
        print(f"HEALTH FAILED: {e}", file=sys.stderr)
        return 1
    print(f"  {data['verdict']}")
    try:
        path = write_health_pdf(data, logs_dir() / report_filename(client.profile))
    except ImportError:
        print("HEALTH FAILED: pip install reportlab", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"HEALTH PDF FAILED: {e}", file=sys.stderr)
        return 1
    print(f"  Saved: {path}")
    return 0
