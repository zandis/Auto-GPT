"""CI-TIERS (D-564): which job runs when. A push to a draft pull request runs the fast tier; the full tier runs when
the pull request is not a draft, on a branch named ``train/*``, on a push to master and by hand. The unit shards and
``unit`` run on every pull request, draft or not (H-120, D-1357), and ``unit`` is never a skipped success. Every workflow that runs on pull requests cancels the older run of the same pull request.
A new job must be put in a tier here."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
CI = WORKFLOWS / "trialbox-ci.yml"

#: the fast tier: on every push to a pull request, draft or not
FAST = {"changes", "checks", "data-scan", "cross-card", "powershell", "differential"}
#: D-578: the short checks that were a job each (a runner and a billed minute each) are steps of `checks`
FOLDED = {
    "ruff": ["ruff check .", "ruff format --check ."],
    "actionlint": ["rhysd/actionlint:1.7.7@sha256:887a259a5a534f3c4f36cb02dca341673c6089431057242cdc931e9f133147e9"],
    "mypy": ["-m mypy libs services tools tests"],
    "doclint": ["tools/doclint.py"],
    "decision numbers": ["-m tools.decisions_index --check"],
    "licence register": ["-m tools.licence_register --check"],
    "limits lint": ["-m tools.limits_lint"],
    "generated contracts": ["make contracts-check"],
    "shipped rulesets": ["-m tools.build_rulesets --check"],
    "traceability": ["tools/gen_traceability.py --check"],
    "shellcheck": ["xargs -0 shellcheck --severity=warning --format=gcc"],
    "PoC host scripts": ["shellcheck --severity=warning deploy/gcp/poc-host.sh", "caddy validate --adapter caddyfile"],
    # D-1119: the fast tier includes the guard tests (tests/unit/test_ci_guard.py holds the step to no database)
    "guard tests": ["-m pytest -m guard -q -n 2 tests/unit", "TB_PG_BIN=/nonexistent"],
    "collection check": ["-m tools.collect_stable"],
}
#: the full tier: not on a draft
FULL = {"unit-shard", "unit", "property", "goldens", "e2e-simple", "demo-boot", "security", "standards", "images"}
FULL_GATE = "needs.changes.outputs.full == 'true'"
#: H-120 (D-1357): the unit shards and `unit` run on every pull request, on the tier code's `unit` output
UNIT_JOBS = {"unit-shard", "unit"}
UNIT_GATE = "${{ !cancelled() && needs.changes.outputs.unit != 'false' }}"
#: D-725: the plain-named checks of the matrix pairs: they run in every tier, after their matrix
GATES = {"goldens-gate", "e2e-simple-gate"}
#: the same rule for a workflow with no `changes` job
#: D-578: the image gates run for a merge train, on master, weekly and by hand; never for a card's pull request
TRAIN_ONLY = "github.event_name != 'pull_request' || startsWith(github.head_ref, 'train/')"

pytestmark = pytest.mark.nodb


def _wf(path: Path) -> dict[Any, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _on(doc: dict[Any, Any]) -> dict[str, Any]:
    on = doc.get("on") or doc.get(True)  # YAML 1.1 reads the key `on` as True
    assert isinstance(on, dict)
    return on


def test_every_job_of_the_gate_is_in_exactly_one_tier() -> None:
    jobs = set(_wf(CI)["jobs"])
    assert not FAST & FULL and not GATES & (FAST | FULL)
    assert jobs == FAST | FULL | GATES, f"put the new job in a tier: {sorted(jobs ^ (FAST | FULL | GATES))}"


def test_the_full_tier_waits_for_a_pull_request_that_is_not_a_draft() -> None:
    jobs = _wf(CI)["jobs"]
    for name in sorted(FULL - UNIT_JOBS):
        assert FULL_GATE in str(jobs[name].get("if")), name
        assert "needs.changes.outputs.trialbox == 'true'" in str(jobs[name].get("if")), name
    for name in sorted(UNIT_JOBS):  # H-120 (D-1357): on every pull request (test_h120_unit_shards_every_pr.py)
        assert jobs[name].get("if") == UNIT_GATE, name
    for name in sorted(FAST - {"changes"}):
        assert "full" not in str(jobs[name].get("if")), name
        assert jobs[name].get("if") == "needs.changes.outputs.trialbox == 'true'", name


def test_unit_runs_on_every_pull_request_and_is_never_skipped_success() -> None:
    """The aggregate runs when a shard failed (`!cancelled()`) and on the tier code's `unit` output, as the shards
    do (H-120, D-1357): on a pull request it is never skipped, and a skipped shard turns it red."""
    unit = _wf(CI)["jobs"]["unit"]
    assert unit["needs"] == ["changes", "unit-shard"]
    cond = str(unit["if"])
    assert "!cancelled()" in cond and "needs.changes.outputs.unit != 'false'" in cond
    first = unit["steps"][0]["run"]
    assert 'needs.unit-shard.result }}" != "success"' in first and "exit 1" in first  # skipped shards are not a pass


def _full(
    event: str,
    draft: str,
    head_ref: str,
    tmp_path: Path,
    proved: str = "",
    docs_only: str = "",
    *,
    card_tier: str | None = None,
    changed: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
    gh_fails: bool = False,
    out_key: str = "full",
) -> str:
    """Run the `changes` job's tier step as the runner would, with the values it reads (D-970: the labels from a
    stand-in ``gh``, the changed paths from ``$RUNNER_TEMP/changed``, ``CARD_TIER`` from the workflow's env unless
    given)."""
    doc = _wf(CI)
    step = next(s for s in doc["jobs"]["changes"]["steps"] if s.get("id") == "tier")
    assert step["env"] == {
        "EVENT": "${{ github.event_name }}",
        "DRAFT": "${{ github.event.pull_request.draft }}",
        "HEAD_REF": "${{ github.head_ref }}",
        "PROVED": "${{ steps.proved.outputs.proved }}",
        "DOCS_ONLY": "${{ steps.diff.outputs.docs_only }}",
        "PR": "${{ github.event.pull_request.number }}",
        "REPO": "${{ github.repository }}",
        "GH_TOKEN": "${{ github.token }}",
    }  # values reach the script through the environment, never pasted into it
    out = tmp_path / "out"
    out.write_text("", encoding="utf-8")
    runner = tmp_path / "runner"
    runner.mkdir(exist_ok=True)
    if changed:
        (runner / "changed").write_text("".join(f"{p}\n" for p in changed), encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    body = "exit 1" if gh_fails else "".join(f"echo '{x}'\n" for x in labels)
    gh.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    gh.chmod(0o755)
    env = {"EVENT": event, "DRAFT": draft, "HEAD_REF": head_ref, "PROVED": proved, "DOCS_ONLY": docs_only,
           "PR": "7", "REPO": "o/r", "GH_TOKEN": "x", "RUNNER_TEMP": str(runner),
           "CARD_TIER": doc["env"]["CARD_TIER"] if card_tier is None else card_tier,
           "GITHUB_OUTPUT": str(out), "PATH": f"{bindir}:/usr/bin:/bin"}  # fmt: skip
    subprocess.run(["bash", "-euo", "pipefail", "-c", step["run"]], env=env, check=True, capture_output=True,
                   cwd=ROOT.parent)  # fmt: skip
    return dict(ln.split("=", 1) for ln in out.read_text(encoding="utf-8").split())[out_key]


@pytest.mark.parametrize(
    ("event", "draft", "head_ref", "full"),
    [
        ("pull_request", "true", "agent/T-1-a-card", "false"),  # a draft: the fast tier only
        ("pull_request", "false", "agent/T-1-a-card", "true"),  # ready: the full tier
        ("pull_request", "true", "train/7", "true"),  # a merge train runs the full tier whatever its state
        ("pull_request", "true", "agent/train/7", "false"),  # only a branch named train/*
        ("push", "", "", "true"),  # master
        ("workflow_dispatch", "", "", "true"),  # by hand
    ],
)
def test_the_tier_of_a_run(event: str, draft: str, head_ref: str, full: str, tmp_path: Path) -> None:
    """D-564's rule, which CARD_TIER=touched (D-970's revert of the trial) keeps for a card's change to a service."""
    assert (
        _full(event, draft, head_ref, tmp_path, card_tier="touched", changed=("trialbox/services/lake/build.py",))
        == full
    )


