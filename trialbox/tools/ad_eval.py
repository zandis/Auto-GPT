"""Alzheimer's disease slice of the TrialBox validation.

Three parts, all on public data:

* ``trec``: every NIST-judged pair (eligible / excluded) between a TREC CT 2021/22 patient and an AD, dementia or MCI
  trial (771 such trials in the corpora). Most pairs belong to one topic (2022-50, a 70-year-old man with progressive
  memory loss and a family history of AD), so this is a case study across 150+ AD trials, not a cohort.
* ``ctgov``: the eligibility criteria of interventional phase 2 / 3 AD trials registered on ClinicalTrials.gov since
  2015, each routed by an LLM router into ``filter`` (decidable from coded EHR data), ``llm`` (needs notes or reports)
  and ``human`` (consent, study partner, investigator judgement), with an AD category (age, diagnosis, cognitive
  score, amyloid / tau biomarker, MRI, medication, study partner, ...). This is what a hospital can pre-screen for an AD
  trial-ready cohort and what needs a visit, a scan or a biomarker.
* ``chiacheck``: the same router on a seeded sample of Chia criteria, scored against the entity rule of
  :mod:`tools.chia_routes`, so the router's routes come with an agreement figure.

    OPENROUTER_API_KEY=... python -m tools.ad_eval trec --models <m> ...
    OPENROUTER_API_KEY=... python -m tools.ad_eval ctgov --router google/gemma-4-26b-a4b-it
    OPENROUTER_API_KEY=... python -m tools.ad_eval chiacheck --router google/gemma-4-26b-a4b-it
    python -m tools.ad_eval score
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import httpx

from tools import mlbench
from tools.open_cohorts_eval import split_criteria
from tools.trec_ct_eval import CACHE as TREC_CACHE
from tools.trec_ct_eval import CTGOV, MAX_CRITERIA, SEED, note, qrels, rate, topics, wilson
from tools.trialgpt_compare import Client, _safe, _split, parsed_criteria

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "ad"
RESULTS = ROOT / "eval" / "ad" / "results"
AD = re.compile(r"alzheimer|dementia|cognitive impairment|\bMCI\b", re.I)
CATEGORIES = (
    "age",
    "sex_or_reproductive",
    "ad_diagnosis_or_stage",
    "cognitive_or_functional_score",
    "amyloid_or_tau_biomarker",
    "mri_or_imaging",
    "genetics_apoe",
    "medication",
    "other_neurological_or_psychiatric",
    "general_medical_condition",
    "lab_value",
    "study_partner_or_caregiver",
    "consent_or_capacity",
    "other_trial_or_logistics",
    "other",
)
ROUTER = (
    "You route ONE clinical-trial eligibility criterion for a hospital pre-screening system. Return JSON "
    '{"route": "filter" | "llm" | "human", "category": <one of: ' + ", ".join(CATEGORIES) + ">}.\n"
    "filter: decidable from coded EHR data alone (age, sex, ICD diagnosis codes, prescribed drugs, coded lab values "
    "or test results with numeric thresholds, dates of coded events).\n"
    "llm: needs reading clinical notes or reports (severity, history described in text, imaging or test findings "
    "written as text, suspected conditions, symptoms, cognitive test results that are usually only in notes).\n"
    "human: needs a person: consent or capacity, willingness, a study partner or caregiver, investigator judgement, "
    "participation in other trials, logistics, or a new procedure done for screening (a scan or test not yet done).\n"
    "Pick the category that best describes what the criterion is about."
)


# ---------------------------------------------------------------- shared
def _client(model: str) -> tuple[Client, str]:
    c = Client(
        os.environ.get("MLBENCH_BASE_URL", "https://openrouter.ai/api/v1"),
        os.environ.get("OPENROUTER_API_KEY", "none"),
        CACHE / "responses",
    )
    base, c.quant = _split(model)
    return c, base


def _route_one(c: Client, model: str, kind: str, text: str) -> dict[str, Any]:
    msgs = [
        {"role": "system", "content": ROUTER},
        {"role": "user", "content": f"Criterion type: {kind}\nCriterion: {text}\n\nReturn the JSON object."},
    ]
    data = c.chat(model, msgs)
    if "_error" in data:
        return {"route": None, "category": None, "error": str(data["_error"])[:120], "cost": 0.0}
    obj = mlbench.parse_output((data["choices"][0].get("message") or {}).get("content") or "") or {}
    r, cat = str(obj.get("route", "")).lower(), str(obj.get("category", "")).lower()
    return {
        "route": r if r in ("filter", "llm", "human") else None,
        "category": cat if cat in CATEGORIES else "other",
        "cost": float((data.get("usage") or {}).get("cost") or 0.0),
    }


# ---------------------------------------------------------------- trec: AD trials x TREC patients
def trec_pairs() -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    trials: dict[str, dict[str, Any]] = {}
    for y in ("2021", "2022"):
        with (TREC_CACHE / f"trec_{y}_corpus.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                if AD.search(d["title"]) or AD.search(str(d["metadata"].get("diseases", ""))):
                    trials[d["_id"]] = d["metadata"] | {"title": d["title"]}
    notes = {pid: note(t) for y in ("2021", "2022") for pid, t in topics(y).items()}
    pairs = []
    for y in ("2021", "2022"):
        for pid, nct, lab in qrels(y):
            if nct in trials and lab in ("1", "2"):
                crits = [("inclusion", c) for c in parsed_criteria(trials[nct], "inclusion")]
                crits += [("exclusion", c) for c in parsed_criteria(trials[nct], "exclusion")]
                if crits and len(crits) <= MAX_CRITERIA * 2:
                    pairs.append({"patient": pid, "trial": nct, "label": lab, "criteria": crits})
    return pairs, notes


def trec_run(models: list[str], workers: int) -> None:
    pairs, notes = trec_pairs()
    cps = [
        mlbench.Pair(f"{p['patient']}|{p['trial']}|{i}", p["patient"], p["trial"], k, t, "", (), "", False)
        for p in pairs
        for i, (k, t) in enumerate(p["criteria"])
    ]
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    for model in models:
        c, base = _client(model)
        with (
            gzip.open(RESULTS / "raw" / f"trec__{_safe(model)}.jsonl.gz", "wt", encoding="utf-8") as fh,
            ThreadPoolExecutor(workers) as ex,
        ):
            for res in ex.map(lambda p, c=c, b=base: mlbench.judge(c, b, "en", p, notes[p.patient_id]), cps):
                fh.write(json.dumps(res.__dict__, ensure_ascii=False) + "\n")
        print("done trec", model, len(cps), flush=True)


# ---------------------------------------------------------------- ctgov: AD trial criteria routes
def ctgov_trials(limit: int = 400) -> list[dict[str, Any]]:
    path = CACHE / "ctgov_ad.json"
    if path.exists():
        return list(json.loads(path.read_text(encoding="utf-8")))
    CACHE.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    token = None
    with httpx.Client(timeout=60) as http:
        while len(out) < limit:
            params: dict[str, str | int] = {
                "query.cond": "Alzheimer Disease",
                "filter.advanced": "AREA[StudyType]INTERVENTIONAL AND (AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) "
                "AND AREA[StartDate]RANGE[2015-01-01,MAX]",
                "fields": "NCTId,BriefTitle,Phase,OverallStatus,StartDate,EligibilityModule,Condition",
                "pageSize": 100,
                "sort": "StartDate:desc",
            }
            if token:
                params["pageToken"] = token
            for attempt in range(6):
                r = http.get(CTGOV, params=params)
                if r.status_code != 429:
                    break
                time.sleep(2.0 * 2**attempt)
            r.raise_for_status()
            js = r.json()
            for s in js.get("studies", []):
                ps = s["protocolSection"]
                conds = " ".join(ps.get("conditionsModule", {}).get("conditions", []))
                if not re.search(r"alzheimer", conds + ps["identificationModule"].get("briefTitle", ""), re.I):
                    continue
                e = ps.get("eligibilityModule", {})
                out.append(
                    {
                        "nct": ps["identificationModule"]["nctId"],
                        "title": ps["identificationModule"].get("briefTitle", ""),
                        "phase": ps.get("designModule", {}).get("phases", []),
                        "status": ps.get("statusModule", {}).get("overallStatus"),
                        "criteria": split_criteria(e.get("eligibilityCriteria", "")),
                    }
                )
            token = js.get("nextPageToken")
            if not token:
                break
            time.sleep(1.0)
    path.write_text(json.dumps(out[:limit], ensure_ascii=False))
    return out[:limit]


def ctgov_run(router: str, workers: int) -> None:
    trials = ctgov_trials()
    jobs = [(t["nct"], i, k, x) for t in trials for i, (k, x) in enumerate(t["criteria"]) if len(t["criteria"]) <= 80]
    c, base = _client(router)
    one = partial(_route_one, c, base)
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    with (
        gzip.open(RESULTS / "raw" / f"ctgov_routes__{_safe(router)}.jsonl.gz", "wt", encoding="utf-8") as fh,
        ThreadPoolExecutor(workers) as ex,
    ):
        for (nct, i, k, x), r in zip(jobs, ex.map(lambda j: one(j[2], j[3]), jobs), strict=True):
            fh.write(json.dumps({"trial": nct, "i": i, "kind": k, "text": x} | r, ensure_ascii=False) + "\n")
    print("done ctgov", len(trials), "trials", len(jobs), "criteria", flush=True)


def chiacheck_run(router: str, workers: int, n: int = 600) -> None:
    from tools.chia_routes import criteria, fetch, route

    rows = [r for r in criteria(fetch()) if r["entities"]]
    rows = random.Random(SEED).sample(rows, n)
    c, base = _client(router)
    one = partial(_route_one, c, base)
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    with (
        gzip.open(RESULTS / "raw" / f"chiacheck__{_safe(router)}.jsonl.gz", "wt", encoding="utf-8") as fh,
        ThreadPoolExecutor(workers) as ex,
    ):
        for row, r in zip(rows, ex.map(lambda x: one(x["kind"], x["text"]), rows), strict=True):
            fh.write(
                json.dumps(
                    {
                        "trial": row["trial"],
                        "kind": row["kind"],
                        "text": row["text"],
                        "chia_route": route(row["entities"]),
                        "chia_route_q_codeable": route(row["entities"], False),
                    }
                    | r,
                    ensure_ascii=False,
                )
                + "\n"
            )
    print("done chiacheck", n, flush=True)


# ---------------------------------------------------------------- score
def _read(p: Path) -> list[dict[str, Any]]:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh]


def kappa(a: list[str], b: list[str]) -> float:
    labs = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in labs) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def score() -> dict[str, Any]:
    res: dict[str, Any] = {}
    raw = RESULTS / "raw"
    # trec
    files = sorted(raw.glob("trec__*.jsonl.gz"))
    if files:
        pairs, _ = trec_pairs()
        ans = {
            f.name.removesuffix(".jsonl.gz").split("__", 1)[1].replace("__", "/", 1): {
                r["annotation_id"]: r for r in _read(f)
            }
            for f in files
        }
        models = sorted(ans)
        combos = [[m] for m in models] + [[a, b] for i, a in enumerate(models) for b in models[i + 1 :]]
        out = {}
        for ms in combos:
            flags: dict[str, list[tuple[str, bool]]] = defaultdict(list)
            for p in pairs:
                ids = [f"{p['patient']}|{p['trial']}|{i}" for i in range(len(p["criteria"]))]
                blk = any(all((ans[m].get(a, {}).get("label") or "") in mlbench.BLOCKS for m in ms) for a in ids)
                flags["eligible_lost" if p["label"] == "2" else "excluded_caught"].append((p["patient"], blk))
                if p["patient"] == "trec2022-50":
                    flags["topic_2022_50_" + ("eligible_lost" if p["label"] == "2" else "excluded_caught")].append(
                        (p["trial"], blk)
                    )
            out["+".join(ms)] = {k: rate(v) for k, v in flags.items()}
        res["trec"] = {
            "pairs": Counter(p["label"] for p in pairs),
            "patients": len({p["patient"] for p in pairs}),
            "trials": len({p["trial"] for p in pairs}),
            "scores": out,
        }
    # ctgov routes
    for f in sorted(raw.glob("ctgov_routes__*.jsonl.gz")):
        rows = [r for r in _read(f) if r["route"]]
        n = len(rows)
        by_cat: dict[str, Counter[str]] = defaultdict(Counter)
        for r in rows:
            by_cat[r["category"]][r["route"]] += 1
        routes = Counter(r["route"] for r in rows)
        res["ctgov"] = {
            "router": f.name.removesuffix(".jsonl.gz").split("__", 1)[1].replace("__", "/", 1),
            "trials": len({r["trial"] for r in rows}),
            "criteria": n,
            "routes": {k: {"n": v, "share": round(v / n, 4), "wilson95": wilson(v, n)} for k, v in routes.items()},
            "by_category": {k: dict(v) for k, v in sorted(by_cat.items(), key=lambda kv: -sum(kv[1].values()))},
            "cost_usd": round(sum(float(r.get("cost") or 0) for r in _read(f)), 4),
        }
    for f in sorted(raw.glob("chiacheck__*.jsonl.gz")):
        rows = [r for r in _read(f) if r["route"]]
        a = [r["route"] for r in rows]
        b = [r["chia_route"] if r["chia_route"] in ("filter", "llm", "human") else "filter" for r in rows]
        bq = [r["chia_route_q_codeable"] for r in rows]
        agree = sum(x == y for x, y in zip(a, b, strict=True))
        res["chiacheck"] = {
            "n": len(rows),
            "agreement": round(agree / len(rows), 4),
            "agreement_wilson95": wilson(agree, len(rows)),
            "kappa": round(kappa(a, b), 3),
            "kappa_vs_qualifier_codeable_rule": round(kappa(a, bq), 3),
            "confusion": {f"{x}->{y}": c for (x, y), c in sorted(Counter(zip(b, a, strict=True)).items())},
            "router_shares": {k: round(v / len(a), 4) for k, v in Counter(a).items()},
        }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "scores.json").write_text(json.dumps(res, indent=1, default=list))
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ad_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trec")
    t.add_argument("--models", nargs="+", required=True)
    t.add_argument("--workers", type=int, default=24)
    for name in ("ctgov", "chiacheck"):
        s = sub.add_parser(name)
        s.add_argument("--router", default="google/gemma-4-26b-a4b-it")
        s.add_argument("--workers", type=int, default=24)
    sub.add_parser("score")
    sub.add_parser("stats")
    a = ap.parse_args(argv)
    if a.cmd == "trec":
        trec_run(a.models, a.workers)
    elif a.cmd == "ctgov":
        ctgov_run(a.router, a.workers)
    elif a.cmd == "chiacheck":
        chiacheck_run(a.router, a.workers)
    elif a.cmd == "stats":
        pairs, _ = trec_pairs()
        print(
            len(pairs), "AD pairs", Counter(p["label"] for p in pairs), sum(len(p["criteria"]) for p in pairs), "crit"
        )
        tr = ctgov_trials()
        print(len(tr), "ctgov AD trials", sum(len(x["criteria"]) for x in tr), "criteria")
    else:
        print(json.dumps(score(), indent=1, default=list)[:6000])


if __name__ == "__main__":
    main()
