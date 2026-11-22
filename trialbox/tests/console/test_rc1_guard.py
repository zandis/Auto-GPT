"""rc1's refusals of live patient lists and of patient mail and downloads (the owner's ruling of 2026-11-20; review
R22-34; ``tb_common.rc1_refusals``).

* ``live_patient_lists``: the orchestrator's first step of every scenario that lists patients refuses
  (``orchestrator.scheduler.require_released``), and the console serves no stored list (``console.rc1_guard``);
* ``patient_mail_and_downloads``: the mail gateway holds a mail with a job's patient-level files
  (``mail_gateway.gateway.Gateway._still_current``), and the console gives no patient-level file to download.

On a box with ``TB_ENV`` unset, PRODUCTION or unknown: nothing is listed, shown, sent or downloaded; the person reads the
table's message (the problem page, JSON on ``/api/``, the job's error, the held mail's reason) and the refusal is an
audited event. On DEV, TEST and VALIDATION (D-1072) the guards let it through. Synthetic data only."""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from console import i18n_rc1
from console import rc1_guard as rg
from console.app import create_app
from console.auth import UserStore
from console.i18n import CATALOGUES
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.routing import Mount, WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from tb_common import rc1_refusals
from tb_common.audit import AuditLog
from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import ADMIN_PW, PILOT_ENV, FakeBackend

ENVS = ("", "PRODUCTION", "PILOT", "DEV", "TEST", "VALIDATION")
LIST_KEY = "rc1.live_patient_lists"
FILE_KEY = "rc1.patient_mail_and_downloads"
PATIENT = "a1b2c3d4e5f6c001" * 2  # a synthetic pseudonym
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def _job(b: FakeBackend, n: int, type_: str, files: tuple[tuple[str, bytes, str], ...]) -> Job:
    jid = f"01JB{n:022d}"
    outs = []
    for name, data, tag in files:
        key = f"outputs/{jid}/{name}"
        b.objects[key] = data
        out = {"filename": name, "sha256": sha256_bytes(data), "minio_key": key, "recipients": ["crc@hospa.test"],
               "tag": tag}  # fmt: skip
        outs.append(JobOutput.model_validate(out))
    job = {"job_id": jid, "type": type_, "ruleset": "GZQO", "ruleset_version": "1.0.0", "requested_by": "crc@hospa.test",
           "received_at": NOW, "updated_at": NOW, "state": "done", "options": {}, "inputs": [], "outputs": outs}  # fmt: skip
    return b.add_job(Job.model_validate(job))


def _console(tmp_path: Path, env: str) -> dict[str, Any]:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore()
    if users.get("admin") is None:  # one trial database per test: a second console of the test shares it
        users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    rows = json.dumps({"rows": [{"pid": PATIENT, "tier": "high"}]}).encode()
    screen = _job(
        backend, 1, "SCREEN", (("candidate_list_GZQO.json", rows, "phi"), ("counts_GZQO.json", b"{}", "aggregate"))
    )
    feas = _job(backend, 2, "FEAS", (("feasibility_GZQO.json", b'{"start_n": 600}', "aggregate"),))
    case = _job(backend, 3, "CASE", (("case_GZQO.html", f"<p>{PATIENT}</p>".encode(), "phi"),))
    base = {k: v for k, v in PILOT_ENV.items() if k != "TB_ENV"}
    app = create_app({**base, **({"TB_ENV": env} if env else {}), "TB_CONSOLE_DIR": str(tmp_path / "console")},
                     backend=backend, audit=AuditLog(backend.audit_dir), users=users)  # fmt: skip
    return {"app": app, "dir": tmp_path, "screen": screen, "feas": feas, "case": case}


def _events(b: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == rg.EVENT and (e.get("detail") or {}).get("refusal")]


def _refused(env: str) -> bool:
    return env not in rc1_refusals.ALLOWED


