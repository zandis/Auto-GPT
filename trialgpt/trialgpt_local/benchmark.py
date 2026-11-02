"""Benchmark the local LLM on the NCBI cohorts and compare with the paper's GPT-4 numbers.

    python -m trialgpt_local.benchmark rank      --cohort sigir [--patients 5] [--trials 20]
    python -m trialgpt_local.benchmark retrieval --cohort trec_2021 [--keywords local|gpt-4-turbo|raw] [--patients 10]
    python -m trialgpt_local.benchmark report    [--model qwen2.5:7b]

``rank`` follows the paper's ranking evaluation: per patient, the labelled trials among the retrieved candidates
(``retrieved_trials.json``) are matched criterion by criterion, aggregated and ranked; NDCG@10, P@10 and AUROC
(eligible vs excluded) are computed per patient and averaged. Outputs use NCBI's own file layout
(``matching_results_*.json``, ``aggregation_results_*.json``) so NCBI's ``rank_results.py`` reads them too.
``--patients`` / ``--trials`` take a seeded slice for quick runs; the report states the slice so it is never mistaken
for a full run. Every LLM call is cached: an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

from trialgpt_local import core, datasets, metrics
from trialgpt_local.config import ROOT, settings
from trialgpt_local.llm import LLMClient

PAPER = json.loads((ROOT / "benchmarks" / "paper_reference.json").read_text(encoding="utf-8"))
VARIANTS = ("combined", "llm_eligibility", "llm_relevance", "linear_included")


def out_dir(model_tag: str, cohort: str) -> Path:
    d = settings().results_dir / model_tag / cohort
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else {}


def _dump(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def select(
    cohort: datasets.Cohort, patients: int | None, trials: int | None, seed: int = 13
) -> dict[str, list[dict[str, Any]]]:
    """Patients and their labelled trials; a slice keeps every label represented (round robin over 2, 1, 0)."""
    rng = random.Random(seed)
    pids = [e["patient_id"] for e in cohort.retrieved]
    if patients:
        pids = sorted(rng.sample(pids, min(patients, len(pids))))
    out = {}
    for pid in pids:
        entry = next(e for e in cohort.retrieved if e["patient_id"] == pid)
        if not trials:
            out[pid] = [t for lab in ("2", "1", "0") for t in entry.get(lab, [])]
            continue
        pools = {lab: rng.sample(entry.get(lab, []), len(entry.get(lab, []))) for lab in ("2", "1", "0")}
        picked: list[dict[str, Any]] = []
        while len(picked) < trials and any(pools.values()):
            for lab in ("2", "1", "0"):
                if pools[lab] and len(picked) < trials:
                    picked.append(pools[lab].pop())
        out[pid] = picked
    return out


def run_rank(cohort_name: str, patients: int | None, trials: int | None, strict: bool = False) -> Path:
    cfg = settings()
    cohort = datasets.load(cohort_name)
    client = LLMClient(cfg)
    d = out_dir(cfg.model_tag, cohort_name)
    mpath, apath = (
        d / f"matching_results_{cohort_name}_{cfg.model_tag}.json",
        d / f"aggregation_results_{cohort_name}_{cfg.model_tag}.json",
    )
    matching, agg, timing = _load(mpath), _load(apath), _load(d / "timing.json")
    chosen = select(cohort, patients, trials)
    labels = {pid: cohort.labels_for(pid) for pid in chosen}
    total = sum(len(v) for v in chosen.values())
    done = 0
    for pid, ts in chosen.items():
        numbered, _ = core.number_patient(cohort.queries[pid])
        matching.setdefault(pid, {"0": {}, "1": {}, "2": {}})
        agg.setdefault(pid, {})
        for trial in ts:
            nct, lab = trial["NCTID"], str(labels[pid][trial["NCTID"]])
            done += 1
            if nct in matching[pid][lab] and nct in agg[pid]:
                continue
            t0 = time.perf_counter()
            try:
                m = core.match_trial(client, trial, numbered, strict_labels=strict)
                m = core.aggregate(client, m, trial, numbered)
            except Exception as exc:  # one failed pair never stops a long run; it is reported
                timing.setdefault("errors", []).append(f"{pid}/{nct}: {exc}")
                _dump(d / "timing.json", timing)
                continue
            matching[pid][lab][nct] = m.raw
            agg[pid][nct] = m.aggregation if m.aggregation is not None else "aggregation error"
            timing.setdefault("pairs", {})[f"{pid}/{nct}"] = {
                "seconds": round(time.perf_counter() - t0, 2),
                "parse_errors": sum(r.label == "parse error" for r in m.criteria),
                "criteria": len(m.criteria),
                "json_errors": len(m.errors),
            }
            _dump(mpath, matching)
            _dump(apath, agg)
            _dump(d / "timing.json", timing)
            print(
                f"[{done}/{total}] {pid} {nct} label={lab} score={m.score:.3f} "
                f"({timing['pairs'][f'{pid}/{nct}']['seconds']}s)",
                flush=True,
            )
    meta = {
        "cohort": cohort_name,
        "model": cfg.llm_model,
        "backend": cfg.llm_backend,
        "num_ctx": cfg.llm_num_ctx,
        "patients": len(chosen),
        "pairs": total,
        "slice": {"patients": patients, "trials": trials},
        "strict_labels": strict,
    }
    _dump(d / "run.json", meta)
    return d


# ------------------------------------------------------------------------------------------------ scoring
def variant_scores(matching: dict[str, Any], assessment: Any) -> dict[str, float]:
    """The paper's Table 2 rows: Feature combination (= NCBI rank_results), LLM eligibility / relevance, % included."""
    m = core.matching_score(matching)
    a = assessment if isinstance(assessment, dict) else {}
    try:
        r, e = float(a.get("relevance_score_R", 0)), float(a.get("eligibility_score_E", 0))
    except (TypeError, ValueError):
        r = e = 0.0
    inc = matching.get("inclusion") or {}
    labs = [v[2] for v in inc.values() if isinstance(v, list) and len(v) == 3]
    denom = sum(1 for x in labs if x != "not applicable")
    pct_inc = (sum(1 for x in labs if x == "included") / denom) if denom else 0.0
    return {
        "combined": m + core.aggregation_score(a) if a else m,
        "llm_eligibility": e / 100,
        "llm_relevance": r / 100,
        "linear_included": pct_inc,
    }


