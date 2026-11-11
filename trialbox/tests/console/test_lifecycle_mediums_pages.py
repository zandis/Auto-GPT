"""D-407 (T-620): the trial lifecycle Mediums in the console.

* LIFE-017: the coordinator's contact outcomes count against the study's limit; a fourth attempt on a limit of three
  is refused with a plain reason, the patient page says "the investigator decides" (to the coordinator and to the
  investigator), and the closing outcomes stay open. The limit and the days between attempts are set per study on the
  set-up page.
* LIFE-020: the screening log shows "Randomised" with the day; the XLSX has the randomisation date.
* LIFE-025: the possible-deviations page; confirm writes a deviation entry, dismiss needs a reason.
* UX-034: the referral page has a "Copy request for the doctor" text and a one-page print in the doctor's language;
  the chart number is printed only after a recorded reveal.

All data is synthetic."""

from __future__ import annotations

import io
import re
from datetime import timedelta
from typing import Any

from console.i18n import CATALOGUES
from console.i18n_lifecycle_mediums import EN, JA, ZH
from openpyxl import load_workbook
from tb_common.wording import check_page

from tests.console.test_amendment_rescreen import _screen
from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import (
    NOW,
    lb,  # noqa: F401 - the fixture is used by name
)
from tests.console.test_lifecycle_pages import PW as LIFE_PW
from tests.console.test_role_pages import _user
from tests.console.test_team_pages import _events

A, B = "a" * 32, "b" * 32


def _row(pid: str) -> dict[str, Any]:
    return {"pid": pid, "tier": "high", "next_appointment": None, "practitioner_id": "DR-SYN", "department": "RHEU",
            "criteria": [{"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": []}}],
            "actions": [], "n_unknown": 0}  # fmt: skip


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def test_every_key_in_every_language() -> None:
    assert set(EN) == set(JA) == set(ZH)
    for lang, cat in CATALOGUES.items():
        assert all(k in cat for k in EN), lang
        assert not check_page(" ".join(cat[k] for k in EN)), lang  # T-116: no verdict word


# ---------------------------------------------------------------------------------------------- LIFE-017
def _approach(b: dict[str, Any], pids: list[str]) -> Any:
    _screen(b, 9901, "3.0.0", [_row(p) for p in pids], 0)
    name_pi(b, "pi")  # D-380: the steward names the PI before the PI acts
    pi, _ = login(b["app"], "pi", LIFE_PW)
    week = pi.get("/studies/GZQO/week").text
    for p in pids:
        r = pi.post(f"/studies/GZQO/patients/{p}/mark", data={"csrf": _csrf(week), "mark": "approach"},
                    follow_redirects=False)  # fmt: skip
        assert r.status_code == 303, r.text[:300]
    return pi


def test_a_fourth_attempt_on_a_limit_of_three_is_refused(lb: dict[str, Any]) -> None:  # noqa: F811
    pi = _approach(lb, [A])
    crc, csrf = login(lb["app"], "crc", LIFE_PW)
    for i in range(3):
        lb["clock"]["now"] = NOW + timedelta(days=i)
        r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "not_reached"},
                     follow_redirects=False)  # fmt: skip
        assert r.status_code == 303, r.text[:300]
    page = crc.get(f"/studies/GZQO/patients/{A}").text
    assert "Contact attempts: 3 of 3" in page and 'data-testid="contact-limit"' in page
    assert 'data-testid="outcome-not_reached"' not in page and 'data-testid="outcome-lost_contact"' in page
    lb["clock"]["now"] = NOW + timedelta(days=3)
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "not_reached"})
    assert r.status_code == 409 and "limit is 3" in r.text
    assert len(lb["app"].state.helpers.store.outcomes("GZQO", A)) == 3  # nothing recorded
    refused = [e["detail"] for e in _events(lb, "console.refused") if e["detail"].get("reason") == "contact limit"]
    assert refused and refused[0]["attempts"] == 3
    # the investigator is asked on the patient's page
    assert 'data-testid="contact-limit-pi"' in pi.get(f"/studies/GZQO/patients/{A}").text
    # closing the contact is never refused (the page asks to confirm a lost contact first, as before)
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "lost_contact"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code in (200, 303) and "limit is" not in r.text, r.text[:300]


def test_the_study_sets_the_limit_and_the_days_between_attempts(lb: dict[str, Any]) -> None:  # noqa: F811
    _approach(lb, [A])
    crc, csrf = login(lb["app"], "crc", LIFE_PW)
    setup = crc.get("/studies/GZQO/setup").text
    assert 'data-testid="setup-contact"' in setup and "At most 3 attempts" in setup
    r = crc.post("/studies/GZQO/setup/contact", data={"csrf": csrf, "max_attempts": "2", "min_days": "2"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[:300]
    assert "At most 2 attempts, at least 2 day(s) apart." in crc.get("/studies/GZQO/setup").text
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "not_reached"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "reached_booked"})
    assert r.status_code == 409 and "can be recorded from 2026-11-10" in r.text
    lb["clock"]["now"] = NOW + timedelta(days=2)
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "not_reached"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    lb["clock"]["now"] = NOW + timedelta(days=5)
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "reached_booked"})
    assert r.status_code == 409 and "limit is 2" in r.text
    # the investigator does not set the coordinator's rule
    pi, pcsrf = login(lb["app"], "pi", LIFE_PW)
    r = pi.post("/studies/GZQO/setup/contact", data={"csrf": pcsrf, "max_attempts": "9", "min_days": "0"})
    assert r.status_code in (403, 404)


