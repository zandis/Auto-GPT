"""The owner's rule of 2026-11-28 (``tools/commit_names.py``): a commit message on a pull request into ``int/*`` names
no model, and no trailer carries a version. Synthetic messages and a throwaway repository only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import commit_names as cn

pytestmark = pytest.mark.nodb

TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>\nClaude-Session: local (integrator's builder, one session)"


@pytest.mark.parametrize(
    "message",
    [
        f"INT-x: a fix\n\nThe body says why.\n\n{TRAILER}\n",
        f"INT-x: pgvector 0.8.7 in the db image (a version in the body is not a trailer)\n\n{TRAILER}\n",
        "INT-x: no trailer at all\n",
        f"INT-x\n\n{TRAILER.replace('local (integrator', 'b6edd13f-082f-4ab7-8fe5-eae24b6345c0 (one')}\n",
    ],
)
def test_a_message_that_names_no_model_passes(message: str) -> None:
    assert cn.problems(message) == []


@pytest.mark.parametrize(
    ("message", "why"),
    [
        ("INT-x\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n", "names a model"),
        ("INT-x\n\nCo-Authored-By: Claude Sonnet <noreply@anthropic.com>\n", "names a model"),
        ("INT-x\n\nReviewed-By: fable\n", "names a model"),
        ("INT-x: as HAIKU said\n", "names a model"),
        ("INT-x\n\nthe patch came from codex\n", "names a model"),
        ("INT-x\n\nAssisted-By: GPT-6.2\n", "names a model"),
        ("INT-x\n\nCo-Authored-By: Claude 5.5 <noreply@anthropic.com>\n", "a version in a trailer"),
        ("INT-x\n\nCo-Authored-By: Claude-5 <noreply@anthropic.com>\n", "a version in a trailer"),
        ("INT-x\n\nAssisted-By: the v6.2 model\n", "a version in a trailer"),
    ],
)
def test_a_message_that_names_a_model_or_a_version_in_a_trailer_fails(message: str, why: str) -> None:
    assert any(why in p for p in cn.problems(message)), cn.problems(message)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_the_check_reads_each_commit_of_the_range_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The base's own history is not read (older commits on ``int/*`` are not the pull request's)."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@example.test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "old\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"good\n\n{TRAILER}")
    good = _git(repo, "rev-parse", "HEAD")
    assert cn.main([f"{base}..{good}", "--repo", str(repo)]) == 0
    _git(repo, "commit", "-q", "--allow-empty", "-m", "bad\n\nCo-Authored-By: Claude 5.5 <noreply@anthropic.com>")
    bad = _git(repo, "rev-parse", "HEAD")
    assert cn.main([f"{base}..{bad}", "--repo", str(repo)]) == 1
    err = capsys.readouterr().err
    assert bad[:12] in err and good[:12] not in err and "a version in a trailer (trailer 1)" in err
    assert "noreply" not in err  # the kind and where, never the message's text
