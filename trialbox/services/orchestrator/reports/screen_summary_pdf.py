"""SCREEN / MICROBATCH / NAV summary PDF (tag ``aggregate``): counts only, small cells suppressed, no patient rows."""

from __future__ import annotations

import io
from collections import Counter
from typing import Any
from xml.sax.saxutils import escape

from tb_common.ruleset import Ruleset
from tb_common.smallcell import suppress
from tb_contracts import CandidateRow

from orchestrator.reports.common import ReportMeta, fmt_count, pdf_fonts, pdf_invariant


def render(
    title: str,
    rows: list[CandidateRow],
    rs: Ruleset,
    meta: ReportMeta,
    scope_lines: list[str],
    small_cell: int = 5,
    practitioners: dict[str, str] | None = None,
) -> bytes:
    pdf_invariant()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular, bold = pdf_fonts(meta.locale)
    body = ParagraphStyle("b", fontName=regular, fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10)
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=16, leading=20, textColor=colors.HexColor("#1f4e79"))
    h2 = ParagraphStyle("h2", parent=body, fontName=bold, fontSize=12, leading=16, spaceBefore=8, spaceAfter=4)
    t = small_cell

    def table(data: list[list[Any]], widths: list[float]) -> Table:
        tb = Table([[Paragraph(escape(str(c)), small) for c in r] for r in data], colWidths=widths, repeatRows=1)
        tb.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce6f1")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9aa9b8")),
                ]
            )
        )
        return tb

    tiers = Counter(r.tier for r in rows)
    story: list[Any] = [Paragraph(escape(title), h1), Spacer(1, 4 * mm)]
    story += [Paragraph(escape(s), body) for s in scope_lines]
    story += [
        Paragraph("Candidates by tier", h2),
        table(
            [["tier", "patients"]]
            + [[k, fmt_count(suppress(tiers.get(k, 0), t))] for k in ("high", "review", "excluded")],
            [60 * mm, 40 * mm],
        ),
    ]
    names = practitioners or {}
    by_pr = Counter(r.practitioner_id or "—" for r in rows if r.tier in ("high", "review"))
    if by_pr:
        story += [
            Paragraph("Listed candidates by practitioner", h2),
            table(
                [["practitioner", "patients"]]
                + [[names.get(k, k), fmt_count(suppress(n, t))] for k, n in sorted(by_pr.items())],
                [80 * mm, 40 * mm],
            ),
        ]
    listed = [r for r in rows if r.tier in ("high", "review")]
    unknown = Counter(v.id for r in listed for v in r.criteria if v.verdict == "unknown")
    pending = Counter(v.id for r in listed for v in r.criteria if v.verdict == "pending_human")
    label = {c.id: c.label or c.text[:50] for c in rs.criteria}
    crow = [["criterion", "label", "unknown", "to ask"]]
    for c in rs.active():
        if c.id in unknown or c.id in pending:
            crow.append(
                [
                    c.id,
                    label[c.id],
                    fmt_count(suppress(unknown.get(c.id, 0), t)),
                    fmt_count(suppress(pending.get(c.id, 0), t)),
                ]
            )
    if len(crow) > 1:
        story += [
            Paragraph("Open items among listed candidates", h2),
            table(crow, [30 * mm, 80 * mm, 25 * mm, 25 * mm]),
        ]
    story += [
        Spacer(1, 4 * mm),
        Paragraph(
            "Patient lists were sent encrypted to the internal list recipients only. "
            f"Cells 1–{t - 1} are shown as '<{t}'.",
            small,
        ),
    ]

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.drawString(15 * mm, 10 * mm, meta.footer)
        canvas.drawRightString(195 * mm, 10 * mm, f"{doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title=title,
        author=f"TrialBox {meta.site_id}",
        subject=meta.footer,
        creator="TrialBox",
        producer="TrialBox",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
