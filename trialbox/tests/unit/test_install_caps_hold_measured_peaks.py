"""E2E P-02: the 50,000-patient full night was OOM-killed under the cap the installer gave the adapter. The box plan
(``tools.box.plan.memory_caps``) shrank every cap by one factor to fit a 96 GB box beside the model servers, so the
adapter got 3,520 MiB; the night peaked at 4,003 MiB (passed at 12 GiB). And ``memcaps`` sized the adapter from a
measurement of its streamed write alone, so a 100,000-patient site kept the 6 GiB default under a 6.61 GiB peak.
Each cap of a service with a measured peak now holds 1.5 times that peak (the cap-from-peak rule)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.box import plan as bp
from tools.trialbox import memcaps

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
FILES = ("docker-compose.yml", "docker-compose.identity.yml", "docker-compose.rtxpro6000.yml")


def _mib(v: str) -> int:
    return int(v[:-1]) if v.endswith("m") else int(float(v[:-1]) * 1024)


@pytest.mark.parametrize("ram", [94.0, 96.0])
def test_the_walks_box_gets_caps_that_hold_the_measured_50k_peaks(ram: float) -> None:
    caps, notes = bp.memory_caps(ram, "rtxpro6000", ROOT / "deploy")
    assert _mib(caps["TB_MEM_ADAPTER"]) >= 1.5 * 4003, caps["TB_MEM_ADAPTER"]  # was 3,520 MiB: killed at 4,003
    assert _mib(caps["TB_MEM_ORCH"]) >= 1.5 * 3973, caps["TB_MEM_ORCH"]
    var, fixed = bp.compose_caps([ROOT / "deploy" / f for f in FILES])
    assert sum(_mib(v) for v in caps.values()) / 1024 <= ram - max(4, ram / 10) - fixed + 0.01  # still fits
    for k, v in caps.items():  # the others gave the memory back, none under the planner's floor
        assert _mib(v) / 1024 >= bp.MIN_SERVICE_SHARE * var[k] - 0.01, (k, v)
    assert len(notes) == 1, notes


def test_a_machine_too_small_for_the_peaks_is_told_so() -> None:
    caps, notes = bp.memory_caps(30, "stub", ROOT / "deploy")
    assert _mib(caps["TB_MEM_ADAPTER"]) < 1.5 * 4003  # the shared rule as before: nothing else is starved for it
    assert any("TB_MEM_ADAPTER" in n and "50,000-patient" in n for n in notes), notes


@pytest.mark.parametrize(("patients", "peak"), [(50_000, 4003), (100_000, 6769)])
def test_memcaps_sizes_the_adapter_from_its_measured_nights(patients: int, peak: int) -> None:
    nights = memcaps.load_nights(memcaps.RECORD.parent / memcaps.NIGHTS_NAME)
    need = memcaps.need_mb(patients, memcaps.load_record(), {}, nights=nights)
    assert need["adapter"] >= 1.5 * peak, need  # 100k: was the 6 GiB default under a 6.61 GiB night


def test_doctor_fails_the_default_adapter_cap_for_a_100k_hospital() -> None:
    from tools.trialbox import doctor

    env = {"TB_ENV": "PRODUCTION", "TB_SITE_PATIENTS": "100000", "TB_MEM_ADAPTER": "6g"}
    c = doctor.check_memory_caps(doctor.DoctorInputs(env=env, deploy=ROOT / "deploy"))
    assert c.status == "FAIL" and "TB_MEM_ADAPTER 6144 MB <" in c.detail, c.detail
