"""The 54-case pair canary from a checkout (TB-PLAN-03 step 2, D-117): ``make canary``.

The box runs the same code by itself (:mod:`orchestrator.canary_gate`: at start, before each night's LLM jobs, and
from the admin Models tile's "Run now"); a passing *pair* result is what lets a note answer exclude a patient. This
command runs it against

* the models of this environment (``TB_GATEWAY_URL`` ..., as the orchestrator would), or
* two OpenAI-compatible servers given directly (``--judge-url``, ``--verifier-url``; bearer key in ``TB_GPU_KEY``),
  with ``--swap`` when they time-share one GPU (vLLM sleep mode: each is woken in turn, the judge left awake);
  ``--judge-url`` alone checks the judge alone (no pair).

It also runs the six-case wake check on each model after its wake (the check a one-GPU run does after every swap).

    python -m tools.canary [--judge-url http://<vm>/judge/v1 --verifier-url http://<vm>/verifier/v1 [--swap]]
                           [--out report.json]

Exit 0 when the pair passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

JUDGE = "local/gemma-4-26b-a4b-nvfp4"
VERIFIER = "local/qwen3.5-9b-awq"


def direct_clients(judge_url: str, verifier_url: str, key: str) -> tuple[Any, Any]:
    """Clients of the two servers; no verifier URL gives no verifier (the judge alone: card 24-5's judge-alone run;
    the self-test then checks the judge only and no pair)."""
    import httpx
    from tb_common.llm import LlmClient

    out: list[Any] = []
    for url, name in ((judge_url, JUDGE), (verifier_url, VERIFIER)):
        if not url:
            out.append(None)
            continue
        c = LlmClient(url, name, timeout=600.0)
        c.http = httpx.Client(timeout=600.0, headers={"Authorization": f"Bearer {key}"})
        out.append(c)
    return out[0], out[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--judge-url", default="")
    ap.add_argument("--verifier-url", default="")
    ap.add_argument("--swap", action="store_true", help="the two servers share one GPU (vLLM sleep mode)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    from orchestrator import canary_gate, selftest

    swap = release = None
    wake: dict[str, Any] = {}
    if a.judge_url:
        key = os.environ["TB_GPU_KEY"]  # from the environment only, never a flag
        llm, verifier = direct_clients(a.judge_url, a.verifier_url, key)
        if a.swap and verifier is not None:
            from gateway.swap import ModelSwap, SwapError
            from tb_common.llm import LlmError

            sw = ModelSwap(
                {"serving": a.judge_url, "verifier": a.verifier_url}, headers={"Authorization": f"Bearer {key}"}
            )
            clients = {"serving": llm, "verifier": verifier}

            def swap(endpoint: str) -> None:
                t0 = time.perf_counter()
                try:
                    sw.activate(endpoint)
                except SwapError as exc:
                    raise LlmError(f"swap to {endpoint}: {exc}") from exc
                why = canary_gate.check_wake("judge" if endpoint == "serving" else "verifier", clients[endpoint])
                wake.setdefault(endpoint, []).append(
                    {"swap_s": round(time.perf_counter() - t0, 2), "ok": why is None, "why": why}
                )
    else:
        from orchestrator.app import verifier_client
        from orchestrator.twophase import GatewaySwap
        from tb_common.audit import AuditLog
        from tb_common.config import get_config
        from tb_common.llm import LlmClient

        cfg = get_config()
        audit = AuditLog(cfg.env.audit_path, cfg.env.tz)
        llm, verifier = LlmClient.from_config(audit), verifier_client(audit)
        gs = GatewaySwap.from_env()
        if gs is not None:
            swap, release = gs.use, gs.release
    t0 = time.perf_counter()
    report = selftest.run_selftest(llm, verifier, swap, release=release)
    report["seconds"] = round(time.perf_counter() - t0, 1)
    report["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if wake:
        report["wake_checks"] = wake
        report["ok"] = report["ok"] and all(w["ok"] for ws in wake.values() for w in ws)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
