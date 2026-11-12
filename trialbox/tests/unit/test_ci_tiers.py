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
FAST = {"changes", "lint", "types", "docs", "contracts", "data-scan", "shell", "trace", "cross-card"}
#: the full tier: not on a draft
FULL = {"unit-shard", "unit", "property", "goldens", "e2e-simple", "demo-boot", "security", "standards", "images"}
FULL_GATE = "needs.changes.outputs.full == 'true'"
#: the same rule for a workflow with no `changes` job
NOT_DRAFT = (
    "github.event_name != 'pull_request' || github.event.pull_request.draft == false"
    " || startsWith(github.head_ref, 'train/')"
)

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


def _full(event: str, draft: str, head_ref: str, tmp_path: Path) -> str:
    """Run the `changes` job's tier step as the runner would, with the three values it reads."""
    step = next(s for s in _wf(CI)["jobs"]["changes"]["steps"] if s.get("id") == "tier")
    assert step["env"] == {
        "EVENT": "${{ github.event_name }}",
        "DRAFT": "${{ github.event.pull_request.draft }}",
        "HEAD_REF": "${{ github.head_ref }}",
    }  # values reach the script through the environment, never pasted into it
    out = tmp_path / "out"
    out.write_text("", encoding="utf-8")
    env = {"EVENT": event, "DRAFT": draft, "HEAD_REF": head_ref, "GITHUB_OUTPUT": str(out), "PATH": "/usr/bin:/bin"}
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


def test_marking_ready_starts_the_full_tier() -> None:
    for name in ("trialbox-ci.yml", "trialbox-images.yml"):
        types = _on(_wf(WORKFLOWS / name))["pull_request"]["types"]
        assert set(types) == {"opened", "synchronize", "reopened", "ready_for_review"}, name


def test_the_image_gates_are_full_tier() -> None:
    jobs = _wf(WORKFLOWS / "trialbox-images.yml")["jobs"]
    assert jobs["images"]["if"] == NOT_DRAFT
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
