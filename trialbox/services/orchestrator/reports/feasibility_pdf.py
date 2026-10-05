"""Feasibility PDF (SPEC §9.1): cover, answer, funnel (table + bar chart), sensitivity, monthly new-eligible, simulation
assumptions, criterion definitions, site capabilities. Aggregate only — no patient-level content."""

from __future__ import annotations

import io
import math
from typing import Any
from xml.sax.saxutils import escape

from tb_common.ruleset import Ruleset
from tb_contracts import FeasibilityResult

from orchestrator.reports.common import ReportMeta, figure, fmt_count, pdf_fonts, pdf_invariant, png

BRAND = "#1f4e79"
CAPABILITY_LABELS = {
    "fundus_photography": "Fundus photography",
    "injection_training": "Injection training",
    "cold_chain": "Cold-chain pharmacy storage",
    "ediary_support": "eDiary support",
    "central_lab_shipping": "Central-lab sample shipping",
    "imaging_ct_mri": "CT / MRI imaging",
    "dexa": "DEXA",
}


def barriers(result: FeasibilityResult, n: int = 2) -> list[tuple[str, str, int | str]]:
    """The applied steps with the largest drop (suppressed cells rank as 0)."""
    steps = [f for f in result.funnel if f.applied is not False]
    ranked = sorted(steps, key=lambda f: (-(f.dropped if isinstance(f.dropped, int) else 0), f.criterion_id))
    return [(f.criterion_id, f.label, f.dropped) for f in ranked[:n] if isinstance(f.dropped, int) and f.dropped > 0]


def answer_text(result: FeasibilityResult, meta: ReportMeta) -> str:
    sim = result.simulation
    text = (
        f"Estimated {sim.months}-month enrolment at {meta.site_name}: <b>{sim.low:g}–{sim.high:g}</b> participants "
        f"(most likely {sim.mid:g}; P10–P90 of {sim.iterations or 1000} simulations). "
    )
    bars = barriers(result)
    if bars:
        parts = [f"{escape(label)} ({cid}, −{fmt_count(d)})" for cid, label, d in bars]
        text += "The biggest barriers are " + " and ".join(parts) + "."
    return text


def funnel_chart(result: FeasibilityResult, locale: str) -> bytes:
    rows = [f for f in result.funnel if f.applied is not False]
    fig = figure(locale, 7.0, max(2.2, 0.26 * len(rows) + 0.8))
    ax = fig.add_subplot(111)
    labels = [f"{r.criterion_id.split('-', 1)[-1]}  {r.label}" for r in rows][::-1]
    vals = [r.remaining if isinstance(r.remaining, int) else 0 for r in rows][::-1]
    ax.barh(range(len(vals)), vals, color=BRAND)
    ax.set_yticks(range(len(vals)), labels)
    for i, r in enumerate(rows[::-1]):
        ax.text(vals[i], i, f" {fmt_count(r.remaining)}", va="center", fontsize=7)
    ax.set_xlabel("patients remaining")
    return png(fig)


def monthly_chart(result: FeasibilityResult, locale: str, small_cell: int = 5) -> bytes:
    """Line chart; suppressed months are drawn as an open marker with a 1..t-1 range bar (never an exact value)."""
    fig = figure(locale, 7.0, 2.6)
    ax = fig.add_subplot(111)
    months = [m.month for m in result.monthly_new]
    xs = list(range(len(months)))
    vals = [float(m.n) if isinstance(m.n, int) else float("nan") for m in result.monthly_new]
    ax.plot(xs, vals, marker="o", color=BRAND, linewidth=1.2, markersize=3, label="new eligible")
    sup = [x for x, m in zip(xs, result.monthly_new, strict=True) if not isinstance(m.n, int)]
    if sup:
        mid = small_cell / 2
        ax.errorbar(
            sup,
            [mid] * len(sup),
            yerr=[[mid - 1] * len(sup), [small_cell - 1 - mid] * len(sup)],
            fmt="o",
            mfc="white",
            color=BRAND,
            markersize=3,
            capsize=2,
            linewidth=0.8,
            label=f"<{small_cell} (suppressed)",
        )
        ax.legend(loc="upper left", frameon=False)
    top = max([v for v in vals if not math.isnan(v)] + [float(small_cell)])
    ax.set_ylim(0, top * 1.15 + 0.5)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_xticks(xs[::3], months[::3], rotation=45, ha="right")
    ax.set_ylabel("new eligible / month")
    return png(fig)


