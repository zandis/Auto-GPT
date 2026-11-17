"""H-25 (D-1124): a demo or steps-mode box runs the orchestrator's opt-out worker, and nothing else of its start-up.

``tools.demo.start_up`` starts what :data:`tools.demo.START_UP` turns on: the opt-out worker (D-441), so a tester
sees an erase complete and the health check ``optout_worker`` is green. The rest of the orchestrator's start-up
(``services/orchestrator/app.py``, ``lifespan``) stays off by name: the job workers, the model pair canary, the
night's clocks and the site-publish batch tick, also on a box started with no ``TB_ENV`` (PRODUCTION by the one
rule). A part the lifespan gains that the table does not name fails here until it is decided.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from tools import demo

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "services" / "orchestrator" / "app.py"

pytestmark = pytest.mark.nodb

#: how each part of the lifespan shows in its code (a call that starts something), by the table's name
MARKS = {
    "workers": r"\bo\.start\(\)",
    "canary": r"canary_gate\.startup\(",
    "scheduler": r"from orchestrator\.scheduler import start\b",
    "site_publish_batch": r"site-publish-batch",
    "optout_worker": r"\boptout_start\(",
}


def lifespan_source() -> str:
    text = APP.read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    return ast.get_source_segment(text, fn) or ""


def test_the_table_names_every_part_of_the_orchestrators_start_up() -> None:
    src = lifespan_source()
    assert set(demo.START_UP) == set(MARKS)
    for name, mark in MARKS.items():
        assert re.search(mark, src), (name, "the lifespan no longer has this part: update tools.demo.START_UP")
    # every call in the lifespan that starts something is one of the parts above: ``start(`` is the scheduler's (its
    # import is the mark), ``sched.add_job(`` the site-publish batch tick
    calls = {
        "o.start(": "workers",
        "canary_gate.startup(": "canary",
        "start(": "scheduler",
        "sched.add_job(": "site_publish_batch",
        "optout_start(": "optout_worker",
    }
    starts = re.findall(r"[\w.]*(?:start|startup|add_job)\w*\(", src)
    unknown = sorted({s for s in starts if s not in calls})
    assert not unknown, f"the lifespan starts something tools.demo.START_UP does not name: {unknown}"
    assert set(calls.values()) == set(demo.START_UP)
    assert {k for k, v in demo.START_UP.items() if v == "on"} == {"optout_worker"}


class _Sched:
    def __init__(self) -> None:
        self.down = False

    def shutdown(self, wait: bool = True) -> None:
        self.down = True


@pytest.mark.parametrize("tb_env", ["unset", "DEV", "PRODUCTION"])
def test_only_the_opt_out_worker_starts_also_without_tb_env(tb_env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from datacore import optout_worker
    from orchestrator import canary_gate, scheduler

    started: list[tuple[Any, bool]] = []
    sched = _Sched()

    def worker(orch: Any, production: bool = False) -> _Sched:
        started.append((orch, production))
        return sched

    def never(*_a: Any, **_k: Any) -> None:
        raise AssertionError("a demo box starts no more of the orchestrator's start-up than the opt-out worker")

    monkeypatch.setattr(optout_worker, "start", worker)
    monkeypatch.setattr(scheduler, "start", never)
    monkeypatch.setattr(canary_gate, "startup", never)
    monkeypatch.setattr(demo.atexit, "register", lambda _f: None)
    env: dict[str, str] = {} if tb_env == "unset" else {"TB_ENV": tb_env}
    orch = object()
    stop = demo.start_up(orch, env)
    assert started == [(orch, False)]
    assert env[optout_worker.MINUTES_ENV] == demo.OPTOUT_MINUTES == "1"
    stop()
    assert sched.down


def test_a_set_interval_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    from datacore import optout_worker

    monkeypatch.setattr(optout_worker, "start", lambda _o, production=False: None)
    monkeypatch.setattr(demo.atexit, "register", lambda _f: None)
    env = {optout_worker.MINUTES_ENV: "5"}
    demo.start_up(object(), env)()
    assert env[optout_worker.MINUTES_ENV] == "5"


def test_the_box_starts_it_only_when_it_serves_after_the_seed() -> None:
    """``main`` calls ``start_up`` after the seed and its checks, on the step that serves (never with --no-serve)."""
    src = (ROOT / "tools" / "demo.py").read_text(encoding="utf-8")
    main = src[src.index("def main(") :]
    assert main.index("if a.no_serve:") < main.index('start_up(out["box"].orch)') < main.index("uvicorn.run(")
    assert main.count("start_up(") == 1
