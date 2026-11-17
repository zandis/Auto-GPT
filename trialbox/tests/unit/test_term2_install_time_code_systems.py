"""TERM-2 (D-1113 to D-1116): the code systems of D-1028 loaded at install by TERM-1's loader, each table with its
manifest line, refused without it or with other bytes; the site's own lists win over every other table; a licensed
system's line names the person who accepted its licence.

Every LOINC, WHO ICD-10 and ATC table here is SYNTHETIC: made-up codes and names written by this test (``SYNTHETIC``
in each name), shaped like the real files so the parsers are exercised. No licensed content is committed (D-1116).
The site lists are synthetic too (local codes ``ZZ...``). The NHI rows are the committed public samples of
``tests/fixtures/refdata`` (OGDL 1.0, row ``nhi-codes``)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from criteria_compiler.terminology import installed
from criteria_compiler.terminology.mapper import ICD10_WHO, LOADED_SYSTEMS, SYSTEMS, Terminology

from tools import terminology_coverage, terminology_install

ROOT = Path(__file__).resolve().parents[2]
REFDATA = ROOT / "tests/fixtures/refdata"
ICD = SYSTEMS["icd10cm"]

SITE_CSV = """local_code,local_name,system,code,display
ZZ-DX-0001,hypertension,icd10cm,I10,SYNTHETIC site row: essential hypertension only
ZZ-DX-0002,高血壓,icd10cm,I10,
ZZ-LAB-0001,SYNTHETIC glucose fasting,loinc,99990-1,
ZZ-DRUG-0001,SYNTHETIC tablet,nhi_drug,ZZ00000100,
"""
# LoincTable/Loinc.csv's columns (a few of them), every row made up
LOINC_CSV = """"LOINC_NUM","COMPONENT","PROPERTY","SYSTEM","SCALE_TYP","CLASS","STATUS","SHORTNAME","LONG_COMMON_NAME"
"99990-1","SYNTHETIC analyte","MCnc","Ser/Plas","Qn","CHEM","ACTIVE","SYN analyte SerPl","SYNTHETIC analyte [Mass/volume] in Serum or Plasma"
"99991-9","SYNTHETIC analyte","MCnc","Bld","Qn","CHEM","ACTIVE","SYN analyte Bld","SYNTHETIC analyte [Mass/volume] in Blood"
"99992-7","SYNTHETIC analyte","MCnc","Urine","Qn","CHEM","ACTIVE","SYN analyte Ur","SYNTHETIC analyte [Mass/volume] in Urine"
"99993-5","SYNTHETIC old analyte","MCnc","Ser","Qn","CHEM","DEPRECATED","SYN old","SYNTHETIC old analyte in Serum"
"""  # noqa: E501
# a ClaML file shaped like WHO's (an external DTD reference, a block, categories), every class made up
CLAML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ClaML SYSTEM "ClaML.dtd">
<ClaML version="2.0.0"><Title name="SYNTHETIC-ICD10" version="2099">SYNTHETIC</Title>
<Class code="U90-U99" kind="block"><Rubric kind="preferred"><Label>SYNTHETIC block of made-up disorders</Label></Rubric></Class>
<Class code="U98" kind="category"><Rubric kind="preferred"><Label>SYNTHETIC who only disorder</Label></Rubric></Class>
<Class code="U98.0" kind="category"><Rubric kind="preferred"><Label>SYNTHETIC who only disorder, first kind</Label></Rubric></Class>
<Class code="U98.9" kind="category"><Rubric kind="preferred"><Label>SYNTHETIC who only disorder, unspecified</Label></Rubric></Class>
</ClaML>"""  # noqa: E501
ATC_TSV = "ATC code\tATC level name\tDDD\tU\tAdm.R\tNote\n" + "\n".join([
    "Z\tSYNTHETIC anatomical group\t\t\t\t",
    "Z99\tSYNTHETIC therapeutic group\t\t\t\t",
    "Z99A\tSYNTHETIC pharmacological group\t\t\t\t",
    "Z99AA\tSYNTHETIC chemical group\t\t\t\t",
    "Z99AA01\tsynthetic substance a\t\t\t\t",
    "Z99AA02\tsynthetic substance b\t\t\t\t",
]) + "\n"  # fmt: skip
# CMS's order file layout (order, code, header flag, short and long description in fixed columns); made-up rows
PCS_ORDER = "\n".join([
    f"{1:05d} {'0Z1':<7} 0 {'SYNTHETIC table header':<60} SYNTHETIC table header",
    f"{2:05d} {'0Z1ZZZZ':<7} 1 {'SYNTHETIC bypass, short':<60} SYNTHETIC bypass procedure, open approach",
    f"{3:05d} {'0Z2ZZZZ':<7} 1 {'SYNTHETIC resection, short':<60} SYNTHETIC resection procedure",
]) + "\n"  # fmt: skip
NAME = "Ada Example (SYNTHETIC test person)"


