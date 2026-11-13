"""PREPUSH (process review 2026-11-13): CI's fast tier on this machine, in one command, before a push.

A push to a pull request runs the fast tier (``changes``, ``checks``, ``data-scan``, ``cross-card``, ``powershell``,
``differential``; D-564) and, when the lock, the Makefile, ``deploy/`` or a workflow changed, the supply chain's
``lock`` job. On 2026-11-12 a red that a local run would have shown reached CI several times, because the local lists
in CONTRIBUTING.md, DEVELOPING.md, ``make lint`` and ``make ci`` each left out a step (none has the limits lint). This
tool runs each of those steps with CI's own command line and environment, plus the owner's local set (the security
scans, the tests you touched), each into a log file. Every step runs even when an earlier one failed, as in CI.
``tests/unit/test_prepush.py`` fails when a CI step and its local twin differ, so the two cannot drift apart.

    python -m tools.prepush --tests tests/unit/test_x.py      # everything, and the tests you touched
    python -m tools.prepush --only mypy,limits-lint
    python -m tools.prepush --list

Exit codes: 0 all passed; 1 a step failed; 2 none failed but a step was skipped (its tool or input is not on this
machine), so the run is not all of CI's fast tier. The result is ``.cache/prepush/<HEAD sha>/summary.json``;
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
TMP = "@TMP@"  # replaced by the run's log directory
#: settings a person exports for a single test run (CLAUDE.md); CI's fast-tier jobs have none of them
NOT_INHERITED = ("TB_ENV", "TB_TZ", "PYTHONPATH")
PATHS = "PYTHONPATH=libs:services:."


@dataclass(frozen=True)
class Step:
    """One check. ``ci`` is where CI runs it (``checks:<step name>``, ``job:<job name>``, ``supply-chain:lock``) or
    ``owner`` (the owner's local set). ``shell`` is CI's command line, environment prefix included; ``env`` holds the
    step's own environment block in CI. ``ready`` is a shell test and what is missing when it fails (then the step is
    skipped, not failed); it must not import project code, so a broken module fails its step instead of hiding it."""

    key: str
    ci: str
    shell: str
    needs: tuple[str, ...] = ()
    ready: tuple[str, str] = ("", "")
    env: dict[str, str] = field(default_factory=dict)
    slow: bool = False


STEPS: tuple[Step, ...] = (
    Step("ruff", "checks:ruff", f"{PY} -m ruff check . && {PY} -m ruff format --check ."),
    Step(
        "actionlint",
        "checks:actionlint (the workflows themselves)",
        "actionlint -color ../.github/workflows/trialbox-*.yml",
        needs=("actionlint",),
    ),
    Step("mypy", "checks:mypy (strict)", f"{PY} -m mypy libs services tools tests", slow=True),
    Step(
        "doclint",
        "checks:doclint (the eight documents; link and path problems are warnings, D-311)",
        f"{PY} tools/doclint.py",
    ),
    Step(
        "decision-numbers",
        "checks:decision numbers (one number, one text; registry rows are notes only; D-306, D-311)",
        f"{PY} -m tools.decisions_index --check",
    ),
    Step(
        "licence-register",
        "checks:licence register (every shipped data file has a row; no SNOMED CT; model licence rows; T-617b, D-342)",
        f"{PATHS} {PY} -m tools.licence_register --check",
    ),
    Step(
        "limits-lint",
        "checks:limits lint (every timeout over 60 s and every LIMIT literal in services/ has a reason; OD-10, T-687, "
        "D-471)",
        f"{PATHS} {PY} -m tools.limits_lint",
    ),
    Step(
        "contracts",
        "checks:generated contracts are what the schemas generate (no hand edit)",
        "make contracts-check",
    ),
    Step(
        "rulesets",
        "checks:shipped rulesets are what the compiler gives (ValueSets, SQL, CQL; T-613a, D-322)",
        f"TB_ENV=DEV TB_TZ=Asia/Taipei {PATHS} {PY} -m tools.build_rulesets --check",
    ),
    Step(
        "traceability",
        "checks:traceability CSV (warnings only, never blocks a merge; D-311)",
        f"{PY} tools/gen_traceability.py --check",
    ),
    Step(
        "shellcheck",
        "checks:shellcheck",
        "git ls-files -z '*.sh' | xargs -0 shellcheck --severity=warning --format=gcc",
        needs=("shellcheck",),
    ),
    Step(
        "poc-host",
        "checks:PoC host scripts and Caddyfile",
        "shellcheck --severity=warning deploy/gcp/poc-host.sh deploy/gcp/hosted-demo-startup.sh && "
        "TB_MD_TB_DOMAIN=poc.example.org TB_MD_TB_IMAGE=r.example.org/demo@sha256:" + "0" * 64 + " "
        f"bash deploy/gcp/hosted-demo-startup.sh --print-caddyfile > {TMP}/Caddyfile && "
        "pin=$(sed -n 's/^CADDY_IMAGE_PIN=\"\\(.*\\)\"$/\\1/p' deploy/gcp/hosted-demo-startup.sh) && "
        f'docker run --rm -v "{TMP}/Caddyfile:/etc/caddy/Caddyfile:ro" "$pin" '
        "caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile",
        needs=("shellcheck", "docker"),
        ready=("docker info", "a running Docker daemon"),
    ),
    Step("data-scan", "job:data-scan", "make data-scan"),
    Step(
        "cross-card",
        "job:cross-card",
        "make cross-card PYTEST_N=auto",
        env={"TB_DATA_DIR": f"{TMP}/tb-data"},
        slow=True,
    ),
    Step(
        "differential",
        "job:differential",
        "make differential",
        needs=("java",),
        ready=(
            'ls "$TB_CQL_LOCAL_LIB"/cqf-fhir-cql-*.jar',
            "the local CQL engine (python -m tools.cql_eval --fetch)",
        ),
        env={"TB_CQL_LOCAL_LIB": ".cache/jvm/cql-local/lib"},
        slow=True,
    ),
    Step("powershell", "job:powershell", "pwsh -NoProfile -File ./tests/windows/run-pester.ps1", needs=("pwsh",)),
    # the offline steps of trialbox-supply-chain.yml's `lock` job; pip-audit and the licence gate need the network
    # and the scanners, and stay CI's
    Step(
        "supply-chain",
        "supply-chain:lock",
        f"make lock-check && make allowlist-check && {PY} -m pytest -q tests/unit/test_supply_chain.py",
    ),
    Step("secret-scan", "owner", f"{PY} -m tools.security_scan secrets"),
    Step("sast", "owner", f"{PY} -m tools.security_scan sast"),
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in NOT_INHERITED}


def run_step(step: Step, log: Path, tmp: Path) -> tuple[str, float]:
    """Run one step with its output in ``log``: ``passed``, ``failed (exit n)`` or ``skipped: <what>``."""
    gone = [t for t in step.needs if shutil.which(t) is None]
    if gone:
        log.write_text(f"skipped: not installed here: {', '.join(gone)}\n", encoding="utf-8")
        return f"skipped: {', '.join(gone)} not installed", 0.0
    env = {**base_env(), **{k: v.replace(TMP, str(tmp)) for k, v in step.env.items()}}
    test, what = step.ready
    if test and subprocess.run(["bash", "-c", test], cwd=ROOT, env=env, capture_output=True, check=False).returncode:
        log.write_text(f"skipped: not here: {what}\n", encoding="utf-8")
        return f"skipped: {what.split(' (')[0]} missing", 0.0
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as out:
        rc = subprocess.run(
            ["bash", "-o", "pipefail", "-c", step.shell.replace(TMP, str(tmp))],
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
        f"TB_ENV=DEV TB_TZ=Asia/Taipei {PATHS} {PY} -m pytest -p no:cacheprovider -n 0 -q " + " ".join(paths),
    )


def select(only: str, skip_slow: bool) -> list[Step]:
    keys = {k.strip() for k in only.split(",") if k.strip()}
    unknown = keys - {s.key for s in STEPS}
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
    ap.add_argument("--tests", nargs="*", default=[], help="the test files you touched")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="directory for the logs (default .cache/prepush/<sha>)")
    args = ap.parse_args(argv)

    if args.list:
        for s in STEPS:
            print(f"{s.key:18} needs: {', '.join(s.needs) or '-':22} {s.ci[:70]}")
        return 0
    steps = select(args.only, args.quick)
    if args.tests:
        steps.append(tests_step(args.tests))

    head = git("rev-parse", "HEAD") or "no-git"
    dirty = bool(git("status", "--porcelain"))  # untracked files count: a module never added passes here, not in CI
    out = args.out or ROOT / ".cache" / "prepush" / head
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for i, step in enumerate(steps, 1):
        log = out / f"{i:02d}-{step.key}.log"
        result, seconds = run_step(step, log, out)
        results[step.key] = result
        print(f"{step.key:18} {result:40} {seconds:6.0f} s   {log}", flush=True)

    complete = not args.only and not args.quick
    summary = {"head": head, "dirty": dirty, "complete": complete, "tests": args.tests, "results": results}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    code = exit_code(results)
    verdict = {0: "all passed", 1: "FAILED: read the logs above", 2: "passed, but steps were skipped (not CI's tier)"}
    print(f"prepush: {verdict[code]}{' (uncommitted or untracked files)' if dirty else ''}; {out / 'summary.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
