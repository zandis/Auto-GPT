"""Card V-2 (plan 8 activity V8): each role may do exactly what the matrix says, walked on the console's app.

The walk (``tools/role_walk.py``) calls every console route as every column (the seven roles, signed out, in- and
out-of-scope accounts, the PI, a sub-investigator, a monitor grant) and compares each answer with ``permit``. The
gate of each route is read from the running app (the actions it asks ``permit``), not from the matrix file.

This file holds the box to the walk: no answer against the matrix but the ones a finding names (each with its own
strict xfail test below), and no route without a gate but the pinned open ones, so a new route cannot go unwalked.
With ``TB_ROLE_WALK_OUT`` set (``python -m tools.role_walk inproc``) the results are written for the report."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    VIEWER_PW,
    _done_feas,
    _done_screen,
    _ulid,
    box,
    login,
)
from tests.console.test_role_route_matrix import ROUTE_ACTIONS, _for, _orchestrator_routes
from tools import role_walk as rw

PW = "role-walk-password-0001"


def _audit_counter(b: dict[str, Any]) -> Any:
    """Counts the audit events the console writes (its ``AuditLog`` object), for "is this refusal recorded"."""
    audit = b["audit"]
    n = {"events": 0}
    orig = audit.append

    def append(*a: Any, **kw: Any) -> Any:
        n["events"] += 1
        return orig(*a, **kw)

    audit.append = append
    return lambda: n["events"]


def clients(b: dict[str, Any]) -> dict[str, tuple[TestClient, str, TestClient]]:
    """One page client (cookie, CSRF token) and one API client (bearer token) per column; the GZQO log names ``pi``
    as PI, ``sub`` as a sub-investigator ticked :data:`tools.role_walk.SUB_TICKS`, and ``cro_mon`` a monitor."""
    from console.teamstore import TeamStore

    users = b["users"]
    out: dict[str, tuple[TestClient, str, TestClient]] = {}
    for col in rw.COLUMNS:
        if col.role is None:
            out[col.name] = (TestClient(b["app"]), "", TestClient(b["app"]))
            continue
        name = {"admin": "admin", "viewer": "viewer"}.get(col.name, f"w{col.name.replace('_', '')}")
        pw = {"admin": ADMIN_PW, "viewer": VIEWER_PW}.get(col.name, PW)
        if users.get(name) is None:
            users.create(name, col.role, pw, f"{name}@hospa.test")
        if col.affiliation != "hospital" or col.studies:
            users.set_scope(name, col.affiliation, col.studies, None)
        page, csrf = login(b["app"], name, pw)
        token, _ = users.new_session(users.get(name), via="api")
        out[col.name] = (page, csrf, TestClient(b["app"], headers={"Authorization": f"Bearer {token}"}))
    team = TeamStore()
    at = "2026-01-01T00:00:00+00:00"
    team.add_entry(rw.STUDY, username="wpi", name="Dr Walk PI", role="pi", tasks=(), start="2026-01-01", end=None,
                   training_day="2026-01-01", training_ref=None, by="stw", at=at)  # fmt: skip
    team.add_entry(rw.STUDY, username="wsub", name="Dr Walk Sub", role="sub_pi", tasks=list(rw.SUB_TICKS),
                   start="2026-01-01", end=None, training_day="2026-01-01", training_ref=None, by="wpi", at=at)  # fmt: skip
    team.add_entry(rw.STUDY, username="wcromon", name="CRA Walk", role="monitor", tasks=(), start="2026-01-01",
                   end=None, training_day=None, training_ref="MV-WALK-1", by="wpi", at=at)  # fmt: skip
    team.close()
    return out


def faithful_reads(b: dict[str, Any]) -> None:
    """The test box's stand-in backend reads the registry without the layer the real one has: ``console.backend``
    signs every patient read (``_registry_call`` -> ``console.actor.read_headers``, D-717), which asks the matrix's
    ``phi.view`` of the signed-in account and refuses (403, ``console.denied``) before the orchestrator is called.
    The walk puts that layer back on the stand-in's registry reads, so the page answers as on a box."""
    from console.actor import read_headers

    bk = b["backend"]
    rows = bk.registry_rows

    def signed_rows(ruleset: str) -> Any:
        read_headers("GET", f"/registry/{ruleset}")
        return rows(ruleset)

    bk.registry_rows = signed_rows


def run_walk(b: dict[str, Any]) -> list[dict[str, Any]]:
    _orchestrator_routes(b)
    faithful_reads(b)
    _done_feas(b["backend"])
    job_id = _ulid(990)
    _done_screen(b["backend"], job_id)
    count = _audit_counter(b)
    cl = clients(b)
    tracer = rw.Tracer()
    tracer.install()
    try:
        raw = rw.console_walk(b["app"], cl, tracer, count, job_id, before=lambda p: _for(b, p))
    finally:
        tracer.uninstall()
        _for(b, "")
    return rw.judge(raw, ROUTE_ACTIONS)


