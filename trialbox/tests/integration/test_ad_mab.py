"""T-503 scenario J1 in process: the AD-MAB early Alzheimer's trial and the NEUR-COH registry on the Japanese
synthetic memory clinic (``tools.synth_hospital --profile jp-ad``).

* the committed rulesets' SQL gives the committed ``tests/expected.json`` on this site, and that equals the planted
  gold on every coded criterion;
* ``SCREEN AD-MAB`` by email lists exactly the patients a hand recount from the raw tables and the gold gives;
* a patient with no amyloid result is "needs information" (review), never "criteria not matched" (excluded).
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
from tb_common.crypto import pid_for_mrn
from tb_common.ruleset import Ruleset

from tests.inproc_box import ingest_site, make_box, unzip_phi
from tests.screening_site import accept_fixture
from tools.synth import ad

ROOT = Path(__file__).resolve().parents[2]
KEY = b"trialbox-test-site-key-0123456789abcdef"
REF = date(2026, 11, 1)
RUN = REF + timedelta(days=1)  # a Monday, the index date of expected.json
SITE_JP = {"site": {"id": "DEMO-J", "name": "デモ病院J（合成）", "tz": "Asia/Tokyo", "locale": "ja"}}


@pytest.fixture(scope="module")
def jp(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from tools.synth_hospital import run

    tmp = tmp_path_factory.mktemp("jpad")
    res = run(tmp / "synth", profile="jp-ad", ref_date=REF)
    assert res.passed, res.failures
    site = tmp / "synth" / "jp-ad"
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(site, tmp / "lake", sec, (REF - timedelta(days=1)).isoformat(), site_id="DEMO-J")
    states = json.loads((site / "states.json").read_text(encoding="utf-8"))
    return {"tmp": tmp, "site": site, "sec": sec, "states": states, "mrn": {pid_for_mrn(KEY, m): m for m in states}}


def _verdicts(lake_dir: Path, rid: str, mrn: dict[str, str]) -> dict[str, dict[str, Any]]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    rs = Ruleset.load(ROOT / "rulesets" / rid)
    rows = LakeLocal(lake_dir, HashEmbedder()).query(rs.sql, [[RUN.isoformat()], None]).to_pylist()
    return {mrn[r["pid"]]: {k[2:]: v for k, v in r.items() if k.startswith("C_")} for r in rows}


@pytest.mark.parametrize("rid", ["AD-MAB", "NEUR-COH"])
def test_sql_gives_the_committed_expected_and_the_gold(jp: dict[str, Any], rid: str) -> None:
    got = _verdicts(jp["tmp"] / "lake", rid, jp["mrn"])
    exp = json.loads((ROOT / "rulesets" / rid / "tests" / "expected.json").read_text(encoding="utf-8"))
    assert exp["index_date"] == RUN.isoformat()
    assert {m: got[m] for m in exp["patients"]} == exp["patients"]
    for m, st in jp["states"].items():
        if st.get("archetype") == "ad":
            gold = ad.expected(st)
            for cid, v in got[m].items():
                if cid in ad.STRUCTURED:
                    assert v == gold[cid], (m, cid, v, gold[cid])
        elif rid == "NEUR-COH":  # nobody else has a memory-clinic diagnosis or visit
            assert got[m]["NEUR-COH-INC-01"] is False and got[m]["NEUR-COH-INC-02"] is False, m


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _recount(site: Path, states: dict[str, dict[str, str]]) -> set[str]:
    """The trial's screening list by hand: a booked appointment with an AD-MAB doctor in the next 180 days or a
    visit to one in the last 12 months, alive, not refusing contact, and no coded criterion that rules the patient out on the gold."""
    doctors = set(ad.NEUR_DOCTORS)
    end = RUN + timedelta(days=180)
    since = date(RUN.year - 1, RUN.month, RUN.day)
    scoped = {
        r["mrn"]
        for r in _rows(site / "appointment.csv")
        if r["staff_id"] in doctors and r["status"] == "B" and RUN <= date.fromisoformat(r["appt_datetime"][:10]) <= end
    }
    scoped |= {
        r["mrn"]
        for r in _rows(site / "encounter.csv")
        if r["staff_id"] in doctors and since <= date.fromisoformat(r["visit_datetime"][:10]) <= RUN
    }
    dead = {
        r["mrn"] for r in _rows(site / "patient.csv") if r["death_date"] and date.fromisoformat(r["death_date"]) <= RUN
    }
    scoped -= dead
    contact: dict[str, str] = {}  # the research registry's latest answer: "N" = do not contact (never listed)
    for r in sorted(_rows(site / "registry.csv"), key=lambda r: r["consent_date"]):
        contact[r["mrn"]] = r["consent_contact"]
    scoped = {m for m in scoped if contact.get(m) != "N"}
    assert all(states[m]["archetype"] == "ad" for m in scoped)  # only the memory clinic's patients see these doctors
    return {m for m in scoped if ad.tier(states[m], notes_read=False) != "excluded"}


def test_screen_lists_the_recount_and_unknown_amyloid_needs_information(jp: dict[str, Any]) -> None:
    box = make_box(
        jp["tmp"] / "box",
        jp["tmp"] / "lake",
        jp["sec"],
        RUN,
        settings_update=SITE_JP,
        extra_env={"TB_DATA_DIR": str(jp["tmp"])},
    )
    accept_fixture(box, "AD-MAB")
    assert box.mail("SCREEN AD-MAB version=1.0.0") == "Processed"
    box.orch.drain()
    job = box.orch.db.find(type_="SCREEN")[0]
    assert job.state == "done", job.error
    mail = next(s for s in reversed(box.sent) if s.subject.startswith("[AD-MAB] SCREEN candidates"))
    files = unzip_phi(box, mail)
    cl = c.CandidateList.model_validate_json(next(v for k, v in files.items() if k.endswith(".json")))
    listed = {jp["mrn"][r.pid] for r in cl.rows}
    want = _recount(jp["site"], jp["states"])
    assert len(want) > 100
    assert listed == want, (sorted(listed - want)[:5], sorted(want - listed)[:5])
    # the test model reads no Japanese note yet: every listed patient is "needs information", none "matched"
    assert {r.tier for r in cl.rows} == {"review"}
    no_amyloid = [r for r in cl.rows if jp["states"][jp["mrn"][r.pid]]["amyloid"] in ("absent", "not_done")]
    assert len(no_amyloid) > 50
    for r in no_amyloid:
        (v,) = [v for v in r.criteria if v.id == "AD-MAB-INC-05"]
        assert v.verdict == "unknown", (r.pid, v.verdict)
    # and nobody is left out for a missing amyloid result: every scoped patient the gold keeps is on the list
    kept_by_gold = {m for m in want if jp["states"][m]["amyloid"] in ("absent", "not_done")}
    assert kept_by_gold <= listed
    assert cl.summary.review == len(cl.rows) and cl.summary.high == 0
