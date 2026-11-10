"""T-011: a synthetic site built from a schema and code lists (tools/synth_site_from_schema.py).

The two sample schemas (tests/fixtures/site_schema/{jp,tw}-sample.yaml) are fictional. Acceptance: (1) the JP sample
as SS-MIX2 storage of 500 patients ingests with 0 errors through the shipped mapping; (2) the TW sample (ROC dates,
Big5, NHI-shaped codes) as a CSV dump gives a report that lists the planted unmapped codes; (3) the data scan over the
output is clean. Plus: the schema validates, a value in a schema is refused, a planted unit mismatch gives no value
(never FALSE), and Big5 and Shift_JIS outputs read back to the same rows."""

from __future__ import annotations

import copy
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common import encoding, labvalue
from tb_contracts.schema import schema_errors

from tools import data_scan as ds
from tools import synth_site_from_schema as sss

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "site_schema"
MAPPING = ROOT / "services" / "adapter" / "mapping"
TW_MAP = MAPPING / "tw_core" / "demo_his.yaml"
JP_MAP = MAPPING / "jp_core" / "ssmix2_site.yaml"


def _schema(name: str) -> dict[str, Any]:
    return sss.load_schema(FIX / f"{name}-sample.yaml")


@pytest.fixture(scope="module")
def jp_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("jp") / "storage"
    sss.build(_schema("jp"), out, patients=500)
    return out


@pytest.fixture(scope="module")
def tw_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("tw") / "export"
    sss.build(_schema("tw"), out, patients=200)
    return out


# ------------------------------------------------------------------------------------------------ the schema
@pytest.mark.parametrize("name", ["jp", "tw"])
def test_sample_schemas_validate(name: str) -> None:
    doc = yaml.safe_load((FIX / f"{name}-sample.yaml").read_text(encoding="utf-8"))
    assert schema_errors("site_schema", doc) == []
    assert sss.check_schema(doc) == []
    assert doc["fictional"] is True
    assert sss.main(["validate", str(FIX / f"{name}-sample.yaml")]) == 0


@pytest.mark.parametrize(
    "where",
    [
        ("tables", "lab", "sample"),
        ("code_lists", "lab", 0, "value"),
        ("plants", "rows"),
        ("examples",),
    ],
)
def test_a_value_in_a_schema_is_refused(where: tuple[Any, ...]) -> None:
    doc = copy.deepcopy(_schema("tw"))
    node: Any = doc
    for k in where[:-1]:
        node = node[k]
    node[where[-1]] = ["SYNT-0001", "5.2"]
    errs = sss.check_schema(doc)
    assert errs and all("no values in a schema file" in e for e in errs)


def test_a_header_named_value_is_a_header_not_a_value() -> None:
    doc = copy.deepcopy(_schema("tw"))
    cols = doc["tables"]["lab"]["columns"]
    cols["VALUE"] = cols.pop("result_value")
    assert sss.check_schema(doc) == []


def test_schema_refuses_what_it_does_not_know() -> None:
    doc = copy.deepcopy(_schema("tw"))
    doc["feed"]["encoding"] = "latin-1"
    assert sss.check_schema(doc)
    doc = copy.deepcopy(_schema("tw"))
    doc["code_lists"]["lab"][0]["name"] = "酶"  # not in Big5: the site's files could not hold it
    assert any("cannot hold" in e for e in sss.check_schema(doc))
    doc = copy.deepcopy(_schema("tw"))
    doc["plants"]["unit_mismatch"][0]["code"] = "NOPE"
    assert any("not in code_lists/lab" in e for e in sss.check_schema(doc))
    doc = copy.deepcopy(_schema("tw"))
    doc["tables"]["lab"]["columns"]["unit"] = "Unit Of Measure"
    assert any("not a canonical column name" in e for e in sss.check_schema(doc))
    doc = copy.deepcopy(_schema("jp"))
    doc["tables"]["lab"] = {"source": "lab", "columns": {"lab_no": "lab_no"}}
    assert any("no header row" in e for e in sss.check_schema(doc))


def test_cli_refuses_a_bad_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = copy.deepcopy(_schema("tw"))
    doc["tables"]["patient"]["rows"] = [["SYNT-0001"]]
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    assert sss.main(["validate", str(bad)]) == 1
    assert "no values in a schema file" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ acceptance
