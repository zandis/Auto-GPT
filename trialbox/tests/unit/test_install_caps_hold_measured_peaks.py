"""E2E P-02: the 50,000-patient full night was OOM-killed under the cap the installer gave the adapter. The box plan
(``tools.box.plan.memory_caps``) shrank every cap by one factor to fit a 96 GB box beside the model servers, so the
adapter got 3,520 MiB; the night peaked at 4,003 MiB (passed at 12 GiB). The installer never used the site's size, and
``memcaps`` sized the adapter from a measurement of its streamed write alone, so a 100,000-patient site kept the 6 GiB
default under a 6.61 GiB night. The caps now come from one measured-peak table keyed by the hospital's size
(``deploy/measured/site_peaks.json``): each cap of a measured service holds 1.5 times the peak of the nearest larger
size (the cap-from-peak rule)."""

from __future__ import annotations

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
