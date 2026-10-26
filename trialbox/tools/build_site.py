"""Build the public TrialBox website (static: GitHub Pages or Netlify, no server, no external requests).

    python tools/build_site.py                  # render site/ + site/data/*.json into build/site/
    python tools/build_site.py --refresh-demo   # also re-run tools.cascade_e2e (stub model) for the demo data
    python -m http.server -d build/site 8000    # preview

Sources (all public, synthetic or open data; the repository is public):

- ``site/templates/layout.html`` and ``site/pages/*.html``: hand-written HTML with ``{{ name }}`` slots.
- ``site/assets/``: CSS, JS, favicon, console screenshots, the DL-1 PDF.
- ``site/data/demo_gzqo_site_a.json``: the RELEASED (D1, external-sponsor profile) parts of a cascade run on synthetic
  site A, written by ``--refresh-demo`` (or automatically when missing and the venv exists). Exact/internal outputs
  (``*_INTERNAL_exact.json``, stage counts, tiers, final list, traces) are never copied.
- ``site/data/open_data_mimic.json``: released funnels for EMPULSE and STARRT-AKI on the MIMIC-IV FHIR demo, refreshed
  from ``.cache/open_data/report.json`` when present (the ``raw`` blocks are dropped).
- ``site/data/bakeoff.json``: model results, refreshed from ``eval/bakeoff/results/<latest date>/``: from
  ``summary.json`` when it exists, else assembled from ``metrics_*.json`` + ``cascade_*.json`` (marked preliminary).
- ``site/data/trialgpt_comparison.json``: the TrialGPT comparison slot (schema in ``site/README.md``), filled by hand.

Every generated file is scanned for API keys, private keys and private IP addresses; the build fails on a hit.
Standard library only, so the Netlify / GitHub Actions build needs nothing but Python 3.12.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DATA = SITE / "data"
OUT_DEFAULT = ROOT / "build" / "site"
BAKEOFF_RESULTS = ROOT / "eval" / "bakeoff" / "results"
OPEN_DATA_REPORT = ROOT / ".cache" / "open_data" / "report.json"
DEMO_SOURCE = Path("tests/fixtures/synthetic_patients/site-a")
REPO_BLOB = "https://github.com/zandis/Auto-GPT/blob/master/trialbox"
REPO_TREE = "https://github.com/zandis/Auto-GPT/tree/master/trialbox"
K_SITE = 11  # small-cell threshold of the dc.sponsor profile (demo pack)
SLOT = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")
LANG_NAMES = {"en": ("English", "英語"), "zh-TW": ("Trad. Chinese", "繁体字中国語"), "ja": ("Japanese", "日本語")}
LANG_NAMES["mixed"] = ("Mixed zh/ja/en", "混在")
LANG_ORDER = ["en", "zh-TW", "ja", "mixed"]
METRIC_KEYS = (
    "n",
    "accuracy",
    "lenient_accuracy",
    "macro_f1",
    "false_block_rate",
    "false_block_upper95",
    "block_recall",
    "agreement_with_gpt4",
    "evidence_f1",
    "invalid_rate",
    "cost_per_1k_usd",
    "cost_usd",
    "latency_mean_s",
    "latency_p50_s",
    "latency_p95_s",
)
CASCADE_KEYS = (
    "passed",
    "certificate_status",
    "calls",
    "schema_valid",
    "cost_usd",
    "latency_ms_mean",
    "seconds",
    "failed_checks",
    "gateway_refusals",
)
SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[0-9a-f]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{32,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
]

Json = Any


class BuildError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------------ small helpers
def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def t(en: str, ja: str | None = None) -> str:
    """Bilingual inline text: both spans are in the page, ``html[data-lang]`` shows one (CSS)."""
    if ja is None or ja == en:
        return esc(en)
    return f'<span class="l-en">{esc(en)}</span><span class="l-ja" lang="ja">{esc(ja)}</span>'


def read_json(path: Path) -> Json:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc: Json) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def is_num(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def fnum(value: object) -> str:
    if is_num(value):
        assert isinstance(value, int | float)
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,}"
    return "—" if value is None else str(value)


def as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def pct(value: object, digits: int = 1) -> str:
    if not is_num(value):
        return "—"
    assert isinstance(value, int | float)
    return f"{value * 100:.{digits}f}%"


def cell(value: object) -> str:
    """A released count: suppressed values get a badge (``<k`` primary, ``x`` complementary)."""
    if isinstance(value, str) and value.startswith("<"):
        return f'<span class="supp" title="small cell suppressed">{esc(value)}</span>'
    if value == "x":
        return '<span class="supp comp" title="complementary suppression">x</span>'
    return esc(fnum(value))


def suppress(value: object, k: int = K_SITE) -> object:
    """Site-side small-cell rule for counts the pack carries unrounded (recall certificate strata)."""
    if is_num(value) and isinstance(value, int) and 0 < value < k:
        return f"<{k}"
    return value


def criteria_ja() -> dict[str, str]:
    path = SITE / "i18n" / "criteria_ja.json"
    doc = read_json(path) if path.exists() else {}
    return {k: v for k, v in doc.items() if not k.startswith("_")}


# ------------------------------------------------------------------------------------------------ data refresh
def extract_demo(e2e_dir: Path) -> dict[str, Any]:
    """Released parts of one ``tools.cascade_e2e`` run: the D1 DL-1 object plus pass/fail checks. Nothing exact."""
    summary = read_json(e2e_dir / "e2e_summary.json")
    packs = sorted((e2e_dir / "dl1").glob("DL1_*.json"))
    packs = [p for p in packs if "INTERNAL" not in p.name]
    if not packs:
        raise BuildError(f"{e2e_dir}/dl1: no released DL1_*.json")
    pack = read_json(packs[0])
    obj = pack["object"]
    if obj.get("data_class") != "D1" or obj.get("logic_text_released") is not False:
        raise BuildError(f"{packs[0]}: not a released D1 pack (data_class {obj.get('data_class')!r})")
    tables = obj.get("tables", {})
    figs = obj.get("figures", {})
    rc = dict(obj.get("recall_certificate", {}))
    rc.pop("cells", None)  # per-cell ledger detail: not needed on the site
    for stratum in rc.get("strata", []):
        for key in ("excluded", "found"):
            stratum[key] = suppress(stratum.get(key))
    for line in rc.get("known_positive", []):
        for key in ("r", "missed"):
            line[key] = suppress(line.get(key))
    rc["never_excluded"] = {k: suppress(v) for k, v in (rc.get("never_excluded") or {}).items()}
    cascade = obj.get("cascade", {})
    return {
        "schema": "trialbox.site.demo@1",
        "source": "tools.cascade_e2e (stub model, no network) -> dl1/DL1_<trial>.json (released D1 object only)",
        "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
        "pack_sha256": pack.get("sha256"),
        "deliverable": obj.get("deliverable"),
        "pack_schema": obj.get("schema"),
        "data_class": obj.get("data_class"),
        "recipient_class": obj.get("recipient_class"),
        "profile": obj.get("profile"),
        "site": obj.get("site"),
        "snapshot": obj.get("snapshot"),
        "study_id": obj.get("study_id"),
        "ruleset": obj.get("ruleset"),
        "headline": obj.get("headline"),
        "cascade": {
            "n_scope": cascade.get("n_scope"),
            "n_after": cascade.get("n_after"),
            "semantics": cascade.get("semantics"),
            "llm_share": cascade.get("llm_share"),
            "pairs_judged": cascade.get("pairs_judged"),
        },
        "study": tables.get("F-T2"),
        "attrition": tables.get("F-T5"),
        "tiers": tables.get("F-T8"),
        "projection": tables.get("F-T17"),
        "flow": (figs.get("F-F1") or {}).get("data"),
        "recall_certificate": rc,
        "disclosure_trace": obj.get("disclosure_trace"),
        "disclaimers": obj.get("disclaimers"),
        "checks": summary.get("checks"),
        "passed": summary.get("passed"),
        "certificate_status": summary.get("certificate_status"),
        "model": {"mode": (summary.get("gateway") or {}).get("mode"), "builds": "deterministic llm_stub (no network)"},
        "seconds": summary.get("seconds"),
    }


def refresh_demo(python: Path, trial: str) -> None:
    with tempfile.TemporaryDirectory(prefix="tb-site-e2e-") as tmp:
        env = dict(os.environ, TB_ENV="TEST", PYTHONPATH="libs:services:.")
        env.pop("TB_GATEWAY_URL", None)  # always the in-process stub: no network, reproducible
        cmd = [str(python), "-m", "tools.cascade_e2e", "--source", str(DEMO_SOURCE), "--trial", trial, "--out", tmp]
        print("running:", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd, check=False, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1200)
        if proc.returncode != 0:
            raise BuildError(f"cascade_e2e failed ({proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
        out = Path(tmp)
        write_json(DATA / f"demo_{trial.lower()}_site_a.json", extract_demo(out))
        pdfs = [p for p in (out / "dl1").glob("DL1_*.pdf") if "INTERNAL" not in p.name]
        if pdfs:
            (SITE / "assets" / "downloads").mkdir(parents=True, exist_ok=True)
            release_pdf(pdfs[0], SITE / "assets" / "downloads" / pdfs[0].name)


INTERNAL_MARKERS = ("INTERNAL appendix", "/ exact ")


def release_pdf(src: Path, dst: Path) -> None:
    """Copy the DL-1 PDF without its INTERNAL released-vs-exact appendix (open/synthetic runs append one).

    Needs pypdf (in the project venv). If any page still carries an internal marker afterwards, nothing is copied.
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        print("pypdf not available: DL-1 PDF not refreshed (run with .venv/bin/python)", file=sys.stderr)
        return
    reader = PdfReader(str(src))
    writer = PdfWriter()
    dropped = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        if any(marker in text for marker in INTERNAL_MARKERS):
            dropped += 1
            continue
        writer.add_page(page)
    tmp = dst.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        writer.write(fh)
    check = PdfReader(str(tmp))
    if any(any(m in (p.extract_text() or "") for m in INTERNAL_MARKERS) for p in check.pages):
        tmp.unlink()
        raise BuildError(f"{src}: internal appendix still present after stripping; PDF not published")
    tmp.replace(dst)
    print(f"DL-1 PDF: {len(check.pages)} pages released, {dropped} internal page(s) dropped")


