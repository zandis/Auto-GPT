"""Hospital-scale simulation of the TrialBox lifecycle: measured pipeline runs plus a projection with error bounds.

Two parts, kept apart so nobody mistakes a projection for a measurement.

``scale`` (measured): generate synthetic hospitals of growing size (``tools.synth``, every patient fictional, planted
truth), run the real dataplat -> cascade S0..S5 -> DL-1 pack -> recall certificate path (:mod:`tools.cascade_e2e`,
deterministic stub model, no network) for one or more rulesets, and record wall time, the stage funnel, model calls
per patient and the invariant checks. This shows where the work goes and whether it grows linearly.

``project`` (modelled): combine the measured funnel with the per-criterion error rates measured on public data
(``tools.trec_ct_eval`` on TREC CT 2021/22, ``tools.medtxt_eval`` on real Japanese reports) to estimate, for a
hospital of N patients screening T trials a year: eligible patients wrongly dropped by the model, review queue,
coordinator hours, model calls and GPU hours. Uncertainty is carried by resampling TREC patients (the cluster
bootstrap of ``trec_ct_eval``); the planning constants (minutes per review, tokens per second, eligible rate) are
named parameters, printed with the result.

    python -m tools.hospital_sim scale --sizes 2000 10000 50000 --trials GZQO
    python -m tools.hospital_sim project --patients 50000 --trials-per-year 12
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "hospital_sim" / "results"
SEED = 20261105


# ---------------------------------------------------------------- measured: real pipeline at growing size
def scale(sizes: list[int], trials: list[str], work: Path | None = None) -> list[dict[str, Any]]:
    from tools.cascade_e2e import run_end_to_end
    from tools.make_fixtures import write_site
    from tools.synth.generator import generate

    rows = []
    base = work or Path(tempfile.mkdtemp(prefix="tb-hospital-sim-"))
    for n in sizes:
        site = base / f"n{n}" / "site-a"
        t0 = time.monotonic()
        write_site(generate(42, "DEMO-A", date(2026, 10, 5), n, "1"), site)
        gen_s = time.monotonic() - t0
        for trial in trials:
            t1 = time.monotonic()
            r = run_end_to_end(site, trial, base / f"n{n}" / f"out-{trial}", repro=False)
            sec = time.monotonic() - t1
            sc = r.stage_counts
            s3 = sc.get("S3", {})
            row = {
                "patients": n,
                "trial": trial,
                "passed": r.passed,
                "failed_checks": [k for k, v in r.checks.items() if not v],
                "generate_s": round(gen_s, 1),
                "pipeline_s": round(sec, 1),
                "ms_per_patient": round(1000 * sec / n, 2),
                "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
                "funnel": {k: {"in": v["patients_in"], "out": v["patients_out"]} for k, v in sc.items()},
                "s3_detail": s3.get("detail", {}),
                "model_calls": r.gateway.get("calls", 0),
                "model_calls_per_1k_patients": round(1000 * r.gateway.get("calls", 0) / n, 1),
                "tiers": r.tiers,
                "final_list": r.final_list_size,
                "certificate": r.certificate_status,
                "certificate_statement": r.certificate_statement,
            }
            rows.append(row)
            _save_scale(row)
            print(
                json.dumps({k: row[k] for k in ("patients", "trial", "passed", "pipeline_s", "model_calls")}),
                flush=True,
            )
    return rows


def _save_scale(row: dict[str, Any]) -> None:
    """Merge one measured row into results/scale.json (one process per size keeps peak memory per size honest)."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / "scale.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    rows = [r for r in rows if (r["patients"], r["trial"]) != (row["patients"], row["trial"])] + [row]
    path.write_text(json.dumps(sorted(rows, key=lambda r: (r["trial"], r["patients"])), indent=1))


