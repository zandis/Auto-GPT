"""10D-15 (D-1367): the ClinicalTrials.gov intake widened: sites, secondary ids, arms, interventions, outcomes, design.

Proved by: a recorded cassette round-trips every widened field (parse -> store -> read back equal); a jRCT id is found
among the secondary ids; a record with contact names stores none. The cassette ``tests/fixtures/ctgov/widened`` is a
synthetic record written to the API v2 format (fictional names, ``example.invalid`` addresses): no network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.ctgov import CtGov, registry_ids, to_study
from tb_common import refdata as rd
from tb_common.ctgov_record import registry_of, strip_names
from tb_common.db import Database
from tb_contracts import CtgovSearchRequest, CtgovSearchResult, CtgovStudy

from tools import refdata_fetch as rf

ROOT = Path(__file__).resolve().parents[2]
CASSETTE = ROOT / "tests/fixtures/ctgov/widened"
NCT = "NCT99000101"
RAW: dict[str, Any] = json.loads((CASSETTE / f"{NCT}.json").read_text(encoding="utf-8"))["studies"][0]
#: every personal name, phone and e-mail the synthetic record carries
PERSONAL = (
    "Synthetic Contact Alpha", "Synthetic Official Beta", "Synthetic Investigator Gamma",
    "Synthetic Site Contact Delta", "Synthetic Site Investigator Epsilon", "Synthetic Results Contact Zeta",
    "Synthetic Author Eta", "+1-555-01", "example.invalid", "Professor (fictional)",
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


def _one(client: CtGov) -> CtgovStudy:
    res = client.search(CtgovSearchRequest(condition="", nct_id=NCT))
    assert [s.nct_id for s in res.studies] == [NCT]
    return res.studies[0]


def _pack(tmp: Path) -> Path:
    """A reference data pack holding the cassette's record, built the way a vendor builds one (no network)."""
    raw = tmp / "raw"
    (raw / "ctgov").mkdir(parents=True)
    data = json.dumps({"studies": [RAW]}).encode()
    (raw / "ctgov" / "page.json").write_bytes(data)
    meta = {"downloaded_at": "2026-11-19T00:00:00+00:00", "url": rf.BY_ID["ctgov"].url, "path": "page.json",
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "slice": 1}  # fmt: skip
    (raw / "ctgov" / "fetch.json").write_text(json.dumps(meta), encoding="utf-8")
    return rf.build(raw, tmp / "out", "20261119", ids=["ctgov"], sample=True)


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
    assert registry_of("jrcts031180001") == ("jRCT", "jRCTs031180001")  # a category letter, any case
    assert registry_of("jRCT 2031 260123 (Japan)") == ("jRCT", "jRCT2031260123")  # spaces and words around it
    assert registry_of("UMIN-CTR000012345") == ("UMIN-CTR", "UMIN000012345")
    assert registry_of("japiccti-123456") == ("JapicCTI", "JapicCTI-123456")
    for other in ("2026-000123-45", "NCT99000101", "jRCT12345", "UMIN12345678", "R000012345", ""):
        assert registry_of(other) is None, other


def test_parse_store_read_back_equal_with_no_personal_name_stored(tmp_path: Path, db_url: str) -> None:
    parsed = _one(CtGov(mode="cassette", cassette_dir=CASSETTE))
    tar = _pack(tmp_path)
    with rd.opened(tar) as p:
        packed = "".join(json.dumps(r) for r in rd.rows(p, "ctgov/studies.jsonl.gz"))
        with rd.RefStore(db_url) as st:
            st.load(p, by="test")
            stored = st.ctgov_study(NCT)
    assert stored is not None
    for value in PERSONAL:
        assert value not in packed, value  # the pack ships no name
        assert value not in json.dumps(stored, ensure_ascii=False), value  # the store keeps none
    read_back = _one(CtGov(mode="offline", db_url=db_url))
    assert read_back == parsed  # every field, the widened ones included
    assert read_back.model_dump(mode="json", include=set(WIDENED)) == WIDENED
    # the contract carries them unchanged: the compiler's answer as the orchestrator reads it
    res = CtgovSearchResult(
        condition=NCT, source="refdata", fetched_at=datetime(2026, 11, 19, tzinfo=UTC), studies=[read_back]
    )
    assert CtgovSearchResult.model_validate_json(res.model_dump_json()) == res


def test_strip_names_drops_the_persons_and_keeps_everything_else() -> None:
    out = strip_names(RAW)
    assert out is not RAW and "centralContacts" in RAW["protocolSection"]["contactsLocationsModule"]  # a copy
    text = json.dumps(out)
    assert not [v for v in PERSONAL if v in text]
    cl = out["protocolSection"]["contactsLocationsModule"]
    assert set(cl) == {"locations"} and all("contacts" not in x for x in cl["locations"])
    rp = out["protocolSection"]["sponsorCollaboratorsModule"]["responsibleParty"]
    assert rp == {"type": "PRINCIPAL_INVESTIGATOR", "investigatorAffiliation": "Synthetic Medical Center Taipei"}
    assert out["protocolSection"]["referencesModule"]["references"] == [{"pmid": "99999901", "type": "BACKGROUND"}]
    assert out["resultsSection"]["moreInfoModule"] == {}
    # nothing else changed
    for module in ("identificationModule", "statusModule", "designModule", "armsInterventionsModule",
                   "outcomesModule", "eligibilityModule", "conditionsModule"):  # fmt: skip
        assert out["protocolSection"][module] == RAW["protocolSection"][module]
    assert to_study(out) == to_study(RAW)  # the study reads no name: stripping changes nothing it carries


def test_version_4_strips_the_records_stored_before(db_url: str) -> None:
    """A box that loaded a pack before D-1367 has the names in its rows; the store's version 4 drops them."""
    db = Database.connect(db_url, rd.SCHEMA)
    try:
        db.migrate(list(rd.MIGRATIONS[:3]))
        with db.transaction() as tx:
            tx.execute(
                "INSERT INTO ctgov_study (nct_id, title, overall_status, conditions, countries, last_update, study, "
                "source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (NCT, "t", "RECRUITING", "|gout|", "|taiwan|japan|", "2026-10-20", json.dumps(RAW), "ctgov"),
            )
    finally:
        db.close()
    with rd.RefStore(db_url) as st:  # migrates to version 4
        stored = st.ctgov_study(NCT)
    assert stored == strip_names(RAW)


@pytest.mark.parametrize("module", ["armsInterventionsModule", "outcomesModule", "contactsLocationsModule"])
def test_a_record_without_a_module_has_none_of_its_fields(module: str) -> None:
    raw = json.loads(json.dumps(RAW))
    del raw["protocolSection"][module]
    s = to_study(raw)
    assert s is not None
    fields = {"armsInterventionsModule": ("arms", "interventions"), "outcomesModule": ("primary_outcomes",
              "secondary_outcomes"), "contactsLocationsModule": ("locations",)}[module]  # fmt: skip
    assert all(getattr(s, f) is None for f in fields)
