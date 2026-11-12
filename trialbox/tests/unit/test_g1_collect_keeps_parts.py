"""G1 bug A1: a collect after a pre-emption deleted the finished, paid-for part results.

``complete-run.sh --collect`` merges each VM's ``parts/`` (made under the VM's run id ``<run>-s<N>`` and the HEAD of
the uploaded archive) into the run folder, then runs the stub parts there with ``complete_run --resume --run-id
<run>``. That ``--resume`` removed every part file it judged to be of "another run or HEAD": hospital-ja, install and
prepare of G1 attempt 2 (5 h of card time). Two rules hold now: a ``--resume`` only ever removes a stale result of a
part it is about to run itself, and ``<run>`` and ``<run>-s<N>`` are one run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import complete_run as cr

VM_HEAD = "986d91c91352748b1e37775d6446b5405c7b1b19"  # the archive the VM ran, not this checkout's HEAD


def _res(run_id: str, head: str) -> dict[str, Any]:
    return {"stages": [{"name": "s", "ok": True, "seconds": 0, "checks": [["c", True, ""]]}],
            "run": {"id": run_id, "head": head}}  # fmt: skip


def test_a_shard_part_is_of_the_same_run() -> None:
    assert cr.same_run(_res("X-s1", "h"), "X", "h") == (True, "")  # the VM's part, read by the driver's merge
    assert cr.same_run(_res("X", "h"), "X-s1", "h") == (True, "")
    assert cr.same_run(_res("X-s2", "h"), "X-s1", "h") == (True, "")
    assert not cr.same_run(_res("Y-s1", "h"), "X", "h")[0]  # another run is still another run
    assert not cr.same_run(_res("X-s1", "old"), "X", "h")[0]  # the same run at another HEAD is still not kept
    assert not cr.same_run(_res("X-sx", "h"), "X", "h")[0]


def test_a_resume_removes_only_parts_it_runs(tmp_path: Path) -> None:
    parts = tmp_path / "parts"
    parts.mkdir()
    for tag in ("hospital-ja", "walk"):
        (parts / f"{tag}.json").write_text(json.dumps(_res("OTHER", "old")), encoding="utf-8")
    assert cr.drop_stale_parts(parts, "X", "h", tags=[]) == []  # nothing runs: nothing is removed
    assert cr.drop_stale_parts(parts, "X", "h", tags=["walk"]) == ["walk"]
    assert sorted(p.stem for p in parts.glob("*.json")) == ["hospital-ja"]


def test_the_collects_stub_resume_keeps_the_vms_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact call of the collect's merge (complete-run.sh) over parts the VM made as ``X-s1`` at its HEAD."""
    parts = tmp_path / "parts"
    parts.mkdir()
    made = {}
    for tag in ("hospital-ja", "install", "prepare"):
        made[tag] = json.dumps(_res("X-s1", VM_HEAD))
        (parts / f"{tag}.json").write_text(made[tag], encoding="utf-8")
    ran: list[list[str]] = []

    def no_part(a: Any, cmd: list[str], env: dict[str, str]) -> int:  # no part really runs
        ran.append(cmd)
        return 0

    monkeypatch.setattr(cr, "_run_part_process", no_part)
    cr.main(["--dir", str(tmp_path), "--resume", "--only", "walk", "backup", "update", "scale", "--patients", "50000",
             "--ocr", "tesseract", "--run-id", "X"])  # fmt: skip
    assert len(ran) == 4
    for tag, body in made.items():
        f = parts / f"{tag}.json"
        assert f.exists(), f"{tag}: the VM's finished part was deleted by the collect"
        assert f.read_text(encoding="utf-8") == body


# ------------------------------------------------------------------------------------------------ the rehearsal case
REH = Path(__file__).resolve().parents[1] / "rehearsal"


def _evidence(e: Path, driver_log: str) -> None:
    import io
    import tarfile

    done = ("scenario-gateway", "scenario-it-dump", "scenario-registry")
    (e / "parts-after-collect").mkdir(parents=True)
    (e / "out" / "parts").mkdir(parents=True)
    (e / "out" / "report").mkdir(parents=True)
    (e / "out" / "shard-1").mkdir(parents=True)
    for tag in done:
        body = json.dumps(_res("R-s1", VM_HEAD))
        (e / "parts-after-collect" / f"{tag}.json").write_text(body, encoding="utf-8")
        (e / "out" / "parts" / f"{tag}.json").write_text(body, encoding="utf-8")
    (e / "POWEROFF.preempt").write_text("t poweroff by: gcloud stop |\n", encoding="utf-8")
    (e / "POWEROFF").write_text("t poweroff by: tb-watchdog | TB-WATCHDOG results collected\n", encoding="utf-8")
    (e / "console.log").write_text("TB-COLLECT-ONLY: results.tgz (10 bytes) at /tb/results.tgz\n", encoding="utf-8")
    (e / "driver.log").write_text(driver_log, encoding="utf-8")
    vm = "".join(f"      {t}: done earlier in this run at this HEAD, kept (--resume)\n" for t in done)
    files = {"vm.log": vm.encode(), "parts/selftest-busy.json": json.dumps(_res("R-s1", VM_HEAD)).encode()}
    with tarfile.open(e / "out" / "shard-1" / "results.tgz", "w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    rep = {"parts": [{"tag": t} for t in (*done, "selftest-busy")], "not_run": []}
    (e / "out" / "report" / "report.json").write_text(json.dumps(rep), encoding="utf-8")


def test_the_rehearsal_has_the_preemption_case(tmp_path: Path) -> None:
    import subprocess
    import sys

    sh = (REH / "rehearse.sh").read_text(encoding="utf-8")
    assert "preempt)" in sh and "--shard 1" in sh and "check preempt" in sh
    only = "scenario-gateway,scenario-it-dump,scenario-registry,selftest-busy"
    assert f"PRE_ONLY={only}" in sh

    def check(e: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(REH / "check.py"), "preempt", str(e), "--only", only],
                              capture_output=True, text=True, check=False)  # fmt: skip

    _evidence(tmp_path / "good", "collected\n")
    good = check(tmp_path / "good")
    assert good.returncode == 0, good.stdout
    _evidence(tmp_path / "bug", "      --resume: 3 part result(s) of another run or HEAD removed: a b c\n")
    assert check(tmp_path / "bug").returncode == 1  # the G1 collect fails the case