def _write(tmp: Path, name: str, text: str, enc: str = "utf-8") -> Path:
    p = tmp / name
    p.write_text(text, encoding=enc)
    return p


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("term2")
    where = tmp / "terminology"
    assert installed.install_site_list(_write(tmp, "dx.csv", SITE_CSV), where, "dx") == {"site_dx": 4}
    assert installed.install_nhi_drugs(REFDATA / "nhi_drugs_sample.csv", where) == {"nhi_drug_list": 1}
    assert installed.install_nhi_services(REFDATA / "nhi_services_sample.csv", where)["nhi_service_list"] == 7
    z = tmp / "2099-icd-10-pcs-codes-file.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("icd10pcs_order_2099.txt", PCS_ORDER)
        f.writestr("icd10pcs_codes_2099.txt", "0Z1ZZZZ SYNTHETIC bypass procedure, open approach\n")
    assert installed.install_icd10pcs(z, where, "2099") == {"icd10pcs": 3}  # the order file is preferred
    lz = tmp / "Loinc_2.99.zip"
    with zipfile.ZipFile(lz, "w") as f:
        f.writestr("LoincTable/Loinc.csv", LOINC_CSV)
        f.writestr("AccessoryFiles/PartFile/Part.csv", "PartNumber\n")
    assert installed.install_loinc(lz, where, NAME, "2099-01-02") == {"loinc_table": 4}
    assert installed.install_icd10_who(_write(tmp, "icd102099en.xml", CLAML), where, NAME) == {"icd10_who": 4}
    assert installed.install_atc(_write(tmp, "atc.tsv", ATC_TSV), where, NAME, version="2099") == {"atc_index": 6}
    return where


@pytest.fixture(scope="module")
def term(loaded: Path) -> Terminology:
    t = Terminology(installed=loaded)
    assert not t.installed_problems, t.installed_problems
    return t


def _fams(r: object, system: str = ICD) -> set[str]:
    return {p for s, p in getattr(r, "families", []) if s == system}


# --------------------------------------------------------------------------------------------- the site's lists
def test_the_site_list_wins_over_every_shipped_table(term: Terminology, tmp_path: Path) -> None:
    shipped = Terminology(installed=tmp_path / "nothing").map("condition", "hypertension")
    assert {"I10", "I11", "I15"} <= _fams(shipped)  # without the list: ICD-10-CM's block I10-I1A (TERM-1)
    r = term.map("condition", "hypertension")
    assert r.method == "site" and not r.needs_review and r.notes == ["site list site_dx"]
    assert _fams(r) == {"I10"} and all(c.code.startswith("I10") for c in r.concepts)
    assert term.map("condition", "高血壓").method == "site"  # a local name in Chinese
    assert term.map("observation", "SYNTHETIC glucose fasting").concepts[0].code == "99990-1"
    assert term.site_codes[("icd10cm", "ZZ-DX-0001")].code == "I10"  # local code -> standard code


