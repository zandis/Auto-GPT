"""The estimate of a hospital part, from the measured parts (OD-10; G1 bug A4, the batch-3 re-base of 2026-11-13).

G1 bug A4: ``estimate()`` once counted only the screening (2.14 h at 50,000 patients) and the cap stopped an ``--only``
run mid-part. It then scaled G1's 17,960 s at one call in flight by G-3's 5,000-patient gain: 3.14 h per hospital part
at 16 in flight, about 3.6x the part run 20261113T085509Z-c25cea6b measured (2,986 s ja, 2,991 s zh-TW). The estimate
now comes from the measured parts themselves (``HOSPITAL_MEASURED``): non-LLM time, the main SCREEN's calls and the
other calls, each scaled with the patients; the cap keeps its 1.3 margin and its floor."""

from __future__ import annotations

import math

import pytest

from tools import complete_run as cr

RUN_50K, RUN_CURVE = "20261113T085509Z-c25cea6b", "20261113T044219Z-2b9eec74"


def _row(e: dict[str, object], tag: str = "hospital-ja") -> dict[str, object]:
    rows = e["rows"]
    assert isinstance(rows, list)
    return dict(next(r for r in rows if r["tags"] == [tag]))


def test_the_source_data_is_the_measured_runs() -> None:
    big = [r for r in cr.HOSPITAL_MEASURED if r["patients"] == 50000]
    assert {(r["run"], r["lang"], r["n"], r["wall"], r["screen_calls"], r["screen_cps"]) for r in big} == {
        (RUN_50K, "ja", 16, 2986.1, 3226, 4.447), (RUN_50K, "zh-TW", 16, 2990.7, 3217, 4.558)}  # fmt: skip
    small = {(r["lang"], r["n"]): (r["wall"], r["screen_cps"]) for r in cr.HOSPITAL_MEASURED if r["patients"] == 5000}
    assert small[("ja", 1)] == (1685.5, 0.385) and small[("ja", 4)] == (734.1, 1.435)
    assert small[("ja", 16)] == (501.5, 4.391) and {r["run"] for r in cr.HOSPITAL_MEASURED} == {RUN_50K, RUN_CURVE}


def test_a_50000_patient_part_at_16_in_flight_is_the_measured_part() -> None:
    """The defect: 3.14 h estimated, 0.83 h measured. At a measured point the model gives the measurement back."""
    for lang, wall in (("ja", 2986.1), ("zh-TW", 2990.7)):
        s = cr.hospital_split(50000, 16, lang)
        assert s["seconds"] == pytest.approx(wall, abs=1) and s["measured"] and s["runs"] == [RUN_50K]
        assert s["non_llm"] + s["main"] + s["other"] == pytest.approx(s["seconds"])
        assert s["main"] == pytest.approx({"ja": 3226 / 4.447, "zh-TW": 3217 / 4.558}[lang])
    e = cr.restrict(cr.estimate(50000, llm_concurrency=(16,)), ["hospital-ja", "hospital-zh-TW"])
    assert _row(e)["hours"] == 0.83 and _row(e, "hospital-zh-TW")["hours"] == 0.83  # was 3.14
    assert _row(e)["model_items"] == 6568 and _row(e)["source"] == [RUN_50K]
    assert e["hours"] == pytest.approx(0.5 + 2 * 0.83, abs=0.02) and e["cap_hours"] == 3  # 2.16 h x 1.3


def test_each_time_scales_with_the_patients() -> None:
    a, b = cr.hospital_split(50000, 16, "ja"), cr.hospital_split(100000, 16, "ja")
    for k in ("non_llm", "main", "other", "seconds"):
        assert b[k] == pytest.approx(2 * a[k])  # beyond the largest measured size: proportional
    mid = cr.hospital_split(25000, 16, "ja")  # between the two sizes: each time interpolated on its own
    lo = cr.hospital_split(5000, 16, "ja")
    for k in ("non_llm", "main", "other"):
        assert mid[k] == pytest.approx(lo[k] + (25000 - 5000) / 45000 * (a[k] - lo[k]))
    assert mid["runs"] == [RUN_CURVE, RUN_50K]


def test_an_unmeasured_setting_takes_the_curves_gain_and_names_its_run() -> None:
    s1, s16 = cr.hospital_split(50000, 1, "ja"), cr.hospital_split(50000, 16, "ja")
    assert not s1["measured"] and s1["runs"] == [RUN_CURVE, RUN_50K]
    assert s1["non_llm"] == s16["non_llm"]  # the non-LLM time does not change with the calls in flight
    assert s1["main"] == pytest.approx(s16["main"] * 4.391 / 0.385, rel=1e-3)  # the curve's main SCREEN gain (ja)
    assert cr.HOSPITAL_PART_SECONDS == pytest.approx(cr.hospital_seconds(50000, 1), abs=0.1)
    # above the largest measured N: held, never extrapolated
    assert cr.hospital_seconds(50000, 48, lang="ja") == pytest.approx(s16["seconds"])


def test_a_small_hospital_never_drops_below_the_model_time() -> None:
    small = cr.estimate(500)  # the rehearsal's size: the canary and the stub time are most of it
    floor = cr.S3_SHARE * 500 * small["seconds_per_note_patient"] + cr.CANARY_SECONDS + cr.STUB_SECONDS["hospital"]
    assert _row(small)["seconds"] >= floor


def test_the_cap_covers_the_part_with_no_gain_it_did_not_measure() -> None:
    e = cr.restrict(cr.estimate(50000, llm_concurrency=(4,)), ["hospital-ja"])  # 4 not measured at 50,000
    assert _row(e)["floor_seconds"] == pytest.approx(cr.hospital_seconds(50000, 1, lang="ja"))
    assert e["cap_hours"] == math.ceil(0.5 + cr.hospital_seconds(50000, 1, lang="ja") / 3600)
    e = cr.restrict(cr.estimate(50000, llm_concurrency=(1,)), ["hospital-ja"])
    start = (cr.BOOT_HOURS + cr.SETUP_HOURS) * 3600
    assert e["cap_hours"] * 3600 >= 1.3 * (start + cr.hospital_seconds(50000, 1, lang="ja"))
    assert e["cap_hours"] == 6  # 3.98 h x 1.3


def test_the_estimate_names_the_runs_its_figures_come_from() -> None:
    text = cr.print_estimate(cr.restrict(cr.estimate(50000, llm_concurrency=(16,)), ["hospital-ja"]))
    assert f"hospital parts: from the measured runs {RUN_50K}" in text
    assert f"{RUN_50K} hospital-ja 50,000 patients, 16 in flight: wall 2,986 s" in text
    assert "main SCREEN 3,226 calls at 4.447/s" in text and "hospital-ja: non-LLM 1,292 s" in text
    assert "hospital parts" not in cr.print_estimate(cr.restrict(cr.estimate(5000), ["scenario-gateway"]))
