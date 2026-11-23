"""The mapping check on code lists (tools.mapping_coverage) and its owner-machine wrapper (tools.owner_code_dictionaries).

Synthetic lists only: the shipped synthetic hospitals' codes, and codes written here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import mapping_coverage as mc
from tools import owner_code_dictionaries as own


@pytest.fixture(scope="module")
def ref() -> mc.Reference:
    return mc.Reference.load()


def _rows(*items: tuple[str, str, str] | tuple[str, str, str, str]) -> list[dict[str, str]]:
    return [dict(zip(("local_code", "local_name", "system", "target_code"), (*i, "")[:4], strict=True)) for i in items]


@pytest.mark.parametrize("style", ["tw", "jp"])
def test_synthetic_hospital_reports_its_figure(style: str, ref: mc.Reference) -> None:
    """The check runs on the shipped synthetic hospitals and prints a figure, 100 % included."""
    rows = [r for rs in mc.synthetic_lists(style).values() for r in rs]
    report = mc.coverage(rows, ref)
    for domain in ("diagnosis", "lab", "medication", "procedure", "department"):
        d = report["by_domain"][domain]
        assert d["codes"] > 0, domain
        assert d["percent"] == 100.0, (domain, [u for u in report["unmapped"] if u["domain"] == domain])
    # the three memory-clinic report kinds have no LOINC rule in a shipped mapping: reported, not skipped
    assert {u["local_code"] for u in report["unmapped"]} == {"CSF-AB", "MRI-BRAIN", "PET-AMY"}
    text = mc.render(report)
    assert f"{report['mapped']} of {report['codes']} codes" in text
    assert "100.0%" in text
    # vital-sign value sets are filled from the export's columns, not a code list
    assert report["valuesets_without_list"] == ["vital"]
    assert report["valuesets_not_reached"] == []


def test_jp_synthetic_uses_the_japanese_routes(ref: mc.Reference) -> None:
    report = mc.coverage([r for rs in mc.synthetic_lists("jp").values() for r in rs], ref)
    assert set(report["by_domain"]["diagnosis"]["routes"]) == {"byomei", "who-icd10"}
    assert "jlac10" in report["by_domain"]["lab"]["routes"]
    assert "yj" in report["by_domain"]["medication"]["routes"]


def test_who_icd10_maps_by_the_same_code_then_the_shipped_table(ref: mc.Reference) -> None:
    """D-314's same code first; then the shipped WHO-to-CM table, applied and reported "applied, not verified"
    while its rows say ``verify`` (SDR2); a code in neither stays on the unmapped list."""
    rows = _rows(("e119", "2型糖尿病", "icd-10"), ("E14.9", "糖尿病", "icd-10"), ("F01.8", "血管性認知症", "icd-10"))
    res = {r.local_code: r for r in (mc.check_code(x, ref) for x in rows)}
    assert res["e119"].mapped and res["e119"].target_code == "E11.9" and not res["e119"].unverified
    assert res["E14.9"].mapped and res["E14.9"].target_code == "E11.9" and res["E14.9"].unverified
    assert not res["F01.8"].mapped and "no row in the WHO-to-CM table" in res["F01.8"].reason
    report = mc.coverage(rows, ref)
    assert report["by_domain"]["diagnosis"]["applied_not_verified"] == 1
    assert [u["local_code"] for u in report["unmapped"]] == ["F01.8"]
    assert "applied, not verified: 1" in mc.render(report)


def test_shipped_who_table_rows_are_icd10cm_codes_with_a_source(ref: mc.Reference) -> None:
    """Every row of the reader's WHO-to-CM table: a WHO code ICD-10-CM lacks, an ICD-10-CM code that exists, a
    relation and a public source; none claims to be verified yet."""
    import csv

    with mc.WHO_CM.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for r in rows:
        assert r["who"] not in ref.icd10cm, r
        assert r["icd10cm"] in ref.icd10cm, r
        assert r["relation"] in ("equivalent", "wider"), r
        assert r["source"].startswith("ICD-10-CM Alphabetic Index"), r
        assert r["verified"] == "verify", r


def test_ssmix2_reader_takes_the_table_and_counts_the_rest(tmp_path: Path) -> None:
    """The reader (lane B2's file, body only): same code, table code, or empty and counted in ``missed``."""
    from adapter.sources.ssmix2.source import Ssmix2Source

    src = Ssmix2Source(tmp_path, licensed={})
    assert src._icd_columns("E11.9") == {"icd10": "E11.9", "icd10cm": "E11.9"}
    assert src._icd_columns("E14.9") == {"icd10": "E14.9", "icd10cm": "E11.9"}
    assert src._icd_columns("F01.8") == {"icd10": "F01.8", "icd10cm": ""}
    assert src.stats["diagnosis:ICD-10-CM from the WHO-to-CM table (applied, not verified)"] == 1
    assert src.stats["diagnosis:WHO ICD-10 with no ICD-10-CM"] == 1
    assert src.missed["diagnosis:F01.8"] == 1


def test_standard_codes_are_checked_too(ref: mc.Reference) -> None:
    """A list already in the criteria's systems is still checked: a wrong check digit or level does not pass."""
    rows = _rows(
        ("3084-1", "urate", "loinc"),
        ("3084-2", "urate typo", "loinc"),
        ("M04AA01", "allopurinol", "atc"),
        ("M04A", "antigout class", "atc"),
        ("M10.9", "gout", "icd-10-cm"),
        ("M10.99X", "not a code", "icd-10-cm"),
        ("RHEU", "Rheumatology", "department"),
        ("NOPE", "a ward", "department"),
    )
    got = {r.local_code: r.mapped for r in (mc.check_code(x, ref) for x in rows)}
    assert got == {
        "3084-1": True,
        "3084-2": False,
        "M04AA01": True,
        "M04A": False,
        "M10.9": True,
        "M10.99X": False,
        "RHEU": True,
        "NOPE": False,
    }


def test_crosswalks_and_site_targets(ref: mc.Reference) -> None:
    rows = _rows(
        ("UA", "uric acid", "local-lab"),
        ("ZZLAB", "unknown lab", "local-lab"),
        ("ZZLAB2", "lab the site maps", "local-lab", "2160-0"),
        ("1A0100000000000000", "a JLAC11 item", "jlac11"),
        ("612345678", "a HOT code", "hot"),
        ("612345679", "a HOT code with ATC", "hot", "M04AA01"),
        ("XX01", "site order", "local-order", "75614B"),
    )
    res = {r.local_code: r for r in (mc.check_code(x, ref) for x in rows)}
    assert res["UA"].route == "lab-lookup" and res["UA"].target_code == "3084-1"
    assert res["ZZLAB"].reason == "not in the lab-lookup table"
    assert res["ZZLAB2"].route == "site table"
    assert "no cross-walk from jlac11" in res["1A0100000000000000"].reason
    assert "no cross-walk from hot" in res["612345678"].reason
    assert res["612345679"].mapped and res["XX01"].mapped


def test_yj_falls_back_to_its_ingredient_stem(ref: mc.Reference) -> None:
    """A YJ code the sample table lacks reaches ATC by its 7-character stem, as the SS-MIX2 reader does."""
    stem = next(iter(ref.stems))
    hit = mc.check_code(_rows((f"{stem}F9999", "a product of a known ingredient", "yj"))[0], ref)
    assert hit.mapped and hit.route == "yj-stem" and hit.target_code == ref.stems[stem][1]
    miss = mc.check_code(_rows(("0000000F0000", "an unknown ingredient", "yj"))[0], ref)
    assert not miss.mapped


def test_value_sets_no_site_code_reaches_are_named(ref: mc.Reference) -> None:
    report = mc.coverage(_rows(("M10.9", "gout", "icd-10-cm")), ref)
    assert report["by_domain"]["diagnosis"]["percent"] == 100.0
    assert "GZQO/VS_TYPE_1_DIABETES_MELLITUS" in report["valuesets_not_reached"]
    assert "GZQO/VS_GOUT" not in report["valuesets_not_reached"]
    # a domain with no list is not called unreached
    assert not any("VS_SERUM_URATE" in v for v in report["valuesets_not_reached"])


def test_criteria_table_names_every_value_set() -> None:
    table = mc.criteria_table()
    assert "| GZQO | VS_BARIATRIC_SURGERY | procedure | nhi-order | 2 | GZQO-EXC-05 |" in table
    assert len(table.splitlines()) - 2 == len(list(mc.RULESETS.glob("*/valuesets/*.json")))


def test_list_without_columns_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.csv").write_text("code,name\nA,b\n", encoding="utf-8")
    assert mc.main([str(tmp_path / "x.csv")]) == 2


def test_cli_lists_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mc.write_lists(mc.synthetic_lists("tw"), tmp_path / "lists")
    assert mc.main([str(tmp_path / "lists"), "--json", str(tmp_path / "r.json")]) == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["by_domain"]["lab"]["percent"] == 100.0
    assert "codes map to the criteria's code systems" in capsys.readouterr().out


# --- the owner-machine wrapper ---------------------------------------------------------------------------------


def _fictional_tw_id() -> str:
    """A string with a valid national-id check digit, built here (no such value is written in the repository)."""
    for n in range(10_000_000):
        s = f"A1{n:08d}"
        if own.tw_id_valid(s):
            return s
    raise AssertionError("unreachable")


@pytest.mark.parametrize("header", ["MRN", "Patient_ID", "病歷號", "患者ID", "カルテ番号", "生年月日", "姓名", "sex"])
def test_owner_refuses_a_patient_identifier_column(tmp_path: Path, header: str) -> None:
    f = tmp_path / "t.csv"
    f.write_text(f"local_code,local_name,{header}\nUA,uric acid,x\n", encoding="utf-8")
    out = tmp_path / "s.json"
    assert own.main(["--table", f"lab:local-lab:{f}", "--out", str(out)]) == 2
    assert not out.exists()


def test_owner_refuses_an_identity_number_cell_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    value = _fictional_tw_id()
    f = tmp_path / "t.csv"
    f.write_text(f"local_code,local_name,note\nUA,uric acid,{value}\n", encoding="utf-8")
    out = tmp_path / "s.json"
    assert own.main(["--table", f"lab:local-lab:{f}", "--out", str(out)]) == 2
    err = capsys.readouterr().err
    assert "line 2" in err and value not in err
    assert not out.exists()


def test_owner_refuses_a_table_of_events(tmp_path: Path) -> None:
    f = tmp_path / "t.csv"
    f.write_text("local_code,local_name\n" + "UA,uric acid\n" * 10, encoding="utf-8")
    assert own.main(["--table", f"lab:local-lab:{f}", "--out", str(tmp_path / "s.json")]) == 2


def test_owner_refuses_a_system_of_another_kind(tmp_path: Path) -> None:
    f = tmp_path / "t.csv"
    f.write_text("local_code,local_name\nUA,uric acid\n", encoding="utf-8")
    assert own.main(["--table", f"drug:local-lab:{f}", "--out", str(tmp_path / "s.json")]) == 2


def test_owner_summary_holds_counts_and_names_only(tmp_path: Path) -> None:
    """Big5 and Shift_JIS dictionaries with their own headers; the summary names no path and no other column."""
    (tmp_path / "lab.tsv").write_bytes(
        "檢驗代碼\t檢驗名稱\t單位\nUA\t尿酸\tmg/dL\nZZ9\t院內特殊檢驗\tmg/dL\n".encode("cp950")
    )
    (tmp_path / "dx.csv").write_bytes("病名コード,病名\nZB26,痛風\nZB99,架空病名\n".encode("cp932"))
    cfg = {
        "tables": [
            {"kind": "lab", "system": "local-lab", "file": "lab.tsv", "code": "檢驗代碼", "name": "檢驗名稱"},
            {"kind": "diagnosis", "system": "medis", "file": "dx.csv", "code": "病名コード", "name": "病名"},
        ]
    }
    (tmp_path / "tables.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "summary.json"
    assert own.main(["--config", str(tmp_path / "tables.json"), "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    s = json.loads(text)
    assert s["codes"] == 4 and s["mapped"] == 2
    assert {u["local_code"]: u["local_name"] for u in s["unmapped"]} == {"ZZ9": "院內特殊檢驗", "ZB99": "架空病名"}
    assert str(tmp_path) not in text and "mg/dL" not in text and "lab.tsv" not in text


def test_who_icd10_reaches_icd10cm_through_the_table(tmp_path: Path) -> None:
    """SDR2 part 1: a WHO code ICD-10-CM lacks maps through the WHO-to-CM table; one with no row stays listed."""
    table = tmp_path / "who_to_cm.csv"
    table.write_text(
        "who,icd10cm,relation,source,verified\nE14.9,E11.9,wider,synthetic test row,verify\n", encoding="utf-8"
    )
    ref = mc.Reference.load(who_icd10cm=table)
    rows = _rows(("E149", "糖尿病", "icd-10"), ("I64", "脳卒中", "icd-10"), ("E11.9", "2型糖尿病", "icd-10"))
    res = {r.local_code: r for r in (mc.check_code(x, ref) for x in rows)}
    assert res["E149"].mapped and res["E149"].target_code == "E11.9"
    assert res["E149"].route == "who-icd10 + WHO-to-CM table"
    assert res["E11.9"].route == "who-icd10"
    assert not res["I64"].mapped and "no row in the WHO-to-CM table" in res["I64"].reason
    report = mc.coverage(rows, ref)
    assert [u["local_code"] for u in report["unmapped"]] == ["I64"]
