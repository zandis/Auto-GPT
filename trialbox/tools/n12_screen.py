"""N-12 from SCREEN: the evidence ``tools/qualify.py``'s ``n12`` step reads (blocker 3 of lane G's first real-model
accuracy run; the split agreed on #639, 2026-11-15).

N-12 is "TREC CT eligible pairs wrongly dropped, unadjusted, at most 5 %" (D-343). It was measured on the benchmark
prompt path (``tools.trec_ct_eval``); it is now read from the product path. Lane G's run (``tools.public_accuracy``)
screens the TREC sets with SCREEN through the gateway and scores them by ids after the run; its score files give, per
language, the eligible pairs the box excluded (``eligible_lost``) and the pairs it never answered. This tool sums the
English TREC sets of those files and writes the evidence:

* ``passed`` / ``ok``: the run answered enough (``complete``) and the rate is at most :data:`GATE`;
* ``basis: "unadjusted"`` (D-343), ``source: "screen"``, ``head`` (this checkout's git HEAD, as ``qualify`` checks);
* ``eligible``, ``lost``, ``rate`` with a Wilson 95 % interval and the exact one-sided 95 % upper bound;
* ``unanswered``: eligible pairs SCREEN never answered. More than :data:`UNANSWERED_SHARE` of them and the file is no
  evidence (``complete: false``): a box that answered nothing would otherwise show 0 lost;
* ``sets`` and ``inputs`` (each score file's name and sha256).

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

#: the N-12 gate (D-343, docs/VALIDATION.md §3): eligible pairs wrongly dropped, unadjusted
GATE = 0.05
#: a run that left more than this share of the eligible pairs unanswered is no evidence
UNANSWERED_SHARE = 0.10
TREC_PREFIX = "trec"


class NoEvidence(ValueError):
    """The score files hold no English TREC pairs."""


def git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30, check=False)
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _eligible_rows(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (doc.get("pairs") or {}).get("rows") or []
    return [r for r in rows if r.get("gold") == "eligible" and r.get("lang") == "en"]


def evidence(files: Sequence[Path], head: str) -> dict[str, Any]:
    """The N-12 evidence from lane G's score files (only English TREC sets count)."""
    from deliverables.analytics import wilson

    from tools.accuracy_set import exact_upper

    sets: list[str] = []
    inputs: list[dict[str, str]] = []
    lost = eligible = unanswered = 0
    for f in files:
        raw = Path(f).read_bytes()
        doc = json.loads(raw)
        name = str(doc.get("set") or "")
        if not name.lower().startswith(TREC_PREFIX):
            continue
        rows = _eligible_rows(doc)
        if not rows:
            continue
        sets.append(name)
        inputs.append({"file": Path(f).name, "sha256": hashlib.sha256(raw).hexdigest()})
        for r in rows:
            eligible += int(r.get("n") or 0)
            lost += int(r.get("excluded") or 0)
            unanswered += int(r.get("unanswered") or 0)
    if not eligible:
        raise NoEvidence("no English TREC eligible pairs in the score files: N-12 is measured on the TREC CT sets")
    answered = eligible - unanswered
    rate = lost / eligible
    complete = unanswered / eligible <= UNANSWERED_SHARE
    lo, hi = wilson(lost, eligible)
    passed = complete and rate <= GATE
    return {
        "step": "n12",
        "source": "screen",
        "basis": "unadjusted",
        "head": head,
        "passed": passed,
        "ok": passed,
        "gate": GATE,
        "sets": sets,
        "eligible": eligible,
        "lost": lost,
        "rate": round(rate, 6),
        "ci95": [round(lo, 6), round(hi, 6)],
        "upper95": round(exact_upper(lost, eligible), 6),
        "answered": answered,
        "unanswered": {"k": unanswered, "n": eligible},
        "complete": complete,
        "inputs": inputs,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.n12_screen", description=__doc__.split("\n\n")[0])
    ap.add_argument("scores", nargs="+", type=Path, help="lane G's score files (tools.public_accuracy)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    ev = evidence(a.scores, git_head())
    a.out.write_text(json.dumps(ev, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: ev[k] for k in ("passed", "rate", "eligible", "lost", "complete", "sets")}))
    return 0 if ev["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
