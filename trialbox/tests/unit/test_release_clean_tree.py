"""RELEASE-CLEAN (D-631): a release bundle is built from a commit. The host tree is packed from the checkout as it
stands (untracked files included), so a file left in ``tools/`` rode to every box inside a signed bundle whose
record named a commit that does not hold it."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import release

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "make_bundle.sh"

pytestmark = pytest.mark.nodb


def _git(repo: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}  # fmt: skip
    subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, env=env
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A checkout shaped like the project: a repository whose project folder is ``trialbox/``."""
    top = tmp_path / "src"
    proj = top / "trialbox"
    (proj / "tools").mkdir(parents=True)
    shutil.copy(SCRIPT, proj / "tools" / "make_bundle.sh")
    shutil.copy(ROOT / "tools" / "release.py", proj / "tools" / "release.py")
    (proj / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (proj / "pyproject.toml").write_text('[project]\nname = "trialbox"\nversion = "1.0.0"\n', encoding="utf-8")
    (proj / ".gitignore").write_text("dist/\n__pycache__/\n", encoding="utf-8")
    (top / "other.txt").write_text("outside the project folder\n", encoding="utf-8")
    _git(tmp_path, "init", "-q", str(top))
    _git(top, "add", "-A")
    _git(top, "commit", "-q", "-m", "a release commit")
    return proj


def test_a_checkout_that_equals_its_commit_has_no_changes(repo: Path) -> None:
    assert release.tree_changes(repo) == []
    (repo / "dist").mkdir()
    (repo / "dist" / "bundle.tar").write_text("ignored build output", encoding="utf-8")
    (repo.parent / "scratch.txt").write_text("outside the project folder", encoding="utf-8")
    assert release.tree_changes(repo) == []


def test_an_untracked_a_changed_and_a_staged_file_are_each_named(repo: Path) -> None:
    (repo / "tools" / "left_here.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text('[project]\nname = "trialbox"\nversion = "9.9.9"\n', encoding="utf-8")
    (repo / "tools" / "staged.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "tools/staged.py")
    said = "\n".join(release.tree_changes(repo))
    for name in ("tools/left_here.py", "pyproject.toml", "tools/staged.py"):
        assert name in said, said


def test_a_folder_that_is_no_checkout_is_not_a_commit(tmp_path: Path) -> None:
    assert release.tree_changes(tmp_path) == ["not a git checkout: a release is built from a commit"]


def _bundle(repo: Path, tmp: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    (tmp / "gates.json").write_text("{}", encoding="utf-8")
    (tmp / "sbom").mkdir(exist_ok=True)
    (tmp / "key").write_text("k", encoding="utf-8")
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PATH": f"{bindir}:/usr/bin:/bin",
        "PY": os.environ.get("TB_TEST_PY", "") or shutil.which("python3") or "python3",
    }
    cmd = ["bash", str(repo / "tools" / "make_bundle.sh"), "--key", str(tmp / "key"), "--id", "x", "--release-seq", "1",
           "--out", str(tmp / "out.tar"), "--gates", str(tmp / "gates.json"), "--sbom-dir", str(tmp / "sbom"), *extra]  # fmt: skip
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120, check=False)


def test_the_script_refuses_a_working_tree_and_names_the_files(repo: Path, tmp_path: Path) -> None:
    (repo / "tools" / "left_here.py").write_text("x = 1\n", encoding="utf-8")
    res = _bundle(repo, tmp_path)
    assert res.returncode == 2, res.stdout + res.stderr
    assert "tools/left_here.py" in res.stderr and "--allow-dirty" in res.stderr and "commit" in res.stderr
    assert not (tmp_path / "out.tar").exists()


def test_a_clean_checkout_passes_the_check_and_a_named_reason_passes_a_dirty_one(repo: Path, tmp_path: Path) -> None:
    clean = _bundle(repo, tmp_path)
    # the stand-in checkout has no compose files and maybe no docker: the script stops later, for another reason
    assert clean.returncode != 0 and "differs from its commit" not in clean.stderr and "allow-dirty" not in clean.stderr
    (repo / "tools" / "left_here.py").write_text("x = 1\n", encoding="utf-8")
    forced = _bundle(repo, tmp_path, "--allow-dirty", "a rehearsal")
    assert "differs from its commit; a release" not in forced.stderr  # not refused at the check
    assert "NOT a release" in forced.stderr and "a rehearsal" in forced.stderr and "tools/left_here.py" in forced.stderr
    empty = _bundle(repo, tmp_path, "--allow-dirty", "")
    assert empty.returncode == 2 and "reason" in empty.stderr


def test_the_check_comes_before_anything_is_exported_and_the_rehearsal_names_its_reason() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.index("status --porcelain") < text.index("command -v docker") < text.index('docker save "$ref"')
    # the script and the release record ask git the same question
    assert "--untracked-files=all" in text and "--untracked-files=all" in Path(release.__file__).read_text(
        encoding="utf-8"
    )
    rehearse = (ROOT / "tools" / "rehearse_box" / "rehearse.sh").read_text(encoding="utf-8")
    call = rehearse[rehearse.index("  tools/make_bundle.sh ") :][:600]
    assert '--allow-dirty "a rehearsal of the working tree"' in call.split("||")[0]


def test_the_release_record_counts_an_untracked_file_as_dirty(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "ROOT", repo)
    assert release.source("1.0.0")["dirty"] is False
    (repo / "tools" / "left_here.py").write_text("x = 1\n", encoding="utf-8")
    assert release.source("1.0.0")["dirty"] is True


# ---------------------------------------------------------------------------------------------- from the review
@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_review_a_file_git_was_told_not_to_look_at_is_a_change(repo: Path, tmp_path: Path, flag: str) -> None:
    """`git status` prints nothing for such a file, and the host tree packs it from disk as it stands."""
    (repo / "pyproject.toml").write_text('[project]\nname = "trialbox"\nversion = "6.6.6"\n', encoding="utf-8")
    _git(repo, "update-index", flag, "pyproject.toml")
    said = "\n".join(release.tree_changes(repo))
    assert "pyproject.toml" in said and "hidden from git" in said
    res = _bundle(repo, tmp_path)
    assert res.returncode == 2 and "pyproject.toml" in res.stderr and "differs from its commit" in res.stderr


def test_review_a_long_list_still_ends_in_the_refusal(repo: Path, tmp_path: Path) -> None:
    """`printf | head` under pipefail died of SIGPIPE (141) before the refusal's own exit."""
    for i in range(6000):
        (repo / "tools" / f"left_{i:04d}_{'x' * 40}.py").write_text("", encoding="utf-8")
    res = _bundle(repo, tmp_path)
    assert res.returncode == 2, res.returncode
    assert "... and 5980 more" in res.stderr
    forced = _bundle(repo, tmp_path, "--allow-dirty", "a rehearsal")
    assert forced.returncode != 141 and "NOT a release" in forced.stderr


def test_review_allow_dirty_needs_its_reason_and_a_flag_is_not_one(repo: Path, tmp_path: Path) -> None:
    last = _bundle(repo, tmp_path, "--allow-dirty")
    assert last.returncode == 2 and "reason" in last.stderr
    flag = _bundle(repo, tmp_path, "--allow-dirty", "--no-third-party")
    assert flag.returncode == 2 and "reason" in flag.stderr


def test_review_names_are_printed_as_they_are_and_gits_own_error_is_kept(repo: Path, tmp_path: Path) -> None:
    (repo / "tools" / "übrig.py").write_text("", encoding="utf-8")
    res = _bundle(repo, tmp_path)
    assert "übrig.py" in res.stderr
    bare = tmp_path / "bare" / "trialbox"
    shutil.copytree(repo, bare, ignore=shutil.ignore_patterns(".git"))
    res = subprocess.run(
        ["bash", str(bare / "tools" / "make_bundle.sh"), "--key", str(tmp_path / "key"), "--id", "x", "--release-seq", "1",
         "--out", str(tmp_path / "o.tar"), "--gates", str(tmp_path / "gates.json"), "--sbom-dir", str(tmp_path / "sbom")],
        capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)},
    )  # fmt: skip
    assert res.returncode == 2 and "not a git" in res.stderr.lower()


def test_review_the_tree_is_looked_at_again_after_the_host_tree_is_packed() -> None:
    """Exporting the images takes minutes: a file changed meanwhile would be packed after a check that passed."""
    text = SCRIPT.read_text(encoding="utf-8")
    pack = text.index("-m tools.host_tree pack")
    assert text.index("tree_changes", pack) > pack
    assert text[pack:].index("changed while the bundle was built") > 0


def test_review_the_record_says_what_the_check_cannot_cover() -> None:
    rec = next((ROOT / "docs" / "decisions").glob("D-631-*.md")).read_text(encoding="utf-8")
    for word in ("--models", "--rulesets", "--refdata", "images", "skip-worktree"):
        assert word in rec, word
