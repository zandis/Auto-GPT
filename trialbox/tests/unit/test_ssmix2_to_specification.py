"""Plan 10 cards 10B-2 to 10B-5 (review 12's faults F1 to F4, criterion F1): the SS-MIX2 reader read against a
storage written from the specification (``tests/ssmix2_spec_kit.py``), not against TrialBox's own exporter. Each
test failed on the reader before its card and passes after it. All data is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_spec_kit as kit

EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}


@pytest.fixture
def storage(tmp_path: Path) -> kit.Storage:
    return kit.build(tmp_path)


def _source(st: kit.Storage, **kw: object) -> Ssmix2Source:
    return Ssmix2Source(st.root, licensed=EMPTY, **kw)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------ F1 (10B-2)
def test_f1_three_visits_on_three_days_read_as_three_with_all9_and_with_a_per_day_number(
    storage: kit.Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 12's probe M4: three ADT-12 files on three days under "ALL9" (patient 1) and under "1" (patient 2)
    gave one visit each under the old default key; the specification's key (D-1000) gives three."""
    monkeypatch.delenv("TB_SSMIX2_ORDER_NUMBERS", raising=False)
    rows = list(_source(storage).rows("encounter", "encounter", None, None))
    for patient, visits in kit.VISITS.items():
        got = sorted(r["enc_no"] for r in rows if r["mrn"] == patient and r["enc_type"] == "OPD")
        assert got == [v for _day, v in visits], patient


