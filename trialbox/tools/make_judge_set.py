"""Build the labelled ``judge`` test set (SPEC §11.1 LLM layer: 300 (excerpt, criterion, verdict) triples) from the
synthetic sites: excerpts = the patient's notes inside the criterion's window at the reference date (newest first,
≤ 28k tokens, i.e. the full-record path), gold = planted note truth (yes/no/unknown -> pass/fail/unknown).

    python tools/make_judge_set.py [--out tests/fixtures/llm/judge_set.jsonl]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "tests" / "fixtures" / "synthetic_patients"
GOLD = {"yes": "pass", "no": "fail", "unknown": "unknown"}
PER_CRITERION = 100
CRITERIA: dict[str, dict[str, object]] = {
    "GZQO-INC-05": {"window": 365},
    "GZQO-EXC-11": {"window": 14},
    "RA-BIO-REN-02": {
        "window": 180,
        "text": "Good response to the current biologic at renewal: DAS28 decreased by at least 1.2 (or to ≤ 3.2).",
        "note_question": "Do the clinical notes document a good treatment response (DAS28 improvement of at least "
        "1.2) to the current biologic?",
    },
}


def criterion_meta(cid: str) -> dict[str, object]:
    meta = dict(CRITERIA[cid])
    path = ROOT / "rulesets" / cid.rsplit("-", 2)[0] / "ir" / f"{cid}.json"
    if path.exists():
        ir = json.loads(path.read_text(encoding="utf-8"))
        meta.setdefault("text", ir["text"])
        meta.setdefault("note_question", ir.get("note_question") or ir["text"])
    return meta


def build(seed: int = 7) -> list[dict[str, object]]:
    items: dict[str, list[dict[str, object]]] = defaultdict(list)
    for site in sorted(p for p in SYNTH.glob("site-*") if p.is_dir()):
        ref = date.fromisoformat(json.loads((site / "meta.json").read_text())["ref_date"])
        truth = json.loads((site / "note_truth.json").read_text(encoding="utf-8"))
        notes: dict[str, list[dict[str, str]]] = defaultdict(list)
        with (site / "note.csv").open(encoding="utf-8") as fh:
            for n in csv.DictReader(fh):
                notes[n["mrn"]].append(n)
        for mrn, crits in sorted(truth.items()):
            for cid, gold in sorted(crits.items()):
                if cid not in CRITERIA:
                    continue
                meta = criterion_meta(cid)
                lo = ref - timedelta(days=int(meta["window"]))  # type: ignore[call-overload]
                ex = sorted(
                    (n for n in notes[mrn] if lo.isoformat() <= n["note_datetime"][:10] <= ref.isoformat()),
                    key=lambda n: (n["note_datetime"], n["note_no"]),
                    reverse=True,
                )
                items[cid].append(
                    {
                        "id": f"{site.name}:{mrn}:{cid}",
                        "criterion_id": cid,
                        "criterion_text": meta["text"],
                        "note_question": meta["note_question"],
                        "index_date": ref.isoformat(),
                        "excerpts": [
                            {"date": n["note_datetime"][:10], "note_type": n["note_type"], "text": n["text"]}
                            for n in ex
                        ],
                        "gold": GOLD[gold],
                    }
                )
    rng = random.Random(seed)
    out: list[dict[str, object]] = []
    for cid in sorted(items):
        pool = items[cid]
        rng.shuffle(pool)
        out.extend(sorted(pool[:PER_CRITERION], key=lambda x: str(x["id"])))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "llm" / "judge_set.jsonl")
    args = ap.parse_args(argv)
    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
    )
    print(f"wrote {len(rows)} judge items to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