# ---------------------------------------------------------------- modelled: projection with error bounds
def _trec_replicates(models: list[str], reps: int) -> dict[str, Any]:
    """Per-criterion false-block rate on eligible pairs and pair-level catch rate on excluded pairs, resampled by
    TREC patient. Returns the point values and ``reps`` bootstrap replicates."""
    from tools import mlbench
    from tools.trec_ct_eval import dataset, load

    pairs, *_ = dataset()
    ans: dict[str, dict[str, dict[str, Any]]] = {}
    for m in models:
        got = load(m)
        if got is None:
            raise SystemExit(f"{m}: run still in progress")
        ans[m] = got
    per_patient: dict[str, list[tuple[int, int, int, int, int]]] = {}
    tokens = calls = 0
    for p in pairs:
        ids = [f"{p['patient']}|{p['trial']}|{i}" for i in range(len(p["criteria"]))]
        blk = [all((ans[m].get(a, {}).get("label") or "") in mlbench.BLOCKS for m in models) for a in ids]
        for m in models:
            for a in ids:
                r = ans[m].get(a, {})
                tokens += int(r.get("prompt_tokens") or 0) + int(r.get("completion_tokens") or 0)
                calls += 1
        elig = p["label"] == "2"
        # (eligible criteria, eligible criterion blocks, eligible pair lost, excluded pairs, excluded caught)
        per_patient.setdefault(p["patient"], []).append(
            (
                len(ids) if elig else 0,
                sum(blk) if elig else 0,
                int(elig and any(blk)),
                int(not elig),
                int(not elig and any(blk)),
            )
        )

    def stats(ids: list[str]) -> dict[str, float]:
        tot = [0, 0, 0, 0, 0]
        ep = 0
        for pid in ids:
            for row in per_patient[pid]:
                for i, v in enumerate(row):
                    tot[i] += v
                ep += int(row[0] > 0)
        return {
            "q": tot[1] / tot[0] if tot[0] else 0.0,  # per-criterion false block on eligible pairs
            "pair_lost": tot[2] / ep if ep else 0.0,
            "caught": tot[4] / tot[3] if tot[3] else 0.0,
        }

    pids = sorted(per_patient)
    rng = random.Random(SEED)
    return {
        "point": stats(pids),
        "reps": [stats([rng.choice(pids) for _ in pids]) for _ in range(reps)],
        "tokens_per_call": tokens / calls if calls else 0.0,
        "criteria_per_trial": sum(len(p["criteria"]) for p in pairs) / len(pairs),
    }


def _ja_factor(models: list[str]) -> dict[str, Any] | None:
    """Ratio of Japanese to English wrong blocks on MedTxt (negated + not-mentioned findings), point and 95 % range
    from the cluster bootstrap of each language."""
    p = ROOT / "eval" / "medtxt" / "results" / "scores.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text(encoding="utf-8"))
    key = "+".join(models)
    group = "both_must_block" if len(models) > 1 else "single"
    try:
        ja, en = s[group][f"{key}|ja"], s[group][f"{key}|en"]
    except KeyError:
        return None

    def wrong(v: dict[str, Any]) -> tuple[float, int]:
        b = v["negative_strict"]["blocked"] + v["absent"]["blocked"]
        n = v["negative_strict"]["n"] + v["absent"]["n"]
        return b / n if n else 0.0, n

    (rj, _), (re_, _) = wrong(ja), wrong(en)
    return {
        "ja_wrong_block": rj,
        "en_wrong_block": re_,
        "ratio": (rj / re_) if re_ else None,
        "ja_recall": ja["positive"]["rate"],
        "en_recall": en["positive"]["rate"],
    }


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(q * len(xs))))]