def refresh_open_data(report_path: Path) -> bool:
    if not report_path.exists():
        return False
    rep = read_json(report_path)
    trials = {}
    for tid, tr in (rep.get("trials") or {}).items():
        rel = tr.get("released") or {}
        trials[tid] = {
            "title": tr.get("title"),
            "nct_id": tr.get("nct_id"),
            "criteria": tr.get("criteria"),
            "funnel": rel.get("funnel"),
            "start_n": rel.get("start_n"),
            "lookback_months": rel.get("lookback_months"),
            "snapshot": rel.get("snapshot"),
            "population": rel.get("population"),
        }
    ds = rep.get("dataset") or {}
    doc = {
        "schema": "trialbox.site.open_data@1",
        "source": ".cache/open_data/report.json (released blocks only; raw per-criterion counts dropped)",
        "dataset": {k: ds.get(k) for k in ("name", "version", "url", "licence")},
        "patients": rep.get("patients"),
        "small_cell": (rep.get("run") or {}).get("small_cell"),
        "run_date": (rep.get("run") or {}).get("run_date"),
        "passed": rep.get("passed"),
        "reproducible": rep.get("reproducible"),
        "trials": trials,
    }
    write_json(DATA / "open_data_mimic.json", doc)
    return True


def _metric_block(raw: Json) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {k: raw[k] for k in METRIC_KEYS if k in raw and (is_num(raw[k]) or raw[k] is None)}


def normalise_model(raw: Json, fallback_id: str = "") -> dict[str, Any] | None:
    """One model entry from a ``metrics_<build>.json`` file or a ``summary.json`` model entry (flat or by_lang)."""
    if not isinstance(raw, dict):
        return None
    build_id = str(raw.get("build_id") or raw.get("id") or raw.get("build") or fallback_id)
    variant = str(raw.get("variant") or "")  # e.g. "trialgpt": the same build with another prompt, its own row
    langs: dict[str, dict[str, Any]] = {}
    ref: dict[str, dict[str, Any]] = {}
    by_lang = raw.get("by_lang") or raw.get("langs_metrics") or raw.get("metrics")
    if isinstance(by_lang, dict) and any(isinstance(v, dict) and "accuracy" in v for v in by_lang.values()):
        for lang, block in by_lang.items():
            if isinstance(block, dict):
                langs[lang] = _metric_block(block)
                if isinstance(block.get("gpt4_reference_same_items"), dict):
                    ref[lang] = _metric_block(block["gpt4_reference_same_items"])
    elif "accuracy" in raw:
        lang = str(raw.get("lang") or "en")
        langs[lang] = _metric_block(raw)
    if not langs:
        return None
    pin: dict[str, Any] = raw["provider_pin"] if isinstance(raw.get("provider_pin"), dict) else {}
    rule = f" ({raw['rule']})" if isinstance(raw.get("rule"), str) else ""  # combined rows, e.g. "agree:a+b"
    name = str(raw.get("model_name") or raw.get("name") or build_id + rule)
    short = re.sub(r"\s*\((hosted|GPT-4-class reference)[^)]*\)\s*$", "", name).strip()
    return {
        "build_id": f"{build_id}__{variant}" if variant else build_id,
        "variant": variant or None,
        "model_name": f"{name} [{variant} prompt]" if variant else name,
        "short_name": f"{short} · {variant}" if variant else short,
        "provider": pin.get("provider") or raw.get("provider"),
        "model": pin.get("model") or raw.get("model"),
        "reasoning_effort": raw.get("reasoning_effort"),
        "role": "reference" if "reference" in (build_id + name).lower() else "candidate",
        "langs": langs,
        "gpt4_recorded_same_items": ref,
    }


def refresh_bakeoff(results_root: Path) -> bool:
    dirs = sorted(d for d in results_root.glob("20*") if d.is_dir()) if results_root.exists() else []
    if not dirs:
        return False
    run = dirs[-1]
    meta = read_json(run / "run_meta.json") if (run / "run_meta.json").exists() else {}
    models: list[dict[str, Any]] = []
    status, source, extra = "preliminary", "metrics_*.json + cascade_*.json (summary.json not written yet)", {}
    summary_path = run / "summary.json"
    if summary_path.exists():
        summary = read_json(summary_path)
        raw_models: Iterable[tuple[str, Json]] = []
        candidates = summary.get("models", summary.get("builds", summary)) if isinstance(summary, dict) else summary
        if isinstance(candidates, dict):
            raw_models = candidates.items()
        elif isinstance(candidates, list):
            raw_models = ((str(i), m) for i, m in enumerate(candidates))
        for key, raw in raw_models:
            entry = normalise_model(raw, key)
            if entry:
                if isinstance(raw, dict) and isinstance(raw.get("cascade"), dict):
                    entry["cascade"] = {k: raw["cascade"][k] for k in CASCADE_KEYS if k in raw["cascade"]}
                models.append(entry)
        runs = summary.get("cascade") if isinstance(summary, dict) else None
        by_build = {str(c.get("build_id")): c for c in runs or [] if isinstance(c, dict)}
        for entry in models:
            if "cascade" not in entry and entry["build_id"] in by_build:
                entry["cascade"] = {
                    k: by_build[entry["build_id"]][k] for k in CASCADE_KEYS if k in by_build[entry["build_id"]]
                }
        if models:
            status, source = "final", "summary.json"
            if isinstance(summary, dict):
                extra = {
                    k: summary[k]
                    for k in ("recommendation", "winner", "ranking", "verdict", "notes", "weights")
                    if k in summary and isinstance(summary[k], str | list | dict)
                }
                extra["summary_keys"] = sorted(summary)
    if not models:
        for path in sorted(run.glob("metrics_*.json")):
            entry = normalise_model(read_json(path), path.stem.removeprefix("metrics_"))
            if entry:
                models.append(entry)
    for entry in models:
        cpath = run / f"cascade_{entry['build_id']}.json"
        if "cascade" not in entry and cpath.exists():
            craw = read_json(cpath)
            entry["cascade"] = {k: craw[k] for k in CASCADE_KEYS if k in craw}
    doc = {
        "schema": "trialbox.site.bakeoff@1",
        "status": status if models else "pending",
        "date": run.name,
        "source": f"eval/bakeoff/results/{run.name}/ :: {source}",
        "note": meta.get("note"),
        "request": meta.get("request"),
        "dataset": {
            "name": "TrialGPT-Criterion-Annotations (NCBI), SIGIR cohort",
            "url": "https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations",
            "items": 1015,
            "labels": "physician criterion-level labels; 'recorded GPT-4' = the label stored from the TrialGPT run",
        },
        "models": models,
        **extra,
    }
    write_json(DATA / "bakeoff.json", doc)
    return True


TRIALGPT_TEMPLATE: dict[str, Any] = {
    "schema": "trialbox.trialgpt_comparison@1",
    "status": "pending",
    "updated": None,
    "owner": "comparison team",
    "notes": "Fill 'systems' (and optionally 'tasks'); set status to 'final'. Field definitions: site/README.md.",
    "dataset": {
        "name": "TrialGPT-Criterion-Annotations (NCBI)",
        "url": "https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations",
        "split": "SIGIR",
        "n_items": 1015,
        "licence": "see dataset card",
    },
    "systems": [],
    "tasks": [],
}


# ------------------------------------------------------------------------------------------------ chart fragments
@dataclass
class Bar:
    label_en: str
    value: float | None
    shown: str
    label_ja: str | None = None
    kind: str = "normal"  # normal | ref | hatched | zero | s1..s4
    tip_en: str = ""
    tip_ja: str = ""
    whisker: float | None = None
    note_en: str = ""
    note_ja: str = ""


def bar_chart(
    bars: list[Bar],
    *,
    cap: tuple[str, str],
    sub: tuple[str, str],
    vmax: float,
    ticks: list[tuple[float, str]],
    legend: str = "",
) -> str:
    rows = []
    for b in bars:
        width = 0.0 if b.value is None or vmax <= 0 else max(0.0, min(100.0, b.value / vmax * 100))
        cls = "bar " + (b.kind if b.kind != "normal" else "")
        if b.value == 0:
            cls = "bar zero"
        whisker = ""
        if b.whisker is not None and vmax > 0:
            whisker = f'<span class="whisker" style="left:{min(100.0, b.whisker / vmax * 100):.2f}%"></span>'
        note = f" <small>{t(b.note_en, b.note_ja or None)}</small>" if b.note_en else ""
        tip = f' data-tip="{esc(b.tip_en)}"' if b.tip_en else ""
        tip += f' data-tip-ja="{esc(b.tip_ja)}"' if b.tip_ja else ""
        rows.append(
            f'<div class="bar-row" tabindex="0"{tip}><span class="bar-label">{t(b.label_en, b.label_ja)}{note}</span>'
            f'<span class="bar-track"><span class="{cls.strip()}" style="width:{width:.2f}%"></span>{whisker}</span>'
            f'<span class="bar-val">{esc(b.shown)}</span></div>'
        )
    tick_html = "".join(f"<span>{esc(lbl)}</span>" for _, lbl in ticks)
    return (
        f'<figure class="chart"><figcaption>{t(*cap)}</figcaption><div class="sub">{t(*sub)}</div>{legend}'
        f'<div class="bars">{"".join(rows)}</div>'
        f'<div class="axis" aria-hidden="true"><span></span><span class="ticks">{tick_html}</span><span></span></div>'
        "</figure>"
    )


def multi_bar_chart(
    groups: list[tuple[str, str | None, list[tuple[float | None, str, str, str]]]],
    *,
    cap: tuple[str, str],
    sub: tuple[str, str],
    vmax: float,
    ticks: list[tuple[float, str]],
    legend: str,
) -> str:
    """Rows of several thin bars (series). Each series item: (value, shown, css class, tooltip)."""
    rows = []
    for label_en, label_ja, series in groups:
        bars, vals, tips = [], [], []
        for value, shown, klass, tip in series:
            w = 0.0 if value is None else max(0.0, min(100.0, value / vmax * 100))
            bars.append(f'<span class="bar thin {klass}" style="width:{w:.2f}%"></span>')
            vals.append(f"<span>{esc(shown)}</span>")
            tips.append(tip)
        rows.append(
            f'<div class="bar-row" tabindex="0" data-tip="{esc(" · ".join(tips))}">'
            f'<span class="bar-label">{t(label_en, label_ja)}</span>'
            f'<span class="bar-track multi">{"".join(bars)}</span><span class="bar-val '
            f'multi">{"".join(vals)}</span></div>'
        )
    tick_html = "".join(f"<span>{esc(lbl)}</span>" for _, lbl in ticks)
    return (
        f'<figure class="chart"><figcaption>{t(*cap)}</figcaption><div class="sub">{t(*sub)}</div>{legend}'
        f'<div class="bars">{"".join(rows)}</div>'
        f'<div class="axis" aria-hidden="true"><span></span><span class="ticks">{tick_html}</span><span></span></div>'
        "</figure>"
    )


