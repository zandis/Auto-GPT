"""H-105, the security review of #1448, F1: the bench host's gate (tools/bench_ci/gate.py), the runner's job-started
hook. A fork's pull request runs its own workflow files and can name the bench label; the workflow on master and its
test are no boundary. The gate runs a job only for a push to this repository's train and lane branches or the
owner's run by hand, of the bench workflow exactly as master has it. Its facts: the runner's GITHUB_* variables and
event payload (set by the runner service from the code host's job message, before any step; a workflow cannot set a
GITHUB_* variable), and the host's job file (master's blob, read by the host, never by the job).
Each case below is one condition broken alone, and a fork's pull request as the code host sends it."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tools.bench_ci import gate

pytestmark = pytest.mark.nodb

REPO = "the-owner/the-repo"
WF = ".github/workflows/trialbox-bench-ci.yml"
MASTERS = b"name: TrialBox bench CI\non:\n  push:\n"  # master's copy of the workflow file
COMMIT = "a" * 40
FACTS = {"repo": REPO, "workflow": WF, "workflow_blob": gate.blob_sha(MASTERS), "proxy": "10.213.1.2:3128"}


def _env(**over: str) -> dict[str, str]:
    env = {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_REPOSITORY_OWNER": "the-owner",
        "GITHUB_REF": "refs/heads/claude/lane-x",
        "GITHUB_ACTOR": "a-lane",
        "GITHUB_TRIGGERING_ACTOR": "a-lane",
        "GITHUB_WORKFLOW_REF": f"{REPO}/{WF}@refs/heads/claude/lane-x",
        "GITHUB_WORKFLOW_SHA": COMMIT,
    }
    env.update(over)
    return {k: v for k, v in env.items() if v != "-"}  # "-": the variable is not set at all


EVENT = {"repository": {"full_name": REPO, "fork": False}}


class Fetch:
    def __init__(self, content: bytes = MASTERS, fail: bool = False) -> None:
        self.content, self.fail = content, fail
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, proxy: str, repo: str, commit: str, path: str) -> bytes:
        self.calls.append((proxy, repo, commit, path))
        if self.fail:
            raise RuntimeError("the code host did not answer")
        return self.content


def _decide(env: Mapping[str, str], event: Mapping[str, Any] = EVENT, fetch: Fetch | None = None) -> list[str]:
    return gate.decide(env, event, FACTS, fetch or Fetch())


@pytest.mark.parametrize(
    "ref",
    ["refs/heads/train/160", "refs/heads/agent/x", "refs/heads/claude/lane-h-105", "refs/heads/lane-h-1"],
)
def test_a_push_of_masters_workflow_to_an_allowed_branch_runs(ref: str) -> None:
    fetch = Fetch()
    assert _decide(_env(GITHUB_REF=ref, GITHUB_WORKFLOW_REF=f"{REPO}/{WF}@{ref}"), fetch=fetch) == []
    assert fetch.calls == [("10.213.1.2:3128", REPO, COMMIT, WF)]  # read by the job's commit, through the proxy


def test_the_owners_run_by_hand_runs_also_on_master() -> None:
    env = _env(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_ACTOR="the-owner", GITHUB_TRIGGERING_ACTOR="the-owner",
               GITHUB_REF="refs/heads/master", GITHUB_WORKFLOW_REF=f"{REPO}/{WF}@refs/heads/master")  # fmt: skip
    assert _decide(env) == []


def test_a_forks_pull_request_is_refused_before_anything_is_read() -> None:
    """As the code host sends it: the pull_request event of the base repository, the merge ref, the fork's file."""
    env = _env(
        GITHUB_EVENT_NAME="pull_request",
        GITHUB_REF="refs/pull/1450/merge",
        GITHUB_ACTOR="a-stranger",
        GITHUB_TRIGGERING_ACTOR="a-stranger",
        GITHUB_WORKFLOW_REF=f"{REPO}/.github/workflows/mine.yml@refs/pull/1450/merge",
    )
    event = {
        "repository": {"full_name": REPO, "fork": False},
        "pull_request": {"head": {"repo": {"full_name": "a-stranger/the-repo", "fork": True}}},
    }
    fetch = Fetch(content=b"on: pull_request\njobs:\n  x:\n    runs-on: [self-hosted, tb-bench, tb-bench-gpu]\n")
    got = _decide(env, event, fetch)
    assert any("the event is pull_request" in p for p in got)
    assert any("the ref refs/pull/1450/merge" in p for p in got)
    assert any("mine.yml" in p for p in got)
    assert fetch.calls == []  # nothing is read for a job that is refused already


