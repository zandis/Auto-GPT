"""The mapping check on code lists (tools.mapping_coverage) and its owner-machine wrapper (tools.owner_code_dictionaries).

Synthetic lists only: the shipped synthetic hospitals' codes, and codes written here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    rows = _rows(
        ("e119", "2型糖尿病", "icd-10"), ("F00.1", "アルツハイマー型認知症", "icd-10"), ("E14.9", "糖尿病", "icd-10")
    )
    res = {r.local_code: r for r in (mc.check_code(x, ref) for x in rows)}
    assert res["e119"].mapped and res["e119"].target_code == "E11.9" and not res["e119"].unverified
    assert res["F00.1"].mapped and res["F00.1"].target_code == "G30.9" and res["F00.1"].unverified
    # E14 has no row: ICD-10-CM has no code holding all of "diabetes, type not stated" (D-1270)
    assert not res["E14.9"].mapped and "no row in the WHO-to-CM table" in res["E14.9"].reason
    report = mc.coverage(rows, ref)
    assert report["by_domain"]["diagnosis"]["applied_not_verified"] == 1
    assert [u["local_code"] for u in report["unmapped"]] == ["E14.9"]
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
        assert r["relation"] == "wider", r  # the ICD-10-CM code holds all of the WHO code's meaning (D-173's sense)
        assert r["source"].startswith(("ICD-10-CM Alphabetic Index", "ICD-10-CM Tabular List")), r
        assert r["verified"] == "verify", r
    # a target that would assert more than the WHO code says has no row (D-1270): diabetes type, infarction
    assert not {r["who"] for r in rows} & {"E14", "E14.9", "I64"}


def test_ssmix2_reader_takes_the_table_and_counts_the_rest(tmp_path: Path) -> None:
    """The reader (lane B2's file, body only): same code, table code, or empty and counted in ``missed``."""
    from adapter.sources.ssmix2.source import Ssmix2Source

    src = Ssmix2Source(tmp_path, licensed={})
    assert src._icd_columns("E11.9") == {"icd10": "E11.9", "icd10cm": "E11.9"}
    assert src._icd_columns("F00.1") == {"icd10": "F00.1", "icd10cm": "G30.9"}
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


def test_a_night_marks_a_diagnosis_that_rests_on_an_unverified_who_row(tmp_path: Path, pg_cluster_url: str) -> None:
    """SDR2 part 1 through a whole SS-MIX2 night (adapter.pipeline, body only): F00.1 is given G30.9 from the table
    and carries D-135's ``verify`` basis tag; E11.9 itself (the same code) carries none; a WHO code with no row keeps
    no ICD-10-CM coding and is on the night's unmapped list."""
    import os

    from adapter.mapping.engine import BASIS, VERIFY_BASIS
    from adapter.ndjson import snapshot_dir
    from adapter.pipeline import AdapterConfig, run_ingest
    from adapter.sources.ssmix2.source import storage_dir
    from tb_contracts import RebuildResult

    class _Rebuild:
        def __call__(self, snap: str, nd: Path) -> RebuildResult:
            return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)

    root = tmp_path / "ss"
    for n, who in enumerate(("F00.1", "E11.9", "F01.8")):
        d = storage_dir(root, "10000001", "20260101", "PPR-01")
        d.mkdir(parents=True, exist_ok=True)
        msh = f"MSH|^~\\&|HIS||TB||20261101||PPR^ZD1|D{n}|P|2.5"
        prb = f"PRB|AD|20260101|^病名^99XYZ^{who}^^I10|D{n}||||||||||A||20260101"
        text = "\r".join([msh, "PID|||10000001^^^^PI", "PV1||O", prb]) + "\r"
        (d / f"10000001_20260101_PPR-01_D{n}_20261101000000000_01_1").write_bytes(text.encode("utf-8"))
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    sep = "&" if "?" in pg_cluster_url else "?"
    cfg = AdapterConfig(
        lake_dir=tmp_path / "lake",
        secrets_dir=sec,
        mapping_path=mc.MAPPING / "jp_core" / "ssmix2_site.yaml",
        site_id="T",
        tz="Asia/Tokyo",
        rebuild=_Rebuild(),
        audit_dir=tmp_path / "audit",
        db_url=f"{pg_cluster_url}{sep}tb_prefix=sdr{os.getpid()}_",
    )
    rep = run_ingest(cfg, "ssmix2", str(root), snapshot="2026-11-01", load_fhir=False, validate=False)
    assert rep.passed
    nd = snapshot_dir(tmp_path / "lake", "2026-11-01")
    conds = [json.loads(x) for x in (nd / "Condition.ndjson").read_text(encoding="utf-8").splitlines()]
    by_who = {
        next(c["code"] for c in r["code"]["coding"] if c["system"] == "http://hl7.org/fhir/sid/icd-10"): r
        for r in conds
    }
    verify = {"system": BASIS, "code": VERIFY_BASIS}

    def cm(r: dict[str, Any]) -> list[str]:
        return [c["code"] for c in r["code"]["coding"] if c["system"] == mc.TARGETS["icd-10-cm"]]

    assert cm(by_who["F00.1"]) == ["G30.9"] and verify in by_who["F00.1"]["meta"]["tag"]
    assert cm(by_who["E11.9"]) == ["E11.9"] and verify not in by_who["E11.9"]["meta"]["tag"]
    assert cm(by_who["F01.8"]) == []
    reader = json.loads((nd / "reader.json").read_text(encoding="utf-8"))
    assert reader["unmapped"]["diagnosis"] == [{"code": "F01.8", "count": 1}]


