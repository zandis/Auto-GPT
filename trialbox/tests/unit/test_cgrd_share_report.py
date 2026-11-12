"""T-731 (D-588): the first look at a source shaped like the CGRD layout, and the one report that may leave the site.

The database here is synthetic. Its "patients" are built at run time from parts, so that this file holds no value
the data scan would take for a real one.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping import sharereport
from adapter.sources.cgrd_sql.source import SqlSource

from tools import mapping_check

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"

CHART = ["1" + "0" * 6 + str(n) for n in (2, 3, 4)]  # chart numbers
NAME = [chr(0x738B) + chr(0x5C0F) + chr(0x660E), chr(0x9673) + chr(0x7F8E) + chr(0x73B2), "LIN " + "MEI-HUA"]
NID = ["A" + "".join(str(i) for i in range(1, 10)), "B" + "2" + "0" * 7 + "6", "C" + "1" + "9" * 8]
PHONE = "09" + "12" + "345" + "678"
BORN = ["1960-" + "03-02", "0490312", "1971/" + "11/30"]
PRIVATE = [*CHART, *NAME, *NID, PHONE, *BORN]

MAPPING = f"""
version: 1
name: SYN_cgrd
extends: {BASE}
tz: Asia/Taipei
tables:
  patient:
    source: PATIENT_VIEW
    key: mrn
    rename: {{CHART_NO: mrn, PT_NAME: name, ID_NO: id_no, BIRTH_DATE: birth_date, SEX: sex}}
    values: {{sex: {{"1": M, "2": F}}}}
    identity: {{name: name, national_id: id_no}}
  encounter:
    source: VISIT_VIEW
    key: enc_no
    delta: updated_at
    rename: {{UPDATE_TIME: updated_at, VISIT_NO: enc_no, CHART_NO: mrn, VISIT_TIME: visit_datetime, DEPT: dept_code, DOC_ID: staff_id, VISIT_TYPE: enc_type}}
    values: {{enc_type: {{O: OPD, I: IPD, E: ER}}}}
  diagnosis:
    source: DIAG_VIEW
    key: diag_no
    delta: updated_at
    rename: {{UPDATE_TIME: updated_at, DIAG_ID: diag_no, VISIT_NO: enc_no, CHART_NO: mrn, ICD10_CODE: icd10, DIAG_DATE: diag_date, KEYIN_DATE: recorded_date, DIAG_STATUS: status}}
  lab:
    source: LAB_VIEW
    key: lab_no
    delta: updated_at
    rename: {{UPDATE_TIME: updated_at, LAB_ID: lab_no, CHART_NO: mrn, ITEM_CODE: local_code, ITEM_NAME: item_name, RESULT: result_value, UNIT: unit, SAMPLE_TIME: sample_datetime}}
  vital:
    source: VITAL_VIEW
    key: vital_no
