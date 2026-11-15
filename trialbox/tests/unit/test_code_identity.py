"""QUALIFY-BOX (D-734): the code a qualification names, with or without a git checkout.

Lane G's blocker 1: ``tools/qualify.py`` stopped with "no git HEAD" on a box installed from a signed bundle, which has
no git. The installed release tree carries its own ``HOST-SHA256SUMS`` (the sha256 of every file, signed with the
bundle, D-367): its sha256 names exactly that code, and a file that differs from it makes the tree dirty."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from tools import code_identity, goldens, qualify

pytestmark = pytest.mark.nodb


def _release(tmp: Path) -> Path:
    rel = tmp / "releases" / "2026.11-3"
    (rel / "deploy").mkdir(parents=True)
    (rel / "deploy" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (rel / "tools").mkdir()
    (rel / "tools" / "x.py").write_text("print(1)\n", encoding="utf-8")
    sums = "".join(
        f"{hashlib.sha256((rel / n).read_bytes()).hexdigest()}  {n}\n"
        for n in ("deploy/docker-compose.yml", "tools/x.py")
    )
    (rel / "HOST-SHA256SUMS").write_text(sums, encoding="utf-8")
    return rel


def test_a_release_tree_is_named_by_its_signed_sums_and_is_clean(tmp_path: Path) -> None:
    rel = _release(tmp_path)
    head, dirty = code_identity.head(rel)
    want = hashlib.sha256((rel / "HOST-SHA256SUMS").read_bytes()).hexdigest()
    assert head == f"release:{want}" and dirty is False


def test_a_changed_file_in_the_release_makes_it_dirty(tmp_path: Path) -> None:
    rel = _release(tmp_path)
    (rel / "tools" / "x.py").write_text("print(2)\n", encoding="utf-8")
    assert code_identity.head(rel)[1] is True


def test_a_file_added_to_the_release_makes_it_dirty(tmp_path: Path) -> None:
    rel = _release(tmp_path)
    (rel / "tools" / "planted.py").write_text("print(3)\n", encoding="utf-8")
    assert code_identity.head(rel)[1] is True


def test_neither_git_nor_a_release_is_unknown(tmp_path: Path) -> None:
    assert code_identity.head(tmp_path) == ("unknown", True)


def test_a_git_checkout_is_named_by_its_commit_as_before(tmp_path: Path) -> None:
    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "f.txt").write_text("a\n", encoding="utf-8")
    git("add", "f.txt")
    git("-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false", "commit", "-qm", "x")
    head, dirty = code_identity.head(tmp_path)
    assert len(head) == 40 and dirty is False
    (tmp_path / "f.txt").write_text("b\n", encoding="utf-8")
    assert code_identity.head(tmp_path)[1] is True


def test_qualify_and_goldens_name_the_code_the_same_way(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rel = _release(tmp_path)
    monkeypatch.setattr(qualify, "ROOT", rel)
    monkeypatch.setattr(goldens, "ROOT", rel)
    want = code_identity.head(rel)
    assert qualify.git_head() == want
    assert goldens.git_head() == want[0]


def test_a_changed_release_tree_is_said_as_such(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rel = _release(tmp_path)
    (rel / "tools" / "x.py").write_text("print(2)\n", encoding="utf-8")
    monkeypatch.setattr(qualify, "ROOT", rel)
    assert qualify.dirty_problem(*qualify.git_head()) == (
        "the installed release differs from its signed HOST-SHA256SUMS: a record must name one release"
    )
    assert "uncommitted" in qualify.dirty_problem("a" * 40, True)