def _ask(b: dict[str, Any], paths: list[str], key: str, env: str, methods: tuple[str, ...] = ("GET", "HEAD")) -> None:
    """Each path, by each method, is refused before its route (refused), or reaches its route (allowed)."""
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    shown = rc1_refusals.text(key, "en", environment=env or "PRODUCTION")
    asked = [(m, p) for p in paths for m in methods]
    for method, path in asked:
        r = c.request(method, path)
        if _refused(env):
            assert r.status_code == 403, (method, path, r.status_code)
            if method == "HEAD":
                assert r.content == b"", path  # the same refusal, with no body
            elif path.startswith("/api/"):
                assert r.json() == {"error": key, "detail": {"environment": env or "PRODUCTION"}}, path
            else:
                assert shown in r.text and 'data-testid="problem-page"' in r.text, path
            assert PATIENT not in r.text, path  # nothing listed or downloaded
        else:
            assert r.status_code != 403 and shown not in r.text, (method, path, r.status_code)
    seen = _events(b)
    if _refused(env):
        assert [e["detail"] for e in seen] == [{"refusal": rc1_refusals.row(key.removeprefix("rc1.")).name,
                                                "environment": env or "PRODUCTION", "action": p} for _, p in asked]  # fmt: skip
        assert all(e["actor"] == "console:-" for e in seen)
    else:
        assert seen == []


@pytest.mark.parametrize("env", ENVS)
def test_no_live_patient_list_on_a_production_box(
    env: str, db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orchestrator.clients import StepFailed
    from orchestrator.scheduler import require_open, require_released

    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)
    monkeypatch.delenv("TB_DB_URL", raising=False)  # a bare stack: the restore hold and the study state are open
    if _refused(env):
        for first_step in (require_released, lambda: require_open("GZQO")):
            with pytest.raises(StepFailed) as got:
                first_step()
            said = "PRODUCTION" if env in ("", "PRODUCTION") else "an unknown TB_ENV"  # the detail names it
            assert got.value.step == "rc1" and got.value.detail == f"{LIST_KEY}: {said}"
            assert got.value.message.startswith("rc1 makes and shows no live patient list on this box.")
    else:
        require_released()
        require_open("GZQO")
    monkeypatch.setenv("TB_DB_URL", db_url)  # the console's own stores
    b = _console(tmp_path, env)
    paths = ["/studies/GZQO/week", "/api/v1/studies/GZQO/patients", f"/studies/GZQO/patients/{PATIENT}",
             f"/api/v1/studies/GZQO/patients/{PATIENT}/twin", "/studies/GZQO/candidates",
             f"/studies/GZQO/candidates/{PATIENT}", "/api/v1/studies/GZQO/candidates",
             f"/api/v1/studies/GZQO/candidates/{PATIENT}", "/studies/GZQO/referrals", "/api/v1/studies/GZQO/referrals",
             "/studies/GZQO/screening-log", "/api/v1/studies/GZQO/screening-log", "/studies/GZQO/cohort",
             "/pilot/registry/GZQO", "/site/patients", "/site/people", f"/pilot/jobs/{b['screen'].job_id}",
             f"/pilot/jobs/{b['case'].job_id}"]  # fmt: skip
    _ask(b, paths, LIST_KEY, env)
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    assert c.get(f"/pilot/jobs/{b['feas'].job_id}").status_code != 403  # a card of counts stays open
    assert (c.get("/week").status_code == 403) is _refused(env)  # fail-closed: a route the list does not name


@pytest.mark.parametrize("env", ["", "PRODUCTION", "DEV"])
def test_a_write_on_a_listed_person_is_refused_by_every_method(env: str, db_url: str, tmp_path: Path) -> None:
    """A held path has no open door: a mark, a reveal, a referral, a promotion, a resolution (POST), as its page."""
    b = _console(tmp_path, env)
    paths = [f"/studies/GZQO/patients/{PATIENT}/mark", f"/studies/GZQO/patients/{PATIENT}/reveal",
             f"/api/v1/studies/GZQO/patients/{PATIENT}/reveal", f"/studies/GZQO/candidates/{PATIENT}/referral",
             "/pilot/registry/GZQO", "/pilot/registry/GZQO/promote", "/site/people/resolve"]  # fmt: skip
    _ask(b, paths, LIST_KEY, env, methods=("POST",))


