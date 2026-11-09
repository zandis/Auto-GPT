"""D-140: the offline reference data pack and the two ClinicalTrials.gov modes.

Everything here runs on the committed samples (``tests/fixtures/refdata``, the synthetic CT.gov cassettes and two
real CT.gov records already in the fixtures): no network. The pack is built, verified, tampered with, loaded into the
test's own ``refdata`` schema, searched as live mode is searched, refreshed through the update path, and shown on
the admin page; the install question, the wizard and the network sheet carry the hospital's choice.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from criteria_compiler.ctgov import CtGov, CtgovError
from tb_common import refdata as rd
from tb_contracts import CtgovSearchRequest

from tools import network_sheet as ns
from tools import refdata_fetch as rf
from tools import settings_wizard as wiz
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sample_tar(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("refpack")
    return rf.build(rf.sample_raw(out / "raw"), out, "20261109", sample=True)


@pytest.fixture
def pack(sample_tar: Path, tmp_path: Path) -> Path:
    with rd.opened(sample_tar) as p:
        dest = tmp_path / p.name
        shutil.copytree(p, dest)
    return dest


@pytest.fixture
def loaded(sample_tar: Path, db_url: str) -> str:
    with rd.opened(sample_tar) as p, rd.RefStore(db_url) as st:
        st.load(p, by="test")
    return db_url


def _ids(studies: list[Any]) -> list[str]:
    return sorted(s.nct_id for s in studies)


# ------------------------------------------------------------------------------------------------ the format
def test_the_manifest_records_url_date_sha_count_licence_terms_and_attribution(pack: Path) -> None:
    m = rd.verify(pack)
    assert m["format"] == "trialbox-refdata/1" and m["pack_id"] == "trialbox-refdata-20261109" and m["sample"]
    ids = {s["id"] for s in m["sources"]}
    assert ids == {"ctgov", "tfda_trials", "tfda_indication", "mhlw_yakka", "nhi_drugs", "icd10cm", "nhi_drug_atc",
                   "tw_icd_2014_2023", "nhi_lab_loinc", "naer_medical_terms", "tw_zh_synonyms"}  # fmt: skip
    for s in m["sources"]:
        assert all(s[k] not in ("", None) for k in ("url", "downloaded_at", "download_sha256", "records", "licence",
                                                     "terms", "attribution", "version"))  # fmt: skip
        assert s["distribution"] == "ship"
    ct = next(s for s in m["sources"] if s["id"] == "ctgov")
    assert (
        ct["records"] == 6 and "National Library of Medicine" in ct["attribution"] and "2026-11-09" in ct["attribution"]
    )
    notice = (pack / "NOTICE.md").read_text(encoding="utf-8")
    assert all(s["attribution"] in notice and s["licence"] in notice for s in m["sources"])


def test_a_changed_file_or_count_is_refused(pack: Path) -> None:
    f = pack / "icd10cm" / "terms.jsonl.gz"
    rows = gzip.decompress(f.read_bytes()).splitlines()
    f.write_bytes(gzip.compress(b"\n".join(rows[:-1]) + b"\n"))
    with pytest.raises(rd.PackError, match="does not match its sha256"):
        rd.verify(pack)
    m = json.loads((pack / "manifest.json").read_text())
    m["sources"][0].pop("attribution")
    (pack / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(rd.PackError, match="missing attribution"):
        rd.verify(pack)


def test_the_tar_is_deterministic_and_safe(sample_tar: Path, tmp_path: Path) -> None:
    with rd.opened(sample_tar) as p:
        again = rd.pack_tar(p, tmp_path / "again.tar")
    assert again.read_bytes() == sample_tar.read_bytes()
    import tarfile

    evil = tmp_path / "evil.tar"
    with tarfile.open(evil, "w") as tf:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 0
        tf.addfile(info)
    with pytest.raises(rd.PackError, match="unsafe member"), rd.opened(evil):
        pass


# ------------------------------------------------------------------------------------------------ parsers
def test_the_parsers_read_the_committed_excerpts(tmp_path: Path) -> None:
    raw = rf.sample_raw(tmp_path / "raw")
    ind = {
        t["display"]: t["extra"]["codes"]
        for t in rf.parse_tfda_indication(raw / "tfda_indication/tfda_indication_sample.csv")
    }
    assert ind["痛風併高尿酸血症"] == ["274.9", "M10.9"]
    trials = list(rf.parse_tfda_trials(raw / "tfda_trials/tfda_trials_sample.csv", ind))
    assert [t["trial_id"] for t in trials] == ["1149900001", "1149900002"]  # the repeated 收文號 once
    assert (
        trials[0]["codes"] == ["274.9", "M10.9"]
        and trials[0]["start"] == "2026-01-15"
        and "eGFR" in trials[0]["exclusion"]
    )
    yakka = {t["code"]: t for t in rf.parse_mhlw_yakka([raw / "mhlw_yakka/yakka_sample.xlsx"])}
    assert (
        yakka["3949003F1023"]["display"] == "フェブリク錠１０ｍｇ"
        and yakka["3949003F1023"]["extra"]["成分名"] == "フェブキソスタット"
    )
    (nhi,) = rf.parse_nhi_drugs(raw / "nhi_drugs/nhi_drugs_sample.csv")
    assert nhi["code"] == "B004858100" and nhi["extra"]["有效起日"] == "2011-12-01"  # the latest 民國 period
    assert nhi["extra"]["ATC代碼"]  # ATC only as the NHI list carries it (owner, 2026-11-09)
    icd = {t["code"]: t["display"] for t in rf.parse_icd10cm(raw / "icd10cm/icd10cm-sample.zip")}
    assert icd["M10.9"] == "Gout, unspecified" and icd["I10"].startswith("Essential") and "M1A.9XX0" in icd
    umin = list(rf.parse_umin(ROOT / "tests/fixtures/refdata/umin_sample.csv"))
    assert [u["trial_id"] for u in umin] == ["UMIN000099901", "UMIN000099902"] and umin[0]["countries"] == ["Japan"]


def test_every_source_has_a_decision_and_nothing_forbidden_is_shipped() -> None:
    by = {s.id: s for s in rf.SOURCES}
    assert {s.distribution for s in rf.SOURCES} == {"ship", "site-fetch", "not usable"}
    assert by["umin_ctr"].distribution == "site-fetch" and not by["umin_ctr"].fetch  # never downloaded by us
    assert by["who_ictrp"].distribution == "not usable" and by["jrct"].distribution == "site-fetch"
    with pytest.raises(SystemExit, match="site-fetch"):
        rf.fetch(["umin_ctr"], Path("/nonexistent"))
    table = rf.table_md()
    assert all(s.name in table for s in rf.SOURCES)


# ------------------------------------------------------------------------------------------------ the store
def test_offline_mode_answers_what_live_answers(loaded: str) -> None:
    c = CtGov(mode="offline", db_url=loaded)
    gout = c.search(CtgovSearchRequest(condition="gout"))
    assert gout.source == "refdata" and _ids(gout.studies) == ["NCT99000001", "NCT99000002", "NCT99000003"]
    assert _ids(c.search(CtgovSearchRequest(condition="Gout", locations=["Japan"])).studies) == [
        "NCT99000001",
        "NCT99000003",
    ]
    assert _ids(c.search(CtgovSearchRequest(condition="gout", locations=["Taiwan"])).studies) == [
        "NCT99000001",
        "NCT99000002",
    ]
    assert c.search(CtgovSearchRequest(condition="rheumatoid arthritis", status="COMPLETED")).studies == []
    one = c.search(CtgovSearchRequest(condition="", nct_id="NCT04157751"))  # a real record, completed, any site
    assert _ids(one.studies) == ["NCT04157751"] and one.studies[0].eligibility_text
    full = c.raw(CtgovSearchRequest(condition="", nct_id="NCT99000004"))[0]
    assert full["protocolSection"]["eligibilityModule"]["eligibilityCriteria"]  # the full record, for drafting
    cassette = CtGov(mode="cassette").search(CtgovSearchRequest(condition="gout"))
    assert _ids(cassette.studies) == _ids(gout.studies)  # the same answer as the cassette of the same studies


def test_reference_lists_and_status(loaded: str) -> None:
    with rd.RefStore(loaded) as st:
        assert (st.term("http://hl7.org/fhir/sid/icd-10-cm", "M10.9") or {}).get("display") == "Gout, unspecified"
        assert (st.term("urn:mhlw:yakka-kijun", "3943001F1012") or {}).get("extra", {}).get(
            "成分名"
        ) == "アロプリノール"
        (t,) = st.trials("TFDA", "痛風")
        assert t["countries"] == ["Taiwan"] and t["codes"] == ["274.9", "M10.9"]
        s = st.status()
        assert s and s["data_as_of"] == "2026-11-09" and s["sample"]
        assert {x["source_id"]: x["records"] for x in s["sources"]}["ctgov"] == 6


def test_a_new_pack_replaces_its_sources_and_keeps_the_hospitals_own(loaded: str, tmp_path: Path) -> None:
    rf.site_load("umin_ctr", ROOT / "tests/fixtures/refdata/umin_sample.csv", tmp_path / "site", db_url=loaded)
    raw = rf.sample_raw(tmp_path / "raw2")
    page = json.loads((raw / "ctgov/sample.json").read_text())
    page["studies"] = page["studies"][:1]
    (raw / "ctgov/sample.json").write_text(json.dumps(page))
    meta = json.loads((raw / "ctgov/fetch.json").read_text())  # as a new fetch would record it (the build re-hashes)
    meta["sha256"] = rd.sha256_file(raw / "ctgov/sample.json")
    (raw / "ctgov/fetch.json").write_text(json.dumps(meta))
    tar = rf.build(raw, tmp_path / "out", "20261210", sample=True)
    with rd.opened(tar) as p, rd.RefStore(loaded) as st:
        st.load(p)
        s = st.status()
        assert s and s["pack_id"] == "trialbox-refdata-20261210" and len(s["packs"]) == 2  # the vendor's and the site's
        recs = {x["source_id"]: x for x in s["sources"]}
        assert recs["ctgov"]["records"] == 1 and recs["umin_ctr"]["distribution"] == "site-fetch"
        assert [t["trial_id"] for t in st.trials("UMIN-CTR")] == ["UMIN000099901", "UMIN000099902"]
        assert any(n["id"] == "umin_ctr" for n in st.notices())


def test_offline_without_a_pack_says_so(db_url: str) -> None:
    with pytest.raises(CtgovError, match="no reference data pack"):
        CtGov(mode="offline", db_url=db_url).search(CtgovSearchRequest(condition="gout"))
    with pytest.raises(CtgovError, match="not one of"):
        CtGov(mode="online")


def test_the_default_mode_is_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_CTGOV_MODE", raising=False)
    assert CtGov().mode == "offline"


def test_live_and_cassette_look_up_one_study_by_its_id() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        raw = json.loads((ROOT / "tests/fixtures/open_data/ctgov_NCT04157751.json").read_text())["study"]
        return httpx.Response(200, json=raw) if req.url.path.endswith("NCT04157751") else httpx.Response(404)

    live = CtGov(
        mode="live", base_url="https://ctgov.test/api/v2", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert _ids(live.search(CtgovSearchRequest(condition="", nct_id="NCT04157751")).studies) == ["NCT04157751"]
    assert live.search(CtgovSearchRequest(condition="", nct_id="NCT00000001")).studies == []
    assert seen == ["/api/v2/studies/NCT04157751", "/api/v2/studies/NCT00000001"]
    assert _ids(CtGov(mode="cassette").search(CtgovSearchRequest(condition="", nct_id="NCT99000004")).studies) == [
        "NCT99000004"
    ]


# ------------------------------------------------------------------------------------------------ the update path
def test_the_update_bundle_loads_the_pack(sample_tar: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stage = tmp_path / "stage"
    (stage / "refdata").mkdir(parents=True)
    shutil.copy2(sample_tar, stage / "refdata" / sample_tar.name)
    plan = up.Plan("B1", "f" * 64, "vendor", [], stage)
    assert up.refdata_packs(plan) == [stage / "refdata" / sample_tar.name]
    calls: list[str] = []

    def run(argv: list[str], **_kw: Any) -> str:
        calls.append(" ".join(argv))
        return ""

    monkeypatch.setenv("TB_COMPOSE", "dc")
    (tmp_path / "deploy").mkdir()
    done = up.ComposeBox(tmp_path / "deploy", run=run).post_apply(plan)
    assert done == [sample_tar.name]
    assert calls[0].startswith("dc cp ") and calls[0].endswith("criteria-compiler:/tmp/refdata-update.tar")
    assert "python -m tb_common.refdata load /tmp/refdata-update.tar --by update:B1" in calls[1]
    assert "refdata" in json.loads((ROOT / "schemas/update_manifest.schema.json").read_text())["$defs"]["update_file"][
        "properties"]["kind"]["enum"]  # fmt: skip


# ------------------------------------------------------------------------------------------------ the choice
def test_the_wizard_defaults_to_offline_and_takes_live_or_the_install_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_CTGOV_MODE", raising=False)
    import yaml

    base = yaml.safe_load((ROOT / "tests/fixtures/onboarding/site_c_answers.yaml").read_text(encoding="utf-8"))
    base.pop("ctgov_mode", None)
    base["mapping"] = "mapping/tw_core/demo_his.yaml"
    _s, env, _w = wiz.build(base)
    assert env["TB_CTGOV_MODE"] == "offline"
    _s, env, warns = wiz.build({**base, "ctgov_mode": "live"})
    assert env["TB_CTGOV_MODE"] == "live" and any("clinicaltrials.gov:443" in w for w in warns)
    with pytest.raises(wiz.WizardError, match="ctgov_mode"):
        wiz.build({**base, "ctgov_mode": "sometimes"})
    monkeypatch.setenv("TB_CTGOV_MODE", "live")
    asked: list[str] = []

    def prompt(q: str) -> str:
        asked.append(q)
        return ""

    answers = wiz.ask({}, prompt=prompt)
    assert answers["ctgov_mode"] == "live" and not any("ClinicalTrials.gov" in q for q in asked)
    for lang in ("en", "ja", "zh-TW"):
        assert "offline" in wiz.CTGOV_QUESTION[lang] and "live" in wiz.CTGOV_QUESTION[lang]


def test_install_asks_in_three_languages_and_defaults_to_offline() -> None:
    text = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    assert "--ctgov) CTGOV=" in text and "offline / live [offline]" in text
    for line in (
        "may this box reach clinicaltrials.gov",
        "clinicaltrials.gov に接続してよいですか",
        "本機可以連上網際網路的 clinicaltrials.gov 嗎",
    ):
        assert line in text
    env = {**os.environ, "TB_CTGOV_PROBE": "fail"}
    out = subprocess.run(
        ["bash", str(ROOT / "deploy/install.sh"), "--ctgov-check"], env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0 and "offline only" in out.stdout
    env["TB_CTGOV_PROBE"] = "ok"
    out = subprocess.run(
        ["bash", str(ROOT / "deploy/install.sh"), "--ctgov-check"], env=env, capture_output=True, text=True, check=False
    )
    assert "the default stays offline" in out.stdout
    bad = subprocess.run(
        ["bash", str(ROOT / "deploy/install.sh"), "--ctgov", "sometimes", "x.tar"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 2 and "live or offline" in bad.stderr


def test_the_network_sheet_shows_the_chosen_mode(tmp_path: Path) -> None:
    for mode, host_open in (("live", True), ("offline", False)):
        env = tmp_path / f"{mode}.env"
        env.write_text(f"TB_CTGOV_MODE={mode}\n", encoding="utf-8")
        out = tmp_path / mode / "network-sheet"
        assert ns.main(["--env", str(env), "--out", str(out)]) == 0
        for lang in ns.LANGS:
            text = out.with_name(f"network-sheet.{lang}.md").read_text(encoding="utf-8")
            assert ns.T[f"ctgov_{mode}"][lang] in text
            assert ("clinicaltrials.gov:443 |" in text) is host_open
    committed = (ROOT / "docs/handover/network-sheet.en.md").read_text(encoding="utf-8")
    assert "offline by default" in committed
