"""Score the header command field against its test set (step 4, D-110).

    python -m tools.command_score            # print the score
    python -m tools.command_score --write    # also write tests/console/data/command_set_score.json

A case is **right** when the field picks the expected action (and the expected study, when one is given). It is
**wrong** when the field opens a different page than expected: that is the failure that matters, because the user
would land somewhere they did not ask for. Anything else (not understood, asked to pick a study) is **unsure**: the
user sees the help panel and nothing happens. Done when right ≥ 95 % and wrong = 0 % (TB-DS-20 step 4).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SET = ROOT / "tests" / "console" / "data" / "command_set.json"
SCORE = ROOT / "tests" / "console" / "data" / "command_set_score.json"


def score(path: Path = SET) -> dict[str, Any]:
    from console.command import interpret

    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, Any] = {"n": 0, "right": 0, "wrong": 0, "unsure": 0, "by_lang": {}, "misses": []}
    for c in data["cases"]:
        act = interpret(c["text"], data["studies"], c["role"])
        ok = act.intent == c["intent"] and (c.get("study") is None or act.study == c["study"])
        if c["intent"] in ("unknown", "pick_study") and not act.opens_page:
            ok = act.intent == c["intent"]
        kind = "right" if ok else "wrong" if act.opens_page else "unsure"
        lang = out["by_lang"].setdefault(c["lang"], {"n": 0, "right": 0, "wrong": 0, "unsure": 0})
        for bucket in (out, lang):
            bucket["n"] += 1
            bucket[kind] += 1
        if kind != "right":
            out["misses"].append({**c, "got": act.intent, "got_study": act.study, "kind": kind})
    out["right_pct"] = round(100 * out["right"] / out["n"], 1)
    out["wrong_pct"] = round(100 * out["wrong"] / out["n"], 1)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write the score file next to the set")
    args = ap.parse_args(argv)
    res = score()
    print(
        f"{res['n']} phrasings: right {res['right']} ({res['right_pct']} %), wrong {res['wrong']} "
        f"({res['wrong_pct']} %), unsure {res['unsure']}"
    )
    for lang, b in sorted(res["by_lang"].items()):
        print(f"  {lang}: {b['right']}/{b['n']} right, {b['wrong']} wrong")
    if args.write:
        SCORE.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if res["right_pct"] >= 95 and res["wrong"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
