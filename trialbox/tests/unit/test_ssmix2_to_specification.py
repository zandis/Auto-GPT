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


@pytest.fixture
def verified_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The PRB-14 table as if the owner's Japanese reader had verified every proposed row (``verified`` = ``yes``):
    what the reader then does with each status. The shipped table applies none (second review of PR #1095 item 9)."""
    import csv

    from adapter.sources.ssmix2 import source

    table: dict[str, dict[str, str]] = {}
    with (source.JP_CORE / "prb14_outcome.csv").open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            table.setdefault(r["system"].upper(), {})[r["code"].upper()] = r["status"]
    monkeypatch.setattr(source, "_OUTCOME", table)
    monkeypatch.setattr(source, "_OUTCOME_ANY", {c: st for t in table.values() for c, st in t.items()})


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


def test_f2_no_unverified_outcome_code_is_applied_and_none_reads_as_active(storage: kit.Storage) -> None:
    """Second review of PR #1095 item 9: no row of ``prb14_outcome.csv`` is verified, so every coded outcome is U
    (unknown, never active, D-587); the days are still read."""
    rows, _, _ = _diagnoses(storage)
    got = {k: (rows[v]["status"], rows[v]["outcome"]) for k, v in kit.DX.items() if v in rows}
    assert got == {
        "gastritis": ("A", ""),
        "uri": ("U", "F"),
        "ra": ("U", "M"),
        "pneumonia": ("A", ""),
        "infarct": ("U", "D"),
        "stopped": ("U", "I"),
    }
    uri = rows[kit.DX["uri"]]
    assert (uri["end_date"], uri["outcome_date"], uri["main_diagnosis"]) == ("2026-03-01", "2026-03-01", "N")


def test_f2_every_outcome_is_read_none_reads_as_active_by_mistake(
    storage: kit.Storage, verified_outcomes: None
) -> None:
    """Once verified: cured (F, HL7 0241) is resolved with its end and outcome days; remission (M, JHSD0006) is
    remission; died (D) is inactive; follow-up stopped (I, JHSD0006) says neither and is U."""
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


def test_f2_the_japan_mapping_gives_each_status_its_fhir_word(storage: kit.Storage, verified_outcomes: None) -> None:
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
     ("F^治癒^HL70241", "U"), ("D^死亡^HL70241", "U"), ("C^継続^JHSD0006", "U"), ("M^寛解^JHSD0006", "U"),
     ("F", "U"), ("R", "R"), ("A", "A")],
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


def test_review_2_a_diagnosis_recorded_long_ago_and_ended_last_night_is_read_on_a_delta(tmp_path: Path) -> None:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    prb = ["PRB", "UP", "20200101090000", "99990003^急性上気道炎^MDCDX2", "DX0003"] + [""] * 14
    prb[10], prb[14], prb[15] = "J069^^I10", "F^治癒^HL70241", "20261101"
    segs = [kit._msh("20261101090000", "PPR^ZD1^PPR_ZD1", "P1"), kit._pid(kit.P1), "|".join(prb)]
    kit._write(st, kit.P1, "-", "PPR-01", "ALL9", kit._stamp("20261101"), segs)
    rows = list(_source(st).rows("diagnosis", "diagnosis", "recorded_date", "2026-11-01 00:00:00"))
    assert [(r["diag_no"], r["status"]) for r in rows] == [("DX0003", "U")] and "_changed" not in rows[0]


def test_review_2_a_new_version_of_a_document_is_read_on_a_delta(storage: kit.Storage) -> None:
    """A corrected discharge summary written on 2026-11-02 under its day 2026-10-15: a delta from 2026-11-01 reads it
    (the day alone would not)."""
    doc = kit.DOCS[0]
    kind = storage.extended / doc.patient[0:3] / doc.patient[3:6] / doc.patient / doc.day / doc.kind
    newer = kind / doc.folder.replace(kit._stamp("20261015", "170000"), kit._stamp("20261102", "100000"))
    newer.mkdir()
    (newer / "summary.txt").write_bytes("訂正版。".encode())
    rows = list(_source(storage).rows("note", "note", "note_datetime", "2026-11-01 00:00:00"))
    assert [(r["doc_code"], r["text"]) for r in rows] == [("18842-5", "訂正版。")] and "_changed" not in rows[0]


