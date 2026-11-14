"""Review 2026-11-09 P-02 and P-03 (D-143): a serious AE stays on the investigator's banner and in N1 until the
investigator acknowledges it, whatever its outcome (a fatal SAE used to leave both the moment it was saved); the
acknowledgement is one tap, audited with the time; the AE form carries the reporting clock (sponsor, IRB,
regulator), and a report past its due day shows on the investigator's and the coordinator's home pages and in N2."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from console import notify
from datacore import lifecycle as lc

from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name


def test_report_rules_jp_tw_and_the_site_override() -> None:
    # D-766: the country's strictest set when named; nothing named gives no clock (no deadline until chosen)
    assert lc.report_rules("Asia/Tokyo", rules="jp") == {"sponsor": (1, 1), "irb": (1, 1), "regulator": (7, 15),
                                                         lc.EXPECTED_REGULATOR: (15, 0)}  # fmt: skip
    assert lc.report_rules("Asia/Taipei", rules="tw") == {"sponsor": (1, 1), "irb": (7, 15), "regulator": (7, 15)}
    assert lc.report_rules("Asia/Taipei") == {} and lc.report_rules("Asia/Tokyo") == {}
    got = lc.report_rules("Asia/Taipei", "irb=3/10, regulator=0, nonsense=4, sponsor=x", "tw")
    assert got == {"sponsor": (1, 1), "irb": (3, 10), "regulator": (0, 0)}
    e = {"ae_serious": "1", "ae_outcome": "5", "ae_onset": "2026-11-01", "ae_aware": "2026-11-03",
         "ae_rep_sponsor": "2026-11-03"}  # fmt: skip
    clock = {c["party"]: c for c in lc.report_clock(e, date(2026, 11, 11), lc.report_rules("Asia/Taipei", rules="tw"))}
    assert clock["sponsor"] == {"party": "sponsor", "days": 1, "hours": 24, "due_at": "2026-11-04T00:00",
                                "due": "2026-11-04", "done": "2026-11-03", "overdue": False, "bad_done": False}  # fmt: skip
    assert clock["irb"]["due"] == "2026-11-10" and clock["irb"]["overdue"]  # fatal: 7 days from the day learned
    other = {**e, "ae_outcome": "2", "ae_serious_why": "3", "ae_rep_sponsor": ""}
    clock = {
        c["party"]: c for c in lc.report_clock(other, date(2026, 11, 11), lc.report_rules("Asia/Taipei", rules="tw"))
    }
    assert clock["irb"]["due"] == "2026-11-18" and not clock["irb"]["overdue"] and clock["sponsor"]["overdue"]
    assert lc.report_clock({**e, "ae_serious": "0"}, date(2026, 11, 11), lc.report_rules()) == []


def test_a_fatal_sae_stays_until_the_pi_acknowledges_and_reports_have_a_clock(lb: dict[str, Any]) -> None:  # noqa: F811
    name_pi(lb, "pi")  # D-380 (ROLE-008): the steward names the study's PI
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"})  # D-766: the clock runs once chosen
    lb["clock"]["now"] = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)  # a Wednesday, Asia/Taipei
    fatal = {"ae_term": "Myocardial infarction", "ae_onset": "2026-11-08", "ae_aware": "2026-11-09",
             "ae_serious": "1", "ae_serious_why": "1", "ae_severity": "3", "ae_outcome": "5", "ae_related": "9"}  # fmt: skip
    r = _save(c, csrf, no, "tb_adverse_event", fatal, "ae1", "subject")
    assert 'data-testid="ae-ae1"' in r.text and 'data-testid="clock-ae1"' in r.text
    assert 'data-testid="clock-ae1-sponsor"' in r.text and "2026-11-10" in r.text  # one day from the day learned
    form = c.get(f"/studies/GZQO/entry?record={no}&form=tb_adverse_event&event=ae1").text
    assert 'data-testid="clock-ae1-irb"' in form and 'data-testid="f-ae_rep_irb"' in form  # the clock on the form
    # fatal and saved: still on the coordinator's home page, with the overdue sponsor report
    home = c.get("/home").text
    assert 'data-testid="sae-banner"' in home and 'data-testid="sae-fatal"' in home
    assert f'data-testid="sae-report-{no}-ae1-sponsor"' in home and "Waiting for the investigator" in home
    assert f'data-testid="sae-ack-{no}-ae1"' not in home  # only the investigator acknowledges
    r = c.post(f"/studies/GZQO/subjects/{no}/aes/ae1/ack", data={"csrf": csrf})
    assert r.status_code == 403
    # N1 on a day with no clinic: the unacknowledged SAE is mailed anyway; N2 lists the overdue report
    h = lb["app"].state.helpers
    out = {n.username: n for n in notify.collect(h, date(2026, 11, 11))}
    assert "Serious adverse events to review: 1" in out["pi"].body and out["pi"].counts["sae"] == 1
    assert "a serious adverse event waits for your acknowledgement" in out["pi"].body
    n2 = out["crc"]
    assert "Overdue serious adverse event reports: 1" in n2.body and "Sponsor report, due 2026-11-10" in n2.body
    assert n2.counts["sae_reports"] == 1 and "Myocardial" not in n2.body  # pseudonym, party and day only
    # the investigator: one tap, audited with the time; the banner and N1 count clear
    p, pcsrf = login(lb["app"], "pi", PW)
    week = p.get("/week").text
    assert 'data-testid="sae-banner"' in week and f'data-testid="sae-ack-{no}-ae1"' in week
    assert f'data-testid="sae-report-{no}-ae1-sponsor"' in week
    r = p.post(f"/studies/GZQO/subjects/{no}/aes/ae1/ack", data={"csrf": pcsrf})
    assert 'data-testid="sae-acked"' in r.text and 'data-testid="ae-acked-ae1"' in r.text and "pi" in r.text
    assert 'data-testid="sae-banner"' not in p.get("/week").text
    assert 'data-testid="sae-banner"' not in c.get("/home").text
    assert f'data-testid="sae-report-{no}-ae1-sponsor"' in c.get("/home").text  # the report is still overdue
    orch = [r for r in _audit(lb["audit"]) if r["event"] == "life.sae_ack"]
    assert len(orch) == 1 and orch[0]["actor"] == "console:pi" and orch[0]["detail"]["outcome"] == "5"
    assert orch[0]["detail"]["at"].startswith("2026-11-11")
    assert any(e.event == "console.sae_ack" for e in lb["backend"].audit(None, 500))
    r = p.post(f"/studies/GZQO/subjects/{no}/aes/ae1/ack", data={"csrf": pcsrf})
    assert (
        len([r for r in _audit(lb["audit"]) if r["event"] == "life.sae_ack"]) == 2
    )  # a second tap is recorded, the first stands
    assert lb["oc"].get(f"/studies/GZQO/subjects/{no}").json()["aes"][0]["ack_by"] == "console:pi"
    out = {n.username: n for n in notify.collect(h, date(2026, 11, 12))}
    assert "pi" not in out  # nothing left to acknowledge, no clinic: no N1
    # the report recorded on the form: the clock is done and leaves the home page
    _save(c, csrf, no, "tb_adverse_event", {**fatal, "ae_rep_sponsor": "2026-11-10", "ae_rep_irb": "2026-11-11",
                                            "ae_rep_reg": "2026-11-11"}, "ae1")  # fmt: skip
    assert 'data-testid="sae-reports"' not in c.get("/home").text
    # the API: the investigator acknowledges, the coordinator may not
    _save(c, csrf, no, "tb_adverse_event", {**fatal, "ae_outcome": "1", "ae_term": "Sepsis"}, "ae2")
    from fastapi.testclient import TestClient

    api = TestClient(lb["app"])
    tok = api.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    assert (
        api.post(f"/api/v1/studies/GZQO/aes/{no}/ae2/ack", headers={"Authorization": f"Bearer {tok}"}).status_code
        == 403
    )
    tok = api.post("/api/v1/session", json={"username": "pi", "password": PW}).json()["token"]
    r = api.post(f"/api/v1/studies/GZQO/aes/{no}/ae2/ack", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and r.json()["ack_by"] == "console:pi"


def _audit(log: Any) -> list[dict[str, Any]]:
    import json

    return [json.loads(x) for f in sorted(log.directory.glob("*.jsonl")) for x in f.read_text().splitlines() if x]
