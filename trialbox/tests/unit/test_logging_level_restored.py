"""The five commands that switch INFO logging off put back the level they found, on return and on an exception (H-87).

``backup_drill.main()`` left ``logging.disable(INFO)`` on in the test process: every later test that reads an INFO
record failed (the polluter ``test_backup_drill_says_why``, the victims the INFO tests of ``test_access_log_route``).
Each case here starts from a level no command sets (WARNING), runs the command to a return and to a raise, and
asserts the level is the one found."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tools import backup_drill, complete_run, demo, e2e_simple, update_drill
from tools.logging_level import restores_logging_level

pytestmark = pytest.mark.nodb

FOUND = logging.WARNING  # not INFO (what the commands set) and not NOTSET (the default), so a reset is caught too


@pytest.fixture
def found_level() -> Iterator[int]:
    before = logging.root.manager.disable
    logging.disable(FOUND)
    try:
        yield FOUND
    finally:
        logging.disable(before)


class Boom(RuntimeError):
    pass


def _boom(*_a: Any, **_k: Any) -> Any:
    raise Boom("the command failed part way")


def _exit(*_a: Any, **_k: Any) -> Any:
    raise SystemExit(3)


def _no_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import config

    monkeypatch.setattr(config, "adopt_site_tz", lambda *a, **k: None)


def _drill_out(*_a: Any, **_k: Any) -> dict[str, Any]:
    return {"ok": True, "checks": [("a check", True, "")], "skipped": [], "seconds": 0.1}


def test_the_wrapper_restores_on_return_raise_and_exit(found_level: int) -> None:
    def quiet(then: Callable[[], Any]) -> Any:
        logging.disable(logging.INFO)
        return then()

    wrapped = restores_logging_level(quiet)
    assert wrapped(lambda: 7) == 7
    assert logging.root.manager.disable == found_level
    with pytest.raises(Boom):
        wrapped(_boom)
    assert logging.root.manager.disable == found_level
    with pytest.raises(SystemExit):
        wrapped(_exit)
    assert logging.root.manager.disable == found_level


@pytest.mark.parametrize("module", [backup_drill, update_drill], ids=["backup_drill", "update_drill"])
@pytest.mark.parametrize("run", [_drill_out, _boom, _exit], ids=["returns", "raises", "exits"])
def test_a_drill_puts_the_level_back(
    module: Any, run: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found_level: int
) -> None:
    _no_tz(monkeypatch)
    monkeypatch.setattr(module, "run", run)
    argv = ["--dir", str(tmp_path / "drill")]
    if run is _drill_out:
        assert module.main(argv) == 0
    else:
        with pytest.raises((Boom, SystemExit)):
            module.main(argv)
    assert logging.root.manager.disable == found_level


@pytest.mark.parametrize("run", ["returns", "raises"])
def test_e2e_simple_puts_the_level_back(
    run: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found_level: int
) -> None:
    _no_tz(monkeypatch)
    monkeypatch.setattr(e2e_simple, "missing_prerequisites", lambda: [])
    monkeypatch.setattr(e2e_simple, "prepare_root", lambda: None)
    monkeypatch.setattr(e2e_simple, "report", lambda out: "report")
    monkeypatch.setattr(
        e2e_simple, "run", (lambda *a: {"ok": True, "stages": [], "seconds": 0.1}) if run == "returns" else _boom
    )
    argv = ["--dir", str(tmp_path / "e2e")]
    if run == "returns":
        assert e2e_simple.main(argv) == 0
    else:
        with pytest.raises(Boom):
            e2e_simple.main(argv)
    assert logging.root.manager.disable == found_level


@pytest.mark.parametrize("run", ["returns", "raises"])
def test_demo_puts_the_level_back_off_the_serving_path(
    run: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found_level: int
) -> None:
    _no_tz(monkeypatch)
    monkeypatch.setenv("TB_DEMO_DAY", "data")
    monkeypatch.setenv("TB_ENV", "TEST")

    def accounts_refused(a: argparse.Namespace) -> dict[str, Any]:
        raise demo.AccountsError("the accounts file is refused")

    monkeypatch.setattr(demo, "start", accounts_refused if run == "returns" else _boom)
    argv = ["--dir", str(tmp_path / "demo"), "--no-serve"]
    if run == "returns":
        assert demo.main(argv) == 2  # an early return, before the serving path that switched it back on
    else:
        with pytest.raises(Boom):
            demo.main(argv)
    assert logging.root.manager.disable == found_level


@pytest.mark.parametrize("run", ["returns", "raises"])
def test_complete_run_part_puts_the_level_back(
    run: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found_level: int
) -> None:
    a = argparse.Namespace(
        part="engine", lang="ja", scenario="", variant="", shots=tmp_path / "shots", dir=tmp_path / "run",
        run_id="r1", resume=True, llm_concurrency="",
    )  # fmt: skip
    final = a.dir / "parts" / f"{complete_run._tag(a.part, a.lang, a.scenario)}.json"
    final.parent.mkdir(parents=True)
    final.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(complete_run, "run_identity", lambda run_id: {"head": "h"})
    monkeypatch.setattr(complete_run, "same_run", lambda old, run_id, head: (True, ""))
    monkeypatch.setattr(complete_run, "_passed", lambda res: True)
    if run == "returns":
        assert complete_run.run_part(a) == 0  # done earlier in this run (--resume): an early return
    else:
        monkeypatch.setattr(complete_run, "run_identity", _boom)
        with pytest.raises(Boom):
            complete_run.run_part(a)
    assert logging.root.manager.disable == found_level
