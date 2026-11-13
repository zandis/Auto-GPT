"""NEW-B-33 (D-674): a part of the scale gate that makes no progress ends the gate; a slow one runs to its end.

The gate's test has no time limit of its own (a night is measured, not budgeted). So that "no limit" does not mean
a hung part burns the nightly job's 340 minutes, every wait of the gate watches for progress: the processor time
of the processes the gate started and the growth of their logs. Nothing of that changing for ``TB_SCALE_STALL_S``
ends the gate, with its report, the part that stalled and what was last seen."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from tb_common import config
from tb_testkit import scale

from tests.unit.test_scale_gate_logic import _params
from tools import scale_gate as sg

GIB = 1 << 30
SLEEPS = "import time; time.sleep(600)"
BUSY = "import time; t = time.monotonic()\nwhile time.monotonic() - t < 3: pass"
TALKS = "import sys, time\nfor i in range(10):\n    print(i, flush=True); time.sleep(0.3)"


def _run(tmp_path: Path, script: str, stall_s: float) -> scale.PhaseRun:
    enf = scale.Enforcer.detect("measure")
    enf.stall_s = stall_s
    return enf.run("part", "adapter", GIB, [sys.executable, "-c", script], {}, tmp_path, tmp_path / "part.log")


def test_a_process_that_does_nothing_is_ended_and_named(tmp_path: Path) -> None:
    t0 = time.monotonic()
    with pytest.raises(scale.Stalled) as got:
        _run(tmp_path, SLEEPS, stall_s=1.0)
    assert time.monotonic() - t0 < 30  # not the 600 s the process would have slept
    said = str(got.value)
    assert "part" in said and "no progress" in said and "TB_SCALE_STALL_S" in said
    assert "processor time" in said and "log" in said  # what was watched, and what it last saw


def test_a_process_that_works_or_writes_its_log_runs_to_its_end(tmp_path: Path) -> None:
    assert _run(tmp_path, BUSY, stall_s=1.0).rc == 0  # three seconds of work with a one-second stall limit
    assert _run(tmp_path, TALKS, stall_s=1.0).rc == 0  # mostly asleep, but its log grows


def test_no_stall_limit_waits_as_before(tmp_path: Path) -> None:
    quick = "import time; time.sleep(1.5)"
    assert _run(tmp_path, quick, stall_s=0).rc == 0


def test_the_longest_quiet_interval_of_each_process_is_in_the_report(tmp_path: Path) -> None:
    """What a later default can be chosen from: the report says how long each process was quiet at most."""
    run = _run(tmp_path, "import time; time.sleep(1.2)", stall_s=0)
    assert 0.8 <= run.quiet_max_s <= 5
    rep = sg.Report(sg.Params(patients=1, out=tmp_path, caps={"adapter": GIB, "lake": GIB, "orchestrator": GIB}), "m")
    rep.runs.append(run)
    assert rep.to_json()["runs"][0]["longest_quiet_s"] == round(run.quiet_max_s, 1)


def test_a_site_publish_that_stops_moving_ends_the_gate_with_its_report(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sitesetup.service import SiteSetup

    def pending_for_ever(self: Any, ws: str) -> dict[str, Any]:
        return {"pending": True}  # the publish never starts its rebuild: the lake sits idle

    monkeypatch.setattr(SiteSetup, "flush", pending_for_ever)
    t0 = time.monotonic()
    with pytest.raises(scale.Stalled) as got:
        sg.run(_params(tmp_path, stall_s=2.0, publish_poll_s=0.2))
    assert time.monotonic() - t0 < 120  # minutes at most, not the publish's own six-hour guard
    assert "site publish" in str(got.value) and "pending" in str(got.value)  # the part, and what it last saw
    out = tmp_path / "gate"
    md = (out / "scale_gate.md").read_text(encoding="utf-8")
    js = json.loads((out / "scale_gate.json").read_text(encoding="utf-8"))
    assert "NOT FINISHED: site publish and lake rebuild" in md and "no progress" in md and js["ok"] is False
    assert {r["check"] for r in js["rows"]} >= {"ingest.night_under_cap"}  # what was measured before it


def test_the_stall_limit_is_a_declared_setting_with_a_default() -> None:
    assert "TB_SCALE_STALL_S" in config.DECLARED
    p = sg.params_from_env(Path("x"), 10)
    assert p.stall_s == sg.STALL_S > 0


def test_a_stall_limit_from_the_environment_is_read_and_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SCALE_STALL_S", "90")
    assert sg.params_from_env(Path("x"), 10).stall_s == 90
    monkeypatch.setenv("TB_SCALE_STALL_S", "0")
    assert sg.params_from_env(Path("x"), 10).stall_s == 0  # 0: no stall cut
    monkeypatch.setenv("TB_SCALE_STALL_S", "-3")
    with pytest.raises(ValueError, match="TB_SCALE_STALL_S"):
        sg.params_from_env(Path("x"), 10)