@pytest.mark.parametrize(
    ("ruleset", "crit_id", "cm_reads"),
    [("GZQO", "GZQO-EXC-01", False), ("GOUT-COH", "GOUT-COH-INC-07", True)],
)
def test_e14_stays_unknown_on_the_shipped_diabetes_criteria_never_false(
    tmp_path: Path, ruleset: str, crit_id: str, cm_reads: bool
) -> None:
    """D-1270's guard (ruling on #639 7103442261): E14.9 has no WHO-to-CM row, so the reader gives it no ICD-10-CM
    code, and the shipped criterion (its own IR and value sets, compiled) reads it unknown, never false: neither the
    type 1 exclusion (GZQO-EXC-01) nor the type 2 inclusion (GOUT-COH-INC-07). An E11.9 record decides both."""
    from datetime import date

    import duckdb
    from adapter.sources.ssmix2.source import Ssmix2Source
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets
    from tb_contracts import CriterionIR

    assert Ssmix2Source(tmp_path, licensed={})._icd_columns("E14.9") == {"icd10": "E14.9", "icd10cm": ""}
    base = mc.RULESETS / ruleset
    crit = CriterionIR.model_validate(json.loads((base / "ir" / f"{crit_id}.json").read_text(encoding="utf-8")))
    by_name = {
        vs["name"]: vs
        for vs in (json.loads(f.read_text(encoding="utf-8")) for f in sorted((base / "valuesets").glob("*.json")))
    }
    sql = SqlGenerator(ruleset, "1.0.0", ValueSets(ruleset, by_name, Terminology())).render([crit])
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)"
    )
    con.execute(
        "CREATE TABLE condition (pid VARCHAR, cid VARCHAR, system VARCHAR, code VARCHAR, onset DATE, recorded DATE)"
    )
    who = "http://hl7.org/fhir/sid/icd-10"
    pts = {"who_e14": (who, "E14.9"), "cm_e11": (mc.TARGETS["icd-10-cm"], "E11.9")}
    for i, (pid, (sy, code)) in enumerate(pts.items()):
        con.execute("INSERT INTO patient VALUES (?, DATE '1960-01-01', 'male', NULL, NULL)", [pid])
        con.execute("INSERT INTO condition VALUES (?, ?, ?, ?, DATE '2025-01-01', NULL)", [pid, f"c{i}", sy, code])
    rows = con.execute(sql, [[date(2026, 1, 1).isoformat()], list(pts)]).fetchall()
    cols = [d[0] for d in con.description]
    got = {dict(zip(cols, r, strict=True))["pid"]: dict(zip(cols, r, strict=True))[f"C_{crit_id}"] for r in rows}
    assert got["who_e14"] is None  # unknown, never false
    assert got["cm_e11"] is cm_reads


