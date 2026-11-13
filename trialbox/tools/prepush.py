"""PREPUSH (process review 2026-11-13): CI's fast tier on this machine, in one command, before a push.

A push to a pull request runs the fast tier (``changes``, ``checks``, ``data-scan``, ``cross-card``, ``powershell``,
``differential``; D-564). On 2026-11-12 a red that a local run would have shown reached CI several times, because
the local lists in CONTRIBUTING.md, DEVELOPING.md, ``make lint`` and ``make ci`` each left out a step of ``checks``
(``make lint`` and ``make ci`` have no limits lint). This tool runs every step of ``checks`` and the fast-tier jobs,
plus the owner's own local set (the security scans), each with its output in a file, and every step runs even when an
earlier one failed, as in CI. ``tests/unit/test_prepush.py`` fails when CI's ``checks`` job gains a step this list
lacks, so the two cannot drift apart.

    python -m tools.prepush                      # everything; exit 0 only when every step passed and none skipped
    python -m tools.prepush --tests tests/unit/test_x.py tests/unit/test_y.py   # and the tests you touched
    python -m tools.prepush --only mypy,limits-lint
    python -m tools.prepush --list

Exit codes: 0 all passed; 1 a step failed; 2 none failed but a step was skipped (a tool is not installed here), so
the run is not CI's fast tier. The result is written to ``.cache/prepush/<HEAD sha>/summary.json``;
``tools.train_ready`` reads it. A step's log is beside it: read the file, never pipe a check into ``tail``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ".venv/bin/python"
TEST_ENV = {"TB_ENV": "DEV", "TB_TZ": "Asia/Taipei"}
CADDY_PRINT = (
    "TB_MD_TB_DOMAIN=poc.example.org TB_MD_TB_IMAGE=r.example.org/demo@sha256:"
    + "0" * 64
    + " bash deploy/gcp/hosted-demo-startup.sh --print-caddyfile > {tmp}/Caddyfile && "
    "pin=$(sed -n 's/^CADDY_IMAGE_PIN=\"\\(.*\\)\"$/\\1/p' deploy/gcp/hosted-demo-startup.sh) && "
    'docker run --rm -v "{tmp}/Caddyfile:/etc/caddy/Caddyfile:ro" "$pin" '
    "caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile"
)


@dataclass(frozen=True)
class Step:
    """One check. ``ci`` names where CI runs it: ``checks:<step name prefix>`` or ``job:<job name>``, or ``owner``
    for the owner's local set that CI runs only in the full tier, or ``supply-chain:lock``."""

    key: str
    ci: str
    shell: str
    needs: tuple[str, ...] = ()
    #: a shell test that must pass first, and what is missing when it does not (skipped, not failed)
    ready: tuple[str, str] = ("", "")
    slow: bool = False
    env: dict[str, str] = field(default_factory=dict)


