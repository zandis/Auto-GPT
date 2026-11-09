"""D-191 (independent plan review PR-17): the SAE register, one record per serious AE on the one reporting clock.

The clock's edge cases (time zones, calendar days over weekends and holidays, the day learned before the onset, late
awareness, no start day, the follow-up deadline) on the pure functions, then the register and the worklist end to end
on the console: create and change trail, the sent day written to the AE form, receipts and follow-ups, the audit
without the AE term, the alert in three languages, and the role table (deny by default)."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from console import saerecord as sr
from console.i18n_sae import EN, JA, ZH
from console.timefmt import local_today
from datacore import lifecycle as lc
from tb_common.authz import ROLE_SAE_ACTIONS, sae_allowed

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name

TW, JP = lc.report_rules("Asia/Taipei"), lc.report_rules("Asia/Tokyo")
FU = sr.followup_rules()


def _ae(**kw: str) -> dict[str, Any]:
    e = {"record": "S-001", "event": "ae1", "ae_serious": "1", "ae_outcome": "2", "ae_serious_why": "3",
         "ae_onset": "", "ae_aware": ""}  # fmt: skip
    e.update(kw)
    return e


def _view(e: dict[str, Any], today: date, rules: dict[str, tuple[int, int]] = TW,
          reports: list[dict[str, Any]] | None = None) -> dict[str, Any]:  # fmt: skip
    """The orchestrator's view (its clock from lc.report_clock) and the worklist row built from it."""
    e = {**e, "clock": lc.report_clock(e, today, rules), "serious": True}
    return sr.case_view(e, None, reports or [], today, FU)


def _rep(v: dict[str, Any], kind: str, party: str) -> dict[str, Any]:
    return next(r for r in v["reports"] if r["kind"] == kind and r["party"] == party)


# ------------------------------------------------------------------------------------------- the clock's edge cases
def test_site_date_not_server_date_in_tokyo_and_taipei() -> None:
    """The deadline is a site calendar day: a server on UTC must not count it a day late or early."""
    tokyo, taipei = ZoneInfo("Asia/Tokyo"), ZoneInfo("Asia/Taipei")
    assert local_today(datetime(2026, 11, 10, 14, 59, tzinfo=UTC), tokyo) == date(2026, 11, 10)  # 23:59 JST
    assert local_today(datetime(2026, 11, 10, 15, 0, tzinfo=UTC), tokyo) == date(2026, 11, 11)  # 00:00 JST
    assert local_today(datetime(2026, 11, 10, 15, 59), taipei) == date(2026, 11, 10)  # naive = UTC; 23:59 CST
    assert local_today(datetime(2026, 11, 10, 16, 0), taipei) == date(2026, 11, 11)
    # Japan: the IRB (through the head of the institution) at once; Taiwan: 7 / 15 days
    e = _ae(ae_onset="2026-11-09", ae_aware="2026-11-09")
    assert _rep(_view(e, date(2026, 11, 10), JP), "initial", "irb")["due"] == "2026-11-10"
    assert _rep(_view(e, date(2026, 11, 10), TW), "initial", "irb")["due"] == "2026-11-24"
    # the same instant, two site days: due today at 23:59 site time, overdue one minute later
    at_2359 = local_today(datetime(2026, 11, 10, 14, 59, tzinfo=UTC), tokyo)
    at_0000 = local_today(datetime(2026, 11, 10, 15, 0, tzinfo=UTC), tokyo)
    assert _rep(_view(e, at_2359, JP), "initial", "sponsor")["state"] == "due_today"
    assert _rep(_view(e, at_0000, JP), "initial", "sponsor")["state"] == "overdue"
    # neither zone has daylight saving: a year of site days keeps the same offset
    assert {datetime(2026, m, 1, tzinfo=tokyo).utcoffset() for m in range(1, 13)} == {
        datetime(2026, 1, 1, tzinfo=tokyo).utcoffset()
    }


