"""N-12 from SCREEN: the evidence ``tools/qualify.py``'s ``n12`` step reads (blocker 3 of lane G's first real-model
accuracy run; the split agreed on #639, 2026-11-15).

N-12 is "TREC CT eligible pairs wrongly dropped, unadjusted, at most 5 %" (D-343). It was measured on the benchmark
prompt path (``tools.trec_ct_eval``); it is now read from the product path. Lane G's run (``tools.public_accuracy``)
screens the TREC sets with SCREEN through the gateway and scores them by ids after the run; its score files give, per
language, the eligible pairs the box excluded (``eligible_lost``) and the pairs it never answered. This tool sums the
English eligible pairs of the TREC CT 2021/22 set and writes the evidence:

* ``passed`` / ``ok``: the run left at most :data:`UNANSWERED_SHARE` unanswered (``complete``) and the rate is at
  most :data:`GATE`;
* ``basis: "unadjusted"`` (D-343), ``source: "screen"``, ``head`` (this checkout's HEAD, which the run must match),
  ``models`` (the served builds the run names);
* ``eligible``, ``lost``, ``rate`` with the exact (Clopper-Pearson) 95 % interval and one-sided upper bound;
* ``unanswered`` and ``open`` (pairs left to a person), ``sets`` and ``inputs`` (each file's name and sha256).

It is no evidence (:class:`NoEvidence`, exit 2) unless each file carries a ``run`` block from a real run at this
HEAD (``head``, ``models``, ``stub: false``), names the TREC set once, holds whole counts that add up per row, and the
files reach :data:`MIN_ELIGIBLE` eligible pairs (review of D-791: a stand-in run, a file given twice, three pairs).

    python -m tools.n12_screen <score.json> [<score.json> ...] --out n12.json   # exit 0 when it passes

Nothing here reads a model or a patient: the score files hold counts only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: the N-12 gate (D-343, docs/VALIDATION.md §3): eligible pairs wrongly dropped, unadjusted, the point estimate
GATE = 0.05
#: a run that left more than this share of the eligible pairs unanswered fails
UNANSWERED_SHARE = 0.10
#: fewer eligible pairs than this is no evidence: at a 5 % rate, 400 pairs put the exact 95 % interval within about
#: ±2.2 points (the 2026-11-08 baseline had 1,700); three pairs with none lost passed before (review of D-791)
MIN_ELIGIBLE = 400
#: the sets N-12 is measured on: TREC CT 2021/22 (D-343), one ``score.json`` named ``trec`` in lane G's run; another
#: set (``trec2023``: today's ClinicalTrials.gov criteria) needs its own decision
SETS = frozenset({"trec"})
CELLS = ("excluded", "listed", "open", "unanswered")
ROOT = Path(__file__).resolve().parents[1]


class NoEvidence(ValueError):
    """The score files are no N-12 evidence, and the sentence says why."""


def git_head() -> str:
    """This checkout's HEAD (the repository of this file, whatever the caller's folder), or ""."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
        )
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _count(row: dict[str, Any], key: str, where: str) -> int:
    v = row.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise NoEvidence(f"{where}: {key!r} is {v!r}, not a whole number of pairs")
    return v


def _run_of(doc: dict[str, Any], where: str, head: str) -> dict[str, Any]:
    run = doc.get("run")
    if not isinstance(run, dict):
        raise NoEvidence(f"{where} has no run block (head, models, stub): which run it scores cannot be told")
    if run.get("stub") is not False:
        raise NoEvidence(f"{where} scores a stand-in run (stub), not the real models: no accuracy result")
    models = run.get("models")
    if not isinstance(models, dict) or not models or not all(isinstance(v, str) and v for v in models.values()):
        raise NoEvidence(f"{where}: the run block names no served models")
    if not head or run.get("head") != head:
        raise NoEvidence(f"{where} was run at {run.get('head')!r}, not this checkout's HEAD {head!r}")
    return run


def evidence(files: Sequence[Path], head: str) -> dict[str, Any]:
    """The N-12 evidence from lane G's score files; :class:`NoEvidence` when they are none."""
    from tools.accuracy_set import exact_upper

    sets: list[str] = []
    shas: set[str] = set()
    inputs: list[dict[str, str]] = []
    models: dict[str, str] = {}
    lost = eligible = unanswered = opened = 0
    for f in files:
        where = Path(f).name
        raw = Path(f).read_bytes()
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise NoEvidence(f"{where} is not JSON ({exc})") from exc
        if not isinstance(doc, dict):
            raise NoEvidence(f"{where} is not a score file (no object at its top)")
        name = str(doc.get("set") or "")
        if name not in SETS:
            raise NoEvidence(f"{where} scores set {name!r}: N-12 is measured on the TREC CT 2021/22 set ('trec')")
        sha = hashlib.sha256(raw).hexdigest()
        if name in sets or sha in shas:
            raise NoEvidence(f"{where}: set {name!r} is given twice; each set counts once")
        run = _run_of(doc, where, head)
        rows = (doc.get("pairs") or {}).get("rows") if isinstance(doc.get("pairs"), dict) else None
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise NoEvidence(f"{where} has no pair rows")
        for r in rows:
            if r.get("gold") != "eligible" or r.get("lang") != "en":
                continue
            n = _count(r, "n", where)
            cells = {k: _count(r, k, where) for k in CELLS}
            if sum(cells.values()) != n:
                raise NoEvidence(f"{where}: a row's cells add up to {sum(cells.values())}, not its n {n}")
            eligible += n
            lost += cells["excluded"]
            unanswered += cells["unanswered"]
            opened += cells["open"]
        sets.append(name)
        shas.add(sha)
        inputs.append({"file": where, "sha256": sha})
        models.update({str(k): str(v) for k, v in run["models"].items()})
    if eligible < MIN_ELIGIBLE:
        raise NoEvidence(f"{eligible} English TREC eligible pairs: N-12 needs at least {MIN_ELIGIBLE}")
    rate = lost / eligible
    complete = unanswered / eligible <= UNANSWERED_SHARE
    lo, hi = _clopper_pearson(lost, eligible)
    passed = complete and rate <= GATE
    return {
        "step": "n12",
        "source": "screen",
        "basis": "unadjusted",
        "head": head,
        "models": models,
        "passed": passed,
        "ok": passed,
        "gate": GATE,
        "sets": sets,
        "eligible": eligible,
        "lost": lost,
        "rate": round(rate, 6),
        "ci95": [round(lo, 6), round(hi, 6)],
        "upper95": round(exact_upper(lost, eligible), 6),
        "answered": eligible - unanswered,
        "unanswered": {"k": unanswered, "n": eligible},
        "open": {"k": opened, "n": eligible},
        "complete": complete,
        "inputs": inputs,
    }


def _clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """The exact two-sided interval, as lane G's scorer and docs/VALIDATION.md report it."""
    from tools.accuracy_set import _binom_cdf

    def solve(below: Any) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if below(mid) else (lo, mid)
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda p: 1 - _binom_cdf(k - 1, n, p) < alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: _binom_cdf(k, n, p) > alpha / 2)
    return lower, upper


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.n12_screen", description=__doc__.split("\n\n")[0])
    ap.add_argument("scores", nargs="+", type=Path, help="lane G's score files (tools.public_accuracy)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        ev = evidence(a.scores, git_head())
    except NoEvidence as exc:
        print(f"n12_screen: no evidence: {exc}", file=sys.stderr)
        return 2
    a.out.write_text(json.dumps(ev, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: ev[k] for k in ("passed", "rate", "eligible", "lost", "complete", "sets")}))
    return 0 if ev["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