# --- SDR2 part 2: departments ----------------------------------------------------------------------------------


def test_hospital_departments_reach_trialbox_codes_only_through_the_table(tmp_path: Path) -> None:
    """A hospital's own department code maps through the department table (the shipped one holds TrialBox's codes
    only; a site's table maps its own); a code with no row is listed with its reason."""
    shipped = mc.Reference.load()
    rows = _rows(("RHEU", "風濕免疫科", "local-department"), ("IM01", "內科", "local-department"))
    res = {r.local_code: r for r in (mc.check_code(x, shipped) for x in rows)}
    assert res["RHEU"].mapped and res["RHEU"].route == "department-table"
    assert not res["IM01"].mapped and res["IM01"].reason == "not in the department-table table"
    shown = mc.render(mc.coverage(rows, shipped))
    assert "department table: none (TrialBox's own codes only); 1 reach no TrialBox department code" in shown
    site = tmp_path / "dept.csv"
    site.write_text("dept_code,code,verified\nIM01,META,verify\n", encoding="utf-8")
    ref = mc.Reference.load(department_table=site)
    hit = mc.check_code(rows[1], ref)
    assert hit.mapped and hit.target_code == "META"
    report = mc.coverage(rows, ref)
    assert report["by_domain"]["department"]["unmapped"] == 1  # RHEU is not in the site's own table
    assert "GZQO/VS_RHEUMATOLOGY_OR_METABOLISM_CLINIC_VISIT" not in report["valuesets_not_reached"]


def test_the_mapping_writes_the_tables_trialbox_code_and_keeps_a_code_with_no_row(tmp_path: Path) -> None:
    """demo_his.yaml (lane B2's file, the go on #639 7102870311): the encounter's department coding is the table's
    TrialBox code where the site's department table has a row, else the hospital's code as written (as before)."""
    import shutil

    from adapter.mapping.engine import Mapper, Mapping

    site = tmp_path / "site.yaml"
    site.write_text(
        "version: 1\nextends: "
        + str(mc.MAPPING / "tw_core" / "demo_his.yaml")
        + "\nname: t\ntables:\n  encounter: {source: encounter, key: enc_no}\n"
        + "lookups:\n  department: {file: dept.csv, key: dept_code}\n",
        encoding="utf-8",
    )
    shutil.copy(mc.DEPT_TABLE, tmp_path / "dept.csv")
    with (tmp_path / "dept.csv").open("a", encoding="utf-8") as fh:
        fh.write("IM01,META,verify\n")
    mapper = Mapper(Mapping.load(site), b"k" * 32, "T")
    row = {"mrn": "M1", "visit_datetime": "2026-01-01 09:00", "staff_id": "S1", "enc_type": "OPD"}
    got = {}
    for code in ("IM01", "RHEU", "XX99"):
        res = mapper.map_table("encounter", iter([{**row, "enc_no": f"E-{code}", "dept_code": code}]))
        enc = next(r for r in res if r["resourceType"] == "Encounter")
        got[code] = enc["serviceType"]["coding"]
    dept = mc.TARGETS["department"]
    assert got["IM01"] == [{"system": dept, "code": "META"}]
    assert got["RHEU"] == [{"system": dept, "code": "RHEU"}]
    assert got["XX99"] == [{"system": dept, "code": "XX99"}]  # no row: the hospital's code, as before SDR2