@pytest.mark.parametrize("env", ENVS)
def test_no_patient_mail_or_download_on_a_production_box(
    env: str, db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_mail_resolve import MTA
    from tests.unit.test_the_outbox_asks_before_it_sends import JOB, Register, _gw, _phi, _state

    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)
    mta, reg = MTA(), Register()
    mta.cause = None  # the server is up
    gw = _gw(tmp_path / "mail", mta, reg)
    gw.send(_phi("rc1"))
    state, why = _state(gw, "rc1")
    if _refused(env):
        assert mta.sent == [] and reg.asked == []  # held before anything is read or sent
        assert state == "failed" and FILE_KEY in why and (env or "PRODUCTION") in why  # held at once, for a person
        assert gw.drain(force=True) == {} and mta.sent == []  # never tried again by itself
        held = [json.loads(x) for f in sorted((tmp_path / "mail" / "audit").glob("*.jsonl"))
                for x in f.read_text(encoding="utf-8").splitlines() if x]  # fmt: skip
        assert [e["event"] for e in held] == ["mail.failed"] and FILE_KEY in held[0]["detail"]["error"]
    else:
        assert state == "sent" and mta.sent and reg.asked == [JOB]  # asked, then sent
    b = _console(tmp_path / "console", env)
    s = b["screen"].job_id
    paths = [f"/pilot/jobs/{s}/files/candidate_list_GZQO.json", f"/pilot/jobs/{s}/view/candidate_list_GZQO.json",
             f"/pilot/jobs/{b['case'].job_id}/files/case_GZQO.html", "/studies/GZQO/edc/copy/GZQO-0001",
             f"/audit/patients/{PATIENT}/report.csv", "/pilot/cascade/RUN1/files/final_list.json",
             "/studies/GZQO/screening-log.xlsx", "/pilot/registry/GZQO/export.xlsx", "/studies/GZQO/enrolment.csv",
             "/api/v1/studies/GZQO/enrolment/csv", "/studies/GZQO/export.csv", "/api/v1/studies/GZQO/export/csv",
             "/studies/GZQO/edc/export.odm.xml", "/api/v1/studies/GZQO/edc/export/odm", "/studies/GZQO/edc/copy.csv",
             "/api/v1/studies/GZQO/edc/copy"]  # fmt: skip
    _ask(b, paths, FILE_KEY, env)
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    assert c.get(f"/pilot/jobs/{s}/files/counts_GZQO.json").status_code != 403  # an aggregate file stays open


def test_the_guard_reads_the_consoles_environment_and_the_table(db_url: str, tmp_path: Path) -> None:
    """One rule: the console's own ``TB_ENV`` (unset is PRODUCTION), an unknown name refused, the table's sets."""
    for env, refused in (("", True), ("PRODUCTION", True), ("PILOT", True), ("VALIDATION", False), ("dev", False),
                         ("TEST", False)):  # fmt: skip
        g = _console(tmp_path / (env or "unset"), env)["app"].state.rc1_guard
        assert g.lists_refused() is refused and g.downloads_refused() is refused, env


def test_the_consoles_words_are_the_tables_words() -> None:
    cats = {"en": i18n_rc1.EN, "ja": i18n_rc1.JA, "zh-TW": i18n_rc1.ZH}
    for r in rc1_refusals.REFUSALS:
        for lang in rc1_refusals.LANGS:
            assert cats[lang][r.key] == rc1_refusals.TEXTS[r.key][lang] == CATALOGUES[lang][r.key], (r.key, lang)
            assert CATALOGUES[lang][f"problem.h.{r.key}"] == cats[lang][f"problem.h.{r.key}"]