def test_a_site_list_only_answers_for_its_systems_domain(term: Terminology) -> None:
    assert term.map("medication", "hypertension").method != "site"


def test_two_site_lists_the_first_by_name_keeps_a_name(tmp_path: Path) -> None:
    where = tmp_path / "t"
    installed.install_site_list(_write(tmp_path, "a.tsv", "local_name\tcode\nhypertension\tI15\n"), where, "a",
                                system="icd10cm")  # fmt: skip
    installed.install_site_list(_write(tmp_path, "b.csv", "local_name,code\nhypertension,I10\n"), where, "b",
                                system="icd10cm")  # fmt: skip
    assert _fams(Terminology(installed=where).map("condition", "hypertension")) == {"I15"}


def test_a_big5_site_list_loads(tmp_path: Path) -> None:
    p = _write(tmp_path, "big5.csv", "local_code,local_name,system,code\nZZ1,糖尿病,icd10cm,E11\n", enc="cp950")
    installed.install_site_list(p, tmp_path / "t", "big5")
    assert Terminology(installed=tmp_path / "t").map("condition", "糖尿病").method == "site"


@pytest.mark.parametrize(("text", "word"), [
    ("local_code,local_name,system,code\nZZ1,x,snomed,123\n", "system 'snomed' is not one of"),
    ("local_code,local_name,system,code\nZZ1,x,icd10cm,\n", "needs a code"),
    ("name,code\nx,I10\n", "no column local_code or local_name"),
])  # fmt: skip
def test_a_site_list_the_loader_cannot_place_is_refused_whole(tmp_path: Path, text: str, word: str) -> None:
    with pytest.raises(ValueError, match=word):
        installed.install_site_list(_write(tmp_path, "x.csv", text), tmp_path / "t", "x")
    assert not (tmp_path / "t" / "manifest.json").exists()


# ------------------------------------------------------------------------------------------------ NHI open data
def test_the_nhi_lists_load_with_their_attribution(loaded: Path, term: Terminology) -> None:
    lines = installed.manifest(loaded)["tables"]
    for t in ("nhi_drug_list", "nhi_service_list"):
        assert "Open Government Data License" in lines[t]["licence"] and "data.gov.tw" in lines[t]["attribution"]
    r = term.map("medication", "flupentixol")  # the drug list's 成分, without salt or strength, to its ATC column
    assert r.method == "loaded" and r.needs_review and [c.code for c in r.concepts] == ["N05AF01"]
    assert r.concepts[0].system == SYSTEMS["atc"]
    h = term.map("procedure", "hemodialysis")
    assert h.method == "loaded" and [(c.system, c.code) for c in h.concepts] == [(SYSTEMS["nhi_order"], "58001C")]
    assert term.map("procedure", "總膽固醇").concepts[0].code == "09001C"


# --------------------------------------------------------------------------------------------------- ICD-10-PCS
def test_icd10pcs_loads_from_the_order_or_the_codes_file(term: Terminology, tmp_path: Path) -> None:
    r = term.map("procedure", "SYNTHETIC resection procedure")
    assert r.method == "loaded" and not r.needs_review
    assert [(c.system, c.code) for c in r.concepts] == [(LOADED_SYSTEMS["icd10pcs"], "0Z2ZZZZ")]
    assert term.map("procedure", "SYNTHETIC table header").method == "none"  # a header is not a code
    codes = _write(tmp_path, "icd10pcs_codes_2099.txt", "0Z1ZZZZ SYNTHETIC bypass procedure, open approach\n")
    assert installed.install_icd10pcs(codes, tmp_path / "t", "2099") == {"icd10pcs": 1}
    with pytest.raises(ValueError, match="not a line of CMS"):
        installed.install_icd10pcs(_write(tmp_path, "bad.txt", "hello world\n"), tmp_path / "u", "2099")


