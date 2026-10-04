"""Analyst-style "manual" CGRD count for the first GZQO funnel steps — the reference the funnel-compare harness is
exercised against on synthetic data (tests/fixtures/synthetic_patients/site-*/cgrd.sqlite).

Written the way a hospital data analyst counts (period-based, hand SQL on the source tables), deliberately *not*
with TrialBox's month-end semantics, so that the harness sees and documents real definition differences:

* START  : patients with ≥1 encounter in the lookback period;
* INC-01 : + age ≥ 18 at the end of the period;
* INC-02 : + any gout diagnosis (ICD-10-CM M10*, M1A*) on or before the end of the period;
* INC-03 : + any BMI ≥ 27 (same-day height + weight, or weight with the latest earlier height) in the period;
* INC-04 : + any serum urate ≥ 6.8 mg/dL in the period, or ≥ 6.0 mg/dL with any urate-lowering drug in the period.

    python tools/manual_funnel.py --db tests/fixtures/synthetic_patients/site-a/cgrd.sqlite --end 2026-09-30 \
        --lookback 36 --out manual_counts.csv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "libs")]

ULT_ATC = ("M04AA01", "M04AA03", "M04AB03", "M04AB01")
DEFINITIONS = {
    "START": "≥1 encounter in the period",
    "GZQO-INC-01": "age ≥ 18 at period end",
    "GZQO-INC-02": "gout dx M10*/M1A* on or before period end",
    "GZQO-INC-03": "any BMI ≥ 27 in the period",
    "GZQO-INC-04": "any urate ≥ 6.8 (≥ 6.0 on ULT) in the period",
}
EXPLANATIONS = {
    "GZQO-INC-03": "system: latest BMI within 365 d of a month-end (D-17); manual: any BMI in the period",
    "GZQO-INC-04": "system: latest urate within the IR window at a month-end; manual: any value in the period",
}


def counts(db: Path, end: date, lookback: int) -> dict[str, int]:
    from tb_common.timeutil import add_months

    start = add_months(end, -lookback).isoformat()
    e = end.isoformat()
    con = sqlite3.connect(str(db))
    q = con.execute
    pop = {
        r[0]
        for r in q("SELECT DISTINCT mrn FROM encounter WHERE substr(visit_datetime,1,10) BETWEEN ? AND ?", (start, e))
    }
    born = {
        r[0]: r[1]
        for r in q(
            "SELECT mrn, birth_date FROM patient WHERE death_date IS NULL OR death_date = '' OR death_date > ?", (e,)
        )
    }

    def age(mrn: str) -> int:
        b = date.fromisoformat(born[mrn][:10])
        return end.year - b.year - ((end.month, end.day) < (b.month, b.day))

    s1 = {m for m in pop if m in born and age(m) >= 18}
    gout = {
        r[0]
        for r in q(
            "SELECT DISTINCT mrn FROM diagnosis WHERE (icd10 LIKE 'M10%' OR icd10 LIKE 'M1A%') "
            "AND substr(diag_date,1,10) <= ?",
            (e,),
        )
    }
    s2 = s1 & gout
    bmi: set[str] = set()
    rows = q(
        "SELECT mrn, substr(measure_datetime,1,10), height_cm, weight_kg FROM vital "
        "WHERE height_cm != '' OR weight_kg != '' ORDER BY mrn, measure_datetime"
    ).fetchall()
    last_h: dict[str, float] = {}
    for mrn, d, h, w in rows:
        if h not in (None, ""):
            last_h[mrn] = float(h)
        if w not in (None, "") and start <= d <= e and mrn in last_h and float(w) / (last_h[mrn] / 100) ** 2 >= 27:
            bmi.add(mrn)
    s3 = s2 & bmi
    hi = {
        r[0]
        for r in q(
            "SELECT DISTINCT mrn FROM lab WHERE local_code = 'UA' AND CAST(result_value AS REAL) >= 6.8 "
            "AND substr(sample_datetime,1,10) BETWEEN ? AND ?",
            (start, e),
        )
    }
    mid = {
        r[0]
        for r in q(
            "SELECT DISTINCT mrn FROM lab WHERE local_code = 'UA' AND CAST(result_value AS REAL) >= 6.0 "
            "AND substr(sample_datetime,1,10) BETWEEN ? AND ?",
            (start, e),
        )
    }
    marks = ",".join("?" * len(ULT_ATC))
    ult = {
        r[0]
        for r in q(
            f"SELECT DISTINCT mrn FROM medication WHERE atc IN ({marks}) "
            "AND substr(start_date,1,10) <= ? AND (end_date IS NULL OR end_date = '' "
            "OR substr(end_date,1,10) >= ?)",
            (*ULT_ATC, e, start),
        )
    }
    s4 = s3 & (hi | (mid & ult))
    con.close()
    return {
        "START": len(pop),
        "GZQO-INC-01": len(s1),
        "GZQO-INC-02": len(s2),
        "GZQO-INC-03": len(s3),
        "GZQO-INC-04": len(s4),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=ROOT / "tests/fixtures/synthetic_patients/site-a/cgrd.sqlite")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--lookback", type=int, default=36)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    c = counts(args.db, date.fromisoformat(args.end), args.lookback)
    out = sys.stdout if args.out is None else args.out.open("w", encoding="utf-8", newline="")
    w = csv.writer(out)
    w.writerow(["criterion_id", "manual_n", "manual_definition", "explanation"])
    for k, v in c.items():
        w.writerow([k, v, DEFINITIONS[k], EXPLANATIONS.get(k, "")])
    if args.out:
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
