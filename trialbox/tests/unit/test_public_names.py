"""The public-names check (hygiene item 4): the tracked files of a public repository name no person, host, home
folder or machine of the project's own. The pattern list lives outside the repository; the file that holds it is
named by an environment variable. These tests use invented patterns in throwaway repositories only."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import public_names as pn

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path, files: dict[str, bytes | str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    return repo


def _patterns(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "outside" / "names.txt"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(repo: Path, env_value: str | None, *args: str) -> tuple[int, str, str]:
    env = {k: v for k, v in os.environ.items() if k != pn.ENV}
    if env_value is not None:
        env[pn.ENV] = env_value
    proc = subprocess.run(
        [sys.executable, "-m", "tools.public_names", "--repo", str(repo), "check", *args],
        cwd=ROOT,
        env={**env, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_a_match_fails_with_place_and_pattern_number_but_never_the_text(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"docs/a.md": "line one\nwritten by Zorbek Quillfeather\n", "b.txt": "clean\n"})
    names = _patterns(tmp_path, "# invented\nnothing-here\nzorbek\\s+quill\\w*\n")
    rc, out, err = _run(repo, str(names))
    assert rc == 1, (out, err)
    assert "docs/a.md:2: pattern 2" in out
    assert "zorbek" not in (out + err).lower() and "quill" not in (out + err).lower()
    assert "b.txt" not in out


def test_a_clean_tree_passes_and_says_how_much_it_read(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.md": "nothing to see\n", "img.bin": b"\x00\x01zorbek\x00"})
    rc, out, err = _run(repo, str(_patterns(tmp_path, "zorbek\n")))
    assert rc == 0, (out, err)
    assert "public-names: PASS" in out
    assert "1 pattern" in out and "2 tracked files" in out


def test_a_tracked_file_name_is_checked_too(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"tools/zorbek_probe.py": "x = 1\n"})
    rc, out, _ = _run(repo, str(_patterns(tmp_path, "zorbek\n")))
    assert rc == 1
    # the path itself would repeat the name: the hit is named by its place in `git ls-files`
    assert "tracked path 1 (git ls-files | sed -n 1p): file name matches pattern 1" in out
    assert "zorbek" not in out


def test_a_line_hit_in_a_file_whose_name_matches_names_the_file_by_number(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.md": "clean\n", "zorbek.md": "hello\nzorbek again\n"})
    rc, out, _ = _run(repo, str(_patterns(tmp_path, "zorbek\n")))
    assert rc == 1
    assert "tracked path 2 (git ls-files | sed -n 2p):2: pattern 1" in out
    assert "zorbek" not in out


def test_untracked_files_are_not_read(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.md": "clean\n"})
    (repo / "scratch.md").write_text("zorbek\n", encoding="utf-8")
    rc, out, _ = _run(repo, str(_patterns(tmp_path, "zorbek\n")))
    assert rc == 0, out


@pytest.mark.parametrize("value", [None, ""])
def test_the_variable_unset_is_said_plainly_and_never_passes(tmp_path: Path, value: str | None) -> None:
    repo = _repo(tmp_path, {"a.md": "clean\n"})
    rc, out, err = _run(repo, value)
    assert rc == 2
    assert f"{pn.ENV} is not set" in err
    assert "NOT checked" in err
    assert "PASS" not in out


def test_an_unreadable_or_empty_list_never_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.md": "clean\n"})
    rc, _, err = _run(repo, str(tmp_path / "missing.txt"))
    assert rc == 2 and "NOT checked" in err
    rc, _, err = _run(repo, str(_patterns(tmp_path, "# only a comment\n\n")))
    assert rc == 2 and "no patterns" in err


def test_a_bad_pattern_is_named_by_number_only(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.md": "clean\n"})
    rc, _, err = _run(repo, str(_patterns(tmp_path, "fine\nzorbek(\n")))
    assert rc == 2
    assert "pattern 2" in err and "zorbek" not in err


def test_a_list_inside_the_repository_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.md": "clean\n"})
    inside = repo / "names.txt"
    inside.write_text("zorbek\n", encoding="utf-8")
    rc, _, err = _run(repo, str(inside))
    assert rc == 2
    assert "inside the repository" in err


def test_the_release_bundle_target_runs_the_check_first() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    rule = next(line for line in text.splitlines() if line.startswith("release-bundle:"))
    assert "public-names" in rule.split(":", 1)[1].split()
    assert "public-names:" in text
