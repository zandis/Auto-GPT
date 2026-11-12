"""G1 bug A5: the partial report said FAILED for parts that never ran.

After the pre-emption the collect's report read ``report FAILED: 216/238 checks`` although every part that ran had
passed but one check: each part with no result counted as "<part> did not report", one failed check. Now a part
without a result is ``pending`` (its VM still runs) or ``not run (VM stopped)``; neither counts as a check. The
verdict is FAILED only when a part that ran has a failed check, INCOMPLETE while parts are missing, else PASSED."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools import complete_run as cr

TAGS = ["prepare", "install", "hospital-ja", "hospital-zh-TW", "scenario-it-dump"]


def _part(ok: bool = True) -> dict[str, Any]:
    return {"stages": [{"name": "s", "ok": ok, "seconds": 1, "checks": [["c", True, ""], ["d", ok, ""]]}],
            "run": {"id": "R-s1", "head": "a" * 40}, "wall_seconds": 1.0}  # fmt: skip


def _report(d: Path, *extra: str, **parts: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    (d / "parts").mkdir(parents=True, exist_ok=True)
    for tag, res in parts.items():
        (d / "parts" / f"{tag.replace('_', '-')}.json").write_text(json.dumps(res), encoding="utf-8")
    rc = cr.main(["--dir", str(d), "--report-only", "--model", "pair", "--patients", "50000", "--ocr", "tesseract",
                  "--run-id", "R", "--report-parts", *TAGS, *extra])  # fmt: skip
    rep = json.loads((d / "report" / "report.json").read_text(encoding="utf-8"))
    return rc, rep, (d / "report" / "report.md").read_text(encoding="utf-8")


def test_parts_that_never_ran_are_not_failures(tmp_path: Path) -> None:
    rc, rep, md = _report(tmp_path, prepare=_part(), install=_part(), hospital_ja=_part())
    assert rep["failed"] == 0 and rep["checks"] == 6  # the missing parts count no check
    assert rep["verdict"] == "INCOMPLETE" and not rep["ok"] and rc != 0
    assert {x["tag"]: x["state"] for x in rep["not_started"]} == {
        "hospital-zh-TW": "not run (VM stopped)", "scenario-it-dump": "not run (VM stopped)"}  # fmt: skip
    assert "FAILED" not in md and "did not report" not in md
    assert "**INCOMPLETE**" in md and "| hospital-zh-TW | hospital-zh-TW: not run (VM stopped) | 0/0 | not run" in md


def test_parts_of_a_vm_still_running_are_pending(tmp_path: Path) -> None:
    _, rep, md = _report(tmp_path, "--pending-parts", "hospital-zh-TW", "scenario-it-dump", prepare=_part(),
                         install=_part(), hospital_ja=_part())  # fmt: skip
    assert {x["state"] for x in rep["not_started"]} == {"pending"} and rep["verdict"] == "INCOMPLETE"
    assert "| hospital-zh-TW | hospital-zh-TW: pending | 0/0 | pending" in md


def test_failed_only_when_a_part_that_ran_failed_a_check(tmp_path: Path) -> None:
    _, rep, md = _report(tmp_path, prepare=_part(), install=_part(), hospital_ja=_part(ok=False))
    assert rep["verdict"] == "FAILED" and rep["failed"] == 1 and "**FAILED**: 5 of 6 checks" in md


def test_every_part_passed_is_passed(tmp_path: Path) -> None:
    rc, rep, _ = _report(tmp_path, prepare=_part(), install=_part(), hospital_ja=_part(), hospital_zh_TW=_part(),
                          scenario_it_dump=_part())  # fmt: skip
    assert rep["verdict"] == "PASSED" and rep["ok"] and rc == 0 and not rep["not_started"]


def test_a_part_that_ran_and_left_no_result_still_fails(tmp_path: Path) -> None:
    """On the VM, run_all knows a part ran: no result file there is "did not report", a failed check, as before."""
    rows = [{"tag": "hospital-ja", "part": "hospital", "lang": "ja", "seconds_total": 1.0, "not_run": "did not report",
             "stages": [{"name": "hospital-ja did not report", "ok": False, "seconds": 0,
                         "checks": [["part ran", False, "exit -9"]]}]}]  # fmt: skip
    a = argparse.Namespace(model="pair", direct=False, ocr="tesseract", patients=50000, langs=["ja"],
                              planned_from=None)  # fmt: skip
    rep = cr.report(a, rows, {"head": "", "subject": "", "dirty": False}, datetime.now(UTC))
    assert rep["verdict"] == "FAILED"