# ---------------------------------------------------------------------------------------------- every route
_FILE = re.compile(r"FileResponse|StreamingResponse|attachment|spreadsheetml|text/csv|application/zip|application/pdf")
#: the allowed routes that give a file, each with why it holds no patient (the integrator's 7080384411)
ALLOWED_FILES: dict[str, str] = {
    "/admin/ops/network/{name}": "hospital IT's network sheet of the box (hosts and ports), no person",
    "/pilot/jobs/{job_id}/sponsor-pack.zip": "a FEAS job's aggregate files and a README only (D-101)",
    "/reports/research-office.xlsx": "counts per study with small cells suppressed (D-270), no person",
    "/pilot/jobs/{job_id}/files/{filename}": "allowed only for an aggregate output, read from the job",
    "/pilot/jobs/{job_id}/view/{filename}": "allowed only for an aggregate output, read from the job",
    "/favicon.ico": "the console's icon",
}
#: refused routes whose code names a file type but take a file in and answer with a page (refused as a list)
TAKES_FILES = {
    "/pilot/protocol": "takes a protocol PDF in; answers with a page",
    "/pilot/mailbox": "takes a test mail's attachment in; answers with a page",
}


def _filled(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "X", path.replace("{fmt}", "csv"))


def _routes(app: Any) -> list[tuple[str, str, Any]]:
    """Every route of the console, mounted apps and ``add_route`` included: (methods, path, endpoint)."""
    out = []
    for r in app.routes:
        if isinstance(r, Mount):
            out.append(("*", r.path + "/x", None))
        elif isinstance(r, WebSocketRoute):  # no methods: a websocket, asked by the guard as one
            out.append(("WEBSOCKET", r.path, r.endpoint))
        else:
            out.append((",".join(sorted(getattr(r, "methods", None) or ["*"])), r.path, getattr(r, "endpoint", None)))
    return out


def test_every_route_is_allowed_by_name_or_refused_and_the_guard_is_outermost(db_url: str, tmp_path: Path) -> None:
    """Fail-closed by construction: each route of the console is on :data:`rg.ALLOWED` or answers rc1's refusal on
    a PRODUCTION box; a route that gives a file is refused as a download unless its row above says why not."""
    b = _console(tmp_path, "PRODUCTION")
    app, g = b["app"], b["app"].state.rc1_guard

    async def live(ws: WebSocket) -> None:  # a websocket route, as a later card might add one
        await ws.close()

    app.add_api_websocket_route("/studies/{rs}/live", live)
    assert app.user_middleware[0].cls is rg.Rc1Layer and app.user_middleware[0].kwargs["guard"] is g  # outermost
    routes = _routes(app)
    assert len(routes) > 300 and any(m == "*" for m, _, _ in routes)  # the walk reached the routes and the mount
    allowed, refused, loose = [], [], []
    for methods, path, endpoint in routes:
        filled = _filled(path)
        gives_file = endpoint is not None and bool(_FILE.search(inspect.getsource(endpoint)))
        named = any(p.match(filled) for p, _ in rg.ALLOWED)
        by_job = rg.JOB_CARD.match(filled) or rg.JOB_FILE.match(filled)
        if named or by_job:
            allowed.append(path)
            if gives_file and path not in ALLOWED_FILES:
                loose.append(f"{methods} {path}: allowed and gives a file, with no reason")
            continue
        name = g.refusal_of("GET", filled)
        if name is None:
            loose.append(f"{methods} {path}: on neither side")
        elif gives_file and name != "patient_mail_and_downloads" and path not in TAKES_FILES:
            loose.append(f"{methods} {path}: gives a file, refused as {name}")
        else:
            refused.append(path)
    assert loose == [], "\n".join(loose)
    assert len(refused) > 200 and len(allowed) > 25
    assert "/studies/{rs}/live" in refused and any(m == "WEBSOCKET" for m, _, _ in routes)
    for p, why in rg.ALLOWED:  # no stale line: each allows a route the console has
        assert any(p.match(_filled(path)) for _, path, _ in routes), (p.pattern, why)


