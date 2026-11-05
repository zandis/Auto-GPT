"""Alzheimer's trial-ready cohort on a Synthea population: what the structured filters alone can decide.

Synthea (Apache-2.0, synthetic, D0) models Alzheimer's disease with MMSE scores, anticoagulants, seizures, cancer and
kidney disease, so its CSV export is a fair stand-in for a hospital's coded data. This tool applies the coded part of
an early-AD protocol (modelled on the public criteria of lecanemab Clarity AD, NCT03887455) and leaves the rest
(amyloid status, study partner, MRI findings) to the LLM or a person, as the filter-first design (D-95) does.

Every count is computed twice, once in Python and once in DuckDB SQL over the same CSV files, and the two must agree
exactly (the "independent implementation" check of spec §10a M2). The funnel, the drop-one counts (patients who pass
every other criterion and fail only this one) and the share left to the LLM or a person are written to
``eval/synthea/results/ad_cohort.json``. Synthea output stays out of the repo.

    java -jar synthea-with-dependencies.jar -p 10000 -a 55-90 --exporter.csv.export=true ...
    python -m tools.synthea_ad_cohort --csv /var/tmp/synthea/out10k/csv
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "synthea" / "results"

AD_CODES = {"26929004", "230265002"}  # Alzheimer's disease; familial early-onset AD (SNOMED CT)
MMSE = "72106-8"  # LOINC, Mini-Mental State Examination total score (as Synthea codes it)
EXCLUDE = {  # criterion -> (table, lower-case description substrings, active only)
    "E1 stroke or cerebrovascular disease": ("conditions", ("stroke", "cerebrovascular", "cerebral infarct"), False),
    "E2 seizure disorder or epilepsy": ("conditions", ("seizure disorder", "epilepsy"), False),
    "E3 anticoagulant now": ("medications", ("warfarin", "heparin", "apixaban", "rivaroxaban", "dabigatran"), True),
    "E4 malignancy in the last 5 years": ("conditions", ("malignant neoplasm", "carcinoma", "lung cancer"), False),
    "E5 severe kidney disease": ("conditions", ("end-stage renal", "chronic kidney disease stage 4"), False),
}
INCLUDE = ["I1 alive", "I2 age 50-90", "I3 Alzheimer's disease diagnosis", "I4 MMSE 22-30 in the last 12 months"]
NOT_CODED = {  # criterion -> who decides; not in coded EHR data
    "Amyloid PET or CSF positive": "LLM reads the PET or lab report",
    "MRI: no more than 4 microhemorrhages, no macro-haemorrhage": "LLM reads the MRI report",
    "Study partner available": "person (coordinator call)",
    "Able to give consent or has a legal representative": "person",
}


MMSE_STATUS: dict[str, str] = {}  # AD patient -> state of the latest MMSE (filled by python_flags)


def _d(s: str) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _years(born: date, ref: date) -> int:
    return ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))


def python_flags(folder: Path, ref: date) -> dict[str, dict[str, bool]]:
    """patient id -> {criterion: passes}. Exclusion criteria pass when the patient does NOT have the finding."""
    pats: dict[str, dict[str, bool]] = {}
    with (folder / "patients.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            born, died = _d(r["BIRTHDATE"]), _d(r["DEATHDATE"])
            assert born is not None
            alive = died is None or died > ref
            pats[r["Id"]] = {"I1 alive": alive, "I2 age 50-90": 50 <= _years(born, ref) <= 90}
    ad: set[str] = set()
    hits: dict[str, set[str]] = defaultdict(set)
    five_years = date(ref.year - 5, ref.month, min(ref.day, 28))
    with (folder / "conditions.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            start = _d(r["START"])
            if start is None or start > ref:
                continue
            if r["CODE"] in AD_CODES:
                ad.add(r["PATIENT"])
            desc = r["DESCRIPTION"].lower()
            for name, (table, words, _active) in EXCLUDE.items():
                if table != "conditions" or not any(w in desc for w in words):
                    continue
                stop = _d(r["STOP"])
                if name.startswith("E4") and stop is not None and stop < five_years:
                    continue
                hits[name].add(r["PATIENT"])
    with (folder / "medications.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            start, stop = _d(r["START"]), _d(r["STOP"])
            desc = r["DESCRIPTION"].lower()
            for name, (table, words, _active) in EXCLUDE.items():
                active = start is not None and start <= ref and (stop is None or stop > ref)
                if table == "medications" and active and any(w in desc for w in words):
                    hits[name].add(r["PATIENT"])
    latest: dict[str, tuple[date, float]] = {}
    with (folder / "observations.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["CODE"] != MMSE:
                continue
            when = _d(r["DATE"])
            if when is None or when > ref:
                continue
            if r["PATIENT"] not in latest or when > latest[r["PATIENT"]][0]:
                latest[r["PATIENT"]] = (when, float(r["VALUE"]))
    year_ago = date(ref.year - 1, ref.month, min(ref.day, 28))
    MMSE_STATUS.clear()
    for pid in ad:
        m = latest.get(pid)
        MMSE_STATUS[pid] = (
            "no MMSE on record"
            if m is None
            else "older than 12 months"
            if m[0] < year_ago
            else "below 22"
            if m[1] < 22
            else "above 30"
            if m[1] > 30
            else "22-30, current"
        )
    for pid, f in pats.items():
        f["I3 Alzheimer's disease diagnosis"] = pid in ad
        m = latest.get(pid)
        f["I4 MMSE 22-30 in the last 12 months"] = bool(m and m[0] >= year_ago and 22 <= m[1] <= 30)
        for name in EXCLUDE:
            f[name] = pid not in hits[name]
    return pats


def sql_flags(folder: Path, ref: date) -> dict[str, dict[str, bool]]:
    """The same flags from an independent DuckDB SQL implementation."""
    con = duckdb.connect()
    for t in ("patients", "conditions", "medications", "observations"):
        path = str(folder / f"{t}.csv").replace("'", "''")
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_csv('{path}', header=true, all_varchar=true)")
    r = ref.isoformat()
    five = date(ref.year - 5, ref.month, min(ref.day, 28)).isoformat()
    year = date(ref.year - 1, ref.month, min(ref.day, 28)).isoformat()

    def like(words: tuple[str, ...]) -> str:
        return "(" + " OR ".join(f"lower(DESCRIPTION) LIKE '%{w}%'" for w in words) + ")"

    ex_sql = []
    for name, (table, words, active) in EXCLUDE.items():
        if table == "medications":
            cond = f"{like(words)} AND START[:10] <= '{r}' AND (STOP IS NULL OR STOP = '' OR STOP[:10] > '{r}')"
        else:
            cond = f"{like(words)} AND START[:10] <= '{r}'"
            if name.startswith("E4"):
                cond += f" AND (STOP IS NULL OR STOP = '' OR STOP[:10] >= '{five}')"
        _ = active
        ex_sql.append(f'p.Id NOT IN (SELECT PATIENT FROM {table} WHERE {cond}) AS "{name}"')
    ad = ", ".join(f"'{c}'" for c in sorted(AD_CODES))
    q = f"""
    WITH mm AS (
      SELECT PATIENT, arg_max(CAST(VALUE AS DOUBLE), DATE) AS v, max(DATE[:10]) AS d
      FROM observations WHERE CODE = '{MMSE}' AND DATE[:10] <= '{r}' GROUP BY PATIENT)
    SELECT p.Id,
      (p.DEATHDATE IS NULL OR p.DEATHDATE = '' OR p.DEATHDATE[:10] > '{r}') AS "I1 alive",
      (date_diff('year', CAST(p.BIRTHDATE AS DATE), DATE '{r}')
        - CASE WHEN strftime(DATE '{r}', '%m-%d') < strftime(CAST(p.BIRTHDATE AS DATE), '%m-%d') THEN 1 ELSE 0 END)
        BETWEEN 50 AND 90 AS "I2 age 50-90",
      p.Id IN (SELECT PATIENT FROM conditions WHERE CODE IN ({ad}) AND START[:10] <= '{r}')
        AS "I3 Alzheimer's disease diagnosis",
      coalesce(mm.d >= '{year}' AND mm.v BETWEEN 22 AND 30, false) AS "I4 MMSE 22-30 in the last 12 months",
      {", ".join(ex_sql)}
    FROM patients p LEFT JOIN mm ON mm.PATIENT = p.Id
    """
    cur = con.execute(q)
    cols = [c[0] for c in cur.description]
    return {row[0]: {c: bool(v) for c, v in zip(cols[1:], row[1:], strict=True)} for row in cur.fetchall()}


def summarise(flags: dict[str, dict[str, bool]]) -> dict[str, Any]:
    order = INCLUDE + list(EXCLUDE)
    funnel, left = [], set(flags)
    for c in order:
        left = {p for p in left if flags[p][c]}
        funnel.append({"criterion": c, "remaining": len(left)})
    base = {p for p in flags if flags[p]["I1 alive"] and flags[p]["I2 age 50-90"]}
    drop_one = {
        c: sum(1 for p in flags if not flags[p][c] and all(flags[p][o] for o in order if o != c)) for c in order
    }
    ad_alive = [p for p in flags if all(flags[p][c] for c in INCLUDE[:3])]
    mmse: dict[str, int] = defaultdict(int)
    for p in ad_alive:
        mmse[MMSE_STATUS.get(p, "no MMSE on record")] += 1
    return {
        "population": len(flags),
        "ad_alive_50_90_mmse": dict(sorted(mmse.items())),
        "alive_50_90": len(base),
        "funnel": funnel,
        "coded_candidates": len(left),
        "drop_one": drop_one,
        "per_1000_alive_50_90": round(1000 * len(left) / len(base), 2) if base else 0.0,
        "still_to_decide": NOT_CODED,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="synthea_ad_cohort")
    ap.add_argument("--csv", type=Path, required=True, help="Synthea CSV export folder")
    ap.add_argument("--ref", type=date.fromisoformat, default=date(2026, 11, 5), help="screening date")
    a = ap.parse_args(argv)
    py, sql = python_flags(a.csv, a.ref), sql_flags(a.csv, a.ref)
    mismatch = [p for p in py if py[p] != sql.get(p)]
    res = summarise(py)
    res |= {
        "ref_date": a.ref.isoformat(),
        "independent_sql_agrees": not mismatch and set(py) == set(sql),
        "mismatches": len(mismatch),
        "protocol": "coded criteria modelled on lecanemab Clarity AD (NCT03887455), simplified",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "ad_cohort.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("population", "alive_50_90", "coded_candidates", "independent_sql_agrees")}))
    for f in res["funnel"]:
        print(f"  {f['criterion']:45s} {f['remaining']:>7,}")


if __name__ == "__main__":
    main()