# ----------------------------------------------------------------------------------- LOINC, WHO ICD-10 and ATC
def test_a_licensed_system_names_who_accepted_its_licence(loaded: Path) -> None:
    lines = installed.manifest(loaded)["tables"]
    for t in ("loinc_table", "icd10_who", "atc_index"):
        assert lines[t]["licence_accepted_by"] == NAME and len(lines[t]["sha256"]) == 64
        assert lines[t]["licence"] == installed.LICENSED[t]
    assert lines["loinc_table"]["licence_accepted_on"] == "2099-01-02" and lines["loinc_table"]["version"] == "LOINC 2.99"
    assert lines["icd10_who"]["version"] == "WHO ICD-10 2099" and lines["atc_index"]["version"] == "ATC 2099"
    assert "site_dx" in lines and "licence_accepted_by" not in lines["site_dx"]


@pytest.mark.parametrize("who", ["", "  ", "yes", "IT", "admin", "123"])
def test_a_licensed_system_without_a_named_person_is_not_loaded(tmp_path: Path, who: str) -> None:
    p = _write(tmp_path, "Loinc.csv", LOINC_CSV)
    with pytest.raises(ValueError, match="must name the person"):
        installed.install_loinc(p, tmp_path / "t", who, version="2.99")
    assert not (tmp_path / "t").exists()


def test_a_licensed_table_whose_line_lost_its_name_is_refused(loaded: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    for p in loaded.iterdir():
        (copy / p.name).write_bytes(p.read_bytes())
    data = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    del data["tables"]["loinc_table"]["licence_accepted_by"]
    (copy / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    t = Terminology(installed=copy)
    assert any("names nobody who accepted its licence" in p for p in t.installed_problems)
    assert "loinc_table" not in t.loaded_sources and t.map("observation", "SYNTHETIC analyte").method == "none"
    (copy / "atc_index.parquet").write_bytes(b"changed")  # other bytes: refused, as TERM-1's tables
    assert any("sha256 differs" in p for p in Terminology(installed=copy).installed_problems)
    assert {s.name for s in installed.status(copy) if s.problem} == {"loinc_table", "atc_index"}


def test_loinc_names_and_components(term: Terminology) -> None:
    r = term.map("observation", "SYNTHETIC analyte [Mass/volume] in Serum or Plasma")
    assert r.method == "loaded" and not r.needs_review and [c.code for c in r.concepts] == ["99990-1"]
    assert term.map("observation", "SYN analyte Bld").concepts[0].code == "99991-9"  # the short name
    comp = term.map("observation", "SYNTHETIC analyte")  # a component: its blood, serum and plasma codes, reviewed
    assert comp.needs_review and {c.code for c in comp.concepts} == {"99990-1", "99991-9"}
    assert term.map("observation", "SYNTHETIC old analyte in Serum").method == "none"  # deprecated


def test_who_icd10_answers_a_condition_icd10cm_does_not_know(term: Terminology) -> None:
    r = term.map("condition", "SYNTHETIC who only disorder")
    assert r.method == "loaded" and _fams(r, ICD10_WHO) == {"U98"}
    assert {c.code for c in r.concepts} == {"U98", "U98.0", "U98.9"} and r.concepts[0].system == ICD10_WHO
    assert term.map("condition", "ischemic heart disease").method == "icd10cm"  # ICD-10-CM answers first


@pytest.mark.parametrize("bad", ['<!DOCTYPE x [<!ENTITY e "boom">]><ClaML/>', "<!DOCTYPE x [<!ELEMENT a ANY>]><ClaML/>"])
def test_a_claml_with_an_entity_or_an_internal_dtd_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="refused"):
        installed.install_icd10_who(_write(tmp_path, "w.xml", bad), tmp_path / "t", NAME, version="x")


def test_atc_names_and_groups(term: Terminology, tmp_path: Path) -> None:
    a = term.map("medication", "synthetic substance a")
    assert a.method == "loaded" and not a.needs_review and [c.code for c in a.concepts] == ["Z99AA01"]
    g = term.map("medication", "SYNTHETIC chemical group")
    assert {c.code for c in g.concepts} == {"Z99AA01", "Z99AA02"} and _fams(g, SYSTEMS["atc"]) == {"Z99AA"}
    with pytest.raises(ValueError, match="--version"):
        installed.install_atc(_write(tmp_path, "a.tsv", ATC_TSV), tmp_path / "t", NAME)
    with pytest.raises(ValueError, match="not an ATC code"):
        installed.install_atc(_write(tmp_path, "b.csv", "code,name\nnot-atc,x\n"), tmp_path / "t", NAME, version="1")


# ------------------------------------------------------------------------------------------ nothing loaded, doctor
def test_with_nothing_loaded_nothing_changes(tmp_path: Path) -> None:
    t = Terminology(installed=tmp_path / "nothing")
    assert not t.site_names and not t.loaded_names and not t.loaded_sources and not t.installed_problems
    assert installed.not_loaded(tmp_path / "nothing") == [label for label, _ in installed.AT_INSTALL]


def test_doctor_names_each_system_and_who_accepted(loaded: Path, tmp_path: Path) -> None:
    from tools.trialbox import doctor

    ok = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(loaded)}))
    assert ok.status == "PASS" and "not loaded" not in ok.detail
    assert f"loinc_table 4 rows (LOINC 2.99), licence accepted by {NAME} on 2099-01-02" in ok.detail
    assert "site_dx 4 rows" in ok.detail and "icd10pcs 3 rows (ICD-10-PCS 2099)" in ok.detail
    none = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(tmp_path / "e")}))
    assert none.status == "PASS" and none.detail.endswith(
        "not loaded: site lists, NHI drug list, NHI service codes, ICD-10-PCS, LOINC, WHO ICD-10, ATC")


