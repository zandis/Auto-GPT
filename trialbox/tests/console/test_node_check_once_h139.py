"""H-139: the console's Node Playwright check runs once per test process, and a node that does not answer in time
is one plain failure, never a skip.

On the bench host, node ran through a slow wrapper. Each module that imports the check called it again at import, so
every xdist worker waited 60 s for each of them, and the TimeoutExpired came out as a collection traceback per module.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from tests import node_check as nc
from tests.console import test_cjk_layout as cjk


@pytest.fixture
def fresh(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """A check not yet made in this process, with node found and every run of it recorded."""
    monkeypatch.setattr(nc, "FOUND", {})
    monkeypatch.setattr(nc.shutil, "which", lambda name: f"/synthetic/bin/{name}")
    return []


def test_a_node_that_does_not_answer_is_one_plain_failure_asked_once(
    fresh: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        fresh.append(argv)
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(nc.subprocess, "run", slow)
    for _ in range(3):  # three modules asking, in one process
        with pytest.raises(pytest.fail.Exception, match=r"node did not answer require\('playwright'\) within 60 s"):
            cjk._node_playwright()
    assert len(fresh) == 1, fresh


@pytest.mark.parametrize(("rc", "want"), [(0, True), (1, False)])
def test_an_answer_is_kept_for_the_process(
    fresh: list[list[str]], monkeypatch: pytest.MonkeyPatch, rc: int, want: bool
) -> None:
    def answer(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        fresh.append(argv)
        return subprocess.CompletedProcess(argv, rc, b"", b"")

    monkeypatch.setattr(nc.subprocess, "run", answer)
    assert [cjk._node_playwright() for _ in range(3)] == [want] * 3
    assert len(fresh) == 1


def test_no_node_at_all_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nc, "FOUND", {})
    monkeypatch.setattr(nc.shutil, "which", lambda name: None)
    assert cjk._node_playwright() is False
