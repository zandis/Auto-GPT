"""TRIAGE-1 G5: deviations are rows. REAL100K ran with hand-set caps, the E2E patched the adapter's cap, the mapping
and the mail relay, and the scale gate ran under dev caps: proofs that patched the installed configuration. The run
writes each patch as a deviation in its evidence; the results table refuses a green row whose evidence carries a
deviation the proof does not record, and shows the recorded ones beside the green."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_results_table_m10 import HEAD, _proof, _refused
from tools import results_table as rt

pytestmark = pytest.mark.nodb

CAP = {"id": "cap-adapter", "what": "TB_MEM_ADAPTER 12g instead of the installer's 3520m"}
MAP = {"id": "mapping", "what": "the site mapping declares the 13 demo tables"}


def _with(folder: Path, criterion: str, devs: Any, recorded: Any = None, result: str = "green", **counts: Any) -> None:
    p = _proof(folder, criterion, result=result, deviations=devs, **counts)
    if recorded is not None:
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["deviations_recorded"] = recorded
        p.write_text(json.dumps(doc), encoding="utf-8")


def test_a_green_with_an_unrecorded_deviation_is_refused(tmp_path: Path) -> None:
    _with(tmp_path, "2c", [CAP, MAP], recorded=["mapping"])
    (reason,) = _refused(tmp_path)
    assert reason.startswith("2c: green") and "does not record: cap-adapter" in reason


def test_recorded_deviations_stand_beside_the_green(tmp_path: Path) -> None:
    _with(tmp_path, "2c", [CAP, MAP], recorded=["cap-adapter", "mapping"])
    (row,) = rt.build(tmp_path, HEAD)
    assert row.deviations == ("cap-adapter", "mapping")
    assert "2 recorded deviations (cap-adapter, mapping)" in rt.render([row], HEAD)


def test_a_red_row_may_carry_its_deviations(tmp_path: Path) -> None:
    _with(tmp_path, "2c", [CAP], result="red", failed=1)
    (row,) = rt.build(tmp_path, HEAD)
    assert row.result == "red"


def test_deviations_that_are_not_rows_are_refused(tmp_path: Path) -> None:
    _with(tmp_path, "2c", ["cap-adapter"])
    (reason,) = _refused(tmp_path)
    assert "not a list of rows with an id" in reason


def test_evidence_from_before_g5_has_none(tmp_path: Path) -> None:
    _proof(tmp_path, "1a")
    (row,) = rt.build(tmp_path, HEAD)
    assert row.deviations == () and row.shown() == "green"
