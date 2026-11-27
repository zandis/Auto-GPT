"""The e2e-box gate's own rules (TRIAGE-1 G1, G5, G6): the install transcript keeps no one-time value and is
root-only, and the verdict is GREEN only with every product failure listed, no journey regressed and every changed
setting named by a DEVIATION row. Synthetic lines and runs only."""

from __future__ import annotations

import importlib.util
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
    assert ptyi.answer("Type it again:", "pass-synthetic", "50000") == ("pass-synthetic", False)
    assert ptyi.answer("How many patients does the hospital hold?", "x", "50000") == ("50000", True)


def _run(tmp_path: Path, rows: list[str], installed: str = "", checked: str = "") -> Path:
    run = tmp_path / "run1"
    (run / "metrics").mkdir(parents=True)
    head = "ts,attempt,journey,step,result,seconds,detail\n"
    ok = "t,1,INSTALL,one-command install; the questions answered,PASS,900,rc=0\n"
    (run / "metrics" / "steps.csv").write_text(head + ok + "".join(r + "\n" for r in rows), encoding="utf-8")
    (run / "metrics" / "config-installed.txt").write_text(installed, encoding="utf-8")
    (run / "metrics" / "config-checked.txt").write_text(checked, encoding="utf-8")
    return run


def test_an_unlisted_product_failure_is_red_and_a_listed_one_green(tmp_path: Path) -> None:
    run = _run(tmp_path, ["t,1,DATA-night,N1 full night,FAIL,1331,rc=137 killed"])
    assert verdict.main(run) == 1
    assert "unlisted FAIL [DATA-night] N1 full night" in (run / "verdict").read_text(encoding="utf-8")
    known = tmp_path / "known.tsv"
    known.write_text(
        "# journey\tstep\tfinding\towner\tnote\nDATA-night\tN1 full night\tP-02\tbatch B\tcaps\n", encoding="utf-8"
    )
    assert verdict.main(run, None, known) == 0
    assert "P-02 (batch B)" in (run / "metrics" / "fails.tsv").read_text(encoding="utf-8")


def test_a_later_pass_counts_and_harness_or_by_design_failures_are_apart(tmp_path: Path) -> None:
    run = _run(tmp_path, [
        "t,1,SCREEN-screen,SCREEN ends,FAIL,10,a value this step needs was not saved by an earlier step",
        "t,1,OPS-power-cut,the cut night run again ends,FAIL,594,a newer night is already served",
        "t,1,DATA-night,N1 full night,FAIL,1331,rc=137",
        "t,2,DATA-night,N1 full night,PASS,1015,rc=0",
    ])  # fmt: skip
    assert verdict.main(run) == 0
    line = (run / "verdict").read_text(encoding="utf-8").splitlines()[0]
    assert "fail_product=0" in line and "by_design=1" in line and "harness=1" in line, line


def test_a_journey_that_regressed_against_the_baseline_is_red(tmp_path: Path) -> None:
    run = _run(tmp_path, ["t,1,MAIL,relay set,PASS,1,ok"])
    base = tmp_path / "base.csv"
    base.write_text(",".join(verdict.COLS) + "\nMAIL,2,2,0,0,0,0,2,relay set,1\n", encoding="utf-8")
    assert verdict.main(run, base) == 1
    assert "regressed MAIL: pass 2 -> 1" in (run / "verdict").read_text(encoding="utf-8")


def test_a_changed_setting_needs_a_deviation_row_naming_it(tmp_path: Path) -> None:
    before = "env:TB_MEM_ADAPTER aaaa\nfile:site/mapping/tw_core/box_site.yaml bbbb\n"
    after = "env:TB_MEM_ADAPTER cccc\nfile:site/mapping/tw_core/box_site.yaml bbbb\n"
    run = _run(tmp_path, [], before, after)
    assert verdict.main(run) == 1
    assert "unrecorded deviation env:TB_MEM_ADAPTER" in (run / "verdict").read_text(encoding="utf-8")
    run = _run(tmp_path / "b", ["t,1,DEVIATION,P02-cap: TB_MEM_ADAPTER=12g,APPLIED,0,"], before, after)
    assert verdict.main(run) == 0


def test_no_install_no_green(tmp_path: Path) -> None:
    run = _run(tmp_path, ["t,2,INSTALL,one-command install; the questions answered,FAIL,30,rc=1"])
    assert verdict.main(run) == 1
