"""Bake-off as code (spec v4 §8.10, LLM-33; S1-14): ``mlbench`` tasks driven through the gateway ``bakeoff`` route.

    python -m tools.bakeoff --dry-run            # plan, cost estimate and gateway preflight; no model call leaves
    python -m tools.bakeoff --live               # needs OPENROUTER_API_KEY, TB_GATEWAY_URL and a pinned build

Candidates come from the model registry (builds whose alias is on the ``bakeoff`` route of ``models/routing.yaml``).
Tasks come from ``tools/mlbench_tasks/``; weights, per-language floors and the cost cap from
``eval/bakeoff/weights.yaml``. The dry run:

* prints the plan (tasks × languages × items × seeds × candidates) and a cost and token estimate per candidate and
  per 1,000 items, from the rendered requests and the endpoint prices in the routing table;
* preflights every candidate through an in-process gateway in DEV with networking disabled: today every OpenRouter
  candidate is refused (``build_unpinned``: no build is pinned by SHA-256), which is the expected MS0 state;
* checks that a D1 payload on the ``bakeoff`` role is refused (LLM-33: OpenRouter is D0 only);
* runs one item through the stub build (TEST, route ``dev-stub``) to show the request path works.

No result is recorded before a live run (§20.8 S1-14).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "eval" / "bakeoff" / "weights.yaml"
BAKEOFF_ROUTE = "bakeoff"


@dataclass(frozen=True)
class Probe:
    name: str
    allowed: bool
    code: str
    detail: str


def _no_network() -> httpx.Client:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network disabled in the bake-off dry run", request=req)

    return httpx.Client(transport=httpx.MockTransport(handler))


def load_weights(path: Path = WEIGHTS) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc


def candidates(policy: Any, registry: Any) -> list[dict[str, Any]]:
    route = next(r for r in policy.routes if r.id == BAKEOFF_ROUTE)
    out = []
    for alias, ep in route.builds:
        for b in registry.builds:
            if b.alias != alias or b.status.value in ("retired", "suspended"):
                continue
            out.append(
                {
                    "build_id": b.build_id,
                    "alias": alias,
                    "endpoint": ep,
                    "status": b.status.value,
                    "pinned": b.pinned,
                    "served": b.served.get(ep),
                    "model_name": b.model_name,
                }
            )
    return out


def plan(
    *, n: int | None = None, langs: list[str] | None = None, prices: tuple[float, float] | None = None
) -> dict[str, Any]:
    """``prices`` = (USD per 1k input, per 1k output) overrides the routing-table prices for the estimate only."""
    from gateway.policy import RoutingPolicy
    from registry.registry import Registry

    from tools import mlbench
    from tools.mlbench_tasks import load_tasks

    weights = load_weights()
    tasks = load_tasks()
    policy = RoutingPolicy.load()
    registry = Registry.load()
    cands = candidates(policy, registry)
    seeds = list(weights.get("seeds") or [7])
    pairs = mlbench.load_pairs()
    roles = []
    total_cost = 0.0
    for role, cfg in sorted((weights.get("roles") or {}).items()):
        task = tasks[str(cfg["task"])]
        use_langs = langs or list(task.langs)
        subset = mlbench.sample(pairs, n if n is not None else task.n)
        tok_in: dict[str, float] = {}
        for lang in use_langs:
            notes = mlbench.load_notes(lang)
            sizes = [len(json.dumps(mlbench.messages(p, notes[p.patient_id]), ensure_ascii=False)) for p in subset]
            tok_in[lang] = statistics.fmean(sizes) / 4 if sizes else 0.0  # ~4 characters per token (est.)
        calls_per_candidate = len(subset) * len(use_langs) * len(seeds)
        per_cand = []
        for c in cands:
            cost = policy.endpoints[c["endpoint"]].cost
            usd_in, usd_out = prices or (float(cost.get("usd_per_1k_in", 0.0)), float(cost.get("usd_per_1k_out", 0.0)))
            tokens_in = sum(tok_in[lang] for lang in use_langs) * len(subset) * len(seeds)
            tokens_out = calls_per_candidate * task.out_tokens
            usd = tokens_in / 1000 * usd_in + tokens_out / 1000 * usd_out
            total_cost += usd
            per_cand.append(
                {
                    **c,
                    "calls": calls_per_candidate,
                    "tokens_in": round(tokens_in),
                    "tokens_out": tokens_out,
                    "cost_usd": round(usd, 4),
                    "cost_per_1k_items_usd": round(1000 * usd / calls_per_candidate, 4) if calls_per_candidate else 0,
                    "prices_set": bool(usd_in or usd_out),
                }
            )
        roles.append(
            {
                "role": role,
                "task": task.id,
                "gateway_role": task.gateway_role,
                "dataset": task.dataset,
                "data_class": task.data_class,
                "langs": use_langs,
                "items": len(subset),
                "seeds": seeds,
                "floors": cfg.get("floors"),
                "weights": cfg.get("weights"),
                "candidates": per_cand,
            }
        )
    cap = float(weights.get("cost_cap_usd", 0.0))
    return {
        "weights_version": weights.get("version"),
        "routing_version": policy.version,
        "registry_version": registry.version,
        "roles": roles,
        "cost_estimate_usd": round(total_cost, 4),
        "cost_cap_usd": cap,
        "within_cap": total_cost <= cap,
    }


def preflight(workdir: Path) -> list[Probe]:
    """Gateway probes with networking disabled. Nothing here can reach a model host."""
    from tb_llm import CallLabels, GatewayError, GatewayRefused, json_schema_format

    from tools import mlbench
    from tools.trialbox.eval import JUDGE_SCHEMA, RecordedUpstream, gateway_client, stub_gateway

    pairs = mlbench.load_pairs()
    notes = mlbench.load_notes("en")
    msgs = mlbench.messages(pairs[0], notes[pairs[0].patient_id])
    fmt = json_schema_format("judge", JUDGE_SCHEMA)
    probes: list[Probe] = []

    def labels(dc: str) -> CallLabels:
        return CallLabels(
            data_class=dc,
            purpose="evaluation",
            study_id="none",
            context_of_use="bakeoff_judge_ml",
            role="bakeoff",
            prompt="mlbench_judge@1",
        )

    dev = gateway_client(stub_gateway(_no_network(), workdir / "audit_dev", "DEV"), "eval")
    from gateway.policy import RoutingPolicy

    route = next(r for r in RoutingPolicy.load().routes if r.id == BAKEOFF_ROUTE)
    for alias, ep in route.builds:
        name = f"{alias}@{ep} (D0)"
        try:
            res = dev.chat(msgs, labels("D0"), response_format=fmt, model=alias)
            probes.append(Probe(name, True, "allowed", f"build {res.build_sha}"))
        except GatewayRefused as e:
            probes.append(Probe(name, False, e.reason, str(e)))
        except GatewayError as e:
            probes.append(Probe(name, False, "gateway_error", str(e)))
    try:
        dev.chat(msgs, labels("D1"), response_format=fmt)
        probes.append(Probe("bakeoff D1 payload", True, "allowed", "a D1 payload was accepted (LLM-33 breach)"))
    except GatewayRefused as e:
        probes.append(Probe("bakeoff D1 payload", False, e.reason, str(e)))
    upstream = RecordedUpstream({RecordedUpstream.key(msgs): {"label": pairs[0].gpt4_label, "evidence": []}})
    test = gateway_client(stub_gateway(upstream.client(), workdir / "audit_test", "TEST"), "eval")
    try:
        res = test.chat(msgs, labels("D0"), response_format=fmt)
        probes.append(Probe("stub (TEST, dev-stub)", True, "allowed", f"{res.alias} {res.build_sha}"))
    except GatewayRefused as e:
        probes.append(Probe("stub (TEST, dev-stub)", False, e.reason, str(e)))
    return probes


def render(p: dict[str, Any], probes: list[Probe]) -> str:
    lines = [
        f"bake-off plan  weights {p['weights_version']}  routing {p['routing_version']}  "
        f"registry {p['registry_version']}"
    ]
    for r in p["roles"]:
        lines.append(
            f"role {r['role']}: task {r['task']} via gateway role {r['gateway_role']} on {r['dataset']} "
            f"({r['data_class']}); "
            f"{r['items']} items x {len(r['langs'])} langs ({' '.join(r['langs'])}) x {len(r['seeds'])} seeds"
        )
        lines.append(f"  floors {r['floors']}")
        for c in r["candidates"]:
            price = "" if c["prices_set"] else " (no prices: pass --usd-per-1k IN OUT)"
            lines.append(
                f"  {c['build_id']:<32} {c['alias']}@{c['endpoint']:<10} {c['status']:<9} pinned={c['pinned']!s:<5} "
                f"calls={c['calls']} tokens_in~{c['tokens_in']} tokens_out~{c['tokens_out']} "
                f"cost~${c['cost_usd']:.2f} (${c['cost_per_1k_items_usd']:.2f}/1k){price}"
            )
    lines.append(
        f"cost estimate ${p['cost_estimate_usd']:.2f} (cap ${p['cost_cap_usd']:.2f}; within cap: {p['within_cap']})"
    )
    lines.append("gateway preflight (network disabled):")
    for pr in probes:
        lines.append(f"  {'ALLOWED' if pr.allowed else 'REFUSED':<8} {pr.name:<34} {pr.code}")
    lines.append("no result is recorded before a live run")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bakeoff", description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    ap.add_argument("--n", type=int, default=None, help="items per task (default: the task's n)")
    ap.add_argument("--langs", nargs="+", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--usd-per-1k",
        nargs=2,
        type=float,
        metavar=("IN", "OUT"),
        default=None,
        help="price override for the estimate (USD per 1k input and output tokens)",
    )
    a = ap.parse_args(argv)
    p = plan(n=a.n, langs=a.langs, prices=tuple(a.usd_per_1k) if a.usd_per_1k else None)
    with tempfile.TemporaryDirectory(prefix="bakeoff-") as tmp:
        probes = preflight(Path(tmp))
    if a.json:
        print(json.dumps({"plan": p, "preflight": [pr.__dict__ for pr in probes]}, indent=1, ensure_ascii=False))
    else:
        print(render(p, probes))
    d1 = next(pr for pr in probes if pr.name == "bakeoff D1 payload")
    if d1.allowed:
        print("FAIL: a D1 payload was accepted on the bakeoff role (LLM-33)", file=sys.stderr)
        return 1
    if a.dry_run:
        return 0
    if not os.environ.get("OPENROUTER_API_KEY") or not os.environ.get("TB_GATEWAY_URL"):
        print("live run refused: OPENROUTER_API_KEY and TB_GATEWAY_URL (a DEV gateway) are required", file=sys.stderr)
        return 2
    routable = [pr for pr in probes if pr.name.endswith("(D0)") and pr.allowed]
    if not routable:
        print(
            "live run refused: no candidate build is routable on the bakeoff route (pin a build first)", file=sys.stderr
        )
        return 3
    if not p["within_cap"]:
        print("live run refused: the cost estimate exceeds the cap", file=sys.stderr)
        return 4
    print("live dispatch is not built in MS0 (S1-14 done-criterion is the dry run)", file=sys.stderr)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
