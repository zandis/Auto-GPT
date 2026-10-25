"""DL-1 renderers: PDF (reportlab), XLSX (openpyxl) and JSON from the frozen pack object only (spec v4 §12.4 formats,
§12.11; RPT-03, RPT-06, RPT-12, RPT-32, RPT-35, RPT-53).

Renderers are pure: they never query data, never call a model and print only what the frozen object holds. They
refuse an object whose hash or ``disclosure_trace`` does not check (:func:`deliverables.pack.verify_frozen`). Output
bytes are deterministic (reportlab invariant mode, fixed workbook properties), so a re-render is byte-identical.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from deliverables.pack import verify_frozen

FIXED_TIME = datetime(2000, 1, 1)


def _cell(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.1f}"
    return str(v)


# ------------------------------------------------------------------------------------------------ PDF
def render_pdf(frozen: Mapping[str, Any]) -> bytes:
    obj = verify_frozen(frozen)
    from reportlab import rl_config
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rl_config.invariant = 1
    try:
        from orchestrator.reports.common import pdf_fonts

        regular, bold = pdf_fonts("zh-TW")
    except Exception:  # fonts not fetched: built-in Helvetica (CJK text then shows as boxes)
        regular, bold = "Helvetica", "Helvetica-Bold"
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName=regular, fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=9, leading=11)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName=bold, fontSize=14)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName=bold, fontSize=11)
    panel = ParagraphStyle(
        "na", parent=body, textColor=colors.HexColor("#595959"), backColor=colors.HexColor("#F2F2F2")
    )
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(
        buf,
        pagesize=page,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"DL-1 feasibility pack {obj['study_id']}",
        author="TrialBox",
        subject="Feasibility pack (aggregate, disclosed)",
        creator="TrialBox deliverables",
    )
    width = page[0] - 28 * mm
    story: list[Any] = []
    pngs = frozen.get("pngs", {})
    prof = obj["profile"]

    def footer(canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.drawString(
            14 * mm,
            8 * mm,
            f"TrialBox {obj['site']['id']} · DL-1 {obj['study_id']} · ruleset {obj['ruleset']['id']} "
            f"v{obj['ruleset']['version']} · snapshot {obj['snapshot']['id']} · disclosure {prof['name']} "
            f"v{prof['version']} · object {frozen['sha256'][:19]} · page {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    def table(tid: str) -> None:
        rows = obj["tables"].get(tid)
        story.append(Paragraph(escape(tid), h2))
        if isinstance(rows, dict) and "not_available" in rows:
            story.append(Paragraph(escape(f"not available: {rows['not_available']}"), panel))
            return
        if not rows:
            story.append(Paragraph("not available: empty", panel))
            return
        keys = list(rows[0].keys())
        data = [[Paragraph(f"<b>{escape(k)}</b>", small) for k in keys]]
        for r in rows:
            data.append([Paragraph(escape(_cell(r.get(k)))[:300], small) for k in keys])
        t = Table(data, repeatRows=1, colWidths=[width / len(keys)] * len(keys))
        t.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#767676")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 4 * mm))

    def figure(fid: str) -> None:
        f = obj["figures"].get(fid, {"not_available": "missing"})
        story.append(Paragraph(escape(f"{fid} {f.get('title', '')}"), h2))
        if "not_available" in f:
            story.append(Paragraph(escape(f"not available: {f['not_available']}"), panel))
            return
        img = Image(io.BytesIO(pngs[fid]))
        scale = min((170 * mm) / img.drawWidth, (120 * mm) / img.drawHeight)
        img.drawWidth, img.drawHeight = img.drawWidth * scale, img.drawHeight * scale
        story.append(img)
        story.append(Paragraph(escape("Alt text: " + f["alt"]), small))
        story.append(Spacer(1, 4 * mm))

    hl = obj["headline"]
    story.append(Paragraph(escape(f"Feasibility pack (DL-1): {obj['ruleset']['id']} at {obj['site']['name']}"), h1))
    adj = hl["adjusted_estimate"]
    p12 = hl["projection_12m"]
    story.append(
        Paragraph(
            escape(
                f"Computable count: {_cell(hl['computable_count'])} (computable: decided by records; the unknown "
                f"share is in F-T5 and F-T8). Adjusted estimate: {_cell(adj['est'])} (95 % interval "
                f"{_cell(adj['ci95_low'])}–{_cell(adj['ci95_high'])}). New patients meeting the criteria per month: "
                f"{_cell(hl['monthly_new_meeting_criteria'])}. 12-month enrolment P10/P50/P90: "
                f"{p12['p10']}/{p12['p50']}/{p12['p90']}."
            ),
            body,
        )
    )
    story.append(Paragraph(escape("Top limiting criteria: " + (", ".join(hl["top_limiting_criteria"]) or "—")), body))
    story.append(Paragraph(escape("Recall: " + hl["recall_sentence"]), body))
    story.append(Paragraph(escape(obj["disclaimers"]["disc.ai"]), small))
    story.append(Spacer(1, 4 * mm))
    for sec in obj["sections"]:
        if sec["id"] != "1":
            story.append(PageBreak())
        story.append(Paragraph(escape(f"§{sec['id']} {sec['title']}"), h1))
        if sec["id"] == "15":
            cert = obj["recall_certificate"]
            story.append(
                Paragraph(escape("Recall certificate: " + json.dumps(_cert_summary(cert), ensure_ascii=False)), small)
            )
            for k, v in obj["disclaimers"].items():
                story.append(Paragraph(escape(f"{k}: {v}"), small))
            story.append(
                Paragraph(
                    escape(
                        f"Disclosure profile {prof['name']} v{prof['version']}: cells 1–{prof['k'] - 1} shown as "
                        f"'<{prof['k']}', other counts rounded to the nearest {prof['base']}; differences from exact "
                        f"values; percentages only where numerator, complement and denominator are 0 or ≥ {prof['k']}. "
                        f"Steps: {', '.join(s['step'] for s in obj['disclosure_trace']['steps'])}. Object sha256 "
                        f"{frozen['sha256']}. CQL/SQL logic text is not released (RPT-35); Annex B lists the criterion "
                        "logic hashes."
                    ),
                    small,
                )
            )
            for cid, h in sorted(obj["annex_b_logic_hashes"].items()):
                story.append(Paragraph(escape(f"Annex B {cid}: {h}"), small))
        for tid in sec["tables"]:
            table(tid)
        for fid in sec["figures"]:
            figure(fid)
    exact = frozen.get("internal_exact")
    if exact:
        story.append(PageBreak())
        story.append(Paragraph("INTERNAL appendix: released vs exact (synthetic or open data only)", h1))
        for row_r, row_x in zip(obj["tables"]["F-T5"], exact["F-T5"], strict=True):
            story.append(
                Paragraph(
                    escape(
                        f"step {row_r['step']} {row_r['criterion_id'] or 'scope'}: remaining released "
                        f"{_cell(row_r['n_remaining'])} / exact {row_x['n_remaining']}; excluded released "
                        f"{_cell(row_r['n_excluded'])} / exact {row_x['n_excluded']}"
                    ),
                    small,
                )
            )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _cert_summary(cert: Mapping[str, Any]) -> dict[str, Any]:
    if cert.get("refused"):
        return {"status": "refused", "reasons": cert.get("reasons", [])}
    return {
        "status": "issued",
        "rc_id": cert.get("rc_id"),
        "alpha": cert.get("alpha"),
        "per_1000_excluded_upper": round(float(cert.get("per_1000_excluded_upper", 0.0)), 1),
        "missed_upper": round(float(cert.get("missed_upper", 0.0)), 1),
        "quoted_line": cert.get("quoted_line"),
        "registered_at": cert.get("registered_at"),
        "series": cert.get("series"),
        "demotions": cert.get("demotions", []),
    }


# ------------------------------------------------------------------------------------------------ XLSX
def render_xlsx(frozen: Mapping[str, Any]) -> bytes:
    obj = verify_frozen(frozen)
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    wb.properties.creator = "TrialBox"
    ws = wb.active
    assert ws is not None
    ws.title = "README"
    prof = obj["profile"]
    lines = [
        f"DL-1 feasibility pack · {obj['ruleset']['id']} v{obj['ruleset']['version']} · site {obj['site']['id']}",
        f"snapshot {obj['snapshot']['id']} · data cut {obj['snapshot']['data_cut_month']} · object {frozen['sha256']}",
        f"disclosure {prof['name']} v{prof['version']}: 1–{prof['k'] - 1} → '<{prof['k']}', nearest {prof['base']}",
        "Columns are the machine keys of spec v4 §12.4. 'not_available' rows carry the reason.",
        "Recall: " + obj["headline"]["recall_sentence"],
    ]
    for i, line in enumerate(lines, start=1):
        ws.cell(row=i, column=1, value=line)
    for tid, rows in obj["tables"].items():
        sh = wb.create_sheet(tid)
        if isinstance(rows, dict):
            sh.append(["not_available"])
            sh.append([rows.get("not_available", "")])
            continue
        if not rows:
            continue
        keys = list(rows[0].keys())
        sh.append(keys)
        for c in sh[1]:
            c.font = Font(bold=True)
        for r in rows:
            sh.append([_xl(r.get(k)) for k in keys])
    for fid, f in obj["figures"].items():  # RPT-12: each figure's data table
        if "not_available" in f or not f.get("data"):
            continue
        sh = wb.create_sheet(f"{fid} data")
        keys = sorted({k for row in f["data"] for k in row})
        sh.append(keys)
        for row in f["data"]:
            sh.append([_xl(row.get(k)) for k in keys])
    exact = frozen.get("internal_exact")
    if exact:
        sh = wb.create_sheet("INTERNAL exact")
        sh.append(["INTERNAL: synthetic or open data only; never released"])
        for tid, rows in exact.items():
            if not isinstance(rows, list) or not rows:
                continue
            sh.append([])
            sh.append([tid])
            keys = list(rows[0].keys())
            sh.append(keys)
            for r in rows:
                sh.append([_xl(r.get(k)) for k in keys])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _xl(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return v


def render_all(frozen: Mapping[str, Any], out_dir: Path, stem: str) -> dict[str, Path]:
    """Write PDF, XLSX, JSON (released object) and the figure PNGs; returns the paths."""
    obj = verify_frozen(frozen)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "pdf": out_dir / f"{stem}.pdf",
        "xlsx": out_dir / f"{stem}.xlsx",
        "json": out_dir / f"{stem}.json",
    }
    paths["pdf"].write_bytes(render_pdf(frozen))
    paths["xlsx"].write_bytes(render_xlsx(frozen))
    paths["json"].write_text(
        json.dumps({"object": obj, "sha256": frozen["sha256"]}, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for fid, png in sorted(frozen.get("pngs", {}).items()):
        p = out_dir / "figures" / f"{stem}_{fid}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(png)
        paths[fid] = p
    if frozen.get("internal_exact"):
        p = out_dir / f"{stem}_INTERNAL_exact.json"
        p.write_text(json.dumps(frozen["internal_exact"], indent=1, sort_keys=True, default=str) + "\n", "utf-8")
        paths["internal_exact"] = p
    return paths


__all__ = ["render_all", "render_pdf", "render_xlsx"]
