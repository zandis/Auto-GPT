"""Manual-vs-system funnel comparison (SPEC §11.2 FEAS acceptance: each step within ±15 % of the manual CGRD count and
every difference explained by a documented definition choice).

    python tools/funnel_compare.py --system feasibility_GZQO_v1.0.0_<snap>.raw.json --manual manual_counts.csv \
        [--tolerance 15] [--out report.md]

``--system`` is the unsuppressed ``*.raw.json`` the FEAS job keeps inside the box (or a ``feasibility_result`` JSON,
whose suppressed cells cannot be compared). ``--manual`` is a CSV with columns
``criterion_id, manual_n, manual_definition, explanation`` (``START`` for the population row). Exit status 0 when
every compared step passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Row:
    criterion_id: str
    system: int | None
    manual: int
    diff_pct: float | None
    explanation: str
    definition: str
    status: str  # ok | unexplained | out_of_tolerance | missing


def system_counts(body: dict[str, Any]) -> dict[str, int]:
    if "remaining" in body and isinstance(body["remaining"], dict):  # raw.json
        out = {k: int(v) for k, v in body["remaining"].items()}
        out["START"] = int(body["start_n"])
        return out
    out = {f["criterion_id"]: f["remaining"] for f in body.get("funnel", []) if isinstance(f.get("remaining"), int)}
    if isinstance(body.get("start_n"), int):
        out["START"] = body["start_n"]
    return out


def compare(system: dict[str, int], manual_rows: list[dict[str, str]], tolerance: float = 15.0) -> list[Row]:
    rows: list[Row] = []
    for m in manual_rows:
        cid = m["criterion_id"].strip()
        man = int(m["manual_n"])
        sysn = system.get(cid)
        expl = (m.get("explanation") or "").strip()
        definition = (m.get("manual_definition") or "").strip()
        if sysn is None:
            rows.append(Row(cid, None, man, None, expl, definition, "missing"))
            continue
        diff = 0.0 if sysn == man else (100.0 * (sysn - man) / man if man else float("inf"))
        if abs(diff) > tolerance:
            status = "out_of_tolerance"
        elif diff != 0 and not expl:
            status = "unexplained"
        else:
            status = "ok"
        rows.append(Row(cid, sysn, man, round(diff, 1), expl, definition, status))
    return rows


def markdown(rows: list[Row], tolerance: float) -> str:
    lines = [
        f"| step | system | manual | diff % | status (±{tolerance:g} %) | manual definition | explanation |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for r in rows:
        diff = "—" if r.diff_pct is None else f"{r.diff_pct:+.1f}"
        sysn = "—" if r.system is None else str(r.system)
        lines.append(
            f"| {r.criterion_id} | {sysn} | {r.manual} | {diff} | {r.status} | {r.definition} | {r.explanation} |"
        )
    ok = all(r.status == "ok" for r in rows)
    lines += [
        "",
        f"**Result: {'PASS' if ok else 'FAIL'}** ({sum(r.status == 'ok' for r in rows)}/{len(rows)} steps ok)",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", type=Path, required=True)
    ap.add_argument("--manual", type=Path, required=True)
    ap.add_argument("--tolerance", type=float, default=15.0)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    system = system_counts(json.loads(args.system.read_text(encoding="utf-8")))
    with args.manual.open(encoding="utf-8") as fh:
        manual = list(csv.DictReader(fh))
    rows = compare(system, manual, args.tolerance)
    report = markdown(rows, args.tolerance)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0 if all(r.status == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
