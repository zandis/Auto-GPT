"""D-407 (T-620): trial lifecycle Mediums in the data core.

* LIFE-017: the study's contact-attempt rule; a fourth attempt on a limit of three is refused with a plain reason,
  and so is an attempt sooner than the days the study asks between two.
* LIFE-020: the enrolment form records randomisation in the sponsor's IRT (yes / no, day, number), never an arm; the
  fields export in ODM; the screening log's detail carries the randomisation day.
* LIFE-025: possible deviations proposed from the box's own facts (a visit outside its window, a consent form version
  not in force, enrolment before consent, enrolment while the screening log says not eligible); each is confirmed (a
  deviation entry is written) or dismissed with a reason, once; the deviation form has a class and a sponsor-report
  date.

All data is synthetic."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from datacore import lifecycle as lc
from datacore.builtin import builtin_questionnaires, fields
from datacore.export import odm
from datacore.lifecycle import Lifecycle, LifeError, Visit
from datacore.store import DataCore
from fastapi import FastAPI
from orchestrator.lifecycle_api import router as life_router
from tb_common.audit import AuditLog

from tests.actor3 import SignedClient

AT = "2026-11-08T09:00:00+09:00"
RS = "GZQO"
NS = {"o": "http://www.cdisc.org/ns/odm/v1.3"}


@pytest.fixture
def life() -> Any:
    dc = DataCore()
    for q in builtin_questionnaires(RS):
        dc.put_form(RS, q, "builtin", AT)
    yield Lifecycle(dc)
    dc.close()


def _put(life: Lifecycle, rec: str, values: dict[str, str], event: str = "") -> None:
    for f, v in values.items():
        life.dc.write(RS, rec, event, f, v, "crc", AT, "trialbox")


# ---------------------------------------------------------------------------------------------- LIFE-017
def test_a_fourth_attempt_on_a_limit_of_three_is_refused() -> None:
    today = date(2026, 11, 10)
    days = ["2026-11-01", "2026-11-03", "2026-11-05"]
    assert lc.contact_check(days[:2], 3, 1, today) == {"attempts": 2, "max": 3, "min_days": 1, "why": "", "next": ""}
    out = lc.contact_check(days, 3, 1, today)
    assert out["why"] == "limit" and out["attempts"] == 3
    # an attempt sooner than the days asked between two: refused with the first day allowed
    soon = lc.contact_check(["2026-11-09"], 3, 2, today)
    assert soon["why"] == "too_soon" and soon["next"] == "2026-11-11"
    assert lc.contact_check(["2026-11-08"], 3, 2, today)["why"] == ""
    assert lc.contact_check(["2026-11-10"], 3, 0, today)["why"] == ""  # 0 days: the same day is allowed
    # only the outcomes that try to reach the patient count; closing the contact is never refused
    assert set(lc.CONTACT_ATTEMPTS) == {"reached_booked", "reached_declined", "not_reached"}


def test_the_study_sets_its_own_contact_rule(life: Lifecycle) -> None:
    assert life.contact_rule(RS) == {"max_attempts": 3, "min_days": 1, "set_by": "", "set_at": ""}
    row = life.set_contact_rule(RS, 5, 2, "crc", AT)
    assert (row["max_attempts"], row["min_days"], row["set_by"]) == (5, 2, "crc")
    for bad in ((0, 1), (21, 1), (3, -1), (3, 61)):
        with pytest.raises(LifeError) as e:
            life.set_contact_rule(RS, *bad, "crc", AT)
        assert e.value.why == "contact_rule"
    assert life.contact_rule("OTHER")["max_attempts"] == 3  # per study


# ---------------------------------------------------------------------------------------------- LIFE-020
def test_randomisation_fields_on_the_enrolment_form_and_no_arm() -> None:
    by = {f.name: f for f in fields()}
    for name in lc.RAND_FIELDS:
        assert by[name].form == "tb_enrolment"
    assert by["en_rand"].kind == "choice" and set(by["en_rand"].options) == {"1", "0", "8"}
    assert by["en_rand_date"].kind == "date"
    assert all(set(by[n].labels) >= {"ja", "zh-TW"} for n in lc.RAND_FIELDS)
    # blinding: no field of any built-in form holds the treatment arm
    assert not [f.name for f in fields() if "arm" in f.name.split("_") or "allocation" in f.label.lower()]


def test_randomisation_fields_export_in_odm_and_reach_the_log(life: Lifecycle) -> None:
    life.ensure(RS, "GZQO-0001", "ab" * 16, "crc", AT)
    _put(life, "GZQO-0001", {"ic_date": "2026-11-01", "ic_version": "v2", "en_date": "2026-11-02", "en_eligible": "1",
                             "en_rand": "1", "en_rand_date": "2026-11-03", "en_rand_no": "R-0107"})  # fmt: skip
    life.derive(RS, "GZQO-0001", by="crc", at=AT)
    root = ET.fromstring(odm(life.dc, RS, AT))
    group = root.find(".//o:ItemGroupDef[@Name='tb_enrolment']", NS)
    assert group is not None
    refs = {r.get("ItemOID") for r in group.findall("o:ItemRef", NS)}
    assert {"en_rand", "en_rand_date", "en_rand_no"} <= refs
    for oid in ("en_rand", "en_rand_date", "en_rand_no"):
        assert root.find(f".//o:ItemDef[@OID='{oid}']", NS) is not None
    data = {i.get("ItemOID"): i.get("Value") for i in root.iter("{http://www.cdisc.org/ns/odm/v1.3}ItemData")}
    assert data["en_rand_date"] == "2026-11-03" and data["en_rand_no"] == "R-0107"
    assert life.screen_detail(RS)["GZQO-0001"]["randomised"] == "2026-11-03"
    assert lc.randomised({"en_rand": "1"}) == "yes" and lc.randomised({"en_rand": "0"}) == ""


def test_the_deviation_form_has_a_class_and_a_sponsor_report_date() -> None:
    by = {f.name: f for f in fields()}
    assert by["dv_class"].form == "tb_deviation" and set(by["dv_class"].options) == {"1", "2", "9"}
    assert by["dv_rep_sponsor"].form == "tb_deviation" and by["dv_rep_sponsor"].kind == "date"


# ---------------------------------------------------------------------------------------------- LIFE-025
def _proposals_case(life: Lifecycle) -> None:
    life.set_schedule(RS, [Visit("v1", 7, 2, 2)], "trialbox", AT)
    # 0001: visit v1 done on day 12 of a 5-to-9 window; consent on an old form version
    life.ensure(RS, "GZQO-0001", "a1" * 16, "crc", AT)
    _put(life, "GZQO-0001", {"ic_date": "2026-10-01", "ic_version": "v1", "en_date": "2026-10-02",
                             "en_eligible": "1"})  # fmt: skip
    _put(life, "GZQO-0001", {"vs_status": "1", "vs_date": "2026-10-14"}, "v1")
    # 0002: enrolled before consent, while the screening log says not eligible
    life.ensure(RS, "GZQO-0002", "a2" * 16, "crc", AT)
    _put(life, "GZQO-0002", {"sl_date": "2026-10-01", "sl_eligible": "0", "sl_reason": "lab value",
                             "sl_criterion": "GZQO-EXC-06", "ic_date": "2026-10-05", "ic_version": "v2",
                             "en_date": "2026-10-03", "en_eligible": "1"})  # fmt: skip
    # 0003: everything in order: no proposal
    life.ensure(RS, "GZQO-0003", "a3" * 16, "crc", AT)
    _put(life, "GZQO-0003", {"ic_date": "2026-10-01", "ic_version": "v2", "en_date": "2026-10-02",
                             "en_eligible": "1"})  # fmt: skip
    _put(life, "GZQO-0003", {"vs_status": "1", "vs_date": "2026-10-09"}, "v1")


def test_possible_deviations_from_the_boxs_own_facts(life: Lifecycle) -> None:
    _proposals_case(life)
    rows = life.possible_deviations(RS, date(2026, 11, 10), icf_version="v2")
    got = sorted((r["record"], r["kind"], r["dv_kind"], r["day"], r["state"]) for r in rows)
    assert got == [
        ("GZQO-0001", "consent_version", "2", "2026-10-01", "open"),
        ("GZQO-0001", "visit_window", "3", "2026-10-14", "open"),
        ("GZQO-0002", "consent_after", "2", "2026-10-03", "open"),
        ("GZQO-0002", "eligibility", "1", "2026-10-03", "open"),
    ]
    elig = next(r for r in rows if r["kind"] == "eligibility")
    assert elig["detail"]["criterion"] == "GZQO-EXC-06"
    win = next(r for r in rows if r["kind"] == "visit_window")
    assert win["detail"] == {"visit": "v1", "done": "2026-10-14", "start": "2026-10-07", "end": "2026-10-11"}
    # no version in force known: no consent-version proposal (never a guess)
    assert not [r for r in life.possible_deviations(RS, date(2026, 11, 10)) if r["kind"] == "consent_version"]
    # the visit form's own "outside the window" answer is a proposal too
    _put(life, "GZQO-0003", {"vs_window": "0"}, "v1")
    assert [r["key"] for r in life.possible_deviations(RS, date(2026, 11, 10)) if r["record"] == "GZQO-0003"] == [
        "visit_window:v1"
    ]


def test_a_proposal_is_confirmed_as_an_entry_or_dismissed_with_a_reason(life: Lifecycle) -> None:
    _proposals_case(life)
    day = date(2026, 11, 10)
    with pytest.raises(LifeError) as e:
        life.decide_deviation(RS, "GZQO-0001", "visit_window:v1", "dismiss", by="crc", at=AT, today=day)
    assert e.value.why == "dismiss_reason"
    with pytest.raises(LifeError) as e:
        life.decide_deviation(RS, "GZQO-0001", "visit_window:v9", "confirm", by="crc", at=AT, today=day)
    assert e.value.why == "proposal"
    out = life.decide_deviation(RS, "GZQO-0001", "visit_window:v1", "confirm", by="crc", at=AT, today=day)
    assert (out["state"], out["event"]) == ("confirmed", "dv1")
    entry = life.dc.record(RS, "GZQO-0001", "dv1")
    assert (entry["dv_date"], entry["dv_kind"]) == ("2026-10-14", "3") and "outside its window" in entry["dv_what"]
    assert [h["source"] for h in life.dc.history(RS, "GZQO-0001") if h["event"] == "dv1"] == ["trialbox:proposed"] * 3
    with pytest.raises(LifeError) as e:
        life.decide_deviation(RS, "GZQO-0001", "visit_window:v1", "dismiss", reason="x", by="crc", at=AT, today=day)
    assert e.value.why == "decided"
    out = life.decide_deviation(RS, "GZQO-0002", "eligibility:screening_log", "dismiss",
                                reason="the PI re-checked the lab value", by="crc", at=AT, today=day)  # fmt: skip
    assert out["state"] == "dismissed" and out["event"] == ""
    assert not life.entries(RS, "GZQO-0002", lc.DV_EVENT)  # a dismissal writes no deviation entry
    states = {(r["record"], r["kind"]): r["state"] for r in life.possible_deviations(RS, day, "v2")}
    assert states[("GZQO-0001", "visit_window")] == "confirmed"
    assert states[("GZQO-0002", "eligibility")] == "dismissed"
    assert states[("GZQO-0002", "consent_after")] == "open"


class _Host:
    def __init__(self, dc: DataCore, audit: AuditLog) -> None:
        self.dc, self.audit, self.registry = dc, audit, None

    def now(self) -> datetime:
        return datetime(2026, 11, 10, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    def stamp(self) -> str:
        return self.now().isoformat()

    def client(self, token_ref: str) -> Any:
        raise AssertionError("no REDCap here")


def test_the_api_for_the_contact_rule_and_possible_deviations(life: Lifecycle, tmp_path: Path) -> None:
    _proposals_case(life)
    audit = AuditLog(tmp_path / "audit")
    host = _Host(life.dc, audit)
    api = FastAPI()
    api.include_router(life_router(lambda: host))
    c = SignedClient(api)
    assert c.get(f"/studies/{RS}/contact-rule").json()["max_attempts"] == 3
    r = c.put(f"/studies/{RS}/contact-rule", json={"max_attempts": 4, "min_days": 2, "by": "console:crc"})
    assert r.status_code == 200 and r.json()["max_attempts"] == 4
    r = c.put(f"/studies/{RS}/contact-rule", json={"max_attempts": 0, "min_days": 2, "by": "console:crc"})
    assert r.status_code == 409 and r.json()["detail"]["why"] == "contact_rule"
    out = c.get(f"/studies/{RS}/deviations/possible", params={"icf": "v2"}).json()
    assert out["open"] == 4 and out["today"] == "2026-11-10"
    body = {"record": "GZQO-0002", "key": "consent_after:enrolment", "decision": "confirm", "by": "console:crc",
            "icf": "v2"}  # fmt: skip
    r = c.post(f"/studies/{RS}/deviations/possible", json=body)
    assert r.status_code == 200 and r.json()["row"]["event"] == "dv1"
    r = c.post(f"/studies/{RS}/deviations/possible", json=body)
    assert r.status_code == 409 and r.json()["detail"]["why"] == "decided"
    events = [
        json.loads(x)["event"] for f in sorted(audit.directory.glob("*.jsonl")) for x in f.read_text().splitlines()
    ]
    assert {"life.contact_rule", "life.deviation_call", "life.refused"} <= set(events)
