"""NEW-STD-1, second half, part 1 (D-592): the CMS General Equivalence Mappings (ICD-9-CM to ICD-10-CM) as a source
of the reference-data pack. The fixture is an excerpt of the public file."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from tb_common import refdata as rd

from tools import refdata_fetch as rf

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "tests/fixtures/refdata/cms_gem_i9_sample.txt"
I9, I10 = "http://hl7.org/fhir/sid/icd-9-cm", "http://hl7.org/fhir/sid/icd-10-cm"


def _zip(tmp_path: Path, text: str | None = None, member: str = "2018_I9gem.txt") -> Path:
    p = tmp_path / "gem.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(member, SAMPLE.read_text() if text is None else text)
        z.writestr("2018_I10gem.txt", "A000    0010  00000\n")  # the reverse file is in the download and not read
    return p


def test_the_item_is_shipped_pinned_and_credited() -> None:
    item = rf.BY_ID["cms_gem_icd9_icd10cm"]
    assert (item.kind, item.distribution, item.version, item.decision) == ("map", "ship", "2018", "D-592")
    assert item.sha256 == "1c5e5f14026ace48437a0d1c485d282fb5d171c357c6ab4f7798fc0a1e3624a2"
    assert item.url.startswith("https://www.cms.gov/") and item.url.endswith(".zip") and item.fetch
    assert "17 U.S.C. 105" in item.licence and "Centers for Medicare & Medicaid Services" in item.attribution
    assert item.name in rf.table_md()


def test_each_line_with_a_target_is_a_row_and_the_relation_says_what_the_file_says(tmp_path: Path) -> None:
    rows = list(rf.parse_cms_gem(_zip(tmp_path)))
    assert all(r["source_system"] == I9 and r["target_system"] == I10 for r in rows)
    by: dict[str, list[dict[str, object]]] = {}
    for r in rows:
        by.setdefault(str(r["source_code"]), []).append(r)
    assert [(r["target_code"], r["relation"]) for r in by["001.0"]] == [("A00.0", "equivalent")]
    assert [(r["target_code"], r["relation"]) for r in by["714.0"]] == [("M06.9", "inexact")]
    assert [(r["target_code"], r["relation"]) for r in by["250.00"]] == [("E11.9", "inexact")]
    assert [(r["target_code"], r["relation"]) for r in by["E800.0"]] == [
        ("V81.2XXA", "inexact")
    ]  # E: four, then the dot
    # several alternatives, or a combination: related, never "the" code
    assert [(r["target_code"], r["relation"]) for r in by["V58.69"]] == [
        ("Z79.84", "relatedto"), ("Z79.891", "relatedto"), ("Z79.899", "relatedto")]  # fmt: skip
    assert {r["relation"] for r in by["428.0"]} == {"relatedto"} and len(by["428.0"]) == 2
    assert [(r["target_code"], r["relation"]) for r in by["073.0"]] == [("A70", "relatedto"), ("J17", "relatedto")]
    assert "365.70" not in by  # "no map": no row, never a guess
    assert by["714.0"][0]["extra"] == {"flags": "10000", "lines": 1}
    assert by["073.0"][0]["extra"] == {"flags": "10111", "lines": 2}
    # the real file names one pair twice (alone, and inside a combination): one row, both flag sets kept
    assert [(r["target_code"], r["relation"]) for r in by["666.02"] if r["target_code"] == "O72.0"] == [
        ("O72.0", "relatedto")]  # fmt: skip
    assert next(r for r in by["666.02"] if r["target_code"] == "O72.0")["extra"] == {
        "flags": "10000+10111",
        "lines": 11,
    }
    assert len(by["666.02"]) == 10 and len(rows) == 23
    keys = [(r["source_code"], r["target_code"]) for r in rows]
    assert len(keys) == len(set(keys))  # the box's table has one row per pair


def test_the_one_code_rule_of_the_next_part_can_be_read_from_the_rows(tmp_path: Path) -> None:
    rows = list(rf.parse_cms_gem(_zip(tmp_path)))
    single = {r["source_code"]: r["target_code"] for r in rows if r["relation"] in ("equivalent", "inexact")}
    assert single == {"001.0": "A00.0", "250.00": "E11.9", "714.0": "M06.9", "E800.0": "V81.2XXA"}


@pytest.mark.parametrize("bad", ["7140 M069 1000\n", "7140  M069\n", "714x  M069    10000\n", "7140  m069    10000\n",
                                 "7140  M069    10000 extra\n", ""])  # fmt: skip
def test_a_file_that_is_not_the_gem_layout_is_refused_whole(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="2018_I9gem.txt"):
        list(rf.parse_cms_gem(_zip(tmp_path, "0010  A000    00000\n" + bad if bad else "")))
    with pytest.raises(ValueError, match="2018_I9gem.txt"):
        list(rf.parse_cms_gem(_zip(tmp_path, member="other.txt")))


def test_the_pack_is_built_from_the_sample_and_carries_source_licence_and_hash(tmp_path: Path) -> None:
    raw = rf.sample_raw(tmp_path / "raw")
    tar = rf.build(raw, tmp_path / "out", "20261112", ids=["cms_gem_icd9_icd10cm"], sample=True)
    with rd.opened(tar) as pack:
        m = rd.verify(pack)
        (src,) = m["sources"]
        recs = list(rd.rows(pack, src["files"][0]["path"]))
    assert src["id"] == "cms_gem_icd9_icd10cm" and src["records"] == 23 == len(recs) and src["kind"] == "map"
    assert src["url"] == rf.BY_ID["cms_gem_icd9_icd10cm"].url and "17 U.S.C. 105" in src["licence"]
    assert len(src["download_sha256"]) == 64 and src["version"]
    assert "Centers for Medicare & Medicaid Services" in rd.notice(m)


def test_a_vendor_build_refuses_another_file_than_the_pinned_one(tmp_path: Path) -> None:
    raw = rf.sample_raw(tmp_path / "raw")
    meta = raw / "cms_gem_icd9_icd10cm" / "fetch.json"
    assert (
        hashlib.sha256((raw / "cms_gem_icd9_icd10cm" / "gem-sample.zip").read_bytes()).hexdigest() in meta.read_text()
    )
    with pytest.raises(SystemExit, match="pinned"):
        rf.build(raw, tmp_path / "out", "20261112", ids=["cms_gem_icd9_icd10cm"])  # not a sample build: the hash rules


def test_a_pack_with_one_map_pair_twice_fails_at_the_vendor_not_at_the_hospital() -> None:
    row = {"source_system": I9, "source_code": "666.02", "target_system": I10, "target_code": "O72.0",
           "relation": "relatedto", "source_display": "", "target_display": "", "extra": {}}  # fmt: skip
    src = {"id": "cms_gem_icd9_icd10cm", "kind": "map"}
    assert len(list(rd.check_records(src, [row, {**row, "target_code": "O72.1"}]))) == 2
    with pytest.raises(rd.PackError, match="twice"):
        list(rd.check_records(src, [row, dict(row)]))


def test_the_item_names_no_country() -> None:
    assert rf.BY_ID["cms_gem_icd9_icd10cm"].country == ""  # a U.S. file, used wherever ICD-9-CM was
