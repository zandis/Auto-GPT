"""Do the two models answer the same after a sleep-mode wake as before any sleep? (TB-PLAN-03 step 1, D-116)

The one-5090 box time-shares the card (``TB_MODEL_SWAP=sleep``): level-1 sleep copies the weights to host memory
and drops the KV cache, wake copies them back. A bad copy, a wrong dtype after wake or a stale cache would change
the answers without any error. This tool measures it on the card, with the SIGIR filter-first benchmark (N-11) in
one language, against the VM that ``deploy/gcp/gpu-swap-run.sh`` boots (``/judge/`` and ``/verifier/`` behind
nginx, the judge awake and never slept, the verifier started only once the judge sleeps):

1. judge, resident (never slept): every SIGIR criterion question;
2. judge to sleep; the VM then starts the verifier: verifier, resident (never slept);
3. verifier to sleep, judge wake: judge again (after a wake);
4. judge to sleep, verifier wake: verifier again (after a wake).

Every call is fresh (no response cache). Reported per model: label agreement resident vs after wake, and for the
pair (both must block, the box's rule) the eligible pairs lost and the false-block rate, resident vs after wake. The
check passes when the pair's lost pairs and false blocks are the same before and after the wake.

    TB_GPU_KEY=... python -m tools.wake_check --vm http://<ip> --out <dir> [--lang en] [--workers 4]
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

from tools import mlbench
from tools import trialgpt_compare as tc

JUDGE = "local/gemma-4-26b-a4b-nvfp4"
VERIFIER = "local/qwen3.5-9b-awq"


class Vm:
    def __init__(self, base: str, key: str) -> None:
        self.base = base.rstrip("/")
        self.http = httpx.Client(timeout=900.0, headers={"Authorization": f"Bearer {key}"})
        self.key = key

    def post(self, name: str, path: str) -> float:
        t0 = time.perf_counter()
        r = self.http.post(f"{self.base}/{name}{path}")
        r.raise_for_status()
        return round(time.perf_counter() - t0, 2)

    def sleeping(self, name: str) -> bool | None:
        try:
            r = self.http.get(f"{self.base}/{name}/is_sleeping", timeout=10)
            return bool(r.json().get("is_sleeping")) if r.status_code < 400 else None
        except (httpx.HTTPError, ValueError):
            return None

    def wait_up(self, name: str, timeout_s: float = 1800) -> float:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            try:
                if self.http.get(f"{self.base}/{name}/health", timeout=10).status_code == 200:
                    return round(time.monotonic() - t0, 1)
            except httpx.HTTPError:
                pass
            time.sleep(10)
        raise SystemExit(f"{name} not up after {timeout_s:.0f} s")

    def wait_awake(self, name: str, timeout_s: float = 300) -> None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            if self.sleeping(name) is False:
                return
            time.sleep(1)
        raise SystemExit(f"{name} did not wake")

    def gpu(self) -> dict[str, Any]:
        try:
            return dict(self.http.get(f"{self.base}/record/gpu_peak.json", timeout=10).json())
        except (httpx.HTTPError, ValueError):
            return {}


def ask_all(vm: Vm, name: str, model: str, lang: str, workers: int) -> tuple[list[dict[str, Any]], float]:
    """Every SIGIR criterion question to one server, fresh (a new empty cache directory per pass)."""
    notes, pairs = mlbench.load_notes(lang), mlbench.load_pairs()
    with tempfile.TemporaryDirectory() as cache:
        c = tc.Client(f"{vm.base}/{name}/v1", vm.key, Path(cache), timeout=900.0)
        c.max_tokens = 2000
        t0 = time.perf_counter()
        with ThreadPoolExecutor(workers) as ex:
            rows = [r.__dict__ for r in ex.map(lambda p: mlbench.judge(c, model, lang, p, notes[p.patient_id]), pairs)]
    return rows, round(time.perf_counter() - t0, 1)


def agreement(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    rb = {r["annotation_id"]: r for r in b}
    same = [r["annotation_id"] for r in a if rb.get(r["annotation_id"], {}).get("label") == r["label"]]
    diff = [
        {"id": r["annotation_id"], "before": r["label"], "after": rb.get(r["annotation_id"], {}).get("label")}
        for r in a
        if r["annotation_id"] not in set(same)
    ]
    return {"n": len(a), "same_label": len(same), "share": round(len(same) / max(1, len(a)), 4), "changed": diff[:40]}


def summarise(runs: dict[str, list[dict[str, Any]]], lang: str) -> dict[str, Any]:
    pairs, tr, rt = mlbench.load_pairs(), tc.trials(), tc.routes()
    by_id = {p.annotation_id: p for p in tc.comparable(pairs, tr)}
    keep = {k: [r for r in v if r["annotation_id"] in by_id] for k, v in runs.items()}

    def m(rows: list[dict[str, Any]]) -> dict[str, Any]:
        x = tc.ff_metrics(rows, by_id, rt)
        keys = ("pairs_lost", "trials_open", "false_block_rate", "block_recall", "valid_rate", "accuracy")
        return {k: x[k] for k in keys}

    out: dict[str, Any] = {k: m(v) for k, v in keep.items()}
    out["pair_resident"] = m(tc.both_block(keep["judge_resident"], keep["verifier_resident"]))
    out["pair_after_wake"] = m(tc.both_block(keep["judge_after_wake"], keep["verifier_after_wake"]))
    out["judge_agreement"] = agreement(keep["judge_resident"], keep["judge_after_wake"])
    out["verifier_agreement"] = agreement(keep["verifier_resident"], keep["verifier_after_wake"])
    pr, pw = out["pair_resident"], out["pair_after_wake"]
    out["equal"] = pr["pairs_lost"] == pw["pairs_lost"] and abs(pr["false_block_rate"] - pw["false_block_rate"]) < 1e-9
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--vm", required=True, help="http://<vm ip> (gpu-swap-run.sh behind nginx)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--lang", default="en", choices=mlbench.LANGS)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    vm = Vm(a.vm, os.environ["TB_GPU_KEY"])
    a.out.mkdir(parents=True, exist_ok=True)
    log: dict[str, Any] = {"lang": a.lang, "steps": []}
    runs: dict[str, list[dict[str, Any]]] = {}

    def run(tag: str, name: str, model: str) -> None:
        rows, secs = ask_all(vm, name, model, a.lang, a.workers)
        runs[tag] = rows
        with gzip.open(a.out / f"wake_{tag}_{a.lang}.jsonl.gz", "wt") as fh:
            fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        log["steps"].append({"run": tag, "seconds": secs, "calls": len(rows), "gpu": vm.gpu()})
        print(tag, secs, "s", flush=True)

    def step(what: str, name: str, path: str) -> None:
        log["steps"].append({"swap": f"{name}{path}", "seconds": vm.post(name, path), "gpu": vm.gpu()})
        print(what, log["steps"][-1]["seconds"], "s", flush=True)

    log["judge_up_s"] = vm.wait_up("judge")
    if vm.sleeping("judge"):
        raise SystemExit("the judge has already slept: boot the VM with gpu-swap-run.sh and run this first")
    run("judge_resident", "judge", JUDGE)
    step("judge sleep", "judge", "/sleep?level=1")
    log["verifier_up_s"] = vm.wait_up("verifier")  # the VM starts it now that the card is free
    run("verifier_resident", "verifier", VERIFIER)
    step("verifier sleep", "verifier", "/sleep?level=1")
    step("judge wake", "judge", "/wake_up")
    vm.wait_awake("judge")
    run("judge_after_wake", "judge", JUDGE)
    step("judge sleep", "judge", "/sleep?level=1")
    step("verifier wake", "verifier", "/wake_up")
    vm.wait_awake("verifier")
    run("verifier_after_wake", "verifier", VERIFIER)
    step("verifier sleep", "verifier", "/sleep?level=1")
    step("judge wake", "judge", "/wake_up")  # leave the box as by day: judge awake
    log["summary"] = summarise(runs, a.lang)
    (a.out / f"wake_check_{a.lang}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    s = log["summary"]
    print(
        f"pair lost resident {s['pair_resident']['pairs_lost']}/{s['pair_resident']['trials_open']}, after wake "
        f"{s['pair_after_wake']['pairs_lost']}; judge same {s['judge_agreement']['share']}, verifier same "
        f"{s['verifier_agreement']['share']}; equal={s['equal']}"
    )
    return 0 if s["equal"] else 1


if __name__ == "__main__":
    sys.exit(main())
