"""NEW-DIN-1, the rest (D-589): a site declares the calendar of a date column; nothing is detected from values."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapper, Mapping, MappingError

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"

SITE = f"""
version: 1
name: roc_site
extends: {BASE}
tz: Asia/Taipei
empty_dates: ["9999-12-31", "99991231", "0000000"]
tables:
  patient: {{source: patient, key: mrn, dates: {{birth_date: roc, death_date: roc}}}}
  lab: {{source: lab, key: lab_no, dates: {{sample_datetime: roc}}}}
  diagnosis: {{source: diagnosis, key: diag_no, dates: {{diag_date: roc}}}}
  medication: {{source: medication, key: rx_no, dates: {{start_date: era, end_date: era}}}}
  encounter: {{source: encounter, key: enc_no}}
"""


def _load(tmp_path: Path, text: str = SITE) -> Mapping:
    p = tmp_path / "site.yaml"
    p.write_text(text, encoding="utf-8")
    return Mapping.load(p)


@pytest.fixture
def m(tmp_path: Path) -> Mapping:
    return _load(tmp_path)


def _lab(when: Any) -> dict[str, Any]:
    return {"lab_no": "L1", "mrn": "P1", "local_code": "CRE", "item_name": "x", "result_value": "1.1",
            "unit": "mg/dL", "sample_datetime": when}  # fmt: skip


def _effective(m: Mapping, when: Any) -> str:
    (res,) = Mapper(m, b"k" * 32, "s").map_table("lab", iter([m.normalize("lab", _lab(when))]))
    return str(res["effectiveDateTime"])


@pytest.mark.parametrize(("raw", "want"), [
    ("1150501", "2026-05-01T00:00:00+08:00"),
    ("0490312", "1960-03-12T00:00:00+08:00"),
    ("11505010830", "2026-05-01T08:30:00+08:00"),
    ("1150501083015", "2026-05-01T08:30:15+08:00"),
    ("115/05/01", "2026-05-01T00:00:00+08:00"),
    ("115-5-1", "2026-05-01T00:00:00+08:00"),
    ("115.05.01 08:30", "2026-05-01T08:30:00+08:00"),
    ("115/05/01 08:30:15", "2026-05-01T08:30:15+08:00"),
    ("民國115年5月1日", "2026-05-01T00:00:00+08:00"),
    ("民國49年3月12日", "1960-03-12T00:00:00+08:00"),
    ("049/03/12", "1960-03-12T00:00:00+08:00"),
    ("民國115年05月01日 08:30", "2026-05-01T08:30:00+08:00"),
    (" 1150501 ", "2026-05-01T00:00:00+08:00"),
    ("1101231", "2021-12-31T00:00:00+08:00"),
])  # fmt: skip
def test_a_column_declared_roc_is_read_in_that_calendar(m: Mapping, raw: str, want: str) -> None:
    assert _effective(m, raw) == want


@pytest.mark.parametrize("raw", [
    "2026-05-01", "20260501", "2026/05/01 08:30", "202605010830",   # western: never read in the other calendar
    "1151301", "1150230", "1150500", "11505012460", "115/05/01 24:00", "115/13/01",
    "R8.5.1", "115年", "abc", "115/05", "11505", "115050108", "1150501T0830", "0000101",
    "3000101",  # the year 2211: outside the range every date must pass
    # the review's finding: digits that are also a western compact value are never taken for a short ROC form
    "201208151000", "200101010000", "2012081510", "260512", "120815", "201012", "490312", "4903120830",
    "490312083015", "26/05/12", "05/12/26", "1/2/3", "49/03/12",
])  # fmt: skip
def test_another_form_in_a_declared_column_is_a_refused_row(m: Mapping, raw: str) -> None:
    with pytest.raises(MappingError):
        _effective(m, raw)


def test_the_refusal_names_the_calendar_and_quotes_the_value(m: Mapping) -> None:
    with pytest.raises(MappingError, match=r"^not a roc calendar date '2026-05-01'$"):
        _effective(m, "2026-05-01")


def test_an_empty_value_stays_empty_and_an_undeclared_column_stays_western(m: Mapping) -> None:
    assert (
        m.normalize("lab", _lab(""))["sample_datetime"] == ""
        and m.normalize("lab", _lab(None))["sample_datetime"] is None
    )
    row = {
        "enc_no": "E1",
        "mrn": "P1",
        "visit_datetime": "1150501",
        "dept_code": "D",
        "staff_id": "S",
        "enc_type": "OPD",
    }
    assert m.normalize("encounter", row)["visit_datetime"] == "1150501"
    with pytest.raises(MappingError, match="unparseable date"):  # as #323 left it
        list(Mapper(m, b"k" * 32, "s").map_table("encounter", iter([m.normalize("encounter", row)])))


def test_a_date_condition_reads_the_declared_calendar(m: Mapping) -> None:
    """The TW Core edition of a diagnosis goes by its date (2023 edition from 2025-01-01)."""

    def systems(day: str) -> list[str]:
        row = {"diag_no": "D1", "enc_no": "E1", "mrn": "P1", "icd10": "M05.79", "diag_date": day,
               "recorded_date": "2024-03-02", "status": "A"}  # fmt: skip
        (res,) = Mapper(m, b"k" * 32, "s").map_table("diagnosis", iter([m.normalize("diagnosis", row)]))
        assert res["onsetDateTime"] == ("2024-12-31" if day.startswith("113") else "2025-01-01")
        return [c["system"] for c in res["code"]["coding"]]

    assert any("2014" in s for s in systems("1131231")) and not any("2023" in s for s in systems("1131231"))
    assert any("2023" in s for s in systems("1140101"))


@pytest.mark.parametrize(("raw", "want"), [
    ("R8.5.1", "2026-05-01"), ("令和8年5月1日", "2026-05-01"), ("令和元年5月1日", "2019-05-01"), ("H31.4.30", "2019-04-30"),
    ("r8/5/1", "2026-05-01"), ("S60.3.12", "1985-03-12"), ("令和8年5月1日 08:30", "2026-05-01 08:30:00"),
])  # fmt: skip
def test_a_column_declared_era_is_read_in_the_japanese_eras(m: Mapping, raw: str, want: str) -> None:
    assert m.normalize("medication", {"start_date": raw})["start_date"] == want


@pytest.mark.parametrize("raw", ["H31.5.1", "平成31年5月1日", "2026-05-01", "1150501", "R8.13.1", "X8.5.1", "5080501"])
def test_a_day_the_era_never_had_or_another_form_is_refused(m: Mapping, raw: str) -> None:
    got = m.normalize("medication", {"start_date": raw})["start_date"]
    with pytest.raises(MappingError, match="not a era calendar date"):
        Mapper(m, b"k" * 32, "s").convert(got, "date")


def test_a_declared_placeholder_is_an_empty_date_and_an_undeclared_one_is_refused(m: Mapping, tmp_path: Path) -> None:
    pat = {"mrn": "P1", "name": "x", "id_no": "y", "birth_date": "0490312", "sex": "M", "death_date": "9999-12-31"}
    row = m.normalize("patient", pat)
    assert row["death_date"] == "" and row["birth_date"] == "1960-03-12"
    res = next(r for r in Mapper(m, b"k" * 32, "s").map_table("patient", iter([row])) if r["resourceType"] == "Patient")
    assert res["birthDate"] == "1960-03-12"
    assert "deceasedDateTime" not in res and "deceasedBoolean" not in res
    assert m.normalize("patient", {**pat, "death_date": " 0000000 "})["death_date"] == ""
    assert m.normalize("patient", {**pat, "name": "9999-12-31"})["name"] == "9999-12-31"  # only in a date column
    plain = Mapping.load(BASE)
    with pytest.raises(MappingError):  # no placeholder is built in
        Mapper(plain, b"k" * 32, "s").convert(plain.normalize("patient", pat)["death_date"], "datetime")


@pytest.mark.parametrize(("old", "new", "why"), [
    ("dates: {sample_datetime: roc}", "dates: {sample_datetime: minguo}", "calendar"),
    ("dates: {sample_datetime: roc}", "dates: {sample_datetim: roc}", "not a date column"),
    ("dates: {sample_datetime: roc}", "dates: {result_value: roc}", "not a date column"),
    ('empty_dates: ["9999-12-31", "99991231", "0000000"]', "empty_dates: 9999-12-31", "empty_dates"),
])  # fmt: skip
def test_a_mapping_that_declares_it_wrongly_does_not_load(tmp_path: Path, old: str, new: str, why: str) -> None:
    assert old in SITE
    with pytest.raises(MappingError, match=why):
        _load(tmp_path, SITE.replace(old, new, 1))


def test_a_mapping_without_declarations_reads_as_before() -> None:
    plain = Mapping.load(BASE)
    row = _lab("2026-05-12 08:30:00")
    assert plain.normalize("lab", row) == row


# ------------------------------------------------------------------------------------------------ DIN-014
@pytest.mark.parametrize(("raw", "want"), [
    ("2026-05-12 08:30:00.000", "2026-05-12T08:30:00+08:00"),
    ("2026-05-12 08:30:15.123456", "2026-05-12T08:30:15+08:00"),
    ("2026/05/12 08:30:15,5", "2026-05-12T08:30:15+08:00"),
    ("2026-05-12T08:30:00.000", "2026-05-12T08:30:00+08:00"),
    ("2026-05-12 8:30", "2026-05-12T08:30:00+08:00"),
    ("2026-05-12 23:59:59", "2026-05-12T23:59:59+08:00"),
    ("2026-05-12", "2026-05-12T00:00:00+08:00"),
])  # fmt: skip
def test_a_time_with_a_fraction_keeps_its_time(raw: str, want: str) -> None:
    assert Mapper(Mapping.load(BASE), b"k" * 32, "s").convert(raw, "datetime") == want


@pytest.mark.parametrize("raw", ["2026-05-12 24:00:00", "2026-05-12 24:00", "2026-05-12 08:60", "2026-05-12 08:30:61",
                                 "2026-05-12 25:00:00.000"])  # fmt: skip
def test_a_time_the_clock_does_not_have_is_refused_not_read_as_midnight(raw: str) -> None:
    with pytest.raises(MappingError, match="unparseable datetime"):
        Mapper(Mapping.load(BASE), b"k" * 32, "s").convert(raw, "datetime")


def test_the_share_report_shows_a_value_not_of_the_declared_calendar_by_its_shape(m: Mapping) -> None:
    from adapter.mapping import sharereport

    rows = [m.normalize("lab", _lab(v)) for v in ("1150501", "2026-05-01", "1150502")]
    got = sharereport.date_shapes(Mapper(m, b"k" * 32, "s"), rows, {"sample_datetime": "datetime"})
    assert got["sample_datetime"]["shapes"] == {"9999-99-99": 2, "9999-99-99 (not roc)": 1}
    assert (got["sample_datetime"]["read"], got["sample_datetime"]["refused"]) == (2, 1)


def test_a_value_that_imitates_the_marker_is_refused_like_any_other(m: Mapping) -> None:
    """A source value that starts with the marker's bytes names no calendar of ours: nothing of it reaches a reason
    or a shape."""
    from adapter.mapping import sharereport

    fake = "\x00not-a-date-of:WANG DA-MING\x00x"
    plain = Mapper(Mapping.load(BASE), b"k" * 32, "s")
    with pytest.raises(MappingError, match="^unparseable datetime "):
        plain.convert(fake, "datetime")
    with pytest.raises(MappingError, match="^unparseable date "):
        plain.convert(fake, "date")
    got = sharereport.date_shapes(plain, [_lab(fake)], {"sample_datetime": "datetime"})
    assert "WANG" not in str(got) and got["sample_datetime"]["refused"] == 1


def test_an_unread_declared_date_refuses_the_row_even_where_nothing_reads_it_as_a_date(tmp_path: Path) -> None:
    """The same column read as a date under a condition that is false and as text elsewhere: the marker must not
    reach a resource."""
    site = (
        SITE
        + """
