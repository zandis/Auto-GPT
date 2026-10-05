"""Agreement of the ``judge`` prompt with the labelled set (SPEC §11.1; phase 4 DoD ≥ 90 %).

    python tools/judge_eval.py                                   # deterministic stub (CPU CI)
    python tools/judge_eval.py --llm-url http://127.0.0.1:8000/v1 --model qwen3.5-35b-a3b-q4   # real model

Each item goes through ``tb_common.llm.chat_json`` and the production post-processing (quote must be a substring
of an excerpt). Prints agreement overall / per criterion / confusion matrix; exit 1 below ``--min``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in ("libs", "services"):
    sys.path.insert(0, str(ROOT / p))


def evaluate(items: list[dict[str, Any]], llm: Any, prompt: str = "judge") -> dict[str, Any]:
    from orchestrator.scenarios.evaluate import postprocess

    confusion: Counter[tuple[str, str]] = Counter()
    per: dict[str, list[int]] = {}
    for it in items:
        res = llm.chat_json(
            prompt,
            {k: it[k] for k in ("criterion_text", "note_question", "index_date", "excerpts")},
        )
        got = postprocess(res.data, it["excerpts"], "full_record").predicate
        confusion[(it["gold"], got)] += 1
        per.setdefault(it["criterion_id"], [0, 0])
        per[it["criterion_id"]][0] += int(got == it["gold"])
        per[it["criterion_id"]][1] += 1
    n = sum(confusion.values())
    ok = sum(v for (g, p), v in confusion.items() if g == p)
    return {
        "n": n,
        "agreement": round(ok / n, 4) if n else 0.0,
        "per_criterion": {k: round(a / b, 4) for k, (a, b) in sorted(per.items())},
        "confusion": {f"{g}->{p}": v for (g, p), v in sorted(confusion.items())},
    }


def main(argv: list[str] | None = None) -> int:
    from tb_common.llm import LlmClient

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", type=Path, default=ROOT / "tests" / "fixtures" / "llm" / "judge_set.jsonl")
    ap.add_argument("--llm-url", default="")
    ap.add_argument("--model", default="trialbox")
    ap.add_argument("--prompt", default="judge")
    ap.add_argument("--min", type=float, default=0.90)
    args = ap.parse_args(argv)
    items = [json.loads(x) for x in args.set.read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.llm_url:
        llm = LlmClient(args.llm_url, args.model)
    else:
        from fastapi.testclient import TestClient
        from llm_stub.app import app as stub

        llm = LlmClient("http://stub/v1", "trialbox-stub")
        llm.http = TestClient(stub)
    report = evaluate(items, llm, args.prompt)
    print(json.dumps(report, indent=1))
    return 0 if report["agreement"] >= args.min else 1


if __name__ == "__main__":
    raise SystemExit(main())
