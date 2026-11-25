"""The step-9 checker: the same patients on the same build, across N SCREEN runs (card INT-S-F).

    python tools/step9_compare.py run1.json run2.json [run3.json ...] [--bound 3] [--out report.json]

A run file is ``{"judged_store": {"on": true, "read": 0, "live": 12}, "rows": [<CandidateRow>, ...]}``: the SCREEN
summary's ``judged_store`` block (``screen_cascade.py``) and the row of every patient of the run, the excluded ones
too (the product's own field names: ``pid``, ``tier``, ``criteria[].id / verdict / basis / prov / evidence``).

The rules (the owner's step 9), for every pair of runs:

* (i) no patient leaves the investigator's list (tier ``high`` or ``review``). A verdict may move between pass and
  unknown and a patient between the two tiers, never off the list (or out of the run).
* (ii) no coded verdict (``basis: coded``) differs at all.
* (iii) the share of model pairs (patient and criterion with a model call behind them, ``prov`` not empty) whose
  verdict differs is reported with the pairs named, and is at most ``--bound`` percent (3). Exactly the bound passes.

Reported, never failed: "same verdict, different evidence" (the note reference or the quote date differs). The state
of the judged-pair store of each run is printed; runs whose state differs, or whose file does not record it, are
refused. Exit 0 when every rule holds, 1 when one fails, 2 when the runs cannot be compared.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

LISTED = ("high", "review")


class Refused(Exception):
    """The runs cannot be compared; the message says why."""


def load(path: Path) -> dict[str, Any]:
    """One run file, reduced to what the rules read; ``Refused`` when the store state is not recorded."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Refused(f"{path.name}: cannot read the run file ({type(e).__name__})") from e
    store = doc.get("judged_store") if isinstance(doc, dict) else None
    if not isinstance(store, dict):
        raise Refused(f"{path.name}: judged_store not recorded (the summary's judged_store block is missing)")
    if not isinstance(store.get("on"), bool):
        raise Refused(f"{path.name}: judged_store.on not recorded (true or false is missing)")
    if not isinstance(doc.get("rows"), list):
        raise Refused(f"{path.name}: rows missing (every patient's row, the excluded ones too)")
    tiers: dict[str, str] = {}
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for r in doc["rows"]:
        pid = str(r["pid"])
        tiers[pid] = str(r.get("tier"))
        for c in r.get("criteria") or []:
            ev = c.get("evidence") or {}
            pairs[(pid, str(c["id"]))] = {
                "verdict": str(c.get("verdict")),
                "coded": c.get("basis") == "coded",
                "model": bool(c.get("prov")),
                "evidence": (tuple(sorted(ev.get("resource_refs") or [])), ev.get("quote_date")),
            }
    return {"name": path.name, "store": store, "tiers": tiers, "pairs": pairs}


def _name(key: tuple[str, str]) -> str:
    return f"{key[0]}/{key[1]}"


def compare_two(a: dict[str, Any], b: dict[str, Any], bound_pct: float) -> dict[str, Any]:
    ta, tb = a["tiers"], b["tiers"]
    left = sorted(p for p in set(ta) | set(tb) if (ta.get(p) in LISTED) != (tb.get(p) in LISTED))
    moves = sorted(p for p in set(ta) & set(tb) if ta[p] in LISTED and tb[p] in LISTED and ta[p] != tb[p])
    pa, pb = a["pairs"], b["pairs"]
    keys = sorted(set(pa) | set(pb))
    coded, model, different, evidence = [], [], [], []  # coded: ii; model: the iii denominator; different: iii
    for k in keys:
        x, y = pa.get(k), pb.get(k)
        if (x and x["coded"]) or (y and y["coded"]):
            if not (x and y and x["coded"] and y["coded"] and x["verdict"] == y["verdict"]):
                coded.append(_name(k))
            continue
        if (x and x["model"]) or (y and y["model"]):
            model.append(k)
            if not (x and y) or x["verdict"] != y["verdict"]:
                different.append(_name(k))
            elif x["evidence"] != y["evidence"]:
                evidence.append(_name(k))
    share = len(different) / len(model) if model else 0.0
    within = len(different) * 100 <= bound_pct * len(model)  # integers: exactly the bound passes
    return {
        "runs": [a["name"], b["name"]],
        "left_list": left,
        "tier_moves": moves,
        "coded_differing": coded,
        "model_total": len(model),
        "model_differing": different,
        "model_share": round(share, 4),
        "within_bound": within,
        "same_verdict_different_evidence": evidence,
    }


def compare(runs: list[dict[str, Any]], bound_pct: float = 3.0) -> dict[str, Any]:
    if len(runs) < 2:
        raise Refused("at least two run files are needed")
    states = {r["store"]["on"] for r in runs}
    if len(states) > 1:
        raise Refused(
            "judged-pair store state differs between the runs ("
            + ", ".join(f"{r['name']}: {'on' if r['store']['on'] else 'off'}" for r in runs)
            + "); compare runs with the same state"
        )
    pairs = [compare_two(a, b, bound_pct) for a, b in combinations(runs, 2)]
    rules = {
        "i_list": not any(p["left_list"] for p in pairs),
        "ii_coded": not any(p["coded_differing"] for p in pairs),
        "iii_share": all(p["within_bound"] for p in pairs),
    }
    return {
        "bound_pct": bound_pct,
        "stores": {r["name"]: r["store"] for r in runs},
        "rules": rules,
        "pass": all(rules.values()),
        "pairs": pairs,
    }


def text(rep: dict[str, Any]) -> str:
    out = []
    for name, s in rep["stores"].items():
        out.append(
            f"{name}: judged-pair store: {'on' if s['on'] else 'off'} (read {s.get('read')}, live {s.get('live')})"
        )
    for p in rep["pairs"]:
        a, b = p["runs"]
        out.append(
            f"{a} vs {b}: left the list {len(p['left_list'])}; tier moves {len(p['tier_moves'])}; "
            f"coded verdicts differing {len(p['coded_differing'])}; model verdicts differing "
            f"{len(p['model_differing'])} of {p['model_total']} ({100 * p['model_share']:.2f} %, bound "
            f"{rep['bound_pct']:g} %); same verdict, different evidence {len(p['same_verdict_different_evidence'])}"
        )
        for label, key in (("left the list", "left_list"), ("coded differing", "coded_differing"),
                           ("model differing", "model_differing")):  # fmt: skip
            if p[key]:
                out.append(f"  {label}: {', '.join(p[key])}")
    r = rep["rules"]
    out.append(
        f"(i) list {'ok' if r['i_list'] else 'FAIL'}; (ii) coded {'ok' if r['ii_coded'] else 'FAIL'}; "
        f"(iii) share {'ok' if r['iii_share'] else 'FAIL'}: {'PASS' if rep['pass'] else 'FAIL'}"
    )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", type=Path, help="the run result files, two or more")
    ap.add_argument("--bound", type=float, default=3.0, help="the most percent of model verdicts that may differ")
    ap.add_argument("--out", type=Path, help="write the report as JSON")
    args = ap.parse_args(argv)
    try:
        rep = compare([load(p) for p in args.runs], args.bound)
    except Refused as e:
        print(f"step9_compare: refused: {e}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(text(rep))
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
