"""The canary of ir_extract v4 (G10 of the P1b review, D-984): the run's own lines where v3 copied the prompt's example
score names onto other atoms, put an age in ``value``, or added a placeholder age (``eval/qualification/
ir_extract_v4_canary.jsonl``). A qualification run extracts each line with the candidate version and scores it here:
every expectation of a line must hold for the line to pass.

    python -m tools.ir_extract_canary <answers.json>   # [{"text": ..., "logic": ...}, ...] -> a JSON report
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

CANARY = Path(__file__).resolve().parents[1] / "eval" / "qualification" / "ir_extract_v4_canary.jsonl"


def _atoms(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if "args" in node:
            for a in node["args"] or []:
                yield from _atoms(a)
        else:
            yield node


def holds(expect: str, logic: Any) -> bool:
    """One expectation of a canary line, on the logic a version wrote for it."""
    atoms = list(_atoms(logic))
    if expect == "no_derived":
        return not any(a.get("derived") for a in atoms)
    if expect == "age_in_age":
        return any(a.get("domain") == "demographic" and a.get("age") for a in atoms) and not any(
            a.get("domain") == "demographic" and a.get("value") for a in atoms
        )
    if expect == "no_placeholder_age":
        return not any(a.get("domain") != "demographic" and a.get("age") for a in atoms)
    raise ValueError(f"unknown expectation {expect!r}")


def score(answers: list[dict[str, Any]], canary: Path = CANARY) -> dict[str, Any]:
    """Per canary line (matched by text, whitespace folded): passed, failed or missing; the share passed."""
    by_text = {_key(a.get("text", "")): a for a in answers}
    rows = [json.loads(x) for x in canary.read_text(encoding="utf-8").splitlines() if x.strip()]
    passed, failed, missing = 0, [], []
    for r in rows:
        a = by_text.get(_key(r["text"]))
        if a is None:
            missing.append(r["text"])
        elif all(holds(e, a.get("logic")) for e in r["expect"]):
            passed += 1
        else:
            failed.append(r["text"])
    share = round(passed / len(rows), 3) if rows else 0.0
    return {"lines": len(rows), "passed": passed, "share": share, "failed": failed, "missing": missing}


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def main(argv: list[str]) -> int:
    report = score(json.loads(Path(argv[0]).read_text(encoding="utf-8")))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if not report["failed"] and not report["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
