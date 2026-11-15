"""TB_RUNNER: which CI jobs may use the self-hosted runner, and which must not.

Repository variable ``TB_RUNNER`` set to ``trialbox`` selects the labels ``self-hosted``, ``Linux``, ``ARM64`` and
``trialbox``. Unset, or any other value, keeps the GitHub-hosted image that job uses today. A ``pull_request`` whose
head repository is not this repository stays on that image even when the variable is ``trialbox``.

A fork can still edit the workflow and delete the check: the expression is the guard inside the file GitHub runs, and
it is not a substitute for requiring approval of fork workflows while the repository is public. ``scale-50k`` and the
image gates stay on GitHub-hosted runners (the scale job needs systemd cgroups and a large disk; the image jobs run
``docker builder prune -af``). There is no ``trialbox-rehearse-box`` workflow (D-570).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
LABELS = '["self-hosted","Linux","ARM64","trialbox"]'

#: job -> GitHub-hosted image used when TB_RUNNER is not exactly trialbox, and for a fork pull request
HEAVY: dict[str, dict[str, str]] = {
    "trialbox-ci.yml": {
        "unit-shard": "ubuntu-24.04",
        "e2e-simple": "ubuntu-24.04",
        "goldens": "ubuntu-24.04",
        "demo-boot": "ubuntu-latest",
    },
    "trialbox-e2e.yml": {
        "nightly": "ubuntu-24.04",
        "random-order": "ubuntu-24.04",
        "compose": "ubuntu-24.04",
    },
    "trialbox-nightly-quality.yml": {
        "mutation": "ubuntu-24.04",
        "branch-coverage-shard": "ubuntu-24.04",
    },
}
#: jobs that stay on a GitHub-hosted runner no matter how TB_RUNNER is set
STAY: dict[str, set[str]] = {
    "trialbox-ci.yml": {
        "changes",
        "checks",
        "standards",
        "unit",
        "cross-card",
        "property",
        "differential",
        "goldens-gate",
        "e2e-simple-gate",
        "data-scan",
        "security",
        "powershell",
        "images",
    },
    "trialbox-e2e.yml": {"scale-50k"},
    "trialbox-nightly-quality.yml": {"mutation-score", "branch-coverage"},
    "trialbox-images.yml": {"images", "multiarch"},
    "trialbox-identity.yml": {"overlay"},
    "trialbox-supply-chain.yml": {"lock"},
}
TIMEOUTS = {
    ("trialbox-ci.yml", "unit-shard"): 70,
    ("trialbox-ci.yml", "e2e-simple"): 40,
    ("trialbox-ci.yml", "goldens"): 40,
    ("trialbox-ci.yml", "demo-boot"): 90,
    ("trialbox-e2e.yml", "nightly"): 90,
    ("trialbox-e2e.yml", "random-order"): 70,
    ("trialbox-e2e.yml", "compose"): 240,
    ("trialbox-e2e.yml", "scale-50k"): 340,
    ("trialbox-nightly-quality.yml", "mutation"): 300,
    ("trialbox-nightly-quality.yml", "branch-coverage-shard"): 120,
}
PUBLISHED_4000 = re.compile(r"-p\s+\S*4000\b|127\.0\.0\.1:4000\b|0\.0\.0\.0:4000\b|:4000:")

pytestmark = pytest.mark.nodb


def _wf(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    jobs = doc["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def runner_expr(hosted: str) -> str:
    """Fork first, then TB_RUNNER=trialbox, then the hosted image. fromJSON keeps runs-on an array either way."""
    hosted_json = f"'[\"{hosted}\"]'"
    # close fromJSON's parenthesis and the ${{ }} together (two braces; an f-string would eat one)
    close = ") }}"
    return (
        "${{ fromJSON( (github.event_name == 'pull_request' && "
        "github.event.pull_request.head.repo.full_name != github.repository) && "
        f"{hosted_json} || (vars.TB_RUNNER == 'trialbox' && '{LABELS}') || {hosted_json} {close}"
    )


def test_every_trialbox_job_is_heavy_or_stays_hosted() -> None:
    names = {p.name for p in WORKFLOWS.glob("trialbox-*.yml")}
    assert names == set(HEAVY) | set(STAY)
    for name in sorted(names):
        jobs = set(_wf(name))
        assert jobs == set(HEAVY.get(name, {})) | STAY.get(name, set()), name


def test_heavy_jobs_select_the_runner_and_keep_a_fork_on_github() -> None:
    for name, jobs in HEAVY.items():
        loaded = _wf(name)
        for job, hosted in jobs.items():
            assert loaded[job]["runs-on"] == runner_expr(hosted), job
            assert loaded[job]["timeout-minutes"] == TIMEOUTS[(name, job)]


def test_the_other_jobs_do_not_read_the_variable() -> None:
    for name, jobs in STAY.items():
        loaded = _wf(name)
        for job in jobs:
            runs_on = str(loaded[job]["runs-on"])
            assert "TB_RUNNER" not in runs_on and "self-hosted" not in runs_on, (name, job)
    assert _wf("trialbox-e2e.yml")["scale-50k"]["runs-on"] == "ubuntu-24.04"
    assert _wf("trialbox-e2e.yml")["scale-50k"]["timeout-minutes"] == TIMEOUTS[("trialbox-e2e.yml", "scale-50k")]


def _code(text: str) -> str:
    """Lines a shell would run: a full-line comment may name a command in order to forbid it."""
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))


def test_no_moved_workflow_prunes_the_host_docker_daemon() -> None:
    for name in ("trialbox-ci.yml", "trialbox-e2e.yml", "trialbox-nightly-quality.yml"):
        text = _code((WORKFLOWS / name).read_text(encoding="utf-8"))
        assert "docker system prune" not in text, name
        assert "docker builder prune" not in text, name
    images = (WORKFLOWS / "trialbox-images.yml").read_text(encoding="utf-8")
    assert "docker builder prune -af" in images  # stays on an ephemeral GitHub-hosted daemon
    assert "TB_RUNNER" not in str(_wf("trialbox-images.yml")["images"]["runs-on"])
    assert "TB_RUNNER" not in str(_wf("trialbox-images.yml")["multiarch"]["runs-on"])


def test_no_workflow_publishes_port_4000() -> None:
    """The self-hosted host already listens on 127.0.0.1:4000 (LiteLLM, not TrialBox)."""
    for path in sorted(WORKFLOWS.glob("trialbox-*.yml")):
        assert not PUBLISHED_4000.search(path.read_text(encoding="utf-8")), path.name
    for path in sorted((ROOT / "deploy").glob("docker-compose*.yml")):
        assert not PUBLISHED_4000.search(path.read_text(encoding="utf-8")), path.name


def test_demo_boot_removes_only_its_own_container_and_binds_loopback() -> None:
    runs = _runs(_wf("trialbox-ci.yml")["demo-boot"])
    assert "docker rm -f tb-demo" in runs and "docker image rm trialbox-demo:ci" in runs
    assert "-p 127.0.0.1:8080:8080" in runs
    assert "-p 8080:8080" not in runs
    code = _code(runs)
    assert "docker system prune" not in code and "docker builder prune" not in code


def test_compose_removes_only_its_project() -> None:
    runs = _runs(_wf("trialbox-e2e.yml")["compose"])
    assert runs.count("down -v --remove-orphans") == 2  # the test stack and the POC stack
    assert "make down" in runs and "make poc-down" in runs
    code = _code(runs)
    assert "docker system prune" not in code and "docker builder prune" not in code
    assert "actions/setup-node@" in str(_wf("trialbox-e2e.yml")["compose"]["steps"])
    assert "sudo -n true" in runs and "playwright install --with-deps chromium" in runs
    assert "playwright install chromium" in runs  # the path with no passwordless sudo


def test_ci_postgres_installs_only_when_missing_and_drops_the_tcp_cluster() -> None:
    text = (ROOT / "tools" / "ci_postgres.sh").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
    missing = code.index('if [ ! -x "$bin/initdb" ]')
    assert missing < code.index("sudo -n true") < code.index('sudo="sudo -n"')
    assert code.index('sudo="sudo -n"') < code.index("create_main_cluster = false")
    assert code.index("create_main_cluster = false") < code.index("pg_dropcluster --stop")
    assert "restore_cluster_conf" in code
    assert "apt-get install" in code and '"postgresql-$major"' in code
    # a service container is a different major from the client tools (test_pg_major.py); this script is the install
    assert "services:" not in code