def test_jp_ssmix2_of_500_patients_ingests_with_no_error(jp_site: Path, tmp_path: Path) -> None:
    """Acceptance (1): SS-MIX2 storage of 500 synthetic patients, the shipped JP mapping, 0 errors."""
    from adapter.pipeline import AdapterConfig, run_ingest

    cfg = AdapterConfig(
        lake_dir=tmp_path / "lake", secrets_dir=tmp_path / "secrets", mapping_path=JP_MAP, site_id="JP-SAMPLE",
        tz="Asia/Tokyo",
    )  # fmt: skip
    rep = run_ingest(cfg, "ssmix2", str(jp_site), snapshot="2026-10-31", load_fhir=False, rebuild_lake=False)
    assert rep.errors == []
    assert rep.passed
    assert rep.counts["Patient"] == 500
    built = json.loads((jp_site / "site_build.json").read_text(encoding="utf-8"))["rows"]
    assert rep.counts["Encounter"] == built["encounter"]
    assert rep.counts["Condition"] == built["diagnosis"]
    assert rep.counts["MedicationRequest"] == built["medication"]
    assert rep.counts["Appointment"] == built["appointment"]
    assert rep.counts["DocumentReference"] == built["note"]


def test_jp_report_lists_the_planted_codes(jp_site: Path, tmp_path: Path) -> None:
    rep = sss.site_report(_schema("jp"), jp_site, JP_MAP, tmp_path / "staged")
    assert rep["passed"]
    assert set(rep["tables"]["lab"]["unmapped_codes"]) == {
        "lab local_code=9Z999000009999901 (not in lookup)",
        "lab local_code=9Z999000009999902 (not in lookup)",
    }
    assert set(rep["unit_mismatch"]) == {"3C015000002327101"}


def test_tw_csv_with_roc_dates_lists_the_planted_unmapped_codes(tw_site: Path, tmp_path: Path) -> None:
    """Acceptance (2): ROC dates, Big5, NHI-shaped codes; the report names the planted codes and holds no value."""
    first = (tw_site / "encounter.csv").read_bytes().decode("big5").splitlines()[1]
    assert first.split(",")[2][:3].isdigit() and first.split(",")[2][3:7].isdigit() and "-" not in first.split(",")[2]
    rep = sss.site_report(_schema("tw"), tw_site, TW_MAP, tmp_path / "staged")
    assert rep["passed"], rep
    lab = rep["tables"]["lab"]
    assert set(lab["unmapped_codes"]) == {
        "lab local_code=ZZLAB01 (not in lookup)",
        "lab local_code=ZZLAB02 (not in lookup)",
    }
    assert lab["resources"] == lab["rows_read"] - sum(lab["unmapped_codes"].values())
    assert rep["unit_mismatch"] == {"CRE": rep["unit_mismatch"]["CRE"]} and rep["unit_mismatch"]["CRE"] > 0
    text = json.dumps(rep, ensure_ascii=False)
    assert "SYNT-" not in text  # no chart number
    with (tmp_path / "staged" / "lab.csv").open(encoding="utf-8") as fh:
        results = {r["result_value"] for r in csv.DictReader(fh)}
    assert not any(f'"{v}"' in text for v in results)  # no result value


