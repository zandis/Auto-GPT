"""Japan reference data items (D-173 to D-175): the WHO ICD-10 <-> ICD-10-CM bridge, YJ -> ATC, CTCAE v5.0, the ja
synonyms, and the site-fetch loaders for MEDIS 病名, JLAC10 -> LOINC and the JCOG CTCAE translation. Fixtures are
synthetic, the repository's own tables, or a six-term excerpt of NCI's public-domain CTCAE workbook."""

from __future__ import annotations

import csv
import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.terminology.mapper import Terminology
from sitesetup import mapping as sm
from tb_common import refdata as rd
from tb_common import refdata_jp as jp
from tb_common import refdata_tw as tw

from tools import refdata_fetch as rf

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "tests" / "fixtures" / "refdata"
SHIP = ("icd10_who_cm_bridge", "jp_yj_atc", "ctcae_v5_en", "ja_synonyms")
SITE = ("medis_byomei_icd10", "jlac10_loinc", "ctcae_v5_ja_jcog")


@pytest.fixture(scope="module")
def sample_tar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("jppack")
    return rf.build(rf.sample_raw(out / "raw"), out, "20261109", sample=True)


@pytest.fixture
def loaded(sample_tar: Path, db_url: str) -> str:
    with rd.opened(sample_tar) as p, rd.RefStore(db_url) as st:
        st.load(p, by="test")
    return db_url


def _write(path: Path, rows: list[list[str]], encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding=encoding) as fh:
        csv.writer(fh).writerows(rows)
    return path


# ------------------------------------------------------------------------------------------------ the registry
def test_each_item_is_registered_with_its_licence_decision_and_loader() -> None:
    by = rf.BY_ID
    for sid in SHIP + SITE:
        s = by[sid]
        assert s.country == "JP" and s.parse is not None and s.decision in ("D-173", "D-174", "D-175")
        assert s.licence and s.terms and s.attribution and s.url
        assert s.name in rf.table_md()
    assert all(by[sid].distribution == "ship" for sid in SHIP)
    # what the licence forbids is never shipped: a loader for the hospital's own file, and nothing to fetch
    for sid in SITE:
        assert by[sid].distribution == "site-fetch" and not by[sid].fetch
        with pytest.raises(SystemExit, match="site-fetch"):
            rf.fetch([sid], Path("/nonexistent"))
    assert by["icd10_who_cm_bridge"].derived_from == "icd10cm"  # read from the ICD-10-CM download
    assert by["ctcae_v5_en"].sha256 and by["ctcae_v5_en"].licence_reader is not None


def test_nothing_from_medis_jlac_or_jcog_is_committed_as_data() -> None:
    """The repository holds no MEDIS 病名, JLAC10 or JCOG translation file: only the loaders and synthetic tests."""
    src = ROOT / "libs" / "tb_common" / "refdata_src"
    assert sorted(p.name for p in src.iterdir()) == sorted(
        ["zh_tw_clinical_synonyms.csv", "jp_yj_atc.csv", "icd10_who_cm_checked.csv", "ja_clinical_synonyms.csv",
         "holidays_jp.csv"]  # 10C-14: the Cabinet Office's public holiday list (PDL 1.0, register row jp-holidays)
    )  # fmt: skip


