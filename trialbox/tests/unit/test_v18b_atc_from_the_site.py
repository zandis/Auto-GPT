"""V-18b (D-1183, V18-07): ATC is never shipped. Its names reach the readers only from the hospital's own copy
(``atc_index``, loaded at install under a named acceptance); without it, ATC codes are identifiers only (D-536): the
ones the NHI drug lists' ATC column and TrialBox's own groupers name, each without a WHOCC name. A drug named only in
the WHOCC index is unmapped, and the FHIR store's ATC is a line of the "information still needed" page.

The index here is synthetic and written by the test (a tracked index is refused, D-1116): real ATC codes as
identifiers, made-up names."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from criteria_compiler.terminology import installed
from criteria_compiler.terminology.mapper import SYSTEMS, TERM_DIR, Terminology

from tools import build_terminology
from tools import fhir_codesystems as fc

ROOT = Path(__file__).resolve().parents[2]
ATC = SYSTEMS["atc"]
SITE_ATC = "ATC code\tATC level name\n" + "".join(f"{c}\t{n}\n" for c, n in [
    ("M04", "SYNTHETIC antigout group"),
    ("M04AA", "SYNTHETIC xanthine group"),
    ("M04AA01", "synthetic urate substance one"),
    ("M04AA03", "synthetic urate substance three"),
    ("M04AB03", "synthetic uricosuric substance"),
    ("L04AX03", "synthetic antifolate substance"),
])  # fmt: skip
NAME = "Ada Example (SYNTHETIC test person)"
# the names the shipped table gave before (WHOCC's); none may reach a reader without the site's copy
WHOCC_NAMES = {"allopurinol", "febuxostat", "benzbromarone", "methotrexate", "colchicine"}


@pytest.fixture
def bare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Terminology:
    """Nothing loaded at install and no NHI list shipped: the image's tables alone."""
    monkeypatch.setattr(installed, "SHIPPED_DIR", tmp_path / "shipped-none")
    return Terminology(installed=tmp_path / "nothing")


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Terminology:
    monkeypatch.setattr(installed, "SHIPPED_DIR", tmp_path / "shipped-none")
    where = tmp_path / "terminology"
    (tmp_path / "atc.tsv").write_text(SITE_ATC, encoding="utf-8")
    assert installed.install_atc(tmp_path / "atc.tsv", where, NAME, version="2099") == {"atc_index": 6}
    t = Terminology(installed=where)
    assert not t.installed_problems, t.installed_problems
    return t


def test_no_atc_table_ships_and_nothing_builds_one() -> None:
    assert not (TERM_DIR / "atc.parquet").exists() and not (TERM_DIR / "src" / "atc.csv").exists()
    assert "atc" not in build_terminology.FILES
    with (ROOT / "docs/licences/register.csv").open(encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["id"] == "atc")
    assert "terminology/atc" not in row["paths"] and "src/atc.csv" not in row["paths"]


def test_without_the_sites_copy_atc_codes_are_identifiers_with_no_whocc_name(bare: Terminology) -> None:
    r = bare.map("medication", "urate-lowering therapy")  # TrialBox's own grouper: two families
    assert {c.code for c in r.concepts} == {"M04AA01", "M04AA03", "M04AB03"}  # the NHI drug list's ATC column
    assert {c.display for c in r.concepts} == {"M04AA01", "M04AA03", "M04AB03"}  # the code, never a WHOCC name
    assert set(r.families) == {(ATC, "M04AA"), (ATC, "M04AB")}
    m = bare.map("medication", "methotrexate")  # the grouper's own exact code
    assert [(c.code, c.display) for c in m.concepts] == [("L04AX03", "L04AX03")]
    for word in WHOCC_NAMES:
        assert all(c.display.lower() != word for c in bare.map("medication", word).concepts), word


def test_a_drug_only_the_whocc_index_named_is_unmapped_without_the_sites_copy(bare: Terminology) -> None:
    r = bare.map("medication", "febuxostat")  # was the shipped table's name of M04AA03
    assert r.method == "none" and r.concepts == []