def test_cli_check_prints_the_report(tw_site: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = str(FIX / "tw-sample.yaml")
    assert sss.main(["check", schema, "--out", str(tw_site), "--mapping", str(TW_MAP)]) == 0
    out = capsys.readouterr().out
    assert "ZZLAB01" in out and "unit mismatch: lab CRE" in out and out.rstrip().endswith("PASSED")


def test_the_data_scan_over_the_output_is_clean(jp_site: Path, tw_site: Path, tmp_path: Path) -> None:
    """Acceptance (3), and the scan is not blind to these files: a chart number planted in a copy is found."""
    staged = tmp_path / "staged"
    sss.stage(_schema("tw"), tw_site, staged)
    patterns, allow = ds.load_patterns(), ds.Allow({}, [])
    for where in (tw_site, staged, jp_site):
        files = [p for p in where.rglob("*") if p.is_file()]
        assert files
        assert ds.run(files, base=tmp_path, patterns=patterns, allow=allow, in_repo=False) == []
    planted = tmp_path / "planted.csv"
    rows = (staged / "patient.csv").read_text(encoding="utf-8").splitlines()
    chart = "".join(str(i) for i in range(2, 10))
    planted.write_text("\n".join([*rows[:3], f"{chart},,1960-01-01,M"]) + "\n", encoding="utf-8")
    hits = ds.run([planted], base=tmp_path, patterns=patterns, allow=allow, in_repo=False)
    assert [h.pattern for h in hits] == ["chart_number"]


# ------------------------------------------------------------------------------------------------ the plants
def test_a_planted_unit_mismatch_has_no_value_never_false(tw_site: Path, tmp_path: Path) -> None:
    """R-31, D-215: a creatinine in µmol/L under a mg/dL lookup becomes no value (unknown), never a number."""
    from adapter.mapping.engine import Mapper, Mapping

    _kind, path = sss.stage(_schema("tw"), tw_site, tmp_path / "staged")
    with (Path(path) / "lab.csv").open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["local_code"] == "CRE"]
    planted = [r for r in rows if r["unit"] == "umol/L"]
    assert planted and len(planted) < len(rows)
    m = Mapping.load(TW_MAP)
    mapped = list(Mapper(m, b"k" * 32, "T").map_table("lab", iter(m.normalize("lab", r) for r in rows)))
    bad = [r for r in mapped if (r.get("dataAbsentReason") or {}).get("text") == labvalue.UNIT_MISMATCH]
    assert len(bad) == len(planted)
    for r in bad:
        assert not any(k.startswith("value") for k in r)
    good = [r for r in mapped if "valueQuantity" in r]
    assert len(good) == len(rows) - len(planted)
    assert all(r["valueQuantity"]["unit"] == "mg/dL" and r["valueQuantity"]["value"] < 2 for r in good)


def test_the_plants_appear_and_the_build_is_deterministic(tmp_path: Path) -> None:
    s = _schema("tw")
    a, b = sss.generate(s, 50, seed=3), sss.generate(s, 50, seed=3)
    assert a == b
    assert sss.generate(s, 50, seed=4) != a
    codes = {r["local_code"] for r in a["lab"]}
    assert {"ZZLAB01", "ZZLAB02"} <= codes
    assert any(r["unit"] == "umol/L" for r in a["lab"])
    assert all(r["name"] == "" for r in a["patient"])  # no names at all
    with pytest.raises(sss.SchemaError):
        sss.generate(s, sss.MAX_PATIENTS + 1)


# ------------------------------------------------------------------------------------------------ encodings
def test_big5_output_round_trips(tw_site: Path) -> None:
    schema = _schema("tw")
    data = (tw_site / "lab.csv").read_bytes()
    assert encoding.detect(data)[0] in ("big5", "cp950")
    want = sss.generate(schema, 200)
    got = sss.read_tables(schema, tw_site)
    for table in schema["tables"]:
        header, rows = sss._local_rows(schema, table, want[table], "roc7")
        assert [list(r.values()) for r in got.get(table, [])] == rows, table
        assert list(got[table][0]) == header if rows else True


def _jp_csv_schema() -> dict[str, Any]:
    """The JP sample as a Shift_JIS, tab-separated CSV export with local headers and YYYYMMDD dates."""
    s = copy.deepcopy(_schema("jp"))
    s["site"] = "jp-sample-csv"
    s["feed"] = {"layout": "csv", "encoding": "shift_jis", "date_format": "yyyymmdd", "delimiter": "\t",
                 "extension": ".txt"}  # fmt: skip
    s["tables"] |= {
        "patient": {"source": "KANJA", "columns": {"KANJA_ID": "mrn", "SEINENGAPPI": "birth_date", "SEIBETSU": "sex"}},
        "encounter": {"source": "JUSHIN", "columns": {"JUSHIN_NO": "enc_no", "KANJA_ID": "mrn",
                      "JUSHIN_NICHIJI": "visit_datetime", "KA": "dept_code", "ISHI": "staff_id", "KUBUN": "enc_type"}},
        "lab": {"source": "KENSA", "columns": {"KENSA_NO": "lab_no", "KANJA_ID": "mrn", "JLAC10": "local_code",
                "KOMOKU": "item_name", "KEKKA": "result_value", "TANI": "unit", "SAISHU_NICHIJI": "sample_datetime"}},
    }  # fmt: skip
    s["code_lists"]["sex"] = {"M": "1", "F": "2"}
    s["code_lists"]["encounter_type"] = {"OPD": "G", "IPD": "N", "ER": "K"}
    assert sss.check_schema(s) == []
    return s


