"""M8 (R1-P2, R1-N1): the timing record of a screening and the bench rows of the speed line.

The per-stage clock is #1451's (``tools.chart_times``, ``cascade_timing_<study>_v<n>.json``); this module only turns a
run's seconds into the record the spec asks for (stage, seconds, rows, patients) and into the rows the bench proof
carries, so the figures of ``tools/speed_50k.sh`` are made by one function a test holds. Counts and seconds only.

    python -m tools.speed_rows --timing cascade_timing_X_v1.json --patients 50000 --peak-gb 31.2 --equal-to-night PASS
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TOLERANCE = 0.05  # the record explains the wall time when what it leaves out is at most this share (acceptance 4)
REST = "unaccounted"  # the wall time no stage names; a stage of its own, so the record always adds up


def timing_record(wall: float, stages: Mapping[str, Mapping[str, Any]], patients: int) -> list[dict[str, Any]]:
    """The record: one row per stage (``seconds``, ``rows`` when the stage counted some, ``patients``) and the rest of
    the wall time as ``unaccounted``, so that the rows add up to ``wall`` (never negative: a stage clock that ran past
    the wall is a fault of the clock, the row is then 0 and :func:`explains_wall` is False)."""
    # patients_in is the real schema of engine.timing_doc
    rows = [
        {
            "stage": name,
            "seconds": float(v["seconds"]),
            "rows": v.get("rows"),
            "patients": v.get("patients_in", patients),
        }
        for name, v in stages.items()
        if name != REST
    ]
    rest = wall - sum(r["seconds"] for r in rows)
    return [*rows, {"stage": REST, "seconds": round(max(rest, 0.0), 3), "rows": None, "patients": patients}]


def explains_wall(rows: list[dict[str, Any]], wall: float, tol: float = TOLERANCE) -> bool:
    """Acceptance 4: the named stages sum to the wall time within ``tol`` (the stages plus ``unaccounted`` are always
    the wall; what is tested is that ``unaccounted`` is small and that no stage ran past the wall)."""
    named = sum(r["seconds"] for r in rows if r["stage"] != REST)
    return wall > 0 and abs(wall - named) <= tol * wall


def largest(rows: list[dict[str, Any]]) -> tuple[str, float]:
    """The largest named stage and its share of the rows' total, in percent: the step-2 decision's row."""
    named = [r for r in rows if r["stage"] != REST]
    total = sum(r["seconds"] for r in rows)
    if not named or total <= 0:
        return "unknown", 0.0
    top = max(named, key=lambda r: r["seconds"])
    return str(top["stage"]), round(100 * top["seconds"] / total, 1)


def bench_rows(
    ruleset: str, wall: float, patients: int, peak_gb: float | None, equal: str, rows: list[dict[str, Any]]
) -> list[str]:
    """The bench proof's lines for one ruleset (spec M8): seconds, seconds per 1,000 patients, memory, equality with
    the night, and the largest stage. A figure that was not measured is ``unknown``, never a number."""
    per = round(wall * 1000 / patients, 1) if patients > 0 and wall > 0 else "unknown"
    name, share = largest(rows)
    return [
        f"{ruleset}\tscreen_now_seconds={round(wall, 1)}",
        f"{ruleset}\tper_1000_patients_seconds={per}",
        f"{ruleset}\tpeak_memory_gb={'unknown' if peak_gb is None else round(peak_gb, 1)}",
        f"{ruleset}\tequal_to_night={equal}",
        f"{ruleset}\tlargest_stage={name} share={share}",
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--timing", type=Path, help="cascade_timing_<study>_v<n>.json (screen.timing on)")
    ap.add_argument("--wall", type=float, help="the job's wall seconds (with --timing: not the stage clock's total)")
    ap.add_argument("--ruleset", default="?", help="the study, when there is no timing file")
    ap.add_argument("--patients", type=int, required=True)
    ap.add_argument("--peak-gb", type=float)
    ap.add_argument("--equal-to-night", default="unknown", choices=["PASS", "FAIL", "unknown"])
    a = ap.parse_args(argv)
    if a.timing is not None:
        doc = json.loads(a.timing.read_text(encoding="utf-8"))
        wall = a.wall if a.wall is not None else float(doc["wall_seconds"])  # the job's wall, when given
        ruleset = str(doc.get("ruleset", a.ruleset))
        rows = timing_record(wall, doc["stages"], a.patients)
    elif a.wall is not None:
        wall, ruleset, rows = a.wall, a.ruleset, []  # no stage clock: the largest stage is "unknown", not guessed
    else:
        ap.error("give --timing or --wall")
    print("\n".join(bench_rows(ruleset, wall, a.patients, a.peak_gb, a.equal_to_night, rows)))
    print(json.dumps({"explains_wall": explains_wall(rows, wall), "record": rows}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
