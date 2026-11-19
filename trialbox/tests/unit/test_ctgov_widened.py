"""10D-15 (D-1367): the ClinicalTrials.gov intake widened: sites, secondary ids, arms, interventions, outcomes, design.

Proved by: a recorded cassette round-trips every widened field (parse -> store -> read back equal); a jRCT id is found
among the secondary ids; a record with contact names stores none (nor a person named as sponsor or collaborator). The
cassette ``tests/fixtures/ctgov/widened/studies.json`` holds two synthetic records written to the API v2 format
(fictional names, ``example.invalid`` addresses): no network.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.ctgov import CtGov, registry_ids, to_study
from tb_common import ctgov_record as cr
from tb_common import refdata as rd
from tb_common.ctgov_record import registry_of, strip_names
from tb_common.db import Database
from tb_contracts import CtgovSearchRequest, CtgovSearchResult, CtgovStudy

from tools import refdata_fetch as rf

ROOT = Path(__file__).resolve().parents[2]
CASSETTE = ROOT / "tests/fixtures/ctgov/widened"
NCT, NCT_INDIV = "NCT99000101", "NCT99000102"  # the second has a person as lead sponsor
RAW, RAW_INDIV = json.loads((CASSETTE / "studies.json").read_text(encoding="utf-8"))["studies"]
#: every personal name, phone and e-mail the synthetic records carry
PERSONAL = (
    "Synthetic Contact Alpha", "Synthetic Official Beta", "Synthetic Investigator Gamma",
    "Synthetic Site Contact Delta", "Synthetic Site Investigator Epsilon", "Synthetic Results Contact Zeta",
    "Synthetic Author Eta", "+1-555-01", "example.invalid", "Professor (fictional)",
    "Synthetic Sponsor Person Iota", "Synthetic Sponsor Person Kappa",
)  # fmt: skip

WIDENED = {
    "locations": [
        {"facility": "Synthetic Medical Center Taipei", "city": "Taipei", "state": None, "country": "Taiwan",
         "status": "RECRUITING"},
        {"facility": "Synthetic University Hospital", "city": "Osaka", "state": "Osaka", "country": "Japan",
         "status": "NOT_YET_RECRUITING"},
    ],
    "secondary_ids": [
        {"id": "jRCT2031260123", "type": "REGISTRY", "domain": "Japan Registry of Clinical Trials", "registry": "jRCT",
         "registry_id": "jRCT2031260123"},
        {"id": "JapicCTI-260123", "type": "OTHER", "domain": "JAPIC", "registry": "JapicCTI",
         "registry_id": "JapicCTI-260123"},
        {"id": "UMIN000056789", "type": "REGISTRY", "domain": "UMIN-CTR", "registry": "UMIN-CTR",
         "registry_id": "UMIN000056789"},
        {"id": "2026-000123-45", "type": "EUDRACT_NUMBER", "domain": None, "registry": None, "registry_id": None},
        {"id": "SYN-GRANT-7", "type": "OTHER_GRANT", "domain": "Synthetic Foundation (fictional)", "registry": None,
         "registry_id": None},
    ],
    "arms": [
        {"label": "URAT1 inhibitor", "type": "EXPERIMENTAL",
         "description": "Synthetic compound SYN-101, 4 mg once daily for 24 weeks",
         "intervention_names": ["Drug: SYN-101"]},
        {"label": "Placebo", "type": "PLACEBO_COMPARATOR", "description": "Matching placebo once daily for 24 weeks",
         "intervention_names": ["Drug: Placebo"]},
    ],
    "interventions": [
        {"name": "SYN-101", "type": "DRUG", "description": "Oral tablet, 4 mg", "arm_labels": ["URAT1 inhibitor"],
         "other_names": ["SYN101"]},
        {"name": "Placebo", "type": "DRUG", "description": "Oral tablet matching SYN-101", "arm_labels": ["Placebo"],
         "other_names": []},
    ],
    "primary_outcomes": [
        {"measure": "Proportion of participants with serum urate below 6.0 mg/dL",
         "description": "At each of the last three visits", "time_frame": "Week 24"},
    ],
    "secondary_outcomes": [
        {"measure": "Change in serum urate from baseline", "description": None, "time_frame": "Weeks 4, 12 and 24"},
        {"measure": "Number of gout flares", "description": "Flares reported by the participant",
         "time_frame": "24 weeks"},
    ],
    "design": {"study_type": "INTERVENTIONAL", "allocation": "RANDOMIZED", "model": "PARALLEL",
               "primary_purpose": "TREATMENT", "masking": "QUADRUPLE",
               "who_masked": ["PARTICIPANT", "CARE_PROVIDER", "INVESTIGATOR", "OUTCOMES_ASSESSOR"],
               "enrollment_type": "ESTIMATED"},
}  # fmt: skip


def _one(client: CtGov, nct: str = NCT) -> CtgovStudy:
    res = client.search(CtgovSearchRequest(condition="", nct_id=nct))
    assert [s.nct_id for s in res.studies] == [nct]
    return res.studies[0]


def _pack(tmp: Path) -> Path:
    """A reference data pack holding the cassette's records, built the way a vendor builds one (no network)."""
    raw = tmp / "raw"
    (raw / "ctgov").mkdir(parents=True)
    data = json.dumps({"studies": [RAW, RAW_INDIV]}).encode()
    (raw / "ctgov" / "page.json").write_bytes(data)
    meta = {"downloaded_at": "2026-11-19T00:00:00+00:00", "url": rf.BY_ID["ctgov"].url, "path": "page.json",
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "slice": 1}  # fmt: skip
    (raw / "ctgov" / "fetch.json").write_text(json.dumps(meta), encoding="utf-8")
    return rf.build(raw, tmp / "out", "20261119", ids=["ctgov"], sample=True)


