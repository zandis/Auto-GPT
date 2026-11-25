"""TB-PLAN-04 step 5 (D-134, D-125, D-127): the console's lifecycle pages and their ``/api/v1`` routes, on the
orchestrator's real data-core and lifecycle API (a real data core and candidate registry in the test's schema).

The path: screening numbers become participants → an illegal step is refused with a plain reason (page and API) →
told about the study → consent and enrolment through the forms move the participant → the visit schedule is saved →
the visit list shows the visit in its window → "Done today" fills the visit form, Save → a serious AE is shown on the
coordinator's and the investigator's home pages → withdrawal → the enrolment report, its CSV and XLSX → N2 mail lists
the visit by pseudonym only."""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from console import notify
from console.backend import problem_of
from console.i18n_life import EN as L_EN
from console.i18n_life import JA as L_JA
from console.i18n_life import ZH as L_ZH
from datacore.store import DataCore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from orchestrator.candidates import CandidateRegistry
from orchestrator.datacore_api import DataService
from orchestrator.datacore_api import router as datacore_router
from orchestrator.db import JobDB
from orchestrator.lifecycle_api import router as life_router
from tb_common.audit import AuditLog

from tests.actor3 import SignedClient
from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, box, login, name_pi  # noqa: F401 - the fixture is used by name

PW = "life-cycle-password-0001"
NOW = datetime(2026, 11, 8, 1, 0, tzinfo=UTC)
CHART_NO = "MRN-000123"


