"""T-102a (D-366): the role x route matrix of TB-DR-02b §4, regenerated as a test.

Every route of the console's router table is called once by every role, on the console's test box with one finished
FEAS and one finished SCREEN job of the synthetic study GZQO. The answers are put into the TB-DR-02b form and compared
with the design table ``tests/console/data/role_route_matrix.md``; a difference fails with the rows that changed. A
change that is meant (a new route, a new right) regenerates the table and commits it with the change:

    TB_WRITE_ROLE_MATRIX=1 .venv/bin/python -m pytest tests/console/test_role_route_matrix.py -n 0

Cells: ``Y`` the route let the role in (2xx, a redirect inside the console, or the empty test body refused with 400,
409, 410, 422 or 429: authorisation passed); ``-`` 403; ``n`` 404; ``L`` sent to sign-in (401 or a redirect to
``/login``); ``U`` 503 after the guard let the role in (the test box has no study store; the page needs the data
core); ``E`` another server error (never wanted). GET rows first, every role; then the changing rows (POST, PUT,
DELETE), every role in the column order, form posts with the role's CSRF token and ``/api/v1`` with its bearer token.
Parameters: ``rs``/``ruleset`` GZQO, ``pid`` the SCREEN job's first candidate, ``job_id`` the SCREEN job, every
other one ``1``.

Columns as TB-DR-02b: ``admin``; ``crc`` a hospital coordinator; ``pi`` an investigator the GZQO log does not name
(D-380, ROLE-008: no right in the study); ``lpi`` the investigator the GZQO log names as PI (D-380); ``smo`` an SMO
coordinator scoped to GZQO; ``cra`` a CRO account scoped to GZQO (D-380, ROLE-011: it must name its studies);
``viewer``; ``steward`` (D-280); and ``privacy`` the privacy office (D-380). The test then holds the rows whose guard
is one row of ``authz_matrix.yaml`` to that row: the walk and ``permit`` agree."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from tb_common.authz import BEST_STANDING, NO_STANDING, permit

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    VIEWER_PW,
    _done_feas,
    _done_screen,
    _ulid,
    box,
    login,
)

TABLE = Path(__file__).parent / "data" / "role_route_matrix.md"
PW = "role-matrix-password-01"
A = "a" * 32
# column -> (username, role, affiliation, studies)
COLUMNS: dict[str, tuple[str, str, str, str]] = {
    "admin": ("admin", "admin", "hospital", ""),
    "crc": ("crc", "coordinator", "hospital", ""),
    "pi": ("pi", "investigator", "hospital", ""),
    "lpi": ("lpi", "investigator", "hospital", ""),
    "smo": ("smo", "coordinator", "smo", "GZQO"),
    "cra": ("cra", "cro", "cro", "GZQO"),
    "viewer": ("viewer", "viewer", "hospital", ""),
    "steward": ("stw", "steward", "hospital", ""),
    "privacy": ("dpo", "privacy", "hospital", ""),
}
# not walked: signing in and out, the session's own routes, static files
SKIP = re.compile(r"^/(login|logout|lang|role|static|healthz|favicon|api/v1/session)(/|$|\.)")  # role: D-877
CHANGING = ("POST", "PUT", "DELETE")
HEADER = "| Method | Route | " + " | ".join(COLUMNS) + " |"


def _routes(app: Any) -> list[tuple[str, str]]:
    out = set()
    for r in app.routes:
        if isinstance(r, APIRoute) and not SKIP.match(r.path):
            for m in r.methods or ():
                if m in ("GET", *CHANGING):
                    out.add((m, r.path))
    gets = sorted(x for x in out if x[0] == "GET")
    return gets + sorted(x for x in out if x[0] != "GET")


def _fill(path: str, job_id: str) -> str:
    def one(m: re.Match[str]) -> str:
        name = m.group(1)
        return {"rs": "GZQO", "ruleset": "GZQO", "pid": A, "job_id": job_id, "fmt": "xlsx"}.get(name, "1")

    return re.sub(r"\{(\w+)(?::\w+)?\}", one, path)


def _cell(r: Any) -> str:
    code = r.status_code
    loc = r.headers.get("location", "")
    if code == 401 or (300 <= code < 400 and loc.split("?")[0].endswith("/login")):
        return "L"
    if code == 403:
        return "-"
    if code == 404:
        return "n"
    if code == 503:
        return "U"
    if code >= 500:
        return "E"
    return "Y"


def _clients(b: dict[str, Any]) -> dict[str, tuple[TestClient, str, TestClient]]:
    """Per column: the page client (cookie), its CSRF token, and the API client (bearer token)."""
    users = b["users"]
    out = {}
    for col, (name, role, aff, studies) in COLUMNS.items():
        pw = {"admin": ADMIN_PW, "viewer": VIEWER_PW}.get(name, PW)
        if users.get(name) is None:
            users.create(name, role, pw, f"{name}@hospa.test")
        if aff != "hospital" or studies:
            users.set_scope(name, aff, studies, None)
        page, csrf = login(b["app"], name, pw)
        token, _ = users.new_session(users.get(name), via="api")
        api = TestClient(b["app"], headers={"Authorization": f"Bearer {token}"})
        out[col] = (page, csrf, api)
    from console.teamstore import TeamStore

    team = TeamStore()  # D-380: the GZQO log names ``lpi`` as its PI (the steward wrote it from the signed log)
    team.add_entry("GZQO", username="lpi", name="Dr L", role="pi", tasks=(), start="2026-01-01", end=None,
                   training_day="2026-01-01", training_ref=None, by="stw", at="2026-01-01T00:00:00+00:00")  # fmt: skip
    team.close()
    return out


def _orchestrator_routes(b: dict[str, Any]) -> None:
    """NEW-ARCH-3 slices 2 and 3 (D-865, D-864): the console's conflicts and instrument pages ask the orchestrator.
    The walk's box answers those two families from the orchestrator's own routers, in process, through a client that
    signs nothing itself. Only while the walk asks those two pages: every other route still sees a box with no study
    store, as before (a study store changes how the console signs a patient read before it asks)."""
    from types import SimpleNamespace

    from console.backend import Unavailable, problem_of
    from fastapi import FastAPI
    from omop import schema
    from orchestrator.conflicts_api import router as conflicts_router
    from orchestrator.setup_api import router as setup_router
    from sitesetup.store import SetupStore
    from tb_common.audit import AuditLog

    from tests.actor3 import SignedClient

    held: dict[str, Any] = {}

    def omop() -> Any:
        if "db" not in held:
            held["db"] = schema.connect()
        return held["db"]

    svc = SimpleNamespace(store=SetupStore(), stamp=lambda: "2026-11-16T09:00:00+00:00",
                          audit=AuditLog(b["dir"] / "orch-audit"))  # fmt: skip
    api = FastAPI()
    api.include_router(conflicts_router(omop))
    site = cast(Any, svc)  # the instrument routes read only the store, the stamp and the audit
    api.include_router(
        setup_router(lambda: site, lambda rid: {}, lambda rid: {}, lambda rid: None, lambda: False, lambda *a: None)
    )
    coc = SignedClient(api, strict=True)

    def study_api(method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        if not path.startswith(("/omop/conflicts", "/setup/instruments")):
            raise Unavailable("this backend has no study store")
        kw: dict[str, Any] = {"headers": headers} if headers else {}
        r = coc.request(method, path, json=body, **kw) if body is not None else coc.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    b["orchestrator_study_api"] = study_api


_ASK_THE_ORCHESTRATOR = ("/data/conflicts", "/data/instruments")


def _for(b: dict[str, Any], path: str) -> None:
    """The orchestrator's two route families for the pages that ask them (D-864, D-865); no study store otherwise."""
    bk = b["backend"]
    if path.startswith(_ASK_THE_ORCHESTRATOR):
        bk.study_api = b["orchestrator_study_api"]
    elif "study_api" in vars(bk):
        del bk.study_api