"""

DAY, NEXT = "2026-11-10", "2026-11-11"


def _db(path: Path) -> str:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE PATIENT_VIEW (CHART_NO TEXT, PT_NAME TEXT, ID_NO TEXT, BIRTH_DATE TEXT, SEX TEXT, ADDRESS TEXT);
        CREATE TABLE VISIT_VIEW (UPDATE_TIME TEXT, VISIT_NO TEXT, CHART_NO TEXT, VISIT_TIME TEXT, DEPT TEXT,
                                 DOC_ID TEXT, VISIT_TYPE TEXT, CHIEF_COMPLAINT TEXT);
        CREATE TABLE DIAG_VIEW (UPDATE_TIME TEXT, DIAG_ID TEXT, VISIT_NO TEXT, CHART_NO TEXT, ICD10_CODE TEXT,
                                DIAG_DATE TEXT, KEYIN_DATE TEXT, DIAG_STATUS TEXT);
        CREATE TABLE LAB_VIEW (UPDATE_TIME TEXT, LAB_ID TEXT, CHART_NO TEXT, ITEM_CODE TEXT, ITEM_NAME TEXT,
                               RESULT TEXT, UNIT TEXT, SAMPLE_TIME TEXT, REMARK TEXT);
        """
    )
    con.executemany("INSERT INTO PATIENT_VIEW VALUES (?,?,?,?,?,?)",
                    [(CHART[i], NAME[i], NID[i], BORN[i], "12X"[i], NAME[i] + " street") for i in range(3)])  # fmt: skip
    at = f"{DAY} 09:00:00"
    con.executemany("INSERT INTO VISIT_VIEW VALUES (?,?,?,?,?,?,?,?)", [
        (at, "V1", CHART[0], f"{DAY} 08:30:00", "RHEU", "S1", "O", NAME[0] + " says"),
        (at, "V2", CHART[1], "1151110" + "0830", "RHEU", "S1", "D", ""),        # ROC date-time; a type nobody mapped
        (at, "V3", CHART[2], f"{DAY}T08:30:00", "RHEU", "S1", NAME[1], ""),     # a name where the type belongs
        (f"{NEXT} 09:00:00", "V4", CHART[0], f"{NEXT} 08:30:00", "RHEU", "S1", "O", ""),  # another day
    ])  # fmt: skip
    con.executemany("INSERT INTO DIAG_VIEW VALUES (?,?,?,?,?,?,?,?)", [
        (at, "D1", "V1", CHART[0], "M05.79", DAY, DAY, "A"),
        (at, "D2", "V2", CHART[1], "M05.79", "115/11/10", "115/11/10", "A"),
        (at, "D3", "V3", CHART[2], "M05.79", "民國115年11月10日", DAY, PHONE),   # a phone where the status belongs
        (at, "D4", "V1", CHART[0], "M05.79", "1151110", DAY, "X"),
    ])  # fmt: skip
    con.executemany("INSERT INTO LAB_VIEW VALUES (?,?,?,?,?,?,?,?,?)", [
        (at, "L1", CHART[0], "CRE", "creatinine", "1.1", "mg/dL", f"{DAY} 07:00:00", ""),
        (at, "L1", CHART[0], "CRE", "creatinine", "1.1", "mg/dL", f"{DAY} 07:00:00", ""),      # the same row twice
        (at, "L2", CHART[1], "CRE", "creatinine", "97", "umol/L", f"{DAY} 07:00:00", ""),      # another unit
        (at, "L2", CHART[1], "CRE", "creatinine", "99", "umol/L", f"{DAY} 07:00:00", ""),      # one key, two values
        (at, "L3", CHART[2], "ALT", "ALT", "30", "IU/L", "2026-11-09 07:00:00", ""),
        (at, "L3", CHART[2], "ALT", "ALT", "31", "IU/L", f"{DAY} 07:00:00", ""),               # the number used again
        (at, "L4", CHART[0], "ZZ9", "a new test", "5", "x", f"{DAY} 07:00:00", ""),            # not in the look-up
        (at, "L5", CHART[0], CHART[0], "x", "5", "x", f"{DAY} 07:00:00", ""),                  # a chart number as code
        (at, "L6", CHART[0], "CRE", "creatinine", "1.0", NID[0], f"{DAY} 07:00:00", ""),       # an id as the unit
        (at, "L7", CHART[0], "HBSAG", "HBsAg", "陽性", "", f"{DAY} 07:00:00", ""),
        (at, "L8", CHART[0], "HBSAG", "HBsAg", "see " + NAME[2], "", f"{DAY} 07:00:00", NAME[0]),  # free text
        (at, "L9", CHART[0], "CRE", "creatinine", "1.2", "mg/dL", "26/11/10", ""),             # a two-digit year
    ])  # fmt: skip
    con.commit()
    con.close()
    return f"sqlite:///{path}"


@pytest.fixture
def site(tmp_path: Path) -> tuple[Path, str]:
    mp = tmp_path / "syn.yaml"
    mp.write_text(MAPPING, encoding="utf-8")
    return mp, _db(tmp_path / "cgrd.db")


def _share(site: tuple[Path, str], **kw: Any) -> dict[str, Any]:
    return dict(mapping_check.check(site[0], "cgrd_sql", site[1], **kw)["share"])


def _texts(x: Any) -> list[str]:
    if isinstance(x, dict):
        return [t for k, v in x.items() for t in (*_texts(k), *_texts(v))]
    if isinstance(x, list):
        return [t for v in x for t in _texts(v)]
    return [x] if isinstance(x, str) else []


def test_nothing_of_a_patient_is_in_the_share_report(site: tuple[Path, str]) -> None:
    rep = _share(site, rows=0)
    text = json.dumps(rep, ensure_ascii=False)
    for value in PRIVATE:
        assert value not in text, value
    for part in ("street", "says", "MEI", "see "):  # free text the mapping does not even name, or names as a value
        assert part not in text
    assert rep["withheld"] >= 3  # the chart number as a code, the id as a unit, the phone as a status


def test_the_net_names_what_it_withheld_by_kind_only(site: tuple[Path, str]) -> None:
    rep = _share(site, rows=0)
    lab = rep["tables"]["lab"]
    assert lab["outside_the_map"]["lookup:lab"] == {"ZZ9": 1, sharereport.WITHHELD: 1}
    assert rep["tables"]["diagnosis"]["outside_the_map"]["map:status"] == {"X": 1, sharereport.WITHHELD: 1}
    units = {p["row_unit"] for p in lab["unit_pairs"]}
    assert units == {"mg/dL", "umol/L", "IU/L", sharereport.NOT_A_UNIT}  # the id put in the unit column is no unit
    assert rep["tables"]["encounter"]["outside_the_map"]["values:enc_type"] == {"(not a code)": 1, "D": 1}


