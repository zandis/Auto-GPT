"""More public patient x trial cohorts for the TrialBox judge: the full SIGIR 2016 cohort and TREC CT 2023.

Companion to :mod:`tools.trec_ct_eval` (same prompt, client, pair rule, Wilson and patient-cluster intervals).

* ``sigir``: Koopman and Zuccon's SIGIR 2016 test collection as redistributed by NCBI TrialGPT (58 patient summaries,
  qrels 0 / 1 / 2). Label 2 ("highly likely to refer") is scored as eligible. Label 1 ("would consider") is not an
  exclusion, so this cohort measures eligible pairs lost only. The 79 pairs of the earlier runs are a subset.
* ``trec2023``: TREC CT 2023, 40 synthetic patients written as **structured questionnaires** (diagnosis, scores,
  prior surgery, comorbidities), 8 diseases, NIST qrels 2 = eligible, 1 = excluded. Closest public stand-in for a
  coded record: each field becomes one note line, empty fields are left out.

Trial criteria for both come from the ClinicalTrials.gov API (``eligibilityCriteria``), split into one criterion per
bullet. Today's registry text may differ from the text the assessors read (trials are amended); that is a caveat.

    python -m tools.open_cohorts_eval fetch
    OPENROUTER_API_KEY=... python -m tools.open_cohorts_eval run --cohort sigir --models <m> [--variant suspected]
    python -m tools.open_cohorts_eval score       # -> eval/open_cohorts/results/scores.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import httpx

from tools import mlbench
from tools.medtxt_eval import SUSPECTED
from tools.trec_ct_eval import CTGOV, MAX_CRITERIA, NEGATION, SEED, note, rate
from tools.trialgpt_compare import Client, _safe, _split

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "open_cohorts"
RESULTS = ROOT / "eval" / "open_cohorts" / "results"
SOURCES = {
    "sigir/queries.jsonl": "https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/dataset/sigir/queries.jsonl",
    "sigir/qrels.tsv": "https://raw.githubusercontent.com/ncbi-nlp/TrialGPT/main/dataset/sigir/qrels/test.tsv",
    "trec2023/topics.xml": "https://trec.nist.gov/data/trials/topics2023.xml",
    "trec2023/qrels.txt": "https://trec.nist.gov/data/trials/qrels2023.txt",
}
COHORTS = ("sigir", "trec2023")
SAMPLE = {"sigir": {"2": 10_000}, "trec2023": {"2": 600, "1": 300}}
VARIANTS = {"base": "", "suspected": SUSPECTED, "v4": SUSPECTED, "negation": NEGATION}


# ---------------------------------------------------------------- data
def fetch() -> None:
    for name, url in SOURCES.items():
        dest = CACHE / name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            r = httpx.get(url, timeout=120, follow_redirects=True)
            r.raise_for_status()
            dest.write_bytes(r.content)
    need = sorted({t for c in COHORTS for _, t, _ in selection(c)})
    path = CACHE / "ctgov_trials.json"
    have: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
    todo = [n for n in need if n not in have]
    with httpx.Client(timeout=60) as http:
        for i in range(0, len(todo), 50):
            ids = todo[i : i + 50]
            params: dict[str, str | int] = {
                "filter.ids": ",".join(ids),
                "fields": "NCTId,BriefTitle,EligibilityModule",
                "pageSize": 50,
            }
            for attempt in range(8):
                r = http.get(CTGOV, params=params)
                if r.status_code != 429:
                    break
                time.sleep(2.0 * 2**attempt)
            r.raise_for_status()
            time.sleep(1.5)
            for s in r.json().get("studies", []):
                ps = s["protocolSection"]
                e = ps.get("eligibilityModule", {})
                have[ps["identificationModule"]["nctId"]] = {
                    "title": ps["identificationModule"].get("briefTitle", ""),
                    "criteria": e.get("eligibilityCriteria", ""),
                    "min_age": e.get("minimumAge"),
                    "max_age": e.get("maximumAge"),
                    "sex": e.get("sex"),
                }
            for n in ids:
                have.setdefault(n, None)
            path.write_text(json.dumps(have, ensure_ascii=False))


HEAD = re.compile(r"^\s*(inclusion|exclusion)\s+criteria\s*:?\s*$", re.I)
BULLET = re.compile(r"^\s*(?:[*\-•·]|\d+[.)]|[a-z][.)])\s+")


def split_criteria(text: str) -> list[tuple[str, str]]:
    """CT.gov eligibility text -> [(inclusion|exclusion, criterion)], one per bullet; text before any heading is
    inclusion. Sub-bullets stay separate items (the same granularity NCBI's parser gives)."""
    kind = "inclusion"
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = HEAD.match(line)
        if m:
            kind = m.group(1).lower()
            continue
        item = BULLET.sub("", line).strip()
        if item.endswith(":") and (item.isupper() or "criteria" in item.lower()):
            continue  # a group heading ("OFFSPRING SUBJECTS - INCLUSION CRITERIA:"), not a criterion
        if len(item) >= 5:
            out.append((kind, item))
    return out


def patients(cohort: str) -> dict[str, list[str]]:
    if cohort == "sigir":
        rows = [json.loads(x) for x in (CACHE / "sigir/queries.jsonl").read_text(encoding="utf-8").splitlines() if x]
        return {r["_id"]: note(r["text"]) for r in rows}
    root = ET.parse(CACHE / "trec2023/topics.xml").getroot()
    out = {}
    for t in root.iter("topic"):
        lines = [f"Condition group: {t.get('template')}."]
        for f in t.iter("field"):
            v = " ".join((f.text or "").split())
            if v:
                lines.append(f"{f.get('name')}: {v}")
        out[f"trec2023-{t.get('number')}"] = lines
    return out


def qrels(cohort: str) -> list[tuple[str, str, str]]:
    if cohort == "sigir":
        rows = (CACHE / "sigir/qrels.tsv").read_text().splitlines()[1:]
        return [tuple(r.split("\t")) for r in rows if r.strip()]  # type: ignore[misc]
    out = []
    for line in (CACHE / "trec2023/qrels.txt").read_text().splitlines():
        t, _, nct, rel = line.split()
        out.append((f"trec2023-{t}", nct, rel))
    return out


def selection(cohort: str) -> list[tuple[str, str, str]]:
    rng = random.Random(f"{SEED}:{cohort}")
    rows = qrels(cohort)
    out = []
    for lab, n in SAMPLE[cohort].items():
        pool = sorted(r for r in rows if r[2] == lab)
        rng.shuffle(pool)
        out += pool[: n * 2]
    return out


def dataset(cohort: str) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    trials = json.loads((CACHE / "ctgov_trials.json").read_text(encoding="utf-8"))
    notes = patients(cohort)
    pairs: list[dict[str, Any]] = []
    taken: dict[str, int] = defaultdict(int)
    for pid, nct, lab in selection(cohort):
        tr = trials.get(nct)
        if not tr or pid not in notes or taken[lab] >= SAMPLE[cohort][lab]:
            continue
        crits = split_criteria(tr["criteria"])
        if not crits or len(crits) > MAX_CRITERIA:
            continue
        taken[lab] += 1
        pairs.append({"cohort": cohort, "patient": pid, "trial": nct, "label": lab, "criteria": crits})
    return pairs, notes


# ---------------------------------------------------------------- run
def variant_of(model: str) -> str:
    return model.partition("~")[2] or "base"


def raw_path(cohort: str, model: str) -> Path:
    return RESULTS / "raw" / f"{cohort}__{_safe(model)}.jsonl.gz"


def _judge(c: Client, model: str, notes: dict[str, list[str]], p: mlbench.Pair) -> mlbench.Result:
    return mlbench.judge(c, model, "en", p, notes[p.patient_id])


def run(cohort: str, models: list[str], base_url: str, workers: int, variant: str = "base") -> None:
    pairs, notes = dataset(cohort)
    trials = json.loads((CACHE / "ctgov_trials.json").read_text(encoding="utf-8"))
    cps = []
    for p in pairs:
        for i, (kind, text) in enumerate(p["criteria"]):
            if variant == "negation":
                text = f"{text}\n(Trial: {trials[p['trial']]['title']})"
            cps.append(
                mlbench.Pair(
                    f"{p['patient']}|{p['trial']}|{i}", p["patient"], p["trial"], kind, text, "", (), "", False
                )
            )
    key = os.environ.get("OPENROUTER_API_KEY", "none")
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    base_system = mlbench.SYSTEM
    mlbench.SYSTEM = base_system + VARIANTS[variant]
    for model in models:
        c = Client(base_url, key, CACHE / "responses")
        base, c.quant = _split(model)
        tag = model if variant == "base" else f"{model}~{variant}"
        with gzip.open(raw_path(cohort, tag), "wt", encoding="utf-8") as fh, ThreadPoolExecutor(workers) as ex:
            for res in ex.map(partial(_judge, c, base, notes), cps):
                fh.write(json.dumps(res.__dict__, ensure_ascii=False) + "\n")
        print("done", cohort, tag, len(cps), flush=True)
    mlbench.SYSTEM = base_system


# ---------------------------------------------------------------- score
def _load(cohort: str, model: str) -> dict[str, dict[str, Any]]:
    with gzip.open(raw_path(cohort, model), "rt", encoding="utf-8") as fh:
        return {r["annotation_id"]: r for r in map(json.loads, fh)}


def _complete(cohort: str, model: str, expected: int) -> bool:
    """False while a run is still appending to the gzip file (no end-of-stream marker yet) or has not started."""
    try:
        n = len(_load(cohort, model))
    except EOFError:
        n = -1
    if n < 0.98 * expected:
        print("skipping", cohort, model, f"({max(n, 0)}/{expected} answers, run still in progress)")
        return False
    return True


def score_combo(cohort: str, models: list[str], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    ans = {m: _load(cohort, m) for m in models}
    flags: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    cost = 0.0
    n_crit = 0
    for p in pairs:
        ids = [f"{p['patient']}|{p['trial']}|{i}" for i in range(len(p["criteria"]))]
        n_crit += len(ids)
        cost += sum(float(ans[m].get(a, {}).get("cost") or 0.0) for m in models for a in ids)
        blk = any(all((ans[m].get(a, {}).get("label") or "") in mlbench.BLOCKS for m in models) for a in ids)
        flags["eligible_lost" if p["label"] == "2" else "excluded_caught"].append((p["patient"], blk))
    out: dict[str, Any] = {k: rate(v) for k, v in flags.items()}
    out |= {"criteria": n_crit, "cost_usd": round(cost, 4)}
    return out


def score() -> dict[str, Any]:
    res: dict[str, Any] = {}
    for cohort in COHORTS:
        files = sorted((RESULTS / "raw").glob(f"{cohort}__*.jsonl.gz"))
        if not files:
            continue
        pairs, _notes = dataset(cohort)
        models = [f.name.removesuffix(".jsonl.gz").split("__", 1)[1].replace("__", "/", 1) for f in files]
        expected = sum(len(p["criteria"]) for p in pairs)
        models = [m for m in models if _complete(cohort, m, expected)]
        if not models:
            continue
        block: dict[str, Any] = {
            "pairs": {lab: sum(p["label"] == lab for p in pairs) for lab in SAMPLE[cohort]},
            "patients": len({p["patient"] for p in pairs}),
            "trials": len({p["trial"] for p in pairs}),
            "single": {m: score_combo(cohort, [m], pairs) for m in models},
            "both_must_block": {
                f"{a}+{b}": score_combo(cohort, [a, b], pairs)
                for i, a in enumerate(models)
                for b in models[i + 1 :]
                if variant_of(a) == variant_of(b)
            },
        }
        res[cohort] = block
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "scores.json").write_text(json.dumps(res, indent=1, default=list))
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="open_cohorts_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("stats")
    r = sub.add_parser("run")
    r.add_argument("--cohort", choices=COHORTS, required=True)
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--workers", type=int, default=32)
    r.add_argument("--variant", default="base", choices=sorted(VARIANTS))
    r.add_argument("--base-url", default=os.environ.get("MLBENCH_BASE_URL", "https://openrouter.ai/api/v1"))
    sub.add_parser("score")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch()
    elif a.cmd == "stats":
        for c in COHORTS:
            pairs, notes = dataset(c)
            print(c, len(pairs), "pairs", sum(len(p["criteria"]) for p in pairs), "criteria", len(notes), "patients")
    elif a.cmd == "run":
        fetch()
        run(a.cohort, a.models, a.base_url, a.workers, a.variant)
    else:
        for cohort, block in score().items():
            for group in ("single", "both_must_block"):
                for k, v in block[group].items():
                    cells = "  ".join(
                        f"{name} {x['k']}/{x['n']}={100 * x['rate']:.1f}% "
                        f"({100 * x['cluster95'][0]:.1f}-{100 * x['cluster95'][1]:.1f})"
                        for name, x in v.items()
                        if isinstance(x, dict)
                    )
                    print(f"{cohort:8s} {k:70s} {cells}")


if __name__ == "__main__":
    main()