@pytest.mark.parametrize(
    ("event", "draft", "head_ref", "proved", "full"),
    [
        ("push", "", "", "true", "false"),  # D-578: master at a tree a green train proved: the fast tier only
        ("push", "", "", "false", "true"),
        ("push", "", "", "", "true"),  # the check did not run or said nothing: the full tier
        ("pull_request", "false", "agent/T-1-a-card", "true", "true"),  # only a push to master reads it
        ("workflow_dispatch", "", "", "true", "true"),
    ],
)
def test_a_master_push_at_a_proved_tree_runs_the_fast_tier(
    event: str, draft: str, head_ref: str, proved: str, full: str, tmp_path: Path
) -> None:
    assert _full(event, draft, head_ref, tmp_path, proved, card_tier="touched") == full


@pytest.mark.parametrize(
    ("event", "draft", "head_ref", "docs_only", "full"),
    [
        ("pull_request", "false", "agent/T-1-a-card", "true", "false"),  # D-969: a card that changes only documents
        ("pull_request", "false", "agent/T-1-a-card", "false", "true"),
        ("pull_request", "false", "train/7", "true", "true"),  # a merge train runs everything, whatever it holds
        ("push", "", "", "true", "true"),  # master: the diff step says false there; the rule is for pull requests
        ("workflow_dispatch", "", "", "true", "true"),
    ],
)
def test_a_docs_only_card_runs_the_fast_tier(
    event: str, draft: str, head_ref: str, docs_only: str, full: str, tmp_path: Path
) -> None:
    assert _full(event, draft, head_ref, tmp_path, docs_only=docs_only, card_tier="touched") == full