def _no_personal_value(text: str) -> None:
    assert not [v for v in PERSONAL if v in text]


def test_the_cassette_gives_every_widened_field() -> None:
    s = _one(CtGov(mode="cassette", cassette_dir=CASSETTE))
    got = s.model_dump(mode="json", include=set(WIDENED))
    assert got == WIDENED
    # the fields read before are read as before
    assert (s.title, s.phases, s.enrollment, s.sponsor, s.countries, s.last_update) == (
        "[SYNTHETIC] Widened Intake Record: a URAT1 Inhibitor Against Placebo in Gout", ["PHASE3"], 320,
        "Synthetic Pharma Co. (fictional)", ["Japan", "Taiwan"], date(2026, 10, 20))  # fmt: skip


def test_a_jrct_id_is_found_among_the_secondary_ids() -> None:
    s = to_study(RAW)
    assert s is not None
    assert registry_ids(s, "jRCT") == ["jRCT2031260123"]
    assert registry_ids(s, "JapicCTI") == ["JapicCTI-260123"] and registry_ids(s, "UMIN-CTR") == ["UMIN000056789"]
    for text, want in (
        ("jrcts031180001", ("jRCT", "jRCTs031180001")),  # the category letter s, any case
        ("jRCT1031230456", ("jRCT", "jRCT1031230456")),
        ("jRCT 2031260123 (Japan)", ("jRCT", "jRCT2031260123")),  # a space after the prefix, words around it
        ("see jRCT-2031260123.", ("jRCT", "jRCT2031260123")),
        ("UMIN-CTR000012345", ("UMIN-CTR", "UMIN000012345")),
        ("japiccti-123456", ("JapicCTI", "JapicCTI-123456")),
        ("jRCT2031260123; jRCT2031260123", ("jRCT", "jRCT2031260123")),  # the same number twice is one
    ):
        assert registry_of(text) == want, text
    for other in (
        "2026-000123-45", "NCT99000101", "jRCT12345", "UMIN12345678", "R000012345", "",
        "jRCT203126012",  # 9 digits without the letter
        "jRCTz999999999", "jRCTss039990001",  # a letter the repository's jRCT data never shows; two letters
        "xjrcts031180001", "jRCT20312601234", "UMIN0000123456", "JapicCTI-1234567",  # not standing on its own
        "UMIN000012345 and jRCT2031260123",  # two numbers in one field: which it stands for is not known
    ):  # fmt: skip
        assert registry_of(other) is None, other
    two = to_study(RAW_INDIV)
    assert two is not None and two.secondary_ids is not None
    assert two.secondary_ids[0].id == "UMIN000012345 and jRCT2031260123" and two.secondary_ids[0].registry is None


