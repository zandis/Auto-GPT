"""G1 bug A4: the estimate of a hospital part was far too low, which made the cloud hard cap unsafe.

``estimate()`` counted only the screening (920 note patients x 6.3 s + the canary + the stub time): 2.14 h at 50,000
patients. G1 measured hospital-ja at 17,960 s (5.0 h). The cap (estimate x 1.3) of an ``--only hospital-ja`` run
was then 4 h, and Compute Engine would have stopped the VM in the middle of the part. OD-10: the limit comes from
the measurement, scaled with the patient count."""

from __future__ import annotations

from tools import complete_run as cr


def _hospital_seconds(e: dict[str, object]) -> float:
    rows = e["rows"]
    assert isinstance(rows, list)
    return float(next(r["seconds"] for r in rows if r["tags"] == ["hospital-ja"]))


def test_a_hospital_part_is_estimated_from_the_g1_measurement() -> None:
    assert cr.HOSPITAL_PART_SECONDS == 17960.0 and cr.HOSPITAL_PART_PATIENTS == 50000
    assert _hospital_seconds(cr.estimate(50000)) == 17960.0
    assert _hospital_seconds(cr.estimate(100000)) == 2 * 17960.0  # scaled with the patients it reads
    assert abs(_hospital_seconds(cr.estimate(25000)) - 8980.0) < 1


def test_a_small_hospital_never_drops_below_the_model_time() -> None:
    small = cr.estimate(500)  # the rehearsal's size: the canary and the stub time are most of it
    floor = cr.S3_SHARE * 500 * small["seconds_per_note_patient"] + cr.CANARY_SECONDS + cr.STUB_SECONDS["hospital"]
    assert _hospital_seconds(small) >= floor


def test_the_cap_of_a_hospital_only_run_covers_the_measured_part() -> None:
    e = cr.restrict(cr.estimate(50000), ["hospital-ja"])
    start = (cr.BOOT_HOURS + cr.SETUP_HOURS) * 3600
    assert e["cap_hours"] * 3600 >= 1.3 * (start + 17960.0)
    assert e["cap_hours"] == 8  # was 4: the VM would have been stopped 3.5 h into a 5 h part


def test_the_cap_of_the_full_plan_covers_both_measured_hospital_parts() -> None:
    e = cr.estimate(50000, parts=("g1", "embed", "profile"))
    assert e["hours"] * 3600 >= 2 * 17960.0
    assert e["cap_hours"] == 20  # was 13
    shard = cr.shard_plan(e, 1)["shards"][0]
    assert shard["cap_hours"] == e["cap_hours"]