def test_the_proved_rule_asks_for_every_full_tier_job() -> None:
    """Review of D-578: a proved push skips the whole full tier, so the rule reads every one of its checks."""
    from tools import ci_proved_tree

    assert set(ci_proved_tree.FULL_TIER) == FULL


def test_the_proved_step_runs_on_a_push_only_and_may_read_checks_and_pull_requests() -> None:
    job = _wf(CI)["jobs"]["changes"]
    step = next(s for s in job["steps"] if s.get("id") == "proved")
    assert step["if"] == "github.event_name == 'push'"
    assert "tools/ci_proved_tree.py" in step["run"] and step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert job["permissions"] == {"contents": "read", "checks": "read", "pull-requests": "read"}
    ids = [s.get("id") for s in job["steps"]]
    assert ids.index("proved") < ids.index("tier")


def test_the_short_checks_are_steps_of_one_job_and_every_one_runs() -> None:
    """D-578: one runner and one set-up for the checks of under a minute. A failed step does not hide the ones
    after it: each check step runs unless the run was cancelled, and the job fails when any of them failed."""
    jobs = _wf(CI)["jobs"]
    assert not {"lint", "types", "docs", "contracts", "trace", "shell"} & set(jobs)
    steps = jobs["checks"]["steps"]
    named = {str(s.get("name", "")): s for s in steps if "run" in s}
    for label, commands in FOLDED.items():
        step = next((s for n, s in named.items() if n.startswith(label)), None)
        assert step is not None, f"no step named {label!r}"
        assert step.get("if") == "${{ !cancelled() }}", label
        assert not step.get("continue-on-error"), label
        for cmd in commands:
            assert cmd in step["run"], (label, cmd)
    setup = [s for s in steps if s.get("if") != "${{ !cancelled() }}"]
    assert (
        len(setup) == 3 and steps[: len(setup)] == setup
    )  # checkout, uv, the environment: first, and they stop the job


def test_marking_ready_starts_the_full_tier() -> None:
    for name in ("trialbox-ci.yml", "trialbox-images.yml"):
        types = _on(_wf(WORKFLOWS / name))["pull_request"]["types"]
        assert set(types) == {"opened", "synchronize", "reopened", "ready_for_review"}, name


def test_the_image_gates_run_for_a_train_on_master_weekly_and_by_hand() -> None:
    """D-578: 129 runs on card pull requests in a day, about 2,900 billed minutes. A card that changes an image
    says so and goes on a train early."""
    doc = _wf(WORKFLOWS / "trialbox-images.yml")
    on = _on(doc)
    assert doc["jobs"]["images"]["if"] == TRAIN_ONLY
    assert on["push"]["branches"] == ["master"] and on["push"]["tags"] == ["trialbox-v*"]
    assert on["schedule"] and "workflow_dispatch" in on
    assert set(on["push"]["paths"]) == set(on["pull_request"]["paths"])  # master: only when an image's input changed


