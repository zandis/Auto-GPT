"""D-170 to D-172: the Taiwan reference data items (NHI drug -> ATC, ICD-10-CM/PCS 2014 <-> 2023, NHI lab -> LOINC,
zh-TW synonyms) in the refdata pack, the store, the name matcher and site set-up.

Everything runs on small committed excerpts (``tests/fixtures/refdata``): no network.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

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
    assert src["nhi_lab_loinc"]["version"] == "tw.gov.mohw.nhi.pas 1.3.0, ConceptMap nhi-loinc 1.3.0, LOINC 2.77"
    assert src["tw_zh_synonyms"]["version"].startswith("TrialBox zh-TW synonyms, 42 entries")
    icd = src["tw_icd_2014_2023"]  # two files: each part with its own sha256, listed in NOTICE
    assert [p["file"] for p in icd["parts"]] == ["tw_icd_2014_2023_cm.csv", "tw_icd_2014_2023_pcs.csv"]
    assert all(p["sha256"] in notice for p in icd["parts"]) and "over the parts' sha256s" in notice
    assert src["nhi_lab_loinc"]["parts"][0]["sha256"] == src["nhi_lab_loinc"]["download_sha256"]


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
    monkeypatch.setattr(tw, "datagov_meta", lambda url: {"version": f"v:{url.rsplit('/', 1)[-1]}", "license": "1"})
    rf.fetch(["nhi_drug_atc", "tw_icd_2014_2023", "tw_zh_synonyms"], tmp_path)
    assert calls == [rf.BY_ID["nhi_drugs"].url, rf.BY_ID["tw_icd_2014_2023"].url,
                     rf.BY_ID["tw_icd_2014_2023"].extra_files[0][1]]  # fmt: skip
    nhi = json.loads((tmp_path / "nhi_drugs/fetch.json").read_text())
    assert nhi["versions"] == {"nhi_drug_atc": "v:23715"}
    icd = json.loads((tmp_path / "tw_icd_2014_2023/fetch.json").read_text())
    assert icd["version"] == "v:177508" and [p["path"] for p in icd["parts"]] == [
        "tw_icd_2014_2023_cm.csv", "tw_icd_2014_2023_pcs.csv"]  # fmt: skip
    assert icd["licence_check"]["license"] == "1"  # the licence field read at fetch time, kept as evidence
    assert nhi["licence_checks"]["nhi_drug_atc"]["license"] == "1"  # the derived item's own record, too
    assert (tmp_path / "tw_zh_synonyms/zh_tw_clinical_synonyms.csv").read_bytes() == tw.REPO_SYNONYMS.read_bytes()


def test_fetch_refuses_a_changed_licence_or_a_pinned_file_that_changed(monkeypatch: pytest.MonkeyPatch,
                                                                         tmp_path: Path) -> None:  # fmt: skip
    def fake_download(url: str, dest: Path, **_: object) -> dict[str, object]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return {"url": url, "downloaded_at": "2026-11-09T00:00:00+00:00", "sha256": "0" * 64, "bytes": 1}

    monkeypatch.setattr(rf, "download", fake_download)
    monkeypatch.setattr(tw, "datagov_meta", lambda url: {"version": "v", "license": "2"})
    with pytest.raises(SystemExit, match="licence '2'"):
        rf.fetch(["naer_medical_terms"], tmp_path)
    monkeypatch.setattr(tw, "datagov_meta", lambda url: {})  # the dataset record did not answer: fail closed
    with pytest.raises(SystemExit, match="licence was not checked"):
        rf.fetch(["naer_medical_terms"], tmp_path)
    with pytest.raises(SystemExit, match="licence was not checked"):
        rf.fetch(["nhi_drug_atc"], tmp_path)  # a derived item's record is checked with its parent's fetch
    # the record's licence covers the file only when the record distributes the URL fetched (NAER: opendata.naer)
    naer = "https://opendata.naer.edu.tw/學術名詞/國家教育研究院-醫學學術名詞.csv"  # as the record lists it, decoded
    monkeypatch.setattr(tw, "datagov_meta", lambda url: {"version": "v", "license": "1", "downloads": [naer]})
    rf.fetch(["naer_medical_terms"], tmp_path)
    assert json.loads((tmp_path / "naer_medical_terms/fetch.json").read_text())["licence_check"]["downloads"] == [naer]
    monkeypatch.setattr(tw, "datagov_meta", lambda url: {"version": "v", "license": "1",
                                                         "downloads": ["https://elsewhere.example/x.csv"]})  # fmt: skip
    with pytest.raises(SystemExit, match="not a download of the dataset record"):
        rf.fetch(["naer_medical_terms"], tmp_path)
    with pytest.raises(SystemExit, match="pinned to sha256"):
        rf.fetch(["nhi_lab_loinc"], tmp_path)  # the 1.3.0 package's sha256 is pinned
    monkeypatch.setattr(tw, "datagov_meta", lambda url: {})  # the dataset API did not answer
    with pytest.raises(SystemExit, match="did not answer"):
        rf.fetch(["naer_medical_terms"], tmp_path)
    rf.fetch(["naer_medical_terms"], tmp_path, licence_check=False)  # explicit: recorded as skipped
    naer = json.loads((tmp_path / "naer_medical_terms/fetch.json").read_text())
    assert naer["licence_check"] == {"skipped": "--no-licence-check"}


# ------------------------------------------------------------------------------------------------ build checks
def test_build_rehashes_every_part_and_requires_the_pcs_file(tmp_path: Path) -> None:
    raw = rf.sample_raw(tmp_path / "raw")
    cm = raw / "tw_icd_2014_2023" / "tw_icd_2014_2023_cm.csv"
    good = cm.read_bytes()
    cm.write_bytes(good.replace(b"A04.71", b"A04.79"))
    with pytest.raises(SystemExit, match="changed after the fetch"):
        rf.build(raw, tmp_path / "o1", "20261109", ids=["tw_icd_2014_2023"], sample=True)
    cm.write_bytes(good)
    (raw / "tw_icd_2014_2023" / "tw_icd_2014_2023_pcs.csv").unlink()
    with pytest.raises(SystemExit, match="tw_icd_2014_2023_pcs.csv is missing"):
        rf.build(raw, tmp_path / "o2", "20261109", ids=["tw_icd_2014_2023"], sample=True)
    with pytest.raises(ValueError, match="missing beside"):
        list(tw.parse_tw_icd_2014_2023(cm))
    # a vendor build (not a sample) checks the pinned sha256 of the PAS package
    with pytest.raises(SystemExit, match="pinned to sha256"):
        rf.build(raw, tmp_path / "o3", "20261109", ids=["nhi_lab_loinc"])
    # ... and refuses an item whose dataset record was not checked at fetch time (the sample has no check)
    with pytest.raises(SystemExit, match="no licence check"):
        rf.build(raw, tmp_path / "o4", "20261109", ids=["naer_medical_terms"])
    with pytest.raises(SystemExit, match="no licence check"):
        rf.build(raw, tmp_path / "o5", "20261109", ids=["nhi_drug_atc"])


def test_build_refuses_zero_records_and_a_changed_shape(tmp_path: Path) -> None:
    raw = rf.sample_raw(tmp_path / "raw")
    f = raw / "naer_medical_terms" / "naer_medical_terms.csv"
    f.write_text("序號,English,Chinese\n1,gout,痛風\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns 英文名稱, 中文名稱 are missing"):
        list(tw.parse_naer_terms(f))
    for bad in ("", "藥品代號,X\n"):
        f.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            list(tw.parse_nhi_drug_atc(f))
    with pytest.raises(ValueError, match="no rows"):
        list(tw.icd_map_rows(b"", pcs=False))
    # a parser that yields nothing (every drug without an ATC code) is refused at build
    nhi = raw / "nhi_drugs" / "nhi_drugs_sample.csv"
    nhi.write_bytes(nhi.read_bytes().replace(b"N05AF01", b""))
    meta = json.loads((raw / "nhi_drugs" / "fetch.json").read_text())
    meta["sha256"] = rd.sha256_file(nhi)
    (raw / "nhi_drugs" / "fetch.json").write_text(json.dumps(meta))
    with pytest.raises(SystemExit, match="0 records"):
        rf.build(raw, tmp_path / "o", "20261109", ids=["nhi_drug_atc"], sample=True)


def test_a_bad_relation_fails_at_verify_not_at_the_hospital(sample_tar: Path, tmp_path: Path) -> None:
    with rd.opened(sample_tar) as p:
        pack = Path(shutil.copytree(p, tmp_path / p.name))
    rel = "nhi_lab_loinc/map.jsonl.gz"
    recs = list(rd.rows(pack, rel))
    recs[0]["relation"] = "related-to"  # an R5 value the box's load refuses
    n = rd.write_jsonl_gz(pack / rel, recs)
    m = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    src = next(s for s in m["sources"] if s["id"] == "nhi_lab_loinc")
    src["files"] = [rd.file_entry(pack, rel, n)]
    (pack / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(rd.PackError, match="relation 'related-to'"):
        rd.verify(pack)


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
    # the newest validity period left the ATC empty: the newest period that states one gives the map row
    old = line("A5", "C10AA05").replace("1150101", "1100101")
    f.write_text("\n".join([head, old, line("A5", "")]))
    (row,) = tw.parse_nhi_drug_atc(f)
    assert row["target_code"] == "C10AA05" and row["extra"]["valid_from"] == "2021-01-01"


def test_icd_2014_2023_relations(tmp_path: Path) -> None:
    raw = rf.sample_raw(tmp_path / "raw")
    rows = list(tw.parse_tw_icd_2014_2023(raw / "tw_icd_2014_2023" / "tw_icd_2014_2023_cm.csv"))
    rel = {(r["source_code"], r["target_code"]): r["relation"] for r in rows if r["source_system"] == tw.ICD_CM_2014}
    assert rel[("A00.0", "A00.0")] == "equivalent" and rel[("M10.9", "M10.9")] == "equivalent"
    assert rel[("A04.7", "A04.71")] == rel[("A04.7", "A04.72")] == "narrower"  # one 2014 code split in two
    assert {rel[("I10", c)] for c in ("I10", "I16.0", "I16.1", "I16.9")} == {"narrower"}
    assert rel[("B18.1", "B18.1")] == "equivalent"  # NHIA's later added mapping does not make it a merge
    assert rel[("Z22.51", "B18.1")] == "relatedto"  # 增列對應: carrier -> chronic hepatitis B is a candidate only
    assert rel[("Z22.50", "")] == "unmatched"  # deleted, no 2023 code: a row without a target
    assert rel[("P83.8", "P83.88")] == "inexact" and rel[("T84.040A", "M97.01XA")] == "inexact"
    a047 = next(r for r in rows if r["source_code"] == "A04.7")
    assert a047["extra"]["status_2014"] == "2014代碼改為不可用" and a047["extra"]["target_zh"].startswith("艱難梭菌")
    assert any(r["source_system"] == tw.ICD_PCS_2014 for r in rows)  # the PCS file beside it
    with pytest.raises(ValueError, match="the source changed shape"):
        list(tw.icd_map_rows(b"a,b\n1,2\n", pcs=False))


def test_nhi_lab_loinc_reads_the_cc0_conceptmap_and_refuses_another_licence(tmp_path: Path) -> None:
    rows = list(tw.parse_nhi_lab_loinc(SAMPLES / "nhi_pas_sample"))
    creat = sorted(r["target_code"] for r in rows if r["source_code"] == "09015C")
    assert "2160-0" in creat and len(creat) > 1 and {r["relation"] for r in rows} == {"relatedto"}
    assert all(r["source_system"] == tw.NHI_SERVICE and r["target_display"] == "" for r in rows)  # codes only
    assert rows[0]["extra"]["loinc_version"] == "2.77"
    bad = Path(shutil.copytree(SAMPLES / "nhi_pas_sample", tmp_path / "pkg"))
    pkg = json.loads((bad / "package.json").read_text(encoding="utf-8"))
    (bad / "package.json").write_text(json.dumps(pkg | {"license": "CC-BY-NC-4.0"}), encoding="utf-8")
    with pytest.raises(ValueError, match="do not ship"):
        list(tw.parse_nhi_lab_loinc(bad))


def _pas_with_target(tmp_path: Path, target: dict[str, str]) -> Path:
    pkg = Path(shutil.copytree(SAMPLES / "nhi_pas_sample", tmp_path / "pkg5"))
    cm = json.loads((pkg / "ConceptMap-nhi-loinc.json").read_text(encoding="utf-8"))
    cm["group"][0]["element"] = [{"code": "09015C", "display": "肌酸酐、血", "target": [target]}]
    (pkg / "ConceptMap-nhi-loinc.json").write_text(json.dumps(cm), encoding="utf-8")
    return pkg


def test_a_later_ig_with_r5_relationships_and_loinc_names(tmp_path: Path) -> None:
    pkg = _pas_with_target(tmp_path, {"code": "2160-0", "display": "Creatinine [Mass/volume] in Serum or Plasma",
                                      "relationship": "related-to"})  # fmt: skip
    (row,) = tw.parse_nhi_lab_loinc(pkg)
    assert row["relation"] == "relatedto" and row["target_display"] == ""  # R5 -> R4; never a LOINC name
    pkg = _pas_with_target(tmp_path / "b", {"code": "2160-0", "relationship": "made-up"})
    with pytest.raises(ValueError, match="unknown relation"):
        list(tw.parse_nhi_lab_loinc(pkg))
    pkg = _pas_with_target(tmp_path / "c", {"display": "no code", "equivalence": "relatedto"})
    with pytest.raises(ValueError, match="without a code"):
        list(tw.parse_nhi_lab_loinc(pkg))
    for i, t in enumerate(({"equivalence": "unmatched"}, {"relationship": "not-related-to"},
                           {"code": "2160-0", "equivalence": "disjoint"})):  # fmt: skip
        assert list(tw.parse_nhi_lab_loinc(_pas_with_target(tmp_path / f"u{i}", t))) == []  # no match: skipped
    pkg = _pas_with_target(tmp_path / "e", {"code": "2160-0", "equivalence": "relatedto"})
    cm = json.loads((pkg / "ConceptMap-nhi-loinc.json").read_text(encoding="utf-8"))
    cm["group"][0]["source"] = "urn:other"
    (pkg / "ConceptMap-nhi-loinc.json").write_text(json.dumps(cm), encoding="utf-8")
    with pytest.raises(ValueError, match="no group from"):  # site set-up asks the NHI system: refuse, not 0 rows
        list(tw.parse_nhi_lab_loinc(pkg))


def test_synonyms_naer_split_and_curated_flag() -> None:
    naer = list(tw.parse_naer_terms(SAMPLES / "naer_medical_terms_sample.csv"))
    stroke = sorted(r["term"] for r in naer if r["canonical"] == "stroke")
    assert stroke == ["中風", "猝發", "發作"] and not any(r["curated"] for r in naer)
    own = list(tw.parse_zh_tw_synonyms(tw.REPO_SYNONYMS))
    review = {r["term"] for r in own if not r["curated"]}
    assert len(own) == 42 and review == {"RA", "MI", "CVA", "GPT", "MTX"}  # ambiguous abbreviations: reviewed
    assert {(r["term"], r["canonical"]) for r in own} >= {("類風濕關節炎", "rheumatoid arthritis"), ("SGPT", "alt")}


def _own_lookup() -> Any:
    own = list(tw.parse_zh_tw_synonyms(tw.REPO_SYNONYMS))

    def lookup(term: str, domain: str = "") -> list[dict[str, Any]]:
        return [r | {"source_id": "tw_zh_synonyms"} for r in own
                if rd.norm_name(r["term"]) == rd.norm_name(term) and r["domain"] in ("", domain)]  # fmt: skip

    return lookup


def test_a_curated_word_beats_a_single_display_match() -> None:
    t = Terminology(name_synonyms=_own_lookup())
    hf = t.map("condition", "心衰竭")  # the zh display of I50.9 alone; the word means the I50 family
    assert hf.method == "synonym" and not hf.needs_review and len(hf.concepts) > 1
    assert ("http://hl7.org/fhir/sid/icd-10-cm", "I50") in hf.families
    assert Terminology().map("condition", "心衰竭").method == "exact"  # without the dictionary: unchanged
    assert t.map("observation", "收縮壓").method == "exact"  # the same code set either way: the display stays


def test_every_trusted_synonym_term_maps_like_its_canonical_name() -> None:
    """The term itself, through the dictionary, gets the canonical name's codes: an exact display hit on one code
    (心衰竭 = I50.9) must not hide the canonical grouper (heart failure = the I50 family)."""
    rows = list(tw.parse_zh_tw_synonyms(tw.REPO_SYNONYMS))

    def lookup(term: str, domain: str = "") -> list[dict[str, object]]:
        n = rd.norm_name(term)
        return [{**r, "source_id": "tw_zh_synonyms"} for r in rows
                if rd.norm_name(r["term"]) == n and (not domain or r["domain"] == domain)]  # fmt: skip

    t, plain = Terminology(name_synonyms=lookup), Terminology()
    off = []
    for r in rows:
        if not r["curated"]:
            continue
        got, want = t.map(r["domain"], r["term"]), plain.map(r["domain"], r["canonical"])
        if {c.code for c in got.concepts} != {c.code for c in want.concepts} or got.needs_review:
            off.append((r["term"], got.method, len(got.concepts), len(want.concepts)))
    assert off == []


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
        bs = st.synonyms(" 減重手術 ", "procedure")
        assert [(s["canonical"], s["curated"]) for s in bs] == [("bariatric surgery", True)]
        assert st.synonyms("減重手術", "condition") == []  # another domain
        assert {s["canonical"] for s in st.synonyms("ｎｓｃｌｃ")} == {"non-small cell lung cancer"}  # NFKC + case
        assert {s["source_id"] for s in st.synonyms("中風")} == {"naer_medical_terms", "tw_zh_synonyms"}
        status = {s["source_id"]: s for s in (st.status() or {})["sources"]}
        assert (
            status["nhi_lab_loinc"]["version"].endswith("LOINC 2.77")
            and len(status["nhi_lab_loinc"]["download_sha256"]) == 64
        )
        notes = {n["id"]: n for n in st.notices()}
        assert notes["tw_icd_2014_2023"]["version"] == "sample" and notes["naer_medical_terms"]["kind"] == "synonym"


def test_a_2014_code_against_a_2023_list_is_unknown_when_split(loaded: str) -> None:
    with rd.RefStore(loaded) as st:
        i10 = st.map_targets(tw.ICD_CM_2014, "I10")
        a047 = st.map_targets(tw.ICD_CM_2014, "A04.7")
        lab = st.map_targets(tw.NHI_SERVICE, "09015C")
    only_i10 = {(tw.ICD_CM_2023, "I10")}
    all_htn = {(tw.ICD_CM_2023, c) for c in ("I10", "I16.0", "I16.1", "I16.9")}
    assert rd.in_set_via_map(i10, all_htn) == "yes"  # every part of the split is in the list
    assert rd.in_set_via_map(i10, only_i10) == "unknown"  # 2014 I10 may have been a hypertensive crisis
    assert rd.in_set_via_map(a047, only_i10) == "no"
    assert rd.in_set_via_map([], only_i10) == "unknown"  # a code the map does not know never excludes
    # NHI lab candidates (relatedto) never decide, in or out of the list
    assert rd.in_set_via_map(lab, {(tw.LOINC, "2160-0")}) == "unknown"
    assert rd.in_set_via_map(lab, {(tw.LOINC, "0000-0")}) == "unknown"
    with rd.RefStore(loaded) as st:
        gone = st.map_targets(tw.ICD_CM_2014, "Z22.50")  # deleted, no 2023 code
        a000 = st.map_targets(tw.ICD_CM_2014, "A00.0")
    assert [t["relation"] for t in gone] == ["unmatched"] and rd.in_set_via_map(gone, only_i10) == "unknown"
    # a list in another system (HL7 ICD-10-CM) is not a list the map can say "no" about
    assert rd.in_set_via_map(a000, {("http://hl7.org/fhir/sid/icd-10-cm", "A00.0")}) == "unknown"
    # a prefix family of the list (a ruleset's grouper) counts as inside
    assert rd.in_set_via_map(a000, set(), families=[(tw.ICD_CM_2023, "A00")]) == "yes"
    assert rd.in_set_via_map(a000, set(), families=[(tw.ICD_CM_2023, "B")]) == "no"
    assert rd.in_set_via_map(i10, set(), families=[(tw.ICD_CM_2023, "I1")]) == "yes"  # I10 and every I16


def _t(code: str, relation: str) -> dict[str, str]:
    return {"target_system": "s", "target_code": code, "relation": relation}


@pytest.mark.parametrize(
    ("rows", "want_in", "want_out"),
    [
        ([_t("A", "equivalent")], "yes", "no"),
        ([_t("A", "equal")], "yes", "no"),
        ([_t("A", "wider")], "yes", "unknown"),  # out: the wider class missing says nothing about the code
        ([_t("A", "subsumes")], "yes", "unknown"),
        ([_t("A", "narrower")], "yes", "no"),  # the only part of the source, in or out
        ([_t("A", "specializes")], "yes", "no"),
        ([_t("A", "inexact")], "unknown", "unknown"),
        ([_t("A", "relatedto")], "unknown", "unknown"),
        ([_t("A", "unmatched")], "unknown", "unknown"),
        ([_t("A", "narrower"), _t("B", "narrower")], "unknown", "no"),  # A in, B out: a split half in the list
        ([_t("A", "equivalent"), _t("B", "unmatched")], "yes", "no"),  # unmatched rows are dropped
    ],
)
def test_in_set_via_map_per_relation(rows: list[dict[str, str]], want_in: str, want_out: str) -> None:
    assert rd.in_set_via_map(rows, {("s", "A")}) == want_in
    assert rd.in_set_via_map(rows, {("s", "Z")}) == want_out


def test_in_set_via_map_never_says_no_across_systems_or_families() -> None:
    eq = [{"target_system": tw.ICD_CM_2023, "target_code": "E11.9", "relation": "equivalent"}]
    hl7 = "http://hl7.org/fhir/sid/icd-10-cm"
    # a list in another code system cannot rule the code out
    assert rd.in_set_via_map(eq, {(hl7, "E11.9")}) == "unknown"
    assert rd.in_set_via_map(eq, set(), families=[(hl7, "E11")]) == "unknown"
    # a prefix family in the targets' system holds the code
    assert rd.in_set_via_map(eq, set(), families=[(tw.ICD_CM_2023, "E11")]) == "yes"
    assert rd.in_set_via_map(eq, set(), families=[(tw.ICD_CM_2023, "E10")]) == "no"
    assert rd.in_set_via_map(eq, {(tw.ICD_CM_2023, "I10")}, families=[(tw.ICD_CM_2023, "E11")]) == "yes"


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
    sgpt = with_dict.map("observation", "SGPT")  # TW usage: SGPT = ALT
    assert sgpt.method == "synonym" and not sgpt.needs_review and {c.code for c in sgpt.concepts} == {"1742-6"}
    # an ambiguous abbreviation (GPT, MI) or a NAER translation (猝發 -> stroke): method dictionary, reviewed
    for domain, term in (("observation", "GPT"), ("condition", "MI"), ("condition", "猝發")):
        res = with_dict.map(domain, term)
        assert res.method == "dictionary" and res.needs_review and res.concepts, term
    assert with_dict.map("condition", "痛風").method in ("exact", "synonym")  # the curated table still wins


def test_a_naer_sense_never_pre_empts_the_curated_table_on_the_models_synonym(loaded: str) -> None:
    with_dict = Terminology(name_synonyms=rd.synonym_lookup(loaded))
    res = with_dict.map("condition", "發作", synonyms=["gout"])  # NAER: 發作 -> stroke; the model says gout
    assert res == Terminology().map("condition", "發作", synonyms=["gout"])
    assert res.method == "synonym" and not res.needs_review and all(c.code.startswith("M1") for c in res.concepts)


def test_a_dead_curated_entry_does_not_hide_the_others() -> None:
    entries = [{"canonical": "no such name", "curated": True, "source_id": "own"},
               {"canonical": "stroke", "curated": False, "source_id": "naer"}]  # fmt: skip

    def lookup(name: str, domain: str = "") -> list[dict[str, Any]]:
        return entries

    res = Terminology(name_synonyms=lookup).map("condition", "x")
    assert res.method == "dictionary" and res.needs_review and res.concepts and "naer" in res.notes[0]


def test_a_failing_shared_store_is_dropped_and_reopened_later(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        closed = False

        def synonyms(self, term: str, domain: str = "") -> list[dict[str, Any]]:
            raise ConnectionError("server closed the connection")

        def close(self) -> None:
            self.closed = True

    st = Broken()
    monkeypatch.setattr(rd, "_SHARED", {"postgresql://x/db": st})
    monkeypatch.setattr(rd, "_FAILED", {})
    assert rd.synonyms_or_empty("中風", url="postgresql://x/db") == []
    assert rd._SHARED == {} and st.closed and "postgresql://x/db" in rd._FAILED  # not kept for the next lookup
    assert rd.shared("postgresql://x/db") is None  # the 60-second pause, then a fresh store


def test_the_matcher_without_a_database_is_unchanged(loaded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert Terminology(name_synonyms=rd.synonym_lookup(loaded)).map("condition", "類風濕關節炎").method == "synonym"
    monkeypatch.delenv("TB_DB_URL", raising=False)
    t = Terminology(name_synonyms=rd.synonym_lookup())  # no database: the same answer as no dictionary at all
    assert t.map("condition", "類風濕關節炎") == Terminology().map("condition", "類風濕關節炎")


# ------------------------------------------------------------------------------------------------ site set-up
def test_site_setup_suggests_from_the_taiwan_maps(loaded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sm, "site_country", lambda: "TW")
    drug = sm.suggest("medication", sm.local_system("drug-code"), "B004858100")
    assert drug["code"] == "N05AF01" and drug["method"] == "refdata" and drug["confidence"] == "0.90"
    creat = sm.suggest("observation", sm.local_system("lab-code"), "09015C")  # several candidates: a person picks
    assert creat.get("method") != "refdata"
    psa = sm.suggest("observation", sm.local_system("lab-code"), "12198C")  # one target
    assert psa["code"] == "83113-1" and psa["confidence"] == "0.90" and psa["display"] == ""  # no NHI name as LOINC
    assert sm.suggest("condition", sm.local_system("dx-code"), "Z22.50") == {}  # deleted: never "same"
    moved = sm.suggest("condition", sm.local_system("dx-code"), "P83.8")  # gone in 2023, one new code
    assert moved["code"] == "P83.88" and moved["method"] == "refdata"
    assert sm.suggest("condition", sm.local_system("dx-code"), "A04.7") == {}  # split: the coordinator picks
    assert sm.suggest("condition", sm.local_system("dx-code"), "Z22.51") == {}  # NHIA's added mapping: no pick
    assert sm.suggest("condition", sm.local_system("dx-code"), "I10")["method"] == "same"  # still a 2023 code


def test_the_2014_step_runs_at_taiwan_sites_only(loaded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    for country in ("JP", None):
        monkeypatch.setattr(sm, "site_country", lambda c=country: c)
        assert sm.suggest("condition", sm.local_system("dx-code"), "P83.8")["method"] == "same"
        assert sm.suggest("condition", sm.local_system("dx-code"), "A04.7")["method"] == "same"


def test_the_method_has_a_label_in_three_languages() -> None:
    from console.i18n_site import EN, JA, ZH

    assert all(d.get("site.codes.method.refdata") for d in (EN, JA, ZH))


def test_a_version_1_refdata_schema_is_migrated(db_url: str, tmp_path: Path) -> None:
    from tb_common.db import Database

    db = Database.connect(db_url, rd.SCHEMA)
    db.migrate([rd.DDL])  # a box from before D-170, with a source and a term
    db.execute("INSERT INTO source (source_id, pack_id, name, kind, distribution, records, url, downloaded_at, "
               "licence, attribution) VALUES ('old', 'trialbox-refdata-20261101', 'Old', 'term', 'ship', 1, 'u', "
               "'2026-11-01', 'l', 'a')")  # fmt: skip
    db.execute("INSERT INTO term (system, code, display, extra, source_id) VALUES ('s', 'c', 'd', '{}', 'old')")
    db.close()
    tar = rf.build(rf.sample_raw(tmp_path / "raw"), tmp_path, "20261109", sample=True)
    with rd.opened(tar) as p, rd.RefStore(db_url) as st:
        st.load(p)
        assert st.term("s", "c") == {"system": "s", "code": "c", "display": "d", "extra": {}}
        old = st.db.fetchdicts("SELECT version, download_sha256 FROM source WHERE source_id = 'old'")
        assert old == [{"version": "", "download_sha256": ""}]
        assert st.map_targets(tw.NHI_DRUG, "B004858100")


def test_site_setup_without_reference_data_is_unchanged() -> None:
    assert sm.suggest("medication", sm.local_system("drug-code"), "B004858100") == {}
    assert sm.suggest("condition", sm.local_system("dx-code"), "P83.8")["method"] == "same"
