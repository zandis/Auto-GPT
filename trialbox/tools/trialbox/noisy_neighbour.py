"""Noisy-neighbour measurement on a shared GPU host (T-319, D-432; WS-13.9, OPS-069 drill half).

On a shared platform the judge and the verifier hold their own MIG instances, but another tenant's job can still
load the same card (memory bandwidth, PCIe, the host's CPUs). This tool measures what that does to TrialBox's serving:
the same short chat request, ``--requests`` times with the card otherwise idle, then again while the neighbour's load
runs, and records the latency of both phases and the ratio of their 95th percentiles::

    python -m tools.trialbox.noisy_neighbour --url http://llm-service:8000/v1/chat/completions --model judge \\
        --neighbour "kubectl -n gpu-burn apply -f burn.yaml" \\
        --neighbour-stop "kubectl -n gpu-burn delete -f burn.yaml" \\
        --out noisy-neighbour.json

The neighbour's load is the platform team's: a command that starts it (``--neighbour``; kept running, or one that
returns once the load is scheduled) and, optionally, one that stops it. The key of the model servers comes from the
file ``TB_LLM_API_KEY_FILE`` names (``deploy/secrets/model/llm.key``, D-437, D-450), else ``TB_LLM_API_KEY`` (sent as a
bearer token, never written). The verdict is PASS when no request failed and the loaded
95th percentile is at most ``--max-ratio`` times the idle one (default 1.5); the record is evidence for IQ and for
the drill after every platform patch (RUNBOOK §17). It needs a real shared GPU host: until one exists its record is
"not run". Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "tb-noisy-neighbour/1"
PROMPT = "Reply with the single word: ready"


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q`` percentile (0 to 100) by linear interpolation; 0.0 for no values."""
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def http_caller(url: str, model: str, key: str, timeout: float = 120.0) -> Callable[[], None]:
    """One chat request to the model server; raises on anything but a 2xx answer."""
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 8, "temperature": 0}
    ).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # the servers are inside the namespace

    def call() -> None:
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        with opener.open(req, timeout=timeout) as r:  # nosec B310: the operator's own model server URL
            r.read()

    return call


def phase(call: Callable[[], None], n: int, clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    lat: list[float] = []
    errors: list[str] = []
    for _ in range(n):
        t0 = clock()
        try:
            call()
        except (OSError, urllib.error.URLError, ValueError) as e:
            errors.append(type(e).__name__)
            continue
        lat.append(clock() - t0)
    return {
        "requests": n,
        "ok": len(lat),
        "errors": errors,
        "p50_s": round(percentile(lat, 50), 4),
        "p95_s": round(percentile(lat, 95), 4),
        "max_s": round(max(lat, default=0.0), 4),
    }


def measure(
    call: Callable[[], None],
    n: int,
    start_neighbour: Callable[[], Callable[[], None]],
    *,
    warmup: float = 0.0,
    max_ratio: float = 1.5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Both phases and the verdict. ``start_neighbour`` starts the load and returns the function that stops it."""
    call()  # one request first, so a cold start is not counted in the idle phase
    alone = phase(call, n, clock)
    stop = start_neighbour()
    try:
        if warmup:
            sleep(warmup)
        loaded = phase(call, n, clock)
    finally:
        stop()
    ratio = round(loaded["p95_s"] / alone["p95_s"], 3) if alone["p95_s"] else None
    failed = bool(alone["errors"] or loaded["errors"])
    ok = not failed and ratio is not None and ratio <= max_ratio
    why = (
        "requests failed"
        if failed
        else ("no idle latency" if ratio is None else f"p95 loaded/idle {ratio} (limit {max_ratio})")
    )
    return {"alone": alone, "loaded": loaded, "p95_ratio": ratio, "max_ratio": max_ratio,
            "verdict": "PASS" if ok else "FAIL", "why": why}  # fmt: skip


def command_neighbour(start: str, stop: str | None) -> Callable[[], Callable[[], None]]:
    """The platform team's load as two commands (no shell)."""

    def begin() -> Callable[[], None]:
        proc = subprocess.Popen(shlex.split(start), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # nosec B603

        def end() -> None:
            if stop:
                subprocess.run(shlex.split(stop), check=False, capture_output=True, timeout=300)  # nosec B603
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()

        return end

    return begin


def model_key(env: Mapping[str, str]) -> str:
    """The model servers' key: the file ``TB_LLM_API_KEY_FILE`` names first (T-212d, D-450), else the variable."""
    path = (env.get("TB_LLM_API_KEY_FILE") or "").strip()
    if path:
        try:
            got = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            got = ""
        if got:
            return got
    return (env.get("TB_LLM_API_KEY") or "").strip()


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="python -m tools.trialbox.noisy_neighbour", description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", required=True, help="the model server's chat completions URL")
    ap.add_argument("--model", required=True, help="the served model name (judge or verifier)")
    ap.add_argument("--neighbour", required=True, help="the command that starts the neighbour's load")
    ap.add_argument("--neighbour-stop", help="the command that stops it (else the started process is ended)")
    ap.add_argument("--requests", type=int, default=20)
    ap.add_argument("--warmup", type=float, default=30.0, help="seconds between starting the load and measuring")
    ap.add_argument("--max-ratio", type=float, default=1.5)
    ap.add_argument("--out", help="where the record is written (JSON); else printed")
    a = ap.parse_args(argv)
    call = http_caller(a.url, a.model, model_key(env))
    try:
        res = measure(call, a.requests, command_neighbour(a.neighbour, a.neighbour_stop), warmup=a.warmup,
                      max_ratio=a.max_ratio)  # fmt: skip
    except (OSError, urllib.error.URLError) as e:
        print(
            f"noisy-neighbour: the model server refused or did not answer the first request: {type(e).__name__}",
            file=sys.stderr,
        )
        return 2
    record = {"schema": SCHEMA, "at": datetime.now(UTC).isoformat(timespec="seconds"), "url": a.url,
              "model": a.model, "neighbour": a.neighbour, **res}  # fmt: skip
    text = json.dumps(record, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    print(f"noisy-neighbour: {record['verdict']}: {record['why']}", file=sys.stderr)
    return 0 if record["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
