"""The e2e-box gate's own rules (TRIAGE-1 G1, G5, G6): the install transcript keeps no one-time value and is
root-only; every planned browser action has a row; the verdict is GREEN only with every product failure and skip
listed, a conclusive run, no journey regressed and every changed setting named by an applied DEVIATION row.
Synthetic lines and runs only."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.nodb
BOX = Path(__file__).resolve().parents[1] / "e2e-box"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"e2e_box_{name}", BOX / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ptyi = _load("ptyinstall")
verdict = _load("verdict")
actions = _load("actions")


def test_the_one_time_password_and_code_never_reach_the_transcript() -> None:
    lines = [
        "    console: password (shown once): Zq7-synthetic_Pw9\n",
        "    console: enrolment code for 'admin' (shown once, valid 24 hours): SYNTH-CODE-1234\n",
        "    console: enrolment code (shown once, valid 24 hours): SYNTH-CODE-5678\n",
    ]
    found: dict[str, str] = {}
    for line in lines:
        clean, got = ptyi.redact(line)
        found.update(got)
        assert "<redacted>" in clean and "synthetic_Pw9" not in clean and "SYNTH-CODE" not in clean, clean
    assert found == {"password": "Zq7-synthetic_Pw9", "enrol": "SYNTH-CODE-5678"}
    plain = "    console: password of 'admin' changed; all sessions ended\n"
    assert ptyi.redact(plain) == (plain, {})


def test_a_label_waiting_for_its_value_is_never_taken_for_a_question() -> None:
    # a read that stops after the label, then a pause: answering it would log the value on the next read unlabelled
    assert not ptyi.is_prompt("    console: password (shown once): ", 5.0)
    assert not ptyi.is_prompt("    console: enrolment code for 'admin' (shown once, valid 24 hours):", 5.0)
    assert ptyi.is_prompt("Administrator's mail address:", 5.0)
    assert not ptyi.is_prompt("Administrator's mail address:", 0.5)


def test_the_transcript_files_are_root_only_whatever_the_umask(tmp_path: Path) -> None:
    old = os.umask(0)
    try:
        fd = ptyi.private(str(tmp_path / "install.log"))
        os.close(fd)
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "install.log").stat().st_mode) == 0o600


def test_the_passphrase_is_typed_but_never_shown_and_the_size_is_declared() -> None:
    assert ptyi.answer("KEK passphrase:", "pass-synthetic", "50000") == ("pass-synthetic", False)
    assert ptyi.answer("Type it again:", "pass-synthetic", "50000", True) == ("pass-synthetic", False)
    assert ptyi.answer("Type YES to confirm:", "pass-synthetic", "50000") == ("", True)  # not after a passphrase prompt
    assert ptyi.answer("How many patients does the hospital hold?", "x", "50000") == ("50000", True)


def test_every_planned_action_has_a_row_and_a_lost_session_never_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = {"actions": [{"j": "J1", "id": "a", "as": "crc1", "method": "GET", "path": "/home"},
                        {"j": "J1", "id": "b", "as": "crc1", "method": "GET", "path": "/week"},
                        {"j": "J1", "id": "c", "as": "crc1", "method": "GET", "path": "/jobs"}]}  # fmt: skip
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    out = [{"id": "a", "status": 200}, {"id": "b", "status": 303, "location": "/login?next=/week"}]
    (tmp_path / "out.jsonl").write_text("".join(json.dumps(o) + "\n" for o in out), encoding="utf-8")
    actions.rows(str(tmp_path / "plan.json"), str(tmp_path / "out.jsonl"))
    got = {r.split("\t")[1]: r.split("\t") for r in capsys.readouterr().out.splitlines()}
    assert got["a"][2] == "PASS" and got["b"][2] == "FAIL", got
    assert got["c"][2] == "FAIL" and got["c"][4].startswith("no result"), got


def _run(tmp_path: Path, rows: list[str], installed: str = "env:A x\n", checked: str = "env:A x\n") -> Path:
    run = tmp_path / "run1"
    (run / "metrics").mkdir(parents=True)
    head = "ts,attempt,journey,step,result,seconds,detail\n"
    ok = "t,1,INSTALL,one-command install; the questions answered,PASS,900,rc=0\n"
    (run / "metrics" / "steps.csv").write_text(head + ok + "".join(r + "\n" for r in rows), encoding="utf-8")
    (run / "metrics" / "config-installed.txt").write_text(installed, encoding="utf-8")
    (run / "metrics" / "config-checked.txt").write_text(checked, encoding="utf-8")
    return run


def _why(run: Path) -> str:
    return (run / "verdict").read_text(encoding="utf-8")


def test_an_unlisted_product_failure_or_skip_is_red_and_a_fully_listed_one_green(tmp_path: Path) -> None:
    run = _run(
        tmp_path, ["t,1,DATA-night,N1 full night,FAIL,1331,rc=137 killed", "t,1,OPS-update,update,SKIP,0,no media"]
    )
    assert verdict.main(run) == 1
    assert "unlisted FAIL [DATA-night] N1 full night" in _why(run) and "unlisted SKIP [OPS-update] update" in _why(run)
    known = tmp_path / "known.tsv"
    known.write_text("# journey\tstep\tfinding\towner\tnote\nDATA-night\tN1 full night\tP-02\tbatch B\tcaps\n"
                     "OPS-update\tupdate\tnone\tlane H\tno next bundle tonight\n", encoding="utf-8")  # fmt: skip
    assert verdict.main(run, None, known) == 0
    assert "P-02 (batch B)" in (run / "metrics" / "fails.tsv").read_text(encoding="utf-8")
    known.write_text("DATA-night\tN1 full night\tP-02\nOPS-update\tupdate\tnone\tlane H\tx\n", encoding="utf-8")
    assert verdict.main(run, None, known) == 1  # a row with no owner or release note lists nothing


def test_harness_failures_make_the_run_inconclusive_and_by_design_refusals_count_apart(tmp_path: Path) -> None:
    run = _run(tmp_path, [
        "t,1,SCREEN-screen,SCREEN ends,FAIL,10,a value this step needs was not saved by an earlier step",
        "t,1,OPS-power-cut,the cut night run again ends,FAIL,594,a newer night (2026-11-27) is already served",
        "t,1,ROLE-admin,the first password and enrolment code reach the harness only,FAIL,1,rc=1",
    ])  # fmt: skip
    assert verdict.main(run) == 1
    line, why = _why(run).splitlines()[0], _why(run)
    assert "fail_product=1" in line and "by_design=1" in line and "harness=1" in line, line
    assert "inconclusive: harness failure [SCREEN-screen] SCREEN ends" in why
    assert "unlisted FAIL [ROLE-admin] the first password" in why  # the word "harness" in a step name excuses nothing


def test_a_journey_that_regressed_or_vanished_against_the_baseline_is_red(tmp_path: Path) -> None:
    run = _run(tmp_path, ["t,1,MAIL,relay set,PASS,1,ok"])
    base = tmp_path / "base.csv"
    base.write_text(
        ",".join(verdict.COLS) + "\nMAIL,2,2,0,0,0,0,2,relay set,1\nOPS-update,1,1,0,0,0,0,1,x,1\n", encoding="utf-8"
    )
    assert verdict.main(run, base) == 1
    assert "regressed MAIL: pass 2 -> 1" in _why(
        run
    ) and "regressed OPS-update: in the baseline, not in this run" in _why(run)


def test_a_changed_setting_needs_an_applied_deviation_row_naming_it(tmp_path: Path) -> None:
    before = "env:TB_MEM_ADAPTER aaaa\nfile:site/mapping/tw_core/box_site.yaml bbbb\n"
    after = "env:TB_MEM_ADAPTER cccc\nfile:site/mapping/tw_core/box_site.yaml bbbb\n"
    run = _run(tmp_path, [], before, after)
    assert verdict.main(run) == 1
    assert "unrecorded deviation env:TB_MEM_ADAPTER" in _why(run)
    run = _run(tmp_path / "b", ["t,1,DEVIATION,P02-cap: TB_MEM_ADAPTER=12g,APPLIED,0,"], before, after)
    assert verdict.main(run) == 0
    run = _run(tmp_path / "c", ["t,1,DEVIATION,P02-cap: TB_MEM_ADAPTER=12g,FAILED,0,"], before, after)
    assert verdict.main(run) == 1
    assert "inconclusive: deviation not applied" in _why(run) and "unrecorded deviation env:TB_MEM_ADAPTER" in _why(run)
    run = _run(tmp_path / "d", ["t,1,DEVIATION,P02-cap: TB_MEM_ADAPTER_OLD=1,APPLIED,0,"], before, after)
    assert verdict.main(run) == 1  # another key that merely starts with the same letters names nothing


def test_no_install_or_no_settings_snapshot_no_green(tmp_path: Path) -> None:
    run = _run(tmp_path, ["t,2,INSTALL,one-command install; the questions answered,FAIL,30,rc=1"])
    assert verdict.main(run) == 1
    run = _run(tmp_path / "b", [], installed="", checked="")
    assert verdict.main(run) == 1
    assert "no snapshot of the box's settings" in _why(run)
