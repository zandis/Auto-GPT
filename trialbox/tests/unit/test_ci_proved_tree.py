"""CI-COST (D-578): a push to master right after a train merge ran the full suite again on a tree the train had
already proved. ``tools/ci_proved_tree.py`` says "true" only when the pushed commit is a merge whose tree equals its
second parent's, that parent is the head of a merged pull request from a ``train/*`` branch, and that head's ``unit``
check passed. Anything else, and any error, says "false": the full tier runs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools import ci_proved_tree as cpt

pytestmark = pytest.mark.nodb

HEAD = "a" * 40
TRAIN = "b" * 40


def _pull(**over: Any) -> dict[str, Any]:
    return {"merged_at": "2026-11-12T10:00:00Z", "head": {"ref": "train/3", "sha": TRAIN}, **over}


def _run(conclusion: str = "success", name: str = "unit", app: str = "github-actions") -> dict[str, Any]:
    return {"name": name, "status": "completed", "conclusion": conclusion, "app": {"slug": app}}


def test_a_train_merge_with_the_same_tree_and_a_green_unit_is_proved() -> None:
    assert cpt.proved("t1", [HEAD[:1] * 40, TRAIN], "t1", [_pull()], [_run()]) == (True, "proved by train/3")


@pytest.mark.parametrize(
    ("kw", "why"),
    [
        ({"parents": [TRAIN]}, "not a merge of two"),
        ({"parents": [HEAD, TRAIN, "c" * 40]}, "not a merge of two"),
        ({"train_tree": "t2"}, "tree differs"),
        ({"pulls": []}, "no merged train"),
        ({"pulls": [_pull(merged_at=None)]}, "no merged train"),
        ({"pulls": [_pull(head={"ref": "agent/train/3", "sha": TRAIN})]}, "no merged train"),
        ({"pulls": [_pull(head={"ref": "train/3", "sha": "d" * 40})]}, "no merged train"),
        ({"runs": []}, "no unit check"),
        ({"runs": [_run("failure")]}, "unit was failure"),
        ({"runs": [_run("skipped")]}, "unit was skipped"),
        ({"runs": [_run(), _run("failure")]}, "unit was failure"),
        ({"runs": [_run(name="unit-shard (1)")]}, "no unit check"),
        ({"runs": [_run(app="someone-else")]}, "no unit check"),
        ({"runs": [{"name": "unit", "status": "in_progress", "conclusion": None, "app": {"slug": "github-actions"}}]},
         "unit was None"),
    ],
)  # fmt: skip
def test_anything_else_is_not_proved(kw: dict[str, Any], why: str) -> None:
    args: dict[str, Any] = {"head_tree": "t1", "parents": [HEAD, TRAIN], "train_tree": "t1", "pulls": [_pull()],
                            "runs": [_run()], **kw}  # fmt: skip
    ok, said = cpt.proved(**args)
    assert not ok and why in said, said


# ------------------------------------------------------------------------------------------------ the command
def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.org", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}  # fmt: skip
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path, *, master_moves: bool) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / "a").write_text("1\n", encoding="utf-8")
    _git(repo, "add", "a")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "train/3")
    (repo / "b").write_text("2\n", encoding="utf-8")
    _git(repo, "add", "b")
    _git(repo, "commit", "-q", "-m", "card")
    train = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "master")
    if master_moves:
        (repo / "c").write_text("3\n", encoding="utf-8")
        _git(repo, "add", "c")
        _git(repo, "commit", "-q", "-m", "someone else")
    _git(repo, "merge", "-q", "--no-ff", "-m", "train 3", "train/3")
    return repo, train


def _gh(tmp_path: Path, train: str, *, conclusion: str = "success", fail: bool = False) -> Path:
    """A stand-in for the `gh` command: answers the two calls from files, or fails."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "pulls.json").write_text(json.dumps([_pull(head={"ref": "train/3", "sha": train})]), encoding="utf-8")
    (tmp_path / "checks.json").write_text(json.dumps({"check_runs": [_run(conclusion)]}), encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        + ("exit 1\n" if fail else "")
        + f'case "$2" in */pulls) cat "{tmp_path}/pulls.json" ;; */check-runs*) cat "{tmp_path}/checks.json" ;; '
        "*) exit 2 ;; esac\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return bin_dir


def _cmd(repo: Path, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "GITHUB_REPOSITORY": "o/r", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_SYSTEM": "/dev/null"}  # fmt: skip
    return subprocess.run(
        [sys.executable, cpt.__file__], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


def test_the_command_says_true_for_a_train_merge_that_changed_nothing(tmp_path: Path) -> None:
    repo, train = _repo(tmp_path, master_moves=False)
    r = _cmd(repo, _gh(tmp_path, train))
    assert (r.returncode, r.stdout.strip()) == (0, "true"), r.stderr
    assert "train/3" in r.stderr


def test_the_command_says_false_when_master_had_moved(tmp_path: Path) -> None:
    repo, train = _repo(tmp_path, master_moves=True)
    r = _cmd(repo, _gh(tmp_path, train))
    assert (r.returncode, r.stdout.strip()) == (0, "false") and "tree differs" in r.stderr


def test_the_command_says_false_when_unit_failed_or_github_does_not_answer(tmp_path: Path) -> None:
    repo, train = _repo(tmp_path, master_moves=False)
    r = _cmd(repo, _gh(tmp_path, train, conclusion="failure"))
    assert (r.returncode, r.stdout.strip()) == (0, "false") and "unit was failure" in r.stderr
    (tmp_path / "bin" / "gh").unlink()
    (tmp_path / "bin").rmdir()
    r = _cmd(repo, _gh(tmp_path, train, fail=True))
    assert (r.returncode, r.stdout.strip()) == (0, "false") and "could not ask" in r.stderr