def legend(items: list[tuple[str, str, str]]) -> str:
    """items: (css colour or 'hatch', en, ja)."""
    spans = []
    for colour, en, ja in items:
        if colour == "hatch":
            spans.append(f'<span class="hatch">{t(en, ja)}</span>')
        else:
            spans.append(f'<span style="--c:{colour}">{t(en, ja)}</span>')
    return f'<div class="chart-legend">{"".join(spans)}</div>'


def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    for step in (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if value <= step * 4:
            return step * 4
    return value


def ticks_for(vmax: float, fmt: Callable[[float], str]) -> list[tuple[float, str]]:
    return [(vmax * i / 4, fmt(vmax * i / 4)) for i in range(5)]


def table(
    headers: list[str], rows: list[list[str]], row_classes: list[str] | None = None, num_cols: Iterable[int] = ()
) -> str:
    nums = set(num_cols)
    head = "".join(f'<th scope="col"{" class=num" if i in nums else ""}>{h}</th>' for i, h in enumerate(headers))
    body = []
    for r, row in enumerate(rows):
        klass = f' class="{row_classes[r]}"' if row_classes and row_classes[r] else ""
        tds = "".join(f"<td{' class=num' if i in nums else ''}>{c}</td>" for i, c in enumerate(row))
        body.append(f"<tr{klass}>{tds}</tr>")
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    return f'<div class="table-wrap" tabindex="0">{table}</div>'  # focusable: keyboard users can scroll it


# ------------------------------------------------------------------------------------------------ landing
ARROW = (
    '<div class="pipe-arrow" aria-hidden="true"><svg viewBox="0 0 20 20"><path d="M3 10h12M11 5l5 5-5 5" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
)
PIPE_COLOURS = {"deterministic": "var(--surface-2)", "llm": "var(--warn-soft)", "human": "var(--good-soft)"}


def site_text() -> dict[str, Any]:
    doc: dict[str, Any] = read_json(SITE / "i18n" / "site_text.json")
    return doc


def pipeline(lang: str) -> str:
    spec = site_text()["pipeline"][lang]
    parts = []
    for i, step in enumerate(spec["steps"]):
        li = "".join(f"<li>{esc(x)}</li>" for x in step["items"])
        strip = ""
        if i == 2:
            kinds = ["", "", "", "", "llm", "llm", "human"]
            stages = ["S0", "S1", "S2", "S2b", "S3", "S4", "S5"]
            spans = "".join(f'<span class="{k}">{s}</span>' for s, k in zip(stages, kinds, strict=True))
            strip = f'<div class="cascade-strip" aria-hidden="true">{spans}</div>'
        out = " out" if i == len(spec["steps"]) - 1 else ""
        parts.append(
            f'<div class="pipe-step{out}" role="listitem"><div class="tag">{esc(step["tag"])}</div>'
            f"<h3>{esc(step['title'])}</h3>"
            f"<ul>{li}</ul>{strip}</div>"
        )
        if i < len(spec["steps"]) - 1:
            parts.append(ARROW)
    leg = "".join(
        f'<span><i style="background:{PIPE_COLOURS[x["kind"]]};border:1px solid '
        f'var(--border)"></i>{esc(x["label"])}</span>'
        for x in spec["legend"]
    )
    return f'<div class="pipeline" role="list">{"".join(parts)}</div><div class="legend-inline">{leg}</div>'


# ------------------------------------------------------------------------------------------------ demo page
def projection_svg(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    w, h, left, right, top, bottom = 640, 250, 46, 14, 14, 40
    months = [int(r["month"]) for r in rows]
    vmax = nice_max(max(float(r.get("cum_p95") or r.get("cum_p90") or 0) for r in rows))

    def x(m: float) -> float:
        return left + (m - min(months)) / max(1, max(months) - min(months)) * (w - left - right)

    def y(v: float) -> float:
        return top + (1 - v / vmax) * (h - top - bottom)

    def band(lo: str, hi: str) -> str:
        pts = [f"{x(r['month']):.1f},{y(float(r[hi])):.1f}" for r in rows]
        pts += [f"{x(r['month']):.1f},{y(float(r[lo])):.1f}" for r in reversed(rows)]
        return " ".join(pts)

    grid = []
    for i in range(5):
        v = vmax * i / 4
        grid.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        grid.append(f'<text x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{fnum(round(v, 1))}</text>')
    for m in months:
        if m in (1, 3, 6, 9, 12) or len(months) <= 6:
            grid.append(f'<text x="{x(m):.1f}" y="{h - bottom + 16}" text-anchor="middle">{m}</text>')
    line = " ".join(f"{x(r['month']):.1f},{y(float(r['cum_p50'])):.1f}" for r in rows)
    dots = "".join(
        f'<circle class="dot" cx="{x(r["month"]):.1f}" cy="{y(float(r["cum_p50"])):.1f}" r="4">'
        f"<title>month {r['month']}: P50 {fnum(r['cum_p50'])} (P10 {fnum(r['cum_p10'])}–P90 "
        f"{fnum(r['cum_p90'])})</title></circle>"
        for r in rows
    )
    axis = (
        f'<g class="l-en"><text x="{(left + w - right) / 2}" y="{h - 4}" text-anchor="middle">months from '
        "start</text></g>"
        f'<g class="l-ja"><text x="{(left + w - right) / 2}" y="{h - 4}" text-anchor="middle">開始からの月数</text></g>'
    )
    has95 = all("cum_p5" in r and "cum_p95" in r for r in rows)
    outer = f'<polygon class="band" points="{band("cum_p5", "cum_p95")}"/>' if has95 else ""
    return (
        f'<svg class="fan" viewBox="0 0 {w} {h}" role="img" aria-label="Cumulative enrolment projection, P50 with '
        'P10–P90 band">'
        f"{''.join(grid)}{outer}"
        f'<polygon class="band2" points="{band("cum_p10", "cum_p90")}"/>'
        f'<polyline class="line" points="{line}"/>{dots}{axis}</svg>'
    )


def demo_fragments(demo: dict[str, Any] | None, open_data: dict[str, Any] | None) -> dict[str, str]:
    ja = criteria_ja()
    frag: dict[str, str] = {}
    if not demo:
        pending = (
            '<div class="notice warn"><strong>Demo data missing</strong>'
            "Run <code>python tools/build_site.py --refresh-demo</code>.</div>"
        )
        for key in ("demo_tiles", "cascade_chart", "attrition_chart", "attrition_table", "tier_table", "projection"):
            frag[key] = pending if key == "demo_tiles" else ""
        frag.update(recall_card="", disclosure="", checks="", demo_meta="", study_table="")
    else:
        head = demo.get("headline") or {}
        cas = demo.get("cascade") or {}
        n_after = cas.get("n_after") or {}
        adj = head.get("adjusted_estimate") or {}
        proj = head.get("projection_12m") or {}
        rc = demo.get("recall_certificate") or {}
        tiles = [
            (("Population of scope", "対象集団"), fnum(cas.get("n_scope")), ("synthetic patients, S0", "合成患者・S0")),
            (
                ("After structured rules (S1)", "構造化ルール通過（S1）"),
                fnum(n_after.get("S1")),
                ("SQL, cost ≈ 0", "SQL・コスト≈0"),
            ),
            (
                ("Final (S5)", "最終（S5）"),
                fnum(n_after.get("S5")),
                (f"small cells shown as <{K_SITE}", f"{K_SITE}未満は秘匿"),
            ),
            (
                ("Adjusted estimate", "補正推定"),
                fnum(adj.get("est")),
                (
                    f"95% interval {fnum(adj.get('ci95_low'))}–{fnum(adj.get('ci95_high'))}",
                    f"95%区間 {fnum(adj.get('ci95_low'))}–{fnum(adj.get('ci95_high'))}",
                ),
            ),
            (
                ("Enrolment in 12 months", "12か月の登録予測"),
                fnum(proj.get("p50")),
                (
                    f"P10 {fnum(proj.get('p10'))} – P90 {fnum(proj.get('p90'))}",
                    f"P10 {fnum(proj.get('p10'))} – P90 {fnum(proj.get('p90'))}",
                ),
            ),
            (
                ("Recall certificate", "再現率証明書"),
                str((rc.get("rc_id") and demo.get("certificate_status")) or "—"),
                (
                    f"≤ {float(rc.get('per_1000_excluded_upper') or 0):.1f} per 1,000 excluded",
                    f"除外1,000人あたり最大 {float(rc.get('per_1000_excluded_upper') or 0):.1f} 人",
                ),
            ),
        ]
        frag["demo_tiles"] = (
            '<div class="tiles">'
            + "".join(
                f'<div class="tile"><div class="k">{t(*k)}</div><div class="v">{esc(v)}</div><div '
                f'class="s">{t(*s)}</div></div>'
                for k, v, s in tiles
            )
            + "</div>"
        )

        stage_names = {
            "S0": ("S0 scope, consent, opt-outs", "S0 対象・同意・オプトアウト"),
            "S1": ("S1 structured rules (SQL)", "S1 構造化ルール（SQL）"),
            "S2": ("S2 lexicon pre-filter", "S2 辞書プレフィルタ"),
            "S2b": ("S2b semantic screen", "S2b 意味スクリーン"),
            "S3": ("S3 LLM judge (residue)", "S3 LLM 判定（残り）"),
            "S4": ("S4 second opinion", "S4 セカンドオピニオン"),
            "S5": ("S5 person decides", "S5 人が判断"),
        }
        scope = float(cas.get("n_scope") or 1)
        bars = []
        for stage, (en, jl) in stage_names.items():
            v = n_after.get(stage)
            if is_num(v):
                bars.append(
                    Bar(
                        en,
                        as_float(v) or 0.0,
                        fnum(v),
                        jl,
                        tip_en=f"{stage}: {fnum(v)} patients after stage",
                        tip_ja=f"{stage}: 通過 {fnum(v)} 人",
                    )
                )
            elif isinstance(v, str):
                bars.append(
                    Bar(
                        en,
                        K_SITE - 1,
                        v,
                        jl,
                        kind="hatched",
                        tip_en=f"{stage}: {v} (suppressed)",
                        tip_ja=f"{stage}: {v}（秘匿）",
                    )
                )
        frag["cascade_chart"] = bar_chart(
            bars,
            cap=("Cascade funnel: patients after each stage", "カスケード・ファネル：各段階の通過患者数"),
            sub=(
                f"Released counts (profile dc.sponsor, k = {K_SITE}, rounded to 5). Hatched = suppressed small cell, "
                "drawn at its upper bound.",
                f"公開値（dc.sponsor、k = {K_SITE}、5単位で丸め）。斜線は秘匿された小セル（上限で描画）。",
            ),
            vmax=scope,
            ticks=ticks_for(scope, lambda v: fnum(round(v))),
            legend=legend(
                [("var(--bar)", "patients", "患者数"), ("hatch", f"suppressed (<{K_SITE})", f"秘匿（{K_SITE}未満）")]
            ),
        )

        attr = demo.get("attrition") or []
        bars = []
        for r in attr:
            lbl = str(r.get("label", ""))
            lja = ja.get(lbl)
            rem = r.get("n_remaining")
            cid = str(r.get("criterion_id") or "")
            note_en = "" if r.get("applied", True) else "not applied: note/human"
            note_ja = "" if r.get("applied", True) else "未適用：記録/人"
            tip_en = f"{cid} {lbl}: remaining {rem}, excluded {r.get('n_excluded')}"
            tip_ja = f"{cid} {lja or lbl}：残り {rem}、除外 {r.get('n_excluded')}"
            if is_num(rem):
                bars.append(
                    Bar(
                        lbl,
                        float(rem),
                        fnum(rem),
                        lja,
                        kind="normal" if r.get("applied", True) else "ref",
                        tip_en=tip_en,
                        tip_ja=tip_ja,
                        note_en=note_en,
                        note_ja=note_ja,
                    )
                )
            elif rem == "x":
                bars.append(
                    Bar(
                        lbl,
                        None,
                        "x",
                        lja,
                        kind="hatched",
                        tip_en=tip_en + " (complementary suppression)",
                        tip_ja=tip_ja + "（補完秘匿）",
                        note_en=note_en,
                        note_ja=note_ja,
                    )
                )
            else:
                bars.append(
                    Bar(
                        lbl,
                        K_SITE - 1,
                        str(rem),
                        lja,
                        kind="hatched",
                        tip_en=tip_en,
                        tip_ja=tip_ja,
                        note_en=note_en,
                        note_ja=note_ja,
                    )
                )
        frag["attrition_chart"] = bar_chart(
            bars,
            cap=("Attrition: patients remaining after each criterion", "脱落：各基準適用後の残り患者数"),
            sub=(
                "Sequential, in protocol order. 'x' = complementary suppression (would let a small cell be recovered "
                "by subtraction).",
                "プロトコル順の逐次適用。「x」は補完秘匿（差し引きで小セルが復元されるのを防ぐ）。",
            ),
            vmax=scope,
            ticks=ticks_for(scope, lambda v: fnum(round(v))),
            legend=legend(
                [
                    ("var(--bar)", "applied", "適用"),
                    ("var(--bar-ref)", "not applied (note / human)", "未適用（記録 / 人）"),
                    ("hatch", "suppressed", "秘匿"),
                ]
            ),
        )
        rows, classes = [], []
        for r in attr:
            lbl = str(r.get("label", ""))
            rows.append(
                [
                    esc(r.get("step")),
                    f'<span class="mono">{esc(r.get("criterion_id") or "—")}</span>',
                    t(lbl, ja.get(lbl)),
                    esc(r.get("stage")),
                    cell(r.get("n_excluded")),
                    cell(r.get("n_remaining")),
                    cell(r.get("n_unknown_data_gap")),
                    cell(r.get("n_unknown_uncertain")),
                    esc("—" if r.get("pct_excluded_of_prev") is None else f"{r['pct_excluded_of_prev']:.1f}"),
                ]
            )
            classes.append("" if r.get("applied", True) else "not-applied")
        frag["attrition_table"] = table(
            [
                "#",
                t("Criterion", "基準"),
                t("Label", "内容"),
                t("Stage", "段階"),
                t("Excluded", "除外"),
                t("Remaining", "残り"),
                t("Unknown: data gap", "不明：データ欠損"),
                t("Unknown: uncertain", "不明：判定不能"),
                t("% excl. of previous", "前段からの除外%"),
            ],
            rows,
            classes,
            num_cols=(4, 5, 6, 7, 8),
        )
        tier_names = {
            "strong": ("strong (every criterion decided by records)", "strong（全基準を記録で判定）"),
            "potential:data_gap": ("potential: data gap", "potential：データ欠損"),
            "potential:uncertain": ("potential: uncertain", "potential：判定不能"),
            "watchlist": ("watchlist", "ウォッチリスト"),
        }
        frag["tier_table"] = table(
            [
                t("Tier", "階層"),
                t("Estimate", "推定"),
                t("95% low", "95%下限"),
                t("95% high", "95%上限"),
                t("Sampled", "抽出数"),
            ],
            [
                [
                    t(*tier_names.get(str(r.get("tier")), (str(r.get("tier")), str(r.get("tier"))))),
                    cell(r.get("est")),
                    cell(r.get("ci95_low")),
                    cell(r.get("ci95_high")),
                    cell(r.get("n_sampled")),
                ]
                for r in demo.get("tiers") or []
            ],
            num_cols=(1, 2, 3, 4),
        )
        frag["projection"] = (
            '<figure class="chart"><figcaption>'
            + t("Cumulative enrolment projection (12 months)", "累積登録予測（12か月）")
            + "</figcaption>"
            '<div class="sub">'
            + t(
                "Median (line), P10–P90 (dark band), P5–P95 (light band). Model output from default reach and accept "
                "rates.",
                "中央値（線）、P10–P90（濃い帯）、P5–P95（薄い帯）。既定の到達率・同意率によるモデル出力。",
            )
            + "</div>"
            + projection_svg(demo.get("projection") or [])
            + "</figure>"
        )
        strata = rc.get("strata") or []
        kp = rc.get("known_positive") or []
        ne = rc.get("never_excluded") or {}
        alpha = rc.get("alpha")
        p1000 = float(rc.get("per_1000_excluded_upper") or 0)
        quoted = next((x for x in kp if x.get("line") == rc.get("quoted_line")), kp[0] if kp else {})
        stmt_en = (rc.get("statement") or {}).get("en", "")
        stmt_ja = (
            "再現率の下限は "
            f"{float(quoted.get('recall_lower') or 0):.3f}"
            f"（{'既往登録者・旧プロセスで見つかったため偏りあり' if quoted.get('biased') else '偏りのない母集団'}）。"
            f"除外された患者 1,000 人あたり、適格だった可能性があるのは最大 {p1000:.1f} 人（常時有効、α = {alpha}）。"
            "盲検カルテレビューの件数はまだ少なく、目標は r = 30。"
        )
        frag["recall_card"] = (
            f'<div class="card"><h3>{t("Statement", "証明文")} <span class="pill '
            f'ok">{esc(demo.get("certificate_status"))}</span></h3>'
            f"<p>{t(stmt_en, stmt_ja)}</p>"
            '<dl class="kv">'
            f"<dt>{t('Certificate id', '証明書 ID')}</dt><dd class='mono'>{esc(rc.get('rc_id'))}</dd>"
            f"<dt>{t('Method', '手法')}</dt><dd>{esc(rc.get('method'))}</dd>"
            f"<dt>{t('Registered', '事前登録')}</dt><dd>{esc(rc.get('registered_at'))}</dd>"
            f"<dt>{t('Ruleset / run', 'ルールセット / 実行')}</dt><dd class='mono'>{esc(rc.get('ruleset'))} · "
            f"{esc(rc.get('run_id'))}</dd>"
            f"<dt>{t('Never excluded', '一度も除外されず')}</dt><dd>{t('abstained only', '判定保留のみ')} "
            f"{cell(ne.get('abstained_only'))} · "
            f"{t('data gap only', 'データ欠損のみ')} {cell(ne.get('data_gap_only'))} · {t('unprocessed', '未処理')} "
            f"{cell(ne.get('unprocessed'))}</dd>"
            "</dl></div>"
            + table(
                [
                    t("Exclusion stratum", "除外層"),
                    t("Excluded", "除外数"),
                    t("Ledger sample", "台帳サンプル"),
                    t("Found eligible", "適格発見"),
                    t("Missed (upper)", "見逃し上限"),
                    t("Per 1,000 excluded (upper)", "除外1,000人あたり上限"),
                ],
                [
                    [
                        f'<span class="mono">{esc(s.get("stage"))}</span>',
                        cell(s.get("excluded")),
                        cell(s.get("ledger_sampled")),
                        cell(s.get("found")),
                        esc(f"{float(s.get('missed_upper') or 0):.2f}"),
                        esc(f"{float(s.get('per_1000_excluded_upper') or 0):.1f}"),
                    ]
                    for s in strata
                ],
                num_cols=(1, 2, 3, 4, 5),
            )
            + table(
                [
                    t("Known-positive line", "既知陽性ライン"),
                    t("Population", "母集団"),
                    "r",
                    t("Recall lower bound", "再現率下限"),
                    t("Biased", "偏り"),
                ],
                [
                    [
                        esc(x.get("label")),
                        esc(x.get("population")),
                        cell(x.get("r")),
                        esc(f"{float(x.get('recall_lower') or 0):.3f}"),
                        t("yes", "あり") if x.get("biased") else t("no", "なし"),
                    ]
                    for x in kp
                ],
                num_cols=(2, 3),
            )
        )
        steps = (demo.get("disclosure_trace") or {}).get("steps") or []
        step_ja = {
            "exact_aggregates": "厳密集計（院内のみ）",
            "primary_suppression": "一次秘匿",
            "independent_rounding": "独立丸め",
            "complementary_suppression": "補完秘匿",
            "rates_from_unrounded": "率は丸め前から計算",
            "no_reason_by_demographic_below_k": "k未満の属性別理由なし",
            "differencing_check": "差分攻撃チェック",
            "freeze_hash": "凍結ハッシュ",
        }
        items = []
        for s in steps:
            name = str(s.get("step"))
            params = ", ".join(
                f"{k}={v}" for k, v in s.items() if k not in ("step", "fields") and not isinstance(v, dict | list)
            )
            items.append(
                f"<li><b>{t(name.replace('_', ' '), step_ja.get(name))}</b> <span class='muted "
                f"small'>{esc(params)}</span></li>"
            )
        frag["disclosure"] = f"<ol>{''.join(items)}</ol>"
        checks = demo.get("checks") or {}
        frag["checks"] = (
            '<ol class="checks">'
            + "".join(
                f"<li><span class='pill {'ok' if v else 'no'}'>{'pass' if v else 'fail'}</span> <span class='mono "
                f"small'>{esc(k)}</span></li>"
                for k, v in sorted(checks.items())
            )
            + "</ol>"
        )
        study = demo.get("study") or []
        frag["study_table"] = (
            '<dl class="kv">'
            + "".join(f"<dt>{esc(r.get('item'))}</dt><dd>{esc(fnum(r.get('value')))}</dd>" for r in study)
            + "</dl>"
        )
        frag["demo_meta"] = esc(
            f"{demo.get('deliverable')} {demo.get('pack_schema')} · {(demo.get('site') or {}).get('name')} · snapshot "
            f"{(demo.get('snapshot') or {}).get('id')} · ruleset {(demo.get('ruleset') or {}).get('id')} "
            f"v{(demo.get('ruleset') or {}).get('version')} · "
            f"profile {(demo.get('profile') or {}).get('name')} (k={(demo.get('profile') or {}).get('k')}, base "
            f"{(demo.get('profile') or {}).get('base')}) · "
            f"pack {str(demo.get('pack_sha256') or '')[:19]}… · built {demo.get('generated')}"
        )
    frag["open_data"] = open_data_fragment(open_data, ja)
    pdfs = sorted((SITE / "assets" / "downloads").glob("DL1_*.pdf"))
    frag["pdf_link"] = (
        f'<a class="btn primary" href="assets/downloads/{esc(pdfs[0].name)}" '
        f"download>{t('Download the DL-1 feasibility pack (PDF)', 'DL-1 実施可能性パックをダウンロード（PDF）')}</a>"
        if pdfs
        else ""
    )
    return frag


def open_data_fragment(doc: dict[str, Any] | None, ja: dict[str, str]) -> str:
    if not doc:
        return (
            '<div class="notice"><strong>Open-data run not included</strong>Run <code>make eval-public</code> '
            "(writes .cache/open_data/report.json) and rebuild.</div>"
        )
    ds = doc.get("dataset") or {}
    k = int(doc.get("small_cell") or 5)
    out = [
        f'<p class="small muted">{t("Dataset", "データセット")}: <a '
        f'href="{esc(ds.get("url"))}">{esc(ds.get("name"))} {esc(ds.get("version"))}</a> · '
        f"{esc(ds.get('licence'))} · {esc(doc.get('patients'))} {t('patients (public demo)', '人（公開デモ）')} · "
        f"{t('released counts', '公開値')}: "
        f"{t(f'cells below {k} shown as <{k}, others rounded to 5', f'{k}未満は <{k}、他は5単位で丸め')}</p>"
    ]
    for tid, tr in (doc.get("trials") or {}).items():
        funnel = tr.get("funnel") or []
        start = float(
            tr.get("start_n")
            or (funnel[0].get("remaining") if funnel and is_num(funnel[0].get("remaining")) else 100)
            or 100
        )
        bars = []
        for r in funnel:
            lbl = str(r.get("label"))
            rem = r.get("remaining")
            applied = bool(r.get("applied", True))
            note = ("", "") if applied else ("not applied: note/human", "未適用：記録/人")
            tip = f"{r.get('criterion_id')}: remaining {rem}, dropped {r.get('dropped')}"
            if is_num(rem):
                bars.append(
                    Bar(
                        lbl,
                        float(rem),
                        fnum(rem),
                        ja.get(lbl),
                        kind="normal" if applied else "ref",
                        tip_en=tip,
                        note_en=note[0],
                        note_ja=note[1],
                    )
                )
            else:
                bars.append(
                    Bar(lbl, k - 1, str(rem), ja.get(lbl), kind="hatched", tip_en=tip, note_en=note[0], note_ja=note[1])
                )
        chart = bar_chart(
            bars,
            cap=(
                f"{tid} ({tr.get('nct_id')}): remaining after each criterion",
                f"{tid}（{tr.get('nct_id')}）：各基準適用後の残り",
            ),
            sub=(str(tr.get("title") or ""), str(tr.get("title") or "")),
            vmax=start,
            ticks=ticks_for(start, lambda v: fnum(round(v))),
            legend=legend(
                [
                    ("var(--bar)", "applied", "適用"),
                    ("var(--bar-ref)", "not applied", "未適用"),
                    ("hatch", f"<{k} suppressed", f"<{k} 秘匿"),
                ]
            ),
        )
        rows = [
            [
                f'<span class="mono">{esc(r.get("criterion_id"))}</span>',
                t(str(r.get("label")), ja.get(str(r.get("label")))),
                cell(r.get("dropped")),
                cell(r.get("remaining")),
                cell(r.get("unknown", "—")),
            ]
            for r in funnel
        ]
        classes = ["" if r.get("applied", True) else "not-applied" for r in funnel]
        out.append(
            f"<details{' open' if not out[1:] else ''}><summary>{esc(tid)} · {esc(tr.get('title'))}</summary>{chart}"
            + table(
                [
                    t("Criterion", "基準"),
                    t("Label", "内容"),
                    t("Dropped", "脱落"),
                    t("Remaining", "残り"),
                    t("Unknown", "不明"),
                ],
                rows,
                classes,
                num_cols=(2, 3, 4),
            )
            + "</details>"
        )
    return "".join(out)


# ------------------------------------------------------------------------------------------------ report page
def report_fragments(bake: dict[str, Any] | None, tg: dict[str, Any] | None) -> dict[str, str]:
    frag: dict[str, str] = {}
    status = (bake or {}).get("status", "pending")
    models: list[dict[str, Any]] = list((bake or {}).get("models") or [])
    if status == "final":
        frag["report_status"] = (
            f'<div class="notice ok"><strong>{t("Final results", "確定結果")}</strong>{t("Rendered from", "出典")} '
            f"<code>{esc(bake.get('source') if bake else '')}</code>.</div>"
        )
    elif status == "preliminary":
        frag["report_status"] = (
            f'<div class="notice warn"><strong>{t("Preliminary results", "暫定結果")}</strong>'
            + t(
                "summary.json for this run is not written yet; numbers below are assembled from the per-model "
                "metrics files and may change.",
                "この実行の summary.json "
                "はまだありません。以下はモデル別メトリクスファイルから集計した暫定値で、変わる可能性があります。",
            )
            + f" <code>{esc(bake.get('source') if bake else '')}</code></div>"
        )
    else:
        frag["report_status"] = (
            f'<div class="notice warn"><strong>{t("Results pending", "結果待ち")}</strong>'
            + t(
                "No bake-off results were found when this site was built. Expected input: "
                "eval/bakeoff/results/<date>/summary.json (fields in site/README.md).",
                "サイト生成時にベイクオフ結果がありませんでした。想定入力：eval/bakeoff/results/<date>/summary.json"
                "（項目は site/README.md）。",
            )
            + "</div>"
        )

    def en(m: dict[str, Any]) -> dict[str, Any]:
        langs: dict[str, dict[str, Any]] = m.get("langs") or {}
        return langs.get("en") or next(iter(langs.values()), {})

    models.sort(key=lambda m: (m.get("role") == "reference", -float(en(m).get("accuracy") or 0)))
    ref_rec: dict[str, Any] = {}
    for m in models:
        cand = (m.get("gpt4_recorded_same_items") or {}).get("en")
        if cand and int(en(m).get("n") or 0) >= int(ref_rec.get("_n", 0)):
            ref_rec = dict(cand, _n=int(en(m).get("n") or 0))
    frag["report_meta"] = esc(
        f"run {bake.get('date')} · {len(models)} model builds · {bake.get('dataset', {}).get('name')}"
        if bake and models
        else "no run"
    )
    if not models:
        for key in (
            "report_tiles",
            "acc_chart",
            "lang_chart",
            "fb_chart",
            "cost_chart",
            "lat_chart",
            "metrics_table",
            "cascade_table",
            "run_note",
        ):
            frag[key] = ""
    else:
        full = [m for m in models if not m.get("variant")] or models  # variant rows ran on a subset
        best = full[0]
        cands = [m for m in full if m.get("role") != "reference"] or full
        cheapest = min(cands, key=lambda m: float(en(m).get("cost_per_1k_usd") or 1e9))
        safest = min(cands, key=lambda m: float(en(m).get("false_block_rate") or 1e9))
        frag["report_tiles"] = (
            '<div class="tiles">'
            + "".join(
                f'<div class="tile"><div class="k">{t(*k)}</div><div class="v">{esc(v)}</div><div '
                f'class="s">{esc(s)}</div></div>'
                for k, v, s in [
                    (
                        ("Items per language", "言語あたり件数"),
                        fnum(en(best).get("n")),
                        "TrialGPT-Criterion-Annotations",
                    ),
                    (
                        ("Best accuracy (EN)", "最高正解率（英語）"),
                        pct(en(best).get("accuracy")),
                        str(best.get("short_name")),
                    ),
                    (
                        ("Lowest false-block (EN)", "最低誤ブロック率（英語）"),
                        pct(en(safest).get("false_block_rate")),
                        str(safest.get("short_name")),
                    ),
                    (
                        ("Cheapest per 1k items", "1,000件あたり最安"),
                        f"${float(en(cheapest).get('cost_per_1k_usd') or 0):.3f}",
                        str(cheapest.get("short_name")),
                    ),
                    (
                        ("TrialGPT GPT-4 (recorded)", "TrialGPT GPT-4（記録値）"),
                        pct(ref_rec.get("accuracy")),
                        "same items, accuracy",
                    ),
                ]
            )
            + "</div>"
        )

        def model_bar(m: dict[str, Any], key: str, fmt: Callable[[float], str], whisker_key: str | None = None) -> Bar:
            blk = en(m)
            v = blk.get(key)
            ref = m.get("role") == "reference"
            w = blk.get(whisker_key) if whisker_key else None
            return Bar(
                str(m.get("short_name")),
                as_float(v),
                fmt(as_float(v) or 0.0) if is_num(v) else "—",
                kind="ref" if ref else "normal",
                tip_en=f"{m.get('model_name')} · {m.get('provider') or ''} · n={fnum(blk.get('n'))}",
                note_en="closed reference" if ref else "",
                note_ja="クローズド参照" if ref else "",
                whisker=as_float(w),
            )

        acc_bars = [model_bar(m, "accuracy", pct) for m in models]
        if ref_rec:
            acc_bars.append(
                Bar(
                    "TrialGPT GPT-4 (recorded label)",
                    float(ref_rec.get("accuracy") or 0),
                    pct(ref_rec.get("accuracy")),
                    "TrialGPT GPT-4（記録ラベル）",
                    kind="ref",
                    tip_en="label stored from the TrialGPT paper run, same items",
                    tip_ja="TrialGPT 論文の実行で保存されたラベル（同一項目）",
                )
            )
        frag["acc_chart"] = bar_chart(
            acc_bars,
            cap=("Accuracy vs physician labels (English notes)", "医師ラベルに対する正解率（英語ノート）"),
            sub=(
                "Six-way criterion label; grey = reference systems, not candidates for the box.",
                "6 分類の基準ラベル。灰色は参照システム（院内搭載候補ではない）。",
            ),
            vmax=1.0,
            ticks=ticks_for(1.0, lambda v: f"{v * 100:.0f}%"),
        )
        multi = [m for m in models if len(m.get("langs") or {}) > 1]
        series_cls = {"en": "s1", "zh-TW": "s2", "ja": "s3", "mixed": "s4"}
        groups: list[tuple[str, str | None, list[tuple[float | None, str, str, str]]]] = []
        for m in multi:
            ser: list[tuple[float | None, str, str, str]] = []
            for lang in LANG_ORDER:
                blk = (m.get("langs") or {}).get(lang)
                if blk:
                    ser.append(
                        (
                            float(blk.get("accuracy") or 0),
                            pct(blk.get("accuracy")),
                            series_cls[lang],
                            f"{LANG_NAMES[lang][0]} {pct(blk.get('accuracy'))} (n={fnum(blk.get('n'))})",
                        )
                    )
            groups.append((str(m.get("short_name")), None, ser))
        frag["lang_chart"] = (
            multi_bar_chart(
                groups,
                cap=("Accuracy by note language", "ノート言語別の正解率"),
                sub=(
                    "Same items rendered in Traditional Chinese, Japanese and mixed text (TrialBox renderings). The "
                    "GPT-4.1 reference ran 200 items for non-English languages.",
                    "同一項目を繁体字中国語・日本語・混在テキストに変換（TrialBox 版）。GPT-4.1 参照は英語以外 200 "
                    "項目。",
                ),
                vmax=1.0,
                ticks=ticks_for(1.0, lambda v: f"{v * 100:.0f}%"),
                legend=legend(
                    [
                        (f"var(--series-{i + 1})", LANG_NAMES[lang][0], LANG_NAMES[lang][1])
                        for i, lang in enumerate(LANG_ORDER)
                    ]
                ),
            )
            if groups
            else ""
        )
        fb_max = nice_max(
            max(
                [float(en(m).get("false_block_upper95") or en(m).get("false_block_rate") or 0) for m in models]
                + [float(ref_rec.get("false_block_upper95") or 0)]
            )
        )
        fb_bars = [model_bar(m, "false_block_rate", lambda v: pct(v, 2), "false_block_upper95") for m in models]
        if ref_rec:
            fb_bars.append(
                Bar(
                    "TrialGPT GPT-4 (recorded label)",
                    float(ref_rec.get("false_block_rate") or 0),
                    pct(ref_rec.get("false_block_rate"), 2),
                    "TrialGPT GPT-4（記録ラベル）",
                    kind="ref",
                    whisker=float(ref_rec.get("false_block_upper95") or 0) or None,
                )
            )
        frag["fb_chart"] = bar_chart(
            fb_bars,
            cap=("False-block rate (lower is better)", "誤ブロック率（低いほど良い）"),
            sub=(
                "Share of items where the model would wrongly exclude an eligible patient. Tick = 95% upper bound.",
                "適格な患者を誤って除外してしまう割合。目盛り線は 95% 上限。",
            ),
            vmax=fb_max,
            ticks=ticks_for(fb_max, lambda v: f"{v * 100:.1f}%"),
        )
        cost_max = nice_max(max(float(en(m).get("cost_per_1k_usd") or 0) for m in models))
        frag["cost_chart"] = bar_chart(
            [model_bar(m, "cost_per_1k_usd", lambda v: f"${v:.3f}") for m in models],
            cap=(
                "Cost per 1,000 criterion judgements (USD, hosted)",
                "基準判定 1,000 件あたりのコスト（USD、ホスティング）",
            ),
            sub=(
                "OpenRouter reported cost per call, English run. On-box (DGX Spark) inference has no per-call cost.",
                "OpenRouter が報告した呼び出し単価（英語）。院内（DGX Spark）推論には呼び出し課金なし。",
            ),
            vmax=cost_max,
            ticks=ticks_for(cost_max, lambda v: f"${v:.2f}"),
        )
        lat_max = nice_max(max(float(en(m).get("latency_p95_s") or en(m).get("latency_p50_s") or 0) for m in models))
        lat_groups: list[tuple[str, str | None, list[tuple[float | None, str, str, str]]]] = [
            (
                str(m.get("short_name")),
                None,
                [
                    (
                        float(en(m).get("latency_p50_s") or 0),
                        f"{float(en(m).get('latency_p50_s') or 0):.1f}s",
                        "s1",
                        f"p50 {float(en(m).get('latency_p50_s') or 0):.2f}s",
                    ),
                    (
                        float(en(m).get("latency_p95_s") or 0),
                        f"{float(en(m).get('latency_p95_s') or 0):.1f}s",
                        "s2",
                        f"p95 {float(en(m).get('latency_p95_s') or 0):.2f}s",
                    ),
                ],
            )
            for m in models
        ]
        frag["lat_chart"] = multi_bar_chart(
            lat_groups,
            cap=("Latency per judgement (seconds)", "判定 1 件あたりのレイテンシ（秒）"),
            sub=(
                "Hosted endpoints through tb-gateway, 8 workers; includes network.",
                "tb-gateway 経由のホスティング、8 並列。ネットワーク時間を含む。",
            ),
            vmax=lat_max,
            ticks=ticks_for(lat_max, lambda v: f"{v:.0f}s"),
            legend=legend([("var(--series-1)", "p50", "p50（中央値）"), ("var(--series-2)", "p95", "p95")]),
        )
        tables_html = []
        for lang in LANG_ORDER:
            rows = []
            for m in models:
                blk = (m.get("langs") or {}).get(lang)
                if not blk:
                    continue
                rows.append(
                    [
                        esc(m.get("short_name")),
                        esc(m.get("provider") or "—"),
                        esc(fnum(blk.get("n"))),
                        esc(pct(blk.get("accuracy"))),
                        esc(pct(blk.get("macro_f1"))),
                        esc(f"{pct(blk.get('false_block_rate'), 2)} (≤{pct(blk.get('false_block_upper95'), 2)})"),
                        esc(pct(blk.get("block_recall"))),
                        esc(pct(blk.get("agreement_with_gpt4"))),
                        esc(pct(blk.get("invalid_rate"), 2)),
                        esc(f"${float(blk.get('cost_per_1k_usd') or 0):.3f}"),
                        esc(f"{float(blk.get('latency_p50_s') or 0):.2f}"),
                        esc(f"{float(blk.get('latency_p95_s') or 0):.2f}"),
                    ]
                )
            if rows:
                tables_html.append(
                    f"<details{' open' if lang == 'en' else ''}><summary>{t(*LANG_NAMES[lang])}</summary>"
                    + table(
                        [
                            t("Model", "モデル"),
                            t("Provider", "提供元"),
                            "n",
                            t("Accuracy", "正解率"),
                            "macro-F1",
                            t("False-block (95% upper)", "誤ブロック（95%上限）"),
                            t("Block recall", "ブロック再現率"),
                            t("Agreement w/ GPT-4", "GPT-4 との一致"),
                            t("Invalid", "無効"),
                            t("$ / 1k", "$ / 1,000件"),
                            "p50 s",
                            "p95 s",
                        ],
                        rows,
                        num_cols=range(2, 12),
                    )
                    + "</details>"
                )
        frag["metrics_table"] = "".join(tables_html)
        crow = []
        for m in models:
            c = m.get("cascade")
            if not c:
                continue
            ok = bool(c.get("passed"))
            crow.append(
                [
                    esc(m.get("short_name")),
                    f"<span class='pill {'ok' if ok else 'no'}'>{'pass' if ok else 'fail'}</span>",
                    esc(c.get("certificate_status") or "—"),
                    esc(fnum(c.get("calls"))),
                    esc(fnum(c.get("schema_valid"))),
                    esc(f"${float(c.get('cost_usd') or 0):.4f}"),
                    esc(f"{float(c.get('latency_ms_mean') or 0) / 1000:.1f}"),
                    esc(", ".join(c.get("failed_checks") or []) or "—"),
                    esc(", ".join(f"{k}: {v}" for k, v in (c.get("gateway_refusals") or {}).items()) or "—"),
                ]
            )
        frag["cascade_table"] = (
            table(
                [
                    t("Model", "モデル"),
                    t("E2E", "E2E"),
                    t("Certificate", "証明書"),
                    t("Judge calls", "判定呼出"),
                    t("Schema-valid", "スキーマ適合"),
                    t("Cost", "コスト"),
                    t("Mean latency s", "平均レイテンシ 秒"),
                    t("Failed checks", "不合格チェック"),
                    t("Gateway refusals", "ゲートウェイ拒否"),
                ],
                crow,
                num_cols=(3, 4, 5, 6),
            )
            if crow
            else ""
        )
        frag["run_note"] = f"<p class='small muted'>{esc((bake or {}).get('note') or '')}</p>"
    frag["trialgpt_section"] = trialgpt_fragment(tg)
    return frag


def trialgpt_fragment(tg: dict[str, Any] | None) -> str:
    systems = list((tg or {}).get("systems") or [])
    if not tg or not systems:
        return (
            f'<div class="notice warn"><strong>{t("Comparison pending", "比較待ち")}</strong>'
            + t(
                "The TrialGPT comparison team fills site/data/trialgpt_comparison.json (schema "
                "trialbox.trialgpt_comparison@1, documented in site/README.md). "
                "Until then this section stays empty; the recorded TrialGPT GPT-4 labels above are the interim "
                "reference.",
                "TrialGPT 比較チームが site/data/trialgpt_comparison.json（スキーマ "
                "trialbox.trialgpt_comparison@1、site/README.md に記載）を記入します。"
                "それまでは上の TrialGPT GPT-4 記録ラベルを暫定の参照とします。",
            )
            + f' <a href="{REPO_BLOB}/site/README.md">{t("Schema", "スキーマ")}</a></div>'
        )
    metrics = ["accuracy", "macro_f1", "false_block_rate", "block_recall", "cost_per_1k_usd", "latency_p50_s"]
    rows = []
    for s in systems:
        m = s.get("metrics") or {}
        rows.append(
            [
                t(str(s.get("label") or s.get("id")), s.get("label_ja")),
                esc(s.get("kind") or "—"),
                esc(s.get("model") or "—"),
            ]
            + [esc(pct(m.get(k)) if k not in ("cost_per_1k_usd", "latency_p50_s") else fnum(m.get(k))) for k in metrics]
        )
    bars = [
        Bar(
            str(s.get("label") or s.get("id")),
            float((s.get("metrics") or {}).get("accuracy") or 0),
            pct((s.get("metrics") or {}).get("accuracy")),
            s.get("label_ja"),
            kind="ref" if s.get("kind") != "trialbox" else "normal",
            tip_en=str(s.get("source") or ""),
        )
        for s in systems
        if is_num((s.get("metrics") or {}).get("accuracy"))
    ]
    out = []
    status = str(tg.get("status") or "pending")
    if status != "final":
        out.append(
            f'<div class="notice warn"><strong>{t("Draft comparison", "比較（草稿）")}</strong>status = '
            f"{esc(status)}</div>"
        )
    if bars:
        out.append(
            bar_chart(
                bars,
                cap=("TrialBox vs TrialGPT: accuracy", "TrialBox と TrialGPT：正解率"),
                sub=(
                    str((tg.get("dataset") or {}).get("name") or ""),
                    str((tg.get("dataset") or {}).get("name") or ""),
                ),
                vmax=1.0,
                ticks=ticks_for(1.0, lambda v: f"{v * 100:.0f}%"),
            )
        )
    out.append(
        table(
            [
                t("System", "システム"),
                t("Kind", "種別"),
                t("Model", "モデル"),
                t("Accuracy", "正解率"),
                "macro-F1",
                t("False-block", "誤ブロック"),
                t("Block recall", "ブロック再現率"),
                t("$ / 1k", "$ / 1,000件"),
                "p50 s",
            ],
            rows,
            num_cols=range(3, 9),
        )
    )
    for task in tg.get("tasks") or []:
        vals = task.get("values") or {}
        out.append(
            f"<h3>{esc(task.get('task'))} · {esc(task.get('metric'))}</h3>"
            + table(
                [t("System", "システム"), esc(task.get("metric"))],
                [[esc(k), esc(fnum(v))] for k, v in vals.items()],
                num_cols=(1,),
            )
        )
    if tg.get("notes"):
        out.append(f"<p class='small muted'>{esc(tg.get('notes'))}</p>")
    return "".join(out)


# ------------------------------------------------------------------------------------------------ screenshots
def shots_fragment() -> str:
    items = []
    for shot in site_text()["shots"]:
        name = shot["file"]
        if not (SITE / "assets" / "screens" / name).exists():
            continue
        title, cap = shot["title"], shot["caption"]
        items.append(
            f'<figure class="shot"><a href="assets/screens/{name}"><img src="assets/screens/{name}" '
            f'alt="{esc(title["en"])}: {esc(cap["en"])}" loading="lazy" width="1280" height="900"></a>'
            f"<figcaption><b>{t(title['en'], title['ja'])}</b>{t(cap['en'], cap['ja'])}</figcaption></figure>"
        )
    if not items:
        return (
            '<div class="notice warn"><strong>Screenshots missing</strong>'
            "Copy the console PNGs to site/assets/screens/.</div>"
        )
    return f'<div class="shots">{"".join(items)}</div>'


# ------------------------------------------------------------------------------------------------ consent explainer
def consent_fragments(rec: dict[str, Any] | None) -> dict[str, str]:
    """The consent page: the record ``tools.consent_live --site`` wrote (synthetic consent form, real models)."""
    keys = ("consent_meta", "consent_tiles", "consent_pages", "consent_held")
    if not rec:
        pending = t(
            "Not generated yet: run tools.consent_live --site.",
            "未生成：tools.consent_live --site を実行してください。",
        )
        return {k: (pending if k == "consent_meta" else "") for k in keys}
    if str(ROOT / "services") not in sys.path:
        sys.path.insert(0, str(ROOT / "services"))
    from orchestrator.reports.consent_html import DISCLAIMER, QUIZ, SECTION_ORDER, SECTION_TITLES

    langs = [lang for lang in ("en", "ja", "zh-TW") if lang in rec.get("languages", [])]
    c = rec.get("counts") or {}
    run = rec.get("run") or {}
    models = rec.get("models") or {}
    frag: dict[str, str] = {}
    frag["consent_meta"] = t(
        f"Consent form {esc(rec['icf']['filename'])} (synthetic) · draft model {esc(models.get('draft'))} · "
        f"second model {esc(models.get('verifier') or 'none')} · {esc(run.get('calls', '?'))} model calls · "
        f"generated {esc(str(rec.get('created', ''))[:10])}",
        f"同意説明文書 {esc(rec['icf']['filename'])}（合成）· 下書きモデル {esc(models.get('draft'))} · "
        f"第 2 モデル {esc(models.get('verifier') or 'なし')} · モデル呼び出し {esc(run.get('calls', '?'))} 回 · "
        f"生成 {esc(str(rec.get('created', ''))[:10])}",
    )
    tiles = [
        (
            ("Statements drafted", "下書きした記述"),
            c.get("items", 0),
            ("plus teach-back questions", "＋理解確認の質問"),
        ),
        (("Questions", "質問"), c.get("questions", 0), ("for the consent visit", "同意取得の面談用")),
        (
            ("Removed by quote check", "引用確認で削除"),
            c.get("removed", 0),
            ("quote not in the form", "文書にない引用"),
        ),
        (("Held back", "保留"), c.get("held", 0), ("statement × language", "記述 × 言語")),
        (("Verified", "確認済み"), c.get("ok", 0), ("statement × language", "記述 × 言語")),
    ]
    frag["consent_tiles"] = (
        '<div class="tiles">'
        + "".join(
            f'<div class="tile"><div class="k">{t(*k)}</div><div class="v">{esc(v)}</div>'
            f'<div class="s">{t(*s)}</div></div>'
            for k, v, s in tiles
        )
        + "</div>"
    )
    names = {"en": "English", "ja": "日本語", "zh-TW": "繁體中文"}
    panels = []
    for i, lang in enumerate(langs):

        def shown(x: dict[str, Any], lang: str = lang) -> bool:
            tx = x["texts"].get(lang) or {}
            return not x.get("removed") and tx.get("status") in ("ok", "unverified")

        body = [f'<p class="notice"><strong>{esc(DISCLAIMER[lang])}</strong></p>']
        for sec in SECTION_ORDER:
            rows = [x for x in rec["items"] if x["section"] == sec and shown(x)]
            if rows:
                body.append(f"<h3>{esc(SECTION_TITLES[sec][lang])}</h3><ul>")
                body += [f"<li>{esc(x['texts'][lang]['text'])}</li>" for x in rows]
                body.append("</ul>")
        qs = [q for q in rec["questions"] if shown(q)]
        if qs:
            body.append(f"<h3>{esc(QUIZ[lang][0])}</h3><ol>")
            body += [f"<li>{esc(q['texts'][lang]['question'])}</li>" for q in qs]
            body.append("</ol>")
        html_lang = "zh-Hant-TW" if lang == "zh-TW" else lang
        panels.append(
            f'<details class="card"{" open" if i == 0 else ""}><summary><b>{esc(names[lang])}</b></summary>'
            f'<div lang="{html_lang}">{"".join(body)}</div></details>'
        )
    frag["consent_pages"] = "".join(panels)
    rows = []
    for x in rec["items"] + rec["questions"]:
        for lang in langs:
            tx = x["texts"].get(lang) or {}
            if x.get("removed") or tx.get("status") != "held":
                continue
            text = tx.get("text") or f"{tx.get('question', '')} — {tx.get('answer', '')}"
            rows.append(
                [
                    esc(x["id"]),
                    esc(lang),
                    f'<span lang="{esc(lang)}">{esc(text)}</span>'
                    + (
                        f'<br><span class="muted small">↩ {esc(tx["back_translation"])}</span>'
                        if lang != "en" and tx.get("back_translation")
                        else ""
                    ),
                    f'<span class="muted">{esc(x["quote"])}</span>',
                    esc(tx.get("problem") or ""),
                ]
            )
    frag["consent_held"] = (
        table(
            [
                t("Id", "ID"),
                t("Lang", "言語"),
                t("Statement", "記述"),
                t("Consent-form quote", "同意説明文書の引用"),
                t("Why held", "保留の理由"),
            ],
            rows,
        )
        if rows
        else f"<p>{t('Nothing was held back in this run.', 'この実行では保留はありませんでした。')}</p>"
    )
    return frag


# ------------------------------------------------------------------------------------------------ pages + layout
@dataclass
class Page:
    out: str  # path under the output dir
    source: str  # site/pages/<source>
    title: str
    description: str
    lang: str  # en | ja | zh-TW
    nav: str  # nav key for aria-current
    toggle: bool  # EN/日本語 toggle for bilingual blocks


PAGES = [
    Page(
        "index.html",
        "index.en.html",
        "TrialBox",
        "On-prem eligibility compiler and patient-finding appliance, driven by e-mail and a web console.",
        "en",
        "home",
        False,
    ),
    Page(
        "ja/index.html",
        "index.ja.html",
        "TrialBox（日本語）",
        "院内設置型の適格性コンパイラ兼患者探索アプライアンス。メールと Web コンソールで操作。",
        "ja",
        "home",
        False,
    ),
    Page(
        "zh-tw/index.html",
        "index.zh-TW.html",
        "TrialBox（繁體中文）",
        "院內部署的收案條件編譯器與病人搜尋設備，以電子郵件與網頁主控台操作。",
        "zh-TW",
        "home",
        False,
    ),
    Page(
        "demo.html",
        "demo.html",
        "Live demo · TrialBox",
        "Static walkthrough of a feasibility cascade run on synthetic site A.",
        "en",
        "demo",
        True,
    ),
    Page(
        "consent.html",
        "consent.html",
        "Consent explainer · TrialBox",
        "A plain-language consent-form guide in EN/JA/zh-TW, checked against the form and by a second model.",
        "en",
        "consent",
        True,
    ),
    Page(
        "screens.html",
        "screens.html",
        "Screenshots · TrialBox",
        "Admin console and web mail tour of the TrialBox POC.",
        "en",
        "screens",
        True,
    ),
    Page(
        "report.html",
        "report.html",
        "Test report · TrialBox",
        "Model bake-off results on TrialGPT criterion annotations and the TrialGPT comparison.",
        "en",
        "report",
        True,
    ),
    Page(
        "docs.html",
        "docs.html",
        "Docs · TrialBox",
        "Links to the README, runbook and architecture on GitHub.",
        "en",
        "docs",
        False,
    ),
]
NAV = [
    ("home", "index.html", ("Overview", "概要", "總覽")),
    ("demo", "demo.html", ("Live demo", "デモ", "示範")),
    ("consent", "consent.html", ("Consent", "同意説明", "同意說明")),
    ("screens", "screens.html", ("Screenshots", "画面", "畫面")),
    ("report", "report.html", ("Test report", "テスト報告", "測試報告")),
    ("docs", "docs.html", ("Docs", "ドキュメント", "文件")),
]
LANG_BOOT = (
    "<script>(function(){var l='en';try{var q=new URLSearchParams(location.search).get('lang');var "
    "s=localStorage.getItem('tb-lang');"
    "l=q||s||((navigator.language||'').slice(0,2)==='ja'?'ja':'en');if(q)localStorage.setItem('tb-lang',q);}catch(e){}"
    "if(l!=='ja')l='en';document.documentElement.setAttribute('data-lang',l);})();</script>"
)


def render_page(page: Page, layout: str, fragments: dict[str, str]) -> str:
    depth = page.out.count("/")
    root = "../" * depth
    li = {"en": 0, "ja": 1, "zh-TW": 2}[page.lang]
    links = []
    for key, href, labels in NAV:
        if key == "home":
            full = "index.html" if page.lang != "en" else root + href  # a translated landing links to itself
        else:
            full = root + href + ("?lang=ja" if page.lang == "ja" else "")
        current = ' aria-current="page"' if key == page.nav else ""
        label = t(labels[0], labels[1]) if page.toggle else esc(labels[li])
        links.append(f'<a class="nav-link" href="{full}"{current}>{label}</a>')
    if page.toggle:
        lang_switch = (
            '<span class="lang" role="group" aria-label="Chart language / 表示言語">'
            '<button type="button" data-set-lang="en" aria-pressed="true">EN</button>'
            '<button type="button" data-set-lang="ja" aria-pressed="false" lang="ja">日本語</button></span>'
        )
    else:
        homes = [("en", "index.html", "EN"), ("ja", "ja/index.html", "日本語"), ("zh-TW", "zh-tw/index.html", "繁中")]
        lang_switch = (
            '<span class="lang" role="group" aria-label="Language">'
            + "".join(
                f'<a href="{root}{h}" '
                f'hreflang="{code}"{" aria-current=true" if code == page.lang and page.nav == "home" else ""}>{lbl}</a>'
                for code, h, lbl in homes
            )
            + "</span>"
        )
    alternates = ""
    if page.nav == "home":
        alternates = "".join(
            f'<link rel="alternate" hreflang="{code}" href="{root}{h}">'
            for code, h in (("en", "index.html"), ("ja", "ja/index.html"), ("zh-Hant-TW", "zh-tw/index.html"))
        )
    body_src = (SITE / "pages" / page.source).read_text(encoding="utf-8")
    common = dict(fragments, root=root, repo=REPO_BLOB, repo_tree=REPO_TREE)
    body = fill(body_src, common, page.source)
    ui = site_text()["ui"][page.lang]
    footer = {
        "en": f'TrialBox · <a href="{REPO_TREE}">source on GitHub</a> · built {fragments["build_date"]}. '
        "Not a medical device; eligibility is decided by the investigator.",
        "ja": f'TrialBox · <a href="{REPO_TREE}">GitHub のソース</a> · 生成 {fragments["build_date"]}。'
        "医療機器ではありません。適格性は治験責任医師が判断します。",
        "zh-TW": f'TrialBox · <a href="{REPO_TREE}">GitHub 原始碼</a> · 產生於 {fragments["build_date"]}。'
        "非醫療器材；收案資格由試驗主持人判定。",
    }[page.lang]
    values = {
        "html_lang": page.lang if page.lang != "zh-TW" else "zh-Hant-TW",
        "data_lang": "ja" if page.lang == "ja" else "en",
        "toggle": "lang" if page.toggle else "none",
        "title": esc(page.title),
        "description": esc(page.description),
        "root": root,
        "home": "index.html" if page.lang == "en" else ("ja/index.html" if page.lang == "ja" else "zh-tw/index.html"),
        "alternates": alternates,
        "lang_boot": LANG_BOOT if page.toggle else "",
        "skip_label": esc(ui["skip"]),
        "banner": esc(ui["banner"]),
        "nav_label": esc(ui["nav"]),
        "nav_links": "".join(links),
        "lang_switch": lang_switch,
        "body": body,
        "footer": footer,
    }
    return fill(layout, values, "layout.html")


def fill(template: str, values: dict[str, str], name: str) -> str:
    missing = sorted({m.group(1) for m in SLOT.finditer(template)} - set(values))
    if missing:
        raise BuildError(f"{name}: no value for slot(s) {', '.join(missing)}")
    return SLOT.sub(lambda m: values[m.group(1)], template)


def scan_for_secrets(out_dir: Path) -> list[str]:
    hits = []
    for path in out_dir.rglob("*"):
        if path.suffix.lower() not in (".html", ".json", ".js", ".css", ".svg", ".toml", ".txt", ".md"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"{path.relative_to(out_dir)}: {pat.pattern[:30]}… matched {m.group(0)[:12]}…")
    return hits


def load_optional(path: Path) -> Any:
    return read_json(path) if path.exists() else None


def build(out_dir: Path) -> list[str]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    shutil.copytree(SITE / "assets", out_dir / "assets")
    (out_dir / "data").mkdir()
    for path in sorted(DATA.glob("*.json")):
        shutil.copyfile(path, out_dir / "data" / path.name)
    demo_files = sorted(DATA.glob("demo_*_site_a.json"))
    demo = read_json(demo_files[0]) if demo_files else None
    fragments: dict[str, str] = {"build_date": datetime.now(UTC).strftime("%Y-%m-%d")}
    for lang in ("en", "ja", "zh-TW"):
        fragments[f"pipeline_{lang.replace('-', '_').lower()}"] = pipeline(lang)
    fragments.update(demo_fragments(demo, load_optional(DATA / "open_data_mimic.json")))
    fragments.update(
        report_fragments(load_optional(DATA / "bakeoff.json"), load_optional(DATA / "trialgpt_comparison.json"))
    )
    fragments["shots"] = shots_fragment()
    fragments.update(consent_fragments(load_optional(DATA / "consent_gzqo.json")))
    layout = (SITE / "templates" / "layout.html").read_text(encoding="utf-8")
    written = []
    for page in PAGES:
        target = out_dir / page.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_page(page, layout, fragments), encoding="utf-8")
        written.append(page.out)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages: serve as is
    (out_dir / "404.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Not found · TrialBox</title><link rel="stylesheet" href="assets/style.css">'
        '<main><h1>Not found</h1><p><a href="index.html">TrialBox home</a></p></main>',
        encoding="utf-8",
    )
    hits = scan_for_secrets(out_dir)
    if hits:
        shutil.rmtree(out_dir)
        raise BuildError("refusing to publish, possible secrets or private addresses:\n" + "\n".join(hits))
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT, help="output directory (default build/site)")
    ap.add_argument("--refresh-demo", action="store_true", help="re-run tools.cascade_e2e (stub) for the demo data")
    ap.add_argument("--no-refresh", action="store_true", help="render only from site/data (CI / Netlify)")
    ap.add_argument("--trial", default="GZQO", help="trial for the demo run (default GZQO)")
    ap.add_argument("--bakeoff-dir", type=Path, default=BAKEOFF_RESULTS)
    ap.add_argument("--open-data-report", type=Path, default=OPEN_DATA_REPORT)
    args = ap.parse_args(argv)
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        if not (DATA / "trialgpt_comparison.json").exists():
            write_json(DATA / "trialgpt_comparison.json", TRIALGPT_TEMPLATE)
        if not args.no_refresh:
            venv_py = ROOT / ".venv" / "bin" / "python"
            demo_missing = not any(DATA.glob("demo_*_site_a.json"))
            if args.refresh_demo or (demo_missing and venv_py.exists()):
                refresh_demo(venv_py if venv_py.exists() else Path(sys.executable), args.trial)
            print("open data:", "refreshed" if refresh_open_data(args.open_data_report) else "kept (no report.json)")
            print("bake-off:", "refreshed" if refresh_bakeoff(args.bakeoff_dir) else "kept (no results)")
        pages = build(args.out)
    except BuildError as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {len(pages)} pages to {args.out}: {', '.join(pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