# ---------------------------------------------------------------------------------------------- LIFE-020, LIFE-025
def _entry(c: Any, csrf: str, record: str, form: str, values: dict[str, str], event: str = "") -> None:
    data: dict[str, Any] = {"csrf": csrf, "record": record, "event": event, "form": form, "back": ""}
    data.update({f"f_{k}": v for k, v in values.items()})
    r = c.post("/studies/GZQO/entry", data=data, follow_redirects=False)
    assert r.status_code in (200, 303), r.text[-400:]


def test_randomised_on_the_log_and_possible_deviations(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    _screen(lb, 9902, "3.0.0", [_row(f"{1:032x}"), _row(f"{2:032x}")], 0)
    crc, csrf = login(lb["app"], "crc", LIFE_PW)
    crc.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})  # the built-in forms, with the D-407 fields
    crc.get("/studies/GZQO/subjects")
    _entry(crc, csrf, no, "tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"})
    _entry(crc, csrf, no, "tb_enrolment", {"en_date": "2026-11-02", "en_eligible": "1", "en_rand": "1",
                                           "en_rand_date": "2026-11-04", "en_rand_no": "R-0107"})  # fmt: skip
    log = crc.get("/studies/GZQO/screening-log").text
    assert f'data-testid="randomised-{no}"' in log and "Randomised 2026-11-04" in log
    ws: Any = load_workbook(io.BytesIO(crc.get("/studies/GZQO/screening-log.xlsx").content))["screening log"]
    rows = [list(x) for x in ws.iter_rows(values_only=True)]
    assert rows[0][-1] == "randomisation_date" and any(r[-1] == "2026-11-04" for r in rows[1:])
    # enrolled on the 2nd, consent on the 3rd: a possible deviation, never a deviation by itself
    page = crc.get("/studies/GZQO/deviations").text
    assert f'data-testid="dev-{no}-consent_after"' in page and "before consent on 2026-11-03" in page
    assert not check_page(page)
    r = crc.post("/studies/GZQO/deviations", data={"csrf": csrf, "record": no, "key": "consent_after:enrolment",
                                                   "decision": "dismiss"})  # fmt: skip
    assert r.status_code == 409 and "say why this is not a deviation" in r.text
    r = crc.post("/studies/GZQO/deviations", data={"csrf": csrf, "record": no, "key": "consent_after:enrolment",
                                                   "decision": "confirm"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    page = crc.get("/studies/GZQO/deviations?done=confirm").text
    assert f'data-testid="dev-entry-{no}-consent_after"' in page and "dv1" in page
    subject = crc.get(f"/studies/GZQO/subjects/{no}").text
    assert "dv1" in subject
    assert lb["dc"].record("GZQO", no, "dv1")["dv_kind"] == "2"
    # the investigator reads the list and does not answer it
    name_pi(lb, "pi")  # D-380
    pi, pcsrf = login(lb["app"], "pi", LIFE_PW)
    assert 'data-testid="dev-list"' in pi.get("/studies/GZQO/deviations").text
    r = pi.post("/studies/GZQO/deviations", data={"csrf": pcsrf, "record": no, "key": "consent_after:enrolment",
                                                  "decision": "dismiss", "reason": "x"})  # fmt: skip
    assert r.status_code == 403


# ---------------------------------------------------------------------------------------------- UX-034
def test_the_request_for_the_doctor_copy_text_and_one_page_print(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(968))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    crc = _user(box, "crc1", "coordinator")
    sp = crc.get("/site/staff").text
    crc.post("/site/staff", data={"csrf": _csrf(sp), "kind": "person", "name": "Coordinator Ito", "department": "CRC",
                                  "username": "crc1", "contact": "ext 2207"})  # fmt: skip
    p = pi.get(f"/studies/GZQO/candidates/{A}?purpose=referral").text
    r = pi.post(f"/studies/GZQO/candidates/{A}/referral", data={"csrf": _csrf(p)}, follow_redirects=False)
    assert r.status_code == 303
    ref = box["app"].state.helpers.team.referrals("GZQO", A)[-1]
    lp = crc.get("/studies/GZQO/referrals").text
    assert f'data-testid="ref-doc-copy-{ref.id}"' in lp and f'data-copy="ask-{ref.id}"' in lp
    text = lp.split(f'data-testid="ref-doc-text-{ref.id}">')[1].split("</textarea>")[0]
    assert "Study GZQO: request for your agreement" in text and "may the study team tell your patient" in text
    assert "Chart number: ____" in text and "aaaaaaaa" in text
    # one page in the doctor's language; no chart number before a recorded reveal
    ja = crc.get(f"/studies/GZQO/referrals/{ref.id}/print?lang=ja").text
    assert 'lang="ja"' in ja and "研究 GZQO：ご了承のお願い" in ja and "カルテ番号：____" in ja
    assert not check_page(ja)
    zh = crc.get(f"/studies/GZQO/referrals/{ref.id}/print?lang=zh-TW").text
    assert "徵詢您的同意" in zh
    # the chart number only through the one reveal path, with its reason and audit record
    r = crc.post(f"/studies/GZQO/referrals/{ref.id}/print", data={"csrf": _csrf(ja), "reason": "contact",
                                                                    "lang": "ja"})  # fmt: skip
    assert r.status_code == 200, r.text[:300]
    assert 'data-testid="ref-letter-chart"' in r.text and "カルテ番号：____" not in r.text
    views = box["app"].state.helpers.team.views("GZQO", A)
    assert ("reveal", "referral") in [(v[0], v[1]) for v in views]
    acts = [e["detail"]["action"] for e in _events(box, "console.referral")]
    assert acts.count("printed") == 3
    assert [
        e["detail"]["chart_no"] for e in _events(box, "console.referral") if e["detail"]["action"] == "printed"
    ] == [False, False, True]
    # someone without the study's screening task gets no print
    viewer = _user(box, "view1", "viewer")
    assert viewer.get(f"/studies/GZQO/referrals/{ref.id}/print").status_code in (403, 404)