def render(
    result: FeasibilityResult, rs: Ruleset, meta: ReportMeta, capabilities: dict[str, bool], small_cell: int = 5
) -> bytes:
    pdf_invariant()
    from criteria_compiler.review import codes_text, logic_summary
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    regular, bold = pdf_fonts(meta.locale)
    body = ParagraphStyle("body", fontName=regular, fontSize=9.5, leading=13, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5)
    h1 = ParagraphStyle("h1", parent=body, fontName=bold, fontSize=20, leading=26, textColor=colors.HexColor(BRAND))
    h2 = ParagraphStyle(
        "h2",
        parent=body,
        fontName=bold,
        fontSize=13,
        leading=17,
        spaceBefore=8,
        spaceAfter=4,
        textColor=colors.HexColor(BRAND),
    )
    m = rs.manifest
    story: list[Any] = []

    def table(rows: list[list[Any]], widths: list[float], head: int = 1) -> Table:
        data = [[c if isinstance(c, Paragraph) else Paragraph(escape(str(c)), small) for c in r] for r in rows]
        t = Table(data, colWidths=widths, repeatRows=head)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, head - 1), colors.HexColor("#dce6f1")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#9aa9b8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return t

    # 1 cover
    story += [
        Spacer(1, 30 * mm),
        Paragraph(f"Feasibility report — {escape(m.trial_alias or m.id)}", h1),
        Spacer(1, 6 * mm),
        table(
            [
                ["Item", "Value"],
                ["Trial", f"{m.title or m.id} (ruleset {m.id} v{m.version})"],
                ["Sponsor", m.sponsor or "—"],
                ["Site", f"{meta.site_name} ({meta.site_id})"],
                ["Run date", meta.run_date],
                ["Data snapshot", meta.snapshot],
                ["Population", result.population],
                ["Lookback", f"{result.lookback_months} months (month-end index dates)"],
                ["Contact", meta.contact or "—"],
            ],
            [40 * mm, 125 * mm],
        ),
        Spacer(1, 8 * mm),
        # 2 answer
        Paragraph("Answer", h2),
        Paragraph(answer_text(result, meta), body),
        PageBreak(),
    ]
    # 3 funnel
    frows: list[list[Any]] = [["Step", "Criterion", "Remaining", "Dropped", "% of start", "Unknown"]]
    frows.append(["—", result.population, fmt_count(result.start_n), "", "100.0", ""])
    for f in result.funnel:
        if f.applied is False:
            frows.append([f.criterion_id, f"{f.label} (not applied in counts)", "", "", "", ""])
        else:
            pct = "—" if f.pct is None else f"{f.pct:.1f}"
            frows.append(
                [f.criterion_id, f.label, fmt_count(f.remaining), fmt_count(f.dropped), pct, fmt_count(f.unknown)]
            )
    story += [
        Paragraph("Eligibility funnel", h2),
        table(frows, [27 * mm, 67 * mm, 20 * mm, 18 * mm, 18 * mm, 20 * mm]),
        Spacer(1, 4 * mm),
        Image(
            io.BytesIO(funnel_chart(result, meta.locale)),
            width=170 * mm,
            height=max(50.0, 6.0 * len([f for f in result.funnel if f.applied is not False]) + 18) * mm,
        ),
    ]
    # 4 sensitivity
    srows: list[list[Any]] = [["Variant", "Criterion", "Remaining", "Δ vs base"]]
    for s in result.sensitivity:
        delta = "—" if s.delta is None else f"{s.delta:+d}"
        srows.append([s.variant, s.criterion_id, fmt_count(s.remaining), delta])
    story += [KeepTogether([Paragraph("Sensitivity", h2), table(srows, [45 * mm, 45 * mm, 30 * mm, 30 * mm])])]
    # 5 monthly
    story += [
        Paragraph(f"New eligible patients per month ({len(result.monthly_new)} months)", h2),
        Image(io.BytesIO(monthly_chart(result, meta.locale, small_cell)), width=170 * mm, height=62 * mm),
    ]
    # 6 simulation assumptions
    sim = result.simulation
    cap = "not limited" if sim.capacity_per_month is None else f"{sim.capacity_per_month:g} per month"
    story += [
        KeepTogether(
            [
                Paragraph("Simulation assumptions", h2),
                table(
                    [
                        ["Parameter", "Value", "Source"],
                        ["Reach rate", f"{sim.reach_rate:.0%}", sim.source or "default"],
                        ["Accept rate", f"{sim.accept_rate:.0%}", sim.source or "default"],
                        ["Investigator capacity", cap, "settings.practitioners"],
                        ["New eligible per month", f"{sim.monthly_eligible_mean or 0:g}", "funnel, last 12 months"],
                        ["Horizon", f"{sim.months} months", "SPEC §8.1"],
                        ["Iterations", str(sim.iterations or 1000), "Beta-distributed rates, Poisson arrivals"],
                        ["Result (P10 / P50 / P90)", f"{sim.low:g} / {sim.mid:g} / {sim.high:g}", "simulation"],
                    ],
                    [55 * mm, 55 * mm, 60 * mm],
                ),
            ]
        ),
        Paragraph("Notes", h2),
    ]
    story += [Paragraph("• " + escape(n), small) for n in result.notes]
    # 7 criterion definitions
    story += [PageBreak(), Paragraph("Appendix A — criterion definitions", h2)]
    drows: list[list[Any]] = [["Id", "Protocol text", "How computed", "Class"]]
    for c in rs.active():
        if c.class_ == "structured":
            how = f"{logic_summary(c.logic, rs.valuesets)}. Codes: {codes_text(c.logic, rs.valuesets)}"
        else:
            how = (
                "Not applied in counts ("
                + ("chart review / note judge" if c.class_ == "note" else "asked at screening")
                + ")"
            )
            if c.fallback:
                how += f". Fallback: {c.fallback}"
        drows.append([c.id, c.text, how[:900], c.class_])
    story.append(table(drows, [23 * mm, 56 * mm, 79 * mm, 20 * mm]))
    # 8 site capability
    story += [Paragraph("Appendix B — site capabilities", h2)]
    crow: list[list[Any]] = [["Capability", "Available"]]
    for k, v in sorted(capabilities.items()):
        crow.append([CAPABILITY_LABELS.get(k, k.replace("_", " ").capitalize()), "yes" if v else "no"])
    story.append(table(crow, [90 * mm, 30 * mm]))

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#555555"))
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
        title=f"Feasibility {m.id} v{m.version}",
        author=f"TrialBox {meta.site_id}",
        subject=meta.footer,
        creator="TrialBox",
        producer="TrialBox",
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
