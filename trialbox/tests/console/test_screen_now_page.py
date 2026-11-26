"""M8 (R1-N1): the page "Screen now": one job per study, a request during the night queued with its wait, the scope
asked about and never assumed, a role without the right refused and audited, a failed run's step. The page's own
template and routes run on a small stand-in for the console's helpers (no database); fixed times; synthetic jobs."""

from __future__ import annotations

import html
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jinja2
import pytest
from console import i18n_screennow, screen_now
from console.home import Helpers
from console.i18n import CATALOGUES
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from starlette.testclient import TestClient
from tb_common.authz import permit
from tb_contracts import Job

pytestmark = pytest.mark.nodb
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
TODAY = date(2026, 10, 25)
PAGE = "/studies/GZQO/screen-now"
TEMPLATES = screen_now.__file__.rsplit("/", 1)[0] + "/templates"
BASE = jinja2.DictLoader(
    {"base.html": '{% if refresh %}<meta http-equiv="refresh">{% endif %}{% block content %}{% endblock %}'}
)


class Stand:
    """The console's helpers as the page uses them, over a list of jobs."""

    def __init__(self, role: str = "coordinator", lang: str = "en") -> None:
        self.jobs: list[Job] = []
        self.audit: list[tuple[str, dict[str, Any]]] = []
        self.approved: list[Any] = [SimpleNamespace(id="GZQO", version="1.0.0", status="approved")]
        self.made: list[str] = []
        self.role, self.lang = role, lang
        self.env = jinja2.Environment(loader=jinja2.ChoiceLoader([BASE, jinja2.FileSystemLoader(TEMPLATES)]),
                                      autoescape=True)  # fmt: skip

    def add(self, n: int, type_: str, state: str, rs: str | None = "GZQO", **extra: Any) -> Job:
        body: dict[str, Any] = {
            "job_id": f"01JC{n:022d}", "type": type_, "ruleset": rs, "requested_by": "crc@hospa.test",
            "received_at": T0 + timedelta(minutes=n), "updated_at": T0 + timedelta(minutes=n), "state": state, **extra,
        }  # fmt: skip
        self.jobs.append(Job.model_validate(body))
        return self.jobs[-1]

    def helpers(self) -> Any:
        user = SimpleNamespace(role=self.role, sees_study=lambda _s: True)
        sess = SimpleNamespace(user=user, lang=self.lang)

        def page(_r: Any, name: str, _s: Any, status: int = 200, **ctx: Any) -> HTMLResponse:
            def t(key: str, **v: Any) -> str:
                return CATALOGUES[self.lang][key].format(**v)

            return HTMLResponse(self.env.get_template(name).render(t=t, csrf="tok", **ctx), status_code=status)

        def problem(status: int, key: str, **_v: Any) -> Exception:
            return HTTPException(status, key)

        def submit(_s: Any, line: str) -> Job:
            self.made.append(line)
            return self.add(900 + len(self.made), "SCREEN", "received")

        def list_jobs(limit: int = 100, state: str | None = None, *, ruleset: str | None = None,
                      type_: str | None = None) -> list[Job]:  # fmt: skip
            return [j for j in self.jobs if (state is None or j.state == state) and (ruleset is None or j.ruleset == ruleset)
                    and (type_ is None or j.type == type_)][:limit]  # fmt: skip

        return SimpleNamespace(
            need=lambda _r: sess, page=page, problem=problem, csrf_ok=lambda _s, c: c == "tok", actor=lambda _s: "console:crc",
            may_run=lambda u, _rs, _c: permit(u.role, "command.SCREEN").allowed, today=lambda: TODAY, submit=submit,
            au=SimpleNamespace(append=lambda ev, **kw: self.audit.append((ev, kw.get("detail", {})))),
            bk=SimpleNamespace(list_jobs=list_jobs, rulesets=lambda: self.approved),
        )  # fmt: skip

    def client(self) -> TestClient:
        app = FastAPI()
        screen_now.register(app, self.helpers())
        return TestClient(app, follow_redirects=False)

    def actions(self, event: str = "console.screen_now") -> list[str]:
        return [d["action"] for ev, d in self.audit if ev == event]


def run_of(wall: float, scoped: int, snap: str = "2026-10-25") -> dict[str, Any]:
    return {"metrics": {"wall_seconds": wall, "patients_scoped": scoped}, "snapshot_date": snap}


def test_the_stand_in_is_what_the_page_takes() -> None:
    assert {"need", "page", "problem", "csrf_ok", "actor", "submit", "au", "bk"} <= set(Helpers.__dataclass_fields__)
    assert callable(Helpers.may_run) and callable(Helpers.today)


def test_the_three_catalogues_hold_the_same_keys() -> None:
    assert set(i18n_screennow.EN) == set(i18n_screennow.JA) == set(i18n_screennow.ZH)