def test_a_vendor_build_never_packs_the_hospitals_own_download(tmp_path: Path) -> None:
    """site-load leaves the hospital's MEDIS file and fetch.json under <out>/raw; a later vendor build over the same
    raw directory must leave it out, and naming it is refused (review High of PR #76)."""
    f = _write(tmp_path / "dl" / "byomei.csv", [["病名交換用コード", "病名表記", "ICD10-2013"], ["ZZ01", "x", "E11.9"]])
    rf.site_load("medis_byomei_icd10", f, tmp_path / "cache", load=False)
    rf.site_load("umin_ctr", SAMPLES / "umin_sample.csv", tmp_path / "cache", load=False)
    raw = tmp_path / "cache" / "raw"
    assert (raw / "medis_byomei_icd10" / "fetch.json").is_file() and (raw / "umin_ctr" / "fetch.json").is_file()
    shutil.copytree(rf.sample_raw(tmp_path / "s" / "raw"), raw, dirs_exist_ok=True)
    tar = rf.build(raw, tmp_path / "vendor", "20261110", sample=True)
    with rd.opened(tar) as pack:
        ids = {s["id"] for s in rd.verify(pack)["sources"]}
        assert not any(p.name.startswith(("medis", "umin")) for p in pack.iterdir())
    assert "medis_byomei_icd10" not in ids and "umin_ctr" not in ids and "jp_yj_atc" in ids
    for sid in ("medis_byomei_icd10", "umin_ctr"):
        with pytest.raises(SystemExit, match="never packs a site-fetch"):
            rf.build(raw, tmp_path / "v2", "20261110", ids=[sid], sample=True)
    with pytest.raises(SystemExit, match="site-fetch items only"):
        rf.build(raw, tmp_path / "v3", "20261110", ids=["jp_yj_atc"], site=True)


# ------------------------------------------------------------------------------------------------ the licence reader
def test_the_licence_reader_lives_on_the_item_and_fetch_keeps_its_evidence(monkeypatch: pytest.MonkeyPatch,
                                                                            tmp_path: Path) -> None:  # fmt: skip
    def fake_download(url: str, dest: Path, **_: object) -> dict[str, object]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return {"url": url, "downloaded_at": "2026-11-10T00:00:00+00:00", "sha256": "0" * 64, "bytes": 1}

    reads: list[str] = []

    def reader(ok: bool, answer: bool = True, downloads: tuple[str, ...] = ()) -> Any:
        def read(item: rd.Item) -> rd.LicenceRead | None:
            reads.append(item.id)
            got = rd.LicenceRead("https://x/terms", "free" if ok else "paid", "free", ok, "", downloads)
            return got if answer else None

        return read

    monkeypatch.setattr(rf, "download", fake_download)
    item = rf.BY_ID["ctcae_v5_en"]
    for ok, answer, err in ((False, True, "now reads 'paid'"), (True, False, "could not be read")):
        monkeypatch.setitem(rf.BY_ID, "ctcae_v5_en", rd.Item(**{**item.__dict__, "licence_reader": reader(ok, answer),
                                                                 "sha256": ""}))  # fmt: skip
        with pytest.raises(SystemExit, match=err):
            rf.fetch(["ctcae_v5_en"], tmp_path)
    # a licence read that lists no download binds nothing: without a sha256 pin the file is refused (fail closed)
    monkeypatch.setitem(rf.BY_ID, "ctcae_v5_en", rd.Item(**{**item.__dict__, "licence_reader": reader(True),
                                                             "sha256": ""}))  # fmt: skip
    with pytest.raises(SystemExit, match="lists no download"):
        rf.fetch(["ctcae_v5_en"], tmp_path)
    monkeypatch.setitem(
        rf.BY_ID,
        "ctcae_v5_en",
        rd.Item(**{**item.__dict__, "sha256": "", "licence_reader": reader(True, True, (item.url,))}),
    )
    rf.fetch(["ctcae_v5_en"], tmp_path)
    meta = json.loads((tmp_path / "ctcae_v5_en/fetch.json").read_text())
    assert meta["licence_check"] == {"url": "https://x/terms", "read": "free", "expected": "free", "ok": True,
                                     "version": "", "downloads": [item.url]}  # fmt: skip
    assert meta["licence_checks"]["ctcae_v5_en"] == meta["licence_check"]
    monkeypatch.setitem(
        rf.BY_ID,
        "ctcae_v5_en",
        rd.Item(**{**item.__dict__, "sha256": "", "licence_reader": reader(True, True, ("https://y/z",))}),
    )
    with pytest.raises(SystemExit, match="not a download of the dataset record"):
        rf.fetch(["ctcae_v5_en"], tmp_path)
    assert reads == ["ctcae_v5_en"] * 5
    # an item without a reader (our own tables) reads nothing; the Taiwan items read data.gov.tw through theirs
    assert rf.read_licence(rf.BY_ID["jp_yj_atc"]) is None
    assert rf.BY_ID["naer_medical_terms"].licence_reader is tw.datagov_tw_licence
    naer = rf.BY_ID["naer_medical_terms"]  # a dataset API URL without a reader is refused, never skipped
    with pytest.raises(SystemExit, match="no licence reader"):
        rf.read_licence(rd.Item(**{**naer.__dict__, "licence_reader": None}))