@pytest.mark.parametrize("env", ["", "PRODUCTION", "DEV"])
def test_a_people_list_address_of_j5_is_refused_before_its_rewrite(env: str, db_url: str, tmp_path: Path) -> None:
    """J-5's addresses (``/studies/{rs}/people/candidates``, rewritten inside to the old list) meet the guard first."""
    b = _console(tmp_path, env)
    paths = ["/studies/GZQO/people/candidates", "/studies/GZQO/people/candidates/all",
             "/studies/GZQO/people/participants", "/people/candidates"]  # fmt: skip
    _ask(b, paths, LIST_KEY, env)


@pytest.mark.parametrize("env", ["", "PRODUCTION"])
def test_what_a_refused_box_still_serves(env: str, db_url: str, tmp_path: Path) -> None:
    """Sign-in, health, the ops and admin pages, aggregate counts and static files answer; the refusal carries the
    console's security headers although no inner middleware ran; the audit records the path, never the query."""
    b = _console(tmp_path, env)
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    for path in ("/login", "/healthz", "/admin/ops", "/reports/research-office", "/static/console.css",
                 f"/pilot/jobs/{b['feas'].job_id}", "/help"):  # fmt: skip
        assert c.get(path).status_code != 403, path
    r = c.get("/home?pid=" + PATIENT)
    assert r.status_code == 403 and r.headers["X-Frame-Options"] == "DENY" and "Content-Security-Policy" in r.headers
    (ev,) = _events(b)
    assert ev["detail"] == {"refusal": "live_patient_lists", "environment": env or "PRODUCTION", "action": "/home"}
    assert PATIENT not in json.dumps(ev)  # M17: the query is never recorded


def test_a_card_of_any_list_job_is_refused_and_a_store_that_fails_refuses(db_url: str, tmp_path: Path) -> None:
    """M11 and M12: a NAV job's card is a list (as SCREEN, MICROBATCH, COHORT, CASE); a store that does not answer
    shows no card, not even one of counts."""
    b = _console(tmp_path, "PRODUCTION")
    nav = _job(b["app"].state.helpers.bk, 9, "NAV", (("nav_GZQO.json", b"{}", "phi"),))
    g = b["app"].state.rc1_guard
    assert g.refusal_of("GET", f"/pilot/jobs/{nav.job_id}") == "live_patient_lists"
    assert g.refusal_of("GET", f"/pilot/jobs/{b['feas'].job_id}") is None

    def down(_job_id: str) -> Any:
        raise ConnectionError("the orchestrator did not answer")

    b["app"].state.helpers.bk.get_job = down
    assert g.refusal_of("GET", f"/pilot/jobs/{b['feas'].job_id}") == "live_patient_lists"
    assert g.refusal_of("GET", f"/pilot/jobs/{b['feas'].job_id}/files/feasibility_GZQO.json") == (
        "patient_mail_and_downloads"
    )