overlay:
  - type: Patient
    table: patient
    elements:
      deceasedDateTime: {column: death_date, type: datetime, when: {column: sex, in: [M]}}
      address[0].text: {column: death_date}
"""
    )
    m = _load(tmp_path, site)
    pat = {"mrn": "P1", "name": "x", "id_no": "y", "birth_date": "0490312", "sex": "F", "death_date": "2026-05-01"}
    with pytest.raises(MappingError, match="not a roc calendar date"):
        list(Mapper(m, b"k" * 32, "s").map_table("patient", iter([m.normalize("patient", pat)])))


def test_a_period_and_an_added_duration_are_date_columns_too(tmp_path: Path) -> None:
    site = SITE.replace("dates: {start_date: era, end_date: era}", "dates: {start_date: roc, end_date: roc}")
    m = _load(tmp_path, site)
    assert {"start_date", "end_date"} <= m.date_columns["medication"]
    assert "appt_datetime" in Mapping.load(BASE).date_columns["appointment"]
    row = m.normalize("medication", {"start_date": "1150501", "end_date": "9999-12-31"})
    assert (row["start_date"], row["end_date"]) == ("2026-05-01", "")


@pytest.mark.parametrize(
    "raw", ["9999-12-31 00:00:00", "9999-12-31T00:00:00", "9999-12-31 00:00", "9999-12-31 00:00:00.000"]
)
def test_a_placeholder_with_a_midnight_after_it_is_the_placeholder(m: Mapping, raw: str) -> None:
    pat = {"mrn": "P1", "birth_date": "0490312", "death_date": raw}
    assert m.normalize("patient", pat)["death_date"] == ""
    assert m.normalize("patient", {**pat, "death_date": "9999-12-31 08:30:00"})["death_date"] != ""


@pytest.mark.parametrize(("old", "new"), [
    ("dates: {sample_datetime: roc}", "dates: [sample_datetime]"),
    ("dates: {sample_datetime: roc}", "dates: roc"),
    ("dates: {sample_datetime: roc}", "date: {sample_datetime: roc}"),
    ("dates: {sample_datetime: roc}", "calendars: {sample_datetime: roc}"),
    ("dates: {sample_datetime: roc}", "empty_dates: ['9999-12-31']"),
    ("tz: Asia/Taipei", "tz: Asia/Taipei\ndates: {sample_datetime: roc}"),
    ('empty_dates: ["9999-12-31", "99991231", "0000000"]', "empty_dates: 0"),
])  # fmt: skip
def test_a_declaration_in_the_wrong_place_or_shape_does_not_load(tmp_path: Path, old: str, new: str) -> None:
    assert old in SITE
    with pytest.raises(MappingError):
        _load(tmp_path, SITE.replace(old, new, 1))
