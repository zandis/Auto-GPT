"""E2E P-02: the 50,000-patient full night was OOM-killed under the cap the installer gave the adapter. The box plan
(``tools.box.plan.memory_caps``) shrank every cap by one factor to fit a 96 GB box beside the model servers, so the
adapter got 3,520 MiB; the night peaked at 4,003 MiB (passed at 12 GiB). The installer never used the site's size, and
``memcaps`` sized the adapter from a measurement of its streamed write alone, so a 100,000-patient site kept the 6 GiB
default under a 6.61 GiB night. The caps now come from one measured-peak table keyed by the hospital's size
(``deploy/measured/site_peaks.json``): each cap of a measured service holds 1.5 times the peak of the nearest larger
size (the cap-from-peak rule)."""

from __future__ import annotations

import dataclasses
import math
import shutil
from pathlib import Path

import pytest

from tools.box import plan as bp
from tools.trialbox import memcaps

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
FILES = ("docker-compose.yml", "docker-compose.identity.yml", "docker-compose.rtxpro6000.yml")
PEAKS = memcaps.load_peaks(ROOT / "deploy" / "measured" / memcaps.PEAKS_NAME)


def _mib(v: str) -> int:
    return int(v[:-1]) if v.endswith("m") else int(float(v[:-1]) * 1024)


def _fits(caps: dict[str, str], ram: float) -> None:
    var, fixed = bp.compose_caps([ROOT / "deploy" / f for f in FILES])
    assert sum(_mib(v) for v in caps.values()) / 1024 <= ram - max(4, ram / 10) - fixed + 0.01  # still fits
    for k, v in caps.items():  # the others gave the memory back, none under the planner's floor
        assert _mib(v) / 1024 >= bp.MIN_SERVICE_SHARE * var[k] - 0.01, (k, v)


def test_the_table_holds_the_measured_peaks() -> None:
    assert [p for p, _ in PEAKS] == [50_000, 100_000]
    assert PEAKS[0][1]["TB_MEM_ADAPTER"] == 4003 and PEAKS[1][1]["TB_MEM_ADAPTER"] == 6769  # the walk; the 100k rerun
    assert PEAKS[1][1]["TB_MEM_ORCH"] == 12053  # 11.77 GiB over the 100k rerun's eight SCREENs


@pytest.mark.parametrize("ram", [94.0, 96.0])
def test_the_walks_box_gets_caps_that_hold_the_measured_50k_peaks(ram: float) -> None:
    caps, notes = bp.memory_caps(ram, "rtxpro6000", ROOT / "deploy")  # no size given: the smallest class
    assert _mib(caps["TB_MEM_ADAPTER"]) >= 1.5 * 4003, caps["TB_MEM_ADAPTER"]  # was 3,520 MiB: killed at 4,003
    assert _mib(caps["TB_MEM_ORCH"]) >= 1.5 * 3973, caps["TB_MEM_ORCH"]
    _fits(caps, ram)
    assert len(notes) == 1, notes


def test_a_100k_hospital_is_sized_from_the_100k_peaks_or_told_the_machine_is_too_small() -> None:
    caps, _ = bp.memory_caps(128, "rtxpro6000", ROOT / "deploy", 100_000)
    assert _mib(caps["TB_MEM_ADAPTER"]) >= 1.5 * 6769 and _mib(caps["TB_MEM_ORCH"]) >= 1.5 * 12053, caps
    _fits(caps, 128)
    _, said = bp.memory_caps(96, "rtxpro6000", ROOT / "deploy", 100_000)
    assert any("TB_MEM_ORCH" in n and "100,000 patients" in n for n in said), said  # not silently under its peak
    nearest, _ = bp.memory_caps(128, "rtxpro6000", ROOT / "deploy", 60_000)  # the nearest larger size: 100k
    assert nearest["TB_MEM_ORCH"] == caps["TB_MEM_ORCH"]


def test_a_machine_too_small_for_the_peaks_is_told_so() -> None:
    caps, notes = bp.memory_caps(30, "stub", ROOT / "deploy")
    assert _mib(caps["TB_MEM_ADAPTER"]) < 1.5 * 4003  # the shared rule as before: nothing else is starved for it
    assert any("TB_MEM_ADAPTER" in n and "50,000 patients" in n for n in notes), notes


def test_the_plan_reads_the_sites_size_and_hands_it_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SITE_PATIENTS", raising=False)
    assert bp.site_patients(tmp_path) == 0
    (tmp_path / ".env").write_text("TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=100000\n", encoding="utf-8")
    assert bp.site_patients(tmp_path) == 100_000
    (tmp_path / ".env").write_text("TB_SITE_PATIENTS=lots\n", encoding="utf-8")
    with pytest.raises(bp.PlanError, match="TB_SITE_PATIENTS"):
        bp.site_patients(tmp_path)


def test_peaks_follow_the_nearest_larger_size_and_extrapolate_above() -> None:
    peaks = [(50_000, {"A": 4000.0, "C": 1300.0}), (100_000, {"A": 7000.0})]
    assert memcaps.peak_mib(peaks, "A", 10_000) == 4000 and memcaps.peak_mib(peaks, "A", 50_001) == 7000
    assert memcaps.peak_mib(peaks, "A", 150_000) == 10_000  # the line through the two sizes
    assert memcaps.peak_mib(peaks, "C", 100_000) == 1300  # not measured at 100k: never under the smaller size's
    assert memcaps.peak_mib(peaks, "B", 50_000) == 0