def test_calendar_days_weekends_and_holidays_do_not_move_a_deadline() -> None:
    """The rules count calendar days (J-GCP 直ちに; the Taiwanese IRB SOPs): a due day on a Saturday or a public
    holiday stays there, it is not pushed to the next working day."""
    fri = _ae(ae_onset="2026-11-06", ae_aware="2026-11-06")  # Friday
    v = _view(fri, date(2026, 11, 8))  # Sunday
    assert _rep(v, "initial", "sponsor")["due"] == "2026-11-07"  # Saturday, not Monday the 9th
    assert _rep(v, "initial", "sponsor")["state"] == "overdue"
    culture = _ae(ae_onset="2026-11-02", ae_aware="2026-11-02")  # the day before 文化の日 (2026-11-03)
    assert _rep(_view(culture, date(2026, 11, 3), JP), "initial", "irb")["due"] == "2026-11-03"
    assert _rep(_view(culture, date(2026, 11, 4), JP), "initial", "irb")["state"] == "overdue"
    national = _ae(ae_onset="2026-10-09", ae_aware="2026-10-09", ae_outcome="5")  # 國慶日 10-10, a Saturday
    v = _view(national, date(2026, 10, 12), TW)
    assert _rep(v, "initial", "sponsor")["due"] == "2026-10-10" and _rep(v, "initial", "irb")["due"] == "2026-10-16"


def test_awareness_before_onset_is_flagged_and_the_clock_uses_the_earlier_day() -> None:
    e = _ae(ae_onset="2026-11-05", ae_aware="2026-11-03")
    v = _view(e, date(2026, 11, 5))
    assert v["flags"] == ["aware_before_onset"] and v["alert"]
    assert _rep(v, "initial", "sponsor")["due"] == "2026-11-04"  # from the day learned, the stricter day
    assert _rep(v, "initial", "sponsor")["state"] == "overdue"


def test_late_awareness_counts_from_the_day_learned() -> None:
    e = _ae(ae_onset="2026-10-01", ae_aware="2026-11-01")
    v = _view(e, date(2026, 11, 2))
    assert v["flags"] == ["late_aware"]
    assert _rep(v, "initial", "irb")["due"] == "2026-11-16"  # 15 days from 11-01, not from the onset
    # counted from the onset every deadline would have passed; from the day learned the sponsor's is today
    assert v["overdue"] == 0 and _rep(v, "initial", "sponsor")["state"] == "due_today"
    # learned within the shortest window: no flag
    assert _view(_ae(ae_onset="2026-11-01", ae_aware="2026-11-02"), date(2026, 11, 2))["flags"] == []


def test_no_start_day_is_an_alert_not_a_quiet_row_and_no_aware_counts_from_onset() -> None:
    v = _view(_ae(), date(2026, 11, 2))
    assert v["flags"] == ["nostart"] and v["alert"]
    assert {r["state"] for r in v["reports"]} == {"nostart"}
    v = _view(_ae(ae_onset="2026-11-01"), date(2026, 11, 2))
    assert v["flags"] == ["aware_missing"] and _rep(v, "initial", "sponsor")["due"] == "2026-11-02"
    assert _rep(v, "initial", "sponsor")["state"] == "due_today"


