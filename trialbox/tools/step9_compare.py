"""The step-9 checker: the same patients on the same build, across N SCREEN runs (card INT-S-F).

    python tools/step9_compare.py run1.json run2.json [run3.json ...] [--bound 3] [--out report.json]

A run file holds the SCREEN summary's ``judged_store`` block (``screen_cascade.py``), the row of every patient of the
run, the excluded ones too (the product's own field names: ``pid``, ``tier``, ``criteria[].id / verdict / basis / prov
/ evidence``), and what the run states about itself: ``commit``, ``snapshot``, ``flags["derived.stored_read"]``,
``consent_state`` and ``list_withheld`` (see the card page for the exact shape).

Refused (exit 2, what is missing named): a run that read stored answers (``judged_store.read`` not 0) or does not say;
runs that differ in store state, commit, snapshot, the ``derived.stored_read`` flag or consent state, or lack one of
them; a run that does not say whether its list was withheld.

The rules (the owner's step 9), for every pair of runs:

* (i) no patient leaves the investigator's list (tier ``high`` or ``review``). A verdict may move between pass and
  unknown and a patient between the two tiers, never off the list (or out of the run).
* (ii) no coded verdict (``basis: coded``) differs at all.
* A run whose list was withheld counts as every patient leaving the list: (i) fails.
* (iii) the share of model pairs (patient and criterion with a model call behind them, ``prov`` not empty) whose
  verdict differs is reported with the pairs named, and is at most ``--bound`` percent (3). Exactly the bound passes.

Reported, never gated: the share of differing model verdicts per criterion (a criterion carrying more than half of
the differences is named) and a fourth section: the patients whose tier differs between runs and, where the rows carry
``--note-truth``, per run and criterion the false demotions (the truth says the note does not speak against the
patient, the run says "not met"), the misses (it does, the run did not say "not met") and the "unknown" truths apart.
Without the file it says the harm measure is not available.

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
    if store["on"] and not isinstance(store.get("read"), int):
        raise Refused(
            f"{path.name}: judged_store.read not recorded (the store is on; how many answers it read is missing)"
        )
    flags = doc.get("flags") if isinstance(doc.get("flags"), dict) else {}
    same = {
        "commit": doc.get("commit"),
        "snapshot": doc.get("snapshot"),
        "derived.stored_read": flags.get("derived.stored_read"),
        "consent_state": doc.get("consent_state"),
    }
    missing = [k for k, v in same.items() if v is None]
    if missing:
        raise Refused(f"{path.name}: not recorded: {', '.join(missing)}")
    if not isinstance(doc.get("list_withheld"), bool):
        raise Refused(f"{path.name}: list_withheld not recorded (true or false is missing)")
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
    return {"name": path.name, "store": store, "tiers": tiers, "pairs": pairs, "same": same,
            "withheld": doc["list_withheld"]}  # fmt: skip


def _name(key: tuple[str, str]) -> str:
    return f"{key[0]}/{key[1]}"


def compare_two(a: dict[str, Any], b: dict[str, Any], bound_pct: float) -> dict[str, Any]:
    ta, tb = a["tiers"], b["tiers"]
    if a["withheld"] or b["withheld"]:  # no list was shown: every patient has left it
        left = sorted(set(ta) | set(tb))
    else:
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
    per_crit: dict[str, dict[str, Any]] = {}
    for k in model:
        c = per_crit.setdefault(k[1], {"total": 0, "differing": 0})
        c["total"] += 1
        c["differing"] += _name(k) in set(different)
    for c in per_crit.values():
        c["share"] = round(c["differing"] / c["total"], 4)
    top = next((c for c, v in sorted(per_crit.items()) if different and v["differing"] * 2 > len(different)), None)
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
        "per_criterion": dict(sorted(per_crit.items())),
        "criterion_over_half": top,
        "same_verdict_different_evidence": evidence,
    }


def section4(runs: list[dict[str, Any]], truth: dict[str, dict[str, str]] | None) -> dict[str, Any]:
    """Reported, never gated (thresholds come from a rehearsal run): who changes tier between runs and, given a note
    truth (``--note-truth``: pseudonymous id -> criterion -> yes/no/unknown, as ``tools.scenarios.note_truth`` reads
    it), per run and criterion: the pairs where the truth says the note does not speak against the patient but the run
    says "not met" (a false demotion), the pairs where it does and the run did not say "not met" (missed), and the
    "unknown" truths apart. The truth value that speaks against a patient is ``BLOCKING_TRUTH`` of ``tools.scenarios``
    (an exclusion criterion: yes; an inclusion criterion: no)."""
    pids = sorted(set().union(*(r["tiers"] for r in runs)))
    differ = {p: {r["name"]: r["tiers"].get(p, "-") for r in runs} for p in pids
              if len({r["tiers"].get(p, "-") for r in runs}) > 1}  # fmt: skip
    out: dict[str, Any] = {"tier_differs": differ, "harm": None}
    if truth is None:
        out["harm_note"] = "the harm measure is not available: no --note-truth file was given"
        return out
    from tools.scenarios import BLOCKING_TRUTH

    harm: dict[str, Any] = {}
    for r in runs:
        per: dict[str, dict[str, Any]] = {}
        for pid, said in sorted(truth.items()):
            for c, t in sorted(said.items()):
                if c not in BLOCKING_TRUTH:
                    continue
                d = per.setdefault(c, {"truth_unknown": 0, "not_in_run": 0, "speaks_against": 0, "missed": [],
                                       "does_not_speak_against": 0, "false_demotion": []})  # fmt: skip
                row = r["pairs"].get((pid, c))
                if t == "unknown":
                    d["truth_unknown"] += 1
                elif row is None:
                    d["not_in_run"] += 1
                elif t == BLOCKING_TRUTH[c]:
                    d["speaks_against"] += 1
                    if row["verdict"] != "fail":
                        d["missed"].append(f"{pid}/{c}")
                else:
                    d["does_not_speak_against"] += 1
                    if row["verdict"] == "fail":
                        d["false_demotion"].append(f"{pid}/{c}")
        harm[r["name"]] = per
    out["harm"] = harm
    return out


def compare(
    runs: list[dict[str, Any]], bound_pct: float = 3.0, truth: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    if len(runs) < 2:
        raise Refused("at least two run files are needed")
    states = {r["store"]["on"] for r in runs}
    if len(states) > 1:
        raise Refused(
            "judged-pair store state differs between the runs ("
            + ", ".join(f"{r['name']}: {'on' if r['store']['on'] else 'off'}" for r in runs)
            + "); compare runs with the same state"
        )
    for r in runs:
        if r["store"]["on"] and r["store"]["read"] != 0:
            raise Refused(
                f"{r['name']}: the judged-pair store read {r['store']['read']} answer(s) in this run; "
                "a run that replays stored answers proves nothing (run with the store off, or read 0)"
            )
    for key in runs[0]["same"]:
        vals = {str(r["same"][key]) for r in runs}
        if len(vals) > 1:
            raise Refused(
                f"{key} differs between the runs (" + ", ".join(f"{r['name']}: {r['same'][key]}" for r in runs) + ")"
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
        "section4": section4(runs, truth),
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
        pc = {c: v for c, v in p["per_criterion"].items() if v["differing"]}
        if pc:
            out.append("  per criterion: " + ", ".join(f"{c} {v['differing']}/{v['total']} ({100 * v['share']:.1f} %)"
                                                         for c, v in pc.items()))  # fmt: skip
        if p["criterion_over_half"]:
            out.append(f"  criterion {p['criterion_over_half']} carries more than half of the differences")
    s4 = rep["section4"]
    out.append(f"section 4 (reported, not gated): patients whose tier differs between runs: {len(s4['tier_differs'])}")
    for pid, t in s4["tier_differs"].items():
        out.append(f"  {pid}: " + ", ".join(f"{n} {v}" for n, v in t.items()))
    if s4["harm"] is None:
        out.append(f"  {s4['harm_note']}")
    else:
        for n, per in s4["harm"].items():
            for c, h in per.items():
                out.append(
                    f"  {n} {c}: truth speaks against {h['speaks_against']}, run missed {len(h['missed'])}; "
                    f"truth does not {h['does_not_speak_against']}, false demotions {len(h['false_demotion'])}; "
                    f"truth unknown {h['truth_unknown']}; not in the run {h['not_in_run']}"
                )
                for label, key in (("missed", "missed"), ("false demotion", "false_demotion")):
                    if h[key]:
                        out.append(f"    {label}: {', '.join(h[key])}")
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
    ap.add_argument("--note-truth", type=Path, help="pid -> criterion -> yes/no/unknown, for section 4 (not gated)")
    args = ap.parse_args(argv)
    try:
        truth = json.loads(args.note_truth.read_text(encoding="utf-8")) if args.note_truth else None
        rep = compare([load(p) for p in args.runs], args.bound, truth)
    except (Refused, OSError, ValueError) as e:
        print(f"step9_compare: refused: {e}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(text(rep))
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