def test_a_profile_department_table_maps_the_sites_codes_and_tags_its_verify_rows(tmp_path: Path) -> None:
    """A site profile's ``used_by: [mapping.department]`` table (libs/tb_common/site_profile.py: the department
    system, go on #639 7104597751) loads, passes the mapping check, and replaces the mapping's department look-up;
    a code from a ``verify`` row carries D-135's basis tag."""
    import yaml
    from adapter import site_profile as sp
    from adapter.mapping.engine import BASIS, VERIFY_BASIS, Mapper, Mapping
    from tb_common.site_profile import load

    folder = tmp_path / "profile"
    (folder / "codes").mkdir(parents=True)
    (folder / "codes" / "department.csv").write_text(
        "dept_code,code,state\nIM01,META,verify\nRA02,RHEU,verified\n", encoding="utf-8"
    )
    manifest = {
        "format": "tb-site-profile/1",
        "id": "test-site",
        "site_id": "T",
        "country": "tw",
        "version": "1.0.0",
        "door": "csv",
        "standards": {"tw_core": "1.0.0"},
        "data_types": ["encounter"],
        "tables": {
            "department": {
                "file": "codes/department.csv",
                "key": "dept_code",
                "target": "code",
                "state": "state",
                "source": "a synthetic test table",
                "used_by": ["mapping.department"],
            }
        },
    }
    (folder / "profile.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    profile = load(folder)
    base = mc.MAPPING / "tw_core" / "demo_his.yaml"
    sp.check_mapping(profile, Mapping.load(base))
    files = sp.write_tables(profile, tmp_path / "tables")
    mapping = Mapping.load(base, {"department": files["mapping.department"]})
    sp.mark_unverified(profile, mapping)
    mapper = Mapper(mapping, b"k" * 32, "T")
    row = {"mrn": "M1", "visit_datetime": "2026-01-01 09:00", "staff_id": "S1", "enc_type": "OPD"}
    verify = {"system": BASIS, "code": VERIFY_BASIS}
    out = {}
    for code in ("IM01", "RA02"):
        res = mapper.map_table("encounter", iter([{**row, "enc_no": f"E-{code}", "dept_code": code}]))
        out[code] = next(r for r in res if r["resourceType"] == "Encounter")
    assert out["IM01"]["serviceType"]["coding"][0]["code"] == "META"
    assert verify in out["IM01"]["meta"]["tag"]
    assert out["RA02"]["serviceType"]["coding"][0]["code"] == "RHEU"
    assert verify not in (out["RA02"].get("meta") or {}).get("tag", [])


def test_a_site_with_no_department_table_reads_exactly_as_before(tmp_path: Path) -> None:
    """The go's own test (#639 7104597751): the synthetic Taiwan site's visits and bookings, mapped with the
    department look-up and with master's mapping before SDR2, give the same resources byte for byte."""
    import shutil

    from adapter.mapping.engine import Mapper, Mapping

    before = tmp_path / "before"
    before.mkdir()
    text = (mc.MAPPING / "tw_core" / "demo_his.yaml").read_text(encoding="utf-8")
    # master's lines before SDR2: no department look-up, and line 124 as it was
    lookup = text[text.index("  # SDR2 (lane M): the hospital's department code") : text.index("static:")]
    new_124 = text[text.index("      # SDR2 (lane M): the department table") : text.index("      # TW Core slice")]
    assert text.count(lookup) == 1 and new_124.count("serviceType.coding[0]") == 3
    old_124 = "      serviceType.coding[0]: {builder: coding, column: dept_code, system: department}\n"
    (before / "demo_his.yaml").write_text(text.replace(lookup, "").replace(new_124, old_124), encoding="utf-8")
    shutil.copy(mc.MAPPING / "tw_core" / "lab_local_to_loinc.csv", before / "lab_local_to_loinc.csv")
    site = mc.ROOT / "tests/fixtures/synthetic_patients/site-a"
    import csv as _csv

    def mapped(path: Path) -> list[str]:
        mapper = Mapper(Mapping.load(path), b"k" * 32, "T")
        out: list[str] = []
        for table in ("encounter", "appointment"):
            rows = list(_csv.DictReader((site / f"{table}.csv").open(encoding="utf-8")))
            assert rows, table
            out += [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in mapper.map_table(table, iter(rows))]
        return out

    copied = tmp_path / "copied"  # a site that copied the base mapping and its lab table, not the department table
    copied.mkdir()
    shutil.copy(mc.MAPPING / "tw_core" / "demo_his.yaml", copied / "demo_his.yaml")
    shutil.copy(mc.MAPPING / "tw_core" / "lab_local_to_loinc.csv", copied / "lab_local_to_loinc.csv")
    then = mapped(before / "demo_his.yaml")
    assert len(then) > 100
    assert mapped(mc.MAPPING / "tw_core" / "demo_his.yaml") == then
    assert mapped(copied / "demo_his.yaml") == then  # the optional look-up loads empty: the codes as written


def test_a_look_up_that_is_not_optional_still_stops_the_load_when_its_file_is_missing(tmp_path: Path) -> None:
    """The go's second test (#639 7105055050): only ``optional: true`` loads empty; the lab look-up's file missing
    still stops the mapping from loading."""
    import shutil

    from adapter.mapping.engine import Mapping

    shutil.copy(mc.MAPPING / "tw_core" / "demo_his.yaml", tmp_path / "demo_his.yaml")
    with pytest.raises((FileNotFoundError, OSError)):
        Mapping.load(tmp_path / "demo_his.yaml")


# --- SDR2 part 3: OMG-11/12 into procedure --------------------------------------------------------------------


def _omg(root: Path, number: str, typ: str, orc1: str = "SC", ze1: str = "1^実施^JSHR003", stamp: str = "1") -> None:
    from adapter.sources.ssmix2.source import storage_dir

    d = storage_dir(root, "10000001", "20260105", typ)
    d.mkdir(parents=True, exist_ok=True)
    segs = [
        f"MSH|^~\\&|HIS||TB||20260105110000||OMI^Z23^OMI_Z23|H{number}|P|2.5",
        "PID|||10000001^^^^PI",
        "PV1||O",
        f"ORC|{orc1}|{number}|||||||20260104090000",
        "TQ1|1||||||||R^^HL70485",
        f"OBR|1|{number}||R0001^胸部単純X線撮影^JJ1017-16M|||20260105110000",
        f"ZE1|1|{ze1}|R0001^胸部単純X線撮影^JJ1017-16M",
        f"IPC|{number}||2.25.1||CR^^DCM",
    ]
    name = f"10000001_20260105_{typ}_{number}_2026010511000000{stamp}_01_1"
    (d / name).write_bytes(("\r".join(segs) + "\r").encode("utf-8"))


def test_ssmix2_reads_a_done_examination_into_procedure_and_keeps_the_extended_csv(tmp_path: Path) -> None:
    """OMG-11/12 (go on #639 7104711754): ORC-1 SC and ZE1-2 実施 is a done procedure (OBR-4, OBR-7); an order not done
    (ORC-1 not SC, or ZE1-2 not 実施) is not read as one; the extended CSV's procedures are still read."""
    from adapter.sources.ssmix2.source import Ssmix2Source

    root = tmp_path / "ss"
    _omg(root, "G1", "OMG-11")
    _omg(root, "G2", "OMG-12")
    _omg(root, "G3", "OMG-11", orc1="NW")
    _omg(root, "G4", "OMG-11", ze1="2^中止^JSHR003")
    ext = root / "extended"
    ext.mkdir()
    (ext / "procedure.csv").write_text(
        "proc_no,mrn,order_code,proc_name,proc_date,order_code_system\n"
        "X1,10000001,K656-2,腹腔鏡下胃縮小術,2025-06-01,JP-K\n",
        encoding="utf-8",
    )
    src = Ssmix2Source(root, licensed={})
    rows = {r["proc_no"]: r for r in src.rows("procedure", "procedure", None, None)}
    assert set(rows) == {"G1", "G2", "X1"}  # G3 (ordered, not done) and G4 (ZE1-2 中止) are not procedures
    g1 = rows["G1"]
    assert (g1["order_code"], g1["order_code_system"], g1["proc_date"], g1["status"]) == (
        "R0001",
        "JJ1017-16M",
        "2026-01-05",
        "completed",
    )
    assert rows["X1"]["order_code_system"] == "JP-K"
    assert src.stats["OMG-11:not done (not read as a procedure)"] == 2


def test_a_japanese_procedure_is_never_an_nhi_order_code_and_taiwan_reads_as_before() -> None:
    """The JP overlay writes JJ1017, a K code or the hospital's own system, never ``nhi_order``; the TW mapping
    ignores ``order_code_system``: a Taiwan row with or without it maps byte for byte as before."""
    import csv as _csv

    from adapter.mapping.engine import Mapper, Mapping

    nhi = "https://trialbox.local/fhir/CodeSystem/nhi-order"
    jp = Mapper(Mapping.load(mc.MAPPING / "jp_core" / "ssmix2_site.yaml"), b"k" * 32, "J")
    base = {"mrn": "M1", "order_code": "X1", "proc_name": "n", "proc_date": "2026-01-05"}
    for system in ("JJ1017-16M", "JP-K", "99HOS", ""):
        res = jp.map_table("procedure", iter([{**base, "proc_no": f"P{system}", "order_code_system": system}]))
        proc = next(r for r in res if r["resourceType"] == "Procedure")
        assert [c["system"] for c in proc["code"]["coding"]] != [] and nhi not in [
            c["system"] for c in proc["code"]["coding"]
        ]
    for status, want in (("completed", "completed"), ("unknown", "unknown"), ("", "completed"), ("odd", "unknown")):
        res = jp.map_table("procedure", iter([{**base, "proc_no": f"S{status}", "status": status}]))
        assert next(r for r in res if r["resourceType"] == "Procedure")["status"] == want
    tw = Mapper(Mapping.load(mc.MAPPING / "tw_core" / "demo_his.yaml"), b"k" * 32, "T")
    site = mc.ROOT / "tests/fixtures/synthetic_patients/site-a"
    rows = list(_csv.DictReader((site / "procedure.csv").open(encoding="utf-8")))
    assert rows
    plain = [json.dumps(r, sort_keys=True) for r in tw.map_table("procedure", iter(rows))]
    tagged = [{**r, "order_code_system": "JJ1017-16M", "status": "unknown"} for r in rows]
    assert [json.dumps(r, sort_keys=True) for r in tw.map_table("procedure", iter(tagged))] == plain
    assert all(nhi in s for s in plain if '"Procedure"' in s)


@pytest.mark.parametrize(("status", "want"), [("unknown", None), ("completed", True)])
def test_a_procedure_of_unknown_status_reads_unknown_never_true(status: str, want: bool | None) -> None:
    """The guard of ruling #639 7105496002 / 7105784808: the lake keeps a Procedure of status ``unknown`` undated
    (D-275's rule, ``lake.flatten``), so the shipped GZQO-EXC-05 (bariatric surgery, no window) reads it unknown,
    never true; a completed one decides it. The compiled SQL is the shipped one, unchanged."""
    from datetime import date

    import duckdb
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets
    from lake.flatten import Flattener
    from tb_contracts import CriterionIR

    proc = {
        "resourceType": "Procedure",
        "id": "p1",
        "status": status,
        "subject": {"reference": "Patient/pt"},
        "code": {"coding": [{"system": "https://trialbox.local/fhir/CodeSystem/nhi-order", "code": "75614B"}]},
        "performedDateTime": "2025-06-01",
    }
    row = Flattener("Asia/Tokyo").procedure(proc)
    assert (row["performed"] is None) is (status == "unknown")
    base = mc.RULESETS / "GZQO"
    crit = CriterionIR.model_validate(json.loads((base / "ir" / "GZQO-EXC-05.json").read_text(encoding="utf-8")))
    by_name = {
        vs["name"]: vs
        for vs in (json.loads(f.read_text(encoding="utf-8")) for f in sorted((base / "valuesets").glob("*.json")))
    }
    sql = SqlGenerator("GZQO", "1.0.0", ValueSets("GZQO", by_name, Terminology())).render([crit])
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)"
    )
    con.execute("CREATE TABLE procedure (prid VARCHAR, pid VARCHAR, code VARCHAR, system VARCHAR, performed DATE)")
    con.execute("INSERT INTO patient VALUES ('pt', DATE '1960-01-01', 'female', NULL, NULL)")
    con.execute(
        "INSERT INTO procedure VALUES (?, ?, ?, ?, ?)",
        [row["prid"], row["pid"], row["code"], row["system"], row["performed"]],
    )
    out = con.execute(sql, [[date(2026, 1, 1).isoformat()], ["pt"]]).fetchall()
    cols = [d[0] for d in con.description]
    assert dict(zip(cols, out[0], strict=True))["C_GZQO-EXC-05"] is want


