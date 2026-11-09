"""D-170 to D-172: the Taiwan reference data items (NHI drug -> ATC, ICD-10-CM/PCS 2014 <-> 2023, NHI lab -> LOINC,
zh-TW synonyms) in the refdata pack, the store, the name matcher and site set-up.

Everything runs on small committed excerpts (``tests/fixtures/refdata``): no network.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from criteria_compiler.terminology.mapper import Terminology
from sitesetup import mapping as sm
from tb_common import refdata as rd
from tb_common import refdata_tw as tw

from tools import refdata_fetch as rf

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "tests" / "fixtures" / "refdata"
TW_IDS = ("nhi_drug_atc", "tw_icd_2014_2023", "nhi_lab_loinc", "naer_medical_terms", "tw_zh_synonyms")


@pytest.fixture(scope="module")
def sample_tar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("twpack")
    return rf.build(rf.sample_raw(out / "raw"), out, "20261109", sample=True)


@pytest.fixture
def loaded(sample_tar: Path, db_url: str) -> str:
    with rd.opened(sample_tar) as p, rd.RefStore(db_url) as st:
        st.load(p, by="test")
    return db_url


# ------------------------------------------------------------------------------------------------ the registry
def test_each_item_is_registered_with_source_licence_decision_and_its_own_loader() -> None:
    by = {s.id: s for s in rf.SOURCES}
    for sid in TW_IDS:
        s = by[sid]
        assert s.country == "TW" and s.distribution == "ship" and s.parse is not None
        assert s.licence and s.attribution and s.url and s.decision in ("D-170", "D-171", "D-172")
    assert by["nhi_lab_loinc"].licence.startswith("CC0") and by["tw_icd_2014_2023"].licence == rf.OGDL
    assert by["nhi_drug_atc"].derived_from == "nhi_drugs"  # read from the drug list's download, not fetched twice
    assert all(s.name in rf.table_md() for s in tw.ITEMS)


def test_the_pack_records_version_and_sha256_and_notice_lists_them(sample_tar: Path) -> None:
    with rd.opened(sample_tar) as pack:
        m = rd.verify(pack)
        notice = (pack / "NOTICE.md").read_text(encoding="utf-8")
    src = {s["id"]: s for s in m["sources"]}
    for sid in TW_IDS:
        s = src[sid]
        assert s["version"] and len(s["download_sha256"]) == 64 and s["country"] == "TW" and s["records"] > 0
        assert f"* Version: {s['version']}" in notice and s["download_sha256"] in notice
    assert src["nhi_lab_loinc"]["version"] == "tw.gov.mohw.nhi.pas 1.3.0, ConceptMap nhi-loinc 1.3.0"
    assert src["tw_zh_synonyms"]["version"].startswith("TrialBox zh-TW synonyms, 62 entries")


def test_a_map_or_synonym_source_without_a_version_is_refused(sample_tar: Path, tmp_path: Path) -> None:
    with rd.opened(sample_tar) as p:
        pack = Path(shutil.copytree(p, tmp_path / p.name))
    m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    next(s for s in m["sources"] if s["id"] == "nhi_lab_loinc")["version"] = ""
    (pack / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(rd.PackError, match="must state its version"):
        rd.verify(pack)


def test_fetch_is_the_only_network_path_and_a_derived_item_fetches_its_parent(monkeypatch: pytest.MonkeyPatch,
                                                                               tmp_path: Path) -> None:  # fmt: skip
    calls: list[str] = []

    def fake_download(url: str, dest: Path, **_: object) -> dict[str, object]:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return {"url": url, "downloaded_at": "2026-11-09T00:00:00+00:00", "sha256": "0" * 64, "bytes": 1}

    monkeypatch.setattr(rf, "download", fake_download)
    monkeypatch.setattr(rf, "dataset_version", lambda url: f"v:{url.rsplit('/', 1)[-1]}")
    rf.fetch(["nhi_drug_atc", "tw_icd_2014_2023", "tw_zh_synonyms"], tmp_path)
    assert calls == [rf.BY_ID["nhi_drugs"].url, rf.BY_ID["tw_icd_2014_2023"].url,
                     rf.BY_ID["tw_icd_2014_2023"].extra_files[0][1]]  # fmt: skip
    nhi = json.loads((tmp_path / "nhi_drugs/fetch.json").read_text())
    assert nhi["versions"] == {"nhi_drug_atc": "v:23715"}
    icd = json.loads((tmp_path / "tw_icd_2014_2023/fetch.json").read_text())
    assert icd["version"] == "v:177508" and len(icd["parts"]) == 2  # sha256 over both files
    assert (tmp_path / "tw_zh_synonyms/zh_tw_clinical_synonyms.csv").read_bytes() == tw.REPO_SYNONYMS.read_bytes()


# ------------------------------------------------------------------------------------------------ the parsers
def test_nhi_drug_to_atc_keeps_the_atc_as_given() -> None:
    (row,) = tw.parse_nhi_drug_atc(SAMPLES / "nhi_drugs_sample.csv")
    assert (row["source_code"], row["target_system"], row["target_code"]) == ("B004858100", tw.ATC, "N05AF01")
    assert row["relation"] == "wider" and row["extra"]["atc_level"] == 5 and row["extra"]["valid_from"] == "2011-12-01"


def test_nhi_drug_to_atc_skips_empty_and_odd_codes_and_keeps_a_partial_level(tmp_path: Path) -> None:
    head = (SAMPLES / "nhi_drugs_sample.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    cols = head.split(",")

    def line(code: str, atc: str) -> str:
        r = dict.fromkeys(cols, "")
        r.update({"藥品代號": code, "有效起日": "1150101", "ATC代碼": atc})
        return ",".join(r[c] for c in cols)

    f = tmp_path / "d.csv"
    f.write_text("\n".join([head, line("A1", "N05AA"), line("A2", ""), line("A3", "XYZ-1"), line("A4", "m04aa01")]))
    got = {r["source_code"]: (r["target_code"], r["extra"]["atc_level"]) for r in tw.parse_nhi_drug_atc(f)}
    assert got == {"A1": ("N05AA", 4), "A4": ("M04AA01", 5)}


def test_icd_2014_2023_relations(tmp_path: Path) -> None:
    raw = rf.sample_raw(tmp_path / "raw")
    rows = list(tw.parse_tw_icd_2014_2023(raw / "tw_icd_2014_2023" / "tw_icd_2014_2023_cm.csv"))
    rel = {(r["source_code"], r["target_code"]): r["relation"] for r in rows if r["source_system"] == tw.ICD_CM_2014}
    assert rel[("A00.0", "A00.0")] == "equivalent" and rel[("M10.9", "M10.9")] == "equivalent"
    assert rel[("A04.7", "A04.71")] == rel[("A04.7", "A04.72")] == "narrower"  # one 2014 code split in two
    assert {rel[("I10", c)] for c in ("I10", "I16.0", "I16.1", "I16.9")} == {"narrower"}
    assert rel[("B18.1", "B18.1")] == rel[("Z22.51", "B18.1")] == "wider"  # two 2014 codes merged into one
    assert rel[("P83.8", "P83.88")] == "inexact" and rel[("T84.040A", "M97.01XA")] == "inexact"
    a047 = next(r for r in rows if r["source_code"] == "A04.7")
    assert a047["extra"]["status_2014"] == "2014代碼改為不可用" and a047["extra"]["target_zh"].startswith("艱難梭菌")
    assert any(r["source_system"] == tw.ICD_PCS_2014 for r in rows)  # the PCS file beside it
    with pytest.raises(ValueError, match="not an NHIA"):
        list(tw.icd_map_rows(b"a,b\n1,2\n", pcs=False))


def test_nhi_lab_loinc_reads_the_cc0_conceptmap_and_refuses_another_licence(tmp_path: Path) -> None:
    rows = list(tw.parse_nhi_lab_loinc(SAMPLES / "nhi_pas_sample"))
    creat = sorted(r["target_code"] for r in rows if r["source_code"] == "09015C")
    assert "2160-0" in creat and len(creat) > 1 and {r["relation"] for r in rows} == {"relatedto"}
    assert all(r["source_system"] == tw.NHI_SERVICE and r["target_display"] == "" for r in rows)  # codes only
    bad = Path(shutil.copytree(SAMPLES / "nhi_pas_sample", tmp_path / "pkg"))
    pkg = json.loads((bad / "package.json").read_text(encoding="utf-8"))
    (bad / "package.json").write_text(json.dumps(pkg | {"license": "CC-BY-NC-4.0"}), encoding="utf-8")
    with pytest.raises(ValueError, match="do not ship"):
        list(tw.parse_nhi_lab_loinc(bad))


def test_synonyms_naer_split_and_curated_flag() -> None:
    naer = list(tw.parse_naer_terms(SAMPLES / "naer_medical_terms_sample.csv"))
    stroke = sorted(r["term"] for r in naer if r["canonical"] == "stroke")
    assert stroke == ["中風", "猝發", "發作"] and not any(r["curated"] for r in naer)
    own = list(tw.parse_zh_tw_synonyms(tw.REPO_SYNONYMS))
    assert len(own) == 62 and all(r["curated"] for r in own)
    assert {(r["term"], r["canonical"]) for r in own} >= {("洗腎", "hemodialysis"), ("HTN", "hypertension")}


def test_roc_dates() -> None:
    assert tw.roc(" 960901") == "2007-09-01" and tw.roc("114.08.04") == "2025-08-04" and tw.roc("x") == "x"


# ------------------------------------------------------------------------------------------------ the store
def test_the_store_answers_maps_both_ways_and_synonyms(loaded: str) -> None:
    with rd.RefStore(loaded) as st:
        (atc,) = st.map_targets(tw.NHI_DRUG, "B004858100")
        assert atc["target_code"] == "N05AF01" and atc["source_id"] == "nhi_drug_atc"
        assert sorted(t["target_code"] for t in st.map_targets(tw.ICD_CM_2014, "A04.7")) == ["A04.71", "A04.72"]
        assert sorted(s["source_code"] for s in st.map_sources(tw.ICD_CM_2023, "B18.1")) == ["B18.1", "Z22.51"]
        assert len(st.map_targets(tw.NHI_SERVICE, "09026C")) > 1
        hd = st.synonyms(" 洗腎 ", "procedure")
        assert [(s["canonical"], s["curated"]) for s in hd] == [("hemodialysis", True)]
        assert st.synonyms("洗腎", "condition") == []  # another domain
        assert {s["canonical"] for s in st.synonyms("htn")} == {"hypertension"}  # NFKC + case like the matcher
        assert {s["source_id"] for s in st.synonyms("高血壓")} == {"naer_medical_terms", "tw_zh_synonyms"}
        status = {s["source_id"]: s for s in (st.status() or {})["sources"]}
        assert (
            status["nhi_lab_loinc"]["version"].endswith("1.3.0")
            and len(status["nhi_lab_loinc"]["download_sha256"]) == 64
        )
        notes = {n["id"]: n for n in st.notices()}
        assert notes["tw_icd_2014_2023"]["version"] == "sample" and notes["naer_medical_terms"]["kind"] == "synonym"


def test_a_2014_code_against_a_2023_list_is_unknown_when_split(loaded: str) -> None:
    with rd.RefStore(loaded) as st:
        i10 = st.map_targets(tw.ICD_CM_2014, "I10")
        a047 = st.map_targets(tw.ICD_CM_2014, "A04.7")
    only_i10 = {(tw.ICD_CM_2023, "I10")}
    all_htn = {(tw.ICD_CM_2023, c) for c in ("I10", "I16.0", "I16.1", "I16.9")}
    assert rd.in_set_via_map(i10, all_htn) == "yes"
    assert rd.in_set_via_map(i10, only_i10) == "unknown"  # 2014 I10 may have been a hypertensive crisis
    assert rd.in_set_via_map(a047, only_i10) == "no"
    assert rd.in_set_via_map([], only_i10) == "unknown"  # a code the map does not know never excludes


def test_a_bad_relation_is_refused() -> None:
    with pytest.raises(rd.PackError, match="relation"):
        rd.map_row({"source_system": "a", "source_code": "1", "target_system": "b", "target_code": "2",
                    "relation": "same"}, "x")  # fmt: skip
    with pytest.raises(rd.PackError, match="synonym row"):
        rd.synonym_row({"term": "x", "lang": "zh-TW"}, "x")


# ------------------------------------------------------------------------------------------------ the name matcher
def test_the_name_matcher_reads_the_dictionary(loaded: str) -> None:
    plain = Terminology()
    with_dict = Terminology(name_synonyms=rd.synonym_lookup(loaded))
    assert plain.map("condition", "類風濕關節炎").method != "synonym"
    ra = with_dict.map("condition", "類風濕關節炎")  # curated: 類風濕關節炎 -> rheumatoid arthritis
    assert ra.method == "synonym" and not ra.needs_review and ra.concepts and "tw_zh_synonyms" in ra.notes[0]
    assert ra.concepts == plain.map("condition", "rheumatoid arthritis").concepts
    gpt = with_dict.map("observation", "GPT")  # TW usage: GPT = ALT
    assert gpt.method == "synonym" and {c.code for c in gpt.concepts} == {"1742-6"}
    # NAER only (not curated): 高尿酸血症 is in our list too, 猝發 only in NAER -> stroke, flagged for review
    stroke = with_dict.map("condition", "猝發")
    assert stroke.method == "synonym" and stroke.needs_review
    assert with_dict.map("condition", "痛風").method in ("exact", "synonym")  # the curated table still wins


def test_the_matcher_without_a_database_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_DB_URL", raising=False)
    t = Terminology(name_synonyms=rd.synonym_lookup())
    assert t.map("condition", "洗腎").method == Terminology().map("condition", "洗腎").method


# ------------------------------------------------------------------------------------------------ site set-up
def test_site_setup_suggests_from_the_taiwan_maps(loaded: str) -> None:
    drug = sm.suggest("medication", sm.local_system("drug-code"), "B004858100")
    assert drug["code"] == "N05AF01" and drug["method"] == "refdata"
    creat = sm.suggest("observation", sm.local_system("lab-code"), "09015C")  # several targets, one in our table
    assert creat["code"] == "2160-0" and creat["method"] == "refdata"
    psa = sm.suggest("observation", sm.local_system("lab-code"), "12198C")  # one target
    assert psa["code"] == "83113-1"
    moved = sm.suggest("condition", sm.local_system("dx-code"), "P83.8")  # gone in 2023, one new code
    assert moved["code"] == "P83.88" and moved["method"] == "refdata"
    assert sm.suggest("condition", sm.local_system("dx-code"), "A04.7") == {}  # split: the coordinator picks
    assert sm.suggest("condition", sm.local_system("dx-code"), "I10")["method"] == "same"  # still a 2023 code


def test_site_setup_without_reference_data_is_unchanged() -> None:
    assert sm.suggest("medication", sm.local_system("drug-code"), "B004858100") == {}
    assert sm.suggest("condition", sm.local_system("dx-code"), "P83.8")["method"] == "same"
