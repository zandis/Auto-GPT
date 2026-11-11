"""D-277 (fix group CR-008 to CR-011) and T-602: the SAE clock and register hardened.

The pure clock first (the 24-hour report in hours, a fatal AE always serious, a "reported on" day that cannot be
right, expectedness, named rule sets per study with the regulator from the site's country, a clock with no party left
or a rule nobody knows as an alert), then the orchestrator (two studies, two clocks; the study's rule set and who
confirmed it), then the console (the register written on the write path only, the copy to the trial office, the
investigator's acknowledgement on the case page, the rule on the set-up page and on the register, the regulator named
from the site's country in every language, a home page that never reads "no SAE" when the answer is unknown)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from console import saerecord as sr
from datacore import lifecycle as lc

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name

TPE = timezone(timedelta(hours=8))
TW = lc.report_rules("Asia/Taipei")


def _ae(**kw: str) -> dict[str, Any]:
    e = {"record": "S-001", "event": "ae1", "ae_serious": "1", "ae_outcome": "2", "ae_serious_why": "3",
         "ae_onset": "2027-05-17", "ae_aware": "2027-05-17", "ae_aware_time": "10:00"}  # fmt: skip
    e.update(kw)
    return e


def _party(clock: list[dict[str, Any]], party: str) -> dict[str, Any]:
    return next(c for c in clock if c["party"] == party)


# ------------------------------------------------------------------------------------------- the clock (pure)
def test_the_24_hour_report_is_counted_in_hours() -> None:
    """LIFE-022: learned 2027-05-17 10:00; at +23 h the sponsor report is not overdue, at +25 h it is (it used to be
    first overdue on 05-19, two days later)."""
    e = _ae()
    at23 = datetime(2027, 5, 18, 9, 0, tzinfo=TPE)
    at25 = datetime(2027, 5, 18, 11, 0, tzinfo=TPE)
    c23 = _party(lc.report_clock(e, at23.date(), TW, at23), "sponsor")
    c25 = _party(lc.report_clock(e, at25.date(), TW, at25), "sponsor")
    assert c23["hours"] == 24 and c23["due_at"] == "2027-05-18T10:00+08:00" and not c23["overdue"]
    assert c25["overdue"]
    # the register agrees, on the same moment
    v = sr.case_view({**e, "clock": lc.report_clock(e, at25.date(), TW, at25)}, None, [], at25.date(), {}, at25)
    assert next(r for r in v["reports"] if r["party"] == "sponsor")["state"] == "overdue" and v["alert"]
    v = sr.case_view({**e, "clock": lc.report_clock(e, at23.date(), TW, at23)}, None, [], at23.date(), {}, at23)
    assert next(r for r in v["reports"] if r["party"] == "sponsor")["state"] == "due_today" and not v["overdue"]
    # no time entered: from 00:00 of the day learned (the strictest reading), and the page asks for the time
    bare = _ae(ae_aware_time="")
    assert _party(lc.report_clock(bare, at23.date(), TW, at23), "sponsor")["overdue"]
    v = sr.case_view({**bare, "clock": lc.report_clock(bare, at23.date(), TW, at23)}, None, [], at23.date(), {}, at23)
    assert "aware_time_missing" in v["flags"]
    # the 7- and 15-day reports stay calendar days
    assert _party(lc.report_clock(e, at25.date(), TW, at25), "irb")["due"] == "2027-06-01"


def test_a_fatal_ae_is_serious_whatever_the_radio_says() -> None:
    """CR-008: a fatal AE with Serious = No has a clock, a case and an alert asking to correct the form."""
    fatal_no = _ae(ae_serious="0", ae_outcome="5", ae_serious_why="")
    assert lc.is_serious(fatal_no) and lc.grave(fatal_no)
    clock = lc.report_clock(fatal_no, date(2027, 5, 17), TW)
    assert {c["party"] for c in clock} == {"sponsor", "irb", "regulator"}
    assert _party(clock, "irb")["days"] == 7
    v = sr.case_view({**fatal_no, "clock": clock}, None, [], date(2027, 5, 17), {})
    assert "serious_mismatch" in v["flags"] and v["alert"]
    # a "why serious" answer with Serious unanswered (an import) is serious; an explicit No with a reason left over
    # from before (the form hides the field and keeps it) is a correction that takes effect
    assert lc.is_serious(_ae(ae_serious="", ae_serious_why="3"))
    assert not lc.is_serious(_ae(ae_serious="0", ae_serious_why="3"))
    assert not lc.is_serious(_ae(ae_serious="0", ae_serious_why=""))


def test_a_reported_day_that_cannot_be_right_does_not_clear_overdue() -> None:
    """CR-010: "reported on" 2099 (or before the event) does not count as sent."""
    for bad in ("2099-01-01", "2027-05-01", "not a day"):
        c = _party(lc.report_clock(_ae(ae_rep_irb=bad), date(2027, 6, 10), TW), "irb")
        assert c["overdue"] and c["bad_done"], bad
    good = _party(lc.report_clock(_ae(ae_rep_irb="2027-05-20"), date(2027, 6, 10), TW), "irb")
    assert not good["overdue"] and not good["bad_done"]


def test_regulator_clock_off_for_an_expected_event() -> None:
    """LIFE-024: expected per the reference safety information: no regulator report is counted."""
    rules = lc.clock_rules("tw_trial", "Asia/Taipei")["parties"]
    exp = _ae(ae_expected="1")
    assert "regulator" not in {c["party"] for c in lc.report_clock(exp, date(2027, 5, 18), rules)}
    assert "regulator" in {c["party"] for c in lc.report_clock(_ae(ae_expected="0"), date(2027, 5, 18), rules)}
    v = sr.case_view({**exp, "clock": lc.report_clock(exp, date(2027, 5, 18), rules)}, None, [], date(2027, 5, 18),
                     {}, rules={"parties": rules, "problems": []})  # fmt: skip
    assert "expected_noreg" in v["flags"]


def test_named_rule_sets_and_the_regulator_from_the_site_country() -> None:
    """LIFE-023, UX-005, CR-009: a study names its set; the regulator comes from the set's country; an unknown name
    or a zone of no known country is an alert, never the Taiwan clock."""
    jp = lc.clock_rules("jp_crb", "Asia/Tokyo")
    assert jp["regulator"] == "MHLW" and jp["parties"]["irb"] == (7, 15) and jp["problems"] == []
    tw = lc.clock_rules("", "Asia/Taipei")
    assert tw["name"] == "tw_trial" and tw["regulator"] == "TFDA" and tw["problems"] == ["default_rules"]
    assert lc.clock_rules("", "Asia/Tokyo")["regulator"] == "PMDA"
    assert lc.clock_rules("", "Japan")["country"] == "JP"  # site.tz: Japan is Japan, not Taiwan (CR-009)
    unknown = lc.clock_rules("jp_gcp_typo", "Asia/Tokyo")
    assert unknown["parties"] == {} and {"unknown_rules", "noclock"} <= set(unknown["problems"])
    nowhere = lc.clock_rules("", "Europe/Paris")
    assert nowhere["parties"] == {} and "no_country" in nowhere["problems"]
    assert "other_country" in lc.clock_rules("jp_gcp", "Asia/Taipei")["problems"]
    bad = lc.clock_rules("tw_trial", "Asia/Taipei", "irb=7/x, sponsor=1")
    assert "bad_override" in bad["problems"] and bad["parties"]["irb"] == (7, 15)
    assert set(lc.RULE_SETS) >= {"jp_gcp", "jp_gcp_ii", "jp_crb", "jp_guideline", "tw_trial", "tw_research"}


def test_clocks_zero_raise_an_alert() -> None:
    """S-16: every party set to 0 leaves a serious AE with no clock: an alert, not a quiet row."""
    rules = lc.clock_rules("tw_trial", "Asia/Taipei", "sponsor=0,irb=0,regulator=0")
    assert rules["parties"] == {"sponsor": (0, 0), "irb": (0, 0), "regulator": (0, 0)}
    assert "noclock" in rules["problems"] and "noclock" in lc.RULE_ALERTS
    e = _ae()
    v = sr.case_view({**e, "clock": lc.report_clock(e, date(2027, 5, 18), rules["parties"])}, None, [],
                     date(2027, 5, 18), {}, rules=rules)  # fmt: skip
    assert "noclock" in v["flags"] and v["alert"]


def test_death_ends_the_participant(lb: dict[str, Any]) -> None:  # noqa: F811
    """CR-011 (PR #60 M5): a fatal AE moves the participant on study to withdrawn, reason 5 (Death)."""
    dc = lb["dc"]
    life = lc.Lifecycle(dc)
    life.ensure("DTH", "D-001", "", "t", "2027-01-01T00:00:00+00:00")
    for st, day in (("approached", "2027-01-02"), ("consented", "2027-01-03"), ("enrolled", "2027-01-04")):
        life.step("DTH", "D-001", st, by="t", at=f"{day}T01:00:00+00:00", on_day=day)
    for f, v in {"ae_outcome": "5", "ae_death_date": "2027-02-10", "ae_onset": "2027-02-09"}.items():
        dc.write("DTH", "D-001", "ae1", f, v, "t", "2027-02-11T00:00:00+00:00", "trialbox")
    out = life.derive("DTH", "D-001", by="t", at="2027-02-11T00:00:00+00:00")
    sub = life.subject("DTH", "D-001")
    assert sub is not None and sub["state"] == "withdrawn" and sub["reason"] == "5" and sub["since"] == "2027-02-10"
    assert out["steps"][-1]["source"] == "form:tb_adverse_event:ae1"


def test_one_initial_report_per_party_and_case() -> None:
    """CR-011 (PR #60 M7): the report rows have a unique index."""
    store = sr.SaeStore()
    store.db.execute("INSERT INTO sae_report (ruleset, record, event, party, kind, by, at) VALUES "
                     "('U1','R','ae1','irb','initial','t','x')")  # fmt: skip
    with pytest.raises(Exception, match="(?i)unique|duplicate"):
        store.db.execute("INSERT INTO sae_report (ruleset, record, event, party, kind, by, at) VALUES "
                         "('U1','R','ae1','irb','initial','t','y')")  # fmt: skip
    store.add_followup("U1", "R", "ae1", "irb", "2027-06-01", "", "t", "z")  # requested follow-ups: many allowed
    store.add_followup("U1", "R", "ae1", "irb", "2027-06-02", "", "t", "z")
    store.close()


# ------------------------------------------------------------------------------------------- orchestrator
def test_two_studies_two_clocks(lb: dict[str, Any]) -> None:  # noqa: F811
    """LIFE-023: the same SAE in two studies at one site: each study's named set gives its own clock, and the API
    names the set and who confirmed it."""
    oc = lb["oc"]
    values = {"ae_term": "Event", "ae_onset": "2027-05-17", "ae_aware": "2027-05-17", "ae_aware_time": "10:00",
              "ae_serious": "1", "ae_serious_why": "3", "ae_outcome": "2"}  # fmt: skip
    for rs, rule in (("STA", "tw_trial"), ("STB", "tw_research")):
        assert oc.post(f"/studies/{rs}/forms/builtin", json={"by": "t"}).status_code == 200
        r = oc.put(f"/studies/{rs}/sae-rule", json={"rule_set": rule, "by": "console:crc"})
        assert r.status_code == 200, r.text
        assert oc.put(f"/studies/{rs}/data/A-1", json={"event": "ae1", "values": values, "by": "t"}).status_code == 200
    got = {}
    for rs in ("STA", "STB"):
        out = oc.get(f"/studies/{rs}/aes?today=2027-05-18&now=2027-05-18T11:00:00%2B08:00").json()
        got[rs] = {c["party"]: c for c in out["serious"][0]["clock"]}
        assert out["rules"]["confirmed_by"] == "console:crc" and out["rules"]["source"] == "study"
    assert set(got["STA"]) == {"sponsor", "irb", "regulator"} and got["STA"]["sponsor"]["overdue"]
    assert set(got["STB"]) == {"irb"} and not got["STB"]["irb"]["overdue"]
    assert oc.put("/studies/STA/sae-rule", json={"rule_set": "nonsense", "by": "x"}).status_code == 409
    # a study with every party at 0 (the box override): the API lists it as an alert
    import os

    os.environ["TB_SAE_REPORT_DAYS"] = "sponsor=0,irb=0,regulator=0"
    try:
        out = oc.get("/studies/STA/aes?today=2027-05-18").json()
    finally:
        del os.environ["TB_SAE_REPORT_DAYS"]
    assert out["serious"][0]["noclock"] and out["alerts"] and "noclock" in out["rules"]["problems"]


# ------------------------------------------------------------------------------------------- the console
def _audit(d: Any) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted(d.glob("*.jsonl")) for x in f.read_text().splitlines() if x]


