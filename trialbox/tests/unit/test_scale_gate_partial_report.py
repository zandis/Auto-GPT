"""NEW-B-33 (D-674): the scale gate is not cut by the test suite's default time limit, and a gate that IS cut still
leaves the report of what it measured.

The nightly of 2026-11-13 (run 109, master 906889ee): the night's ingest of 50,000 patients passed under the
adapter's cap with the real HL7 validator (1,553,259 records in 817.8 s). The whole gate is one fixture; the
suite's default limit of 900 s per test cut it about 80 s into the site publish. The report was written only at
the gate's end, so the night left no report: not the ingest's peak memory, nothing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import config
from tb_testkit import scale

from tests.unit.test_scale_gate_logic import _params
from tools import scale_gate as sg

ROOT = Path(__file__).resolve().parents[2]


class Cut(BaseException):
    """What a time limit does to the gate: an error that is no ``Exception`` (as pytest's own time-limit failure)."""


def _report(tmp_path: Path) -> tuple[str, dict[str, Any]]:
    out = tmp_path / "gate"
    return (out / "scale_gate.md").read_text(encoding="utf-8"), json.loads((out / "scale_gate.json").read_text())


def test_a_gate_cut_in_the_site_publish_leaves_what_the_ingest_measured(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cut(*_a: Any, **_k: Any) -> Any:
        raise Cut

    monkeypatch.setattr(sg, "_publish", cut)
    with pytest.raises(Cut):
        sg.run(_params(tmp_path))
    md, js = _report(tmp_path)
    assert "NOT FINISHED" in md and "site publish" in md and "Gate: green" not in md and "Gate: RED" not in md
    rows = {r["check"]: r for r in js["rows"]}
    assert rows["ingest.night_under_cap"]["state"] == scale.PASS  # what was measured before the cut
    assert "publish.recorded_once" not in rows and "screen.ends_under_cap" not in rows  # not reached: no row
    assert js["unfinished"] and "site publish" in js["unfinished"] and js["ok"] is False
    ingest = next(line for line in md.splitlines() if line.startswith("| ingest (nightly)"))
    assert "| ok |" in ingest and "GiB" in ingest  # its result and its peak memory
    lake = next(line for line in md.splitlines() if line.startswith("| lake (rebuild, queries)"))
    assert "still running" in lake


@pytest.mark.parametrize("part", ["generate", "ingest (nightly)"])
def test_a_gate_cut_in_an_earlier_part_names_that_part(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, part: str
) -> None:
    real = scale.Enforcer.run

    def run(self: Any, name: str, *a: Any, **k: Any) -> Any:
        if name == part:
            raise Cut
        return real(self, name, *a, **k)

    monkeypatch.setattr(scale.Enforcer, "run", run)
    with pytest.raises(Cut):
        sg.run(_params(tmp_path))
    md, js = _report(tmp_path)
    assert f"NOT FINISHED: {part}" in md and js["unfinished"] == part and js["ok"] is False


def test_a_gate_that_ends_says_nothing_of_the_kind(tmp_path: Path, db_url: str) -> None:
    rep = sg.run(_params(tmp_path, outage_s=0.0, restart_after=0))
    md, js = _report(tmp_path)
    assert rep.ok() and "NOT FINISHED" not in md and "still running" not in md and "Gate: green" in md
    assert js["unfinished"] == "" and js["ok"] is True and set(r["check"] for r in js["rows"]) == set(sg.CHECKS)


def test_a_report_of_an_earlier_run_is_not_left_to_be_taken_for_this_one(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "gate"
    out.mkdir()
    (out / "scale_gate.md").write_text("# Scale gate\n\nGate: green\n", encoding="utf-8")
    real = scale.Enforcer.run

    def run(self: Any, name: str, *a: Any, **k: Any) -> Any:
        if name == "generate":
            raise Cut
        return real(self, name, *a, **k)

    monkeypatch.setattr(scale.Enforcer, "run", run)
    with pytest.raises(Cut):
        sg.run(_params(tmp_path))
    assert "Gate: green" not in (out / "scale_gate.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------- the gate's time limit
def _limit_of_the_gates_test(monkeypatch: pytest.MonkeyPatch, value: str | None) -> float:
    import importlib

    if value is None:
        monkeypatch.delenv("TB_SCALE_LIMIT_S", raising=False)
    else:
        monkeypatch.setenv("TB_SCALE_LIMIT_S", value)
    mod = importlib.import_module("tests.perf.test_scale_gate")
    mod = importlib.reload(mod)
    marks = mod.pytestmark if isinstance(mod.pytestmark, list) else [mod.pytestmark]
    (limit,) = [m for m in marks if m.name == "timeout"]
    return float(limit.args[0])


def test_the_gate_does_not_run_under_the_suites_default_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 is "no limit" to pytest-timeout: the night is measured, not budgeted. The nightly job's own limit ends a
    hang (its ``timeout-minutes``), and the gate's parts have their own guards."""
    assert _limit_of_the_gates_test(monkeypatch, None) == 0
    assert _limit_of_the_gates_test(monkeypatch, "") == 0
    assert _limit_of_the_gates_test(monkeypatch, "1800") == 1800  # a person's own limit, on their own machine
    assert "TB_SCALE_LIMIT_S" in config.DECLARED


def test_the_suites_default_limit_is_still_there_for_every_other_test_and_the_job_bounds_the_gate() -> None:
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["pytest"]["ini_options"]["timeout"] > 0
    wf = yaml.safe_load((ROOT.parent / ".github/workflows/trialbox-e2e.yml").read_text(encoding="utf-8"))
    assert wf["jobs"]["scale-50k"]["timeout-minutes"] > 0  # the bound of the gate: the job's own
