"""The acceptance results table from the proof files (INT-M10 min, item b).

    python -m tools.results_table --proofs DIR --commit SHA [--out FILE]

One row per proof file (``DIR/*.json``, schema :data:`PROOF_SCHEMA`), in criterion order: the two-part acceptance's
criteria (Part 1 SYSTEM, Part 2 RULES AND DATA). A proof file says what was proven and points at its evidence::

    {"schema": "tb-acceptance-proof/1", "criterion": "1a", "title": "...", "result": "green" | "red",
     "evidence": "evidence/1a.json"}

``evidence`` is relative to the proof file. The evidence file is what the run wrote, never typed by hand::

    {"commit": "<40 hex>", "passed": N, "failed": N, "skipped": N, "xfailed": N, "xfail_strict": N}

The table is refused (exit 2, one line per row, no table written) when a row:

* names no evidence, or its evidence file is not there;
* has evidence that names another commit than ``--commit``, or names none;
* says green while its evidence counts a failure, or passed nothing (every test skipped is not a proof).

Every green row carries its skip and strict-xfail counts beside it ("green, 3 skipped, 1 strict xfail") and in their
own columns, so a skipped proof is never read as green. Nothing here reads a clock or calls a service. Standard
library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROOF_SCHEMA = "tb-acceptance-proof/1"
RESULTS = ("green", "red")
COUNTS = ("passed", "failed", "skipped", "xfailed", "xfail_strict")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class Refused(Exception):
    """The table cannot be built: one reason per refused row."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Row:
    criterion: str
    title: str
    result: str
    evidence: str
    counts: dict[str, int]

    def shown(self) -> str:
        """The result as the table shows it: a green carries its skips and strict xfails beside it."""
        extra = []
        if self.counts["skipped"]:
            extra.append(f"{self.counts['skipped']} skipped")
        if self.counts["xfail_strict"]:
            extra.append(f"{self.counts['xfail_strict']} strict xfail")
        return ", ".join([self.result, *extra])


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _row(path: Path, commit: str) -> tuple[Row | None, str | None]:
    try:
        proof = _read_json(path)
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: not a proof file ({exc})"
    if not isinstance(proof, dict) or proof.get("schema") != PROOF_SCHEMA:
        return None, f"{path.name}: not a proof file (schema is not {PROOF_SCHEMA})"
    crit = str(proof.get("criterion") or path.stem)
    result = proof.get("result")
    if result not in RESULTS:
        return None, f"{crit}: result {result!r} is not one of {', '.join(RESULTS)}"
    ev_name = proof.get("evidence")
    if not isinstance(ev_name, str) or not ev_name.strip():
        return None, f"{crit}: the proof names no evidence file"
    ev_path = path.parent / ev_name
    if not ev_path.is_file():
        return None, f"{crit}: no evidence file at {ev_name}"
    try:
        ev = _read_json(ev_path)
    except (OSError, ValueError) as exc:
        return None, f"{crit}: the evidence {ev_name} cannot be read ({exc})"
    if not isinstance(ev, dict):
        return None, f"{crit}: the evidence {ev_name} is not a mapping"
    named = ev.get("commit")
    if not isinstance(named, str) or not named.strip():
        return None, f"{crit}: the evidence {ev_name} names no commit"
    if named.strip().lower() != commit:
        return None, f"{crit}: the evidence {ev_name} names commit {named.strip()}, not {commit}"
    counts: dict[str, int] = {}
    for key in COUNTS:
        val = ev.get(key, 0)
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            return None, f"{crit}: the evidence {ev_name} has no count {key!r} (a whole number)"
        counts[key] = val
    if result == "green" and counts["failed"]:
        return None, f"{crit}: green, but its evidence counts {counts['failed']} failed"
    if result == "green" and not counts["passed"]:
        return None, f"{crit}: green, but its evidence passed nothing ({counts['skipped']} skipped)"
    return Row(crit, str(proof.get("title") or ""), result, ev_name, counts), None


def build(proofs: Path, commit: str) -> list[Row]:
    """Every row of ``proofs``, or :class:`Refused` naming each row that cannot stand."""
    commit = commit.strip().lower()
    if not _SHA.match(commit):
        raise Refused([f"--commit {commit!r} is not a full 40-character commit id"])
    files = sorted(proofs.glob("*.json"))
    if not files:
        raise Refused([f"no proof file in {proofs}"])
    rows: list[Row] = []
    reasons: list[str] = []
    for f in files:
        row, why = _row(f, commit)
        if why:
            reasons.append(why)
        elif row:
            rows.append(row)
    seen: set[str] = set()
    for r in rows:
        if r.criterion in seen:
            reasons.append(f"{r.criterion}: two proof files for one criterion")
        seen.add(r.criterion)
    if reasons:
        raise Refused(reasons)
    return sorted(rows, key=lambda r: r.criterion)


def render(rows: list[Row], commit: str) -> str:
    out = [
        f"# Acceptance results at {commit}",
        "",
        "Written by `tools/results_table.py` from the proof files; do not edit by hand. A green row shows its skipped",
        "and strict-xfail counts beside it.",
        "",
        "| Criterion | Title | Result | Passed | Failed | Skipped | Strict xfail | Evidence |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        c = r.counts
        out.append(
            f"| {r.criterion} | {r.title} | {r.shown()} | {c['passed']} | {c['failed']} | {c['skipped']} "
            f"| {c['xfail_strict']} | `{r.evidence}` |"
        )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--proofs", type=Path, required=True, help="the folder of proof files (*.json)")
    ap.add_argument("--commit", required=True, help="the full commit id every evidence file must name")
    ap.add_argument("--out", type=Path, help="write the table here (default: standard output)")
    args = ap.parse_args(argv)
    try:
        rows = build(args.proofs, args.commit)
    except Refused as exc:
        for reason in exc.reasons:
            print(f"results_table: refused: {reason}", file=sys.stderr)
        return 2
    text = render(rows, args.commit.strip().lower())
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
