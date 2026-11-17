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
"""
# a ClaML file shaped like WHO's (an external DTD reference, a block, categories), every class made up
CLAML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ClaML SYSTEM "ClaML.dtd">
<ClaML version="2.0.0"><Title name="SYNTHETIC-ICD10" version="2099">SYNTHETIC</Title>
<Class code="XXII" kind="chapter"><Rubric kind="preferred"><Label>SYNTHETIC chapter</Label></Rubric></Class>
<Class code="U90-U99" kind="block"><Rubric kind="preferred"><Label>SYNTHETIC block of made-up disorders</Label></Rubric></Class>
<Class code="U98" kind="category"><Rubric kind="preferred"><Label>SYNTHETIC who only disorder</Label></Rubric></Class>
<Class code="U98.0" kind="category"><Rubric kind="preferred"><Label>SYNTHETIC who only disorder, first kind</Label></Rubric></Class>
<Class code="U98.9" kind="category"><Rubric kind="preferred"><Label>SYNTHETIC who only disorder, unspecified</Label></Rubric></Class>
</ClaML>"""
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


def test_two_site_lists_that_disagree_go_to_a_person(tmp_path: Path) -> None:
    """TERM-2 review: the first list (by name) still answers, but no longer silently: two of the site's own lists that
    give one name different codes are for review, and the note names both (this corrects the earlier expectation)."""
    where = tmp_path / "t"
    installed.install_site_list(_write(tmp_path, "a.tsv", "local_name\tcode\nhypertension\tI15\n"), where, "a",
                                system="icd10cm")  # fmt: skip
    installed.install_site_list(_write(tmp_path, "b.csv", "local_name,code\nhypertension,I10\n"), where, "b",
                                system="icd10cm")  # fmt: skip
    r = Terminology(installed=where).map("condition", "hypertension")
    assert _fams(r) == {"I15"} and r.method == "site" and r.needs_review
    assert "lists site_a, site_b give this name different codes" in r.notes
    other = tmp_path / "u"
    for n in ("a", "c"):  # two lists that agree are no conflict
        installed.install_site_list(_write(tmp_path, f"{n}.csv", "local_name,code\nhypertension,I15\n"), other, n,
                                    system="icd10cm")  # fmt: skip
    agree = Terminology(installed=other).map("condition", "hypertension")
    assert not agree.needs_review and agree.notes == ["site list site_a"]


def test_a_site_list_that_contradicts_itself_is_refused(tmp_path: Path) -> None:
    text = "local_code,local_name,system,code\nZZ1,hypertension,icd10cm,I10\nZZ2,Hypertension,icd10cm,I15\n"
    with pytest.raises(ValueError, match=r"line 3: local_name 'Hypertension' is I15 here and I10 on line 2"):
        installed.install_site_list(_write(tmp_path, "x.csv", text), tmp_path / "t", "x")
    same = "local_code,local_name,system,code\nZZ1,x,icd10cm,I10\nZZ1,y,icd10cm,E11\n"
    with pytest.raises(ValueError, match="local_code 'ZZ1' is E11 here and I10 on line 2"):
        installed.install_site_list(_write(tmp_path, "y.csv", same), tmp_path / "t", "y")


@pytest.mark.parametrize(("code", "stored"), [("e11", "E11"), ("Ｅ１１", "E11"), (" i10 ", "I10"), ("E11.9", "E11.9")])
def test_a_site_code_is_stored_as_the_tables_write_it(tmp_path: Path, code: str, stored: str) -> None:
    p = _write(tmp_path, "s.csv", f"local_name,code\nSYNTHETIC name,{code}\n")
    installed.install_site_list(p, tmp_path / "t", "s", system="icd10cm")
    r = Terminology(installed=tmp_path / "t").map("condition", "SYNTHETIC name")
    assert r.method == "site" and not r.needs_review and r.concepts[0].code.startswith(stored)


@pytest.mark.parametrize(("system", "code"), [("icd10cm", "I109"), ("icd10cm", "hypertension"), ("loinc", "2160"),
                                              ("atc", "Z99AA0"), ("icd10pcs", "0Z1"), ("icd10_who", "XXII")])  # fmt: skip
def test_a_site_code_not_shaped_as_its_system_refuses_the_list(tmp_path: Path, system: str, code: str) -> None:
    p = _write(tmp_path, "s.csv", f"local_name,system,code\nok,icd10cm,I10\nSYNTHETIC name,{system},{code}\n")
    with pytest.raises(ValueError, match=f"line 3: '{code}' is not a {system} code"):
        installed.install_site_list(p, tmp_path / "t", "s")
    assert not (tmp_path / "t").exists()