def evaluate(cohort_name: str, model_tag: str) -> dict[str, Any]:
    d = settings().results_dir / model_tag / cohort_name
    matching = _load(d / f"matching_results_{cohort_name}_{model_tag}.json")
    agg = _load(d / f"aggregation_results_{cohort_name}_{model_tag}.json")
    per_variant: dict[str, dict[str, list[float | None]]] = {
        v: {"ndcg@10": [], "p@10": [], "auroc": []} for v in VARIANTS
    }
    n_pairs = 0
    for pid, by_label in matching.items():
        rel = {nct: int(lab) for lab, trials in by_label.items() for nct in trials}
        if not rel:
            continue
        n_pairs += len(rel)
        scores: dict[str, dict[str, float]] = {v: {} for v in VARIANTS}
        for trials in by_label.values():
            for nct, res in trials.items():
                for v, s in variant_scores(res, agg.get(pid, {}).get(nct)).items():
                    scores[v][nct] = s
        for v in VARIANTS:
            ranked = sorted(scores[v], key=lambda t: -scores[v][t])
            per_variant[v]["ndcg@10"].append(metrics.ndcg_at_k(ranked, rel))
            per_variant[v]["p@10"].append(metrics.precision_at_k(ranked, rel))
            per_variant[v]["auroc"].append(metrics.auroc(scores[v], rel))
    timing = _load(d / "timing.json")
    pairs = list((timing.get("pairs") or {}).values())
    crit = sum(p["criteria"] for p in pairs)
    return {
        "cohort": cohort_name,
        "patients": len(matching),
        "pairs": n_pairs,
        "run": _load(d / "run.json"),
        "metrics": {v: {k: metrics.mean(vals) for k, vals in m.items()} for v, m in per_variant.items()},
        "diagnostics": {
            "criterion_parse_error_rate": (sum(p["parse_errors"] for p in pairs) / crit) if crit else None,
            "json_error_pairs": sum(1 for p in pairs if p["json_errors"]),
            "mean_seconds_per_pair": metrics.mean([p["seconds"] for p in pairs]),
            "failed_pairs": len(timing.get("errors") or []),
        },
    }


def run_retrieval(cohort_name: str, keywords: str, patients: int | None) -> dict[str, Any]:
    from trialgpt_local.retrieval import HybridIndex

    cfg = settings()
    cohort = datasets.load(cohort_name)
    client = LLMClient(cfg) if keywords == "local" else None
    index = HybridIndex.build(datasets.corpus(cohort_name), name=cohort_name)
    pids = sorted(cohort.qrels)
    if patients:
        pids = sorted(random.Random(13).sample(pids, min(patients, len(pids))))
    rec: dict[int, list[float | None]] = {100: [], 500: [], 1000: []}
    kw_out = {}
    for pid in pids:
        if keywords == "local":
            assert client is not None
            kw = core.generate_keywords(client, cohort.queries[pid])
            kw_out[pid] = kw
            conds = kw["conditions"]
        else:
            q = cohort.id2queries[pid][keywords]
            conds = [q] if isinstance(q, str) else q["conditions"]
        ranked = [t for t, _ in index.search(conds, n=2000)]
        for n in rec:
            rec[n].append(metrics.recall_at_n(ranked, cohort.qrels[pid], n))
    tag = cfg.model_tag if keywords == "local" else keywords
    res = {
        "cohort": cohort_name,
        "keywords": tag,
        "patients": len(pids),
        "recall": {str(n): metrics.mean(v) for n, v in rec.items()},
    }
    d = out_dir(cfg.model_tag if keywords == "local" else "_reference", cohort_name)
    _dump(d / f"retrieval_{tag}.json", {**res, "keywords_generated": kw_out})
    return res