def test_the_right_is_the_request_pages_own() -> None:
    assert permit("coordinator", "command.SCREEN").allowed and not permit("viewer", "command.SCREEN").allowed


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_page_says_the_scope_and_the_time_from_the_last_measured_run(lang: str) -> None:
    s = Stand(lang=lang)
    s.add(1, "MICROBATCH", "done", **run_of(270, 600))
    text = s.client().get(PAGE).text
    assert {"en": i18n_screennow.EN, "ja": i18n_screennow.JA, "zh-TW": i18n_screennow.ZH}[lang][
        "screennow.start"
    ] in text
    assert "600" in text and "450.0" in text and "4.5" in text  # 270 s over 600 patients: 450 s per 1,000, 4.5 minutes


def test_without_a_measured_run_the_time_and_the_scope_are_not_known_and_the_scope_is_asked() -> None:
    s = Stand()
    c, en = s.client(), i18n_screennow.EN
    page = c.get(PAGE).text
    assert (
        en["screennow.time.unknown"] in page and 'data-testid="screennow-ask-scope"' in page
    )  # the ask is on the page, as a box to tick
    assert 'name="all_dept"' in page and en["screennow.all_dept"] in html.unescape(page)  # its box is the confirmation
    r = c.post(PAGE, data={"csrf": "tok"})
    assert r.status_code == 400 and en["screennow.ask_scope"] in html.unescape(r.text) and s.made == []
    assert c.post(PAGE, data={"csrf": "tok", "all_dept": "1"}).status_code == 303 and len(s.made) == 1


def test_a_request_starts_the_study_screening_once_audited() -> None:
    s = Stand()
    s.add(1, "SCREEN", "done", **run_of(100, 100))
    r = s.client().post(PAGE, data={"csrf": "tok"})
    assert r.status_code == 303 and r.headers["location"] == PAGE
    assert s.made == ["SCREEN GZQO version=1.0.0"] and s.actions() == ["started"]


def test_a_second_request_for_one_study_joins_the_first() -> None:
    s = Stand()
    s.add(1, "SCREEN", "done", **run_of(100, 100))
    c = s.client()
    c.post(PAGE, data={"csrf": "tok"})
    r = c.post(PAGE, data={"csrf": "tok"})
    assert r.headers["location"] == PAGE and len(s.made) == 1  # one job
    page = c.get(PAGE).text
    assert 'data-testid="screennow-running"' in page
    assert 'http-equiv="refresh"' in page  # a running page refreshes by itself
    assert s.actions() == ["started", "joined"]


def test_a_request_during_the_night_is_queued_with_the_wait_stated() -> None:
    s = Stand()
    s.add(1, "SCREEN", "done", **run_of(100, 100))
    s.add(2, "MICROBATCH", "done", **run_of(480, 0))
    s.add(3, "MICROBATCH", "running", rs="OTHER")
    c, en = s.client(), i18n_screennow.EN
    r = c.post(PAGE, data={"csrf": "tok"})
    assert len(s.made) == 1 and r.headers["location"] == PAGE and s.actions() == ["queued"]
    page = c.get(PAGE).text
    assert en["screennow.queued"].format(n=1) in page and "state: received" in page
    assert en["screennow.wait.known"].format(minutes=8.0) in page


def test_a_wait_with_no_earlier_run_to_go_by_is_not_made_up() -> None:
    s = Stand()
    s.add(1, "INGEST", "running", rs=None)
    assert i18n_screennow.EN["screennow.wait.unknown"] in s.client().get(PAGE).text


def test_an_old_snapshot_is_said_to_be_old() -> None:
    s = Stand()
    s.add(1, "SCREEN", "done", **run_of(100, 100, snap="2020-01-01"))
    assert 'data-testid="screennow-stale"' in s.client().get(PAGE).text


def test_a_failed_run_names_its_step_and_the_previous_list_stays() -> None:
    s = Stand()
    done = s.add(1, "SCREEN", "done", **run_of(100, 100))
    s.add(2, "SCREEN", "failed", error={"step": "judging", "message": "The model did not answer."})
    text = s.client().get(PAGE).text
    assert 'data-testid="screennow-failed"' in text and "judging" in text
    assert f"/pilot/jobs/{done.job_id}" in text and "2026-10-25 09:01" in text  # screened now at <time>


def test_a_study_with_no_approved_ruleset_is_refused_by_name() -> None:
    s = Stand()
    s.approved = []
    r = s.client().post(PAGE, data={"csrf": "tok", "all_dept": "1"})
    assert r.status_code == 409 and i18n_screennow.EN["screennow.no_ruleset"] in r.text and s.made == []
    assert s.actions() == ["refused"]


def test_a_role_without_the_right_cannot_start_it_and_the_act_is_audited() -> None:
    s = Stand(role="viewer")
    c = s.client()
    assert 'data-testid="screennow-start"' not in c.get(PAGE).text
    assert c.post(PAGE, data={"csrf": "tok", "all_dept": "1"}).status_code == 403 and s.made == []
    assert s.actions("console.denied") == ["screen-now GZQO"]


def test_a_wrong_token_and_a_bad_study_name_start_nothing() -> None:
    s = Stand()
    c = s.client()
    assert c.post(PAGE, data={"csrf": "wrong", "all_dept": "1"}).status_code == 400
    assert c.get("/studies/bad name!/screen-now").status_code == 404 and s.made == []
