"""Agreement of the ``judge`` prompt with the labelled set (SPEC §11.1; phase 4 DoD ≥ 90 %).

    python tools/judge_eval.py                                            # the stub: a wiring test (CPU CI)
    python tools/judge_eval.py --gateway-url http://127.0.0.1:8080/v1     # a model, through a DEV/TEST gateway

Each item goes through ``tb_common.llm.chat_json`` and the production post-processing (quote must be a substring
of an excerpt). Prints agreement overall / per criterion / confusion matrix; exit 1 below ``--min``.

**What it counts (INT-S-E).** A reply is read as the product reads it (``no_sentinel_date``, the product's own
function, before the schema). It never converts a reply silently: ``schema_invalid`` counts replies outside the schema
(per criterion and per rule broken; they still score as ``unknown``, as before), and ``placeholder`` counts an
``unknown`` that carries a filler quote, a sentinel date or a confidence. ``--out FILE`` writes the same summary plus,
per call, the finish reason and the token counts the gateway returned.

**``--gateway-url`` on a TEST stack.** ``--model`` must be the build's *alias* on the route (the ``builds`` of route
``dev-stub`` in ``models/routing.yaml``, or an id listed by ``GET <gateway>/v1/models``), not the name the model server
serves it under. With no ``--model`` the route's first build answers, and that is a stub that is not running
(``502 upstream_down``); with the served name the gateway says ``403 class_route_mismatch``.

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


_WHERE = "models/routing.yaml, route dev-stub, or GET <gateway>/v1/models"
REFUSALS = {
    "upstream_down": "judge_eval: {status} {reason} for --model {model}: the route's first build is not running; "
    f"pass --model <the build's alias on the route> ({_WHERE}).",
    "class_route_mismatch": "judge_eval: {status} {reason} for --model {model}: that is not an alias on the route; "
    f"--model must be the build's alias ({_WHERE}), not the name the model server serves it under.",
}


class GatewayEval:
    """``chat_json`` for :func:`evaluate` through a gateway, as caller ``eval`` with purpose ``evaluation`` on D0
    (synthetic) notes; an answer outside the judge schema counts as no answer (LLM-022)."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def chat_json(self, prompt_id: str, variables: dict[str, Any]) -> Any:
        from types import SimpleNamespace

        from tb_common.llm import load_prompt, no_sentinel_date, render
        from tb_contracts import inline_schema, load_schema, null_absent
        from tb_contracts.schema import schema_error_codes
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
        # the product's order (tb_common.llm.chat_json): null for absent, the sentinel date is no date, then the schema
        data = null_absent(load_schema(p.meta.output_schema), res.data) if isinstance(res.data, dict) else None
        sentinel = False
        if isinstance(data, dict):
            fixed = no_sentinel_date(data)
            sentinel = fixed is not data
            data = fixed
        codes = (
            schema_error_codes(p.meta.output_schema, data) if isinstance(data, dict) else ["<root>: not JSON"]
        )  # path: rule, never the value
        audit = {
            "schema_errors": codes,
            "sentinel_date": sentinel,
            "finish_reason": (res.payload.get("choices") or [{}])[0].get("finish_reason"),
            "tokens_in": res.tokens_in,
            "tokens_out": res.tokens_out,
            "call_id": res.call_id,
        }
        # counted by evaluate(), then scored as unknown with confidence 0, as before (agreement is unchanged)
        out = {"verdict": "unknown", "confidence": 0.0, "quote": None} if codes else data
        return SimpleNamespace(data=out, audit=audit)


def evaluate(items: list[dict[str, Any]], llm: Any, prompt: str = "judge") -> dict[str, Any]:
    from orchestrator.scenarios.evaluate import postprocess

    confusion: Counter[tuple[str, str]] = Counter()
    per: dict[str, list[int]] = {}
    invalid_rules: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    counts: dict[str, dict[str, int]] = {}
    calls: list[dict[str, Any]] = []
    for it in items:
        res = llm.chat_json(
            prompt,
            {k: it[k] for k in ("criterion_text", "note_question", "index_date", "excerpts")},
        )
        audit = getattr(res, "audit", None) or {}
        c = counts.setdefault(it["criterion_id"], {"schema_invalid": 0, "placeholder": 0})
        codes = audit.get("schema_errors") or []
        if codes:
            c["schema_invalid"] += 1
            invalid_rules.update(codes)
        elif res.data.get("verdict") == "unknown":
            found = [
                k
                for k, hit in (
                    ("quote", bool(res.data.get("quote"))),
                    ("sentinel_date", bool(audit.get("sentinel_date")) or bool(res.data.get("quote_date"))),
                    ("confidence", bool(res.data.get("confidence"))),
                )
                if hit
            ]
            c["placeholder"] += bool(found)
            kinds.update(found)
        calls.append({
            "criterion_id": it["criterion_id"],
            "finish_reason": audit.get("finish_reason"),
            "tokens_in": audit.get("tokens_in", getattr(res, "tokens_in", None)),
            "tokens_out": audit.get("tokens_out", getattr(res, "tokens_out", None)),
            "call_id": audit.get("call_id"),
        })  # fmt: skip
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
        "schema_invalid": sum(v["schema_invalid"] for v in counts.values()),
        "schema_invalid_rules": dict(sorted(invalid_rules.items())),
        "placeholder": sum(v["placeholder"] for v in counts.values()),
        "placeholder_kinds": dict(sorted(kinds.items())),
        "per_criterion_counts": dict(sorted(counts.items())),
        "calls": calls,
    }


def main(argv: list[str] | None = None) -> int:
    from tb_common.llm import LlmClient

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", type=Path, default=ROOT / "eval" / "qualification" / "judge_set.jsonl")
    ap.add_argument("--gateway-url", default=os.environ.get("TB_GATEWAY_URL", ""), help="a DEV or TEST gateway")
    ap.add_argument(
        "--model",
        default="",
        help="the build's ALIAS on the gateway's route for the judge role (the builds of route dev-stub in "
        "models/routing.yaml, or an id listed by GET <gateway>/v1/models), not the name the model server serves it "
        "under. With none the route's first build answers; on a TEST stack that is a stub that is not running",
    )
    ap.add_argument("--out", type=Path, default=None, help="write the summary and, per call, finish reason and tokens")
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
    from tb_llm import GatewayRefused

    try:
        result = evaluate(items, llm, args.prompt)
    except GatewayRefused as e:
        if e.reason not in REFUSALS:
            raise
        print(
            REFUSALS[e.reason].format(model=args.model or "(none)", status=e.status, reason=e.reason), file=sys.stderr
        )
        return 2
    calls = result.pop("calls")
    report = {"mode": mode, **result, "not_measured": not_measured}
    print(json.dumps(report, indent=1))
    if args.out:
        args.out.write_text(json.dumps({**report, "calls": calls}, indent=1) + "\n", encoding="utf-8")
    return 0 if report["agreement"] >= args.min else 1


if __name__ == "__main__":
    raise SystemExit(main())