def _mismatches(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], str]:
    return {(r["method"], r["path"], n): c["verdict"] for r in rows for n, c in r["cells"].items()
            if c["verdict"].startswith(("ALLOWED-", "REFUSED-"))}  # fmt: skip


#: the routes that ask no row of the matrix: open to every signed-in account (and, for the PUBLIC ones of
#: ``tools.role_walk``, to anyone). The product has no marking for "any signed-in person", so this list is the
#: marking: a new route that asks no row fails the walk until it asks one or is added here with its reason.
OPEN_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/"): "the start page: sends each account to its own first page",
    ("GET", "/home"): "the start page of the account's role",
    ("GET", "/account"): "one's own account and password",
    ("POST", "/account/password"): "one's own password",
    ("GET", "/about"): "the licence notices (T-617a)",
    ("GET", "/about/NOTICE.txt"): "the licence notices (T-617a)",
    ("GET", "/help"): "the help pages",
    ("GET", "/help/guide"): "one's own role guide (T-317, D-774)",
    ("GET", "/ask"): "the help page's question box; the answer is drawn for the account's own rights",
    ("GET", "/cmd"): "the command line of the console: each command asks its own row when run",
    ("GET", "/reports"): "the reports list; each report asks its own row",
    ("POST", "/feedback"): "a note to the box's keepers",
    ("GET", "/api/v1/studies"): "the studies the account sees (scoped by D-104)",
    ("GET", "/studies/{rs}/feasibility"): "a feasibility report: aggregate counts, small cells hidden (D-104)",
    ("GET", "/api/edc/health"): "the EDC door's health: a version number",
    # answered 404 for every column on the test box (the feature is off there): not decided, listed as unclear
    ("GET", "/api/edc/oidc/.well-known/openid-configuration"): "the EDC door's sign-on: off on the test box",
    ("GET", "/api/edc/oidc/authorize"): "the EDC door's sign-on: off on the test box",
    ("GET", "/api/edc/oidc/userinfo"): "the EDC door's sign-on: off on the test box",
    ("POST", "/api/edc/oidc/token"): "the EDC door's sign-on: off on the test box",
    ("POST", "/api/edc/events/v1"): "the EDC's signed events: off on the test box (a shared secret, no person)",
    ("GET", "/auth/oidc/start"): "directory sign-in: off on the test box",
    ("GET", "/auth/oidc/callback"): "directory sign-in: off on the test box",
    ("GET", "/demo/ack"): "the demo's notice: off outside the demo",
    ("POST", "/demo/ack"): "the demo's notice: off outside the demo",
}


@pytest.fixture
def walked(box: dict[str, Any]) -> list[dict[str, Any]]:  # noqa: F811
    rows = run_walk(box)
    rw.save_fragment("console", {"routes": rows})
    return rows


def test_every_console_route_answers_every_column_as_the_matrix_says(walked: list[dict[str, Any]]) -> None:
    """The whole walk: no answer against the matrix (both ways), every route either names a gate or is pinned
    open, and the gate agrees with the row ``test_role_route_matrix`` names by hand where it names one."""
    rows = walked
    assert len(rows) > 300  # the walk reached the router table
    bad = _mismatches(rows)
    assert not bad, "answers against the matrix:\n" + "\n".join(f"{k}: {v}" for k, v in sorted(bad.items()))
    open_now = {(r["method"], r["path"]) for r in rows if r["gate"] is not None and not r["gate"]["actions"]}
    assert open_now - set(OPEN_ROUTES) == set(), "a route asks no row of the matrix: give it one, or pin it here"
    assert set(OPEN_ROUTES) - open_now == set(), "a pinned open route now asks a row: take it off the list"
    gates = {(r["method"], r["path"]): r["gate_label"] for r in rows if r["gate"] is not None}
    differ = {k: (v, gates.get(k)) for k, v in ROUTE_ACTIONS.items() if gates.get(k) not in (v, None)}
    # two of the hand-named rows coincide with the delegation log's standing on every column, so the walk cannot
    # tell them apart (the reveal also needs the study's ``screen`` task; the mark the log's ``approach``)
    assert set(differ) <= {
        ("POST", "/studies/{rs}/patients/{pid}/reveal"),
        ("POST", "/studies/{rs}/patients/{pid}/mark"),
    }
    walked_routes = {(r["method"], r["path"]) for r in rows if r["walked"]}
    assert walked_routes >= set(ROUTE_ACTIONS)
    # the data half: a column whose role reads no patient row (phi.view) sees none of the seeded pseudonyms on any
    # page or API answer it opens, but the rows that show pseudonyms by their own right (the audit trail's ids)
    from tb_common.authz import permit

    leaks = [f"{r['method']} {r['path']} as {n}: {c['shows']}" for r in rows for n, c in r["cells"].items()
             if c["shows"] and not (rw.BY_NAME[n].role and permit(str(rw.BY_NAME[n].role), "phi.view").allowed)
             and not (r["path"].startswith("/audit") and permit(str(rw.BY_NAME[n].role), "audit.ids").allowed)]  # fmt: skip
    assert not leaks, "a pseudonym on a page of a role with no patient row:\n" + "\n".join(leaks)


