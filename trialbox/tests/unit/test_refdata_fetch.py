"""T-618 (D-317): every reference list fetched from a cassette, with its version and source; the full CT.gov
download's version and count check; retried and resumed downloads; the NHI service list; UCUM; the hospital's jRCT
download; withdrawing a source; the Taiwan 2014 codes read at ingest.

No network: :func:`tb_common.refdata.replay` answers every request from ``tests/fixtures/refdata/cassettes``, and a
request the cassette did not record fails the test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from tb_common import refdata as rd
from tb_common import refdata_jp as jp
from tb_common import refdata_tw as tw

from tools import refdata_fetch as rf

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/fixtures/refdata"
CAS = FIX / "cassettes"

# every item the vendor fetches over the network or from the repository (the account downloads, LOINC and the
# NHIA workbook, take --file; site-fetch items are the hospital's: see the jRCT test)
FETCHED = sorted(s.id for s in rf.SOURCES if s.distribution == "ship" and (s.fetch or s.url.startswith("repo:")))


def test_the_fetched_list_covers_every_shipped_item_but_the_account_downloads() -> None:
    shipped = {s.id for s in rf.SOURCES if s.distribution == "ship"}
    assert shipped - set(FETCHED) == {"loinc", "tw_icd10_zh"}
    assert {"ctgov", "nhi_drugs", "nhi_services", "ucum"} <= set(FETCHED)


def _unpin(monkeypatch: pytest.MonkeyPatch, cas: rd.Cassette, sid: str) -> None:
    """A pinned item (the PAS package, CTCAE, UCUM) is refused when the cassette's excerpt is not the pinned file;
    the test then pins the excerpt, as a new release would be pinned."""
    item = rf.BY_ID[sid]
    sha = hashlib.sha256(cas.payload(item.url)).hexdigest()
    monkeypatch.setitem(rf.BY_ID, sid, rd.Item(**{**item.__dict__, "sha256": sha}))


@pytest.mark.parametrize("sid", FETCHED)
def test_every_list_is_fetched_from_the_cassette_with_its_version_and_source(
    sid: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rf, "BACKOFF", 0.0)
    raw = tmp_path / "raw"
    parent = rf.BY_ID[sid].derived_from or sid
    with rd.replay(CAS / "ship_items.json") as cas:
        if rf.BY_ID[parent].sha256:
            with pytest.raises(SystemExit, match="is pinned to sha256"):
                rf.fetch([sid], raw)
            _unpin(monkeypatch, cas, parent)
        rf.fetch([sid], raw)
        assert cas.misses == []
    meta = json.loads((raw / parent / "fetch.json").read_text(encoding="utf-8"))
    assert meta["url"] and len(meta["sha256"]) == 64 and meta["downloaded_at"]
    for p in meta["parts"]:
        assert rd.sha256_file(raw / parent / p["path"]) == p["sha256"]
    item = rf.BY_ID[sid]
    if item.licence_reader is not None:  # the licence was read at the source, and the evidence kept
        assert meta["licence_checks"][sid]["ok"] is True
    tar = rf.build(raw, tmp_path / "out", "20261110", ids=[sid])
    with rd.opened(tar) as pack:
        m = rd.verify(pack)
    (src,) = m["sources"]
    assert src["id"] == sid and src["records"] > 0 and src["download_sha256"] == meta["sha256"]
    assert src["url"] and src["licence"] and src["attribution"] and src["version"]
    if item.licence_reader is not None or item.version_of is not None or sid == "ctgov":
        assert not src["version"].startswith("downloaded"), src["version"]  # read at the source or from the file


def test_the_full_ctgov_download_records_the_registry_version_and_is_checked_against_its_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    with rd.replay(CAS / "ship_items.json"):
        rf.fetch(["ctgov"], raw)
    meta = json.loads((raw / "ctgov/fetch.json").read_text(encoding="utf-8"))
    assert meta["version"] == "ClinicalTrials.gov data of 2026-11-10T10:00:05 (API 2.0.5)"
    assert meta["expected_records"] == 4 and meta["path"] == "ctg-studies.json.zip"
    tar = rf.build(raw, tmp_path / "out", "20261110", ids=["ctgov"])
    with rd.opened(tar) as pack:
        ids = sorted(r["nct_id"] for r in rd.rows(pack, "ctgov/studies.jsonl.gz"))
    assert ids == ["NCT99000001", "NCT99000002", "NCT99000003", "NCT99000004"]
    # the registry counted many more than the zip holds: a short download never builds
    meta["expected_records"] = 1000
    (raw / "ctgov/fetch.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(SystemExit, match="more than 2% short"):
        rf.build(raw, tmp_path / "out2", "20261110", ids=["ctgov"])
    rf.check_ctgov_count(980, {"expected_records": 1000})  # within 2 %
    rf.check_ctgov_count(3, {"expected_records": 1000, "slice": 3})  # a slice is not the registry
    rf.check_ctgov_count(3, {})  # the API did not answer at fetch time: nothing to check against


def test_a_cut_off_download_is_retried_and_never_kept(tmp_path: Path) -> None:
    url = rf.BY_ID["nhi_drugs"].url
    want = hashlib.sha256((FIX / "nhi_drugs_sample.csv").read_bytes()).hexdigest()
    with rd.replay(CAS / "cut_off.json") as cas:
        got = rf.download(url, tmp_path / "a.csv", wait=0)
        assert cas.unused() == []
    assert got["sha256"] == want and got["tries"] == 2
    with rd.replay(CAS / "cut_off.json"), pytest.raises(RuntimeError, match="cut off at 100 of"):
        rf.download(url, tmp_path / "b.csv", attempts=1, wait=0)
    assert not (tmp_path / "b.csv").exists() and not (tmp_path / "b.csv.part").exists()


def test_a_server_that_answers_a_range_is_resumed(tmp_path: Path) -> None:
    data = (FIX / "nhi_drugs_sample.csv").read_bytes()
    (tmp_path / "rest.bin").write_bytes(data[64:])
    (tmp_path / "full.bin").write_bytes(data)
    url = "https://example.invalid/list.csv"
    cassette = {"interactions": [
        {"url": url, "body": {"file": "full.bin"}, "cut_at": 64},
        {"url": url, "status": 206, "body": {"file": "rest.bin"}},
    ]}  # fmt: skip
    (tmp_path / "range.json").write_text(json.dumps(cassette), encoding="utf-8")
    with rd.replay(tmp_path / "range.json"):
        got = rf.download(url, tmp_path / "out" / "list.csv", wait=0)
    assert got["sha256"] == hashlib.sha256(data).hexdigest() and got["bytes"] == len(data)


def test_a_request_the_cassette_did_not_record_never_reaches_the_network(tmp_path: Path) -> None:
    with rd.replay(CAS / "cut_off.json") as cas, pytest.raises(RuntimeError, match="after 1 tries"):
        rf.download("https://example.invalid/other", tmp_path / "x", attempts=1, wait=0)
    assert cas.misses == ["GET https://example.invalid/other"]


def test_a_local_file_is_streamed_and_hashed(tmp_path: Path) -> None:
    src = FIX / "nhi_drugs_sample.csv"
    got = rf.local_file(src, tmp_path / "copy.csv", "https://x")
    assert got["sha256"] == rd.sha256_file(src) and got["bytes"] == src.stat().st_size


# ------------------------------------------------------------------------------------------------ new lists
def test_the_nhi_service_list_keeps_the_latest_period_per_code() -> None:
    terms = {t["code"]: t for t in tw.parse_nhi_services(FIX / "nhi_services_sample.csv")}
    assert sorted(terms) == ["09001C", "09005C", "09015C", "09026C", "21", "33070B", "58001C"]
    glu = terms["09005C"]
    assert glu["system"] == tw.NHI_SERVICE and glu["display"] == "血液及體液葡萄糖-空腹"
    assert glu["extra"]["points"] == "50" and glu["extra"]["valid_from"] == "2024-03-01"
    assert glu["extra"]["valid_to"] == "2910-12-31" and glu["extra"]["en"] == "Glucose-Ante Cibum, AC"
    assert terms["58001C"]["extra"]["en"] == "Hemodialysis"
    with pytest.raises(ValueError, match="NHI service list"):
        list(tw.parse_nhi_services(FIX / "nhi_drugs_sample.csv"))


def test_ucum_keeps_each_element_as_the_file_gives_it(tmp_path: Path) -> None:
    terms = list(rf.parse_ucum(FIX / "ucum_sample.xml"))
    assert [(t["code"], t["extra"]["element"]) for t in terms] == [("tbxp", "prefix"), ("tbxb", "base-unit"),
                                                                    ("tbxu", "unit")]  # fmt: skip
    unit = terms[2]
    assert unit["system"] == "http://unitsofmeasure.org" and unit["display"] == "testunit"
    assert unit["extra"]["names"] == ["testunit", "second name"] and unit["extra"]["CODE"] == "TBXU"
    assert unit["extra"]["value"] == {"Unit": "tbxb", "UNIT": "TBXB", "value": "2", "text": "2"}
    assert unit["extra"]["isMetric"] == "yes" and terms[1]["extra"]["dim"] == "Q"
    assert rf.ucum_version(FIX / "ucum_sample.xml") == "UCUM 2.2 (2024-06-17)"
    (tmp_path / "x.xml").write_text("<root/>", encoding="utf-8")
    with pytest.raises(ValueError, match="not a UCUM essence file"):
        list(rf.parse_ucum(tmp_path / "x.xml"))


def test_jrct_is_the_hospitals_own_download_and_never_shipped(tmp_path: Path) -> None:
    item = rf.BY_ID["jrct"]
    assert item.distribution == "site-fetch" and not item.fetch and item.decision == "D-317"
    rows = list(jp.parse_jrct(FIX / "jrct_sample.csv"))
    assert [r["trial_id"] for r in rows] == ["jRCT2031990001", "jRCT1031990002"]
    assert rows[0]["conditions"] == ["痛風", "高尿酸血症"] and rows[0]["registry"] == "jRCT"
    assert rows[0]["status"] == "募集中" and rows[0]["exclusion"] == "重度の腎機能障害"
    tar = rf.site_load("jrct", FIX / "jrct_sample.csv", tmp_path / "site", load=False)
    with rd.opened(tar) as pack:
        (src,) = rd.verify(pack)["sources"]
    assert src["distribution"] == "site-fetch" and src["records"] == 2 and src["version"].startswith("downloaded")
    with pytest.raises(SystemExit, match="not a ship item|not ship items"):
        rf.build(tmp_path / "site" / "raw", tmp_path / "vendor", ids=["jrct"])
    with pytest.raises(SystemExit, match="is site-fetch"):
        rf.fetch(["jrct"], tmp_path / "raw")
    with pytest.raises(ValueError, match="no header row"):
        list(jp.parse_jrct(FIX / "nhi_drugs_sample.csv"))


# ------------------------------------------------------------------------------------------------ withdrawing
def test_a_manifest_that_withdraws_needs_a_reason_and_cannot_ship_the_same_source() -> None:
    base: dict[str, Any] = {"format": rd.FORMAT, "pack_id": "trialbox-refdata-20261110", "data_as_of": "2026-11-10",
                            "sources": []}  # fmt: skip
    rd.check_manifest({**base, "withdrawn": [{"id": "x", "reason": "licence changed"}]})
    with pytest.raises(rd.PackError, match="needs an id and a reason"):
        rd.check_manifest({**base, "withdrawn": [{"id": "x", "reason": " "}]})
    with pytest.raises(rd.PackError, match="no source"):
        rd.check_manifest(base)
    with pytest.raises(rd.PackError, match="withdrawn twice"):
        rd.check_manifest({**base, "withdrawn": [{"id": "x", "reason": "a"}, {"id": "x", "reason": "b"}]})
    with pytest.raises(SystemExit, match="both built and withdrawn"):
        rf.build(Path("/nonexistent"), Path("/nonexistent"), ids=["icd10cm"], withdraw={"icd10cm": "r"})


def test_a_source_is_withdrawn_by_a_pack_or_by_hand_and_the_hospitals_own_rows_stay(
    db_url: str, tmp_path: Path
) -> None:
    sample = rf.build(rf.sample_raw(tmp_path / "s" / "raw"), tmp_path / "s", "20261109", sample=True)
    with rd.opened(sample) as p, rd.RefStore(db_url) as st:
        st.load(p, by="test")
    rf.site_load("umin_ctr", FIX / "umin_sample.csv", tmp_path / "site", db_url=db_url)
    with rd.RefStore(db_url) as st:
        assert st.term("http://hl7.org/fhir/sid/icd-10-cm", "M10.9") is not None
        assert st.trials("UMIN-CTR")
    (tmp_path / "empty").mkdir()
    tar = rf.build(tmp_path / "empty", tmp_path / "w", "20261110",
                   withdraw={"icd10cm": "replaced by a later edition", "umin_ctr": "not ours to remove"})  # fmt: skip
    with rd.opened(tar) as p:
        assert "## Withdrawn by this pack" in (p / "NOTICE.md").read_text(encoding="utf-8")
        with rd.RefStore(db_url) as st:
            res = st.load(p, by="vendor-update")
    assert res.counts == {}
    with rd.RefStore(db_url) as st:
        assert st.term("http://hl7.org/fhir/sid/icd-10-cm", "M10.9") is None  # the vendor's rows are gone
        assert st.trials("UMIN-CTR")  # a vendor pack never withdraws the hospital's own rows
        (w,) = st.withdrawn()
        assert w["source_id"] == "icd10cm" and w["reason"] == "replaced by a later edition" and w["records"] > 0
        assert w["pack_id"] == "trialbox-refdata-20261110" and w["withdrawn_by"] == "vendor-update"
        status = st.status()
        assert status is not None and "icd10cm" not in {s["source_id"] for s in status["sources"]}
        assert [x["source_id"] for x in status["withdrawn"]] == ["icd10cm"]
        assert "icd10cm" not in {n["id"] for n in st.notices()}
        # a restore loads the older pack again: the withdrawn source does not come back; a newer pack ships it
        with rd.opened(sample) as p:
            again = st.load(p, by="restore")
        assert "icd10cm" not in again.counts and "tfda_trials" in again.counts
        assert st.term("http://hl7.org/fhir/sid/icd-10-cm", "M10.9") is None
        newer = rf.build(rf.sample_raw(tmp_path / "n" / "raw"), tmp_path / "n", "20261111", sample=True)
        with rd.opened(newer) as p:
            assert st.load(p, by="vendor-update").counts["icd10cm"] > 0
        assert st.term("http://hl7.org/fhir/sid/icd-10-cm", "M10.9") is not None
        # by hand: the hospital takes its own part out; a source not loaded, or no reason, is refused
        assert st.withdraw("umin_ctr", "site no longer uses UMIN", by="admin") > 0
        assert not st.trials("UMIN-CTR")
        with pytest.raises(rd.PackError, match="not loaded"):
            st.withdraw("umin_ctr", "again")
        with pytest.raises(rd.PackError, match="needs a reason"):
            st.withdraw("tfda_trials", " ")
    assert rd.main(["withdraw", "tfda_trials", "--reason", "test"]) == 0


# ------------------------------------------------------------------------------------------------ 2014 at ingest
def test_a_taiwan_2014_code_is_read_through_the_map_at_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = {
        "P83.8": [{"target_system": tw.ICD_CM_2023, "target_code": "P83.88", "relation": "inexact"}],
        "E11.9": [{"target_system": tw.ICD_CM_2023, "target_code": "E11.9", "relation": "equivalent"}],
        "I10": [{"target_system": tw.ICD_CM_2023, "target_code": c, "relation": "narrower"}
                for c in ("I10", "I16.0", "I16.1", "I16.9")],
        "Z99.9": [{"target_system": tw.ICD_CM_2023, "target_code": "", "relation": "unmatched"}],
    }  # fmt: skip
    seen: list[tuple[str, str]] = []

    def fake(system: str, code: str, url: str | None = None) -> list[dict[str, Any]]:
        seen.append((system, code))
        return rows.get(code, [])

    monkeypatch.setattr(tw, "map_targets_or_empty", fake)
    assert tw.tw_icd_edition("2024-12-31") == "2014" and tw.tw_icd_edition("2025-01-01T08:00") == "2023"
    assert tw.tw_icd_edition("") == "" and tw.tw_icd_edition("31/12/2024") == ""
    e11 = tw.tw_icd_at_ingest("e11.9", "2023-05-01")
    assert e11["system"] == tw.ICD_CM_2014 and e11["code"] == "E11.9" and e11["same_2023"] == "E11.9"
    assert tw.tw_icd_at_ingest("P83.8", "2023-05-01")["same_2023"] == ""  # a changed code is not the same
    assert tw.tw_icd_at_ingest("Z99.9", "2023-05-01")["targets"] == []  # deleted: nothing to read through
    new = tw.tw_icd_at_ingest("I10", "2025-03-01")
    assert new["system"] == tw.ICD_CM_2023 and new["targets"] == [] and seen.count((tw.ICD_CM_2014, "I10")) == 0
    assert tw.tw_icd_at_ingest("I10", "?")["edition"] == ""
    wanted = {(tw.ICD_CM_2023, "E11.9"), (tw.ICD_CM_2023, "I10")}
    assert tw.tw_code_in_list(e11, wanted) == "yes"
    assert tw.tw_code_in_list(tw.tw_icd_at_ingest("I10", "2020-01-01"), wanted) == "unknown"  # split, part in
    assert tw.tw_code_in_list(tw.tw_icd_at_ingest("P83.8", "2020-01-01"), wanted) == "unknown"  # inexact
    assert tw.tw_code_in_list(new, wanted) == "yes"
    assert tw.tw_code_in_list(tw.tw_icd_at_ingest("J45.9", "2025-06-01"), wanted) == "no"
    assert tw.tw_code_in_list(new, {("http://hl7.org/fhir/sid/icd-10-cm", "I10")}) == "unknown"  # other system
    assert tw.tw_code_in_list(tw.tw_icd_at_ingest("I10", ""), wanted) == "unknown"