def test_shift_jis_output_round_trips(tmp_path: Path) -> None:
    schema = _jp_csv_schema()
    out = tmp_path / "export"
    sss.build(schema, out, patients=40)
    data = (out / "KENSA.txt").read_bytes()
    assert encoding.detect(data, ("cp932", "big5"))[0] in ("cp932", "shift_jis")
    assert "クレアチニン".encode("shift_jis") in data
    want = sss.generate(schema, 40)
    got = sss.read_tables(schema, out)
    for table in schema["tables"]:
        if table in sss.EXTENDED_TABLES and not want[table]:
            continue
        _header, rows = sss._local_rows(schema, table, want[table], "yyyymmdd")
        assert [list(r.values()) for r in got[table]] == rows, table
    assert {r["SEIBETSU"] for r in got["patient"]} <= {"1", "2"}


def test_sql_layout_writes_a_database_and_a_dump(tmp_path: Path) -> None:
    schema = copy.deepcopy(_schema("tw"))
    schema["feed"] = {"layout": "sql", "encoding": "utf-8", "date_format": "roc7"}
    out = tmp_path / "sql"
    sss.build(schema, out, patients=30)
    assert "CREATE TABLE lab" in (out / "site.sql").read_text(encoding="utf-8")
    with sqlite3.connect(out / "site.sqlite") as db:
        assert db.execute("SELECT count(*) FROM patient").fetchone()[0] == 30
    rep = sss.site_report(schema, out, TW_MAP, tmp_path / "staged")
    assert rep["passed"]
    assert "lab local_code=ZZLAB01 (not in lookup)" in rep["tables"]["lab"]["unmapped_codes"]


def test_a_parse_error_is_reported_without_its_value(tw_site: Path, tmp_path: Path) -> None:
    """A schema that states the wrong date format: the adapter cannot read a date; the report says so, no value."""
    schema = copy.deepcopy(_schema("tw"))
    schema["feed"]["date_format"] = "iso"  # the files hold ROC dates
    rep = sss.site_report(schema, tw_site, TW_MAP, tmp_path / "staged")
    assert not rep["passed"]
    assert rep["parse_errors"] == ["unparseable date '…'"]


# ------------------------------------------------------------------------------------------------ the scan (D-203)
def test_scan_pattern_from_a_stated_chart_number_form(tw_site: Path, tmp_path: Path) -> None:
    entry = sss.scan_pattern(_schema("tw"))
    assert entry is not None and entry["id"] == "chart_number_tw_sample"
    pfile = tmp_path / "patterns.yaml"
    pfile.write_text(yaml.safe_dump({"patterns": [entry]}, allow_unicode=True), encoding="utf-8")
    (pat,) = ds.load_patterns(pfile)
    chart = "Q" + "".join(str(i) for i in range(2, 10))
    assert list(pat.hits(f"seen in clinic, {chart}, follow up")) == [chart]
    assert list(pat.hits("visit 20261110 lab 3C015000002327101")) == []
    files = [p for p in tw_site.rglob("*") if p.is_file()]
    assert ds.run(files, base=tmp_path, patterns=[pat], allow=ds.Allow({}, []), in_repo=False) == []


def test_no_bare_pattern_for_a_digits_only_form(capsys: pytest.CaptureFixture[str]) -> None:
    assert sss.scan_pattern(_schema("jp")) is None  # 10 digits, no check digit: it would hit every count
    luhn = copy.deepcopy(_schema("jp"))
    luhn["identifiers"]["chart_number"]["check"] = "luhn"
    assert (sss.scan_pattern(luhn) or {}).get("check") == "luhn"
    assert sss.main(["scan-pattern", str(FIX / "jp-sample.yaml")]) == 0
    assert "no bare pattern" in capsys.readouterr().out