def test_f1_each_admission_is_kept_and_discharged(storage: kit.Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """Card 12-1's proof: two admissions and two discharges, each under the per-day sequence "1"; the first
    admission is no longer lost and none stays "in-progress"."""
    monkeypatch.delenv("TB_SSMIX2_ORDER_NUMBERS", raising=False)
    src = _source(storage)
    rows = {r["enc_no"]: r for r in src.rows("encounter", "encounter", None, None) if r["enc_type"] == "IPD"}
    assert sorted(rows) == ["V2101", "V2102"]
    assert {k: (r["enc_status"], r["end_datetime"]) for k, r in rows.items()} == {
        "V2101": ("finished", "2026-09-05 11:00:00"),
        "V2102": ("finished", "2026-09-25 11:00:00"),
    }
    assert src.stats["ADT-52:discharge"] == 2


def test_f1_a_site_that_declares_unique_still_keeps_all9_and_adt_records_by_day(storage: kit.Storage) -> None:
    """``unique`` stays as a site's declared exception (D-1000); "ALL9" is not an order number and an ADT number is
    a per-day sequence, so neither ever collapses days."""
    rows = list(_source(storage, order_key="unique").rows("encounter", "encounter", None, None))
    assert len(rows) == 8  # six outpatient visits and two admissions


def test_f1_the_default_is_the_specifications_key() -> None:
    from adapter.sources.ssmix2 import source
    from tb_common.config import DECLARED

    assert source.DEFAULT_ORDER_KEY == "per_day"
    assert DECLARED["TB_SSMIX2_ORDER_NUMBERS"].default == "per_day"


# ------------------------------------------------------------------------------------------------ F2 (10B-3)
def _diagnoses(st: kit.Storage) -> tuple[dict[str, dict[str, object]], list[dict[str, object]], Ssmix2Source]:
    src = _source(st)
    rows = {str(r["diag_no"]): r for r in src.rows("diagnosis", "diagnosis", None, None)}
    dead = list(src.deleted_rows("diagnosis", "diagnosis", None, None))
    return rows, dead, src


def test_f2_the_specifications_sample_reads_icd10_onset_current_and_main(storage: kit.Storage) -> None:
    """Card 12-2's proof: ICD-10 K29.7 from PRB-10, onset 2011-08-31 (PRB-16), diagnosed 2011-09-10 (PRB-7), no
    outcome so not resolved, 主診断 (PRB-18)."""
    rows, _, src = _diagnoses(storage)
    g = rows[kit.DX["gastritis"]]
    assert (g["icd10"], g["diag_date"], g["diagnosed_date"], g["status"], g["main_diagnosis"]) == (
        "K29.7",
        "2011-08-31",
        "2011-09-10",
        "A",
        "Y",
    )
    assert g["byomei_code"] == "99990001" and g["suspected"] == ""
    assert not [k for k in src.missed if k.startswith("diagnosis:")]  # every ICD-10 came from PRB-10


def test_f2_a_deleted_diagnosis_is_no_row_and_a_tombstone(storage: kit.Storage) -> None:
    rows, dead, src = _diagnoses(storage)
    assert kit.DX["diabetes"] not in rows
    assert [(d["diag_no"], d["mrn"]) for d in dead] == [(kit.DX["diabetes"], kit.P1)]
    assert src.stats["PPR-01:deleted diagnosis"] == 1


def test_f2_every_outcome_is_read_none_reads_as_active_by_mistake(storage: kit.Storage) -> None:
    """Cured (F, HL7 0241) is resolved with its end and outcome days; remission (M, JHSD0006) is remission; died (D)
    is inactive; follow-up stopped (I, JHSD0006) says neither and is U, which the mapping leaves unconfirmed."""
    rows, _, _ = _diagnoses(storage)
    got = {k: (rows[v]["status"], rows[v]["outcome"]) for k, v in kit.DX.items() if v in rows}
    assert got == {
        "gastritis": ("A", ""),
        "uri": ("R", "F"),
        "ra": ("M", "M"),
        "pneumonia": ("A", ""),
        "infarct": ("I", "D"),
        "stopped": ("U", "I"),
    }
    uri = rows[kit.DX["uri"]]
    assert (uri["end_date"], uri["outcome_date"], uri["main_diagnosis"]) == ("2026-03-01", "2026-03-01", "N")


def test_f2_a_suspicion_written_only_as_a_modifier_is_suspected(storage: kit.Storage) -> None:
    rows, _, _ = _diagnoses(storage)
    p = rows[kit.DX["pneumonia"]]
    assert (p["byomei_name"], p["written_name"], p["modifiers"], p["suspected"]) == ("肺炎", "肺炎の疑い", "の疑い", "Y")


def test_f2_the_japan_mapping_gives_each_status_its_fhir_word(storage: kit.Storage) -> None:
    """The reader's rows through ``jp_core/ssmix2_site.yaml``: each outcome its clinical status, U none and
    unconfirmed (D-587), and the end day as the abatement of the cured diagnosis only."""
    from adapter.mapping.engine import Mapper, Mapping

    m = Mapping.load(JP_MAPPING)
    mp = Mapper(m, b"k" * 32, "S")
    spec = next(r for r in m.resources if r.type == "Condition")
    rows, _, _ = _diagnoses(storage)
    out = {}
    for key, no in kit.DX.items():
        if no in rows:
            res = mp.map_row(spec, rows[no])
            assert res is not None, key
            out[key] = res
    words = {k: [c["code"] for c in (r.get("clinicalStatus") or {}).get("coding", [])] for k, r in out.items()}
    assert words == {
        "gastritis": ["active"],
        "uri": ["resolved"],
        "ra": ["remission"],
        "pneumonia": ["active"],
        "infarct": ["inactive"],
        "stopped": [],
    }
    unconfirmed = [c["code"] for c in out["stopped"]["verificationStatus"]["coding"] if c]
    assert "unconfirmed" in unconfirmed
    assert out["uri"]["abatementDateTime"].startswith("2026-03-01")
    assert "abatementDateTime" not in out["gastritis"]


JP_MAPPING = Path(__file__).resolve().parents[2] / "services/adapter/mapping/jp_core/ssmix2_site.yaml"


# ------------------------------------------------------------------------------------------------ F3 (10B-4)
def _medicines(st: kit.Storage, table: bool = True) -> tuple[dict[str, dict[str, object]], Ssmix2Source]:
    usage = st.root.parent / "usage.csv"
    src = _source(st, usage_table=usage if table else st.root.parent / "absent.csv")
    return {str(r["rx_no"]): r for r in src.rows("medication", "medication", None, None)}, src


def test_f3_two_tablets_three_times_a_day_is_six_a_day(storage: kit.Storage) -> None:
    """Card 12-3's proof: "1回2錠 1日3回" gives 6 a day; the one dose is kept as it was written."""
    rows, _ = _medicines(storage)
    r = rows[kit.RX["tid"]]
    assert (r["dose_per_time"], r["doses_per_day"], r["doses_per_day_from"], r["daily_dose"], r["dose_unit"]) == (
        "2",
        "3",
        "usage text",
        "6",
        "TAB",
    )


def test_f3_a_missing_or_unreadable_frequency_leaves_the_daily_dose_unknown(storage: kit.Storage) -> None:
    rows, src = _medicines(storage)
    for key in ("prn", "none"):
        r = rows[kit.RX[key]]
        assert (r["dose_per_time"], r["doses_per_day"], r["daily_dose"]) == ("1", "", ""), key
    assert src.stats["OMP-01:daily dose unknown (no frequency)"] == 2
    assert src.missed["usage:U99"] == 1  # the steward's work list names the usage code nothing reads


def test_f3_the_sites_usage_table_gives_the_doses_a_day_and_without_it_nothing_is_guessed(storage: kit.Storage) -> None:
    rows, _ = _medicines(storage)
    r = rows[kit.RX["coded"]]
    assert (r["usage_code"], r["doses_per_day"], r["doses_per_day_from"], r["daily_dose"]) == ("U02", "2", "usage table", "2")
    rows, _ = _medicines(storage, table=False)
    assert (rows[kit.RX["coded"]]["doses_per_day"], rows[kit.RX["coded"]]["daily_dose"]) == ("", "")


def test_f3_the_yj_code_of_rxe31_resolves_the_atc_of_a_hot9_line(storage: kit.Storage) -> None:
    """Card 12-3's proof: HOT9 in RXE-2 and YJ in RXE-31 resolves ATC; the line's own code stays the source."""
    rows, src = _medicines(storage)
    r = rows[kit.RX["tid"]]
    assert (r["nhi_drug_code"], r["hot_code"], r["source_drug_code"], r["atc"]) == (
        "3943001F1020",
        "999000001",
        "999000001",
        "M04AA01",
    )
    assert all(rows[k]["atc"] for k in rows) and not [k for k in src.missed if k.startswith("medication:")]
    assert src.stats["medication:YJ from RXE-31"] == 4
