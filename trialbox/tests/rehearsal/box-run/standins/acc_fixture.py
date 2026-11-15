"""Stand-in for ``python -m tools.public_accuracy fetch|build`` in the box's image on the VM (the acc group's step
53-acc-data): no network and no public file here. ``build`` runs the REAL item builder (tools.public_accuracy.site
.build, with the set's own offsets, the box's day) on a tiny SYNTHETIC bundle of the set's kind: three patients, two
trials (one only for a compile-only set), their gold. Synthetic text only; never a public record.

    acc_fixture.py fetch --only SET
    acc_fixture.py build --set SET --size N --out DIR --ref YYYY-MM-DD --for-box
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "libs")]

from tools.public_accuracy import sets, site  # noqa: E402

COMPILE_ONLY = ("tfda", "jrct", "chia")


def bundle(name: str) -> sets.Bundle:
    b = sets.Bundle(name)
    t1, t2 = "NCT90000001", "NCT90000002"
    b.trials = {
        t1: sets.Trial(t1, "en", "Synthetic trial one", ["Type 2 diabetes"], ["Pregnancy"], ["Aged 18 years or older"]),
        t2: sets.Trial(t2, "en", "Synthetic trial two", ["Asthma"], ["Current smoker"]),
    }
    if name in COMPILE_ONLY:
        b.trials = {t1: b.trials[t1]}
        return b
    lang = "ja" if name == "jmed" else "en"
    b.patients = {
        f"{name}:1": sets.Patient(f"{name}:1", lang, "A 61-year-old woman with type 2 diabetes (synthetic).", 61, "F"),
        f"{name}:2": sets.Patient(f"{name}:2", lang, "A 45-year-old man with asthma who smokes (synthetic).", 45, "M"),
        f"{name}:3": sets.Patient(f"{name}:3", lang, "A 30-year-old woman, pregnant (synthetic).", 30, "F"),
    }
    b.pairs = [
        sets.Pair(f"{name}:1", t1, "eligible", name),
        sets.Pair(f"{name}:3", t1, "excluded", name),
        sets.Pair(f"{name}:2", t2, "excluded", name),
    ]
    b.criteria = [sets.CriterionGold(f"{name}:3", t1, "exclusion", "Pregnancy", "excluded", [0])]
    return b


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--only", default="")
    b = sub.add_parser("build")
    b.add_argument("--set", required=True)
    b.add_argument("--size", type=int, default=3)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--ref", default="")
    b.add_argument("--for-box", action="store_true")
    a = ap.parse_args()
    if a.cmd == "fetch":
        print(json.dumps({"standin": True, "only": a.only}))
        return 0
    kw: dict = {"ref": date.fromisoformat(a.ref)} if a.ref else {}
    if a.for_box:
        kw["mrn0"], kw["pi0"], kw["rs_prefix"] = site.SET_OFFSETS[a.set]
    print(json.dumps(site.build(bundle(a.set), a.out / "built", **kw), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