FATAL = {"ae_term": "Myocardial infarction", "ae_onset": "2026-11-09", "ae_aware": "2026-11-09",
         "ae_aware_time": "09:00", "ae_serious": "1", "ae_serious_why": "1", "ae_severity": "3", "ae_outcome": "5",
         "ae_related": "9"}  # fmt: skip


def test_write_path_office_copy_ack_and_named_rule(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """CR-012: a page view writes nothing; the AE form's save writes the case (system:sync). FIT-025: the new case
    goes to the trial office's mailbox without the AE term; the register names the rule set and who confirmed it.
    UX-028: the investigator acknowledges on the case page. UX-005: the regulator's name is the same in every
    language."""
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "trial-office@hospa.test")
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    lb["clock"]["now"] = datetime(2026, 11, 10, 0, 30, tzinfo=UTC)
    # the rule on the set-up page: the coordinator chooses it and so confirms it
    page = c.get("/studies/GZQO/setup").text
    assert 'data-testid="setup-sae"' in page and 'value="tw_research"' in page
    r = c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"}, follow_redirects=True)
    assert r.status_code == 200 and "Confirmed by crc" in r.text
    from console.saerecord import SaeStore

    # an AE written straight into the data core (as the REDCap read-back would): a page view does not write it
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "ae1", "values": FATAL, "by": "rc:read"})
    page = c.get("/sae").text
    assert f'data-testid="sae-row-GZQO-{no}-ae1"' in page and SaeStore().case("GZQO", no, "ae1") is None
    assert not lb["backend"].notices
    # the coordinator's "bring up to date" (or the daily job) writes it, as system:sync, and copies the office
    assert c.post("/studies/GZQO/sae/sync", data={"csrf": csrf}).status_code in (200, 303)
    case = SaeStore().case("GZQO", no, "ae1")
    assert case is not None and case["created_by"] == sr.SYNC
    office = [n for n in lb["backend"].notices if n[1] == ["trial-office@hospa.test"]]
    assert len(office) == 1 and no in office[0][2] and "Myocardial" not in office[0][3] and "tw_trial" in office[0][3]
    # a save through the console is the other write path: the second AE is in the register at once
    _save(c, csrf, no, "tb_adverse_event", {**FATAL, "ae_term": "Stroke"}, "ae2")
    assert SaeStore().case("GZQO", no, "ae2") is not None
    assert len([n for n in lb["backend"].notices if n[1] == ["trial-office@hospa.test"]]) == 2
    # the worklist names the rule set, the regulator (TFDA in every language) and who confirmed it
    page = c.get("/sae").text
    assert 'data-testid="sae-rules-GZQO"' in page and "tw_trial" not in page  # the set's name, in words
    assert "Taiwan, 人體試驗" in page and "Regulator (TFDA)" in page and 'data-testid="sae-confirmed"' in page
    assert 'data-testid="sae-legend"' in page
    for lang in ("ja", "zh-TW"):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/sae"})
        assert "TFDA" in c.get("/sae").text and "PMDA" not in c.get("/sae").text
    c.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/sae"})
    # the investigator acknowledges on the case page; the coordinator may not
    case_page = c.get(f"/studies/GZQO/sae/{no}/ae1").text
    assert 'data-testid="sae-case-ack"' not in case_page and 'data-testid="sae-due-at-sponsor"' in case_page
    assert c.post(f"/studies/GZQO/sae/{no}/ae1/ack", data={"csrf": csrf}).status_code == 403
    p, pcsrf = login(lb["app"], "pi", PW)
    assert 'data-testid="sae-case-ack"' in p.get(f"/studies/GZQO/sae/{no}/ae1").text
    r = p.post(f"/studies/GZQO/sae/{no}/ae1/ack", data={"csrf": pcsrf}, follow_redirects=True)
    assert 'data-testid="sae-acked"' in r.text and 'data-testid="sae-case-ack"' not in r.text
    assert any(t["action"] == "ack" for t in SaeStore().trail("GZQO", no, "ae1"))
    # a page view by the investigator wrote nothing as the investigator
    assert not [x for x in _audit(lb["backend"].audit_dir) if x["event"] == "console.sae" and x["actor"] == "console:pi"]


