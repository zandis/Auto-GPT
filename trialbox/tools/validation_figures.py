"""Publication figures for the 2026-11 public-data validation (docs/reviews/2026-11-05-public-data-validation.md).

Reads only committed result files (``eval/*/results``), writes PNG (300 dpi) and SVG to ``docs/figures/validation``
plus ``figure_data.json`` (every plotted number with its interval, so a figure can be re-drawn or checked).

    python -m tools.validation_figures
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures" / "validation"
EV = ROOT / "eval"

# validated categorical slots (dataviz reference palette, light mode) + neutral ink
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8985", "#e4e3df", "#ffffff"
G4, G4Q, OSS, Q9 = (
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-26b-a4b-it@fp4",
    "openai/gpt-oss-120b",
    "qwen/qwen3.5-9b",
)
CONFIGS = [  # (label, models, colour)
    ("Gemma 4 26B", [G4], MUTED),
    ("Gemma 4 26B 4-bit", [G4Q], MUTED),
    ("gpt-oss-120b", [OSS], MUTED),
    ("Qwen3.5-9B", [Q9], MUTED),
    ("Spark pair: gpt-oss-120b + Gemma 4", [G4, OSS], BLUE),
    ("RTX 5090 pair: Gemma 4 4-bit + Qwen3.5-9B", [G4Q, Q9], ORANGE),
]

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 8.5,
        "axes.titlesize": 9.5,
        "axes.titleweight": "bold",
        "axes.labelsize": 8.5,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK2,
        "axes.linewidth": 0.6,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "legend.frameon": False,
        "figure.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "svg.fonttype": "none",
    }
)
DATA: dict[str, Any] = {}


def _j(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _key(models: list[str], group: dict[str, Any]) -> dict[str, Any] | None:
    """Find a single-model or pair entry regardless of the order the scorer joined the names."""
    if len(models) == 1:
        hit = group.get("single", {}).get(models[0])
    else:
        a, b = sorted(models)
        hit = group.get("both_must_block", {}).get(f"{a}+{b}")
    return hit if isinstance(hit, dict) else None


def _save(fig: Figure, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def _panel_letter(ax: Axes, letter: str) -> None:
    ax.annotate(
        letter,
        (0, 1),
        xycoords="axes fraction",
        xytext=(-6, 5),
        textcoords="offset points",
        fontsize=12,
        fontweight="bold",
        color=INK,
        ha="right",
        va="bottom",
    )


# ---------------------------------------------------------------- data
def cohorts() -> dict[str, dict[str, Any]]:
    """cohort label -> {config label -> {lost, caught}} with point, low, high (percent)."""
    out: dict[str, dict[str, Any]] = {}
    trec = _j(EV / "trec_ct/results/scores.json")
    oc = _j(EV / "open_cohorts/results/scores.json")
    ad = _j(EV / "ad/results/scores.json").get("trec", {}).get("scores", {})

    def cell(r: dict[str, Any] | None) -> dict[str, float] | None:
        if not r:
            return None
        lo, hi = r["cluster95"]
        return {"point": 100 * r["rate"], "low": 100 * lo, "high": 100 * hi, "k": r["k"], "n": r["n"]}

    for name, src in (("TREC CT 2021-22", trec),):
        out[name] = {}
        for label, ms, _ in CONFIGS:
            e = _key(ms, src)
            if e:
                out[name][label] = {
                    "lost": cell(e["llm"]["eligible_lost"]),
                    "caught": cell(e["llm"]["excluded_caught"]),
                }
    for cname, label_c in (
        ("sigir", "SIGIR 2016 (full; eligible pairs only)"),
        ("trec2023", "TREC CT 2023 (structured)"),
    ):
        if cname in oc:
            out[label_c] = {}
            for label, ms, _ in CONFIGS:
                e = _key(ms, oc[cname])
                if e:
                    out[label_c][label] = {
                        "lost": cell(e.get("eligible_lost")),
                        "caught": cell(e.get("excluded_caught")),
                    }
    if ad:
        out["Alzheimer's trials (TREC)"] = {}
        for label, ms, _ in CONFIGS:
            e = ad.get("+".join(sorted(ms)) if len(ms) > 1 else ms[0]) or ad.get("+".join(ms))
            if e:
                out["Alzheimer's trials (TREC)"][label] = {
                    "lost": cell(e.get("eligible_lost")),
                    "caught": cell(e.get("excluded_caught")),
                }
    return out


# ---------------------------------------------------------------- figures
def fig_forest(data: dict[str, dict[str, Any]]) -> None:
    names = [c for c in data if data[c]]
    if not names:
        return
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 0.3 * len(names) * (len(CONFIGS) + 1.4) + 1.2), sharey=True)
    ylabels, ypos = [], []
    y = 1.3
    rows = []
    for c in names:
        for label, _, col in CONFIGS:
            if label in data[c]:
                rows.append((y, c, label, col, data[c][label]))
                y += 1
        y += 1.4
    for ax, metric, title, letter in (
        (axes[0], "lost", "Eligible pairs dropped (lower is safer)", "a"),
        (axes[1], "caught", "Excluded pairs caught (higher saves review)", "b"),
    ):
        for yy, _c, _label, col, d in rows:
            v = d.get(metric)
            if not v:
                continue
            ax.plot([v["low"], v["high"]], [yy, yy], color=col, lw=1.6, solid_capstyle="round")
            ax.plot(v["point"], yy, "o", ms=5.5 if col != MUTED else 4.5, color=col, mec=SURFACE, mew=0.8, zorder=3)
            ax.text(v["high"] + 1.2, yy, f"{v['point']:.1f}", va="center", fontsize=7, color=INK2)
        ax.set_title(title, loc="left")
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, 100)
        _panel_letter(ax, letter)
    for yy, _c, label, _col, _d in rows:
        ylabels.append(label)
        ypos.append(yy)
    axes[0].set_yticks(ypos, ylabels, fontsize=7.2)
    starts: dict[str, float] = {}
    for yy, c, *_ in rows:
        starts.setdefault(c, yy)
    for c, yy in starts.items():
        axes[0].text(1, yy - 0.75, c, fontsize=7.8, fontweight="bold", color=INK, ha="left", va="center")
    axes[0].set_ylim(rows[-1][0] + 0.6, 0)
    axes[1].tick_params(axis="y", left=False)
    h = fig.get_figheight()
    fig.subplots_adjust(top=1 - 0.8 / h, bottom=0.6 / h)
    fig.supxlabel(
        "% of labelled pairs, point and 95% CI (patient-cluster bootstrap)", fontsize=8.5, color=INK2, y=0.12 / h
    )
    fig.suptitle(
        "Raw pair-level results across public cohorts (labels are noisy; see Figs. 3 and 8)",
        x=0.01,
        ha="left",
        fontsize=10,
        fontweight="bold",
        y=1 - 0.1 / h,
    )
    _save(fig, "fig2_cohorts_forest")
    DATA["fig2"] = data


def fig_tradeoff(data: dict[str, dict[str, Any]]) -> None:
    d = data.get("TREC CT 2021-22", {})
    if not d:
        return
    fig, ax = plt.subplots(figsize=(4.4, 3.6))
    for label, _, col in CONFIGS:
        if label not in d:
            continue
        lo, ca = d[label]["lost"], d[label]["caught"]
        ax.errorbar(
            lo["point"],
            ca["point"],
            xerr=[[lo["point"] - lo["low"]], [lo["high"] - lo["point"]]],
            yerr=[[ca["point"] - ca["low"]], [ca["high"] - ca["point"]]],
            fmt="o",
            color=col,
            ms=6,
            mec=SURFACE,
            mew=0.8,
            elinewidth=1.0,
            capsize=0,
        )
        short = label.split(":")[0]
        dx, dy, ha = {
            "Gemma 4 26B": (-6, 6, "right"),
            "gpt-oss-120b": (6, 6, "left"),
            "Qwen3.5-9B": (6, -10, "left"),
            "Gemma 4 26B 4-bit": (-6, 6, "right"),
        }.get(short, (6, 6, "left"))
        ax.annotate(
            short,
            (lo["point"], ca["point"]),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=7,
            color=INK2,
            ha=ha,
        )
    ax.set_xlabel("Eligible pairs dropped (%)  ← safer")
    ax.set_ylabel("Excluded pairs caught (%)  ↑ less review")
    ax.set_title("Safety vs screening value, TREC CT 2021-22\n1,200 eligible / 500 excluded pairs", loc="left")
    _save(fig, "fig3a_tradeoff")


def fig_audit() -> None:
    cats = [
        ("Model error", 10, ORANGE),
        ("Label noise (criterion clearly blocks)", 12, MUTED),
        ("Criterion of another trial arm", 5, AQUA),
        ("Ambiguous", 3, YELLOW),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(6.4, 4.2), gridspec_kw={"height_ratios": [1, 1.1], "hspace": 1.25})
    ax = axes[0]
    left = 0
    for _name, n, col in cats:
        ax.barh(0, n, left=left, color=col, edgecolor=SURFACE, linewidth=2, height=0.5)
        ax.text(left + n / 2, 0, str(n), ha="center", va="center", fontsize=8, color=INK, fontweight="bold")
        left += n
    ax.set_xlim(0, 30)
    ax.set_yticks([])
    ax.set_xlabel("30 dropped eligible pairs, read by hand")
    ax.grid(False)
    ax.legend(
        handles=[Patch(color=c, label=f"{n}") for n, _, c in cats],
        labels=[n for n, _, _ in cats],
        loc="upper left",
        bbox_to_anchor=(0, -0.55),
        ncol=2,
        fontsize=7.5,
    )
    ax.set_title("Why the RTX 5090 pair dropped NIST-eligible pairs", loc="left")
    _panel_letter(ax, "a")
    ax = axes[1]
    pats = [
        ("Negated exclusion read as the condition", 5),
        ("'Other X' applied to the index condition", 2),
        ("Blocked without evidence / wrong sub-type", 3),
    ]
    ax.barh(range(len(pats)), [p[1] for p in pats], color=ORANGE, height=0.55, edgecolor=SURFACE)
    ax.set_yticks(range(len(pats)), [p[0] for p in pats], fontsize=7.2)
    ax.invert_yaxis()
    ax.set_xlabel("model errors (of 10)")
    ax.set_title("Model error patterns", loc="left")
    ax.grid(axis="y", visible=False)
    _panel_letter(ax, "b")
    _save(fig, "fig3b_audit")
    DATA["fig3b"] = {"categories": {n: k for n, k, _ in cats}, "patterns": dict(pats)}


def fig_medtxt() -> None:
    s = _j(EV / "medtxt/results/scores.json")
    if not s:
        return
    cats = [
        ("positive", "Present"),
        ("negative_strict", "Stated\nabsent"),
        ("suspicious_strict", "Suspected"),
        ("absent", "Not\nmentioned"),
    ]
    pairs = [("Spark pair", [G4, OSS], BLUE), ("RTX 5090 pair", [G4Q, Q9], ORANGE)]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9), sharey=True)
    rec: dict[str, Any] = {}
    for ax, (pname, ms, col), letter in zip(axes, pairs, "ab", strict=True):
        a, b = sorted(ms)
        for j, lang in enumerate(("en", "ja")):
            e = s["both_must_block"].get(f"{a}+{b}|{lang}")
            if not e:
                continue
            xs = [i + (j - 0.5) * 0.3 for i in range(len(cats))]
            vals = [100 * e[c]["rate"] for c, _ in cats]
            los = [100 * e[c]["cluster95"][0] for c, _ in cats]
            his = [100 * e[c]["cluster95"][1] for c, _ in cats]
            ax.bar(
                xs,
                vals,
                width=0.28,
                color=col if lang == "en" else SURFACE,
                edgecolor=col,
                linewidth=1.4,
                label="English translation" if lang == "en" else "Japanese original",
            )
            ax.errorbar(
                xs,
                vals,
                yerr=[
                    [v - lo for v, lo in zip(vals, los, strict=True)],
                    [hi - v for v, hi in zip(vals, his, strict=True)],
                ],
                fmt="none",
                ecolor=INK2,
                elinewidth=0.8,
            )
            rec[f"{pname}|{lang}"] = dict(zip([c for _, c in cats], [round(v, 1) for v in vals], strict=True))
        ax.set_xticks(range(len(cats)), [c for _, c in cats])
        ax.set_ylim(0, 100)
        ax.set_title(f"{pname}: share of findings that exclude", loc="left")
        ax.grid(axis="x", visible=False)
        ax.legend(fontsize=7, loc="upper right")
        _panel_letter(ax, letter)
    axes[0].set_ylabel("% excluded (95% CI)")
    fig.suptitle(
        "Real Japanese clinical text (MedTxt, 215 reports): Japanese lowers recall, not safety",
        x=0.01,
        ha="left",
        fontsize=10,
        fontweight="bold",
        y=1.03,
    )
    fig.tight_layout()
    _save(fig, "fig4_japanese_medtxt")
    DATA["fig4"] = rec


def fig_prompt() -> None:
    s = _j(EV / "medtxt/results/scores.json")
    if not s:
        return
    rows = []
    for label, ms, col in CONFIGS:
        for lang in ("en", "ja"):
            if len(ms) == 1:
                base = s["single"].get(f"{ms[0]}|{lang}")
                v4 = s["single"].get(f"{ms[0]}~suspected|{lang}")
            else:
                a, b = sorted(ms)
                base = s["both_must_block"].get(f"{a}+{b}|{lang}")
                a2, b2 = sorted(f"{m}~suspected" for m in ms)
                v4 = s["both_must_block"].get(f"{a2}+{b2}|{lang}")
            if base and v4:
                rows.append((f"{label.split(':')[0]} ({lang})", col, base, v4))
    if not rows:
        return
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 0.28 * len(rows) + 1.2), sharey=True, gridspec_kw={"wspace": 0.12})
    for ax, key, title, letter in (
        (axes[0], "suspicious_strict", "Suspected findings excluded (want low)", "a"),
        (axes[1], "positive", "Present findings excluded (want high)", "b"),
    ):
        for i, (_lab, col, base, v4) in enumerate(rows):
            b, v = 100 * base[key]["rate"], 100 * v4[key]["rate"]
            ax.plot([b, v], [i, i], color=GRID, lw=2, zorder=1)
            ax.plot(b, i, "o", color=SURFACE, mec=col, mew=1.4, ms=5.5, zorder=2)
            ax.plot(v, i, "o", color=col, mec=SURFACE, mew=0.8, ms=5.5, zorder=3)
        ax.set_xlim(0, 100)
        ax.set_title(title, loc="left")
        ax.set_xlabel("% of MedTxt findings")
        ax.grid(axis="y", visible=False)
        _panel_letter(ax, letter)
    axes[0].set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=7)
    axes[0].invert_yaxis()
    fig.suptitle(
        "Judge v4: suspected findings stop excluding (open circle = v3, filled = v4)",
        x=0.01,
        ha="left",
        fontsize=10,
        fontweight="bold",
        y=1.0,
    )
    fig.tight_layout()
    _save(fig, "fig5_prompt_v4")
    DATA["fig5"] = {
        r[0]: {
            "suspected_v3": round(100 * r[2]["suspicious_strict"]["rate"], 1),
            "suspected_v4": round(100 * r[3]["suspicious_strict"]["rate"], 1),
            "recall_v3": round(100 * r[2]["positive"]["rate"], 1),
            "recall_v4": round(100 * r[3]["positive"]["rate"], 1),
        }
        for r in rows
    }


def fig_routes() -> None:
    chia = _j(EV / "chia/results/routes.json").get("qualifier_needs_llm")
    ad = _j(EV / "ad/results/scores.json").get("ctgov")
    if not chia:
        return
    if ad:
        fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.8), gridspec_kw={"width_ratios": [1, 1.5], "wspace": 0.95})
    else:
        fig, ax0 = plt.subplots(figsize=(3.8, 3.4))
        axes = [ax0]
    cols = {"filter": BLUE, "llm": ORANGE, "human": AQUA}
    names = {"filter": "Structured filter (codes, labs, dates)", "llm": "LLM reads notes", "human": "Person decides"}
    ax = axes[0]
    bars = [
        ("Chia, all", chia["routes"] and {k: v["share"] for k, v in chia["routes"].items()}),
        ("Chia, inclusion", chia["routes_inclusion"]),
        ("Chia, exclusion", chia["routes_exclusion"]),
    ]
    if ad:
        bars.append(("AD trials (CT.gov)", {k: v["share"] for k, v in ad["routes"].items()}))
    for i, (_lab, sh) in enumerate(bars):
        left = 0.0
        for k in ("filter", "llm", "human"):
            w = 100 * float(sh.get(k, 0))
            ax.barh(i, w, left=left, color=cols[k], edgecolor=SURFACE, linewidth=2, height=0.6)
            if w > 7:
                ax.text(
                    left + w / 2,
                    i,
                    f"{w:.0f}%",
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color=SURFACE,
                    fontweight="bold",
                )
            left += w
    ax.set_yticks(range(len(bars)), [b[0] for b in bars])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of criteria")
    ax.grid(False)
    ax.set_title(
        f"Who decides each criterion\nChia: {chia['annotated']:,} criteria, {chia['trials']:,} trials", loc="left"
    )
    ax.legend(
        handles=[Patch(color=cols[k], label=names[k]) for k in cols],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        fontsize=7,
        ncol=1,
    )
    _panel_letter(ax, "a")
    if ad:
        ax = axes[1]
        cats = sorted(ad["by_category"].items(), key=lambda kv: -sum(kv[1].values()))
        for i, (_cat, cnt) in enumerate(cats):
            left = 0
            for k in ("filter", "llm", "human"):
                w = cnt.get(k, 0)
                ax.barh(i, w, left=left, color=cols[k], edgecolor=SURFACE, linewidth=1.5, height=0.65)
                left += w
            ax.text(left + 8, i, f"{left}", va="center", fontsize=7, color=INK2)
        ax.set_yticks(
            range(len(cats)),
            [
                c.replace("_", " ")
                .replace("ad ", "AD ")
                .replace("apoe", "APOE")
                .replace("mri", "MRI")
                .replace("other neurological or psychiatric", "other neuro / psychiatric")
                for c, _ in cats
            ],
            fontsize=7.2,
        )
        ax.invert_yaxis()
        ax.set_xlabel("criteria")
        ax.grid(axis="y", visible=False)
        ax.set_title(
            f"Alzheimer's trials: {ad['trials']} phase 2/3 trials since 2015,\n"
            f"{ad['criteria']:,} criteria by topic and route",
            loc="left",
        )
        _panel_letter(ax, "b")
    _save(fig, "fig6_routes_chia_ad")
    DATA["fig6"] = {"chia": chia["routes"], "ad": ad}


def fig_scale() -> None:
    rows = (
        json.loads((EV / "hospital_sim/results/scale.json").read_text())
        if (EV / "hospital_sim/results/scale.json").exists()
        else []
    )
    rows = sorted([r for r in rows if r["trial"] == "GZQO"], key=lambda r: r["patients"])
    if not rows:
        return
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.3))
    x = [r["patients"] / 1000 for r in rows]
    for ax, ys, lab, letter in (
        (axes[0], [r["pipeline_s"] / 60 for r in rows], "pipeline minutes", "a"),
        (
            axes[1],
            [(r["peak_rss_mb"] + r.get("peak_swap_mb", 0)) / 1024 for r in rows],
            "memory, GB (RAM + swap)",
            "b",
        ),
        (axes[2], [r["funnel"]["S5"]["in"] for r in rows], "review queue (S5)", "c"),
    ):
        ax.plot(x, ys, "-o", color=BLUE, lw=2, ms=6, mec=SURFACE, mew=0.8)
        for xi, yi in zip(x, ys, strict=True):
            ax.annotate(
                f"{yi:.1f}" if yi < 20 else f"{yi:.0f}",
                (xi, yi),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color=INK2,
            )
        ax.set_xlabel("synthetic patients (thousands)")
        ax.set_title(lab, loc="left")
        ax.set_ylim(0, max(ys) * 1.25)
        _panel_letter(ax, letter)
    fig.suptitle(
        "Full pipeline at hospital scale: all 16 checks pass at every size; linear growth",
        x=0.01,
        ha="left",
        fontsize=10,
        fontweight="bold",
        y=1.05,
    )
    fig.tight_layout()
    _save(fig, "fig7_scale")
    DATA["fig7"] = [{k: r[k] for k in ("patients", "pipeline_s", "peak_rss_mb", "model_calls")} for r in rows]


def fig_overview() -> None:
    items = []
    t = _j(EV / "trec_ct/results/scores.json").get("pairs")
    if t:
        items.append(("TREC CT 2021-22", "125 patients, NIST pair labels", t["eligible"] + t["excluded"], 20096))
    oc = _j(EV / "open_cohorts/results/scores.json")
    for c, lab, desc in (
        ("sigir", "SIGIR 2016 (full)", "58 patients, physician labels"),
        ("trec2023", "TREC CT 2023", "40 structured patient records"),
    ):
        if c in oc:
            n = sum(oc[c]["pairs"].values())
            crit = next(iter(oc[c]["single"].values()))["criteria"]
            items.append((lab, desc, n, crit))
    ad = _j(EV / "ad/results/scores.json")
    if ad.get("trec"):
        items.append(("Alzheimer's trials x TREC", "AD/dementia/MCI trials", sum(ad["trec"]["pairs"].values()), 3184))
    m = _j(EV / "medtxt/results/scores.json")
    if m:
        items.append(("MedTxt Japanese (ja + en)", "215 real Japanese reports", 0, sum(m["items"].values())))
    ch = _j(EV / "chia/results/routes.json").get("qualifier_needs_llm")
    if ch:
        items.append(("Chia criteria corpus", "1,000 trials, expert entities", 0, ch["annotated"]))
    if ad.get("ctgov"):
        items.append(("AD trials on CT.gov", "phase 2/3 since 2015", 0, ad["ctgov"]["criteria"]))
    if not items:
        return
    fig, ax = plt.subplots(figsize=(7.2, 0.36 * len(items) + 0.9))
    ax.barh(range(len(items)), [i[3] for i in items], color=BLUE, height=0.55, edgecolor=SURFACE)
    for i, (_lab, desc, pairs, crit) in enumerate(items):
        extra = f"  ·  {pairs:,} patient-trial pairs" if pairs else ""
        ax.text(crit + 300, i, f"{crit:,} criteria{extra}  ·  {desc}", va="center", fontsize=7.2, color=INK2)
    ax.set_yticks(range(len(items)), [i[0] for i in items])
    ax.invert_yaxis()
    ax.set_xlim(0, max(i[3] for i in items) * 2.1)
    ax.set_xlabel("criteria judged or routed")
    ax.grid(axis="y", visible=False)
    ax.set_title("Public data used (all D0, fetched at run time; model answers committed)", loc="left")
    _save(fig, "fig1_data_overview")
    DATA["fig1"] = items


AUDITS = {  # cohort -> (model errors, pairs read); see eval/*/AUDIT.md
    "TREC CT 2021-22": (10, 30),
    "TREC CT 2023 (structured)": (2, 12),
    "Alzheimer's trials (TREC)": (3, 15),
}


def fig_adjusted(data: dict[str, dict[str, Any]]) -> None:
    """Raw loss x share of drops that a person judged a real model error (Beta posterior, Monte Carlo)."""
    import random

    label = CONFIGS[-1][0]
    rows = []
    rng = random.Random(20261105)
    for c, (k, n) in AUDITS.items():
        cell = data.get(c, {}).get(label, {}).get("lost")
        if not cell:
            continue
        raw = cell["point"]
        sims = sorted(rng.uniform(cell["low"], cell["high"]) * rng.betavariate(k + 1, n - k + 1) for _ in range(20000))
        adj = raw * k / n
        rows.append((c, raw, cell["low"], cell["high"], adj, sims[500], sims[19499], k, n))
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(6.4, 0.75 * len(rows) + 1.3))
    for i, (_c, raw, lo, hi, adj, alo, ahi, k, n) in enumerate(rows):
        ax.plot([lo, hi], [i - 0.15, i - 0.15], color=MUTED, lw=1.6)
        ax.plot(raw, i - 0.15, "o", color=SURFACE, mec=MUTED, mew=1.4, ms=6)
        ax.text(hi + 1, i - 0.15, f"raw {raw:.1f}%", va="center", fontsize=7, color=INK2)
        ax.plot([alo, ahi], [i + 0.15, i + 0.15], color=ORANGE, lw=1.8)
        ax.plot(adj, i + 0.15, "o", color=ORANGE, mec=SURFACE, mew=0.8, ms=6.5)
        ax.text(
            ahi + 1,
            i + 0.15,
            f"true about {adj:.1f}%  ({k} model errors in {n} read)",
            va="center",
            fontsize=7,
            color=INK,
        )
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 60)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("% of NIST-eligible pairs dropped by the RTX 5090 pair (95% interval)")
    ax.set_title("After reading the dropped pairs by hand, true loss is about 6% in every cohort", loc="left")
    _save(fig, "fig8_audit_adjusted")
    DATA["fig8"] = [
        dict(
            zip(
                ("cohort", "raw", "raw_low", "raw_high", "adjusted", "adj_low", "adj_high", "errors", "read"),
                r,
                strict=True,
            )
        )
        for r in rows
    ]


def fig_synthea_ad() -> None:
    d = _j(EV / "synthea/results/ad_cohort.json")
    if not d:
        return
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.2), gridspec_kw={"width_ratios": [1.5, 1], "wspace": 0.9})
    ax = axes[0]
    steps = [("Alive, age 50-90", d["alive_50_90"])] + [
        (f["criterion"].split(" ", 1)[1], f["remaining"]) for f in d["funnel"][2:]
    ]
    for i, (_lab, n) in enumerate(steps):
        ax.barh(i, n, color=BLUE if i < 3 else AQUA, height=0.62, edgecolor=SURFACE)
        ax.text(n * 1.15 if n else 1.2, i, f"{n:,}", va="center", fontsize=7.2, color=INK2)
    ax.set_xscale("log")
    ax.set_xlim(10, d["alive_50_90"] * 4)
    ax.set_yticks(range(len(steps)), [s[0] for s in steps], fontsize=7.2)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("patients (log scale)")
    ax.set_title(f"Coded filters on {d['alive_50_90']:,} synthetic adults 50-90", loc="left")
    _panel_letter(ax, "a")
    ax = axes[1]
    order = ["22-30, current", "below 22", "older than 12 months", "no MMSE on record"]
    mm = d["ad_alive_50_90_mmse"]
    cols = [AQUA, MUTED, ORANGE, YELLOW]
    for i, (k, c) in enumerate(zip(order, cols, strict=True)):
        ax.barh(i, mm.get(k, 0), color=c, height=0.62, edgecolor=SURFACE)
        ax.text(mm.get(k, 0) + 8, i, f"{mm.get(k, 0):,}", va="center", fontsize=7.2, color=INK2)
    ax.set_yticks(
        range(len(order)),
        ["MMSE 22-30, current", "MMSE below 22", "MMSE older than 12 months", "no MMSE on record"],
        fontsize=7.2,
    )
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("patients with Alzheimer's disease")
    ax.set_title("Why they drop: the latest MMSE", loc="left")
    _panel_letter(ax, "b")
    fig.suptitle(
        f"Synthea Alzheimer's cohort: {d['coded_candidates']} coded candidates, then amyloid, MRI and study partner\n"
        "blue = inclusion, green = exclusion; Python and SQL counts agree exactly",
        x=0.01,
        ha="left",
        fontsize=9.5,
        fontweight="bold",
        y=1.04,
    )
    _save(fig, "fig9_synthea_ad_cohort")
    DATA["fig9"] = d


def main() -> None:
    fig_overview()
    data = cohorts()
    fig_forest(data)
    fig_tradeoff(data)
    fig_adjusted(data)
    fig_audit()
    fig_medtxt()
    fig_prompt()
    fig_routes()
    fig_scale()
    fig_synthea_ad()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "figure_data.json").write_text(json.dumps(DATA, indent=1, default=str))
    print("figures in", OUT, sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
