from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools import external_worker as xw


@pytest.mark.nodb
def test_write_files_writes_allowed_and_creates_parents(tmp_path: Path) -> None:
    allowed = {"a/b/c.py"}
    answer = "=== FILE: a/b/c.py ===\n```\nprint('hi')\n```"
    written, refused = xw.write_files(tmp_path, answer, allowed)
    assert written == ["a/b/c.py"]
    assert refused == []
    p = tmp_path / "a/b/c.py"
    assert p.exists()
    assert p.read_text(encoding="utf-8") == "print('hi')\n"


@pytest.mark.nodb
def test_write_files_refuses_bad_paths(tmp_path: Path) -> None:
    allowed = {"good.py", "../evil.py", "/abs.py"}
    answer = (
        "=== FILE: good.py ===\n```\nok\n```\n"
        "=== FILE: ../evil.py ===\n```\nevil\n```\n"
        "=== FILE: /abs.py ===\n```\nabs\n```\n"
        "=== FILE: notallowed.py ===\n```\nno\n```\n"
    )
    written, refused = xw.write_files(tmp_path, answer, allowed)
    assert written == ["good.py"]
    assert set(refused) == {"../evil.py", "/abs.py", "notallowed.py"}
    assert (tmp_path / "good.py").read_text(encoding="utf-8") == "ok\n"
    assert not (tmp_path / "evil.py").exists()
    assert not (tmp_path / "abs.py").exists()
    assert not (tmp_path / "notallowed.py").exists()


@pytest.mark.nodb
def test_write_files_two_blocks_and_no_block(tmp_path: Path) -> None:
    allowed = {"f1.py", "f2.py"}
    answer_two = "=== FILE: f1.py ===\n```\n1\n```\n=== FILE: f2.py ===\n```\n2\n```"
    written, refused = xw.write_files(tmp_path, answer_two, allowed)
    assert written == ["f1.py", "f2.py"]
    assert refused == []
    assert (tmp_path / "f1.py").read_text(encoding="utf-8") == "1\n"
    assert (tmp_path / "f2.py").read_text(encoding="utf-8") == "2\n"
    answer_none = "no blocks here at all"
    written, refused = xw.write_files(tmp_path, answer_none, allowed)
    assert written == []
    assert refused == []


@pytest.mark.nodb
def test_main_returns_2_on_bad_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("task")
    logp = tmp_path / "log.log"
    base_argv = [
        "prog",
        "--task",
        str(task),
        "--root",
        str(tmp_path),
        "--edit",
        "a.py",
        "--check",
        "true",
        "--log",
        str(logp),
    ]
    monkeypatch.setattr(sys, "argv", base_argv)
    monkeypatch.delenv("XW_API_URL", raising=False)
    monkeypatch.setenv("XW_MODEL", "m")
    assert xw.main() == 2
    monkeypatch.setenv("XW_API_URL", "http://example.com")
    assert xw.main() == 2
    monkeypatch.setenv("XW_API_URL", "https://example.com")
    monkeypatch.delenv("XW_MODEL", raising=False)
    assert xw.main() == 2


@pytest.mark.nodb
def test_whole_run_stubbed_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("task")
    logp = tmp_path / "out.log"
    monkeypatch.setenv("XW_API_URL", "https://example.com")
    monkeypatch.setenv("XW_MODEL", "m")
    monkeypatch.setenv("XW_API_KEY", "secret123")

    def fake_call(api: str, model: str, messages: list[dict[str, str]], usage: dict[str, int]) -> str:
        usage["in"] += 10
        usage["out"] += 5
        return "=== FILE: a.py ===\n```\nnew content\n```"

    monkeypatch.setattr(xw, "call", fake_call)
    argv = [
        "prog",
        "--task",
        str(task),
        "--root",
        str(tmp_path),
        "--edit",
        "a.py",
        "--check",
        "test -s a.py",
        "--log",
        str(logp),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    ret = xw.main()
    assert ret == 0
    assert logp.exists()
    log_content = logp.read_text(encoding="utf-8")
    assert "secret123" not in log_content
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "new content\n"


@pytest.mark.nodb
def test_run_fails_check_then_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("task")
    logp = tmp_path / "log.log"
    monkeypatch.setenv("XW_API_URL", "https://example.com")
    monkeypatch.setenv("XW_MODEL", "m")
    monkeypatch.setenv("XW_API_KEY", "k")
    received: list[list[dict[str, str]]] = []

    def fake_call(api: str, model: str, messages: list[dict[str, str]], usage: dict[str, int]) -> str:
        received.append([m.copy() for m in messages])
        usage["in"] += 1
        usage["out"] += 1
        if len(received) == 1:
            return "=== FILE: f.txt ===\n```\nbad\n```"
        return "=== FILE: f.txt ===\n```\ngood\n```"

    monkeypatch.setattr(xw, "call", fake_call)
    argv = [
        "prog",
        "--task",
        str(task),
        "--root",
        str(tmp_path),
        "--edit",
        "f.txt",
        "--check",
        'test "$(cat f.txt)" = "good"',
        "--log",
        str(logp),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    ret = xw.main()
    assert ret == 0
    assert len(received) == 2
    last_user = received[1][-1]
    assert last_user["role"] == "user"
    assert "The check command failed" in last_user["content"]
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "good\n"


@pytest.mark.nodb
def test_run_never_passes_returns_1(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text("task")
    logp = tmp_path / "log.log"
    monkeypatch.setenv("XW_API_URL", "https://example.com")
    monkeypatch.setenv("XW_MODEL", "m")
    monkeypatch.setenv("XW_API_KEY", "k")

    def fake_call(api: str, model: str, messages: list[dict[str, str]], usage: dict[str, int]) -> str:
        usage["in"] += 1
        usage["out"] += 1
        return "=== FILE: f.txt ===\n```\nbad\n```"

    monkeypatch.setattr(xw, "call", fake_call)
    argv = [
        "prog",
        "--task",
        str(task),
        "--root",
        str(tmp_path),
        "--edit",
        "f.txt",
        "--check",
        'test "$(cat f.txt)" = "good"',
        "--log",
        str(logp),
        "--rounds",
        "2",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    ret = xw.main()
    assert ret == 1