def test_dates_are_given_by_their_shape_and_counted_as_read_or_refused(site: tuple[Path, str]) -> None:
    rep = _share(site, rows=0)
    d = rep["tables"]["diagnosis"]["date_shapes"]["diag_date"]
    assert d["shapes"] == {"9999-99-99": 1, "999/99/99": 1, "9999999": 1, "民國999年99月99日": 1}
    assert (d["read"], d["refused"], d["empty"], d["type"]) == (1, 3, 0, "date")
    v = rep["tables"]["encounter"]["date_shapes"]["visit_datetime"]
    assert v["shapes"] == {"9999-99-99 99:99:99": 2, "99999999999": 1, "9999-99-99T99:99:99": 1}
    assert (v["read"], v["refused"]) == (3, 1)
    assert rep["tables"]["patient"]["date_shapes"]["birth_date"]["shapes"] == {
        "9999-99-99": 1, "9999/99/99": 1, "9999999": 1}  # fmt: skip
    assert rep["tables"]["lab"]["date_shapes"]["sample_datetime"]["shapes"]["99/99/99"] == 1


def test_a_refused_row_is_counted_by_reason_and_does_not_stop_the_check(site: tuple[Path, str]) -> None:
    rep = _share(site, rows=0)
    rej = rep["tables"]["diagnosis"]["rejected_rows"]
    assert sum(rej.values()) == 3 and rep["tables"]["diagnosis"]["resources"] == 1
    for reason in rej:
        assert not any(c.isdigit() and c != "9" for c in reason), reason
    assert sum(rep["tables"]["encounter"]["rejected_rows"].values()) == 1
    assert "lab" in rep["tables"] and rep["tables"]["lab"]["resources"] >= 5  # the tables after it were still read


def test_repeated_keys_are_counted_and_a_number_used_on_another_day_is_told_apart(site: tuple[Path, str]) -> None:
    lab = _share(site, rows=0)["tables"]["lab"]["repeated_keys"]
    assert lab == {"key": "lab_no", "rows_without_key": 0, "keys_repeated": 3, "rows_in_them": 6,
                   "identical_copies": 1, "differing_copies": 2, "day_column": "sample_datetime",
                   "differing_on_another_day": 1}  # fmt: skip
    assert _share(site, rows=0)["tables"]["diagnosis"]["repeated_keys"]["keys_repeated"] == 0


def test_unit_spellings_and_result_texts(site: tuple[Path, str]) -> None:
    lab = _share(site, rows=0)["tables"]["lab"]
    by = {(p["code"], p["row_unit"]): p for p in lab["unit_pairs"]}
    assert by[("CRE", "umol/L")]["read"] == "unit_mismatch: no value" and by[("CRE", "umol/L")]["factor"] is not None
    assert by[("CRE", "mg/dL")]["read"] == "same unit" and by[("ALT", "IU/L")]["read"] == "same unit"
    raws = {q["raw"]: q["read"] for q in lab["qualitative_values"]}
    assert raws["陽性"].startswith("POS") and raws["AAA AAA AAA-AAA"].startswith("unknown")


def test_a_table_that_is_not_there_is_said_and_the_rest_is_read(site: tuple[Path, str]) -> None:
    rep = _share(site, rows=0)
    assert rep["tables"]["vital"] == {"source": "VITAL_VIEW", "rows_read": 0, "cannot_be_read": "OperationalError",
                                      "outside_the_map": {}, "unmapped_dropped_or_unknown": {}}  # fmt: skip
    assert rep["passed"] is False and rep["tables"]["lab"]["rows_read"] == 12


def test_one_day_is_read_and_the_limit_is_told(site: tuple[Path, str]) -> None:
    day = _share(site, rows=0, since=f"{DAY} 00:00:00", until=f"{NEXT} 00:00:00")
    assert day["tables"]["encounter"]["rows_read"] == 3 and day["tables"]["encounter"]["window_on"] == "updated_at"
    assert day["tables"]["patient"]["window_on"].startswith("no change-time column")
    cut = _share(site, rows=2)
    assert cut["tables"]["lab"]["rows_read"] == 2 and cut["tables"]["lab"]["cut_at_rows_limit"] is True
    assert _share(site, rows=0)["tables"]["lab"]["cut_at_rows_limit"] is False


