"""PREPUSH (process review 2026-11-13): ``tools.prepush`` runs what CI's fast tier runs, with the same command line and
the same environment. A step added to ``checks``, a step or an environment variable added to a fast-tier job, or a
command changed on one side only, fails here until the two agree, so a red a local run could show does not first
appear in CI (billed minutes, a lost push)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import prepush

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
CI = WORKFLOWS / "trialbox-ci.yml"
SUPPLY = WORKFLOWS / "trialbox-supply-chain.yml"
FULL_GATE = "needs.changes.outputs.full == 'true'"
#: the same check by another command: CI runs actionlint and caddy in containers, and installs the Pester modules
#: first; the needle must stay in CI's command
OTHER_COMMAND = {"actionlint": "rhysd/actionlint:", "poc-host": "caddy validate", "powershell": "run-pester.ps1"}
#: steps of a fast job that prepare the runner, not checks
SETUP_RUN = re.compile(r"^(make venv|tools/ci_postgres\.sh)\b")
SETUP_NAME = ("Python environment", "Local CQL engine")

pytestmark = pytest.mark.nodb


def _jobs(path: Path = CI) -> dict[str, Any]:
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _norm(run: str) -> str:
    return " ".join(run.split()).replace(prepush.PY, ".venv/bin/python")


def _checks() -> dict[str, dict[str, Any]]:
    out = {}
    for s in _jobs()["checks"]["steps"]:
        if "uses" in s:
            continue
        assert "name" in s, f"an unnamed run step in CI's checks job: {s}"
        if not s["name"].startswith(SETUP_NAME):
            out[s["name"]] = s
    return out


def _local(kind: str) -> dict[str, prepush.Step]:
    return {s.ci.split(":", 1)[1]: s for s in prepush.STEPS if s.ci.startswith(kind + ":")}


def test_the_checks_job_and_the_local_list_name_the_same_steps() -> None:
    assert set(_checks()) == set(_local("checks"))


def test_each_checks_step_runs_ci_s_command_line() -> None:
    checks = _checks()
    for name, step in _local("checks").items():
        run = _norm(checks[name]["run"])
        if step.key in OTHER_COMMAND:
            assert OTHER_COMMAND[step.key] in run, step.key
        else:
            assert run == _norm(step.shell), f"{step.key}: CI runs `{run}`, prepush `{_norm(step.shell)}`"
        assert not checks[name].get("env"), f"{name}: CI gives the step an env block; give its twin the same"


def test_every_fast_tier_job_runs_locally_with_ci_s_command_and_environment() -> None:
    jobs = _jobs()
    fast = {n for n, j in jobs.items() if FULL_GATE not in str(j.get("if", ""))} - {"changes", "checks"}
    local = _local("job")
    assert fast == set(local)
    for name, step in local.items():
        steps = [
            s
            for s in jobs[name]["steps"]
            if "run" in s and not SETUP_RUN.match(s["run"].strip()) and not s.get("name", "").startswith(SETUP_NAME)
        ]
        assert len(steps) == 1, f"{name}: CI's job has checks {[s.get('name') for s in steps]}; prepush runs one"
        run = _norm(steps[0]["run"])
        if step.key in OTHER_COMMAND:
            assert OTHER_COMMAND[step.key] in run, name
        else:
            assert run.startswith(_norm(step.shell)), f"{name}: CI runs `{run}`, prepush `{_norm(step.shell)}`"
        ci_env = {**jobs[name].get("env", {}), **steps[0].get("env", {})}
        assert set(ci_env) == set(step.env), f"{name}: CI sets {sorted(ci_env)}, prepush {sorted(step.env)}"


def test_the_offline_steps_of_the_supply_chain_lock_job_run_locally() -> None:
    runs = [_norm(s["run"]) for s in _jobs(SUPPLY)["lock"]["steps"] if "run" in s]
    step = next(s for s in prepush.STEPS if s.ci == "supply-chain:lock")
    for part in _norm(step.shell).split(" && "):
        assert part in runs, f"CI's lock job no longer runs `{part}`"


def test_the_workflow_sets_no_environment_prepush_would_lack() -> None:
    env = yaml.safe_load(CI.read_text(encoding="utf-8")).get("env", {})
    assert set(env) <= {"TB_SCRATCH"}, f"a new workflow-wide setting: {env}"  # TB_SCRATCH has a local default


def test_keys_are_unique_and_settings_set_by_hand_are_not_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [s.key for s in prepush.STEPS]
    assert len(keys) == len(set(keys))
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    monkeypatch.setenv("TB_ENV", "DEV")
    assert "TB_TZ" not in prepush.base_env() and "TB_ENV" not in prepush.base_env()


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
    ok = prepush.Step("ok", "owner", "echo fine ${HOME:+home}")
    bad = prepush.Step("bad", "owner", "echo broken; exit 3")
    gone = prepush.Step("gone", "owner", "true", needs=("tb-no-such-tool-anywhere",))
    assert prepush.run_step(ok, tmp_path / "ok.log", tmp_path)[0] == "passed"
    assert prepush.run_step(bad, tmp_path / "bad.log", tmp_path)[0] == "failed (exit 3)"
    assert prepush.run_step(gone, tmp_path / "gone.log", tmp_path)[0].startswith("skipped")
    assert (tmp_path / "ok.log").read_text(encoding="utf-8") == "fine home\n"
    assert "broken" in (tmp_path / "bad.log").read_text(encoding="utf-8")


def test_a_pipe_fails_when_its_first_command_fails(tmp_path: Path) -> None:
    result = prepush.run_step(prepush.Step("p", "owner", "false | cat"), tmp_path / "p.log", tmp_path)[0]
    assert result.startswith("failed")


def test_a_step_whose_input_is_missing_is_skipped_not_failed(tmp_path: Path) -> None:
    step = prepush.Step("needs-input", "owner", "exit 9", ready=("false", "an input (fetch it)"))
    assert prepush.run_step(step, tmp_path / "n.log", tmp_path)[0] == "skipped: an input missing"


def test_no_readiness_test_imports_project_code() -> None:
    for s in prepush.STEPS:
        assert "import" not in s.ready[0] and "-m tools" not in s.ready[0], s.key


def test_main_writes_the_summary_train_ready_reads(tmp_path: Path) -> None:
    code = prepush.main(["--only", "decision-numbers", "--out", str(tmp_path)])
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["complete"] is False and summary["tests"] == []
    assert code == (0 if summary["results"]["decision-numbers"] == "passed" else 1)


def test_an_unknown_step_is_refused() -> None:
    with pytest.raises(SystemExit):
        prepush.select("no-such-step", skip_slow=False)