def project(
    patients: int,
    trials_per_year: int,
    models: list[str],
    llm_share: float,
    eligible_per_1k: float,
    review_minutes: float,
    gpu_tokens_per_s: float,
    reps: int,
    audit: tuple[int, int] = (10, 30),
) -> dict[str, Any]:
    scale_rows = json.loads((RESULTS / "scale.json").read_text()) if (RESULTS / "scale.json").exists() else []
    big = max(scale_rows, key=lambda r: r["patients"]) if scale_rows else None
    s1_pass = (big["funnel"]["S1"]["out"] / big["funnel"]["S0"]["in"]) if big else 0.03
    s3_share = (big["funnel"]["S3"]["in"] / max(1, big["funnel"]["S1"]["out"])) if big else 1.0
    calls_per_s3 = (big["model_calls"] / max(1, big["funnel"]["S3"]["in"])) if big else 2.0
    review_share = (big["funnel"]["S5"]["in"] / max(1, big["funnel"]["S0"]["in"])) if big else s1_pass

    tr = _trec_replicates(models, reps)
    k_all = float(tr["criteria_per_trial"])
    k_llm = llm_share * k_all
    eligible = patients * eligible_per_1k / 1000 * trials_per_year

    def lost(q: float, k: float) -> float:
        return float(1 - (1 - q) ** k)

    ja = _ja_factor(models)
    ratio = ja["ratio"] if ja and ja["ratio"] else 1.0
    # TREC "eligible" labels are noisy: in the AUDIT.md hand check 10 of 30 dropped pairs were model errors. The
    # adjusted figure scales each replicate by a Beta(10+1, 20+1) draw of that share.
    rng = random.Random(SEED + 1)
    share_draws = [rng.betavariate(audit[0] + 1, audit[1] - audit[0] + 1) for _ in tr["reps"]]
    out_rows = []
    for lang, factor in (("en", 1.0), ("ja", max(1.0, ratio))):  # never let Japanese look better than English
        for kind in ("raw", "audit_adjusted"):
            point_f = audit[0] / audit[1] if kind == "audit_adjusted" else 1.0
            shares = [
                lost(min(1.0, r["q"] * factor), k_llm) * (f if kind == "audit_adjusted" else 1.0)
                for r, f in zip(tr["reps"], share_draws, strict=True)
            ]
            point = lost(min(1.0, tr["point"]["q"] * factor), k_llm) * point_f
            out_rows.append(
                {
                    "lang": lang,
                    "kind": kind,
                    "eligible_patient_trial_pairs_per_year": round(eligible),
                    "share_dropped": {
                        "point": round(point, 4),
                        "p2.5": round(_pct(shares, 0.025), 4),
                        "p97.5": round(_pct(shares, 0.975), 4),
                    },
                    "wrongly_dropped_per_year": {
                        "point": round(eligible * point, 1),
                        "p2.5": round(eligible * _pct(shares, 0.025), 1),
                        "p97.5": round(eligible * _pct(shares, 0.975), 1),
                    },
                }
            )
    screened = patients * trials_per_year
    s1_out = screened * s1_pass
    llm_patients = s1_out * s3_share
    calls = llm_patients * calls_per_s3  # the measured call count already includes the S4 second opinion
    review = screened * review_share  # the S5 queue: strong, watchlist, uncertain and data-gap candidates
    gpu_hours = calls * tr["tokens_per_call"] / gpu_tokens_per_s / 3600
    res = {
        "parameters": {
            "patients": patients,
            "trials_per_year": trials_per_year,
            "models": models,
            "llm_share_of_criteria": llm_share,
            "eligible_per_1k_patients_per_trial": eligible_per_1k,
            "review_minutes_per_candidate": review_minutes,
            "gpu_tokens_per_s": gpu_tokens_per_s,
            "bootstrap_reps": reps,
            "audit_model_errors_of_sampled": list(audit),
        },
        "measured_inputs": {
            "s1_pass_rate (synthetic run)": round(s1_pass, 4),
            "s3_share_of_s1_survivors": round(s3_share, 3),
            "s5_queue_per_1k_patients": round(1000 * review_share, 2),
            "model_calls_per_s3_patient": round(calls_per_s3, 2),
            "trec_per_criterion_false_block": {
                "point": round(tr["point"]["q"], 5),
                "p2.5": round(_pct([r["q"] for r in tr["reps"]], 0.025), 5),
                "p97.5": round(_pct([r["q"] for r in tr["reps"]], 0.975), 5),
            },
            "trec_excluded_pairs_caught": {
                "point": round(tr["point"]["caught"], 3),
                "p2.5": round(_pct([r["caught"] for r in tr["reps"]], 0.025), 3),
                "p97.5": round(_pct([r["caught"] for r in tr["reps"]], 0.975), 3),
            },
            "criteria_per_trial (TREC sample)": round(k_all, 1),
            "tokens_per_call (TREC)": round(tr["tokens_per_call"]),
            "japanese": ja,
        },
        "per_year": {
            "patient_trial_screens": screened,
            "pass_structured_filters": round(s1_out),
            "reach_llm": round(llm_patients),
            "model_calls": round(calls),
            "gpu_hours": round(gpu_hours, 1),
            "review_queue": round(review),
            "coordinator_hours": round(review * review_minutes / 60),
            "wrongly_dropped": out_rows,
        },
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"project_{patients}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hospital_sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scale")
    s.add_argument("--sizes", nargs="+", type=int, default=[2000, 10000])
    s.add_argument("--trials", nargs="+", default=["GZQO"])
    s.add_argument("--work", type=Path)
    p = sub.add_parser("project")
    p.add_argument("--patients", type=int, default=50000)
    p.add_argument("--trials-per-year", type=int, default=12)
    p.add_argument("--models", nargs="+", default=["google/gemma-4-26b-a4b-it@fp4", "qwen/qwen3.5-9b"])
    p.add_argument("--llm-share", type=float, default=0.42, help="share of criteria the LLM reads (filter-first)")
    p.add_argument("--eligible-per-1k", type=float, default=2.0, help="truly eligible patients per 1,000 per trial")
    p.add_argument("--review-minutes", type=float, default=10.0)
    p.add_argument("--gpu-tokens-per-s", type=float, default=2500.0, help="aggregate prefill+decode on the box")
    p.add_argument("--reps", type=int, default=2000)
    a = ap.parse_args(argv)
    if a.cmd == "scale":
        scale(a.sizes, a.trials, a.work)
    else:
        r = project(
            a.patients,
            a.trials_per_year,
            a.models,
            a.llm_share,
            a.eligible_per_1k,
            a.review_minutes,
            a.gpu_tokens_per_s,
            a.reps,
        )
        print(json.dumps(r, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
