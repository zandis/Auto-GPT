"""Agreement of the ``judge`` prompt with the labelled set (SPEC §11.1; phase 4 DoD ≥ 90 %).

    python tools/judge_eval.py                                            # the stub: a wiring test (CPU CI)
    python tools/judge_eval.py --gateway-url http://127.0.0.1:8080/v1     # a model, through a DEV/TEST gateway

Each item goes through ``tb_common.llm.chat_json`` and the production post-processing (quote must be a substring
of an excerpt). Prints agreement overall / per criterion / confusion matrix; exit 1 below ``--min``.

**What it does not measure (T-608, D-445; review LLM-032).** On the stub the agreement is 1.0 by construction: the
stub's rules are the fixture's sentence templates. That run is a wiring test of the prompt, the schema and the
post-processing, never evidence about a model, and the report says so (``mode``, ``not_measured``). With a model the
call goes through a gateway (``--gateway-url``, or ``TB_GATEWAY_URL``), so the gateway's forced sampling, routing and
audit apply, never straight to a model server. Even then the set is synthetic and its sentences follow a few
templates: it measures agreement on those, not on real notes, and not the two-model pair (``trialbox eval
qualify`` does that).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in ("libs", "services"):
    sys.path.insert(0, str(ROOT / p))


STUB_NOT_MEASURED = [
    "any model: the stub's rules are the fixture's sentence templates, so agreement is 1.0 by construction",
    "token counts: the stub's are estimates (usage.estimated)",
]
MODEL_NOT_MEASURED = [
    "real notes: the set is synthetic and follows a few sentence templates",
    "the judge and verifier pair (trialbox eval qualify measures that)",
]


class GatewayEval:
    """``chat_json`` for :func:`evaluate` through a gateway, as caller ``eval`` with purpose ``evaluation`` on D0
    (synthetic) notes; an answer outside the judge schema counts as no answer (LLM-022)."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def chat_json(self, prompt_id: str, variables: dict[str, Any]) -> Any:
        from types import SimpleNamespace

        from tb_common.llm import load_prompt, render
        from tb_contracts import inline_schema, load_schema, null_absent, schema_errors
        from tb_llm import CallLabels, json_schema_format

        p = load_prompt(prompt_id)
        labels = CallLabels(
            data_class="D0",
            purpose="evaluation",
            study_id="none",
            context_of_use="s3_note_judgement",
            role="judge",
            prompt=f"{p.meta.id}@{p.meta.version}",
            prompt_sha=p.sha256,
        )
        fmt = json_schema_format(p.meta.id, inline_schema(p.meta.output_schema))
        res = self.client.chat(render(p, variables), labels, response_format=fmt, max_tokens=p.meta.max_tokens)
        data = null_absent(load_schema(p.meta.output_schema), res.data) if isinstance(res.data, dict) else None
        ok = isinstance(data, dict) and not schema_errors(p.meta.output_schema, data)
        return SimpleNamespace(data=data if ok else {"verdict": "unknown", "confidence": 0.0, "quote": None})


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
    ap.add_argument("--set", type=Path, default=ROOT / "eval" / "qualification" / "judge_set.jsonl")
    ap.add_argument("--gateway-url", default=os.environ.get("TB_GATEWAY_URL", ""), help="a DEV or TEST gateway")
    ap.add_argument("--model", default="", help="an alias the gateway may route the judge role to")
    ap.add_argument("--prompt", default="judge")
    ap.add_argument("--min", type=float, default=0.90)
    args = ap.parse_args(argv)
    items = [json.loads(x) for x in args.set.read_text(encoding="utf-8").splitlines() if x.strip()]
    if args.gateway_url:
        from tb_llm import GatewayClient

        # LLM-032: through the gateway (forced sampling, routing, audit), never straight to a model server
        llm: Any = GatewayEval(GatewayClient(args.gateway_url, "eval", model=args.model or None))
        mode, not_measured = "model through the gateway", MODEL_NOT_MEASURED
    else:
        from fastapi.testclient import TestClient
        from llm_stub.app import app as stub

        llm = LlmClient("http://stub/v1", "trialbox-stub")
        llm.http = TestClient(stub)
        mode, not_measured = "stub wiring test", STUB_NOT_MEASURED
    report = {"mode": mode, **evaluate(items, llm, args.prompt), "not_measured": not_measured}
    print(json.dumps(report, indent=1))
    return 0 if report["agreement"] >= args.min else 1


if __name__ == "__main__":
    raise SystemExit(main())
