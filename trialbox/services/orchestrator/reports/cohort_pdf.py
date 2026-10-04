"""Cohort report PDF (SPEC §8.3, tag ``aggregate``): per-quarter "criterion × count" table with contactable counts,
a trend chart of the population, and the trial simulation summary. Counts are the suppressed alliance values."""

from __future__ import annotations

import io
from typing import Any
from xml.sax.saxutils import escape

from tb_common.ruleset import Ruleset
from tb_contracts import CohortTable, TrialSimResult

from orchestrator.reports.common import ReportMeta, figure, fmt_count, pdf_fonts, pdf_invariant, png


def _trend_png(table: CohortTable, population: str, locale: str) -> bytes | None:
    pts = [(r.quarter, r.n) for r in table.rows if r.criterion_id == population]
    if len(pts) < 2:
        return None
    fig = figure(locale, 6.5, 2.4)
    ax = fig.add_subplot(1, 1, 1)
    xs = list(range(len(pts)))
    known = [(x, v) for x, (_, v) in zip(xs, pts, strict=True) if isinstance(v, int)]
    if known:
        ax.plot([x for x, _ in known], [v for _, v in known], marker="o", color="#1f4e79")
    ax.set_xticks(xs, [q for q, _ in pts])
    ax.set_ylabel("population")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.3)
    return png(fig)


def render(rs: Ruleset, table: CohortTable, sims: TrialSimResult | None, meta: ReportMeta) -> bytes:
    pdf_invariant()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from orchestrator.scenarios.cohort import population_id

    regular, bold = pdf_fonts(meta.locale)
    body = ParagraphStyle("b", fontName=regular, fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10)
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=16, leading=20, textColor=colors.HexColor("#1f4e79"))
    h2 = ParagraphStyle("h2", parent=body, fontName=bold, fontSize=12, leading=16, spaceBefore=8, spaceAfter=4)

    def grid(data: list[list[Any]], widths: list[float]) -> Table:
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

    pop = population_id(rs)
    quarters = sorted({r.quarter for r in table.rows})
    disease = table.rows[0].disease if table.rows else rs.id
    title = f"Cohort report — {rs.manifest.title or rs.id}"
    story: list[Any] = [Paragraph(escape(title), h1), Spacer(1, 3 * mm)]
    story.append(
        Paragraph(
            escape(
                f"Site {meta.site_id} · disease {disease} · quarters {quarters[0]}–{quarters[-1]} · definition "
                f"{rs.id} v{rs.version} · counts at each quarter end (population = {pop})."
            ),
            body,
        )
    )
    trend = _trend_png(table, pop, meta.locale)
    if trend:
        story += [Spacer(1, 2 * mm), Image(io.BytesIO(trend), width=165 * mm, height=61 * mm)]
    for q in reversed(quarters):
        rows = [r for r in table.rows if r.quarter == q]
        story += [
            Paragraph(f"{q}", h2),
            grid(
                [["criterion", "label", "n", "contactable"]]
                + [[r.criterion_id, r.criterion_label, fmt_count(r.n), fmt_count(r.n_contactable)] for r in rows],
                [38 * mm, 92 * mm, 22 * mm, 26 * mm],
            ),
        ]
    if sims is not None:
        story += [
            Paragraph("Recruiting trials — enrolment simulation (12 months, this site)", h2),
            Paragraph(
                escape(
                    f"ClinicalTrials.gov ({sims.source}) condition '{sims.condition}', Taiwan/Japan, recruiting. "
                    f"Eligibility texts were compiled automatically (not reviewed); reach {sims.reach_rate:.0%} × "
                    f"accept {sims.accept_rate:.0%}."
                ),
                small,
            ),
            grid(
                [["NCT", "title", "criteria counted", "eligible now", "new / month", "P10–P50–P90"]]
                + [
                    [
                        r.nct_id,
                        r.title,
                        f"{r.criteria_applied}/{r.criteria_total}",
                        fmt_count(r.eligible_now),
                        "—" if r.new_per_month is None else f"{r.new_per_month:g}",
                        "—"
                        if r.enrol_12m_mid is None
                        else f"{r.enrol_12m_low:g}–{r.enrol_12m_mid:g}–{r.enrol_12m_high:g}",
                    ]
                    for r in sims.rows
                ],
                [24 * mm, 70 * mm, 20 * mm, 20 * mm, 18 * mm, 28 * mm],
            ),
        ]
    story += [
        Spacer(1, 4 * mm),
        Paragraph(
            "Aggregate counts only; cells 1–4 are shown as '<5' (small-cell suppression before leaving the box). "
            "'contactable' = patients with an active research-contact consent in the site registry.",
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
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
