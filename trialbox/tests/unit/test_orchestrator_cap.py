"""H23b-01 (D-1005): the orchestrator's memory cap sized from the hospital's patients.

The size test (H-23b, D-1137) showed that SCREEN of the whole hospital needs 4.37 GiB at 50,000 patients and 8.22 GiB
at 100,000. No installer step raised the orchestrator's 4 GiB cap (``TB_MEM_ORCH``), so a box as installed killed
SCREEN from about 45,000 patients. Now:

* ``memcaps --from-ladder`` writes ``deploy/measured/orchestrator_memory.json`` from the size ladder's results: a line
  on or above every peak, with a patient count whose stage was killed at its cap left out;
* ``memcaps --write`` (``deploy/install.sh``) writes ``TB_MEM_ORCH`` once the need passes the compose default, keeps a
  value set by hand, and removes one it wrote that is no longer needed (the two-device workstation keeps its 3 GiB);
* ``trialbox doctor`` (``memory_caps``) fails when the orchestrator's cap is below the need.
Synthetic counts only.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from tools.trialbox import doctor, memcaps

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
GIB = 2**30


def _row(stage: str, n: int, peak_gib: float, ok: bool = True, cap_gib: float = 4.0) -> dict[str, Any]:
    return {"stage": stage, "patients": n, "service": "orchestrator", "peak": int(peak_gib * GIB),
            "cap": int(cap_gib * GIB), "ok": ok, "lifted": cap_gib > 4}  # fmt: skip


def _ladder(tmp: Path, rows: list[dict[str, Any]], name: str = "r.json") -> Path:
    p = tmp / name
    p.write_text(json.dumps({"commit": "synthetic", "written": "2026-11-18T00:00:00+00:00", "table": rows}))
    return p


def _orch(tmp: Path, fixed_mb: float = 500.0, per_patient_kb: float = 80.0) -> Path:
    p = tmp / "orchestrator_memory.json"
    doc = {"format": memcaps.ORCH_FORMAT, "services": {"orchestrator": {"fixed_mb": fixed_mb,
                                                                        "per_patient_kb": per_patient_kb}}}  # fmt: skip
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------------ the record
def test_the_line_lies_on_or_above_every_peak_and_a_killed_count_is_left_out(tmp_path: Path) -> None:
    rows = [_row("SCREEN x1", 10_000, 1.0), _row("FEAS x1", 10_000, 0.5), _row("SCREEN x1", 40_000, 3.5),
            _row("SCREEN x1", 80_000, 6.0, cap_gib=10), _row("FEAS x1", 200_000, 0.6),
            _row("SCREEN x1", 200_000, 4.0, ok=False)]  # fmt: skip
    doc = memcaps.from_ladder([_ladder(tmp_path, rows)])
    part = doc["services"]["orchestrator"]
    assert set(part["peak_mb"]) == {"10000", "40000", "80000"}  # 200,000: SCREEN was killed, FEAS alone says nothing
    assert doc["left_out"] == ["200000 patients: SCREEN x1 killed at the cap"]
    for n, peak in part["peak_mb"].items():
        assert part["fixed_mb"] + part["per_patient_kb"] * int(n) / 1024 >= peak
    assert part["per_patient_kb"] > 0 and doc["commits"] == ["synthetic"]


def test_two_counts_are_needed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="two patient counts"):
        memcaps.from_ladder([_ladder(tmp_path, [_row("SCREEN x1", 10_000, 1.0)])])


def test_a_combined_record_reads_each_part_s_table(tmp_path: Path) -> None:
    p = tmp_path / "combined.json"
    p.write_text(json.dumps({"commit": "a", "table": [_row("SCREEN x1", 50_000, 4.0, ok=False)],
                             "later": {"commit": "b", "table": [_row("SCREEN x1", 50_000, 4.4, cap_gib=10),
                                                                _row("SCREEN x1", 20_000, 2.0)]}}))  # fmt: skip
    doc = memcaps.from_ladder([p])
    assert doc["services"]["orchestrator"]["peak_mb"]["50000"] == pytest.approx(4.4 * 1024, abs=0.1)
    assert doc["commits"] == ["a", "b"]


def test_the_shipped_record_is_the_size_test_s_and_needs_more_than_4_gib_from_about_45000() -> None:
    shipped = json.loads(memcaps.ORCH_RECORD.read_text(encoding="utf-8"))
    again = memcaps.from_ladder([ROOT / "docs" / "plan" / "measurements" / "size-test-2026-11-17.json"])
    assert shipped == again  # written by the tool from the size test, never by hand
    orch, rec = memcaps.load_orch_record(), memcaps.load_record()
    assert memcaps.compose_default("TB_MEM_ORCH") == "4g"
    assert memcaps.need_mb(40_000, rec, {}, orch=orch)["orchestrator"] == 4096
    at = {n: memcaps.need_mb(n, rec, {}, orch=orch)["orchestrator"] for n in (50_000, 100_000)}
    assert at[50_000] >= 4.37 * 1024 and at[100_000] >= 8.22 * 1024  # H-23b's SCREEN peaks (H23b-01)


# ------------------------------------------------------------------------------------------------ the installer
def _env(tmp: Path, text: str) -> Path:
    p = tmp / ".env"
    p.write_text(text, encoding="utf-8")
    return p


def test_install_writes_the_cap_above_the_default_and_removes_its_own_when_no_longer_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(memcaps, "ORCH_RECORD", _orch(tmp_path))
    env = _env(tmp_path, "TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=100000\n")
    assert memcaps.main(["--env-file", str(env), "--write"]) == 0
    got = memcaps._parse_env(env.read_text(encoding="utf-8"))
    assert got["TB_MEM_ORCH"] == f"{math.ceil(500 + 80 * 100_000 / 1024)}m"
    # the site was smaller than said: the default fits, and the value this tool wrote goes
    env.write_text(env.read_text(encoding="utf-8").replace("100000", "20000"), encoding="utf-8")
    memcaps.main(["--env-file", str(env), "--write"])
    text = env.read_text(encoding="utf-8")
    assert "TB_MEM_ORCH" not in memcaps._parse_env(text) and "TB_MEM_ORCH" not in text.split(memcaps.MARKER)[1]


def test_a_small_hospital_keeps_the_shipped_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The two-device workstation's overlay gives the orchestrator 3 GiB (``${TB_MEM_ORCH:-3g}``): nothing is written
    for a hospital the default fits, so that stays."""
    monkeypatch.setattr(memcaps, "ORCH_RECORD", _orch(tmp_path))
    env = _env(tmp_path, "TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=20000\n")
    memcaps.main(["--env-file", str(env), "--write"])
    assert "TB_MEM_ORCH" not in memcaps._parse_env(env.read_text(encoding="utf-8"))
    overlay = (ROOT / "deploy" / "two-device" / "docker-compose.workstation.yml").read_text(encoding="utf-8")
    assert "${TB_MEM_ORCH:-3g}" in overlay