STEPS: tuple[Step, ...] = (
    Step("ruff", "checks:ruff", f"{PY} -m ruff check . && {PY} -m ruff format --check ."),
    Step(
        "actionlint",
        "checks:actionlint",
        "actionlint -color ../.github/workflows/trialbox-*.yml",
        needs=("actionlint",),
    ),
    Step("mypy", "checks:mypy", f"{PY} -m mypy libs services tools tests", slow=True),
    Step("doclint", "checks:doclint", f"{PY} tools/doclint.py"),
    Step("decision-numbers", "checks:decision numbers", f"{PY} -m tools.decisions_index --check"),
    Step("licence-register", "checks:licence register", f"{PY} -m tools.licence_register --check"),
    Step("limits-lint", "checks:limits lint", f"{PY} -m tools.limits_lint"),
    Step("contracts", "checks:generated contracts", "make contracts-check"),
    Step("rulesets", "checks:shipped rulesets", f"{PY} -m tools.build_rulesets --check", env=TEST_ENV),
    Step("traceability", "checks:traceability", f"{PY} tools/gen_traceability.py --check"),
    Step(
        "shellcheck",
        "checks:shellcheck",
        "git ls-files -z '*.sh' | xargs -0 shellcheck --severity=warning --format=gcc",
        needs=("shellcheck",),
    ),
    Step(
        "poc-host",
        "checks:PoC host scripts",
        "shellcheck --severity=warning deploy/gcp/poc-host.sh deploy/gcp/hosted-demo-startup.sh && " + CADDY_PRINT,
        needs=("shellcheck", "docker"),
        ready=("docker info", "a running Docker daemon (the Caddyfile is validated in caddy's pinned image)"),
    ),
    Step("data-scan", "job:data-scan", "make data-scan"),
    Step("cross-card", "job:cross-card", "make cross-card PYTEST_N=auto", slow=True),
    Step(
        "differential",
        "job:differential",
        "make differential",
        needs=("java",),
        ready=(
            f"{PY} -c 'import sys, tools.cql_eval as c; sys.exit(0 if c.available() else 1)'",
            "the local CQL engine (python -m tools.cql_eval --fetch)",
        ),
        slow=True,
    ),
    Step("powershell", "job:powershell", "pwsh -NoProfile -File tests/windows/run-pester.ps1", needs=("pwsh",)),
    # the offline steps of trialbox-supply-chain.yml's `lock` job, which runs on a pull request that touches the lock,
    # the Makefile, deploy/ or a workflow; pip-audit and the licence gate need the network and the scanners: CI's
    Step(
        "supply-chain",
        "supply-chain:lock",
        f"make lock-check allowlist-check && {PY} -m pytest -q -p no:cacheprovider -n 0 tests/unit/test_supply_chain.py",
        env=TEST_ENV,
    ),
    Step("secret-scan", "owner", f"{PY} -m tools.security_scan secrets"),
    Step("sast", "owner", f"{PY} -m tools.security_scan sast"),
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def missing_tools(step: Step) -> list[str]:
    return [t for t in step.needs if shutil.which(t) is None]


def run_step(step: Step, log: Path, tmp: Path) -> tuple[str, float]:
    """Run one step with its output in ``log``; ``passed``, ``failed`` or ``skipped: <tools>``."""
    gone = missing_tools(step)
    if gone:
        log.write_text(f"skipped: not installed here: {', '.join(gone)}\n", encoding="utf-8")
        return f"skipped: {', '.join(gone)} not installed", 0.0
    env = {**os.environ, "PYTHONPATH": "libs:services:.", **step.env}
    test, what = step.ready
    if test and subprocess.run(["bash", "-c", test], cwd=ROOT, env=env, capture_output=True, check=False).returncode:
        log.write_text(f"skipped: not here: {what}\n", encoding="utf-8")
        return f"skipped: {what.split(' (')[0]} missing", 0.0
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as out:
        rc = subprocess.run(
            ["bash", "-o", "pipefail", "-c", step.shell.format(tmp=tmp)],
            cwd=ROOT,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode
    return ("passed" if rc == 0 else f"failed (exit {rc})"), time.monotonic() - started


def tests_step(paths: list[str]) -> Step:
    return Step(
        "tests",
        "owner",
        f"{PY} -m pytest -p no:cacheprovider -n 0 -q " + " ".join(paths),
        env=TEST_ENV,
    )


def select(only: str, skip_slow: bool) -> list[Step]:
    keys = {k.strip() for k in only.split(",") if k.strip()}
    unknown = keys - {s.key for s in STEPS} - {"tests"}
    if unknown:
        raise SystemExit(f"prepush: unknown step(s): {', '.join(sorted(unknown))} (see --list)")
    return [s for s in STEPS if (not keys or s.key in keys) and not (skip_slow and s.slow)]


def exit_code(results: dict[str, str]) -> int:
    if any(r.startswith("failed") for r in results.values()):
        return 1
    if any(r.startswith("skipped") for r in results.values()):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.prepush", description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", default="", help="comma-separated step keys")
    ap.add_argument("--quick", action="store_true", help="leave out the slow steps (not enough before a push)")
    ap.add_argument("--tests", nargs="*", default=[], help="test files you touched, run as the owner's set asks")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="directory for the logs (default .cache/prepush/<sha>)")
    args = ap.parse_args(argv)

    steps = select(args.only, args.quick)
    if args.tests:
        steps.append(tests_step(args.tests))
    if args.list:
        for s in STEPS:
            print(f"{s.key:18} {s.ci:32} needs: {', '.join(s.needs) or '-'}{'  (slow)' if s.slow else ''}")
        return 0

    head = git("rev-parse", "HEAD") or "no-git"
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    out = args.out or ROOT / ".cache" / "prepush" / head
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for i, step in enumerate(steps, 1):
        result, seconds = run_step(step, out / f"{i:02d}-{step.key}.log", out)
        results[step.key] = result
        print(f"{step.key:18} {result:34} {seconds:6.0f} s   {out / f'{i:02d}-{step.key}.log'}", flush=True)

    complete = not args.only and not args.quick
    summary = {"head": head, "dirty": dirty, "complete": complete, "results": results}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    code = exit_code(results)
    verdict = {0: "all passed", 1: "FAILED: read the logs above", 2: "passed, but not CI's fast tier: steps skipped"}
    print(f"prepush: {verdict[code]}{' (tree has uncommitted changes)' if dirty else ''}; {out / 'summary.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