def test_the_cql_reads_a_procedure_of_unknown_status_as_unknown_too() -> None:
    """The CQL side of the same guard (ruling #639 7105784808): GZQO-EXC-05 compiled from the shipped value sets,
    evaluated by the local CQL engine: a Procedure of status ``unknown`` gives null, a completed one true."""
    from datetime import date

    from criteria_compiler.compile_cql.generator import CqlGenerator, render_common
    from criteria_compiler.compile_cql.translator import Translator, available, fhirhelpers_source
    from criteria_compiler.terminology.mapper import Terminology, ValueSets
    from tb_common.fhir import FhirEvaluator, library_resource
    from tb_contracts import CriterionIR

    from tools import cql_eval

    if not (available() and cql_eval.available()):
        pytest.skip("CQL translator or local CQL engine not available (python -m tools.cql_eval --fetch)")
    base = mc.RULESETS / "GZQO"
    crit = CriterionIR.model_validate(json.loads((base / "ir" / "GZQO-EXC-05.json").read_text(encoding="utf-8")))
    vs_all = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((base / "valuesets").glob("*.json"))]
    gen = CqlGenerator("SDR", "1.0.0", ValueSets("SDR", {v["name"]: v for v in vs_all}, Terminology()))
    cql = gen.render([crit])
    tr = Translator().translate({"FHIRHelpers": fhirhelpers_source(), "TB_Common": render_common(), gen.library: cql})
    version = next(x for x in cql.splitlines() if x.startswith("library ")).split(" version ")[1].strip().strip("'")
    libs = [
        library_resource("TB_Common", "1.0.0", render_common(), tr.elm.get("TB_Common")),
        library_resource(gen.library, version, cql, tr.elm.get(gen.library)),
    ]
    lines: list[str] = []
    for pid, status in (("pu", "unknown"), ("pc", "completed")):
        lines.append(json.dumps({"resourceType": "Patient", "id": pid, "gender": "female", "birthDate": "1960-01-01"}))
        proc = {
            "resourceType": "Procedure",
            "id": f"x-{pid}",
            "status": status,
            "subject": {"reference": f"Patient/{pid}"},
            "code": {"coding": [{"system": "https://trialbox.local/fhir/CodeSystem/nhi-order", "code": "75614B"}]},
            "performedDateTime": "2025-06-01",
        }
        lines.append(json.dumps(proc))
    lines += [json.dumps(v) for v in vs_all] + [json.dumps(x) for x in libs]
    idx = date(2026, 1, 1)
    exprs = CqlGenerator.expression_names([crit])
    got = {}
    for body in cql_eval.run(lines, gen.library, version, idx, exprs, ["pu", "pc"]):
        pid = str(body.get("id"))
        got[pid] = FhirEvaluator.parse(pid, idx, body, exprs).results.get("GZQO-EXC-05")
    assert got == {"pu": None, "pc": True}