def test_a_pinned_file_needs_no_listed_download_and_build_refuses_an_unchecked_item(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One licence mechanism for Taiwan and Japan (merge of D-170's second review with D-173): a licence page that
    lists no download (NCI) binds the file through the item's sha256 pin; a vendor build refuses an item with a
    licence reader whose fetch.json holds no check."""
    item = rf.BY_ID["ctcae_v5_en"]

    def fake_download(url: str, dest: Path, **_: object) -> dict[str, object]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return {"url": url, "downloaded_at": "2026-11-10T00:00:00+00:00", "sha256": item.sha256, "bytes": 1}

    monkeypatch.setattr(rf, "download", fake_download)
    monkeypatch.setitem(rf.BY_ID, "ctcae_v5_en", rd.Item(**{**item.__dict__, "licence_reader": lambda i: rd.LicenceRead(
        "https://p", "free of copyright", "free of copyright", True)}))  # fmt: skip
    rf.fetch(["ctcae_v5_en"], tmp_path)
    meta = json.loads((tmp_path / "ctcae_v5_en/fetch.json").read_text())
    assert meta["licence_check"]["ok"] and meta["licence_check"]["downloads"] == []
    meta.pop("licence_check")
    meta.pop("licence_checks")
    real = rd.sha256_file(tmp_path / "ctcae_v5_en" / meta["path"])  # unpin, so build reaches the licence check
    meta["sha256"] = meta["parts"][0]["sha256"] = real
    (tmp_path / "ctcae_v5_en/fetch.json").write_text(json.dumps(meta))
    monkeypatch.setitem(rf.BY_ID, "ctcae_v5_en", rd.Item(**{**rf.BY_ID["ctcae_v5_en"].__dict__, "sha256": ""}))
    with pytest.raises(SystemExit, match="no licence check"):
        rf.build(tmp_path, tmp_path / "out", "20261110", ids=["ctcae_v5_en"])


def test_the_page_reader_needs_every_marker(tmp_path: Path) -> None:
    page = {"url": "https://p/", "repeat": True,
            "body": {"text": "Unless otherwise indicated, all text ... is free of copyright"}}  # fmt: skip
    (tmp_path / "page.json").write_text(json.dumps({"interactions": [page]}), encoding="utf-8")
    item = rf.BY_ID["ctcae_v5_en"]
    with rd.replay(tmp_path / "page.json"):  # through the fetch's one HTTP client (D-317)
        assert rd.page_licence_reader("https://p/", "free of copyright")(item) == rd.LicenceRead(
            "https://p/", "free of copyright", "free of copyright", True
        )
        got = rd.page_licence_reader("https://p/", "free of copyright", "no fee")(item)
        assert got is not None and not got.ok
        assert rd.page_licence_reader("https://q/", "x")(item) is None  # no answer (not in the cassette)


# ------------------------------------------------------------------------------------------------ the pack
def test_the_pack_records_version_and_sha256_for_each_japan_item(sample_tar: Path) -> None:
    with rd.opened(sample_tar) as pack:
        m = rd.verify(pack)
        notice = (pack / "NOTICE.md").read_text(encoding="utf-8")
    src = {s["id"]: s for s in m["sources"]}
    assert not set(SITE) & set(src)  # the site-fetch items are never in the vendor's pack
    for sid in SHIP:
        s = src[sid]
        assert s["version"] and len(s["download_sha256"]) == 64 and s["country"] == "JP" and s["records"] > 0
        assert f"* Version: {s['version']}" in notice and s["download_sha256"] in notice
    assert src["jp_yj_atc"]["version"].startswith("TrialBox YJ stem to ATC, 56 entries")
    assert src["ctcae_v5_en"]["version"] == "CTCAE v5.0 (NCI, 2017-11-27), terms of MedDRA v20.1"
    assert src["ctcae_v5_en"]["records"] == 6 and "free of copyright" in notice.lower()


# ------------------------------------------------------------------------------------------------ D-173 bridge
def test_the_bridge_says_wider_only_for_checked_categories(tmp_path: Path) -> None:
    import zipfile

    z = tmp_path / "icd10cm-code-descriptions-2027.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("x/icd10cm-codes-2027.txt",
                    "E119    Type 2 diabetes mellitus without complications\nE1165   T2DM with hyperglycemia\n"
                    "E139    Other specified diabetes mellitus without complications\nO24410  GDM\n"
                    "Z87891  Personal history of nicotine dependence\nI10     Essential hypertension\n"
                    "A099    Infectious gastroenteritis and colitis, unspecified\nM1000   Idiopathic gout\n"
                    "C7A010  Malignant carcinoid tumor of the duodenum\nC170    Malignant neoplasm of duodenum\n")  # fmt: skip
    rows = {r["source_code"]: r for r in jp.parse_icd10_who_cm_bridge(z)}
    assert sorted(rows) == ["A09", "C17", "C7A", "E11", "E13", "I10", "M10", "O24", "Z87"]
    assert (
        rows["E11"]["relation"] == "wider" and rows["E11"]["target_code"] == "E11" and rows["E11"]["extra"]["checked"]
    )
    assert rows["E11"]["source_system"] == jp.ICD10_WHO and rows["E11"]["target_system"] == jp.ICD10CM
    assert {c for c, r in rows.items() if r["relation"] == "wider"} == {"E11", "I10"}
    # scope differs: WHO A09 holds unspecified diarrhoea (CM: K52.9); WHO M10 holds chronic gout (CM: M1A); WHO C17
    # holds carcinoid of the small intestine (CM: C7A); WHO E13 holds what CM puts under E08 / E09
    for c in ("A09", "M10", "C17", "E13", "O24", "Z87"):
        assert rows[c]["relation"] == "inexact", c
    assert all(r["source_display"] == "" and r["target_display"] == "" for r in rows.values())  # code strings only
    assert jp.bridge_version(z).startswith("ICD-10-CM FY2027 categories; TrialBox checked list sha256 ")


def test_the_checked_list_holds_no_category_known_to_differ(tmp_path: Path) -> None:
    checked = jp.bridge_checked()
    assert len(checked) == 36 and all(note for note in checked.values())
    assert not {"A09", "M10", "E13", "E14", "J46", "G41"} & set(checked)
    assert not any(c[0] in "CDOUVWXYZ" for c in checked)  # neoplasms (C7A, D3A) and restructured chapters
    bad = tmp_path / "checked.csv"
    bad.write_text("category,note\nE11.9,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="3-character"):
        jp.bridge_checked(bad)


def test_a_who_code_is_in_its_family_or_unknown_never_no(loaded: str) -> None:
    fam = [(jp.ICD10CM, "E11")]
    # the sample ICD-10-CM list has M10, M1A, E11, I10... categories (tests/fixtures/refdata/icd10cm_sample.txt)
    assert jp.who_icd10_in_list("E11.9", set(), fam, loaded) == "yes"  # WHO E11.9 is inside the CM E11 family
    assert jp.who_icd10_in_list("E11.9", {(jp.ICD10CM, "E11.9")}, (), loaded) == "unknown"  # exact codes only
    assert jp.who_icd10_in_list("I10", {(jp.ICD10CM, "M10.9")}, [(jp.ICD10CM, "M10")], loaded) == "unknown"
    assert jp.who_icd10_in_list("E14.9", set(), [(jp.ICD10CM, "E1")], loaded) == "unknown"  # WHO-only category
    assert jp.who_icd10_targets("not a code", loaded) == []
    # a category not checked (M10: WHO M10 also holds chronic gout, CM M1A): inexact, never yes, never no
    assert jp.who_icd10_in_list("M10.9", set(), [(jp.ICD10CM, "M10")], loaded) == "unknown"


# ------------------------------------------------------------------------------------------------ D-173 MEDIS
def test_medis_loader_reads_a_headerless_shift_jis_release(tmp_path: Path) -> None:
    """A synthetic file shaped like a MEDIS release (Shift_JIS, no header row): the site gives the columns."""
    f = _write(tmp_path / "medis" / "NMAIN.TXT",
               [["1", "ZZ01", "テスト病名一", "E119", "8800001"], ["1", "ZZ02", "テスト病名二", "", "8800002"],
                ["1", "ZZ03", "テスト病名三", "XYZ", "8800003"], ["1", "BAD", "x", "I10", ""]],
               encoding="cp932")  # fmt: skip
    with pytest.raises(ValueError, match="no header row"):
        list(jp.parse_medis_byomei(f))
    (f.parent / "columns.txt").write_text(
        "変更区分,病名交換用コード,病名表記,ICD10-2013,傷病名コード", encoding="utf-8"
    )
    rows = list(jp.parse_medis_byomei(f))
    assert [(r["source_code"], r["target_code"], r["relation"]) for r in rows] == [("ZZ01", "E11.9", "wider")]
    assert rows[0]["source_display"] == "テスト病名一" and rows[0]["extra"] == {"receipt_code": "8800001"}


def test_site_load_of_medis_keeps_the_hospitals_part_and_shows_it_on_the_notice(loaded: str, tmp_path: Path) -> None:
    f = _write(tmp_path / "dl" / "byomei.csv",
               [["病名交換用コード", "病名表記", "ICD10-2013"], ["ZZ01", "テスト病名一", "E11.9"]])  # fmt: skip
    tar = rf.site_load("medis_byomei_icd10", f, tmp_path / "site", db_url=loaded, version="Ver.9.99 (synthetic)")
    assert "site-medis-byomei-icd10" in tar.name
    with rd.RefStore(loaded) as st:
        got = st.map_targets(jp.MEDIS_BYOMEI, "ZZ01")
        notes = {n["id"]: n for n in st.notices()}
    assert [(t["target_system"], t["target_code"]) for t in got] == [(jp.ICD10_WHO, "E11.9")]
    medis = notes["medis_byomei_icd10"]
    assert medis["distribution"] == "site-fetch" and medis["version"] == "Ver.9.99 (synthetic)"
    assert "使用許諾申請書" in medis["terms"] and len(medis["download_sha256"]) == 64
    assert "jp_yj_atc" in notes  # the vendor's pack is still there beside the hospital's part


# ------------------------------------------------------------------------------------------------ D-174 YJ -> ATC
def test_the_yj_table_is_one_ingredient_per_stem_with_full_atc_codes() -> None:
    rows = list(jp.parse_jp_yj_atc(jp.REPO_YJ_ATC))
    assert len(rows) == 56 and len({r["source_code"] for r in rows}) == 56
    assert all(r["relation"] == "wider" and len(r["target_code"]) == 7 for r in rows)
    by = {r["source_code"]: r["target_code"] for r in rows}
    assert by["3962002"] == "A10BA02" and by["3332001"] == "B01AA03"  # metformin, warfarin
    assert by["3999016"] == "L04AX03" and by["4222001"] == "L01BA01"  # methotrexate: RA vs oncology stems
    assert by["3399007"] == "B01AC06" and by["1143001"] == "N02BA01"  # aspirin: antiplatelet vs analgesic


def test_a_bad_yj_row_refuses_the_table(tmp_path: Path) -> None:
    f = _write(tmp_path / "t.csv", [list(jp.YJ_COLS), ["396200", "x", "内用", "A10BA02", "metformin"]])
    with pytest.raises(ValueError, match="bad row"):
        list(jp.parse_jp_yj_atc(f))


def test_site_setup_suggests_atc_for_a_yj_code(loaded: str) -> None:
    got = sm.suggest("medication", sm.local_system("drug-code"), "3339004F1020")  # an apixaban tablet
    assert got == {"system": sm.ATC, "code": "B01AF02", "display": "apixaban", "method": "refdata",
                   "confidence": "0.90"}  # fmt: skip
    assert sm.suggest("medication", sm.local_system("drug-code"), "9999999F1020") == {}  # stem not in the table
    assert jp.yj_atc_targets("333900412345") == []  # all digits: a hospital's own code, not a YJ code
    assert sm.suggest("medication", sm.local_system("drug-code"), "333900412345").get("method") != "refdata"


# ------------------------------------------------------------------------------------------------ D-174 JLAC10
def test_jlac10_loader_reads_codes_or_parts_and_keeps_only_valid_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    f = _write(tmp_path / "a.csv", [["JLAC10", "LOINC", "項目名"], ["3C015000002327101", "2160-0", "クレアチニン"],
                                    ["3C0150000023271", "2160-0", "15 characters"], ["bad", "2160-0", ""],
                                    ["3C015000002327101", "not-loinc", ""]])  # fmt: skip
    rows = list(jp.parse_jlac10_loinc(f))
    assert [(r["source_code"], r["target_code"], r["relation"]) for r in rows] == [
        ("3C015000002327101", "2160-0", "relatedto"), ("3C0150000023271", "2160-0", "relatedto")]  # fmt: skip
    g = _write(tmp_path / "b.csv", [["分析物コード", "識別コード", "材料コード", "測定法コード", "結果識別コード",
                                     "LOINCコード", "relation"], ["3C015", "0000", "023", "271", "01", "2160-0",
                                                                  "equivalent"]])  # fmt: skip
    assert [(r["source_code"], r["relation"]) for r in jp.parse_jlac10_loinc(g)] == [
        ("3C015000002327101", "equivalent")]  # fmt: skip
    k = _write(tmp_path / "d.csv", [["JLAC10", "LOINC"], ["3C015-0000-023-271-01", "2160-0"], ["x", "y"], ["z", "1-1"]])
    with caplog.at_level(logging.WARNING, logger="tb_common.refdata_jp"):
        assert [r["source_code"] for r in jp.parse_jlac10_loinc(k)] == ["3C015000002327101"]  # hyphens as printed
    assert "2 rows left out" in caplog.text
    h = _write(tmp_path / "c.csv", [["JLAC10", "LOINC", "relation"], ["3C015000002327101", "2160-0", "same"]])
    with pytest.raises(ValueError, match="R4 equivalence"):
        list(jp.parse_jlac10_loinc(h))


def test_site_setup_suggests_loinc_from_the_hospitals_jlac10_map(loaded: str, tmp_path: Path) -> None:
    code = "3Z999000002399901"  # synthetic: not in the shipped JP-Core sample table
    assert sm.suggest("observation", sm.local_system("lab-code"), code) == {}
    f = _write(tmp_path / "dl" / "jlac.csv", [["JLAC10", "LOINC", "項目名"], [code, "2160-0", "テスト項目"],
                                              ["3Z998000002399901", "2160-0", "a"],
                                              ["3Z998000002399901", "38483-4", "b"]])  # fmt: skip
    rf.site_load("jlac10_loinc", f, tmp_path / "site", db_url=loaded)
    got = sm.suggest("observation", sm.local_system("lab-code"), code)
    assert got["code"] == "2160-0" and got["method"] == "refdata" and got["confidence"] == "0.90"
    assert sm.suggest("observation", sm.local_system("lab-code"), "3Z998000002399901") == {}  # two targets


# ------------------------------------------------------------------------------------------------ D-174 CTCAE
def test_ctcae_en_keeps_terms_grades_and_definitions_but_no_meddra_codes(tmp_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.worksheets[0]
    ws.title = "CTCAE v5.0 Clean Copy"
    rows = list(csv.reader((SAMPLES / "ctcae_v5_sample.csv").open(encoding="utf-8")))
    rows[1][0] = "10002272"  # a code as NCI's file has it: it must not reach the pack
    for r in rows:
        ws.append(r)
    f = tmp_path / "ctcae-v5.0.xlsx"
    wb.save(f)
    terms = {t["code"]: t for t in jp.parse_ctcae_v5_en(f)}
    assert sorted(terms) == sorted(["Anemia", "Febrile neutropenia", "Diarrhea", "Nausea",
                                    "Alanine aminotransferase increased", "Peripheral sensory neuropathy"])  # fmt: skip
    fn = terms["Febrile neutropenia"]
    assert fn["system"] == jp.CTCAE5 and fn["extra"]["grades"]["1"] == "" and fn["extra"]["grades"]["5"] == "Death"
    assert fn["extra"]["soc"] == "Blood and lymphatic system disorders" and fn["extra"]["definition"]
    assert "10002272" not in json.dumps(list(terms.values()))


def test_jcog_loader_gives_ja_terms_for_the_english_terms(tmp_path: Path) -> None:
    """A synthetic workbook in the JCOG layout (our own Japanese words, not JCOG's text)."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.worksheets[0]
    ws.append(["ソート用\nID", "CTCAE v5.0\nMedDRA \nv20.1 Code", "CTCAE v5.0\nSOC", "CTCAE v5.0\nSOC 日本語",
               "CTCAE v5.0\nTerm", "CTCAE v5.0\nTerm 日本語", "Grade 1\n原文", "Grade 1", "Grade 2\n原文", "Grade 2",
               "Grade 3\n原文", "Grade 3", "Grade 4\n原文", "Grade 4", "Grade 5 \n原文", "Grade 5",
               "CTCAE v5.0 AE Term \nDefinition", "CTCAE v5.0 AE Term \nDefinition", "Navigational Note",
               "検索上の注意"])  # fmt: skip
    ws.append([None, "合成 SOC 見出し"])
    ws.append([None, "", "Gastrointestinal disorders", "合成の器官別分類", "Nausea", "合成用語・吐き気",
               "x", "合成グレード1", "x", "合成グレード2", "x", "合成グレード3", "-", "-", "-", "-",
               "def", "合成の定義", "-", "-"])  # fmt: skip
    f = tmp_path / "CTCAEv5J_20990101_synthetic.xlsx"
    wb.save(f)
    rows = list(jp.parse_ctcae_v5_ja(f))
    assert len(rows) == 1
    r = rows[0]
    assert (r["term"], r["lang"], r["canonical"], r["domain"], r["system"], r["code"]) == (
        "合成用語・吐き気", "ja", "Nausea", "adverse_event", jp.CTCAE5, "Nausea")  # fmt: skip
    assert r["extra"]["grades_ja"] == {
        "1": "合成グレード1",
        "2": "合成グレード2",
        "3": "合成グレード3",
        "4": "",
        "5": "",
    }
    assert r["extra"]["definition_ja"] == "合成の定義" and r["extra"]["soc_ja"] == "合成の器官別分類"
    assert jp.ctcae_ja_version(f) == "CTCAE v5.0 日本語訳JCOG版 20990101"


def test_the_ctcae_store_answers_en_and_ja(loaded: str, tmp_path: Path) -> None:
    with rd.RefStore(loaded) as st:
        t = st.term(jp.CTCAE5, "Nausea")
    assert t is not None and t["extra"]["grades"]["4"] == "" and t["extra"]["lang"] == "en"


# ------------------------------------------------------------------------------------------------ D-175 synonyms
def _site_atc(tmp: Path) -> Path:
    """V-18b (D-1183): no ATC name ships, so a drug's name answers only from the site's own ATC copy. A SYNTHETIC
    copy: the dictionary's drug names, each under a made-up code (Z99, a group ATC does not have)."""
    from criteria_compiler.terminology import installed

    names = sorted({r["canonical"] for r in jp.parse_ja_synonyms(jp.REPO_SYNONYMS) if r["domain"] == "medication"})
    src = tmp / "atc.tsv"
    src.write_text("ATC code\tATC level name\n" + "".join(f"Z99AA{i:02d}\t{n}\n" for i, n in enumerate(names, 1)),
                   encoding="utf-8")  # fmt: skip
    installed.install_atc(src, tmp / "terminology", "Ada Example (SYNTHETIC test person)", version="2099")
    return tmp / "terminology"


def test_every_curated_ja_synonym_resolves_and_maps_like_its_canonical_name(tmp_path: Path) -> None:
    rows = list(jp.parse_ja_synonyms(jp.REPO_SYNONYMS))
    assert len(rows) == 70 and {r["term"] for r in rows if not r["curated"]} == {"RA", "AMI", "MTX", "PSL", "GPT"}
    site = _site_atc(tmp_path)  # V-18b: the drug names answer from the site's copy (synthetic here)
    plain = Terminology(installed=site)
    # V-18b: a drug name answers from the site's copy, a table loaded at install (method "loaded")
    dead = [r["term"] for r in rows
            if plain.map(r["domain"], r["canonical"]).method not in ("exact", "synonym", "loaded")]  # fmt: skip
    assert dead == []

    def lookup(term: str, domain: str = "") -> list[dict[str, Any]]:
        n = rd.norm_name(term)
        return [{**r, "source_id": "ja_synonyms"} for r in rows
                if rd.norm_name(r["term"]) == n and (not domain or r["domain"] == domain)]  # fmt: skip

    t = Terminology(name_synonyms=lookup, installed=site)
    off = [r["term"] for r in rows if r["curated"] and (
        {c.code for c in t.map(r["domain"], r["term"]).concepts}
        != {c.code for c in plain.map(r["domain"], r["canonical"]).concepts}
        or t.map(r["domain"], r["term"]).needs_review)]  # fmt: skip
    assert off == []


def test_the_name_matcher_reads_the_ja_dictionary(loaded: str, tmp_path: Path) -> None:
    site = _site_atc(tmp_path)  # V-18b: the drug names answer from the site's copy (synthetic here)
    plain = Terminology(installed=site)
    with_dict = Terminology(name_synonyms=rd.synonym_lookup(loaded), installed=site)
    assert plain.map("condition", "関節リウマチ").method not in ("exact", "synonym")
    ra = with_dict.map("condition", "関節リウマチ")
    assert ra.method == "synonym" and not ra.needs_review and "ja_synonyms" in ra.notes[0]
    assert ra.concepts == plain.map("condition", "rheumatoid arthritis").concepts
    psl = with_dict.map("medication", "PSL")  # a note abbreviation: reviewed
    # V-18b: prednisolone's code is the site copy's (H02AB06 in WHOCC's index; a made-up code in this synthetic one)
    assert psl.method == "dictionary" and psl.needs_review
    pred = {c.code for c in plain.map("medication", "prednisolone").concepts}
    assert len(pred) == 1 and {c.code for c in psl.concepts} == pred
