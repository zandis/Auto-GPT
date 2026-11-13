"""TRAIN-READY (process review 2026-11-13): ``tools.train_ready`` refuses a head that breaks a standing rule before
the lane hands it to the integrator: an unpushed or dirty head, a commit without the two closing lines or naming a
model, a merge of master into the branch, no complete prepush run on that head."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import train_ready

pytestmark = pytest.mark.nodb

SESSION_LINE = "Claude-Session: https://claude.ai/code/session_x1"
GOOD_END = "\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n" + SESSION_LINE
OK_PREPUSH = {"ruff": "passed", "pwsh": "skipped: pwsh not installed"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(repo: Path, name: str, message: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "master", str(remote))
    _git(tmp_path, "clone", "-q", str(remote), str(work))
    _git(work, "checkout", "-q", "-b", "master")
    _commit(work, "base", "base" + GOOD_END)
    _git(work, "push", "-q", "origin", "master")
    _git(work, "checkout", "-q", "-b", "agent/T-1-card")
    return work


def _prepush(
    repo: Path, results: dict[str, str], *, complete: bool = True, dirty: bool = False, tests: bool = True
) -> Path:
    out = repo.parent / "pp"
    out.mkdir(exist_ok=True)
    summary = {
        "head": "x",
        "dirty": dirty,
        "complete": complete,
        "tests": ["t.py"] if tests else [],
        "results": results,
    }
    (out / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return out


def _push(repo: Path, *, upstream: bool = True) -> None:
    _git(repo, "push", "-q", *(["-u"] if upstream else []), "origin", "agent/T-1-card")


@pytest.mark.parametrize(
    ("message", "ok"),
    [
        ("T-1: a change" + GOOD_END, True),
        ("T-1: a change\n\nCo-Authored-By: Claude <noreply@anthropic.com>", False),
        ("T-1: a change" + GOOD_END + "\n", True),
        ("T-1: a change\n\nCo-authored-by: Claude <noreply@anthropic.com>\nClaude-Session: https://x/y", False),
        ("T-1: a change\n\nCo-Authored-By: Claude <noreply@anthropic.com> \n" + GOOD_END.split("\n")[-1], False),
        ("T-1: a change\n\nCo-Authored-By: Claude <noreply@anthropic.com>\nClaude-Session: https://e.org/x", False),
        ("T-1: reviewed by Sonnet" + GOOD_END, False),
        ("T-1: the claude-opus-9-9 run" + GOOD_END, False),
        ("T-1: the Fable review" + GOOD_END, False),
        ("T-1: a link in docs/plan/fable-review-2026-11-08.md; a magnum opus" + GOOD_END, True),
    ],
)
def test_message_rules(message: str, ok: bool) -> None:
    assert (train_ready.message_problems(message) == []) is ok


def test_a_clean_pushed_checked_head_is_ready(repo: Path) -> None:
    head = _commit(repo, "a", "T-1: a" + GOOD_END)
    _push(repo)
    got, problems, skipped = train_ready.check(cwd=repo, prepush_dir=_prepush(repo, OK_PREPUSH))
    assert (got, problems, skipped) == (head, [], ["pwsh"])


def test_a_branch_pushed_without_an_upstream_is_ready(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    _push(repo, upstream=False)
    assert train_ready.check(cwd=repo, prepush_dir=_prepush(repo, OK_PREPUSH))[1] == []


def test_an_untracked_file_is_named(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    _push(repo)
    (repo / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    assert any("untracked" in p for p in train_ready.check(cwd=repo, prepush_dir=_prepush(repo, OK_PREPUSH))[1])


def test_python_changed_without_tests_in_prepush_is_named(repo: Path) -> None:
    _commit(repo, "a.py", "T-1: a" + GOOD_END)
    _push(repo)
    problems = train_ready.check(cwd=repo, prepush_dir=_prepush(repo, OK_PREPUSH, tests=False))[1]
    assert problems == ["the prepush run had no --tests, and the branch changes Python files"]


def test_unpushed_dirty_and_unchecked_are_named(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    (repo / "a").write_text("changed", encoding="utf-8")
    _, problems, _ = train_ready.check(cwd=repo, prepush_dir=repo.parent / "none")
    text = "\n".join(problems)
    assert "uncommitted" in text and "push the branch first" in text and "no prepush run" in text


def test_a_commit_after_the_push_is_named(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    _push(repo)
    _commit(repo, "b", "T-1: b" + GOOD_END)
    _, problems, _ = train_ready.check(cwd=repo, prepush_dir=_prepush(repo, {"ruff": "passed"}))
    assert any("is not what origin/agent/T-1-card holds" in p for p in problems)


def test_a_failed_partial_or_dirty_prepush_is_named(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    _push(repo)
    pp = _prepush(repo, {"mypy": "failed (exit 1)"}, complete=False, dirty=True)
    _, problems, _ = train_ready.check(cwd=repo, prepush_dir=pp)
    assert len(problems) == 3


def test_a_merge_of_master_into_the_branch_is_named(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    _git(repo, "checkout", "-q", "master")
    _commit(repo, "m", "another card" + GOOD_END)
    _git(repo, "push", "-q", "origin", "master")
    _git(repo, "checkout", "-q", "agent/T-1-card")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge master" + GOOD_END, "master")
    _push(repo)
    _, problems, _ = train_ready.check(cwd=repo, prepush_dir=_prepush(repo, {"ruff": "passed"}))
    assert any("merges origin/master" in p for p in problems)


def test_a_merge_with_master_as_first_parent_is_named(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    _git(repo, "checkout", "-q", "master")
    _commit(repo, "m", "another card" + GOOD_END)
    _git(repo, "push", "-q", "origin", "master")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge the card" + GOOD_END, "agent/T-1-card")
    _git(repo, "branch", "-q", "-f", "agent/T-1-card", "HEAD")
    _git(repo, "checkout", "-q", "agent/T-1-card")
    _push(repo)
    _, problems, _ = train_ready.check(cwd=repo, prepush_dir=_prepush(repo, OK_PREPUSH))
    assert any("merges origin/master" in p for p in problems)


def test_merging_a_train_tip_that_holds_a_merge_of_master_is_allowed(repo: Path) -> None:
    _commit(repo, "a", "T-1: a" + GOOD_END)
    _git(repo, "checkout", "-q", "-b", "train/9", "master")
    _commit(repo, "m", "another card" + GOOD_END)
    _git(repo, "push", "-q", "origin", "HEAD:master")
    _git(repo, "checkout", "-q", "-b", "side", "HEAD~1")
    _commit(repo, "s", "a third card" + GOOD_END)
    _git(repo, "checkout", "-q", "train/9")
    _git(repo, "merge", "-q", "--no-ff", "-m", "train: merge without the closing lines", "side")
    _git(repo, "push", "-q", "origin", "train/9")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "agent/T-1-card")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge the train's tip" + GOOD_END, "train/9")
    _push(repo)
    _, problems, _ = train_ready.check(cwd=repo, prepush_dir=_prepush(repo, OK_PREPUSH))
    assert problems == []


def test_a_bad_commit_message_is_named(repo: Path) -> None:
    sha = _commit(repo, "a", "T-1: a")
    _push(repo)
    _, problems, _ = train_ready.check(cwd=repo, prepush_dir=_prepush(repo, {"ruff": "passed"}))
    assert problems and problems[0].startswith(f"commit {sha[:8]}")