def test_a_site_code_no_table_holds_is_for_review(tmp_path: Path) -> None:
    p = _write(tmp_path, "s.csv", "local_name,system,code\nSYNTHETIC one,icd10cm,I10.99\nSYNTHETIC two,loinc,99990-1\n")
    installed.install_site_list(p, tmp_path / "t", "s")
    t = Terminology(installed=tmp_path / "t")
    for name, code in (("SYNTHETIC one", "I10.99"), ("SYNTHETIC two", "99990-1")):
        r = t.map("condition" if code.startswith("I") else "observation", name)
        assert r.method == "site" and r.needs_review and f"in no loaded or shipped table: {code}" in r.notes


def test_cjk_and_bracketed_names_keep_their_own_keys(tmp_path: Path) -> None:
    """TERM-2 review: a zh name is never reduced to its Latin letters, and words in brackets stay words."""
    site = ("local_name,system,code\nB型肝炎,icd10cm,B18.1\n第2型糖尿病,icd10cm,E11\n"
            "Hepatitis B (HBsAg),icd10cm,B18.1\n")  # fmt: skip
    installed.install_site_list(_write(tmp_path, "s.csv", site), tmp_path / "t", "s")
    t = Terminology(installed=tmp_path / "t")
    assert t.map("condition", "B型肝炎").method == "site"
    for other in ("B群鏈球菌感染", "第2期慢性腎病", "Hepatitis B (anti-HBs)", "hepatitis b"):
        assert t.map("condition", other).method != "site", other
    assert t.map("condition", "hepatitis-B (HBsAg)").method == "site"  # punctuation and case alone still match


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
    # the sample's only drug left the list on 2014-06-30 (有效迄日 1030630): an ended code answers nothing
    assert term.map("medication", "flupentixol").method == "none"
    h = term.map("procedure", "hemodialysis")
    assert h.method == "loaded" and [(c.system, c.code) for c in h.concepts] == [(SYSTEMS["nhi_order"], "58001C")]
    assert term.map("procedure", "總膽固醇").concepts[0].code == "09001C"


# NHIA's drug-list columns (as tests/fixtures/refdata/nhi_drugs_sample.csv has them), every row made up
NHI_DRUG_HEAD = ("異動,藥品代號,藥品英文名稱,藥品中文名稱,成分,規格量,規格單位,單複方,支付價,有效起日,有效迄日,藥商,製造廠名稱,"
                 "劑型,藥品分類,分類分組名稱,ATC代碼,給付規定章節,藥品代碼超連結,給付規定章節連結")  # fmt: skip


def _nhi_drug(code: str, ingredient: str, atc: str, until: str = "1991231") -> str:
    return f",{code},SYNTHETIC,合成,{ingredient},,,單方,1.00,1100101,{until},,,錠,,,{atc},,,"


def test_an_nhi_ingredient_keeps_its_digits_and_ended_codes_are_left_out(tmp_path: Path) -> None:
    text = "\n".join([NHI_DRUG_HEAD, _nhi_drug("ZZ00000100", "SYNTHETICOL B12 1 MG", "Z99AA01"),
                      _nhi_drug("ZZ00000200", "SYNTHETICOL B6 (HCL) 5 MG", "Z99AA02"),
                      _nhi_drug("ZZ00000300", "SYNTHETIC ENDED 1 MG", "Z99AA03", until="1030630")]) + "\n"  # fmt: skip
    installed.install_nhi_drugs(_write(tmp_path, "d.csv", text), tmp_path / "t")
    t = Terminology(installed=tmp_path / "t")
    b12 = t.map("medication", "syntheticol b12")
    assert b12.method == "loaded" and b12.needs_review and [c.code for c in b12.concepts] == ["Z99AA01"]
    assert [c.code for c in t.map("medication", "syntheticol b6").concepts] == ["Z99AA02"]
    assert t.map("medication", "synthetic ended").method == "none"