def test_the_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    where = tmp_path / "t"
    site = _write(tmp_path, "s.csv", SITE_CSV)
    assert terminology_install.main(["site-list", str(site), "--name", "dx", "--dir", str(where)]) == 0
    loinc = _write(tmp_path, "Loinc.csv", LOINC_CSV)
    assert terminology_install.main(["loinc", str(loinc), "--accepted-by", "yes", "--version", "2.99",
                                     "--dir", str(where)]) == 2  # fmt: skip
    assert "must name the person" in capsys.readouterr().err
    assert terminology_install.main(["loinc", str(loinc), "--accepted-by", NAME, "--version", "2.99",
                                     "--dir", str(where)]) == 0  # fmt: skip
    assert terminology_install.main(["status", "--dir", str(where)]) == 0
    out = capsys.readouterr().out
    assert f"loinc_table: 4 rows, 2.99, licence accepted by {NAME}" in out and "site_dx: 4 rows" in out


# ------------------------------------------------------------------------------------------- the measurement tool
def test_the_coverage_tool_counts_by_domain(loaded: Path) -> None:
    def call(cands: list[dict[str, object]]) -> dict[str, object]:
        out = {"criteria": [{"concept_candidates": cands}]}
        return {"attributes": {"tb.role": "extract_criteria"}, "output": json.dumps(out)}

    traces = {"traces": [
        call([{"domain": "condition", "name": "hypertension"}, {"domain": "demographic", "name": "age"}]),
        call([{"domain": "medication", "name": "synthetic substance a"},
              {"domain": "procedure", "name": "SYNTHETIC unknown"}]),
        {"attributes": {"tb.role": "screen"}, "output": "{}"},
        {"attributes": {"tb.role": "extract_criteria"}, "output": "not json"},
    ]}  # fmt: skip
    got = terminology_coverage.measure(traces, Terminology(installed=loaded))
    assert got["calls"] == 3 and got["candidates"] == 4
    assert got["by_domain"] == {"condition": [1, 1], "medication": [1, 1], "procedure": [1, 0]}
    assert got["methods"] == {"site": 1, "loaded": 1} and got["unmapped"] == {"procedure": {"synthetic unknown": 1}}
    assert "| **all** | **3** | **2 (66.7 %)** |" in terminology_coverage.table(got)