def test_follow_up_deadline_on_the_same_clock() -> None:
    """ICH E2A: a fatal or life-threatening case, reported to the regulator, is completed 8 days after that report."""
    grave = _ae(ae_onset="2026-11-01", ae_aware="2026-11-01", ae_serious_why="1", ae_rep_reg="2026-11-05")
    v = _view(grave, date(2026, 11, 13))
    fu = _rep(v, "followup", "regulator")
    assert fu["due"] == "2026-11-13" and fu["state"] == "due_today" and fu["origin"] == "rule"
    assert _rep(_view(grave, date(2026, 11, 14)), "followup", "regulator")["state"] == "overdue"
    done = [{"kind": "followup", "origin": "rule", "party": "regulator", "sent_on": "2026-11-12", "id": 7}]
    assert _rep(_view(grave, date(2026, 11, 20), reports=done), "followup", "regulator")["state"] == "sent"
    # not sent yet to the regulator: no follow-up clock; another serious AE: none by default
    assert not [r for r in _view({**grave, "ae_rep_reg": ""}, date(2026, 11, 3))["reports"] if r["kind"] == "followup"]
    other = {**grave, "ae_serious_why": "3"}
    assert not [r for r in _view(other, date(2026, 11, 20))["reports"] if r["kind"] == "followup"]
    # the site's override, in TB_SAE_REPORT_DAYS's form
    assert sr.followup_rules("regulator=5/10, sponsor=x, bogus=3") == {"sponsor": (0, 0), "irb": (0, 0),
                                                                        "regulator": (5, 10)}  # fmt: skip
    fu_other = sr.rule_followups({**other, "clock": lc.report_clock(other, date(2026, 11, 20), TW)},
                                 date(2026, 11, 20), sr.followup_rules("regulator=5/10"), {})  # fmt: skip
    assert fu_other[0]["due"] == "2026-11-15" and fu_other[0]["overdue"]
    # a follow-up a receiver asked for: overdue after its own due day
    asked = [{"kind": "followup", "origin": "request", "party": "sponsor", "due": "2026-11-10", "sent_on": None,
              "id": 3}]  # fmt: skip
    assert _rep(_view(grave, date(2026, 11, 11), reports=asked), "followup", "sponsor")["state"] == "overdue"


def test_worklist_order_overdue_first() -> None:
    day = date(2026, 11, 20)
    a = _view(_ae(record="A", ae_onset="2026-11-19", ae_aware="2026-11-19"), day)  # open
    b = _view(_ae(record="B", ae_onset="2026-11-01", ae_aware="2026-11-01"), day)  # overdue
    c = _view(_ae(record="C"), day)  # no start day
    assert [v["record"] for v in sorted([a, c, b], key=sr.sort_key)] == ["B", "C", "A"]


def test_role_table_denies_by_default() -> None:
    assert sae_allowed("coordinator", "record") and sae_allowed("investigator", "view")
    assert not sae_allowed("investigator", "record") and not sae_allowed("admin", "record")
    for role in ("viewer", "cro", "", "steward", "ADMIN"):
        assert not sae_allowed(role, "view") and not sae_allowed(role, "record")
    assert not sae_allowed("coordinator", "delete") and set(ROLE_SAE_ACTIONS) == {
        "admin",
        "coordinator",
        "investigator",
    }


def test_references_carry_no_text() -> None:
    assert sr.check_ref("CIOMS-2026/0042") == "CIOMS-2026/0042"
    for bad in ("Patient Tanaka", "x" * 61, "山田", "a;b"):
        with pytest.raises(sr.SaeError):
            sr.check_ref(bad)


def test_every_key_in_every_language() -> None:
    assert set(EN) == set(JA) == set(ZH)
    for cat in (JA, ZH):
        for k, v in cat.items():
            for name in re.findall(r"\{(\w+)\}", EN[k]):
                assert "{" + name + "}" in v, (k, name)


def test_store_sync_writes_once_and_records_each_change() -> None:
    store = sr.SaeStore()
    day = date(2026, 11, 10)
    e = {**_ae(ae_onset="2026-11-08", ae_aware="2026-11-09", ae_term="Sepsis", pid="ab" * 16), "serious": True}
    e["clock"] = lc.report_clock(e, day, TW)
    first = store.sync("GZQO", e, "console:crc", "2026-11-10T01:00:00+00:00")
    assert [w["action"] for w in first] == ["create"]
    assert store.sync("GZQO", e, "console:pi", "2026-11-10T01:00:05+00:00") == []  # nothing changed: no row
    moved = {**e, "ae_aware": "2026-11-08"}
    moved["clock"] = lc.report_clock(moved, day, TW)
    rows = store.sync("GZQO", moved, "console:crc", "2026-11-10T02:00:00+00:00")
    assert rows[0]["action"] == "change" and rows[0]["body"]["aware"] == {"old": "2026-11-09", "new": "2026-11-08"}
    assert rows[0]["body"]["due_sponsor"] == {"old": "2026-11-10", "new": "2026-11-09"}
    trail = store.trail("GZQO", "S-001", "ae1")
    assert [t["action"] for t in trail] == ["create", "change"] and "Sepsis" not in json.dumps(trail)
    assert store.case("GZQO", "S-001", "ae1")["pid"] == "ab" * 16  # type: ignore[index]
    store.close()