def test_a_name_with_several_codes_in_one_table_answers_all_of_them_for_review(tmp_path: Path) -> None:
    """TERM-2 review: never the first code alone. Two NHI items named the same, and one ATC substance under two codes."""
    svc = ("診療項目代碼,健保支付點數,生效起日,生效迄日,英文項目名稱,中文項目名稱,備註\n"
           "ZZ001C,1,20200101,29101231,SYNTHETIC dialysis,合成透析（門診）,\n"
           "ZZ002B,1,20200101,29101231,SYNTHETIC dialysis,合成透析（住院）,\n")  # fmt: skip
    installed.install_nhi_services(_write(tmp_path, "s.csv", svc), tmp_path / "t")
    atc = "ATC code\tATC level name\nZ99AA01\tsynthetic twin\nZ99BB01\tsynthetic twin\nZ99CC01\tsynthetic single\n"
    installed.install_atc(_write(tmp_path, "a.tsv", atc), tmp_path / "t", NAME, version="2099")
    t = Terminology(installed=tmp_path / "t")
    d = t.map("procedure", "SYNTHETIC dialysis")
    assert d.needs_review and {c.code for c in d.concepts} == {"ZZ001C", "ZZ002B"}
    assert "several codes share this name" in d.notes[0]
    tw = t.map("medication", "synthetic twin")
    assert tw.needs_review and {c.code for c in tw.concepts} == {"Z99AA01", "Z99BB01"}
    single = t.map("medication", "synthetic single")
    assert not single.needs_review and [c.code for c in single.concepts] == ["Z99CC01"]


def test_a_name_in_two_tables_answers_from_the_first_for_review(tmp_path: Path) -> None:
    svc = ("診療項目代碼,健保支付點數,生效起日,生效迄日,英文項目名稱,中文項目名稱,備註\n"
           "ZZ003C,1,20200101,29101231,SYNTHETIC resection procedure,合成切除,\n")  # fmt: skip
    installed.install_nhi_services(_write(tmp_path, "s.csv", svc), tmp_path / "t")
    installed.install_icd10pcs(_write(tmp_path, "icd10pcs_order_2099.txt", PCS_ORDER), tmp_path / "t", "2099")
    r = Terminology(installed=tmp_path / "t").map("procedure", "SYNTHETIC resection procedure")
    assert r.needs_review and [c.code for c in r.concepts] == ["ZZ003C"] and "also in icd10pcs" in r.notes[0]


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
    empty = f"{4:05d} {'0Z3ZZZZ':<7} 1 {'SYNTHETIC short only':<60}\n"  # an order line without its long description
    with pytest.raises(ValueError, match="line 1: not a line of CMS"):
        installed.install_icd10pcs(_write(tmp_path, "icd10pcs_order_2098.txt", empty), tmp_path / "v", "2098")


# ----------------------------------------------------------------------------------- LOINC, WHO ICD-10 and ATC
def test_a_licensed_system_names_who_accepted_its_licence(loaded: Path) -> None:
    lines = installed.manifest(loaded)["tables"]
    for t in ("loinc_table", "icd10_who", "atc_index"):
        assert lines[t]["licence_accepted_by"] == NAME and len(lines[t]["sha256"]) == 64
        assert lines[t]["licence"] == installed.LICENSED[t]
    assert (
        lines["loinc_table"]["licence_accepted_on"] == "2099-01-02" and lines["loinc_table"]["version"] == "LOINC 2.99"
    )
    assert lines["icd10_who"]["version"] == "WHO ICD-10 2099" and lines["atc_index"]["version"] == "ATC 2099"
    assert "site_dx" in lines and "licence_accepted_by" not in lines["site_dx"]


@pytest.mark.parametrize("who", ["", "  ", "yes", "IT", "admin", "123", "A", "Ada", "A B"])
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


@pytest.mark.parametrize(
    "bad", ['<!DOCTYPE x [<!ENTITY e "boom">]><ClaML/>', "<!DOCTYPE x [<!ELEMENT a ANY>]><ClaML/>"]
)
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
NAMES = [("condition", "hypertension"), ("condition", "ischemic heart disease"), ("condition", "gout"),
         ("condition", "高血壓"), ("condition", "qwerty zxcv syndrome"), ("medication", "allopurinol"),
         ("medication", "urate-lowering therapy"), ("observation", "serum uric acid"), ("observation", "hba1c"),
         ("procedure", "hemodialysis"), ("procedure", "chest x-ray"), ("encounter", "rheumatology"),
         ("claim", "allopurinol"), ("report", "creatinine")]  # fmt: skip


def _answer(t: Terminology, domain: str, name: str) -> tuple[object, ...]:
    r = t.map(domain, name)
    return r.method, r.needs_review, [(c.system, c.code) for c in r.concepts], r.families, r.notes


