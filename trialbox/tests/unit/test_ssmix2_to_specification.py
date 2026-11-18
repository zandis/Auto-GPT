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
    assert (p["byomei_name"], p["written_name"], p["modifiers"], p["suspected"]) == (
        "肺炎",
        "肺炎の疑い",
        "の疑い",
        "Y",
    )


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
    assert (r["usage_code"], r["doses_per_day"], r["doses_per_day_from"], r["daily_dose"]) == (
        "U02",
        "2",
        "usage table",
        "2",
    )
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


# ------------------------------------------------------------------------------------------------ F4 (10B-5)
def test_f4_a_guideline_layout_storage_reads_every_document_typed(storage: kit.Storage) -> None:
    """Review 12's probe M5 (0 of 1 read): content folders under CWE+LOINC data-type folders. Card 12-4's proof:
    the discharge summary and the pathology report read, typed; the local-only folder reads as a document; the
    index file is not taken as text."""
    src = _source(storage)
    notes = {(r["mrn"], r["doc_code"], r["note_type"]): r for r in src.rows("note", "note", None, None)}
    assert sorted(notes) == [
        (kit.P1, "11526-1", "report"),
        (kit.P1, "18842-5", "discharge"),
        (kit.P2, "", "document"),
    ]
    summary = notes[(kit.P1, "18842-5", "discharge")]
    assert "抗菌薬" in summary["text"] and "contents" not in summary["text"]
    assert summary["note_datetime"] == "2026-10-15 00:00:00"
    # a month day (YYYYMM) takes the content folder's 発生日時; a "-" day too
    assert notes[(kit.P1, "11526-1", "report")]["note_datetime"] == "2026-10-20 12:00:00"
    assert notes[(kit.P2, "", "document")]["note_datetime"] == "2026-10-02 09:00:00"
    assert src.stats["document:_contents.xml not read"] == 1


def test_f4_a_content_folder_flagged_0_is_a_tombstone(storage: kit.Storage) -> None:
    src = _source(storage)
    rows = list(src.rows("note", "note", None, None))
    dead = list(src.deleted_rows("note", "note", None, None))
    assert not [r for r in rows if r["mrn"] == kit.P2 and r["doc_code"] == "18842-5"]
    assert [d["mrn"] for d in dead] == [kit.P2]


def test_f4_the_japan_mapping_carries_the_documents_own_loinc_code(storage: kit.Storage) -> None:
    from adapter.mapping.engine import Mapper, Mapping

    m = Mapping.load(JP_MAPPING)
    spec = next(r for r in m.resources if r.type == "DocumentReference")
    mp = Mapper(m, b"k" * 32, "S")
    rows = {r["doc_code"]: r for r in _source(storage).rows("note", "note", None, None)}
    path = mp.map_row(spec, rows["11526-1"])
    assert path is not None
    assert [c.get("code") for c in path["type"]["coding"]] == ["47045-0", "11526-1"]
    local = mp.map_row(spec, rows[""])
    assert local is not None and [c.get("code") for c in local["type"]["coding"]] == ["34133-9"]


# ------------------------------------------------------------------------------------------------ review of PR #1095
@pytest.mark.parametrize(
    "text",
    ["週1回 1日1回 月曜", "疼痛時 1日3回まで", "頓用 1日2回を限度", "隔日 1日1回", "1日3回 分3", "月2回 1日1回",
     "1日1回 1日2回"],
)  # fmt: skip
def test_review_1_a_usage_the_reader_does_not_fully_understand_gives_no_daily_dose(text: str) -> None:
    from adapter.sources.ssmix2.source import doses_from_text

    assert doses_from_text(text) is None


@pytest.mark.parametrize(
    ("text", "n"), [("１日３回毎食後", 3), ("内服・経口・1日3回朝昼夕食後", 3), ("1日1回 就寝前", 1)]
)
def test_review_1_a_plain_times_a_day_with_meal_times_is_still_read(text: str, n: int) -> None:
    from adapter.sources.ssmix2.source import doses_from_text

    assert doses_from_text(text) == n


def _prb_row(tmp_path: Path, prb: str, extra: tuple[str, ...] = ()) -> dict[str, object]:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    segs = [kit._msh("20261001090000", "PPR^ZD1^PPR_ZD1", "P1"), kit._pid(kit.P1), prb, *extra]
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp("20261001"), segs)
    (row,) = list(_source(st).rows("diagnosis", "diagnosis", None, None))
    return row


@pytest.mark.parametrize(
    ("name", "flag", "zpr"),
    [("肺癌疑", "", ()), ("肺癌(疑)", "", ()), ("肺癌", "1^疑い^99ZZZ", ()), ("肺癌", "", ("ZPR|1|8002",))],
)
def test_review_3_every_way_of_writing_a_suspicion_reads_as_suspected(
    tmp_path: Path, name: str, flag: str, zpr: tuple[str, ...]
) -> None:
    prb = ["PRB", "AD", "20261001", f"99990009^{name}^MDCDX2", "DX0009"] + [""] * 14
    prb[13], prb[10] = flag, "C349^^I10"
    assert _prb_row(tmp_path, "|".join(prb), zpr)["suspected"] == "Y"


@pytest.mark.parametrize(
    ("outcome", "status"),
    [("R^x^HL70241", "U"), ("N^x^HL70241", "U"), ("W^x^HL70241", "U"), ("Z^x^JHSD0006", "U"), ("Q", "U"),
     ("F^治癒^HL70241", "R"), ("D^死亡^HL70241", "I"), ("R", "R"), ("A", "A")],
)  # fmt: skip
def test_review_4_only_cited_outcome_codes_are_mapped_and_an_unlisted_one_is_never_active(
    tmp_path: Path, outcome: str, status: str
) -> None:
    prb = ["PRB", "AD", "20261001", "99990009^胃炎^MDCDX2", "DX0009"] + [""] * 14
    prb[10], prb[14] = "K297^^I10", outcome
    assert _prb_row(tmp_path, "|".join(prb))["status"] == status


def test_review_all9_keeps_its_day_under_unique_for_a_type_that_is_not_adt(tmp_path: Path) -> None:
    """A mutant survived: "ALL9 keeps its day" was only proved through ADT types. Two PPR-01 snapshots under ALL9
    on two day folders stay two records under ``unique`` too (each read, and not counted as a repeat)."""
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    for day, dx in (("20261001", "DX0001"), ("20261002", "DX0002")):
        prb = ["PRB", "AD", "20261001", "99990001^胃炎^MDCDX2", dx] + [""] * 14
        prb[10] = "K297^^I10"
        segs = [kit._msh(f"{day}090000", "PPR^ZD1^PPR_ZD1", dx), kit._pid(kit.P1), "|".join(prb)]
        kit._write(st, kit.P1, day, "PPR-01", "ALL9", kit._stamp(day), segs)
    src = _source(st, order_key="unique")
    assert sorted(r["diag_no"] for r in src.rows("diagnosis", "diagnosis", None, None)) == ["DX0001", "DX0002"]
    assert not [k for k in src.stats if "several days" in k]