@pytest.mark.parametrize(
    ("case", "env", "words"),
    [
        ("pull_request_target", _env(GITHUB_EVENT_NAME="pull_request_target"), "the event is pull_request_target"),
        ("issue_comment", _env(GITHUB_EVENT_NAME="issue_comment"), "the event is issue_comment"),
        ("workflow_run", _env(GITHUB_EVENT_NAME="workflow_run"), "the event is workflow_run"),
        ("schedule", _env(GITHUB_EVENT_NAME="schedule"), "the event is schedule"),
        ("no event", _env(GITHUB_EVENT_NAME="-"), "the event is not given"),
        ("another repository", _env(GITHUB_REPOSITORY="a-stranger/the-repo"), "the repository is a-stranger"),
        ("no repository", _env(GITHUB_REPOSITORY="-"), "the repository is not given"),
        ("master pushed", _env(GITHUB_REF="refs/heads/master", GITHUB_WORKFLOW_REF=f"{REPO}/{WF}@refs/heads/master"),
         "not an allowed branch"),
        ("another branch", _env(GITHUB_REF="refs/heads/feature/x", GITHUB_WORKFLOW_REF=f"{REPO}/{WF}@refs/heads/feature/x"),
         "not an allowed branch"),
        ("a deeper lane branch", _env(GITHUB_REF="refs/heads/claude/a/b", GITHUB_WORKFLOW_REF=f"{REPO}/{WF}@refs/heads/claude/a/b"),
         "not an allowed branch"),
        ("a tag", _env(GITHUB_REF="refs/tags/train/1", GITHUB_WORKFLOW_REF=f"{REPO}/{WF}@refs/tags/train/1"),
         "not an allowed branch"),
        ("another workflow file", _env(GITHUB_WORKFLOW_REF=f"{REPO}/.github/workflows/other.yml@refs/heads/claude/lane-x"),
         "other.yml"),
        ("the workflow of another repository", _env(GITHUB_WORKFLOW_REF=f"a-stranger/x/{WF}@refs/heads/claude/lane-x"),
         "a-stranger/x"),
        ("the workflow at another ref", _env(GITHUB_WORKFLOW_REF=f"{REPO}/{WF}@refs/heads/master"), "at the job's ref"),
        ("no workflow commit", _env(GITHUB_WORKFLOW_SHA="-"), "commit is not given"),
        ("by hand, not the owner", _env(GITHUB_EVENT_NAME="workflow_dispatch"), "not the repository's owner"),
        ("by hand, re-run by another", _env(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_ACTOR="the-owner"),
         "not the repository's owner"),
        ("by hand, no owner given", _env(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REPOSITORY_OWNER="-",
                                         GITHUB_ACTOR="", GITHUB_TRIGGERING_ACTOR=""), "not the repository's owner"),
    ],
)  # fmt: skip
def test_each_condition_broken_alone_refuses_the_job(case: str, env: dict[str, str], words: str) -> None:
    got = _decide(env)
    assert got and any(words in p for p in got), (case, got)


@pytest.mark.parametrize(
    ("case", "event"),
    [
        ("a fork's repository in the payload", {"repository": {"full_name": "a-stranger/the-repo", "fork": True}}),
        ("the payload says fork", {"repository": {"full_name": REPO, "fork": True}}),
        ("no repository in the payload", {}),
    ],
)
def test_the_event_payload_must_be_this_repository(case: str, event: dict[str, Any]) -> None:
    assert any("is not this repository" in p for p in _decide(_env(), event)), case


def test_a_branch_whose_workflow_file_differs_from_masters_is_refused() -> None:
    """The branch changed the file (or lacks master's change to it): refused until it carries master's file."""
    got = _decide(_env(), fetch=Fetch(content=MASTERS + b"  pull_request:\n"))
    assert len(got) == 1 and "is not master's" in got[0]


def test_a_branch_on_an_older_master_with_the_same_file_runs() -> None:
    """The edge the rule is written for: the blob, not the commit, is compared; an unchanged file is the same blob."""
    old_commit = "b" * 40
    fetch = Fetch(content=MASTERS)
    assert _decide(_env(GITHUB_WORKFLOW_SHA=old_commit), fetch=fetch) == []
    assert fetch.calls[0][2] == old_commit


def test_an_unreadable_file_refuses_and_a_missing_fact_refuses() -> None:
    assert "could not be read" in _decide(_env(), fetch=Fetch(fail=True))[0]
    for key in ("repo", "workflow", "workflow_blob"):
        facts = {k: v for k, v in FACTS.items() if k != key}
        assert gate.decide(_env(), EVENT, facts, Fetch()) != [], key
    assert gate.decide(_env(), EVENT, {**FACTS, "workflow_blob": "not-a-sha"}, Fetch()) != []


def test_the_blob_is_gits() -> None:
    assert gate.blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"  # git's id of an empty file
    assert gate.blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_the_hook_ends_the_job_on_a_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    job = tmp_path / "job.json"
    job.write_text(json.dumps(FACTS), encoding="utf-8")
    payload = tmp_path / "event.json"
    payload.write_text(json.dumps(EVENT), encoding="utf-8")
    env = _env(GITHUB_EVENT_PATH=str(payload))
    assert gate.main(["--job", str(job)], env=env, fetch=Fetch()) == 0
    assert gate.main(["--job", str(job)], env={**env, "GITHUB_EVENT_NAME": "pull_request"}, fetch=Fetch()) == 1
    assert "does not run on the bench host" in capsys.readouterr().err
    assert gate.main(["--job", str(tmp_path / "missing.json")], env=env, fetch=Fetch()) == 1  # no facts: refused


def test_the_gate_reads_no_variable_for_its_own_facts() -> None:
    """The proxy's address and master's blob come from the host's job file; only GITHUB_* facts are the runner's."""
    text = (Path(gate.__file__)).read_text(encoding="utf-8")
    assert "os.environ.get(" not in text and "HTTPS_PROXY" not in text
