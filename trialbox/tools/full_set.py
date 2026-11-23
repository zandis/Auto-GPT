"""The whole existing test set, run three times in a row, each run with a log per stage (rc1 line 1).

The owner's ruling of 2026-11-23: line 1 holds when the whole set (unit, integration, e2e, goldens, the GPU suites)
has run three times back to back with every stage passing, at any time of day, on the B200. This is the one command
for it::

    python -m tools.full_set --out DIR --llm-url http://<vllm>:8000/v1 --llm-model <served name>

* ``DIR/run-N/<stage>.log`` holds everything a stage printed; the console shows one line per stage.
* A run is green only when every stage passed. A stage that could not start (no model endpoint for the GPU suites,
  say) is ``not-run``, and a run with a ``not-run`` stage is red: a missing prerequisite never counts as a pass.
* The runner stops after the first red run, and says so: a red run is fixed, not run again, and the count of green
  runs in a row starts again. ``DIR/summary.json`` and ``DIR/summary.md`` name the commit, each run and each stage.
* ``--list`` prints the stages and their commands; ``--only a,b`` runs those (a partial run is marked and never
  counts as the set).

Costs nothing by itself: no cloud call, no model but the one the endpoint serves. Synthetic and public data only."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = 3
GREEN, RED, NOT_RUN = "passed", "failed", "not-run"


@dataclass(frozen=True)
class Stage:
    name: str
    what: str
    commands: tuple[tuple[str, ...], ...]  # run in order; the first that fails stops the stage
    always: tuple[tuple[str, ...], ...] = ()  # run after, pass or fail (a stack that was started is stopped)
    needs: tuple[str, ...] = ()  # options the stage cannot start without
    env: dict[str, str] = field(default_factory=dict)


def _make(*args: str) -> tuple[str, ...]:
    return ("make", "--no-print-directory", *args)


STAGES: tuple[Stage, ...] = (
    Stage("unit", "the unit suite, every test that needs no stack", (_make("test", "PYTEST_N=auto"),)),
    Stage("pure", "the pure tests with no PostgreSQL", (_make("test-pure", "PYTEST_N=auto"),)),
    Stage("guard", "the tree-reading guard tests", (_make("guard"),)),
    Stage("goldens", "the committed goldens, both lake sources", (_make("goldens-check"),)),
    Stage("e2e-simple", "the build gate: one synthetic hospital, end to end", (_make("e2e-simple"),)),
    Stage("console", "the console tests", (_make("test-console"),)),
    Stage(
        "compose",
        "integration and e2e on the compose test stack, no skip",
        (_make("images"), _make("up-test"), _make("test-compose", "COMPOSE_JUNIT={out}/compose-junit.xml")),
        always=(_make("logs"), _make("down")),
    ),
    Stage("walks", "the five steps-mode walks, no skip", (_make("test-walks"),)),
    Stage(
        "poc",
        "the POC stack and the console POC test",
        (_make("poc"), _make("test-console-e2e")),
        always=(_make("poc-down"),),
    ),
    Stage("perf", "the performance gate at 5,000 patients", (_make("bench-gate", "BENCH_OUT={out}/bench-gate"),)),
    Stage(
        "gpu",
        "the model-quality suites against the real models (marker llm)",
        (
            (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:randomly",
                "-m",
                "llm",
                "tests/llm",
                "tests/unit/test_judge_tier.py",
            ),
        ),
        needs=("llm_url", "llm_model"),
        env={"TB_INTEGRATION": "1"},
    ),
)

Runner = Callable[[Sequence[str], Path, dict[str, str]], int]


def run_command(argv: Sequence[str], log: Path, env: dict[str, str]) -> int:
    """Run ``argv`` from the trialbox folder, everything it prints appended to ``log``."""
    with log.open("ab") as f:
        f.write(f"\n$ {shlex.join(argv)}\n".encode())
        f.flush()
        return subprocess.run(list(argv), cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT, check=False).returncode


def _env(stage: Stage, opts: argparse.Namespace) -> dict[str, str]:
    env = {**os.environ, **stage.env}
    if opts.llm_url:
        env["TB_LLM_EVAL_URL"] = opts.llm_url
    if opts.llm_model:
        env["TB_LLM_EVAL_MODEL"] = opts.llm_model
    env["TB_TEST_ROOT"] = str(Path(opts.out) / "test-root")
    return env


def run_stage(stage: Stage, opts: argparse.Namespace, log_dir: Path, runner: Runner = run_command) -> dict[str, object]:
    log = log_dir / f"{stage.name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    missing = [n for n in stage.needs if not getattr(opts, n, "")]
    if missing:
        log.write_text(f"not run: needs --{', --'.join(m.replace('_', '-') for m in missing)}\n", encoding="utf-8")
        return {"stage": stage.name, "result": NOT_RUN, "why": f"needs {', '.join(missing)}", "seconds": 0.0}
    env, t0 = _env(stage, opts), time.monotonic()
    fill = {"out": str(log_dir)}
    result, rc = GREEN, 0
    for argv in stage.commands:
        rc = runner([a.format(**fill) for a in argv], log, env)
        if rc != 0:
            result = RED
            break
    for argv in stage.always:
        runner([a.format(**fill) for a in argv], log, env)
    return {
        "stage": stage.name,
        "result": result,
        "rc": rc,
        "seconds": round(time.monotonic() - t0, 1),
        "log": str(log),
    }


def head() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return r.stdout.strip()


def render(summary: dict[str, object]) -> str:
    lines = [
        f"# The whole set, {summary['runs_green_in_a_row']} of {summary['runs_wanted']} runs green in a row",
        "",
        f"Commit `{summary['commit']}`. Partial: {summary['partial']}. {summary['verdict']}",
        "",
        "| run | stage | result | seconds |",
        "| --- | --- | --- | ---: |",
    ]
    for n, run in enumerate(summary["runs"], 1):  # type: ignore[arg-type]
        for s in run["stages"]:
            lines.append(f"| {n} | {s['stage']} | {s['result']} | {s['seconds']} |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None, runner: Runner = run_command) -> int:
    ap = argparse.ArgumentParser(prog="tools.full_set", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="full-set", help="the folder of the run logs and the summary")
    ap.add_argument("--runs", type=int, default=RUNS, help="runs in a row (the ruling: 3)")
    ap.add_argument("--only", default="", help="comma list of stages; a partial run never counts as the set")
    ap.add_argument("--llm-url", dest="llm_url", default="", help="the vLLM endpoint of the GPU suites")
    ap.add_argument("--llm-model", dest="llm_model", default="", help="the served model name of the GPU suites")
    ap.add_argument("--list", action="store_true", help="print the stages and their commands, run nothing")
    a = ap.parse_args(argv)
    names = [n for n in a.only.split(",") if n]
    bad = sorted(set(names) - {s.name for s in STAGES})
    if bad:
        raise SystemExit(f"unknown stage: {', '.join(bad)} (--list shows them)")
    stages = [s for s in STAGES if not names or s.name in names]
    if a.list:
        for s in STAGES:
            print(f"{s.name}: {s.what}")
            for c in (*s.commands, *s.always):
                print("   " + shlex.join(c))
        return 0
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    a.out = str(out)
    runs: list[dict[str, object]] = []
    in_a_row = 0
    for n in range(1, a.runs + 1):
        results = []
        for st in stages:
            r = run_stage(st, a, out / f"run-{n}", runner)
            results.append(r)
            print(f"run {n}  {st.name:<11} {r['result']:<8} {r['seconds']} s", flush=True)
        green = all(r["result"] == GREEN for r in results)
        runs.append({"run": n, "green": green, "stages": results})
        if not green:
            break
        in_a_row += 1
    partial = bool(names)
    done = in_a_row == a.runs and not partial
    verdict = (
        "All runs green: the set ran in full."
        if done
        else (
            "Partial run: it does not count as the set."
            if partial and in_a_row == a.runs
            else f"Run {len(runs)} was red: fix it, then start the count again."
        )
    )
    summary = {
        "commit": head(),
        "runs_wanted": a.runs,
        "runs_green_in_a_row": in_a_row,
        "partial": partial,
        "verdict": verdict,
        "runs": runs,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out / "summary.md").write_text(render(summary), encoding="utf-8")
    print(verdict, f"Logs and summary in {out}")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