def test_a_cap_set_by_hand_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memcaps, "ORCH_RECORD", _orch(tmp_path))
    for n in ("100000", "20000"):
        env = _env(tmp_path, f"TB_ENV=PRODUCTION\nTB_SITE_PATIENTS={n}\nTB_MEM_ORCH=24g\n")
        memcaps.main(["--env-file", str(env), "--write"])
        assert memcaps._parse_env(env.read_text(encoding="utf-8"))["TB_MEM_ORCH"] == "24g"


def test_the_installer_names_the_cap() -> None:
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "python3 -m tools.trialbox.memcaps --env-file deploy/.env" in install
    assert "TB_MEM_ADAPTER, TB_MEM_LAKE and TB_MEM_ORCH in deploy/.env" in install
    assert "orchestrator_memory.json" in install


# ------------------------------------------------------------------------------------------------ the doctor
def test_doctor_fails_an_orchestrator_cap_below_the_need(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "measured").mkdir(parents=True)
    for f in ("ingest_memory.json", "orchestrator_memory.json"):
        (deploy / "measured" / f).write_text((ROOT / "deploy" / "measured" / f).read_text(encoding="utf-8"))
    (deploy / "docker-compose.yml").write_text((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
    env = {"TB_ENV": "PRODUCTION", "TB_SITE_PATIENTS": "100000"}
    low = doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=deploy))
    assert low.status == "FAIL" and "TB_MEM_ORCH 4096 MB <" in low.detail and "SCREEN" in low.detail
    env["TB_MEM_ORCH"] = "9g"
    ok = doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=deploy))
    assert ok.status == "PASS" and "TB_MEM_ORCH 9216 MB" in ok.detail
    # a box from before this record: the adapter and the lake are still checked
    (deploy / "measured" / "orchestrator_memory.json").unlink()
    old = doctor.check_memory_caps(doctor.DoctorInputs(env={**env, "TB_MEM_ORCH": "1g"}, deploy=deploy))
    assert old.status == "PASS" and "TB_MEM_ORCH" not in old.detail