def report(model_tag: str) -> str:
    root = settings().results_dir / model_tag
    lines = [f"# TrialGPT on {model_tag} vs the paper (GPT-4)", ""]
    evals = [evaluate(c, model_tag) for c in datasets.COHORTS if (root / c / "run.json").exists()]
    if evals:
        lines += [
            "## Ranking (labelled trials among the retrieved; paper Table 2)",
            "",
            "| cohort | patients | pairs | slice | NDCG@10 | P@10 | AUROC | parse errors | s/pair |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for e in evals:
            m, dg, sl = e["metrics"]["combined"], e["diagnostics"], e["run"].get("slice") or {}
            sl_txt = (
                f"{sl.get('patients') or 'all'} pts x {sl.get('trials') or 'all'} trials"
                if any(sl.values())
                else "full"
            )
            lines.append(
                f"| {e['cohort']} | {e['patients']} | {e['pairs']} | {sl_txt} | {_f(m['ndcg@10'])} | {_f(m['p@10'])} | "
                f"{_f(m['auroc'])} | {_f(dg['criterion_parse_error_rate'], pct=True)} | "
                f"{_f(dg['mean_seconds_per_pair'], 1)} |"
            )
        avg = {k: metrics.mean([e["metrics"]["combined"][k] for e in evals]) for k in ("ndcg@10", "p@10", "auroc")}
        ref = PAPER["ranking_avg_3_cohorts"]["TrialGPT-Ranking (GPT-4) Feature combination"]
        lines += [
            "",
            f"Average over {len(evals)} cohort(s): NDCG@10 {_f(avg['ndcg@10'])}, P@10 {_f(avg['p@10'])}, "
            f"AUROC {_f(avg['auroc'])}. Paper, GPT-4, average over 3 cohorts: NDCG@10 {ref['ndcg@10']}, "
            f"P@10 {ref['p@10']}, AUROC {ref['auroc']}.",
            "",
            "Variants (paper rows):",
            "",
        ]
        for v in VARIANTS:
            vals = {k: metrics.mean([e["metrics"][v][k] for e in evals]) for k in ("ndcg@10", "p@10", "auroc")}
            lines.append(f"- {v}: NDCG@10 {_f(vals['ndcg@10'])}, P@10 {_f(vals['p@10'])}, AUROC {_f(vals['auroc'])}")
        if any(e["run"].get("slice", {}).get("patients") or e["run"].get("slice", {}).get("trials") for e in evals):
            lines += [
                "",
                "**Slice run**: a seeded subset of patients/trials — indicative only, not comparable to the "
                "paper's full run.",
            ]
    for c in datasets.COHORTS:
        for p in sorted((root / c).glob("retrieval_*.json")) if (root / c).exists() else []:
            r = _load(p)
            ref = PAPER["retrieval_recall_hybrid"].get(c, {}).get("gpt-4-turbo", {})
            lines.append(
                f"- retrieval {c} keywords={r['keywords']} ({r['patients']} patients): recall "
                + ", ".join(f"@{n} {_f(v)}" for n, v in r["recall"].items())
                + f"; paper GPT-4 keywords: {ref}"
            )
    lines += [
        "",
        "AUROC: eligible (2) vs excluded (1); the paper does not name its classes. Reference: " + PAPER["source"],
    ]
    text = "\n".join(lines) + "\n"
    (root).mkdir(parents=True, exist_ok=True)
    (root / "report.md").write_text(text, encoding="utf-8")
    _dump(root / "report.json", evals)
    return text


def _f(v: float | None, nd: int = 4, pct: bool = False) -> str:
    if v is None:
        return "—"
    return f"{100 * v:.1f} %" if pct else f"{v:.{nd}f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m trialgpt_local.benchmark")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rank")
    r.add_argument("--cohort", choices=datasets.COHORTS, required=True)
    r.add_argument("--patients", type=int)
    r.add_argument("--trials", type=int, help="labelled trials per patient (seeded, all labels represented)")
    r.add_argument("--strict-labels", action="store_true", help="NCBI's exact label matching")
    q = sub.add_parser("retrieval")
    q.add_argument("--cohort", choices=datasets.COHORTS, required=True)
    q.add_argument(
        "--keywords", default="local", help="local (generate with the local LLM) | gpt-4-turbo | gpt-35-turbo | raw"
    )
    q.add_argument("--patients", type=int)
    p = sub.add_parser("report")
    p.add_argument("--model", help="model tag (default: TG_LLM_MODEL)")
    a = ap.parse_args(argv)
    if a.cmd == "rank":
        run_rank(a.cohort, a.patients, a.trials, a.strict_labels)
        print(report(settings().model_tag))
    elif a.cmd == "retrieval":
        print(json.dumps(run_retrieval(a.cohort, a.keywords, a.patients), indent=1))
    else:
        tag = "".join(c if c.isalnum() or c in "._-" else "-" for c in a.model) if a.model else settings().model_tag
        print(report(tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
