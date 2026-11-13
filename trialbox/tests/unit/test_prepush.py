"""PREPUSH (process review 2026-11-13): ``tools.prepush`` runs what CI's fast tier runs. A step added to the ``checks``
job, or a job added to the fast tier, fails here until the local list has it, so a red that a local run could show
does not first appear in CI (billed minutes, a lost push)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import prepush

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"
SUPPLY = ROOT.parent / ".github" / "workflows" / "trialbox-supply-chain.yml"
FULL_GATE = "needs.changes.outputs.full == 'true'"
#: run by another means here: CI runs actionlint in a container and caddy in its pinned image; the local step calls
#: the installed actionlint and the same pinned caddy image
SAME_CHECK_OTHER_COMMAND = {"actionlint", "poc-host"}
#: CI-only steps of ``checks``: the set-up, not a check
SETUP = ("Python environment",)

pytestmark = pytest.mark.nodb


def _jobs() -> dict[str, Any]:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _checks_steps() -> dict[str, str]:
    steps = _jobs()["checks"]["steps"]
    return {s["name"]: s.get("run", "") for s in steps if "name" in s and not s["name"].startswith(SETUP)}


def _local(kind: str) -> dict[str, prepush.Step]:
    return {s.ci.split(":", 1)[1]: s for s in prepush.STEPS if s.ci.startswith(kind + ":")}


def test_every_step_of_the_checks_job_runs_locally() -> None:
    local = _local("checks")
    missing = [n for n in _checks_steps() if not any(n.startswith(prefix) for prefix in local)]
    assert not missing, f"CI's checks job has steps tools/prepush.py does not run: {missing}"


def test_no_local_checks_step_names_a_step_ci_no_longer_has() -> None:
    names = list(_checks_steps())
    stale = [p for p in _local("checks") if not any(n.startswith(p) for n in names)]
    assert not stale, stale


def test_the_local_command_is_ci_s_command() -> None:
    ci = _checks_steps()
    for prefix, step in _local("checks").items():
        if step.key in SAME_CHECK_OTHER_COMMAND:
            continue
        run = next(r for n, r in ci.items() if n.startswith(prefix))
        local = step.shell.replace(prepush.PY, ".venv/bin/python")
        assert local in run, f"{step.key}: local `{local}` is not CI's `{run.strip()}`"


def test_every_fast_tier_job_runs_locally() -> None:
    fast = {n for n, j in _jobs().items() if FULL_GATE not in str(j.get("if", ""))} - {"changes", "checks"}
    assert fast == set(_local("job")), "the fast tier's jobs and tools/prepush.py's job steps differ"


def test_keys_are_unique() -> None:
    keys = [s.key for s in prepush.STEPS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    ("results", "code"),
    [
        ({"a": "passed"}, 0),
        ({"a": "passed", "b": "skipped: pwsh not installed"}, 2),
        ({"a": "failed (exit 1)", "b": "skipped: x not installed"}, 1),
    ],
)
def test_exit_code(results: dict[str, str], code: int) -> None:
    assert prepush.exit_code(results) == code


def test_a_step_runs_writes_its_log_and_a_failure_does_not_stop_the_next(tmp_path: Path) -> None:
    ok = prepush.Step("ok", "owner", "echo fine")
    bad = prepush.Step("bad", "owner", "echo broken; false | true; exit 3")
    gone = prepush.Step("gone", "owner", "true", needs=("tb-no-such-tool-anywhere",))
    assert prepush.run_step(ok, tmp_path / "ok.log", tmp_path)[0] == "passed"
    assert prepush.run_step(bad, tmp_path / "bad.log", tmp_path)[0] == "failed (exit 3)"
    assert prepush.run_step(gone, tmp_path / "gone.log", tmp_path)[0].startswith("skipped")
    assert (tmp_path / "ok.log").read_text(encoding="utf-8") == "fine\n"
    assert "broken" in (tmp_path / "bad.log").read_text(encoding="utf-8")


def test_a_pipe_fails_when_its_first_command_fails(tmp_path: Path) -> None:
    piped = prepush.Step("piped", "owner", "false | cat")
    assert prepush.run_step(piped, tmp_path / "p.log", tmp_path)[0].startswith("failed")


def test_main_writes_the_summary_train_ready_reads(tmp_path: Path) -> None:
    code = prepush.main(["--only", "decision-numbers", "--out", str(tmp_path)])
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is False
    assert set(summary["results"]) == {"decision-numbers"}
    assert code == (0 if summary["results"]["decision-numbers"] == "passed" else 1)


def test_an_unknown_step_is_refused() -> None:
    with pytest.raises(SystemExit):
        prepush.select("no-such-step", skip_slow=False)


def test_a_step_whose_input_is_missing_is_skipped_not_failed(tmp_path: Path) -> None:
    step = prepush.Step("needs-input", "owner", "exit 9", ready=("false", "an input (fetch it)"))
    assert prepush.run_step(step, tmp_path / "n.log", tmp_path)[0] == "skipped: an input missing"


def test_the_offline_steps_of_the_supply_chain_lock_job_run_locally() -> None:
    doc = yaml.safe_load(SUPPLY.read_text(encoding="utf-8"))
    runs = " ".join(s.get("run", "") for s in doc["jobs"]["lock"]["steps"])
    step = next(s for s in prepush.STEPS if s.ci == "supply-chain:lock")
    for needle in ("make lock-check", "make allowlist-check", "-m pytest -q tests/unit/test_supply_chain.py"):
        assert needle in runs, f"CI's lock job no longer runs `{needle}`: change tools/prepush.py with it"
    assert "lock-check" in step.shell and "allowlist-check" in step.shell and "test_supply_chain.py" in step.shell