def test_home_page_never_reads_no_sae_when_unknown(lb: dict[str, Any]) -> None:  # noqa: F811
    """CR-010: the orchestrator does not answer: the home page says the SAEs are unknown."""
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    from console.backend import Unavailable

    real = lb["backend"].study_api

    def flaky(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if "/aes" in path:
            raise Unavailable("orchestrator down")
        return real(method, path, body)

    lb["backend"].study_api = flaky
    assert 'data-testid="sae-home-failed"' in c.get("/home").text


def test_rule_follow_ups_reach_the_home_page_and_the_mail(lb: dict[str, Any]) -> None:  # noqa: F811
    """CR-010: an overdue rule follow-up (regulator, day 15 for a fatal SAE) is listed with the overdue reports."""
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    lb["clock"]["now"] = datetime(2026, 11, 30, 1, 0, tzinfo=UTC)
    sent = {"ae_rep_sponsor": "2026-11-09", "ae_rep_irb": "2026-11-10", "ae_rep_reg": "2026-11-10"}
    _save(c, csrf, no, "tb_adverse_event", {**FATAL, **sent}, "ae1")
    rows = lb["app"].state.helpers.life_reports("GZQO")
    assert [(r["party"], r.get("kind")) for r in rows] == [("regulator", "followup")]
    assert f'data-testid="sae-report-{no}-ae1-regulator"' in c.get("/home").text
