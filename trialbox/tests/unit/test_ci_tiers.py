"""CI-TIERS (D-564): which job runs when. A push to a draft pull request runs the fast tier; the full tier runs when
the pull request is not a draft, on a branch named ``train/*``, on a push to master and by hand. ``unit`` is skipped
on a draft, never success. Every workflow that runs on pull requests cancels the older run of the same pull request.
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
}
#: the full tier: not on a draft
FULL = {"unit-shard", "unit", "property", "goldens", "e2e-simple", "demo-boot", "security", "standards", "images"}
FULL_GATE = "needs.changes.outputs.full == 'true'"
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
    assert not FAST & FULL
    assert jobs == FAST | FULL, f"put the new job in a tier: {sorted(jobs ^ (FAST | FULL))}"


def test_the_full_tier_waits_for_a_pull_request_that_is_not_a_draft() -> None:
    jobs = _wf(CI)["jobs"]
    for name in sorted(FULL):
        assert FULL_GATE in str(jobs[name].get("if")), name
        assert "needs.changes.outputs.trialbox == 'true'" in str(jobs[name].get("if")), name
    for name in sorted(FAST - {"changes"}):
        assert "full" not in str(jobs[name].get("if")), name
        assert jobs[name].get("if") == "needs.changes.outputs.trialbox == 'true'", name


def test_unit_is_skipped_on_a_draft_and_never_success() -> None:
    """The aggregate runs when a shard failed (`!cancelled()`), so it must carry the tier's gate itself: without
    it a draft's `unit` would run with every shard skipped."""
    unit = _wf(CI)["jobs"]["unit"]
    assert unit["needs"] == ["changes", "unit-shard"]
    cond = str(unit["if"])
    assert "!cancelled()" in cond and FULL_GATE in cond
    first = unit["steps"][0]["run"]
    assert 'needs.unit-shard.result }}" != "success"' in first and "exit 1" in first  # skipped shards are not a pass


def _full(event: str, draft: str, head_ref: str, tmp_path: Path, proved: str = "") -> str:
    """Run the `changes` job's tier step as the runner would, with the values it reads."""
    step = next(s for s in _wf(CI)["jobs"]["changes"]["steps"] if s.get("id") == "tier")
    assert step["env"] == {
        "EVENT": "${{ github.event_name }}",
        "DRAFT": "${{ github.event.pull_request.draft }}",
        "HEAD_REF": "${{ github.head_ref }}",
        "PROVED": "${{ steps.proved.outputs.proved }}",
    }  # values reach the script through the environment, never pasted into it
    out = tmp_path / "out"
    out.write_text("", encoding="utf-8")
    env = {"EVENT": event, "DRAFT": draft, "HEAD_REF": head_ref, "PROVED": proved, "GITHUB_OUTPUT": str(out),
           "PATH": "/usr/bin:/bin"}  # fmt: skip
    subprocess.run(["bash", "-euo", "pipefail", "-c", step["run"]], env=env, check=True, capture_output=True)
    return dict(ln.split("=", 1) for ln in out.read_text(encoding="utf-8").split())["full"]


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
    assert _full(event, draft, head_ref, tmp_path) == full


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
    assert _full(event, draft, head_ref, tmp_path, proved) == full


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
    assert TRAIN_ONLY in doc["jobs"]["images"]["if"]
    assert on["push"]["branches"] == ["master"] and on["push"]["tags"] == ["trialbox-v*"]
    assert on["schedule"] and "workflow_dispatch" in on
    assert set(on["push"]["paths"]) == set(on["pull_request"]["paths"])  # master: only when an image's input changed


def test_a_master_push_a_train_proved_does_not_build_the_images_again() -> None:
    """Deep review `architecture`: the push of train 8's merge commit built and scanned the images the train had just
    built from the same tree (about 45 billed minutes). The image gates ask the CI gate's rule (tools/ci_proved_tree.py)
    on a push to master only; anywhere else, and on any doubt, they build."""
    jobs = _wf(WORKFLOWS / "trialbox-images.yml")["jobs"]
    proved = jobs["proved"]
    assert proved["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/master'"
    assert proved["permissions"] == {"contents": "read", "checks": "read", "pull-requests": "read"}
    assert any("tools/ci_proved_tree.py --image-legs" in str(s.get("run", "")) for s in proved["steps"])
    assert proved["steps"][0]["with"]["fetch-depth"] == 0  # the tool compares the trees of both parents
    images = jobs["images"]
    assert images["needs"] == "proved"
    cond = images["if"]
    assert "!cancelled()" in cond  # a skipped `proved` (a train, a tag, the weekly run) does not skip the images
    assert "needs.proved.outputs.proved != 'true'" in cond  # only a definite "true" skips; an error says "false"
    assert "ci_proved_tree" not in str(jobs["multiarch"])  # a release tag always builds


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
    assert seen == 4  # ci, images, supply chain, identity


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
