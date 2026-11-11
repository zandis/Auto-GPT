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
from typing import Any

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
SKIP = re.compile(r"^/(login|logout|lang|static|healthz|favicon|api/v1/session)(/|$|\.)")
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


def walk(b: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
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
                if path.startswith("/api/v1/"):
                    r = api.request(method, url, json={} if changing else None, follow_redirects=False)
                else:
                    data = {"csrf": csrf} if changing else None
                    r = page.request(method, url, data=data, follow_redirects=False)
                cells[(method, path)][col] = _cell(r)
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


# The routes whose guard is one row of the matrix, today (T-102c moves the other call sites to ``permit``): the walk
# must refuse exactly the roles ``permit`` refuses (with no standing in the study; the column's role, not its scope).
# Only routes that check the role before they read the body: the job page's and the candidate page's reveal answer an
# empty body with 400 before the role check (one reveal path, D-273, refuses the administrator after it).
ROUTE_ACTIONS: dict[tuple[str, str], str] = {
    ("GET", "/sae"): "sae.view",
    ("GET", "/ops/users"): "ops.view",
    ("GET", "/ops/flags"): "ops.view",
    ("POST", "/studies/{rs}/patients/{pid}/reveal"): "id.reveal",
    ("GET", "/breakglass"): "breakglass.read",
    ("POST", "/studies/{rs}/patients/{pid}/mark"): "list.mark",
    ("POST", "/pilot/jobs/{job_id}/approve"): "criteria.approve",
    ("POST", "/breakglass"): "breakglass.open",
    ("GET", "/site/opt-outs"): "optout.keep",  # D-380 (ROLE-005)
    ("POST", "/site/opt-outs"): "optout.keep",
    ("GET", "/api/v1/site/opt-outs"): "optout.keep",
    ("GET", "/data/items"): "items.view",  # D-380: the steward's page, not the administrator's
}


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
