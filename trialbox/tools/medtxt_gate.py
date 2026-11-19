"""The MedTxt Japanese pair gate (card 10G-22, D-1325): a standing gate for any model, prompt or quantisation change.

Scores a judge + verifier pair on its **recorded** answers (``eval/medtxt/results/raw/<model>__ja.jsonl.gz``, written
by ``python -m tools.medtxt_eval run``) against the committed answer key (``eval/medtxt/key.json``: annotation id ->
certainty, no report text) and holds it to review 17 §7.3 rules 1 and 2 against the control pair, on the same items:

1. stated-absent findings blocked by both (``negative``): not higher than the control's by more than 1 point, and
   the Wilson 95 % upper bound under 15 %;
2. present findings blocked by both (``positive``): at least the control's.

And, because an unanswered item is never a block (so a broken build would look safe on rule 1), the candidate
answers every item of the key and leaves no more items unanswered (an error or no record) than the control.

No model is called, nothing is fetched: the gate reads files in the tree. ``eval/medtxt/gate.json`` names the control
and the candidate (today the same, the shipped pair as recorded). A change of model, prompt or quantisation records
the new pair's answers with ``medtxt_eval run`` and names it as the candidate; the guard test
``tests/unit/test_medtxt_pair_gate.py`` then fails CI while the candidate fails the gate.

    python -m tools.medtxt_gate check [--judge M --verifier M] [--raw DIR]   # exit 1 when the gate fails
    python -m tools.medtxt_gate key        # rebuild eval/medtxt/key.json from the fetched corpus (.cache/medtxt)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from tools.mlbench import BLOCKS
from tools.trec_ct_eval import wilson
from tools.trialgpt_compare import _safe

ROOT = Path(__file__).resolve().parents[1]
MEDTXT = ROOT / "eval" / "medtxt"
KEY = MEDTXT / "key.json"
GATE = MEDTXT / "gate.json"
RAW = MEDTXT / "results" / "raw"
LANG = "ja"
# D-1325, from review 17 §7.3 (the decision rule written before the run)
NEGATED_TOLERANCE = 0.01  # rule 1: not higher than the control's by more than 1 point
NEGATED_UPPER_BOUND_BELOW = 0.15  # rule 1: and its 95 % upper bound under 15 %


def raw_file(model: str, raw: Path = RAW) -> Path:
    return raw / f"{_safe(model)}__{LANG}.jsonl.gz"


def load_key(path: Path = KEY) -> dict[str, str]:
    return dict(json.loads(path.read_text(encoding="utf-8"))["items"])


def load_answers(model: str, raw: Path = RAW) -> dict[str, dict[str, Any]]:
    f = raw_file(model, raw)
    if not f.exists():
        raise SystemExit(f"medtxt gate: no recorded answers for {model} ({f})")
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        return {r["annotation_id"]: r for r in map(json.loads, fh)}


def score_pair(judge: str, verifier: str, key: dict[str, str], raw: Path = RAW) -> dict[str, Any]:
    """Both-must-block rates per certainty over the key's items, the items with no record, and those unanswered."""
    ans = [load_answers(judge, raw), load_answers(verifier, raw)]
    blocked: dict[str, list[int]] = {}
    missing = unanswered = 0
    for aid, certainty in sorted(key.items()):
        rs = [a.get(aid) for a in ans]
        missing += sum(1 for r in rs if r is None)
        unanswered += sum(1 for r in rs if not r or r.get("error"))
        blk = all(r is not None and (r.get("label") or "") in BLOCKS for r in rs)
        kn = blocked.setdefault(certainty, [0, 0])
        kn[0] += int(blk)
        kn[1] += 1
    rates = {c: {"blocked": k, "n": n, "rate": k / n if n else 0.0, "wilson95": list(wilson(k, n))}
             for c, (k, n) in sorted(blocked.items())}  # fmt: skip
    return {"judge": judge, "verifier": verifier, "lang": LANG, "items": len(key), "missing": missing,
            "unanswered": unanswered, "rates": rates}  # fmt: skip


