"""TrialBox judge on the TREC 2021 / 2022 Clinical Trials cohorts: pair-level validation with error bounds.

The SIGIR set behind :mod:`tools.trialgpt_compare` has 79 eligible patient x trial pairs, so one lost pair moves the
headline by 1.3 points. TREC CT 2021 (75 patients) and 2022 (50 patients) have NIST pair labels for ~35,000
judged pairs: 2 = eligible, 1 = excluded, 0 = not relevant. This tool samples eligible and excluded pairs, runs the
TrialBox per-criterion judge (``tools.mlbench`` prompt, unchanged) on every criterion of each sampled trial, and scores
at the pair level, the unit a coordinator sees:

* **eligible pairs lost**: an eligible pair where some criterion blocks (inclusion "not included" or exclusion
  "excluded"). With two models the S4 rule applies: a criterion blocks only when both block it.
* **excluded pairs caught**: an excluded pair blocked by some criterion (the screening value).
* **age / sex filter**: the deterministic S1 check on ClinicalTrials.gov's structured ``minimumAge`` /
  ``maximumAge`` / ``sex`` against the age and sex written in the topic. Reported alone and as filter-then-LLM.

Error bounds: Wilson 95 % intervals on pair rates, plus a patient-cluster bootstrap (pairs of one patient are not
independent), seeded. Labels are NIST assessor judgements on the trial as a whole, not per criterion.

    python -m tools.trec_ct_eval fetch                          # NIST topics + qrels, NCBI corpus, CT.gov fields
    OPENROUTER_API_KEY=... python -m tools.trec_ct_eval run --models openai/gpt-oss-120b google/gemma-4-26b-a4b-it
    python -m tools.trec_ct_eval score                          # -> eval/trec_ct/results/scores.json

Data stays in ``.cache/trec_ct`` (never committed); model answers are cached by request hash and the per-criterion
answers are written to ``eval/trec_ct/results/raw``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from tools import mlbench
from tools.trialgpt_compare import Client, _safe, _split, parsed_criteria

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache" / "trec_ct"
RESULTS = ROOT / "eval" / "trec_ct" / "results"
NIST = "https://trec.nist.gov/data/trials/"
NCBI = "https://ftp.ncbi.nlm.nih.gov/pub/lu/TrialGPT/"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
YEARS = ("2021", "2022")
SEED = 20261105
SAMPLE = {"2": 600, "1": 250}  # per year: eligible, excluded pairs
MAX_CRITERIA = 40  # longer trials are skipped (a few 100+ item trials would dominate the cost)
# Candidate judge-prompt amendment from the AUDIT.md error patterns (not yet in judge_v3.md): negated exclusions and
# "other than the index condition". With this variant the criterion also carries the trial title.
NEGATION = (
    " Read negated criteria literally. An exclusion criterion written as an absence ('No evidence of X', 'Negative "
    "test for Y', 'never treated', 'no prior Z') applies only when the patient matches that absence: a patient who has "
    "X, tested positive for Y, or was treated is \"not excluded\" by it. A criterion about 'other' or 'another' "
    "condition does not apply to the condition the trial is studying (see the trial title). Block only on a stated "
    'fact; when the note is silent answer "not enough information".'
)
VARIANTS = {"base": "", "negation": NEGATION}


# ---------------------------------------------------------------- data
def fetch() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for y in YEARS:
        for name, base in ((f"qrels{y}.txt", NIST), (f"topics{y}.xml", NIST), (f"trec_{y}_corpus.jsonl", NCBI)):
            dest = CACHE / name
            if not dest.exists():
                with httpx.stream("GET", base + name, timeout=900, follow_redirects=True) as r, dest.open("wb") as fh:
                    r.raise_for_status()
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
    sel = selection()
    trials_file = CACHE / "sample_trials.json"
    if not trials_file.exists():
        need = {n for _, _, n, _ in sel}
        out = {}
        for y in YEARS:
            with (CACHE / f"trec_{y}_corpus.jsonl").open(encoding="utf-8") as fh:
                for line in fh:
                    d = json.loads(line)
                    if d["_id"] in need and d["_id"] not in out:
                        m = d["metadata"]
                        out[d["_id"]] = {
                            "title": d["title"],
                            "inclusion_criteria": m.get("inclusion_criteria", ""),
                            "exclusion_criteria": m.get("exclusion_criteria", ""),
                        }
        trials_file.write_text(json.dumps(out, ensure_ascii=False))
    ct_file = CACHE / "ctgov_fields.json"
    ct: dict[str, Any] = json.loads(ct_file.read_text()) if ct_file.exists() else {}
    todo = sorted({n for _, _, n, _ in sel} - set(ct))
    with httpx.Client(timeout=60) as http:
        for i in range(0, len(todo), 50):
            ids = todo[i : i + 50]
            params: dict[str, str | int] = {
                "filter.ids": ",".join(ids),
                "fields": "NCTId,EligibilityModule",
                "pageSize": 50,
            }
            for attempt in range(8):
                r = http.get(CTGOV, params=params)
                if r.status_code != 429:
                    break
                time.sleep(2.0 * 2**attempt)  # CT.gov rate limit (~50 requests / minute)
            r.raise_for_status()
            time.sleep(1.5)
            for s in r.json().get("studies", []):
                ps = s["protocolSection"]
                e = ps.get("eligibilityModule", {})
                ct[ps["identificationModule"]["nctId"]] = {
                    "min_age": e.get("minimumAge"),
                    "max_age": e.get("maximumAge"),
                    "sex": e.get("sex"),
                }
            for n in ids:
                ct.setdefault(n, None)  # withdrawn / renamed: no structured fields
            ct_file.write_text(json.dumps(ct, indent=0, sort_keys=True))
    ct_file.write_text(json.dumps(ct, indent=0, sort_keys=True))


def topics(year: str) -> dict[str, str]:
    root = ET.parse(CACHE / f"topics{year}.xml").getroot()
    return {f"trec{year}-{t.get('number')}": " ".join((t.text or "").split()) for t in root.iter("topic")}


SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def note(text: str) -> list[str]:
    return [s for s in SENT.split(text) if s.strip()]


def qrels(year: str) -> list[tuple[str, str, str]]:
    out = []
    for line in (CACHE / f"qrels{year}.txt").read_text().splitlines():
        t, _, nct, rel = line.split()
        out.append((f"trec{year}-{t}", nct, rel))
    return out


def selection() -> list[tuple[str, str, str, str]]:
    """Seeded sample (year, patient, trial, label): SAMPLE[label] pairs per year, spread over patients."""
    out = []
    for y in YEARS:
        rng = random.Random(f"{SEED}:{y}")
        rows = qrels(y)
        for lab, n in SAMPLE.items():
            pool = sorted(r for r in rows if r[2] == lab)
            rng.shuffle(pool)
            out += [(y, p, t, lab) for p, t, _ in pool[: n * 2]]  # 2x head room for trials dropped below
    return out


def dataset() -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, Any], dict[str, Any]]:
    """Sampled pairs that have a usable criteria list, their notes, the trial texts and CT.gov fields."""
    trials = json.loads((CACHE / "sample_trials.json").read_text(encoding="utf-8"))
    ct = json.loads((CACHE / "ctgov_fields.json").read_text())
    notes = {pid: note(t) for y in YEARS for pid, t in topics(y).items()}
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    taken: dict[tuple[str, str], int] = defaultdict(int)
    for y, pid, nct, lab in selection():
        tr = trials.get(nct)
        if tr is None or (pid, nct) in seen or taken[(y, lab)] >= SAMPLE[lab]:
            continue
        crits = [("inclusion", c) for c in parsed_criteria(tr, "inclusion")]
        crits += [("exclusion", c) for c in parsed_criteria(tr, "exclusion")]
        if not crits or len(crits) > MAX_CRITERIA:
            continue
        seen.add((pid, nct))
        taken[(y, lab)] += 1
        pairs.append({"year": y, "patient": pid, "trial": nct, "label": lab, "criteria": crits})
    return pairs, notes, trials, ct


def criterion_pairs(pairs: list[dict[str, Any]], titles: dict[str, str] | None = None) -> list[mlbench.Pair]:
    out = []
    for p in pairs:
        for i, (kind, text) in enumerate(p["criteria"]):
            if titles:
                text = f"{text}\n(Trial: {titles[p['trial']]})"
            out.append(
                mlbench.Pair(
                    annotation_id=f"{p['patient']}|{p['trial']}|{i}",
                    patient_id=p["patient"],
                    trial_id=p["trial"],
                    criterion_type=kind,
                    criterion=text,
                    expert_label="",
                    expert_sentences=(),
                    gpt4_label="",
                    training=False,
                )
            )
    return out


# ---------------------------------------------------------------- deterministic age / sex filter (S1)
AGE = re.compile(
    r"(\d{1,3})[- ]?(?:years?|yrs?)(?:[- ]old)?\b|(\d{1,3})\s*(?:yo|y/o|y\.o\.)|\baged? (\d{1,3})\b"
    r"|^\s*(?:an? )?(\d{1,3})\s*[MF]\b",
    re.I,
)
SMALL = re.compile(r"(\d{1,2})[- ](month|week|day)s?[- ]old", re.I)
_AGE_SEX = r"\b\d{1,3}\s*(?:yo |y/o |year[- ]old )?"
FEMALE = re.compile(r"\b(woman|female|girl|lady|she|her|mother|pregnant)\b|" + _AGE_SEX + r"F\b", re.I)
MALE = re.compile(r"\b(man|male|boy|gentleman|he|his)\b|" + _AGE_SEX + r"M\b", re.I)


def patient_age_sex(text: str) -> tuple[float | None, str | None]:
    """Age (years) and sex as written in a TREC topic; ``None`` when not stated (the filter then never blocks)."""
    age: float | None = None
    if (sm := SMALL.search(text)) is not None:
        age = int(sm.group(1)) / {"month": 12, "week": 52.18, "day": 365.25}[sm.group(2).lower()]
    elif (m := AGE.search(text)) is not None:
        age = float(next(g for g in m.groups() if g))
    f, ma = len(FEMALE.findall(text)), len(MALE.findall(text))
    sex = "FEMALE" if f > ma else "MALE" if ma > f else None
    return age, sex


def ct_age(v: str | None) -> float | None:
    if not v:
        return None
    m = re.match(r"(\d+(?:\.\d+)?)\s*(year|month|week|day|hour|minute)", v, re.I)
    if not m:
        return None
    div = {"year": 1, "month": 12, "week": 52.18, "day": 365.25, "hour": 8766, "minute": 525960}[m.group(2).lower()]
    return float(m.group(1)) / div


def age_sex_filter(fields: dict[str, Any] | None, text: str) -> str:
    """``pass`` | ``block`` | ``unknown`` (no structured field or patient age/sex not stated: never blocks)."""
    if not fields:
        return "unknown"
    age, sex = patient_age_sex(text)
    lo, hi = ct_age(fields.get("min_age")), ct_age(fields.get("max_age"))
    if any("week" in str(fields.get(k) or "").lower() for k in ("min_age", "max_age")):
        lo = hi = None  # neonatal trials often put gestational age in these fields: leave age to the reader
    if age is not None and ((lo is not None and age < lo) or (hi is not None and age > hi)):
        return "block"
    if sex and fields.get("sex") in ("MALE", "FEMALE") and fields["sex"] != sex:
        return "block"
    return "pass"


# ---------------------------------------------------------------- run
def variant_of(model: str) -> str:
    return model.partition("~")[2] or "base"


def raw_path(model: str) -> Path:
    return RESULTS / "raw" / f"{_safe(model)}.jsonl.gz"


def run(models: list[str], base_url: str, workers: int, variant: str = "base") -> None:
    pairs, notes, trials, _ = dataset()
    cps = criterion_pairs(pairs, {k: v["title"] for k, v in trials.items()} if variant != "base" else None)
    base_system = mlbench.SYSTEM
    mlbench.SYSTEM = base_system + VARIANTS[variant]
    key = os.environ.get("OPENROUTER_API_KEY", "none")
    (RESULTS / "raw").mkdir(parents=True, exist_ok=True)
    for model in models:
        c = Client(base_url, key, CACHE / "responses")
        base, c.quant = _split(model)
        tag = model if variant == "base" else f"{model}~{variant}"
        with gzip.open(raw_path(tag), "wt", encoding="utf-8") as fh, ThreadPoolExecutor(workers) as ex:
            for n, res in enumerate(
                ex.map(lambda p, c=c, base=base: mlbench.judge(c, base, "en", p, notes[p.patient_id]), cps)
            ):
                fh.write(json.dumps(res.__dict__, ensure_ascii=False) + "\n")
                if n % 2000 == 0:
                    print(model, n, "/", len(cps), flush=True)
        print("done", tag, len(cps), flush=True)
    mlbench.SYSTEM = base_system


# ---------------------------------------------------------------- scoring
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def cluster_ci(flags: list[tuple[str, bool]], reps: int = 2000, seed: int = SEED) -> tuple[float, float]:
    """Percentile CI of a pair rate, resampling patients (clusters) with replacement."""
    by: dict[str, list[bool]] = defaultdict(list)
    for pid, f in flags:
        by[pid].append(f)
    ids = sorted(by)
    if not ids:
        return (0.0, 1.0)
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        k = n = 0
        for pid in (rng.choice(ids) for _ in ids):
            k += sum(by[pid])
            n += len(by[pid])
        vals.append(k / n if n else 0.0)
    vals.sort()
    return (vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1])


def rate(flags: list[tuple[str, bool]]) -> dict[str, Any]:
    k, n = sum(f for _, f in flags), len(flags)
    return {"k": k, "n": n, "rate": k / n if n else 0.0, "wilson95": wilson(k, n), "cluster95": cluster_ci(flags)}


def load(model: str) -> dict[str, dict[str, Any]]:
    with gzip.open(raw_path(model), "rt", encoding="utf-8") as fh:
        return {r["annotation_id"]: r for r in map(json.loads, fh)}


def blocks(models: list[str], answers: dict[str, dict[str, dict[str, Any]]], aid: str) -> bool:
    return all((answers[m].get(aid, {}).get("label") or "") in mlbench.BLOCKS for m in models)


def score_combo(
    models: list[str],
    answers: dict[str, dict[str, dict[str, Any]]],
    pairs: list[dict[str, Any]],
    ct: dict[str, Any],
    notes_text: dict[str, str],
) -> dict[str, Any]:
    out: dict[str, Any] = {"models": models}
    variants: dict[str, dict[str, list[tuple[str, bool]]]] = defaultdict(lambda: defaultdict(list))
    crit_blocks = crit_n = 0
    cost = 0.0
    errors = 0
    for p in pairs:
        ids = [f"{p['patient']}|{p['trial']}|{i}" for i in range(len(p["criteria"]))]
        llm = any(blocks(models, answers, a) for a in ids)
        crit_blocks += sum(blocks(models, answers, a) for a in ids)
        crit_n += len(ids)
        for m in models:
            for a in ids:
                r = answers[m].get(a, {})
                cost += float(r.get("cost") or 0.0)
                errors += bool(r.get("error")) or a not in answers[m]
        filt = age_sex_filter(ct.get(p["trial"]), notes_text[p["patient"]]) == "block"
        key = "eligible_lost" if p["label"] == "2" else "excluded_caught"
        for name, flag in (("llm", llm), ("filter", filt), ("filter_then_llm", filt or llm)):
            variants[name][key].append((p["patient"], flag))
            variants[name][f"{key}_{p['year']}"].append((p["patient"], flag))
    for name, v in variants.items():
        out[name] = {k: rate(f) for k, f in sorted(v.items())}
    out["criteria"] = crit_n
    out["criterion_block_rate"] = crit_blocks / crit_n if crit_n else 0.0
    out["cost_usd"] = round(cost, 4)
    out["cost_per_1k_criteria"] = round(1000 * cost / crit_n, 4) if crit_n else 0.0
    out["unanswered"] = errors
    return out


def score() -> dict[str, Any]:
    pairs, notes, _, ct = dataset()
    notes_text = {pid: " ".join(s) for pid, s in notes.items()}
    models = sorted(
        f.name.removesuffix(".jsonl.gz").replace("__", "/", 1) for f in (RESULTS / "raw").glob("*.jsonl.gz")
    )
    answers = {m: load(m) for m in models}
    res: dict[str, Any] = {
        "pairs": {
            "eligible": sum(p["label"] == "2" for p in pairs),
            "excluded": sum(p["label"] == "1" for p in pairs),
            "patients": len({p["patient"] for p in pairs}),
            "trials": len({p["trial"] for p in pairs}),
        },
        "single": {m: score_combo([m], answers, pairs, ct, notes_text) for m in models},
        "both_must_block": {
            f"{a}+{b}": score_combo([a, b], answers, pairs, ct, notes_text)
            for i, a in enumerate(models)
            for b in models[i + 1 :]
            if variant_of(a) == variant_of(b)
        },
    }
    res["filter_coverage"] = {
        "trials_with_ctgov_fields": sum(1 for p in {q["trial"] for q in pairs} if ct.get(p)),
        "patients_age_parsed": sum(patient_age_sex(t)[0] is not None for t in notes_text.values()),
        "patients_sex_parsed": sum(patient_age_sex(t)[1] is not None for t in notes_text.values()),
        "patients": len(notes_text),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "scores.json").write_text(json.dumps(res, indent=1, default=list))
    return res


def _fmt(r: dict[str, Any]) -> str:
    lo, hi = r["cluster95"]
    return f"{r['k']}/{r['n']} = {100 * r['rate']:.1f}% (95% CI {100 * lo:.1f}-{100 * hi:.1f})"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="trec_ct_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="+", required=True)
    r.add_argument("--workers", type=int, default=24)
    r.add_argument("--variant", default="base", choices=sorted(VARIANTS))
    r.add_argument("--base-url", default=os.environ.get("MLBENCH_BASE_URL", "https://openrouter.ai/api/v1"))
    sub.add_parser("score")
    sub.add_parser("stats")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        fetch()
    elif a.cmd == "stats":
        pairs, *_ = dataset()
        print(len(pairs), "pairs,", sum(len(p["criteria"]) for p in pairs), "criteria")
    elif a.cmd == "run":
        fetch()
        run(a.models, a.base_url, a.workers, a.variant)
    else:
        res = score()
        for group in ("single", "both_must_block"):
            for k, v in res[group].items():
                print(f"{k:70s} lost {_fmt(v['llm']['eligible_lost'])}  caught {_fmt(v['llm']['excluded_caught'])}")
                print(
                    f"{'  + age/sex filter':70s} lost {_fmt(v['filter_then_llm']['eligible_lost'])}  "
                    f"caught {_fmt(v['filter_then_llm']['excluded_caught'])}  ${v['cost_usd']}"
                )


if __name__ == "__main__":
    main()