@pytest.mark.parametrize(("patients", "peak"), [(50_000, 4003), (100_000, 6769)])
def test_memcaps_sizes_the_adapter_from_the_measured_nights(patients: int, peak: int) -> None:
    need = memcaps.need_mb(patients, memcaps.load_record(), {}, peaks=PEAKS)
    assert need["adapter"] >= 1.5 * peak, need  # 100k: was the 6 GiB default under a 6.61 GiB night


def test_doctor_fails_the_default_adapter_cap_for_a_100k_hospital() -> None:
    from tools.trialbox import doctor

    env = {"TB_ENV": "PRODUCTION", "TB_SITE_PATIENTS": "100000", "TB_MEM_ADAPTER": "6g"}
    c = doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=ROOT / "deploy"))
    assert c.status == "FAIL" and "TB_MEM_ADAPTER 6144 MB <" in c.detail, c.detail


# ------------------------------------------------------------------------------------------------ round 2 (review)
def test_doctor_fails_an_undersized_orchestrator_when_the_other_caps_hold() -> None:
    """R1: the orchestrator at 100,000 patients is sized by the ladder line (8.4 GiB), under 1.5 x its 11.77 GiB night."""
    from tools.trialbox import doctor

    floor = math.ceil(memcaps.HEADROOM * memcaps.peak_mib(PEAKS, "TB_MEM_ORCH", 100_000))
    env = {"TB_ENV": "PRODUCTION", "TB_SITE_PATIENTS": "100000", "TB_MEM_ADAPTER": "11g", "TB_MEM_LAKE": "9g"}
    ok = doctor.check_memory_caps(doctor.DoctorInputs(env={**env, "TB_MEM_ORCH": f"{floor}m"}, deploy=ROOT / "deploy"))
    assert ok.status == "PASS", ok.detail
    c = doctor.check_memory_caps(doctor.DoctorInputs(env={**env, "TB_MEM_ORCH": "12g"}, deploy=ROOT / "deploy"))
    assert c.status == "FAIL" and f"TB_MEM_ORCH 12288 MB < {floor} MB" in c.detail, c.detail


def test_memcaps_needs_hold_each_measured_service_s_floor() -> None:
    orch = memcaps.load_orch_record(ROOT / "deploy" / "measured" / "orchestrator_memory.json")
    need = memcaps.need_mb(100_000, memcaps.load_record(), {}, orch=orch, peaks=PEAKS)
    for svc, var in {**memcaps.CAPS, memcaps.ORCH: memcaps.ORCH_VAR}.items():
        assert need[svc] >= math.ceil(memcaps.HEADROOM * memcaps.peak_mib(PEAKS, var, 100_000)), (svc, need)


def test_a_measured_surplus_is_the_donor_when_the_other_service_is_short() -> None:
    """R2: A is short of its floor; L holds a surplus; X cannot give (its half share is above what it has left)."""
    caps = {"A": 10.0, "L": 8.0, "X": 5.0}
    defaults = {"A": 6.0, "L": 6.0, "X": 20.0}
    got, said = bp.measured_floors(caps, defaults, {"A": 12.0, "L": 2.0}, 100_000, [])
    assert got == {"A": 12.0, "L": 6.0, "X": 5.0} and said == [], (got, said)
    none, said = bp.measured_floors(caps, defaults, {"A": 20.0, "L": 2.0}, 100_000, [])  # all spare is 5: not enough
    assert none == caps and len(said) == 1


def test_the_extrapolation_never_falls_below_the_largest_measured_peak() -> None:
    """R3: peaks 7,000 then 4,000 MiB: 100,001 patients must not get less than 100,000 does."""
    peaks = [(50_000, {"A": 7000.0}), (100_000, {"A": 4000.0})]
    assert memcaps.peak_mib(peaks, "A", 100_000) == 7000
    assert memcaps.peak_mib(peaks, "A", 100_001) == 7000 and memcaps.peak_mib(peaks, "A", 200_000) == 7000


def test_the_plan_hands_the_sites_size_to_the_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4: a 100,000-patient ``.env`` through ``bp.plan``: the caps are the 100k class's, and the size is emitted."""
    from tb_common.box_answers import parse

    from tests.unit.test_site_country import HW, OWNER

    a, problems = parse(OWNER)
    assert a is not None, problems
    monkeypatch.delenv("TB_SITE_PATIENTS", raising=False)
    deploy = tmp_path / "deploy"
    shutil.copytree(ROOT / "deploy", deploy, ignore=shutil.ignore_patterns(".env"))
    hw = dataclasses.replace(HW, ram_gib=96.0)  # room for the 100k class's caps, not by the shared rule alone
    base = bp.plan(a, hw, deploy).env_extra
    assert "TB_SITE_PATIENTS" not in base and _mib(base["TB_MEM_ORCH"]) < 1.5 * 12053  # the smallest class
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\nTB_SITE_PATIENTS=100000\n", encoding="utf-8")
    env = bp.plan(a, hw, deploy).env_extra
    assert env["TB_SITE_PATIENTS"] == "100000"
    assert _mib(env["TB_MEM_ADAPTER"]) >= 1.5 * 6769 and _mib(env["TB_MEM_ORCH"]) >= 1.5 * 12053, env