def verdict(cand: dict[str, Any], ctrl: dict[str, Any]) -> dict[str, Any]:
    """Rules 1 and 2 of review 17 §7.3 and the same-items rule; ``passed`` with every failing rule named."""
    cn, kn = cand["rates"]["negative"], ctrl["rates"]["negative"]
    cp, kp = cand["rates"]["positive"], ctrl["rates"]["positive"]
    fails: list[str] = []
    if cand["missing"]:
        fails.append(f"not the same items: {cand['missing']} answers of the key's {cand['items']} items not recorded")
    if cand["unanswered"] > ctrl["unanswered"]:
        fails.append(f"unanswered {cand['unanswered']} > the control's {ctrl['unanswered']}")
    if cn["rate"] > kn["rate"] + NEGATED_TOLERANCE + 1e-12:
        fails.append(f"rule 1: stated-absent blocked {cn['rate']:.3f} ({cn['blocked']}/{cn['n']}) > the control's "
                     f"{kn['rate']:.3f} + {NEGATED_TOLERANCE:.2f}")  # fmt: skip
    if cn["wilson95"][1] >= NEGATED_UPPER_BOUND_BELOW:
        fails.append(f"rule 1: stated-absent blocked 95 % upper bound {cn['wilson95'][1]:.3f} not under "
                     f"{NEGATED_UPPER_BOUND_BELOW:.2f}")  # fmt: skip
    if cp["rate"] < kp["rate"] - 1e-12:
        fails.append(f"rule 2: present blocked {cp['rate']:.3f} ({cp['blocked']}/{cp['n']}) < the control's "
                     f"{kp['rate']:.3f}")  # fmt: skip
    return {"passed": not fails, "fails": fails, "candidate": cand, "control": ctrl,
            "rule": "D-1325 (review 17 §7.3 rules 1 and 2)"}  # fmt: skip


def gate(
    judge: str | None = None, verifier: str | None = None, raw: Path = RAW, gate_file: Path = GATE, key_file: Path = KEY
) -> dict[str, Any]:
    g = json.loads(gate_file.read_text(encoding="utf-8"))
    key = load_key(key_file)
    ctrl = score_pair(g["control"]["judge"], g["control"]["verifier"], key)  # the control is always the tree's record
    cand = score_pair(judge or g["candidate"]["judge"], verifier or g["candidate"]["verifier"], key, raw)
    return verdict(cand, ctrl)


def build_key() -> dict[str, Any]:
    """The answer key from the fetched corpus (``python -m tools.medtxt_eval fetch`` first): ids and certainty only."""
    from tools import medtxt_eval as m

    items, _ = m.dataset()
    shas = {}
    for files in m.FILES.values():
        for f in files:
            for lang in m.LANGS:
                p = m.CACHE / "Test collection" / f.format(L=lang.upper())
                shas[f.format(L=lang.upper())] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {
        "what": "MedTxt answer key of tools/medtxt_eval.dataset(): annotation id -> the tag's certainty; no text",
        "source": "NTCIR-16 Real-MedNLP test collection, Sociocom NAIST (MedTxt-CR training split, MedTxt-RR)",
        "licence": "CC BY 4.0",
        "corpus_sha256": dict(sorted(shas.items())),
        "items": {it["id"]: it["certainty"] for it in items},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="medtxt_gate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--judge")
    c.add_argument("--verifier")
    c.add_argument("--raw", type=Path, default=RAW)
    sub.add_parser("key")
    a = ap.parse_args(argv)
    if a.cmd == "key":
        KEY.write_text(json.dumps(build_key(), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        return 0
    v = gate(a.judge, a.verifier, a.raw)
    for name in ("control", "candidate"):
        s = v[name]
        r = s["rates"]
        print(f"{name}: {s['judge']} + {s['verifier']} ({LANG}): present blocked {r['positive']['rate']:.3f}, "
              f"stated absent blocked {r['negative']['rate']:.3f} (95 % UB {r['negative']['wilson95'][1]:.3f}), "
              f"unanswered {s['unanswered']}, missing {s['missing']}")  # fmt: skip
    print("medtxt gate: " + ("passed" if v["passed"] else "FAILED: " + "; ".join(v["fails"])))
    return 0 if v["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