def test_the_lock_job_starts_on_what_it_reads() -> None:
    """D-578: `trialbox/**` started it 362 times in a day. Every file the job's commands and its gate tests read is
    under one of these paths; the gate tests run with the unit tests too."""
    paths = set(_on(_wf(WORKFLOWS / "trialbox-supply-chain.yml"))["pull_request"]["paths"])
    assert "trialbox/**" not in paths
    for needed in (
        "trialbox/uv.lock", "trialbox/pyproject.toml", "trialbox/deploy/**", "trialbox/tools/supply_chain/**",
        "trialbox/tools/make_bundle.sh", "trialbox/Makefile", "trialbox/.dockerignore",
        "trialbox/demo/**", "trialbox/README.md",  # review: the gate tests read the demo Dockerfile and the README
        "trialbox/tests/unit/test_supply_chain.py", "trialbox/tests/fixtures/supply_chain/**",
        ".github/workflows/trialbox-*.yml",
    ):  # fmt: skip
        assert needed in paths, needed
    assert _on(_wf(WORKFLOWS / "trialbox-supply-chain.yml"))["schedule"]  # new advisories, weekly


def test_the_weekly_scan_does_not_cancel_a_master_pushs_scan() -> None:
    group = _wf(WORKFLOWS / "trialbox-images.yml")["concurrency"]["group"]
    assert "github.event_name" in group


def test_a_push_to_master_is_not_a_release() -> None:
    """The multi-architecture build is for a release tag or a run by hand; master pushes must not start it."""
    cond = _wf(WORKFLOWS / "trialbox-images.yml")["jobs"]["multiarch"]["if"]
    assert "startsWith(github.ref, 'refs/tags/')" in cond and "workflow_dispatch" in cond


def test_the_arm64_leg_runs_for_a_train_master_and_a_release_only() -> None:
    """The arm64 runner is the dearer leg: not weekly and not by hand."""
    text = (WORKFLOWS / "trialbox-images.yml").read_text(encoding="utf-8")
    include = _wf(WORKFLOWS / "trialbox-images.yml")["jobs"]["images"]["strategy"]["matrix"]["include"]
    assert isinstance(include, str) and include.startswith("${{ fromJSON(")
    assert "github.event_name == 'pull_request' || github.event_name == 'push'" in include
    both, one = re.findall(r"'(\[.*?\])'", include)
    assert [m["platform"] for m in __import__("json").loads(both)] == ["linux/amd64", "linux/arm64"]
    assert [m["platform"] for m in __import__("json").loads(one)] == ["linux/amd64"]
    assert "ubuntu-24.04-arm" in both and "ubuntu-24.04-arm" not in one and "matrix.runner" in text
    lock = _wf(WORKFLOWS / "trialbox-supply-chain.yml")["jobs"]["lock"]
    assert "draft" not in str(lock.get("if"))  # the lock check is fast tier


def test_a_new_push_cancels_the_old_run_of_the_same_pull_request() -> None:
    seen = 0
    for path in sorted(WORKFLOWS.glob("trialbox-*.yml")):
        doc = _wf(path)
        if "pull_request" not in _on(doc):
            continue
        seen += 1
        conc = doc["concurrency"]
        assert re.search(r"github\.event\.pull_request\.number \|\| github\.ref", conc["group"]), path.name
        cancel = conc["cancel-in-progress"]
        assert cancel is True or cancel == "${{ github.event_name == 'pull_request' }}", path.name
    assert seen == 6  # ci, images, supply chain, identity, box rehearsal (D-887), visual regression (9k-17, D-1377)


def test_the_developers_page_names_the_tiers_and_the_train() -> None:
    page = (ROOT / "docs" / "DEVELOPING.md").read_text(encoding="utf-8")
    for word in ("fast tier", "full tier", "train/", "ready for review", "--no-ff", "merge commit"):
        assert word in page, word
    for job in sorted(FAST | FULL):
        assert f"`{job}`" in page, job