#: V2-02: the refusals that write no ``console.denied`` record (see the page). Each route here refuses the listed
#: columns with 403 and nothing in the audit trail, while its siblings record theirs (D-483 2.; D-451, D-443, ...).
UNAUDITED: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/studies/{rs}/patients/{pid}"): ("admin", "steward", "privacy"),
    ("GET", "/studies/{rs}/week"): ("admin", "steward", "privacy"),
    ("GET", "/week"): ("viewer",),
    ("GET", "/ops/users"): ("crc", "steward"),
    ("GET", "/ops/identity"): ("crc", "steward"),
    ("GET", "/reports/research-office"): ("pi", "steward"),
    ("GET", "/pilot/jobs/{job_id}/sponsor-pack.zip"): ("pi", "steward"),
    ("POST", "/admin/redcap/{ref}/test"): ("crc", "steward"),
    ("POST", "/studies/{rs}/setup/redcap/test"): ("pi",),
}


@pytest.mark.xfail(strict=True, reason="V2-02: refusals on nine routes write no console.denied record")
def test_v2_02_every_refusal_of_these_routes_is_in_the_audit_trail(box: dict[str, Any]) -> None:  # noqa: F811
    _done_feas(box["backend"])
    job_id = _ulid(990)
    _done_screen(box["backend"], job_id)
    count = _audit_counter(box)
    cl = clients(box)
    silent = []
    for (method, path), cols in UNAUDITED.items():
        for name in cols:
            page, csrf, _ = cl[name]
            n = count()
            r = page.request(method, rw.fill(path, job_id), data={"csrf": csrf} if method == "POST" else None,
                             follow_redirects=False)  # fmt: skip
            assert r.status_code == 403, (path, name, r.status_code)
            if count() == n:
                silent.append(f"{method} {path} as {name}")
    assert not silent, "refused with no audit record: " + "; ".join(silent)


def test_the_walk_tells_a_refusal_from_a_validation_answer() -> None:
    """The rules of ``tools.role_walk`` on made-up cells (no box): a 400 counts as allowed only when the gate was
    asked in that request and said yes; a 5xx is never a pass; a 404 refuses only a column that does not see the
    study."""
    crc, smo_out = rw.BY_NAME["crc"], rw.BY_NAME["smo_out"]
    gate = rw.Gate(("study.setup",))
    assert rw.classify(crc, "/studies/{rs}/x", 403, "") == "R"
    assert rw.classify(crc, "/x", 303, "/login?why=idle") == "R"
    assert rw.classify(smo_out, "/studies/{rs}/x", 404, "") == "R"
    assert rw.classify(crc, "/studies/{rs}/x", 404, "") == "N"
    assert rw.final(crc, {"class": "V", "asked": [("study.setup", True, "x")]}, gate) == "A"
    assert rw.final(crc, {"class": "V", "asked": [("study.setup", False, "x")]}, gate) == "R"
    assert rw.final(crc, {"class": "V", "asked": []}, gate) == "?"
    assert rw.final(crc, {"class": "U", "asked": [("study.setup", True, "x")]}, gate) == "?"
    assert (
        rw.verdict(False, "A") == "ALLOWED-BUT-MATRIX-REFUSES" and rw.verdict(True, "R") == "REFUSED-BUT-MATRIX-ALLOWS"
    )
    assert rw.expected(rw.BY_NAME["anon"], "/about", rw.Gate(())) and not rw.expected(
        rw.BY_NAME["anon"], "/x", rw.Gate(())
    )
    assert not rw.expected(smo_out, "/studies/{rs}/x", rw.Gate(()))  # scope before the row
    assert rw.expected(rw.BY_NAME["pi"], "/x", rw.Gate(("study.reopen",)))  # the log's PI: the [pi] cell
    assert not rw.expected(rw.BY_NAME["inv"], "/x", rw.Gate(("study.reopen",)))
    assert not rw.expected(rw.BY_NAME["smo_in"], "/x", rw.Gate(("irb.edit",)))  # "hospital staff only"
