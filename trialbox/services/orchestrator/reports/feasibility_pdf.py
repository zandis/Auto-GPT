"""Feasibility PDF (SPEC §9.1): cover, answer, funnel (table + bar chart), sensitivity, monthly new-eligible, simulation
assumptions, criterion definitions, site capabilities. Aggregate only — no patient-level content."""

from __future__ import annotations

import io
import math
from typing import Any
from xml.sax.saxutils import escape

from tb_common.ruleset import Ruleset
from tb_contracts import FeasibilityResult

from orchestrator.i18n import t
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
    lang = meta.locale
    text = t(
        lang,
        "pdf.answer.text",
        months=sim.months,
        site=escape(meta.site_name),
        low=f"{sim.low:g}",
        high=f"{sim.high:g}",
        mid=f"{sim.mid:g}",
        iterations=sim.iterations or 1000,
    )
    bars = barriers(result)
    if bars:
        parts = [f"{escape(label)} ({cid}, −{fmt_count(d)})" for cid, label, d in bars]
        text += t(lang, "pdf.answer.barriers", items=t(lang, "pdf.and").join(parts))
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
    lang = meta.locale

    def L(key: str, **kw: Any) -> str:  # noqa: N802 - label
        return t(lang, key, **kw)

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
        Paragraph(escape(L("pdf.feas.title", trial=m.trial_alias or m.id)), h1),
        Spacer(1, 6 * mm),
        table(
            [
                [L("pdf.item"), L("pdf.value")],
                [L("pdf.trial"), L("pdf.trial.value", title=m.title or m.id, rs=m.id, ver=m.version)],
                [L("pdf.sponsor"), m.sponsor or "—"],
                [L("pdf.site"), f"{meta.site_name} ({meta.site_id})"],
                [L("pdf.run_date"), meta.run_date],
                [L("pdf.snapshot"), meta.snapshot],
                [L("pdf.population"), result.population],
                [L("pdf.lookback"), L("pdf.lookback.value", months=result.lookback_months)],
                [L("pdf.contact"), meta.contact or "—"],
            ],
            [40 * mm, 125 * mm],
        ),
        Spacer(1, 8 * mm),
        # 2 answer
        Paragraph(L("pdf.answer"), h2),
        Paragraph(answer_text(result, meta), body),
        PageBreak(),
    ]
    # 3 funnel
    frows: list[list[Any]] = [
        [L("pdf.step"), L("pdf.criterion"), L("pdf.remaining"), L("pdf.dropped"), L("pdf.pct_start"), L("pdf.unknown")]
    ]
    frows.append(["—", result.population, fmt_count(result.start_n), "", "100.0", ""])
    for f in result.funnel:
        if f.applied is False:
            frows.append([f.criterion_id, L("pdf.not_applied", label=f.label), "", "", "", ""])
        else:
            pct = "—" if f.pct is None else f"{f.pct:.1f}"
            frows.append(
                [f.criterion_id, f.label, fmt_count(f.remaining), fmt_count(f.dropped), pct, fmt_count(f.unknown)]
            )
    story += [
        Paragraph(L("pdf.funnel"), h2),
        table(frows, [27 * mm, 67 * mm, 20 * mm, 18 * mm, 18 * mm, 20 * mm]),
        Spacer(1, 4 * mm),
        Image(
            io.BytesIO(funnel_chart(result, meta.locale)),
            width=170 * mm,
            height=max(50.0, 6.0 * len([f for f in result.funnel if f.applied is not False]) + 18) * mm,
        ),
    ]
    # 4 sensitivity
    srows: list[list[Any]] = [[L("pdf.variant"), L("pdf.criterion"), L("pdf.remaining"), L("pdf.delta")]]
    for s in result.sensitivity:
        delta = "—" if s.delta is None else f"{s.delta:+d}"
        srows.append([s.variant, s.criterion_id, fmt_count(s.remaining), delta])
    story += [KeepTogether([Paragraph(L("pdf.sensitivity"), h2), table(srows, [45 * mm, 45 * mm, 30 * mm, 30 * mm])])]
    # 5 monthly
    story += [
        Paragraph(L("pdf.monthly", n=len(result.monthly_new)), h2),
        Image(io.BytesIO(monthly_chart(result, meta.locale, small_cell)), width=170 * mm, height=62 * mm),
    ]
    # 6 simulation assumptions
    sim = result.simulation
    cap = (
        L("pdf.capacity.unlimited")
        if sim.capacity_per_month is None
        else L("pdf.capacity.value", n=f"{sim.capacity_per_month:g}")
    )
    story += [
        KeepTogether(
            [
                Paragraph(L("pdf.assumptions"), h2),
                table(
                    [
                        [L("pdf.parameter"), L("pdf.value"), L("pdf.source")],
                        [L("pdf.reach"), f"{sim.reach_rate:.0%}", sim.source or L("pdf.default")],
                        [L("pdf.accept"), f"{sim.accept_rate:.0%}", sim.source or L("pdf.default")],
                        [L("pdf.capacity"), cap, "settings.practitioners"],
                        [
                            L("pdf.monthly_eligible"),
                            f"{sim.monthly_eligible_mean or 0:g}",
                            L("pdf.monthly_eligible.source"),
                        ],
                        [L("pdf.horizon"), L("pdf.horizon.value", months=sim.months), "SPEC §8.1"],
                        [L("pdf.iterations"), str(sim.iterations or 1000), L("pdf.iterations.source")],
                        [L("pdf.result"), f"{sim.low:g} / {sim.mid:g} / {sim.high:g}", L("pdf.simulation")],
                    ],
                    [55 * mm, 55 * mm, 60 * mm],
                ),
            ]
        ),
        Paragraph(L("pdf.notes"), h2),
    ]
    story += [Paragraph("• " + escape(n), small) for n in result.notes]
    # 7 criterion definitions
    story += [PageBreak(), Paragraph(L("pdf.appendix_a"), h2)]
    drows: list[list[Any]] = [[L("pdf.id"), L("pdf.protocol_text"), L("pdf.how"), L("pdf.class")]]
    for c in rs.active():
        if c.class_ == "structured":
            how = L(
                "pdf.how.structured",
                logic=logic_summary(c.logic, rs.valuesets),
                codes=codes_text(c.logic, rs.valuesets),
            )
        elif c.class_ == "mixed":
            how = L("pdf.how.mixed", logic=logic_summary(c.logic, rs.valuesets))
        else:
            how = L("pdf.how.note" if c.class_ == "note" else "pdf.how.human")
            if c.fallback:
                how += L("pdf.fallback", text=c.fallback)
        drows.append([c.id, c.text, how[:900], c.class_])
    story.append(table(drows, [23 * mm, 56 * mm, 79 * mm, 20 * mm]))
    # 8 site capability
    story += [Paragraph(L("pdf.appendix_b"), h2)]
    crow: list[list[Any]] = [[L("pdf.capability"), L("pdf.available")]]
    for k, v in sorted(capabilities.items()):
        crow.append([CAPABILITY_LABELS.get(k, k.replace("_", " ").capitalize()), L("pdf.yes") if v else L("pdf.no")])
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