def test_review_5_an_hl7_explicit_null_is_empty_never_a_value() -> None:
    from adapter.sources.ssmix2 import hl7

    seg = hl7.parse('MSH|^~\\&\rOBX|1|NM|X^y^JC10||""|""|""|""|||""').first("OBX")
    assert seg is not None
    assert [seg.field(n) for n in (5, 6, 7, 8, 11)] == ["", "", "", "", ""]
    assert hl7.Segment.rep_comp('""^x', 1) == ""


def test_review_escapes_and_declared_separators_are_read() -> None:
    from adapter.sources.ssmix2 import hl7

    assert hl7.unescape("a\\.br\\b\\X41\\c\\F\\d") == "a\nbAc|d"
    m = hl7.parse("MSH#:*%@#HIS\rPID###10^1:x:PI")
    pid = m.first("PID")
    assert pid is not None and (pid.comp(3, 1), pid.comp(3, 3)) == ("10^1", "PI")


def test_review_6_every_drug_of_an_order_is_a_row_with_its_own_key(tmp_path: Path) -> None:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    day = "20261001"
    segs = [kit._msh(f"{day}090000", "RDE^O11^RDE_O11", "RX9"), kit._pid(kit.P1)]
    for drug, yj in (
        ("999000001^アロプリノール^HOT9", "3943001F1020^x^YJ"),
        ("999000003^メトホルミン^HOT9", "3962002F1020^x^YJ"),
    ):
        rxe = ["RXE", "", drug, "1", "", "TAB"] + [""] * 26
        rxe[31] = yj
        segs += [f"ORC|NW|RX0009||1|IP||||{day}0900", f"TQ1|1||&1日2回朝夕食後&99XYZ||||{day}", "|".join(rxe)]
    kit._write(st, kit.P1, day, "OMP-01", "RX0009", kit._stamp(day), segs)
    rows = {r["rx_no"]: r for r in _source(st).rows("medication", "medication", None, None)}
    assert {k: (r["atc"], r["daily_dose"]) for k, r in rows.items()} == {
        "RX0009#1:999000001": ("M04AA01", "2"),
        "RX0009#1:999000003": ("A10BA02", "2"),
    }


def _ss(tmp_path: Path) -> kit.Storage:
    st = kit.Storage(tmp_path / "ss", tmp_path / "ss" / "extended_storage")
    st.root.mkdir(parents=True)
    return st