def test_a_family_with_no_code_in_the_nhi_lists_still_answers_with_its_codes(bare: Terminology) -> None:
    r = bare.map("medication", "anticoagulant")
    assert {c.code for c in r.concepts} == {"B01AA03", "B01AE07", "B01AF01", "B01AF02", "B01AF03"}
    assert set(r.families) == {(ATC, "B01AA"), (ATC, "B01AE"), (ATC, "B01AF")}


def test_the_sites_copy_names_the_codes_and_answers_its_own_names(site: Terminology) -> None:
    r = site.map("medication", "urate-lowering therapy")  # the grouper expands from the site's index only
    assert [(c.code, c.display) for c in r.concepts] == [
        ("M04AA01", "synthetic urate substance one"),
        ("M04AA03", "synthetic urate substance three"),
        ("M04AB03", "synthetic uricosuric substance"),
    ]
    one = site.map("medication", "synthetic urate substance three")
    assert one.method == "loaded" and [c.code for c in one.concepts] == ["M04AA03"]  # a table loaded at install
    named = site.concept(ATC, "M04AA01")
    assert named is not None and named.display.startswith("synthetic")


def test_the_fhir_store_carries_atc_only_from_the_sites_copy(tmp_path: Path) -> None:
    src = next(s for s in fc.SOURCES if s.key == "atc")
    got = fc.pick(src, tmp_path / "nothing", [])
    assert isinstance(got, str)  # nothing to load: absent, a line of needed.jsonl and no fault (D-1182)


def test_a_partial_site_copy_never_takes_a_code_from_a_grouper(bare: Terminology, site: Terminology) -> None:
    """Review F1: each code is looked up in order (the site's copy, the NHI lists' ATC column, the grouper itself),
    so a copy that lacks a code (older, or cut to a formulary) leaves every grouper its codes; ``atc_gaps`` names the
    codes the copy does not hold."""
    names = sorted({(str(s["domain"]), str(s["name"])) for s in bare.synonyms if s["table"] == "atc"})
    lost = {n: sorted({c.code for c in bare.map(d, n).concepts} - {c.code for c in site.map(d, n).concepts})
            for d, n in names}  # fmt: skip
    assert {n: codes for n, codes in lost.items() if codes} == {}
    gaps = site.atc_gaps()
    assert gaps["anticoagulant"] == ["B01AA03", "B01AE07", "B01AF01", "B01AF02", "B01AF03"]
    assert "urate-lowering therapy" not in gaps  # the copy holds all three
    assert bare.atc_gaps() == {}


NHI_HEAD = ("異動,藥品代號,藥品英文名稱,藥品中文名稱,成分,規格量,規格單位,單複方,支付價,有效起日,有效迄日,藥商,製造廠名稱,"
            "劑型,藥品分類,分類分組名稱,ATC代碼,給付規定章節,藥品代碼超連結,給付規定章節連結")  # NHIA's layout  # fmt: skip


@pytest.mark.parametrize(("name", "code"), [("hydroxychloroquine", "P01BA02"), ("isoniazid", "J04AC01"),
                                            ("metformin", "A10BA02"), ("sulfasalazine", "A07EC01"),
                                            ("warfarin", "B01AA03")])  # fmt: skip
def test_the_nhi_drug_list_brings_back_a_name_the_shipped_table_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, code: str
) -> None:
    """Review: the five drug names H-17 lost without the shipped table answer again on a box that loaded the NHI drug
    list (its ingredient column, open data), for review; with committed data alone they stay unmapped."""
    monkeypatch.setattr(installed, "SHIPPED_DIR", tmp_path / "shipped-none")
    row = f",ZZ00000100,SYNTHETIC,合成,{name.upper()} 100 MG,,,單方,1.00,1100101,1991231,,,錠,,,{code},,,"
    (tmp_path / "d.csv").write_text(NHI_HEAD + "\n" + row + "\n", encoding="utf-8")
    installed.install_nhi_drugs(tmp_path / "d.csv", tmp_path / "t")
    got = Terminology(installed=tmp_path / "t").map("medication", name)
    assert got.method == "loaded" and got.needs_review and [c.code for c in got.concepts] == [code]
    assert Terminology(installed=tmp_path / "nothing").map("medication", name).method == "none"
