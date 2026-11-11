"""D-399 (T-302a, FIT-009, LIFE-018, LIFE-019): the consent record in the data core and the study's approved
consent-form (ICF) versions in the team store.

* an enrolment without a consent record holds the subject before "consented" (never implied), with the alert's source;
* an enrolment or a visit dated before the consent is flagged, and nothing is moved;
* every consent is read: the first, the old re-consent slot and each re-consent on its ``rcN`` event;
* a consent's version is checked against the approved list on the consent's day (a warning, never a refusal);
* a new version that asks for re-consent lists the subjects on study still on an older one; a re-consent on the new
  version takes the subject off the list;
* the ICF list keeps history rows: a change and a withdrawal are new rows, the IRB record reads the newest version."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from console.teamstore import IcfVersion, Irb, TeamError, TeamStore
from datacore import lifecycle as lc
from datacore.builtin import builtin_questionnaires
from datacore.lifecycle import Lifecycle, LifeError, Visit
from datacore.store import DataCore

AT = "2026-11-08T09:00:00+09:00"
RS = "GZQO"


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


def _subject(life: Lifecycle, rec: str) -> None:
    life.ensure(RS, rec, "", "crc", AT)
    life.step(RS, rec, "approached", by="crc", at=AT, on_day="2026-10-01")


# ---------------------------------------------------------------------------------------------- acceptance 1 and 2
def test_an_enrolment_without_a_consent_record_is_held_with_an_alert(life: Lifecycle) -> None:
    _subject(life, "GZQO-0001")
    _put(life, "GZQO-0001", {"en_date": "2026-10-05", "en_eligible": "1"})
    out = life.derive(RS, "GZQO-0001", by="crc", at=AT)
    assert out["steps"] == [] and out["held"] == [{"state": "consented", "why": "consent_missing",
                                                  "current": "approached", "source": "form:tb_enrolment"}]  # fmt: skip
    assert (life.subject(RS, "GZQO-0001") or {})["state"] == "approached"
    assert life.consent_missing(RS, "GZQO-0001", "approached") == "form:tb_enrolment"
    # the consent form saved: the subject walks on, and the alert is gone
    _put(life, "GZQO-0001", {"ic_date": "2026-10-03", "ic_version": "v1"})
    out = life.derive(RS, "GZQO-0001", by="crc", at=AT)
    assert [s["to"] for s in out["steps"]] == ["consented", "enrolled"]
    assert life.consent_missing(RS, "GZQO-0001", "enrolled") == ""
    assert life.consent_record(RS, "GZQO-0001", "enrolled")["flags"] == []


def test_a_visit_or_an_enrolment_before_consent_is_flagged_and_nothing_moves(life: Lifecycle) -> None:
    _subject(life, "GZQO-0002")
    _put(life, "GZQO-0002", {"ic_date": "2026-10-10", "ic_version": "v1", "en_date": "2026-10-08", "en_eligible": "1"})
    _put(life, "GZQO-0002", {"vs_status": "1", "vs_date": "2026-10-09"}, "v1")
    _put(life, "GZQO-0002", {"vs_status": "1", "vs_date": "2026-10-20"}, "v2")
    life.derive(RS, "GZQO-0002", by="crc", at=AT)
    rec = life.consent_record(RS, "GZQO-0002", "on_study")
    assert rec["flags"] == [
        {"flag": "enrolment_before_consent", "day": "2026-10-08", "event": "", "consent_day": "2026-10-10"},
        {"flag": "visit_before_consent", "day": "2026-10-09", "event": "v1", "consent_day": "2026-10-10"},
    ]
    assert life.dc.record(RS, "GZQO-0002")["en_date"] == "2026-10-08"  # flagged, never changed
    assert {f for f in lc.CONSENT_FLAGS} >= {f["flag"] for f in rec["flags"]}


def test_past_consent_without_a_consent_form_is_flagged_where_the_study_records_consent(life: Lifecycle) -> None:
    _subject(life, "GZQO-0003")
    life.step(RS, "GZQO-0003", "consented", by="crc", at=AT, on_day="2026-10-02")  # a person's step, no form
    assert life.records_consent(RS)
    assert [f["flag"] for f in life.consent_record(RS, "GZQO-0003", "consented")["flags"]] == ["no_consent_form"]
    # a sponsor study (its CRF holds consent): nothing to flag here
    assert life.consent_record(RS, "GZQO-0003", "consented", here=False)["flags"] == []


def test_every_consent_is_read_oldest_first_with_the_next_reconsent_event(life: Lifecycle) -> None:
    _subject(life, "GZQO-0004")
    _put(life, "GZQO-0004", {"ic_date": "2026-01-10", "ic_version": "v1", "ic_reconsent": "1",
                             "ic_reconsent_date": "2026-05-01", "ic_reconsent_version": "v2"})  # fmt: skip
    _put(life, "GZQO-0004", {"ic_date": "2026-09-01", "ic_version": "v3"}, "rc1")
    rec = life.consent_record(RS, "GZQO-0004", "on_study")
    assert [(c["day"], c["version"], c["event"], c["kind"]) for c in rec["consents"]] == [
        ("2026-01-10", "v1", "", "first"), ("2026-05-01", "v2", "", "reconsent"), ("2026-09-01", "v3", "rc1",
                                                                                   "reconsent")]  # fmt: skip
    assert rec["last"]["version"] == "v3" and rec["next_rc"] == "rc2"


def test_a_visit_is_never_named_like_a_reconsent_event() -> None:
    with pytest.raises(LifeError):
        lc.check_visit(Visit("rc1", 7))


# ---------------------------------------------------------------------------------------------- the version check
LIST = [
    {"version": "v1", "irb_approved_on": "2026-01-01", "effective_from": "2026-01-01", "reconsent": True, "seq": 1},
    {"version": "v2", "irb_approved_on": "2026-06-01", "effective_from": "2026-06-15", "reconsent": True, "seq": 2},
    {"version": "v3", "irb_approved_on": "", "effective_from": "", "reconsent": True, "seq": 3},
]


@pytest.mark.parametrize(
    ("version", "day", "want"),
    [
        ("v1", "2026-03-01", []),
        ("V 1", "2026-03-01", []),  # spaces and case do not matter
        ("v2", "2026-07-01", []),
        ("v9", "2026-07-01", ["icf_not_listed"]),
        ("v3", "2026-07-01", ["icf_unapproved"]),
        ("v2", "2026-06-10", ["icf_not_yet"]),  # approved, not yet in use
        ("v1", "2026-07-01", ["icf_superseded"]),
    ],
)
def test_the_consent_version_is_checked_against_the_approved_list(version: str, day: str, want: list[str]) -> None:
    assert lc.icf_check(LIST, version, day) == want


def test_no_approved_list_says_so() -> None:
    assert lc.icf_check([], "v1", "2026-07-01") == ["icf_none"]
    assert lc.icf_in_force(LIST, date(2026, 6, 14))["version"] == "v1"  # type: ignore[index]


# ---------------------------------------------------------------------------------------------- acceptance 3
def _subs(life: Lifecycle) -> list[dict[str, Any]]:
    return [{**s, "consent": life.consent_record(RS, str(s["record"]), str(s["state"]))} for s in life.subjects(RS)]


def test_a_new_icf_version_lists_the_subjects_to_reconsent(life: Lifecycle) -> None:
    for rec in ("GZQO-0011", "GZQO-0012", "GZQO-0013", "GZQO-0014"):
        _subject(life, rec)
        _put(life, rec, {"ic_date": "2026-02-01", "ic_version": "v1", "en_date": "2026-02-02", "en_eligible": "1"})
        life.derive(RS, rec, by="crc", at=AT)
    _put(life, "GZQO-0014", {"wd_date": "2026-03-01", "wd_reason": "1"})  # withdrawn: not asked again
    life.derive(RS, "GZQO-0014", by="crc", at=AT)
    one = [LIST[0]]
    assert lc.reconsent_due(_subs(life), one, date(2026, 7, 1))["rows"] == []  # nothing new
    # v2 approved, in use from 06-15 and asks for re-consent: the three on study are listed from that day
    two = LIST[:2]
    assert lc.reconsent_due(_subs(life), two, date(2026, 6, 14))["target"]["version"] == "v1"
    due = lc.reconsent_due(_subs(life), two, date(2026, 7, 1))
    assert due["target"]["version"] == "v2"
    assert [(r["record"], r["version"], r["next_rc"]) for r in due["rows"]] == [
        ("GZQO-0011", "v1", "rc1"), ("GZQO-0012", "v1", "rc1"), ("GZQO-0013", "v1", "rc1")]  # fmt: skip
    # a re-consent on v2 takes the subject off the list
    _put(life, "GZQO-0012", {"ic_date": "2026-07-02", "ic_version": "v2"}, "rc1")
    due = lc.reconsent_due(_subs(life), two, date(2026, 7, 3))
    assert [r["record"] for r in due["rows"]] == ["GZQO-0011", "GZQO-0013"]
    # a version that does not ask for re-consent (only for new subjects) lists nobody
    quiet = [LIST[0], {**LIST[1], "reconsent": False}]
    assert lc.reconsent_due(_subs(life), quiet, date(2026, 7, 3)) == {"target": LIST[0], "rows": []}


# ---------------------------------------------------------------------------------------------- the ICF list
def test_icf_list_keeps_history_rows_and_the_irb_record_reads_the_newest() -> None:
    t = TeamStore()
    rec = t.save_irb(RS, Irb("IRB-1", "2026-01-01", "2027-01-01", "v1", "2025-12-20"), "crc1", "2026-01-02T00:00:00")
    assert [(v.version, v.irb_approved_on, v.effective_from) for v in t.icf_list(RS)] == [("v1", "2026-01-01",
                                                                                          "2026-01-01")]  # fmt: skip
    assert rec.icf_version == "v1" and rec.warnings(date(2026, 3, 1)) == []
    t.add_icf(RS, IcfVersion("v2", "2026-05-20", "2026-06-01", "2026-06-15"), "crc1", "2026-06-02T00:00:00")
    assert t.irb(RS).icf_version == "v2"  # the IRB record reads the newest version on the list
    # a change is a new row; the list shows the newest; the history keeps both
    t.add_icf(RS, IcfVersion("v2", "2026-05-20", "2026-06-01", "2026-06-20", reconsent=False), "crc1",
              "2026-06-03T00:00:00")  # fmt: skip
    v2 = next(v for v in t.icf_list(RS) if v.version == "v2")
    assert v2.effective_from == "2026-06-20" and not v2.reconsent
    with pytest.raises(TeamError):
        t.add_icf(RS, IcfVersion("v3", "", "2026-08-01", "2026-07-01"), "crc1", "2026-06-04T00:00:00")
    with pytest.raises(TeamError):
        t.add_icf(RS, IcfVersion("v 3; drop", "", "2026-08-01"), "crc1", "2026-06-04T00:00:00")
    with pytest.raises(TeamError):
        t.withdraw_icf(RS, "v2", "", "crc1", "2026-06-05T00:00:00")  # a withdrawal says why
    t.withdraw_icf(RS, "v2", "entered by mistake", "crc1", "2026-06-05T00:00:00")
    assert [v.version for v in t.icf_list(RS)] == ["v1"] and t.irb(RS).icf_version == "v1"
    assert [(v.version, v.action) for v in t.icf_history(RS)] == [("v1", "add"), ("v2", "add"), ("v2", "add"),
                                                                  ("v2", "withdraw")]  # fmt: skip
    rows = [v.as_row() for v in t.icf_list(RS)]
    assert lc.icf_check(rows, "v2", "2026-07-01") == ["icf_not_listed"]