def test_parse_store_read_back_equal_with_no_personal_name_stored(tmp_path: Path, db_url: str) -> None:
    parsed = [_one(CtGov(mode="cassette", cassette_dir=CASSETTE), n) for n in (NCT, NCT_INDIV)]
    tar = _pack(tmp_path)
    with rd.opened(tar) as p:
        _no_personal_value("".join(json.dumps(r) for r in rd.rows(p, "ctgov/studies.jsonl.gz")))  # the pack ships none
        with rd.RefStore(db_url) as st:
            st.load(p, by="test")
            stored = [st.ctgov_study(n) for n in (NCT, NCT_INDIV)]
    assert all(stored)
    _no_personal_value(json.dumps(stored, ensure_ascii=False))  # the store keeps none
    read_back = [_one(CtGov(mode="offline", db_url=db_url), n) for n in (NCT, NCT_INDIV)]
    assert read_back == parsed  # every field, the widened ones included
    assert read_back[0].model_dump(mode="json", include=set(WIDENED)) == WIDENED
    assert read_back[1].sponsor is None  # a person as lead sponsor is not named
    # the contract carries them unchanged: the compiler's answer as the orchestrator reads it
    res = CtgovSearchResult(
        condition=NCT, source="refdata", fetched_at=datetime(2026, 11, 19, tzinfo=UTC), studies=read_back
    )
    assert CtgovSearchResult.model_validate_json(res.model_dump_json()) == res


