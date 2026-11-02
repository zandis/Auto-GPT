"""Head-to-head: local TrialGPT (your Ollama model, live ClinicalTrials.gov) vs trialgpt.app on the same public
synthetic patients.

    python -m trialgpt_local.h2h.compare local      # run the local system on every captured patient
    python -m trialgpt_local.h2h.compare crosseval  # TrialGPT-match both systems' top-10 with a judge model
    python -m trialgpt_local.h2h.compare workbook   # pooled, blinded physician workbook (both top-10s, shuffled)
    python -m trialgpt_local.h2h.compare report [--adjudicated results/h2h/pooled.xlsx]

Three lenses, from cheapest to strongest:
1. labelled coverage: the cohort labels (TREC/SIGIR qrels) judge only the trials of their frozen corpus — few live
   trials are labelled, so this is reported as coverage + graded precision on the labelled subset only;
2. cross-evaluation: TrialGPT criterion matching (``TG_JUDGE_MODEL``, default the local model) scores every trial of
   both top-10s. Biased toward the local system when the judge is the same model — the report says so;
3. physician adjudication of the pooled, blinded top-10s: graded P@10 / NDCG@10 per system, per-patient wins and a
   paired bootstrap CI. This is the result to quote.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

from trialgpt_local import annotate, core, ctgov, datasets, metrics
from trialgpt_local.config import settings
from trialgpt_local.llm import LLMClient
from trialgpt_local.pipeline import run_patient

TOP = 10


def h2h_dir() -> Path:
    d = settings().results_dir / "h2h"
    d.mkdir(parents=True, exist_ok=True)
    return d


def captured() -> dict[str, dict[str, Any]]:
    d = h2h_dir() / "trialgpt_app"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))} if d.exists() else {}


def cohort_of(pid: str) -> str:
    return "sigir" if pid.startswith("sigir") else "trec_2021" if pid.startswith("trec-2021") else "trec_2022"


def local_dir() -> Path:
    d = h2h_dir() / "local" / settings().model_tag
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_local(prefer_country: str | None) -> None:
    client = LLMClient()
    for pid, cap in captured().items():
        out = local_dir() / f"{pid}.json"
        if out.exists():
            continue
        note = datasets.load(cohort_of(pid)).queries[pid]
        run = run_patient(
            note, client=client, source="live", top_k=TOP, prefer_country=prefer_country or cap.get("country")
        )
        out.write_text(json.dumps(run.to_json(), indent=1, ensure_ascii=False), encoding="utf-8")
        print(pid, [m.nct_id for m in run.ranked], run.seconds, flush=True)


def lists() -> dict[str, dict[str, list[str]]]:
    """patient -> {"local": top-10, "trialgpt.app": top-10}."""
    out = {}
    for pid, cap in captured().items():
        lp = local_dir() / f"{pid}.json"
        if not lp.exists():
            continue
        loc = json.loads(lp.read_text(encoding="utf-8"))
        out[pid] = {"local": [m["nct_id"] for m in loc["ranked"]][:TOP], "trialgpt.app": cap["ranked"][:TOP]}
    return out


def judge_client() -> tuple[LLMClient, str]:
    cfg = settings()
    model = os.environ.get("TG_JUDGE_MODEL", cfg.llm_model)
    return LLMClient(replace(cfg, llm_model=model)), model


def crosseval() -> None:
    client, model = judge_client()
    tag = "".join(c if c.isalnum() or c in "._-" else "-" for c in model)
    d = h2h_dir() / "crosseval" / tag
    d.mkdir(parents=True, exist_ok=True)
    for pid, sys_lists in lists().items():
        out = d / f"{pid}.json"
        done = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        ids = list(dict.fromkeys(sys_lists["local"] + sys_lists["trialgpt.app"]))
        todo = [n for n in ids if n not in done]
        if not todo:
            continue
        trials = ctgov.get(todo)
        numbered, _ = core.number_patient(datasets.load(cohort_of(pid)).queries[pid])
        for nct in todo:
            if nct not in trials:
                done[nct] = {"error": "not found in ClinicalTrials.gov"}
                continue
            m = core.aggregate(client, core.match_trial(client, trials[nct], numbered), trials[nct], numbered)
            labels = [c.label for c in m.criteria]
            done[nct] = {
                "score": m.score,
                "matching": m.matching_score,
                "aggregation": m.aggregation,
                "not_included": labels.count("not included"),
                "excluded": labels.count("excluded"),
                "included": labels.count("included"),
            }
            out.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        print(pid, len(done), flush=True)


def workbook() -> Path:
    items = []
    for pid, sys_lists in lists().items():
        note = datasets.load(cohort_of(pid)).queries[pid]
        ids = list(dict.fromkeys(sys_lists["local"] + sys_lists["trialgpt.app"]))
        trials = ctgov.get(ids)
        for nct in ids:
            t = trials.get(nct)
            if t is None:
                continue
            text = (
                f"Conditions: {', '.join(t['diseases_list'])}\nSummary: {t['brief_summary'][:1500]}\n\n"
                f"Inclusion:\n{t['inclusion_criteria'][:3000]}\n\nExclusion:\n{t['exclusion_criteria'][:3000]}"
            )
            items.append(
                {
                    "item_id": f"{pid}|{nct}",
                    "patient_id": pid,
                    "patient": note,
                    "nct_id": nct,
                    "trial_title": t["brief_title"],
                    "trial_text": text,
                    "systems": [s for s, ids_ in sys_lists.items() if nct in ids_],
                }
            )
    path = h2h_dir() / "pooled.xlsx"
    return annotate.write_workbook(items, path, title="TrialGPT head-to-head: pooled, blinded trial-level adjudication")


def _bootstrap(diffs: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def report(adjudicated: Path | None) -> str:
    L = lists()
    caps = captured()
    lines = [
        "# Head-to-head: local TrialGPT vs trialgpt.app",
        "",
        f"Patients: {len(L)} public synthetic cohort patients (captured: {len(caps)}). Local model: "
        f"`{settings().llm_model}`. Both systems search the live registry; top {TOP} compared.",
        "",
    ]
    if not L:
        return "\n".join([*lines, "No patient has results from both systems yet."]) + "\n"
    # 0. overlap and lengths
    jac = [
        len(set(v["local"]) & set(v["trialgpt.app"])) / max(1, len(set(v["local"]) | set(v["trialgpt.app"])))
        for v in L.values()
    ]
    lines += [
        f"- top-{TOP} overlap (Jaccard): {metrics.mean(jac):.3f}",
        f"- trialgpt.app mean search time: {metrics.mean([c.get('search_seconds') for c in caps.values()]):.1f} s; "
        f"selection policy: {sorted({str(c.get('select_policy')) for c in caps.values()})}; country: "
        f"{sorted({str(c.get('country')) for c in caps.values()})}",
        "",
    ]
    # 1. labelled coverage
    lines += [
        "## 1. Cohort labels (frozen corpus, mostly not covering live trials)",
        "",
        "| system | labelled share of top-10 | graded precision on labelled |",
        "|---|---|---|",
    ]
    for s in ("local", "trialgpt.app"):
        cov, prec = [], []
        for pid, v in L.items():
            rel = datasets.load(cohort_of(pid)).qrels.get(pid, {})
            lab = [rel[n] for n in v[s] if n in rel]
            cov.append(len(lab) / max(1, len(v[s])))
            if lab:
                prec.append(sum(lab) / (2 * len(lab)))
        lines.append(f"| {s} | {metrics.mean(cov):.3f} | {_fmt(metrics.mean(prec))} (n={len(prec)} patients) |")
    # 2. cross-evaluation
    for jd in sorted((h2h_dir() / "crosseval").glob("*")) if (h2h_dir() / "crosseval").exists() else []:
        same = jd.name == settings().model_tag
        lines += [
            "",
            f"## 2. Cross-evaluation by TrialGPT matching (judge `{jd.name}`)",
            "",
            "Same model as the local system: biased toward it."
            if same
            else "Judge differs from the local system's model.",
            "",
            "| system | mean TrialGPT score top-10 | trials with no failed criterion | mean relevance R |",
            "|---|---|---|---|",
        ]
        for s in ("local", "trialgpt.app"):
            sc: list[float] = []
            clean: list[float] = []
            mean_r: list[float] = []
            for pid, v in L.items():
                p = jd / f"{pid}.json"
                if not p.exists():
                    continue
                ce = json.loads(p.read_text(encoding="utf-8"))
                for n in v[s]:
                    r = ce.get(n) or {}
                    if "score" not in r:
                        continue
                    sc.append(r["score"])
                    clean.append(1.0 if r["not_included"] == 0 and r["excluded"] == 0 else 0.0)
                    a = r.get("aggregation") or {}
                    if isinstance(a.get("relevance_score_R"), (int, float)):
                        mean_r.append(float(a["relevance_score_R"]))
            lines.append(
                f"| {s} | {_fmt(metrics.mean(sc))} | {_fmt(metrics.mean(clean))} | {_fmt(metrics.mean(mean_r), 1)} |"
            )
    # 3. physician adjudication
    if adjudicated and adjudicated.exists():
        judged = annotate.read_workbook(adjudicated)
        grade = {(j["patient_id"], j["nct_id"]): j["answer"] for j in judged if isinstance(j["answer"], int)}
        lines += [
            "",
            "## 3. Physician adjudication (pooled, blinded) — the result to quote",
            "",
            f"{len(grade)} of {len(judged)} rows judged.",
            "",
            "| system | graded P@10 | NDCG@10 (pool-ideal) | eligible (2) per patient |",
            "|---|---|---|---|",
        ]
        per: dict[str, list[float]] = {"local": [], "trialgpt.app": []}
        for s in per:
            nd, el = [], []
            for pid, v in L.items():
                rel = {n: g for (p, n), g in grade.items() if p == pid}
                if not rel:
                    continue
                per[s].append(metrics.precision_at_k(v[s], rel, TOP))
                nd.append(metrics.ndcg_at_k(v[s], rel, TOP))
                el.append(sum(1 for n in v[s] if rel.get(n) == 2))
            lines.append(
                f"| {s} | {_fmt(metrics.mean(per[s]))} | {_fmt(metrics.mean(nd))} | {_fmt(metrics.mean(el), 2)} |"
            )
        diffs = [a - b for a, b in zip(per["local"], per["trialgpt.app"], strict=True)]
        if diffs:
            lo, hi = _bootstrap(diffs)
            wins = sum(d > 0 for d in diffs)
            ties = sum(d == 0 for d in diffs)
            lines += [
                "",
                f"Per-patient graded P@10, local − trialgpt.app: mean {sum(diffs) / len(diffs):+.3f} "
                f"(95 % bootstrap CI {lo:+.3f} to {hi:+.3f}); local better for {wins}, tie {ties}, "
                f"trialgpt.app better for {len(diffs) - wins - ties} of {len(diffs)} patients.",
            ]
    else:
        lines += [
            "",
            "## 3. Physician adjudication",
            "",
            (
                "Not yet: the blinded workbook `results/h2h/pooled.xlsx` is ready for the physicians"
                if (settings().results_dir / "h2h" / "pooled.xlsx").exists()
                else "Not yet: `python -m trialgpt_local.h2h.compare workbook`, have physicians fill "
                "`results/h2h/pooled.xlsx`"
            )
            + "; then `report --adjudicated results/h2h/pooled.xlsx`.",
        ]
    text = "\n".join(lines) + "\n"
    (h2h_dir() / "report.md").write_text(text, encoding="utf-8")
    return text


def _fmt(v: float | None, nd: int = 3) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trialgpt_local.h2h.compare")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lo = sub.add_parser("local")
    lo.add_argument("--prefer-country", help="default: the country trialgpt.app used for that patient")
    sub.add_parser("crosseval")
    sub.add_parser("workbook")
    r = sub.add_parser("report")
    r.add_argument("--adjudicated", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "local":
        run_local(a.prefer_country)
    elif a.cmd == "crosseval":
        crosseval()
    elif a.cmd == "workbook":
        print(workbook())
    else:
        print(report(a.adjudicated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