@pytest.fixture
def lb(box: dict[str, Any], tmp_path: Path) -> Iterator[dict[str, Any]]:  # noqa: F811
    """The console box on the orchestrator's data-core and lifecycle routers, with a real candidate registry."""
    dc = DataCore()
    audit = AuditLog(tmp_path / "orch-audit")
    reg = CandidateRegistry(JobDB(), audit, tmp_path)
    clock = {"now": NOW}
    svc = DataService(dc, audit, lambda: clock["now"], lambda _ref: None, None, reg)  # type: ignore[arg-type,return-value]
    api = FastAPI()
    api.include_router(datacore_router(lambda: svc))
    api.include_router(life_router(lambda: svc))
    oc = SignedClient(api)  # the test's own calls (seeding)
    coc = SignedClient(api, strict=True)  # the console's calls: it signs them itself (review M3)

    def study_api(method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        if path == "/redcap/connections":
            return {"connections": [{"token_ref": "main"}]}
        kw: dict[str, Any] = {"headers": headers} if headers else {}  # T-715: the signed person goes with the call
        r = coc.request(method, path, json=body, **kw) if body is not None else coc.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    box["backend"].study_api = study_api
    h = box["app"].state.helpers
    h.clock = lambda: clock["now"]
    for name, role in (("crc", "coordinator"), ("pi", "investigator")):
        box["users"].create(name, role, PW, f"{name}@hospa.test")
    nos = [h.store.assign_screening_no("GZQO", f"{i:032x}", h.settings_of("GZQO"), "2026-11-01T09:00:00+00:00")
           for i in (1, 2)]  # fmt: skip
    yield {**box, "dc": dc, "oc": oc, "reg": reg, "nos": nos, "clock": clock, "audit": audit}
    dc.close()


def _save(c: TestClient, csrf: str, record: str, form: str, values: dict[str, str], event: str = "",
          back: str = "", reason: str = "") -> Any:  # fmt: skip
    data: dict[str, Any] = {"csrf": csrf, "record": record, "event": event, "form": form, "back": back,
                            "reason": reason}  # fmt: skip
    data.update({f"f_{k}": v for k, v in values.items()})
    return c.post("/studies/GZQO/entry", data=data)


def test_every_key_in_every_language() -> None:
    assert set(L_EN) == set(L_JA) == set(L_ZH)
    for cat in (L_JA, L_ZH):
        for k, v in cat.items():
            for name in re.findall(r"\{(\w+)\}", L_EN[k]):
                assert "{" + name + "}" in v, (k, name)


def test_lifecycle_path_on_the_console(lb: dict[str, Any]) -> None:
    no, other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    assert 'data-testid="dc-builtin-added"' in c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf},
                                                      follow_redirects=True).text  # fmt: skip
    page = c.get("/studies/GZQO/subjects").text
    assert f'data-testid="subject-{no}"' in page and f'data-testid="subject-{other}"' in page
    assert re.search(r'data-testid="count-listed"[^>]*><b>2</b>', page)  # D-1221: "On the list"
    # an illegal step: refused with a plain reason, nothing changed
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "enrolled"})
    assert r.status_code == 409 and 'data-testid="life-refused"' in r.text
    assert "Enrolled cannot follow On the list. Possible next steps: Contacted, Screen failure." in r.text
    r = c.post(f"/studies/GZQO/subjects/{other}/step", data={"csrf": csrf, "to": "screen_fail"})
    assert r.status_code == 409 and "choose a reason" in r.text
    r = c.post(f"/studies/GZQO/subjects/{other}/step",
               data={"csrf": csrf, "to": "screen_fail", "reason": "declined", "on_day": "2026-11-05",
                     "confirm": "yes"})  # fmt: skip
    assert 'data-testid="life-saved"' in r.text and "Screen failure" in r.text
    assert lb["reg"].rows("GZQO")[0].status == "screen_fail"  # the screening log follows
    r = c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    assert 'data-testid="go-consented"' in r.text and 'data-testid="go-enrolled"' not in r.text
    # consent and enrolment through the forms move the participant
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"})
    r = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-04", "en_eligible": "1"}, back="subject")
    assert str(r.url).endswith(f"/studies/GZQO/subjects/{no}?done=entry") and 'data-testid="life-entry-saved"' in r.text
    assert 'data-state="enrolled"' in r.text and "Consent given" not in r.text
    # the visit schedule, and its refusal in plain words
    sched = {"csrf": csrf, "action": "save", "visit": ["v1", "v2", ""], "label": ["Week 1", "", ""],
             "day": ["7", "28", ""], "before": ["2", "3", ""], "after": ["2", "3", ""],
             "anchor": ["enrolment", "enrolment", "enrolment"]}  # fmt: skip
    r = c.post("/studies/GZQO/schedule", data=sched)
    assert 'data-testid="schedule-saved">Schedule saved: 2 visits.' in r.text
    r = c.post("/studies/GZQO/schedule", data={**sched, "visit": ["ae1", "", ""]})
    assert 'data-testid="schedule-refused"' in r.text and "ae1 or dv1 are kept" in r.text
    # the visit list on 2026-11-11 (window 11-09 to 11-13): v1 is in the window; "Done today" fills the form
    lb["clock"]["now"] = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
    page = c.get("/studies/GZQO/visits").text
    week = page[page.index('data-testid="visits-today"') : page.index('data-testid="visits-overdue"')]
    assert f'data-testid="visit-{no}-v1"' in week and "In the window" in week
    href = re.search(rf'href="([^"]+)" data-testid="done-{no}-v1"', page)
    assert href
    form = c.get(href.group(1).replace("&amp;", "&")).text
    assert re.search(r'value="1" checked[^>]*data-testid="f-vs_status-1"', form) and 'value="2026-11-11"' in form
    assert 'name="back" value="visits"' in form
    r = _save(c, csrf, no, "tb_visit", {"vs_status": "1", "vs_date": "2026-11-11", "vs_window": "1"}, "v1", "visits")
    assert 'data-testid="visit-saved"' in r.text and f'data-testid="visit-{no}-v1"' not in r.text
    one = lb["oc"].get(f"/studies/GZQO/subjects/{no}").json()
    assert one["subject"]["state"] == "on_study" and one["visits"][0]["status"] == "done"
    # a serious AE on ae1: on the coordinator's home page and the investigator's
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'href="/studies/GZQO/entry?record=' in page and "event=ae1" in page
    r = _save(c, csrf, no, "tb_adverse_event", {"ae_term": "Pneumonia", "ae_onset": "2026-11-10", "ae_serious": "1",
              "ae_serious_why": "3", "ae_severity": "3", "ae_related": "9"}, "ae1", "subject")  # fmt: skip
    assert 'data-testid="ae-ae1"' in r.text and "event=ae2" in r.text
    home = c.get("/home").text
    assert 'data-testid="sae-banner"' in home and "Pneumonia" in home
    # D-1258: the start page's SAE banner follows the SAE pages' own rule, which admits the PI the log names
    name_pi(lb, "pi")
    p, _ = login(lb["app"], "pi", PW)
    assert 'data-testid="sae-banner"' in p.get("/week").text
    r = p.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": _, "to": "withdrawn", "reason": "3"})
    assert r.status_code == 403  # the investigator reads; the coordinator records
    # withdrawal by the form; the report and its files
    r = _save(c, csrf, no, "tb_withdrawal", {"wd_date": "2026-11-11", "wd_reason": "3", "wd_data_use": "1"},
              back="subject")  # fmt: skip
    assert 'data-state="withdrawn"' in r.text and 'data-testid="life-final"' in r.text
    page = c.get("/studies/GZQO/enrolment").text
    assert re.search(r'data-testid="rep-now-withdrawn">1<', page) and re.search(r'rep-now-screen_fail">1<', page)
    assert "Declined: <b>1</b>" in page and f'data-testid="wd-{no}"' in page
    x = c.get("/studies/GZQO/enrolment.xlsx")
    assert x.status_code == 200 and load_workbook(io.BytesIO(x.content)).sheetnames[0] == "states"
    f = c.get("/studies/GZQO/enrolment.csv")
    assert "state,now,withdrawn,1" in f.text and f.content.startswith(b"\xef\xbb\xbf")  # the byte order mark
    assert CHART_NO not in page and CHART_NO not in x.text
    events = {e.event for e in lb["backend"].audit(None, 500)}
    assert {"console.life_step", "console.life_schedule", "console.export"} <= events