def test_an_older_pack_with_names_is_stripped_as_it_is_loaded(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pack built before D-1367 carries the names; loading it stores none (``refdata.ctgov_row``)."""
    monkeypatch.setattr(rf, "strip_names", lambda study: study)  # the pack build as it was before
    tar = _pack(tmp_path)
    with rd.opened(tar) as p:
        packed = "".join(json.dumps(r) for r in rd.rows(p, "ctgov/studies.jsonl.gz"))
        assert all(v in packed for v in PERSONAL)  # the old pack does carry every one of them
        with rd.RefStore(db_url) as st:
            st.load(p, by="test")
            stored = [st.ctgov_study(n) for n in (NCT, NCT_INDIV)]
    assert stored == [strip_names(RAW), strip_names(RAW_INDIV)]
    _no_personal_value(json.dumps(stored, ensure_ascii=False))


def test_strip_names_drops_the_persons_and_keeps_everything_else() -> None:
    out = strip_names(RAW)
    assert out is not RAW and "centralContacts" in RAW["protocolSection"]["contactsLocationsModule"]  # a copy
    _no_personal_value(json.dumps(out))
    cl = out["protocolSection"]["contactsLocationsModule"]
    assert set(cl) == {"locations"} and all("contacts" not in x for x in cl["locations"])
    sc = out["protocolSection"]["sponsorCollaboratorsModule"]
    assert sc["responsibleParty"] == {"type": "PRINCIPAL_INVESTIGATOR",
                                      "investigatorAffiliation": "Synthetic Medical Center Taipei"}  # fmt: skip
    assert sc["leadSponsor"] == RAW["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"]  # a company
    assert sc["collaborators"] == [{"class": "INDIV"}, {"name": "Synthetic University (fictional)", "class": "OTHER"}]
    assert out["protocolSection"]["referencesModule"]["references"] == [{"pmid": "99999901", "type": "BACKGROUND"}]
    assert out["resultsSection"]["moreInfoModule"] == {}
    # nothing else changed
    for module in ("identificationModule", "statusModule", "designModule", "armsInterventionsModule",
                   "outcomesModule", "eligibilityModule", "conditionsModule"):  # fmt: skip
        assert out["protocolSection"][module] == RAW["protocolSection"][module]
    assert to_study(out) == to_study(RAW)  # the study reads no name: stripping changes nothing it carries
    indiv = strip_names(RAW_INDIV)["protocolSection"]["sponsorCollaboratorsModule"]
    assert indiv == {"responsibleParty": {"type": "SPONSOR_INVESTIGATOR"}, "leadSponsor": {"class": "INDIV"}}
    s = to_study(RAW_INDIV)
    assert s is not None and s.sponsor is None  # not even from a live record that still has the name


def _xmin(db: Database, nct: str) -> str:
    row = db.fetchone("SELECT xmin::text FROM ctgov_study WHERE nct_id = ?", (nct,))
    assert row is not None
    return str(row[0])


def test_version_4_strips_the_records_stored_before_and_rewrites_no_other(db_url: str) -> None:
    """A box that loaded a pack before D-1367 has the names in its rows; the store's version 4 drops them in one
    statement that rewrites only the rows holding a name (a clean row keeps its row version)."""
    clean = strip_names(RAW)
    clean["protocolSection"]["identificationModule"]["nctId"] = "NCT99000103"
    db = Database.connect(db_url, rd.SCHEMA)
    try:
        db.migrate(list(rd.MIGRATIONS[:3]))
        with db.transaction() as tx:
            for nct, rec in ((NCT, RAW), (NCT_INDIV, RAW_INDIV), ("NCT99000103", clean)):
                tx.execute(
                    "INSERT INTO ctgov_study (nct_id, title, overall_status, conditions, countries, last_update, "
                    "study, source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (nct, "t", "RECRUITING", "|gout|", "|taiwan|", "2026-10-20", json.dumps(rec), "ctgov"),
                )
        before = {n: _xmin(db, n) for n in (NCT, NCT_INDIV, "NCT99000103")}
        db.migrate(list(rd.MIGRATIONS))  # version 4
        after = {n: _xmin(db, n) for n in before}
    finally:
        db.close()
    assert after["NCT99000103"] == before["NCT99000103"]  # not rewritten
    assert after[NCT] != before[NCT] and after[NCT_INDIV] != before[NCT_INDIV]
    with rd.RefStore(db_url) as st:
        assert [st.ctgov_study(n) for n in (NCT, NCT_INDIV, "NCT99000103")] == [
            strip_names(RAW), strip_names(RAW_INDIV), clean]  # fmt: skip


def test_version_4_names_every_path_strip_names_drops() -> None:
    """The SQL of version 4 and the Python constants cannot drift apart unnoticed."""
    paths = [*cr.DROPPED_PATHS, *(p for p, _ in cr.DROPPED_IN_LISTS), *cr.PERSON_OBJECTS, *cr.PERSON_LISTS]
    for path in paths:
        assert "'{" + ",".join(path) + "}'" in rd.DDL_V4, path
    for _, key in cr.DROPPED_IN_LISTS:
        assert f"e.v - '{key}'" in rd.DDL_V4 and f"e.v -> '{key}' IS NOT NULL" in rd.DDL_V4, key
    assert rd.DDL_V4.count(f"'{cr.INDIV}'") == 4 and ";" not in rd.DDL_V4 and "?" not in rd.DDL_V4


@pytest.mark.parametrize("module", ["armsInterventionsModule", "outcomesModule", "contactsLocationsModule"])
def test_a_record_without_a_module_has_none_of_its_fields(module: str) -> None:
    raw = copy.deepcopy(RAW)
    del raw["protocolSection"][module]
    s = to_study(raw)
    assert s is not None
    fields = {"armsInterventionsModule": ("arms", "interventions"), "outcomesModule": ("primary_outcomes",
              "secondary_outcomes"), "contactsLocationsModule": ("locations",)}[module]  # fmt: skip
    assert all(getattr(s, f) is None for f in fields)


def _malformed() -> dict[str, Any]:
    raw: dict[str, Any] = copy.deepcopy(RAW)
    ps = raw["protocolSection"]
    ps["identificationModule"]["secondaryIdInfos"] = ["jRCT2031260123", None, {"id": 7}, {"id": "jRCT2031260123"}]
    ps["armsInterventionsModule"]["armGroups"] = [None, "Placebo", {"label": "Arm A", "interventionNames": "Drug: X"}]
    ps["armsInterventionsModule"]["interventions"] = "SYN-101"
    ps["outcomesModule"] = ["not a module"]
    ps["designModule"]["designInfo"] = "RANDOMIZED"
    ps["contactsLocationsModule"]["locations"] = [{"facility": {"name": "x"}, "country": "Japan"}, 3,
                                                  {"facility": "Synthetic Clinic", "country": ["Japan"]}]  # fmt: skip
    return raw


def test_a_malformed_record_never_stops_the_search(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text(json.dumps({"studies": [_malformed()]}), encoding="utf-8")
    s = _one(CtGov(mode="cassette", cassette_dir=tmp_path))
    want = {
        "secondary_ids": [{"id": "jRCT2031260123", "type": None, "domain": None, "registry": "jRCT",
                           "registry_id": "jRCT2031260123"}],
        "arms": [{"label": "Arm A", "type": None, "description": None, "intervention_names": ["Drug: X"]}],
        "interventions": None,
        "primary_outcomes": None,
        "locations": [{"facility": "Synthetic Clinic", "city": None, "state": None, "country": None, "status": None}],
    }  # fmt: skip
    assert s.model_dump(mode="json", include=set(want)) == want
    design = {"study_type": "INTERVENTIONAL", "enrollment_type": "ESTIMATED"}
    assert s.design is not None and s.design.model_dump(exclude_none=True) == design
    assert s.countries == ["Japan"]  # the first site's country stays; a list as country is left out


def test_a_single_string_is_one_value_not_its_characters() -> None:
    raw = copy.deepcopy(RAW)
    raw["protocolSection"]["designModule"]["designInfo"]["maskingInfo"]["whoMasked"] = "PARTICIPANT"
    raw["protocolSection"]["designModule"]["phases"] = "PHASE3"
    s = to_study(raw)
    assert s is not None and s.design is not None
    assert s.design.who_masked == ["PARTICIPANT"] and s.phases == ["PHASE3"]
