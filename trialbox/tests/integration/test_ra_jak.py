"""T-504 scenario T2 in process: the RA-JAK interventional trial on the Taiwanese rheumatology site
(``tools.synth_hospital --profile tw-ra``).

* the committed ruleset's SQL gives the committed ``tests/expected.json`` (CQL verdicts recorded by the local engine,
  D-321) on every criterion where CQL answers, and the planted gold on every coded criterion;
* ``SCREEN RA-JAK`` lists exactly the patients a hand recount from the raw tables and the gold gives;
* the two planted states: a herpes zoster or a venous thromboembolism in the codes keeps the patient off the list; one
  written only in a note leaves the patient on it, with the criterion for a person to read.
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
from tools.synth import rajak

ROOT = Path(__file__).resolve().parents[2]
KEY = b"trialbox-test-site-key-0123456789abcdef"
REF = date(2026, 11, 1)
RUN = REF + timedelta(days=1)  # the index date of expected.json
SITE_TW = {"site": {"id": "DEMO-T", "name": "示範醫院T（合成）", "tz": "Asia/Taipei", "locale": "zh-TW"}}
RID = "RA-JAK"


@pytest.fixture(scope="module")
def tw(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from tools.synth_hospital import run

    tmp = tmp_path_factory.mktemp("twra")
    res = run(tmp / "synth", profile="tw-ra", ref_date=REF)
    assert res.passed, res.failures
    site = tmp / "synth" / "tw-ra"
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    ingest_site(site, tmp / "lake", sec, (REF - timedelta(days=1)).isoformat(), site_id="DEMO-T")
    states = json.loads((site / "states.json").read_text(encoding="utf-8"))
    return {"tmp": tmp, "site": site, "sec": sec, "states": states, "mrn": {pid_for_mrn(KEY, m): m for m in states}}


def _verdicts(lake_dir: Path, mrn: dict[str, str]) -> dict[str, dict[str, Any]]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal

    rs = Ruleset.load(ROOT / "rulesets" / RID)
    rows = LakeLocal(lake_dir, HashEmbedder()).query(rs.sql, [[RUN.isoformat()], None]).to_pylist()
    return {mrn[r["pid"]]: {k[2:]: v for k, v in r.items() if k.startswith("C_")} for r in rows}


def test_sql_gives_the_recorded_cql_and_the_gold(tw: dict[str, Any]) -> None:
    got = _verdicts(tw["tmp"] / "lake", tw["mrn"])
    exp = json.loads((ROOT / "rulesets" / RID / "tests" / "expected.json").read_text(encoding="utf-8"))
    assert exp["index_date"] == RUN.isoformat()
    known = set(exp["agreement"]["known_differences"])
    assert known == {"RA-JAK-INC-04", "RA-JAK-EXC-11"}  # D-321: the engine's ReplaceMatches, derived scores only
    assert len(exp["patients"]) >= 200
    for m, verdicts in exp["patients"].items():
        for cid, v in verdicts.items():
            if cid in known:
                assert v is None or got[m][cid] == v, (m, cid)  # CQL null there; SQL is checked on the gold below
            else:
                assert got[m][cid] == v, (m, cid, got[m][cid], v)
    assert all(
        exp["agreement"]["per_criterion"][c] == 100.0 for c in exp["agreement"]["per_criterion"] if c not in known
    )
    rajak_patients = [m for m, st in tw["states"].items() if st.get("archetype") == "rajak"]
    assert len(rajak_patients) > 600
    for m in rajak_patients:
        gold = rajak.expected(tw["states"][m])
        for cid, v in got[m].items():
            if cid in rajak.STRUCTURED:
                assert v == gold[cid], (m, cid, v, gold[cid])
    rs = Ruleset.load(ROOT / "rulesets" / RID)
    assert rs.manifest.status == "approved" and (rs.manifest.equivalence.overall_pct or 0) == 100.0  # type: ignore[union-attr]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _recount(site: Path, states: dict[str, dict[str, str]], verdicts: dict[str, dict[str, Any]]) -> set[str]:
    """The trial's list by hand: a booked appointment with an RA-JAK doctor in the next 180 days or a visit to one in
    the last 12 months, alive, not refusing contact, and no coded criterion that rules the patient out (the gold for
    the trial's own patients, the SQL for the rest of the clinic)."""
    doctors = set(rajak.RHEU_DOCTORS)
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
    contact: dict[str, str] = {}
    for r in sorted(_rows(site / "registry.csv"), key=lambda r: r["consent_date"]):
        contact[r["mrn"]] = r["consent_contact"]
    scoped = {m for m in scoped if contact.get(m) != "N"}

    def coded_ok(m: str) -> bool:
        if states[m].get("archetype") == "rajak":
            return rajak.coded_candidate(states[m])
        for cid, v in verdicts[m].items():
            if (rajak.KINDS[cid] == "inclusion" and v is False) or (rajak.KINDS[cid] == "exclusion" and v is True):
                return False
        return True

    return {m for m in scoped if coded_ok(m)}


def test_screen_lists_the_recount_and_the_planted_states(tw: dict[str, Any]) -> None:
    box = make_box(tw["tmp"] / "box", tw["tmp"] / "lake", tw["sec"], RUN, settings_update=SITE_TW)
    assert box.mail(f"SCREEN {RID} version=1.0.0") == "Processed"
    box.orch.drain()
    job = box.orch.db.find(type_="SCREEN")[0]
    assert job.state == "done", job.error
    mail = next(s for s in reversed(box.sent) if s.subject.startswith(f"[{RID}] SCREEN candidates"))
    files = unzip_phi(box, mail)
    cl = c.CandidateList.model_validate_json(next(v for k, v in files.items() if k.endswith(".json")))
    listed = {tw["mrn"][r.pid] for r in cl.rows}
    want = _recount(tw["site"], tw["states"], _verdicts(tw["tmp"] / "lake", tw["mrn"]))
    assert len(want) > 80
    assert listed == want, (sorted(listed - want)[:5], sorted(want - listed)[:5])
    st = tw["states"]
    on_rajak = [m for m in listed if st[m].get("archetype") == "rajak"]
    assert on_rajak and all(st[m]["zoster"] != "coded_recent" for m in on_rajak)
    assert all(not st[m]["vte"].startswith("coded") for m in on_rajak)
    # a note-only zoster or thromboembolism: on the list, the criterion left for a person (codes say nothing)
    by_pid = {tw["mrn"][r.pid]: r for r in cl.rows}
    note_only = [m for m in on_rajak if st[m]["zoster"] == "note_recent" or st[m]["vte"] == "note_only"]
    assert len(note_only) > 5
    for m in note_only:
        crit = "RA-JAK-EXC-06" if st[m]["zoster"] == "note_recent" else "RA-JAK-EXC-07"
        (v,) = [v for v in by_pid[m].criteria if v.id == crit]
        assert v.verdict != "pass", (m, crit, v.verdict)  # an exclusion "pass" would mean "not present"
    assert {r.tier for r in cl.rows} <= {"review", "high"}