# ------------------------------------------------------------------------------------------- the register end to end
def _audit_lines(d: Any) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted(d.glob("*.jsonl")) for x in f.read_text().splitlines() if x]


@pytest.fixture
def taipei(monkeypatch: pytest.MonkeyPatch) -> None:
    """The site's zone (the console reads it when the pages are registered, so before the box is built)."""
    monkeypatch.setenv("TB_TZ", "Asia/Taipei")


def test_register_worklist_and_trail_on_the_console(taipei: None, lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    lb["clock"]["now"] = datetime(2026, 11, 10, 15, 30, tzinfo=UTC)  # 23:30 on 11-10 in Taipei
    fatal = {"ae_term": "Myocardial infarction", "ae_onset": "2026-11-08", "ae_aware": "2026-11-09",
             "ae_serious": "1", "ae_serious_why": "1", "ae_severity": "3", "ae_outcome": "5", "ae_related": "9"}  # fmt: skip
    _save(c, csrf, no, "tb_adverse_event", fatal, "ae1", "subject")
    page = c.get("/sae").text
    row = f'data-testid="sae-row-GZQO-{no}-ae1"'
    assert row in page and "Myocardial" not in page  # never the AE term on the worklist
    assert 'data-testid="sae-alert"' not in page  # sponsor due 11-10: due today on the site's date, not overdue
    assert 'data-testid="sae-unconfirmed"' in page and f'data-testid="sae-noack-{no}-ae1"' in page
    lb["clock"]["now"] = datetime(2026, 11, 10, 16, 30, tzinfo=UTC)  # 00:30 on 11-11 in Taipei; still 11-10 in UTC
    page = c.get("/sae").text
    assert 'data-testid="sae-alert-overdue"' in page and "Overdue reports: 1" in page
    case = c.get(f"/studies/GZQO/sae/{no}/ae1").text
    assert 'data-testid="sae-rep-initial-sponsor" data-state="overdue"' in case
    # record the sponsor report: the day goes to the AE form, the one field the clock and the home pages read
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": csrf, "party": "sponsor", "on": "2026-11-10",
                                                         "ref": "SP-0042"}, follow_redirects=True)  # fmt: skip
    assert 'data-testid="sae-saved"' in r.text and 'data-state="sent"' in r.text and "SP-0042" in r.text
    values = lb["oc"].get(f"/studies/GZQO/records/{no}").json()["values"]["ae1"]
    assert values["ae_rep_sponsor"]["value"] == "2026-11-10" and values["ae_term"]["value"] == "Myocardial infarction"
    assert 'data-testid="sae-alert"' not in c.get("/sae").text
    # refusals: a reference with text, a day in the future, a receipt before the report was sent
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": csrf, "party": "irb", "on": "2026-11-10",
                                                         "ref": "Mr Tanaka"})  # fmt: skip
    assert r.status_code == 409 and "letters, digits" in r.text
    assert (
        lb["oc"].get(f"/studies/GZQO/records/{no}").json()["values"]["ae1"].get("ae_rep_irb", {}).get("value", "") == ""
    )
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": csrf, "party": "irb", "on": "2026-11-12"})
    assert r.status_code == 409 and 'data-testid="sae-refused"' in r.text
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/receipt", data={"csrf": csrf, "party": "irb", "kind": "initial",
                                                            "on": "2026-11-10"})  # fmt: skip
    assert r.status_code == 409 and "not been sent" in r.text
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/receipt", data={"csrf": csrf, "party": "sponsor", "kind": "initial",
                                                            "on": "2026-11-09"})  # fmt: skip
    assert r.status_code == 409 and "between the day sent and today" in r.text
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/receipt", data={"csrf": csrf, "party": "sponsor", "kind": "initial",
                                                            "on": "2026-11-11", "ref": "ACK-1"}, follow_redirects=True)  # fmt: skip
    assert re.search(r'data-testid="sae-rep-initial-sponsor" data-state="sent">.*?2026-11-10.*?2026-11-11\s*</td>',
                     r.text, re.S)  # fmt: skip
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/receipt", data={"csrf": csrf, "party": "sponsor", "kind": "initial",
                                                            "on": "2026-11-11"})  # fmt: skip
    assert r.status_code == 409 and "Already recorded" in r.text  # a receipt is recorded once
    # a sent day is recorded once here; a correction is made on the AE form, where its history is kept
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": csrf, "party": "sponsor", "on": "2026-11-11"})
    assert r.status_code == 409 and "Already recorded" in r.text
    # the regulator's first report: the rule's follow-up appears, 8 days later
    c.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": csrf, "party": "regulator", "on": "2026-11-11"})
    case = c.get(f"/studies/GZQO/sae/{no}/ae1").text
    assert re.search(r'data-testid="sae-rep-followup-regulator" data-state="open">.*?2026-11-19', case, re.S)
    # a follow-up the sponsor asked for, then sent
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/followup", data={"csrf": csrf, "party": "sponsor", "due": "2026-11-01"})
    assert r.status_code == 409 and "before the event began" in r.text
    c.post(f"/studies/GZQO/sae/{no}/ae1/followup", data={"csrf": csrf, "party": "sponsor", "due": "2026-11-15"})
    case = c.get(f"/studies/GZQO/sae/{no}/ae1").text
    fid = re.search(r'data-testid="sae-rep-followup-sponsor-(\d+)" data-state="open"', case)
    assert fid
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/followup_sent", data={"csrf": csrf, "id": fid.group(1), "on": "2026-11-11"},
               follow_redirects=True)  # fmt: skip
    assert f'data-testid="sae-rep-followup-sponsor-{fid.group(1)}" data-state="sent"' in r.text
    r = c.post(f"/studies/GZQO/sae/{no}/ae1/followup_sent", data={"csrf": csrf, "id": fid.group(1), "on": "2026-11-11"})
    assert r.status_code == 409 and "Already recorded" in r.text
    # a date changed on the AE form moves the deadlines: a change row with old and new
    _save(c, csrf, no, "tb_adverse_event", {**fatal, "ae_aware": "2026-11-08", "ae_rep_sponsor": "2026-11-10",
                                            "ae_rep_reg": "2026-11-11"}, "ae1")  # fmt: skip
    case = c.get(f"/studies/GZQO/sae/{no}/ae1").text
    actions = re.findall(r'data-action="(\w+)"', case)
    assert actions[0] == "create" and {"report", "receipt", "followup_add", "followup_sent", "change"} <= set(actions)
    assert "aware=2026-11-09→2026-11-08" in case and "Myocardial" not in case
    # the trail and the audit: every create and change, dates and parties only, never the AE term
    au = [x for x in _audit_lines(lb["backend"].audit_dir) if x["event"] == "console.sae"]
    assert {x["detail"]["action"] for x in au} >= {"create", "change", "report", "receipt", "followup_add",
                                                   "followup_sent", "report_ref"}  # fmt: skip
    assert all(x["actor"] == "console:crc" and x["ruleset"] == "GZQO" for x in au)
    raw = "".join(f.read_text() for f in lb["backend"].audit_dir.glob("*.jsonl"))
    assert "Myocardial" not in raw and "Mr Tanaka" not in raw
    from console.saerecord import SaeStore

    trail = SaeStore().trail("GZQO", no, "ae1")
    assert "Myocardial" not in json.dumps(trail) and trail[0]["action"] == "create"
    # Japanese and Chinese: the same alert in the reader's language
    _save(c, csrf, no, "tb_adverse_event", {**fatal, "ae_term": "Sepsis", "ae_outcome": "1", "ae_onset": "2026-11-01",
                                            "ae_aware": "2026-11-01"}, "ae2")  # fmt: skip
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/sae"})
    page = c.get("/sae").text
    assert "期限超過の報告：" in page and "SAE 台帳" in page and "Sepsis" not in page
    c.post("/lang", data={"csrf": csrf, "lang": "zh-TW", "back": "/sae"})
    assert "已逾期的通報：" in c.get("/sae").text
    # no longer serious on the AE form: the case stays in the register, marked, and nothing more is recorded
    c.post("/lang", data={"csrf": csrf, "lang": "en", "back": "/sae"})
    _save(c, csrf, no, "tb_adverse_event", {**fatal, "ae_term": "Sepsis", "ae_outcome": "1", "ae_onset": "2026-11-01",
                                            "ae_aware": "2026-11-01", "ae_serious": "0", "ae_serious_why": ""}, "ae2")  # fmt: skip
    page = c.get("/sae").text
    assert f'data-testid="sae-row-GZQO-{no}-ae2"' not in page and f'data-testid="sae-lost-GZQO-{no}-ae2"' in page
    case = c.get(f"/studies/GZQO/sae/{no}/ae2").text
    assert 'data-testid="sae-not-serious"' in case and "serious=1→0" in case
    r = c.post(f"/studies/GZQO/sae/{no}/ae2/followup", data={"csrf": csrf, "party": "sponsor", "due": "2026-11-20"})
    assert r.status_code == 409 and "not serious on the AE form now" in r.text


