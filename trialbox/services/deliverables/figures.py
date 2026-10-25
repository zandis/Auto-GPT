"""DL-1 figures from the **released** tables only (spec v4 §12.4 figures, §12.2.3 figure rules, §12.2.4 standard).

Implemented: F-F1 CONSORT-style flow, F-F2 waterfall, F-F3 100 % stacked bar, F-F4 incidence line, F-F10 fan chart,
F-F12 tornado. Every figure returns PNG bytes (deterministic: Agg backend, no metadata), generated alt text and the
data table it was drawn from (RPT-12). Colours are palette ``tb-cvd-1``; every series also carries a non-colour
channel (hatch or marker, RPT-11). Suppressed values (``<k``) are drawn as hatched ``///`` bars in #595959 and labelled
``<k``, never at their exact height.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

BLUE = "#0072B2"
VERMILLION = "#D55E00"
GREEN = "#009E73"
GREY = "#767676"
DARK_GREY = "#595959"
LIGHT_GREY = "#BBBBBB"
BLACK = "#000000"
PALETTE_TB_CVD_1 = (BLUE, VERMILLION, GREEN, "#CC79A7", "#B07800", "#2B8CC4", "#8A7F00", BLACK)

Released = int | str


@dataclass
class FigureOut:
    fid: str
    title: str
    png: bytes
    alt: str
    data: list[dict[str, Any]] = field(default_factory=list)


def _fig(width_mm: float = 170, height_mm: float = 90) -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        from orchestrator.reports.common import _mpl_font

        family = _mpl_font("zh-TW")
    except Exception:  # fonts not fetched: matplotlib default (tests without .cache/fonts)
        family = "DejaVu Sans"
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "lines.linewidth": 1.5,
            "hatch.color": DARK_GREY,
            "svg.hashsalt": "trialbox",
        }
    )
    return plt.figure(figsize=(width_mm / 25.4, height_mm / 25.4), dpi=150)


def _png(fig: Any) -> bytes:
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, metadata={"Software": None}, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _num(v: Released, k: int) -> float:
    """Drawing height of a released value: suppressed cells get a nominal half-threshold height (hatched)."""
    return float(v) if isinstance(v, int) else k / 2


def _label(v: Released) -> str:
    return f"{v:,}" if isinstance(v, int) else str(v)


def waterfall(steps: Sequence[dict[str, Any]], final: Released, k: int) -> FigureOut:
    """F-F2: start bar (blue), drops as vermillion floating bars, end bar (blue); top three drops annotated."""
    fig = _fig(170, max(70, 8 * len(steps) + 30))
    ax = fig.add_subplot(111)
    labels = ["Scope"] + [s["label"][:28] for s in steps] + ["Remaining"]
    start = steps[0]["n_prev"] if steps else final
    top = _num(start, k)
    ax.bar(0, top, color=BLUE, edgecolor=BLACK, linewidth=0.6)
    ax.text(0, top, _label(start), ha="center", va="bottom", fontsize=9)
    level = top
    drops = []
    for i, s in enumerate(steps, start=1):
        d = s["n_excluded"]
        h = _num(d, k)
        suppressed = isinstance(d, str)
        ax.bar(
            i,
            h,
            bottom=max(level - h, 0),
            color=LIGHT_GREY if suppressed else VERMILLION,
            hatch="///" if suppressed else None,
            edgecolor=DARK_GREY if suppressed else BLACK,
            linewidth=0.6,
        )
        ax.text(i, level, _label(d), ha="center", va="bottom", fontsize=9)
        drops.append((h if not suppressed else 0, i, s["label"]))
        rem = s["n_remaining"]
        level = _num(rem, k)
    ax.bar(len(steps) + 1, _num(final, k), color=BLUE, edgecolor=BLACK, linewidth=0.6, hatch="..")
    ax.text(len(steps) + 1, _num(final, k), _label(final), ha="center", va="bottom", fontsize=9)
    for _h, i, _lab in sorted(drops, reverse=True)[:3]:
        ax.annotate("top drop", (i, 0), xytext=(0, -2), textcoords="offset points", ha="center", va="top", fontsize=9)
    ax.set_xticks(range(len(labels)), labels, rotation=60, ha="right", fontsize=9)
    ax.set_ylabel("patients (released counts)")
    ax.set_title("F-F2 Attrition waterfall")
    biggest = ", ".join(lab for _h, _i, lab in sorted(drops, reverse=True)[:3])
    alt = (
        f"Waterfall of {len(steps)} criteria from {_label(start)} patients in scope to {_label(final)} remaining. "
        f"Largest drops: {biggest}. Suppressed drops are hatched and labelled '<{k}'."
    )
    data = [{"label": "Scope", "value": start}, *({"label": s["label"], "value": s["n_excluded"]} for s in steps)]
    return FigureOut("F-F2", "Attrition waterfall", _png(fig), alt, [*data, {"label": "Remaining", "value": final}])


def flow(boxes: Sequence[dict[str, Any]], k: int) -> FigureOut:
    """F-F1: CONSORT-style flow; main boxes = n remaining per stage, side boxes = exclusions with their reasons."""
    fig = _fig(170, 30 * len(boxes) + 10)
    ax = fig.add_subplot(111)
    ax.set_axis_off()
    n = len(boxes)
    for i, b in enumerate(boxes):
        y = n - i
        ax.text(
            0.3,
            y,
            f"{b['stage']}: {b['label']}\nn = {_label(b['n'])}",
            ha="center",
            va="center",
            fontsize=9,
            bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": BLUE, "linewidth": 1.5},
        )
        if b.get("excluded") is not None:
            reasons = "; ".join(f"{r} ({_label(v)})" for r, v in b.get("reasons", [])[:3])
            ax.text(
                0.78,
                y - 0.5,
                f"Excluded: {_label(b['excluded'])}\n{reasons}"[:160],
                ha="center",
                va="center",
                fontsize=9,
                style="italic" if b.get("unknown") else "normal",
                bbox={"boxstyle": "square", "facecolor": "white", "edgecolor": VERMILLION, "linewidth": 1.5},
            )
        if i < n - 1:
            ax.annotate("", (0.3, y - 0.75), (0.3, y - 0.25), arrowprops={"arrowstyle": "->", "color": BLACK})
    ax.set_xlim(0, 1)
    ax.set_ylim(0.3, n + 0.7)
    ax.set_title("F-F1 Cascade flow (released counts)")
    alt = "Flow from scope to computable count: " + " → ".join(f"{b['stage']} {_label(b['n'])}" for b in boxes) + "."
    return FigureOut("F-F1", "Cascade flow", _png(fig), alt, [dict(b) for b in boxes])


def stacked(rows: Sequence[dict[str, Any]], k: int) -> FigureOut:
    """F-F3: per criterion pass / fail / unknown data gap / unknown uncertain as 100 % stacked bars."""
    fig = _fig(170, max(60, 7 * len(rows) + 25))
    ax = fig.add_subplot(111)
    parts = [
        ("pass", GREEN, None, "pass"),
        ("fail", VERMILLION, "\\\\", "fail"),
        ("unknown_data_gap", LIGHT_GREY, "..", "unknown: data gap"),
        ("unknown_uncertain", LIGHT_GREY, "xx", "unknown: uncertain"),
    ]
    for i, r in enumerate(rows):
        vals = {p: _num(r[p], k) for p, *_ in parts}
        total = sum(vals.values()) or 1.0
        left = 0.0
        for key, colour, hatch, _name in parts:
            w = 100 * vals[key] / total
            sup = isinstance(r[key], str)
            ax.barh(i, w, left=left, color=colour, hatch="///" if sup else hatch, edgecolor=DARK_GREY, linewidth=0.4)
            if not sup and w >= 8:
                ax.text(left + w / 2, i, _label(r[key]), ha="center", va="center", fontsize=9)
            left += w
    ax.set_yticks(range(len(rows)), [f"{r['criterion_id']} {r['badge']}" for r in rows], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("% of patients evaluated")
    ax.set_title("F-F3 Criterion status")
    import matplotlib.patches as mpatches

    ax.legend(
        handles=[mpatches.Patch(facecolor=c, hatch=h, edgecolor=DARK_GREY, label=n) for _k, c, h, n in parts],
        fontsize=9,
        loc="lower right",
    )
    alt = f"Stacked bars of pass, fail and unknown shares for {len(rows)} criteria; segments below {k} unlabelled."
    return FigureOut("F-F3", "Criterion status", _png(fig), alt, [dict(r) for r in rows])


def incidence(months: Sequence[dict[str, Any]], k: int) -> FigureOut:
    """F-F4: monthly new patients meeting the structured criteria (markers) and the 12-month moving average."""
    fig = _fig(170, 70)
    ax = fig.add_subplot(111)
    xs = list(range(len(months)))
    ys = [_num(m["n_new_meeting"], k) for m in months]
    sup = [isinstance(m["n_new_meeting"], str) for m in months]
    ax.plot(xs, ys, color=BLUE, linewidth=1.5, marker="o", markersize=4, label="new per month")
    for x, y, s in zip(xs, ys, sup, strict=True):
        if s:
            ax.plot([x], [y], marker="o", markersize=6, markerfacecolor="white", markeredgecolor=DARK_GREY)
    ma = [m["ma12"] for m in months]
    ax.plot(
        [x for x, v in zip(xs, ma, strict=True) if v is not None],
        [v for v in ma if v is not None],
        color=BLACK,
        linewidth=2.5,
        linestyle="--",
        label="12-month moving average",
    )
    ax.set_xticks(xs[::3], [m["month"] for m in months][::3], rotation=45, fontsize=9)
    ax.set_ylabel("patients")
    ax.legend(fontsize=9)
    ax.set_title(f"F-F4 Incidence (hollow markers: <{k})")
    alt = f"Monthly new patients meeting the criteria over {len(months)} months, with a 12-month moving average."
    return FigureOut("F-F4", "Incidence", _png(fig), alt, [dict(m) for m in months])


def fan(proj: Sequence[dict[str, Any]], target: int | None) -> FigureOut:
    """F-F10: cumulative P50 with P10–P90 (dark) and P5–P95 (light) bands; model output, so no suppression."""
    fig = _fig(170, 70)
    ax = fig.add_subplot(111)
    xs = [p["month"] for p in proj]
    ax.fill_between(xs, [p["cum_p5"] for p in proj], [p["cum_p95"] for p in proj], color="#9ecae1", label="P5–P95")
    ax.fill_between(xs, [p["cum_p10"] for p in proj], [p["cum_p90"] for p in proj], color="#4292c6", label="P10–P90")
    ax.plot(xs, [p["cum_p50"] for p in proj], color=BLACK, linewidth=2, marker="s", markersize=4, label="P50")
    if target:
        ax.axhline(target, color=GREY, linestyle="--", linewidth=1, label=f"target {target}")
    ax.set_xlabel("months from projected activation")
    ax.set_ylabel("cumulative enrolment")
    ax.legend(fontsize=9)
    ax.set_title("F-F10 Projection (fan chart)")
    last = proj[-1] if proj else {"cum_p10": 0, "cum_p50": 0, "cum_p90": 0}
    alt = (
        f"Fan chart of cumulative enrolment over {len(proj)} months: month {len(proj)} P10 {last['cum_p10']:.0f}, "
        f"P50 {last['cum_p50']:.0f}, P90 {last['cum_p90']:.0f}."
    )
    return FigureOut("F-F10", "Projection", _png(fig), alt, [dict(p) for p in proj])


def tornado(rows: Sequence[dict[str, Any]], k: int) -> FigureOut:
    """F-F12: Δ eligible when each criterion is left out, sorted; locked (safety-critical) rows hatched."""
    data = sorted(rows, key=lambda r: -_num(r["delta_n"], k) if r["delta_n"] != 0 else 0)
    fig = _fig(170, max(50, 7 * len(data) + 25))
    ax = fig.add_subplot(111)
    for i, r in enumerate(data):
        v = _num(r["delta_n"], k)
        sup = isinstance(r["delta_n"], str)
        ax.barh(
            i,
            v,
            color=LIGHT_GREY if (sup or r["locked"]) else BLUE,
            hatch="///" if sup else ("xx" if r["locked"] else None),
            edgecolor=DARK_GREY,
            linewidth=0.5,
        )
        lab = _label(r["delta_n"]) + (" (locked)" if r["locked"] else "")
        ax.text(v, i, f" {lab}", va="center", fontsize=9)
    ax.set_yticks(range(len(data)), [r["criterion_id"] for r in data], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Δ eligible if the criterion is removed (released)")
    ax.set_title("F-F12 Leave-one-out impact")
    alt = f"Tornado of leave-one-out gains for {len(data)} criteria; locked rows hatched; values below {k} '<{k}'."
    return FigureOut("F-F12", "Leave-one-out impact", _png(fig), alt, [dict(r) for r in data])


__all__ = ["PALETTE_TB_CVD_1", "FigureOut", "fan", "flow", "incidence", "stacked", "tornado", "waterfall"]