# ---------------------------------------------------------------------------------------------- the third look
@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION"])
def test_the_admins_send_now_mails_no_candidate_row_on_a_refused_box(
    env: str, db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2234-13: ``POST /ops/notices`` (an ops page, allowed) sends today's notices through ``console.notify``; on a
    refused box no N1 or N2 carries a candidate row (``notify._collect`` asks the table)."""
    from datetime import date
    from types import SimpleNamespace

    from console.sitestore import NotifyPerson

    from tests.console.test_console_app import login_totp
    from tests.console.test_study_state_d386 import _helpers

    monkeypatch.setenv("TB_ENV", env)
    b = _console(tmp_path, env)
    h = b["app"].state.helpers
    fake = _helpers(h.store)  # the week's rows of two candidates, a PI and a coordinator who see the study
    h.store.save_notify_person(NotifyPerson("pi", None, lang="en"))
    h.store.save_notify_person(NotifyPerson("crc", None, lang="en"))
    real_users = h.users

    class Users:  # the real store for the admin's sign-in; the fake's people for the round
        def users(self) -> Any:
            return fake.users.users()

        def __getattr__(self, name: str) -> Any:
            return getattr(real_users, name)

    c, csrf = login_totp(b["app"])
    for name in ("trials", "week_bundle", "delegated_ok"):
        monkeypatch.setattr(h, name, getattr(fake, name))
    monkeypatch.setattr(h, "users", Users())
    monkeypatch.setattr(h, "life_mail", None, raising=False)
    monkeypatch.setattr(h, "today", lambda: date(2026, 11, 2))  # a Monday: the week's N1 goes without a clinic id
    h.bk.registry_rows = SimpleNamespace(registry_rows=lambda _rs: []).registry_rows
    r = c.post("/ops/notices", data={"csrf": csrf})
    assert r.status_code == 200, r.text[-300:]
    bodies = [body for _kind, _to, _subject, body in h.bk.notices]
    rows = [x for x in bodies if "11111111" in x or "22222222" in x]
    if env == "PRODUCTION":
        assert rows == []  # no candidate row leaves
    else:
        assert rows  # the same round on an allowed box mails its rows


@pytest.mark.parametrize("env", ["", "PRODUCTION", "VALIDATION"])
def test_the_audit_page_of_one_patient_is_refused_on_a_refused_box(env: str, db_url: str, tmp_path: Path) -> None:
    """R2234-14: ``/audit?pid=`` is the same list as ``/audit/patients/{pid}``; the plain log stays an admin page."""
    b = _console(tmp_path, env)
    g = b["app"].state.rc1_guard
    refused = env != "VALIDATION"
    assert (g.refusal_of("GET", "/audit", f"pid={PATIENT}") == "live_patient_lists") is refused
    assert (g.refusal_of("GET", "/audit", f"kind=reveal&pid=%20{PATIENT[:8]}") == "live_patient_lists") is refused
    assert g.refusal_of("GET", "/audit", "kind=reveal") is None and g.refusal_of("GET", "/audit", "pid=") is None
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    r = c.get(f"/audit?pid={PATIENT}")
    assert (r.status_code == 403) is refused
    seen = _events(b)
    if refused:
        assert [e["detail"]["action"] for e in seen] == ["/audit"] and PATIENT not in json.dumps(seen)


@pytest.mark.parametrize("kind", ["SCREEN", "MICROBATCH", "COHORT", "NAV", "CASE", "SUBMIT"])
def test_the_card_of_every_job_that_names_a_patient_is_refused(kind: str, db_url: str, tmp_path: Path) -> None:
    """R2234-15 and mutants M09, M10: each list job's card, and SUBMIT's (its card names the patient), is refused."""
    b = _console(tmp_path, "PRODUCTION")
    job = _job(b["app"].state.helpers.bk, 20, kind, (("counts.json", b"{}", "aggregate"),))
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    assert c.get(f"/pilot/jobs/{job.job_id}").status_code == 403
    assert c.get(f"/pilot/jobs/{job.job_id}/files/counts.json").status_code != 403  # its counts stay open


@pytest.mark.parametrize("tag", ["phi", "D1", "internal"])
def test_every_file_of_a_job_that_is_not_aggregate_is_refused(tag: str, db_url: str, tmp_path: Path) -> None:
    """Mutants M12 and M13: a file is open only when the job names it and tags it aggregate."""
    b = _console(tmp_path, "PRODUCTION")
    job = _job(b["app"].state.helpers.bk, 21, "FEAS", (("one.json", b"{}", "aggregate"),))
    if tag != "aggregate":  # a tag the contract does not know yet (fail-closed: only "aggregate" opens a file)
        (job.outputs or [])[0].__dict__["tag"] = tag
    g = b["app"].state.rc1_guard
    assert g.refusal_of("GET", f"/pilot/jobs/{job.job_id}/files/one.json") == "patient_mail_and_downloads"
    assert g.refusal_of("GET", f"/pilot/jobs/{job.job_id}/files/missing.json") == "patient_mail_and_downloads"


@pytest.mark.parametrize("method", ["OPTIONS", "PUT", "PATCH", "DELETE", "POST", "HEAD", "GET"])
def test_a_refused_route_is_refused_by_every_method(method: str, db_url: str, tmp_path: Path) -> None:
    """Mutants M14 and M15 (the review's M13 to M15): OPTIONS, PUT, PATCH and DELETE meet the same refusal."""
    b = _console(tmp_path, "PRODUCTION")
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    for path in ("/studies/GZQO/week", "/api/v1/studies/GZQO/patients", "/studies/GZQO/screening-log.xlsx"):
        assert c.request(method, path).status_code == 403, (method, path)
    assert len(_events(b)) == 3


def test_a_websocket_on_a_refused_box_is_closed_before_it_opens(db_url: str, tmp_path: Path) -> None:
    """R2234-16 (a): ``BaseHTTPMiddleware`` lets a websocket through; the guard is a plain ASGI layer that closes it."""
    sent: list[str] = []
    for env in ("PRODUCTION", "VALIDATION"):
        b = _console(tmp_path / env, env)

        async def rows(ws: WebSocket) -> None:
            await ws.accept()
            sent.append("row")
            await ws.send_text(PATIENT)
            await ws.close()

        b["app"].add_api_websocket_route("/studies/{rs}/live", rows)
        c = TestClient(b["app"], base_url="https://testserver")
        if env == "PRODUCTION":
            with pytest.raises(WebSocketDisconnect) as got, c.websocket_connect("/studies/GZQO/live") as ws:
                ws.receive_text()
            assert got.value.code == 1008 and sent == []
            assert [e["detail"]["action"] for e in _events(b)] == ["/studies/GZQO/live"]
        else:
            with c.websocket_connect("/studies/GZQO/live") as ws:
                assert ws.receive_text() == PATIENT


def test_the_guard_reads_the_path_without_the_root_path(db_url: str, tmp_path: Path) -> None:
    """R2234-16 (b): behind a proxy that mounts the console under a root path, the route's own path is matched."""
    b = _console(tmp_path, "PRODUCTION")
    c = TestClient(b["app"], base_url="https://testserver", root_path="/tb", follow_redirects=False)
    assert c.get("/tb/studies/GZQO/week").status_code == 403
    assert c.get("/tb/healthz").status_code != 403
    assert [e["detail"]["action"] for e in _events(b)] == ["/studies/GZQO/week"]


def test_an_address_is_matched_as_it_is_sent(db_url: str, tmp_path: Path) -> None:
    """Mutants M20 and M21: a trailing slash is another address (refused), and a query is never part of the match."""
    b = _console(tmp_path, "PRODUCTION")
    c = TestClient(b["app"], base_url="https://testserver", follow_redirects=False)
    assert c.get("/healthz/").status_code == 403 and c.get("/login/").status_code == 403
    assert c.get("/login?next=/home").status_code != 403 and c.get("/healthz?full=1").status_code != 403


def test_a_new_admin_page_is_refused_until_it_is_listed(db_url: str, tmp_path: Path) -> None:
    """R2234-16 (c): the admin pages are listed one by one; an admin address the list does not name is refused."""
    g = _console(tmp_path, "PRODUCTION")["app"].state.rc1_guard
    assert g.refusal_of("GET", "/admin/ops") is None and g.refusal_of("POST", "/admin/jobs/01J/retry") is None
    for path in ("/admin/patients", "/admin/ops/x/y", "/admin/jobs/01J/rows", "/adminx"):
        assert g.refusal_of("GET", path) == "live_patient_lists", path
