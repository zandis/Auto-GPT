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
REPO = "o/r"


def _pull(**over: Any) -> dict[str, Any]:
    return {"merged_at": "2026-11-12T10:00:00Z", "base": {"ref": "master"},
            "head": {"ref": "train/3", "sha": TRAIN, "repo": {"full_name": REPO}}, **over}  # fmt: skip


def _head(**over: Any) -> dict[str, Any]:
    return {"ref": "train/3", "sha": TRAIN, "repo": {"full_name": REPO}, **over}


def _green(**over: str) -> list[dict[str, Any]]:
    """One passed run for every full-tier check, as a green train leaves them; ``over`` changes some."""
    names = {**{n: "success" for n in cpt.FULL_TIER}, **over}
    return [_run(c, n) for n, c in names.items()]


def _run(conclusion: str = "success", name: str = "unit", app: str = "github-actions") -> dict[str, Any]:
    return {"name": name, "status": "completed", "conclusion": conclusion, "app": {"slug": app}}


def _args(**kw: Any) -> dict[str, Any]:
    return {"head_tree": "t1", "parents": [HEAD, TRAIN], "train_tree": "t1", "master_in_train": True, "repo": REPO,
            "pulls": [_pull()], "runs": _green(), **kw}  # fmt: skip


def test_a_train_merge_with_the_same_tree_and_a_green_full_tier_is_proved() -> None:
    assert cpt.proved(**_args()) == (True, "proved by train/3")
    more = [*_green(), _run("success", "goldens (omop)"), _run("success", "unit-shard (3)"), _run("failure", "checks")]
    assert cpt.proved(**_args(runs=more))[0]  # the legs of a matrix count; the fast tier runs on master anyway


@pytest.mark.parametrize(
    ("kw", "why"),
    [
        ({"parents": [TRAIN]}, "not a merge of two"),
        ({"parents": [HEAD, TRAIN, "c" * 40]}, "not a merge of two"),
        ({"train_tree": "t2"}, "tree differs"),
        # review M2: the train's run tested the train merged into master as it was; master must be inside the train
        ({"master_in_train": False}, "master had commits the train did not hold"),
        ({"pulls": []}, "no merged train"),
        ({"pulls": [_pull(merged_at=None)]}, "no merged train"),
        ({"pulls": [_pull(head=_head(ref="agent/train/3"))]}, "no merged train"),
        ({"pulls": [_pull(head=_head(sha="d" * 40))]}, "no merged train"),
        ({"pulls": [_pull(base={"ref": "train/9"})]}, "no merged train"),  # review M3: into master only
        ({"pulls": [_pull(head=_head(repo={"full_name": "someone/fork"}))]}, "no merged train"),  # and from this repo
        ({"runs": []}, "no unit check"),
        ({"runs": _green(unit="failure")}, "unit was failure"),
        ({"runs": _green(unit="skipped")}, "unit was skipped"),
        ({"runs": [*_green(), _run("failure")]}, "unit was failure"),
        ({"runs": [r for r in _green() if r["name"] != "unit"] + [_run(name="unit-shard (1)")]}, "no unit check"),
        ({"runs": [_run(app="someone-else"), *[r for r in _green() if r["name"] != "unit"]]}, "no unit check"),
        ({"runs": [{**r, "status": "in_progress", "conclusion": None} if r["name"] == "unit" else r for r in _green()]},
         "unit was None"),
        # review HIGH: every full-tier job is skipped on master, so every one of them must have passed on the train
        ({"runs": _green(security="failure")}, "security was failure"),
        ({"runs": [*_green(), _run("failure", "goldens (omop)")]}, "goldens was failure"),
        ({"runs": [r for r in _green() if r["name"] != "standards"]}, "no standards check"),
        ({"runs": _green(**{"demo-boot": "cancelled"})}, "demo-boot was cancelled"),
    ],
)  # fmt: skip
def test_anything_else_is_not_proved(kw: dict[str, Any], why: str) -> None:
    ok, said = cpt.proved(**_args(**kw))
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
    (tmp_path / "pulls.json").write_text(json.dumps([_pull(head=_head(sha=train))]), encoding="utf-8")
    (tmp_path / "checks.json").write_text(json.dumps({"check_runs": _green(unit=conclusion)}), encoding="utf-8")
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
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "GITHUB_REPOSITORY": REPO, "GIT_CONFIG_GLOBAL": "/dev/null",
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


def test_review_m2_a_revert_on_master_that_makes_the_trees_equal_is_not_proved(tmp_path: Path) -> None:
    """Master gets a commit, the train's run tests the train with it, master reverts it, the train is merged: the
    merge's tree is the train's, and no run ever tested that tree."""
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
    (repo / "x").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "x")
    _git(repo, "commit", "-q", "-m", "X")
    _git(repo, "revert", "--no-edit", "HEAD")
    _git(repo, "merge", "-q", "--no-ff", "-m", "train 3", "train/3")
    assert _git(repo, "rev-parse", "HEAD^{tree}") == _git(repo, "rev-parse", f"{train}^{{tree}}")  # the premise
    r = _cmd(repo, _gh(tmp_path, train))
    assert (r.returncode, r.stdout.strip()) == (0, "false") and "master had commits" in r.stderr


def test_the_image_gates_need_a_leg_of_their_own_not_the_hadolint_job() -> None:
    """Adversarial review of the deep review `architecture`: the CI gate's hadolint job is named `images` too, so a
    train whose image gates never ran met the full-tier rule. With ``image_legs`` a passed `images (...)` leg is
    needed; the CI gate's own question is unchanged."""
    assert cpt.proved(**_args())[0]  # the CI gate: hadolint's `images` is enough, as before
    ok, why = cpt.proved(**_args(), image_legs=True)
    assert not ok and why == "no image-gate leg ran on the train's head"
    legs = [*_green(), _run("success", "images (ubuntu-24.04, linux/amd64)")]
    assert cpt.proved(**_args(runs=legs), image_legs=True)[0]
    red = [*legs, _run("failure", "images (ubuntu-24.04-arm, linux/arm64)")]
    assert not cpt.proved(**_args(runs=red), image_legs=True)[0]