def test_only_the_columns_the_mapping_names_are_asked_for(site: tuple[Path, str]) -> None:
    src = SqlSource(site[1])
    rows = list(src.rows("patient", "PATIENT_VIEW", None, None, columns=["chart_no", "SEX", "NOT_THERE"]))
    assert rows[0] == {"chart_no": CHART[0], "SEX": "1"}  # under the names given, whatever the database's case
    assert set(next(iter(src.rows("patient", "PATIENT_VIEW", None, None)))) >= {"ADDRESS", "PT_NAME"}  # as before
    seen: list[str] = []
    real = SqlSource.rows

    def spy(self: SqlSource, *a: Any, **kw: Any) -> Any:
        seen.extend(kw.get("columns") or ["*"])
        return real(self, *a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SqlSource, "rows", spy)
        mapping_check.check(site[0], "cgrd_sql", site[1], rows=0)
    assert "*" not in seen and not {"ADDRESS", "CHIEF_COMPLAINT", "REMARK"} & set(seen)


def test_columns_only_reads_no_row(site: tuple[Path, str]) -> None:
    con = sqlite3.connect(site[1].removeprefix("sqlite:///"))
    con.execute("ALTER TABLE LAB_VIEW RENAME COLUMN UNIT TO unit_txt")
    con.execute("ALTER TABLE DIAG_VIEW RENAME COLUMN ICD10_CODE TO icd10_code")
    con.commit()
    con.close()
    rep = mapping_check.columns_only(site[0], "cgrd_sql", site[1])
    text = json.dumps(rep, ensure_ascii=False)
    assert not any(v in text for v in PRIVATE)
    assert rep["dialect"] == "sqlite" and rep["passed"] is False
    # UNIT is the site's name for it; result_status is a canonical column this site does not map at all
    assert rep["tables"]["lab"]["mapped_names_not_in_table"] == ["UNIT", "result_status"]
    assert rep["tables"]["lab"]["absent_optional"] == ["result_status", "unit"]
    assert rep["tables"]["lab"]["missing_columns"] == []
    assert rep["tables"]["diagnosis"]["names_differ_in_case_only"] == ["ICD10_CODE"]
    assert rep["tables"]["vital"]["cannot_be_read"] == "OperationalError"
    assert rep["tables"]["lab"]["date_column_types"] == {"sample_datetime": "TEXT", "updated_at": "TEXT"}


def test_the_command_prints_only_the_share_report_and_takes_the_connection_from_the_environment(
    site: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SYN_DSN", site[1])
    out = tmp_path / "day.json"
    rc = mapping_check.main(["--mapping", str(site[0]), "--source", "cgrd_sql", "--dsn-env", "SYN_DSN", "--day", DAY,
                             "--rows", "0", "--share", str(out)])  # fmt: skip
    printed = capsys.readouterr().out
    assert rc == 1  # the vital view is not there
    assert json.loads(out.read_text(encoding="utf-8"))["window"] == {"since": f"{DAY} 00:00:00",
                                                                      "until": f"{NEXT} 00:00:00"}  # fmt: skip
    for value in (*PRIVATE, site[1], "cgrd.db"):
        assert value not in printed and value not in out.read_text(encoding="utf-8")
    assert printed.rstrip().endswith(f"Send back only this file: {out}")
    monkeypatch.delenv("SYN_DSN")
    with pytest.raises(SystemExit, match="SYN_DSN is not set"):
        mapping_check.main(["--mapping", str(site[0]), "--source", "cgrd_sql", "--dsn-env", "SYN_DSN"])


@pytest.mark.parametrize(("raw", "want"), [
    ("2026-05-12 08:30:00", "9999-99-99 99:99:99"), ("1150501", "9999999"), ("R8.5.1", "A9.9.9"),
    ("令和8年5月1日", "令和9年9月9日"), ("民國115年05月01日 上午8時", "民國999年99月99日 上午9時"),
    ("2026-05-12T08:30:00Z", "9999-99-99T99:99:99A"), ("Tom 12", "AAA 99"), ("１２/５", "99/9"),
    ("x" * 60, "A" * 40 + "…"), ("", ""),
])  # fmt: skip
def test_shape(raw: str, want: str) -> None:
    assert sharereport.shape(raw) == want


def test_a_reason_keeps_its_words_and_loses_every_value() -> None:
    chart = CHART[0]
    assert sharereport.scrub_reason(f"unparseable date {chart}") == "unparseable date 99999999"
    assert sharereport.scrub_reason(f"not a number: '{chart}'") == "not a number: <value>"
    assert sharereport.scrub_reason(f"bad {NAME[0]} here") == "bad 字字字 here"