def test_review_7_names_that_are_not_message_files_are_counted_never_read(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    segs = [kit._msh("20261001093000", "ADT^A04^ADT_A01", "x"), kit._pid(kit.P1), kit._pv1("O", "V1", "202610010930")]
    good = kit._write(st, kit.P1, "20261001", "ADT-12", "1", kit._stamp("20261001"), segs)
    for name in (good.name + ".bak", good.name.rsplit("_", 1)[0] + "_9", "_".join(good.name.split("_")[:6])):
        (good.parent / name).write_bytes(good.read_bytes())
    (good.parent.parent / good.name).write_bytes(good.read_bytes())  # one folder too shallow
    src = _source(st)
    assert len(list(src.rows("encounter", "encounter", None, None))) == 1
    stats = {k: n for k, n in src.stats.items() if k.startswith("storage:")}
    assert stats == {
        "storage:file name not read (an extension (not a message file))": 1,
        "storage:file name not read (a condition flag other than 0, 1 or 2)": 1,
        "storage:file name not read (6 parts, not 7)": 1,
        "storage:file at another folder depth": 1,
    }
    assert not [k for k in stats if kit.P1 in k]  # a pattern, never the patient


def test_review_7_on_an_equal_time_a_deletion_wins(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    segs = [kit._msh("20261001093000", "ADT^A04^ADT_A01", "x"), kit._pid(kit.P1), kit._pv1("O", "V1", "202610010930")]
    for flag in ("1", "0"):
        kit._write(st, kit.P1, "20261001", "ADT-12", "1", kit._stamp("20261001"), segs, flag=flag)
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert [r["enc_no"] for r in src.deleted_rows("encounter", "encounter", None, None)] == ["V1"]


def test_review_8_one_order_number_on_two_days_gives_two_keys_and_a_misfiled_cancel_is_counted(tmp_path: Path) -> None:
    st = _ss(tmp_path)
    for day, flag, stamp in (("20261001", "1", "090000"), ("20261002", "1", "090000"), ("20261003", "0", "090000")):
        rxe = ["RXE", "", "999000001^x^HOT9", "1", "", "TAB"] + [""] * 26
        rxe[31] = "3943001F1020^x^YJ"
        segs = [kit._msh(f"{day}090000", "RDE^O11^RDE_O11", day), kit._pid(kit.P1),
                f"ORC|NW|RX1||1|IP||||{day}0900", "|".join(rxe)]  # fmt: skip
        kit._write(st, kit.P1, day, "OMP-01", "RX1", kit._stamp(day, stamp), segs, flag=flag)
    src = _source(st)
    assert sorted(r["rx_no"] for r in src.rows("medication", "medication", None, None)) == [
        "RX1@20261001",
        "RX1@20261002",
    ]
    assert src.stats["OMP-01:delete filed under another day (order left live)"] == 1


def test_review_tombstones_never_grow_or_repeat_on_another_call(storage: kit.Storage) -> None:
    src = _source(storage)
    for _ in range(2):
        list(src.rows("diagnosis", "diagnosis", None, None))
        list(src.rows("note", "note", None, None))
    first = [list(src.deleted_rows(t, t, None, None)) for t in ("diagnosis", "note")]
    second = [list(src.deleted_rows(t, t, None, None)) for t in ("diagnosis", "note")]
    assert first == second and [len(x) for x in first] == [1, 1]


def test_review_a_symbolic_link_is_never_followed_out_of_the_storage(tmp_path: Path) -> None:
    outside = kit.build(tmp_path / "elsewhere")
    st = _ss(tmp_path)
    (st.root / "100").symlink_to(outside.root / "100")
    src = _source(st)
    assert list(src.rows("encounter", "encounter", None, None)) == []
    assert src.stats["storage:symbolic link not followed"] == 1


def test_review_9_euc_jp_named_in_msh18_is_read_as_euc_jp() -> None:
    from adapter.sources.ssmix2 import hl7

    data = "MSH|^~\\&|HIS||TB||20261001||ADT^A08|1|P|2.5||||||EUC-JP\rPID|||1^^^^PI||東京^太郎\r".encode("euc_jp")
    text, codec = hl7.decode_bytes(data)
    assert codec == "euc_jp" and "東京" in text


def test_review_9_an_escape_left_open_at_a_segment_end_sets_the_message_aside() -> None:
    """Second review of PR #1095 item 1: a set left open to a segment's end may have read its separators as
    characters (which bytes were data cannot be known): the message is refused, never read garbled."""
    from adapter.sources.ssmix2 import hl7

    first = "PID|||1^^^^PI||".encode("ascii") + "胃炎".encode("iso2022_jp").removesuffix(b"\x1b(B")
    data = b"MSH|^~\\&|HIS||TB||20261001||ADT^A08|1|P|2.5||||||~ISO IR87\r" + first + b"\rPV1|1|O\r"
    with pytest.raises(hl7.Undecodable, match="left open"):
        hl7.decode_bytes(data)
    closed = data.replace(b"\x1b$B", b"\x1b$B", 1).replace(b"\rPV1", b"\x1b(B\rPV1")
    assert hl7.parse(hl7.decode_bytes(closed)[0]).first("PID").comp(5, 1) == "胃炎"  # type: ignore[union-attr]


def test_review_9_so_si_half_width_katakana_is_read_as_katakana() -> None:
    from adapter.sources.ssmix2 import hl7

    data = b"MSH|^~\\&|HIS||TB||20261001||ADT^A08|1|P|2.5||||||~ISO IR87\rPID|||1^^^^PI||\x0e6\x0f\r"
    text, _codec = hl7.decode_bytes(data)
    assert "\x0e" not in text and "ｶ" in text  # ｶ


def test_review_10_impossible_and_era_dates_are_refused_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.sources.ssmix2 import hl7

    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    assert hl7.ts("R08.11.01") is None  # an era date: no date, counted
    # an impossible date is counted and passed on for the mapping to reject the row (STD-025, test_ssmix2_hardening)
    assert hl7.ts("20261301") == "2026-13-01" and hl7.ts("99999999") == "9999-99-99"
    assert hl7.ts("20261101") == "2026-11-01" and hl7.ts("202611011230+0900") == "2026-11-01 12:30:00"
    st = _ss(tmp_path)
    segs = [kit._msh("20261001093000", "ADT^A04^ADT_A01", "x"), kit._pid(kit.P1), kit._pv1("O", "V1", "20261301")]
    kit._write(st, kit.P1, "20261001", "ADT-12", "1", kit._stamp("20261001"), segs)
    src = _source(st)
    (row,) = list(src.rows("encounter", "encounter", None, None))
    assert row["visit_datetime"] == "2026-13-01"
    assert src.stats["encounter:date not a calendar date (the row is rejected by the mapping)"] == 1