def test_the_shards_limit_is_the_measured_one() -> None:
    """D-564: 1.5 times the slowest shard's median (24.8 minutes), rounded up to the next five; at 30 a shard that
    had passed was cancelled while it kept its record."""
    text = CI.read_text(encoding="utf-8")
    job = _wf(CI)["jobs"]["unit-shard"]
    assert job["timeout-minutes"] == 40
    block = text[: text.index("    timeout-minutes: 40\n")].rsplit("unit-shard:", 1)[1]
    assert "24.8" in block and "1.5" in block  # the derivation stays beside the number (OD-10)


CARD = ("pull_request", "false", "agent/T-1-a-card")


def test_the_workflow_runs_the_trial_of_e() -> None:
    """D-970: the one line the integrator changes to revert the trial."""
    assert _wf(CI)["env"]["CARD_TIER"] == "fast"


@pytest.mark.parametrize(
    ("changed", "labels", "full"),
    [
        (("trialbox/services/lake/build.py",), (), "false"),  # E: a card on no full-tier path runs the fast tier
        (("trialbox/services/matching/engine.py",), (), "true"),  # decides about a patient
        (("trialbox/services/lake/build.py", "trialbox/services/adapter/x.py"), (), "true"),  # one is enough
        (("trialbox/services/lake/sqlguard.py",), (), "true"),  # which rows a query may return
        (("trialbox/services/lake/build.py",), ("ci:full",), "true"),  # the label forces it
        (("trialbox/services/lake/build.py",), ("bug", "ci:fullish"), "false"),  # only that exact label
    ],
)
def test_a_card_runs_the_fast_tier_unless_on_the_list_or_labelled(
    changed: tuple[str, ...], labels: tuple[str, ...], full: str, tmp_path: Path
) -> None:
    assert _full(*CARD, tmp_path, changed=changed, labels=labels) == full


def test_labels_that_cannot_be_read_mean_the_full_tier(tmp_path: Path) -> None:
    assert _full(*CARD, tmp_path, changed=("trialbox/services/lake/build.py",), gh_fails=True) == "true"


def test_a_train_and_master_run_everything_on_the_trial(tmp_path: Path) -> None:
    assert _full("pull_request", "false", "train/9", tmp_path, changed=("trialbox/services/lake/build.py",)) == "true"
    assert _full("push", "", "", tmp_path) == "true"
    assert _full("pull_request", "true", "train/9", tmp_path, out_key="scenarios") == "true"


def test_a_draft_runs_the_fast_tier_unless_labelled(tmp_path: Path) -> None:
    on_list = ("trialbox/services/matching/engine.py",)
    assert _full("pull_request", "true", "agent/T-1-a-card", tmp_path, changed=on_list) == "false"
    assert _full("pull_request", "true", "agent/T-1-a-card", tmp_path, changed=on_list, labels=("ci:full",)) == "true"


@pytest.mark.parametrize(
    ("changed", "scenarios"),
    [
        (("trialbox/deploy/install.sh", "trialbox/tools/make_bundle.sh"), "false"),  # D: no scenario jobs
        ((".github/workflows/trialbox-e2e.yml",), "false"),
        (("trialbox/deploy/install.sh", "trialbox/services/lake/build.py"), "true"),
        (("trialbox/tools/keys.py",), "true"),  # on the full-tier list: everything
    ],
)
def test_touched_skips_the_scenario_jobs_for_deploy_and_tools_only(
    changed: tuple[str, ...], scenarios: str, tmp_path: Path
) -> None:
    assert _full(*CARD, tmp_path, card_tier="touched", changed=changed) == "true"
    assert _full(*CARD, tmp_path, card_tier="touched", changed=changed, out_key="scenarios") == scenarios


def test_the_scenario_jobs_wait_for_their_own_output() -> None:
    jobs = _wf(CI)["jobs"]
    for name in ("goldens", "e2e-simple", "demo-boot"):
        assert "needs.changes.outputs.scenarios == 'true'" in str(jobs[name]["if"]), name
    assert _wf(CI)["jobs"]["changes"]["outputs"]["scenarios"] == "${{ steps.tier.outputs.scenarios }}"