def test_with_nothing_loaded_nothing_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-1116: with no folder and with an empty folder the mapper gives the same answers, and none is TERM-2's. H-17
    (D-1127): nothing shipped either (the NHI tables the image may ship are tested in test_h17_*)."""
    monkeypatch.setattr(installed, "SHIPPED_DIR", tmp_path / "shipped-none")
    (tmp_path / "empty").mkdir()
    none, empty = Terminology(installed=tmp_path / "nothing"), Terminology(installed=tmp_path / "empty")
    for t in (none, empty):
        assert not t.site_names and not t.loaded_names and not t.loaded_sources and not t.installed_problems
    for domain, name in NAMES:
        assert _answer(none, domain, name) == _answer(empty, domain, name), name
        assert _answer(empty, domain, name)[0] not in ("site", "loaded"), name
    assert installed.not_loaded(tmp_path / "nothing") == [label for label, _ in installed.AT_INSTALL]


def test_a_damaged_manifest_is_a_refusal_not_a_crash(loaded: Path, tmp_path: Path) -> None:
    from tools.trialbox import doctor

    copy = tmp_path / "copy"
    copy.mkdir()
    for p in loaded.glob("*.parquet"):
        (copy / p.name).write_bytes(p.read_bytes())
    (copy / "manifest.json").write_text('{"tables": {"site_dx": {"sha', encoding="utf-8")  # cut short
    t = Terminology(installed=copy)
    assert any("not readable JSON" in p for p in t.installed_problems) and not t.loaded_sources
    assert t.map("condition", "hypertension").method != "site"
    bad = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(copy)}))
    assert bad.status == "FAIL" and "not readable JSON" in bad.detail


def test_a_manifest_key_that_is_not_a_plain_name_is_refused(tmp_path: Path) -> None:
    where = tmp_path / "t"
    installed.install_site_list(_write(tmp_path, "s.csv", "local_name,code\nx,I10\n"), where, "s", system="icd10cm")
    data = json.loads((where / "manifest.json").read_text(encoding="utf-8"))
    data["tables"]["../outside"] = dict(data["tables"]["site_s"])
    (where / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    problems = {s.name: s.problem for s in installed.status(where)}
    assert "not a plain table name" in problems["../outside"] and not problems["site_s"]


def test_the_loader_leaves_no_temporary_file_and_a_whole_manifest(loaded: Path) -> None:
    assert not list(loaded.glob("*.tmp")) and not list(loaded.glob(".*.tmp"))
    assert set(installed.manifest(loaded)["tables"]) == {p.stem for p in loaded.glob("*.parquet")}


def test_a_licensed_name_may_be_written_in_cjk(tmp_path: Path) -> None:
    who = "測試人員"  # SYNTHETIC: "test staff", not a person's name
    assert installed.licence_line("loinc_table", who)["licence_accepted_by"] == who


def test_a_who_category_in_a_site_list_stands_for_its_family(loaded: Path, tmp_path: Path) -> None:
    where = tmp_path / "t"
    for p in loaded.iterdir():
        (where / p.name).parent.mkdir(exist_ok=True)
        (where / p.name).write_bytes(p.read_bytes())
    installed.install_site_list(_write(tmp_path, "w.csv", "local_name,code\nSYNTHETIC local disorder,U98\n"), where,
                                "who", system="icd10_who")  # fmt: skip
    r = Terminology(installed=where).map("condition", "SYNTHETIC local disorder")
    assert r.method == "site" and not r.needs_review and {c.code for c in r.concepts} == {"U98", "U98.0", "U98.9"}
    assert (ICD10_WHO, "U98") in r.families


def test_doctor_names_each_system_and_who_accepted(loaded: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    from tools.trialbox import doctor

    monkeypatch.setattr(installed, "SHIPPED_DIR", tmp_path / "shipped-none")  # H-17: nothing shipped here either

    ok = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(loaded)}))
    assert ok.status == "PASS" and "not loaded" not in ok.detail
    assert f"loinc_table 4 rows (LOINC 2.99), licence accepted by {NAME} on 2099-01-02" in ok.detail
    assert "site_dx 4 rows" in ok.detail and "icd10pcs 3 rows (ICD-10-PCS 2099)" in ok.detail
    none = doctor.check_terminology(doctor.DoctorInputs(env={"TB_TERMINOLOGY_DIR": str(tmp_path / "e")}))
    assert none.status == "PASS" and none.detail.endswith(
        "not loaded: site lists, NHI drug list, NHI service codes, ICD-10-PCS, LOINC, WHO ICD-10, ATC"
    )


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