def walk(b: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
    _orchestrator_routes(b)
    _done_feas(b["backend"])
    job_id = _ulid(990)
    _done_screen(b["backend"], job_id)
    clients = _clients(b)
    routes = _routes(b["app"])
    cells: dict[tuple[str, str], dict[str, str]] = {r: {} for r in routes}
    for changing in (False, True):
        for col, (page, csrf, api) in clients.items():
            for method, path in routes:
                if (method in CHANGING) != changing:
                    continue
                url = _fill(path, job_id)
                _for(b, path)
                if path.startswith("/api/v1/"):
                    r = api.request(method, url, json={} if changing else None, follow_redirects=False)
                else:
                    data = {"csrf": csrf} if changing else None
                    r = page.request(method, url, data=data, follow_redirects=False)
                cells[(method, path)][col] = _cell(r)
    _for(b, "")  # the box as it was: no study store
    return [(m, p, cells[(m, p)]) for m, p in routes]


def render(rows: list[tuple[str, str, dict[str, str]]]) -> str:
    lines = [
        "# Role x route matrix (generated by tests/console/test_role_route_matrix.py; T-102a, D-366)",
        "",
        "The design table: the test walks every console route as every role and compares the answers with this file.",
        "Legend, columns and parameters: the test's docstring. Regenerate with `TB_WRITE_ROLE_MATRIX=1`.",
        "",
        HEADER,
        "|---|---|" + "---|" * len(COLUMNS),
    ]
    lines += [f"| {m} | `{p}` | " + " | ".join(c[k] for k in COLUMNS) + " |" for m, p, c in rows]
    return "\n".join(lines) + "\n"


def parse(text: str) -> dict[tuple[str, str], dict[str, str]]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\| (GET|POST|PUT|DELETE) \| `([^`]+)` \| (.+) \|$", line)
        if m:
            out[(m.group(1), m.group(2))] = dict(zip(COLUMNS, (c.strip() for c in m.group(3).split("|")), strict=True))
    return out


def test_the_generated_matrix_equals_the_design_table(box: dict[str, Any]) -> None:  # noqa: F811
    walked = walk(box)
    got = render(walked)
    if os.environ.get("TB_WRITE_ROLE_MATRIX") == "1":
        TABLE.write_text(got, encoding="utf-8")
    want = parse(TABLE.read_text(encoding="utf-8"))
    have = parse(got)
    assert len(have) > 150  # the walk reached the router table
    diff = [f"{k[0]} {k[1]}: design {want.get(k)} walk {have.get(k)}" for k in sorted(set(want) | set(have))
            if want.get(k) != have.get(k)]  # fmt: skip
    assert not diff, "the role x route matrix changed:\n" + "\n".join(diff)
    assert not [k for k, c in have.items() if "E" in c.values()], "a route answered with a server error"
    agree_with_permit(walked)
    same_answer(have)


# The routes whose guard is one row of the matrix alone (T-102c, D-425: every call site asks ``permit``): the walk
# must refuse exactly the roles ``permit`` refuses (with no standing in the study; the column's role, not its scope).
# Only routes that check the role before they read the body: the job page's and the candidate page's reveal answer an
# empty body with 400 before the role check (one reveal path, D-273, refuses the administrator after it).
ROUTE_ACTIONS: dict[tuple[str, str], str] = {
    ("GET", "/admin/edc"): "redcap.connection",
    ("GET", "/api/edc/map"): "redcap.connection",
    ("PUT", "/api/edc/map"): "redcap.connection",
    ("POST", "/api/edc/tools"): "redcap.connection",
    ("POST", "/api/edc/tools/{proposal_id}/confirm"): "redcap.connection",
    ("GET", "/sae"): "sae.view",
    ("GET", "/ops/users"): "ops.view",
    # NEW-FLAG-1 (D-706): the page opens for whoever may see the hold after a restore (the administrator, who sees
    # every flag there, and the data steward, who sees that one); which flags it lists is the page's own rule
    ("GET", "/ops/flags"): "restore.release",
    # (the table's POST /ops/flags row shows the steward refused: the walk posts an empty body, which names no flag;
    # the steward's change of the one flag, and everyone else's refusal of it, are held by test_flags_page.py)
    ("POST", "/studies/{rs}/patients/{pid}/reveal"): "id.reveal",
    ("GET", "/breakglass"): "breakglass.read",
    ("POST", "/studies/{rs}/patients/{pid}/mark"): "list.mark",
    ("POST", "/pilot/jobs/{job_id}/approve"): "criteria.approve",
    ("POST", "/breakglass"): "breakglass.open",
    ("GET", "/site/opt-outs"): "optout.keep",  # D-380 (ROLE-005)
    ("POST", "/site/opt-outs"): "optout.keep",
    ("GET", "/api/v1/site/opt-outs"): "optout.keep",
    ("GET", "/data/items"): "items.view",  # D-380: the steward's page, not the administrator's
    ("GET", "/reports/research-office"): "report.office",  # T-102c (ROLE-017): one row for the page and its XLSX
    ("GET", "/reports/research-office.xlsx"): "report.office",
    ("GET", "/audit"): "audit.browse",  # T-211c (D-451, ROLE-013): the privacy office and the steward only
    ("GET", "/audit/patients"): "audit.browse",
    ("GET", "/audit/patients/{pid}"): "audit.browse",
    ("GET", "/audit/patients/{pid}/report.csv"): "audit.browse",
    ("POST", "/audit/verify"): "audit.browse",
    ("POST", "/api/v1/audit/verify"): "audit.browse",
    # T-310a (D-446): the weekly PI sample of criteria not matched and the site's check, page and /api/v1 alike
    ("GET", "/studies/{rs}/not-matched/sample"): "notmatched.sample",
    ("POST", "/studies/{rs}/not-matched/sample/{pid}"): "notmatched.sample",
    ("GET", "/api/v1/studies/{rs}/not-matched/sample"): "notmatched.sample",
    ("POST", "/api/v1/studies/{rs}/not-matched/sample/{pid}"): "notmatched.sample",
    ("GET", "/studies/{rs}/not-matched/check"): "notmatched.check",
    ("POST", "/studies/{rs}/not-matched/check"): "notmatched.check",
    ("GET", "/api/v1/studies/{rs}/not-matched/check"): "notmatched.check",
    ("POST", "/api/v1/studies/{rs}/not-matched/check"): "notmatched.check",
}

# T-102c (D-425, ROLE-017): a page, its download and its /api/v1 twin ask one question, so every role gets the same
# answer from each (the PI was refused the XLSX the API gave it; the administrator got the XLSX the page refused).
SAME_ANSWER: tuple[tuple[tuple[str, str], ...], ...] = (
    (("GET", "/studies/{rs}/screening-log"), ("GET", "/studies/{rs}/screening-log.xlsx"),
     ("GET", "/api/v1/studies/{rs}/screening-log")),
    (("GET", "/reports/research-office"), ("GET", "/reports/research-office.xlsx")),
    (("GET", "/audit"), ("GET", "/audit/patients/{pid}"), ("GET", "/audit/patients/{pid}/report.csv"),
     ("POST", "/audit/verify"), ("POST", "/api/v1/audit/verify")),
    (("GET", "/studies/{rs}/not-matched/sample"), ("GET", "/api/v1/studies/{rs}/not-matched/sample")),  # T-310a
    (("POST", "/studies/{rs}/not-matched/sample/{pid}"), ("POST", "/api/v1/studies/{rs}/not-matched/sample/{pid}")),
    (("GET", "/studies/{rs}/not-matched/check"), ("GET", "/api/v1/studies/{rs}/not-matched/check")),
    (("POST", "/studies/{rs}/not-matched/check"), ("POST", "/api/v1/studies/{rs}/not-matched/check")),
)  # fmt: skip


def same_answer(have: dict[tuple[str, str], dict[str, str]]) -> None:
    for group in SAME_ANSWER:
        first = have[group[0]]
        for key in group[1:]:
            assert have[key] == first, (group[0], key, first, have[key])


def test_role017_page_and_api_agree_in_the_design_table() -> None:
    """ROLE-017: in the committed design table (which the walk above must equal) page, XLSX and API agree."""
    have = parse(TABLE.read_text(encoding="utf-8"))
    same_answer(have)
    log = have[("GET", "/api/v1/studies/{rs}/screening-log")]
    assert log["lpi"] == "Y" and log["admin"] == "-"  # the logged PI reads its log; the administrator no patient row


# D-380 (ROLE-008): an investigator the study's log does not name has no right in the study, whatever the role row
# says; on a study's route the delegation log refuses ``pi`` before the row is read (``test_t102b_roles`` holds it).
UNLOGGED = ("pi",)
STANDING = {"lpi": BEST_STANDING}  # the logged PI: every task of GZQO (the walk's study)


def agree_with_permit(walked: list[tuple[str, str, dict[str, str]]]) -> None:
    have = {(m, p): c for m, p, c in walked}
    for key, action in ROUTE_ACTIONS.items():
        assert key in have, key
        for col, (_, role, _, _) in COLUMNS.items():
            if col in UNLOGGED and key[1].startswith("/studies/"):
                assert have[key][col] == "-", (key, col)
                continue
            refused = have[key][col] == "-"
            assert refused == (not permit(role, action, STANDING.get(col, NO_STANDING))), (key, col, have[key][col])