def test_api_v1_refusal_in_the_accounts_language_and_roles(lb: dict[str, Any]) -> None:
    no, _other = lb["nos"]
    c = TestClient(lb["app"])
    r = c.post("/api/v1/session", json={"username": "crc", "password": PW, "lang": "ja"})
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    subs = c.get("/api/v1/studies/GZQO/subjects").json()
    assert {s["record"] for s in subs["subjects"]} == set(lb["nos"]) and subs["may_step"] is True
    r = c.post(f"/api/v1/studies/GZQO/subjects/{no}/step", json={"to": "completed"})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert (
        d["why"] == "order"
        and d["message"]
        == "「リスト掲載」の次に「試験終了」は来ません。次に来られる段階：連絡済み, スクリーニング不適格。"
    )
    r = c.post(f"/api/v1/studies/GZQO/subjects/{no}/step", json={"to": "approached", "on_day": "2026-11-02"})
    assert r.status_code == 200 and r.json()["subject"]["state"] == "approached"
    put = c.put("/api/v1/studies/GZQO/schedule", json={"visits": [{"visit": "v1", "day": 7, "before": 1, "after": 1}]})
    assert put.status_code == 200 and c.get("/api/v1/studies/GZQO/schedule").json()["visits"][0]["visit"] == "v1"
    assert c.get("/api/v1/studies/GZQO/visits").json()["today"] == "2026-11-08"
    assert c.get("/api/v1/studies/GZQO/enrolment").json()["counts"]["approached"] == 1
    assert c.get("/api/v1/studies/GZQO/enrolment/csv").status_code == 200
    v, _csrf = login(lb["app"], "viewer", VIEWER_PW)
    assert v.get("/studies/GZQO/subjects").status_code == 403 and v.get("/studies/GZQO/visits").status_code == 403
    a, _csrf = login(lb["app"], "admin", ADMIN_PW)
    assert a.get(f"/studies/GZQO/subjects/{no}").status_code == 403  # D-280 (OD-5): no patient page for the admin
    assert a.get("/studies/NOPE-01/subjects").status_code == 404


def test_visits_in_the_coordinators_mail_by_pseudonym_and_screening_number(lb: dict[str, Any]) -> None:
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-01", "ic_version": "v1", "ic_copy": "1"})
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-01", "en_eligible": "1"})
    lb["oc"].put("/studies/GZQO/schedule", json={"visits": [{"visit": "v1", "day": 7, "before": 1, "after": 1},
                                                            {"visit": "v2", "day": 1, "before": 0, "after": 2}],
                                                 "by": "crc"})  # fmt: skip
    h = lb["app"].state.helpers
    lb["clock"]["now"] = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)  # a Monday: v1 due today, v2 overdue
    out = notify.collect(h, date(2026, 11, 9), ("N2",))
    mail = next(n for n in out if n.username == "crc")
    pid8 = f"{1:032x}"[:8]
    assert "Study visits today: 1" in mail.body and "Overdue study visits: 1" in mail.body
    assert f"patient {pid8} ({no}) (GZQO): visit v1, window 2026-11-07 to 2026-11-09" in mail.body  # D-136
    assert no not in mail.subject and CHART_NO not in mail.body
    assert mail.counts["study_visits"] == 1 and mail.counts["overdue"] == 1