def test_sae_register_roles_deny_by_default(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    _save(c, csrf, no, "tb_adverse_event", {"ae_term": "Stroke", "ae_onset": "2026-11-07", "ae_aware": "2026-11-07",
                                            "ae_serious": "1", "ae_serious_why": "2", "ae_severity": "3",
                                            "ae_outcome": "2", "ae_related": "9"}, "ae1")  # fmt: skip
    assert c.get("/sae").status_code == 200
    # the investigator reads, never records
    p, pcsrf = login(lb["app"], "pi", PW)
    assert f'data-testid="sae-row-GZQO-{no}-ae1"' in p.get("/sae").text
    case = p.get(f"/studies/GZQO/sae/{no}/ae1").text
    assert 'data-testid="sae-sent-sponsor"' not in case
    r = p.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": pcsrf, "party": "sponsor", "on": "2026-11-08"})
    assert r.status_code == 403
    # the administrator reads; the viewer and the CRO see nothing
    a, acsrf = login(lb["app"], "admin")
    assert a.get("/sae").status_code == 200
    assert a.post(f"/studies/GZQO/sae/{no}/ae1/followup", data={"csrf": acsrf, "party": "sponsor",
                                                                "due": "2026-11-20"}).status_code == 403  # fmt: skip
    from tests.console.test_console_app import VIEWER_PW

    v, _ = login(lb["app"], "viewer", VIEWER_PW)
    assert v.get("/sae").status_code == 403 and v.get(f"/studies/GZQO/sae/{no}/ae1").status_code == 403
    lb["users"].create("cra1", "cro", PW)
    cro, _ = login(lb["app"], "cra1", PW)
    assert cro.get("/sae").status_code == 403 and cro.get(f"/studies/GZQO/sae/{no}/ae1").status_code in (403, 404)
    assert "sae-row" not in cro.get("/sae").text
    # another study's coordinator: 404, not 403, and the study is not on the worklist
    lb["users"].create("crc2", "coordinator", PW)
    lb["users"].set_scope("crc2", studies="OTHER")
    o, ocsrf = login(lb["app"], "crc2", PW)
    assert o.get(f"/studies/GZQO/sae/{no}/ae1").status_code == 404
    assert o.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": ocsrf, "party": "sponsor",
                                                            "on": "2026-11-08"}).status_code == 404  # fmt: skip
    assert "sae-row-GZQO" not in o.get("/sae").text
    denied = [x for x in _audit_lines(lb["backend"].audit_dir) if x["event"] == "console.denied"]
    assert any("/sae" in str(x["detail"].get("action")) for x in denied)
    # bad keys and a forged action: 404
    assert c.get(f"/studies/GZQO/sae/{no}/visit1").status_code == 404
    assert c.post(f"/studies/GZQO/sae/{no}/ae1/delete", data={"csrf": csrf}).status_code == 404
    assert c.post(f"/studies/GZQO/sae/{no}/ae1/sent", data={"csrf": "x", "party": "sponsor"}).status_code == 400
