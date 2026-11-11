"""T-516 (D-385): workflow fixes on the PoC path.

* UX-011: the screening log agrees with the participant page after a consent form is saved, also when the consent
  form was saved before the participant was first opened (the screening number was not yet known to the data core).
* UX-013: a referral asked after Approach pauses the Approach: a confirm sheet says so, the coordinator's call task
  and contact outcomes wait for the doctor's agreement, the patient page and the screening log say "paused"; the
  other order (referral first) still refuses Approach.
* UX-015: the sub-investigator without the "approach" tick sees why the button is absent and who marks Approach.
* UX-014: the demo seeds the trial's IRB approval date and consent-form version (two values), never over a record.
* LIFE-019 (PoC part): consent is never implied by a TrialBox form; an enrolment without a consent record is held
  and the participant page raises "consent record missing".

The pages are walked in ja, zh-TW and en; the phone layout (390 px) is checked on the markup the pages share: the
viewport meta, the hint and warning lines that wrap, and no fixed width on the new lines."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pytest
from datacore.builtin import builtin_questionnaires
from datacore.lifecycle import Lifecycle
from datacore.store import DataCore
from tb_contracts import RegistryUpdate

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import NOW, _save, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW as LPW
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_team_pages import A, B, _events, _log_pi_and_sub

LANGS = ("ja", "zh-TW", "en")
AT = "2026-11-08T09:00:00+09:00"


def _lang(c: Any, lang: str) -> None:
    c.post("/lang", data={"csrf": _csrf(c.get("/home").text), "lang": lang, "back": "/home"})


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _phone_ok(html: str, *testids: str) -> None:
    """The 390 px contract of a console page: the viewport meta, and each new line a wrapping hint or warning (a
    paragraph of the shared ``hint``/``warn`` classes) with no inline width."""
    assert 'name="viewport"' in html and "width=device-width" in html
    for tid in testids:
        m = re.search(rf'<p class="(hint|warn)"[^>]*data-testid="{tid}"[^>]*>', html)
        assert m, tid
        assert "style=" not in m.group(0) and "nowrap" not in m.group(0), tid


# ---------------------------------------------------------------------------------------------- UX-011
def test_consent_saved_first_the_screening_log_agrees_with_the_participant(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    pid = f"{1:032x}"
    lb["backend"].registry_rows = lb["reg"].rows  # the log reads the real registry
    lb["reg"].update("GZQO", RegistryUpdate(pid=pid, status="contacted", by="crc", source="manual"), NOW)
    c, csrf = login(lb["app"], "crc", LPW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    # the consent form is the first thing saved for this screening number: no participant page was opened before
    r = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"})
    assert r.status_code == 200
    assert {e.pid: e.status for e in lb["reg"].rows("GZQO")}[pid] == "consented"
    for lang in LANGS:
        _lang(c, lang)
        log = c.get("/studies/GZQO/screening-log").text
        status = re.search(rf'data-testid="status-{no}">([^<]*)<', log)
        sub = c.get(f"/studies/GZQO/subjects/{no}").text
        assert status and 'data-state="consented"' in sub, lang
        from console.i18n import translate

        assert status.group(1).startswith(translate(lang, "registry.status.consented")), (lang, status.group(1))


def test_a_log_behind_the_participant_is_brought_up_but_never_pulled_back(lb: dict[str, Any]) -> None:  # noqa: F811
    from orchestrator.lifecycle_api import behind

    assert behind("contacted", "consented") and behind(None, "approached") and behind("candidate", "enrolled")
    assert not behind("consented", "consented") and not behind("enrolled", "consented")
    assert not behind("withdrawn", "consented") and not behind("declined", "approached")
    assert not behind(None, "candidate") and not behind("contacted", "withdrawn")


# ---------------------------------------------------------------------------------------------- LIFE-019
@pytest.fixture
def life() -> Any:
    dc = DataCore()
    for q in builtin_questionnaires("GZQO"):
        dc.put_form("GZQO", q, "builtin", AT)
    yield Lifecycle(dc)
    dc.close()


def _put(life: Lifecycle, rec: str, values: dict[str, str], event: str = "") -> None:
    for f, v in values.items():
        life.dc.write("GZQO", rec, event, f, v, "crc", AT, "trialbox")


def test_an_enrolment_without_a_consent_record_is_held(life: Lifecycle) -> None:
    life.ensure("GZQO", "GZQO-0001", "", "crc", AT)
    _put(life, "GZQO-0001", {"en_date": "2026-10-03", "en_eligible": "1"})
    out = life.derive("GZQO", "GZQO-0001", by="crc", at=AT)
    assert [s["to"] for s in out["steps"]] == ["approached"]  # approach may be implied; consent never
    assert out["held"] == [{"state": "consented", "why": "consent_missing", "current": "approached",
                            "source": "form:tb_enrolment"}]  # fmt: skip
    assert (life.subject("GZQO", "GZQO-0001") or {})["state"] == "approached"
    assert life.consent_missing("GZQO", "GZQO-0001", "approached") == "form:tb_enrolment"
    # a visit without consent: held too
    life.ensure("GZQO", "GZQO-0002", "", "crc", AT)
    _put(life, "GZQO-0002", {"vs_status": "1", "vs_date": "2026-10-10"}, "v1")
    assert life.derive("GZQO", "GZQO-0002", by="crc", at=AT)["held"][0]["why"] == "consent_missing"
    # the consent form saved: the participant follows to enrolled, and the alert is gone
    _put(life, "GZQO-0001", {"ic_date": "2026-10-01"})
    out = life.derive("GZQO", "GZQO-0001", by="crc", at=AT)
    assert [s["to"] for s in out["steps"]] == ["consented", "enrolled"] and out["held"] == []
    assert life.consent_missing("GZQO", "GZQO-0001", "enrolled") == ""
    # a sponsor study (the screening log, fed by the sponsor's CRF, says enrolled): still walked, labelled
    life.ensure("GZQO", "GZQO-0003", "cd" * 16, "crc", AT)
    out = life.derive("GZQO", "GZQO-0003", by="crc", at=AT, registry="enrolled")
    assert [s["to"] for s in out["steps"]] == ["approached", "consented", "enrolled"]
    assert life.steps("GZQO", "GZQO-0003")[2]["note"] == "implied by screening_log"


def test_the_participant_page_raises_consent_record_missing(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", LPW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    r = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-04", "en_eligible": "1"}, back="subject")
    assert 'data-state="approached"' in r.text and 'data-testid="consent-missing"' in r.text
    for lang in LANGS:
        _lang(c, lang)
        page = c.get(f"/studies/GZQO/subjects/{no}").text
        assert 'data-testid="consent-missing-do"' in page and "life.alert" not in _text(page), lang
        _phone_ok(page)
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-state="enrolled"' in page and 'data-testid="consent-missing"' not in page


# ---------------------------------------------------------------------------------------------- UX-013
def test_a_referral_after_approach_pauses_the_approach(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(981))
    pi = _user(box, "drsato", "investigator")
    crc = _user(box, "crc1", "coordinator")
    page = pi.get(f"/studies/GZQO/patients/{A}").text
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(page), "mark": "approach"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert 'data-testid="task-call"' in crc.get("/home").text
    cand = pi.get(f"/studies/GZQO/candidates/{A}?purpose=referral").text
    assert 'data-testid="referral-pauses"' in cand
    # the consequence first, then the referral
    r = pi.post(f"/studies/GZQO/candidates/{A}/referral", data={"csrf": _csrf(cand), "route": "outside"})
    assert r.status_code == 200 and 'data-testid="confirm-text"' in r.text and "paused" in r.text
    assert box["app"].state.helpers.team.referrals("GZQO", A) == []
    r = pi.post(f"/studies/GZQO/candidates/{A}/referral", data={"csrf": _csrf(cand), "route": "outside",
                                                              "confirm": "yes"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    ev = [e for e in _events(box, "console.referral") if e["detail"].get("action") == "requested"]
    assert ev[-1]["detail"]["paused"] == "approach"
    # Approach is paused: no call task, contact outcomes refused (page and API), the pages say so
    home = crc.get("/home").text
    assert 'data-testid="task-call"' not in home and 'data-testid="task-refer"' in home
    cp = crc.get(f"/studies/GZQO/patients/{A}").text
    assert 'data-testid="outcome-paused"' in cp and 'data-testid="outcomes"' not in cp
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": _csrf(cp), "outcome": "reached_booked"})
    assert r.status_code == 409 and "Approach is paused" in r.text
    pp = pi.get(f"/studies/GZQO/patients/{A}").text
    assert 'data-testid="approach-paused"' in pp and f'data-testid="approach-{A[:8]}"' not in pp
    no = box["app"].state.helpers.store.screening_no("GZQO", A)
    assert f'data-testid="paused-{no}"' in crc.get("/studies/GZQO/screening-log").text
    # the doctor agrees: Approach resumes, the call task is back and the outcome is taken
    ref = box["app"].state.helpers.team.referrals("GZQO", A)[-1]
    refs = crc.get("/studies/GZQO/referrals").text
    r = crc.post(f"/studies/GZQO/referrals/{ref.id}/answer", data={"csrf": _csrf(refs), "answer": "agree",
                                                                  "channel": "phone"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert 'data-testid="task-call"' in crc.get("/home").text
    cp = crc.get(f"/studies/GZQO/patients/{A}").text
    assert 'data-testid="outcomes"' in cp
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": _csrf(cp), "outcome": "reached_booked"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert f'data-testid="paused-{no}"' not in crc.get("/studies/GZQO/screening-log").text


def test_a_referral_first_still_refuses_approach(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(982))
    pi = _user(box, "drsato", "investigator")
    cand = pi.get(f"/studies/GZQO/candidates/{B}?purpose=referral").text
    assert 'data-testid="referral-pauses"' not in cand  # nothing to pause: no confirm sheet
    r = pi.post(f"/studies/GZQO/candidates/{B}/referral", data={"csrf": _csrf(cand), "route": "outside"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    page = pi.get(f"/studies/GZQO/patients/{B}").text
    assert 'data-testid="ref-wait"' in page and 'data-testid="approach-paused"' not in page
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    assert r.status_code == 409


def test_paused_approach_in_three_languages(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(983))
    pi = _user(box, "drsato", "investigator")
    crc = _user(box, "crc1", "coordinator")
    page = pi.get(f"/studies/GZQO/patients/{A}").text
    pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    cand = pi.get(f"/studies/GZQO/candidates/{A}?purpose=referral").text
    pi.post(f"/studies/GZQO/candidates/{A}/referral", data={"csrf": _csrf(cand), "route": "outside", "confirm": "yes"})
    for lang in LANGS:
        _lang(pi, lang)
        _lang(crc, lang)
        pp = pi.get(f"/studies/GZQO/patients/{A}").text
        cp = crc.get(f"/studies/GZQO/patients/{A}").text
        log = crc.get("/studies/GZQO/screening-log").text
        for html in (pp, cp, log):
            assert "team.approach" not in _text(html) and "log.paused" not in _text(html), lang
        _phone_ok(pp, "approach-paused")
        assert 'data-testid="outcome-paused"' in cp
        _phone_ok(log)


# ---------------------------------------------------------------------------------------------- UX-015
def test_the_sub_investigator_sees_why_approach_is_absent(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(984))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("screen", "refer"))
    for lang in LANGS:
        _lang(sub, lang)
        for path in (f"/studies/GZQO/patients/{A}", f"/studies/GZQO/week?list=all&pid={A}",
                     f"/studies/GZQO/candidates/{A}?purpose=eligibility"):  # fmt: skip
            html = sub.get(path).text
            assert f'data-testid="approach-{A[:8]}"' not in html, (lang, path)
            m = re.search(r'data-testid="approach-absent">([^<]*)<', html)
            assert m and "drsato" in m.group(1), (lang, path)  # who marks Approach: the logged PI
            assert "team.approach" not in _text(html), (lang, path)
            _phone_ok(html, "approach-absent")
    # the PI has the button and no such line
    html = pi.get(f"/studies/GZQO/patients/{A}").text
    assert f'data-testid="approach-{A[:8]}"' in html and 'data-testid="approach-absent"' not in html


# ---------------------------------------------------------------------------------------------- UX-014
def test_the_demo_seeds_irb_date_and_consent_version_once() -> None:
    from console.teamstore import Irb, TeamStore

    from tools import demo

    t = TeamStore()
    assert demo.seed_irb(t, "GZQO", date(2026, 11, 11), "2026-11-11T00:00:00+00:00")
    rec = t.irb("GZQO")
    assert (rec.approved_on, rec.icf_version) == ("2026-09-12", "1.0") and rec.warnings(date(2026, 11, 11)) == []
    assert t.irb("GOUT-COH").warnings(date(2026, 11, 11)) == ["irb_missing", "icf_missing"]  # kept on purpose
    t.save_irb("GZQO", Irb(approved_on="2026-10-01", icf_version="2.0"), "crc1", "2026-11-11T01:00:00+00:00")
    assert not demo.seed_irb(t, "GZQO", date(2026, 11, 11), "2026-11-11T02:00:00+00:00")  # a saved record stays
    assert t.irb("GZQO").icf_version == "2.0"


def test_every_new_key_in_every_language() -> None:
    from console import i18n_life, i18n_team

    assert set(i18n_team.EN) == set(i18n_team.JA) == set(i18n_team.ZH)
    assert set(i18n_life.EN) == set(i18n_life.JA) == set(i18n_life.ZH)
    for k in ("team.approach.not_delegated.pi", "team.approach.paused"):
        for cat in (i18n_team.JA, i18n_team.ZH):
            for name in re.findall(r"\{(\w+)\}", i18n_team.EN[k]):
                assert "{" + name + "}" in cat[k], (k, name)
