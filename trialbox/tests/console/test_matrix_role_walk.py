"""Card V-2 (plan 8 activity V8): each role may do exactly what the matrix says, walked on the console's app.

The walk (``tools/role_walk.py``) calls every console route as every column (the seven roles, signed out, in- and
out-of-scope accounts, the PI, a sub-investigator, a monitor grant). What each route must answer is the committed
table ``tests/console/data/route_actions.yaml`` (one row per route: the matrix action(s) it must ask, or public,
signed_in or scope, each with the document that says so); the walk never infers it from the route's behaviour.
An answer counts as allowed only when the route answered with success (2xx, a redirect onward), as refused on 401,
403, a redirect to sign-in, or a 404 for an account that does not see the study; anything else is "check not
reached" and is pinned by route and column in ``tests/console/data/role_walk_unclear.txt``.

The tests fail on: a route with no row (or a row with no route); an answer against its row that no finding names;
an unclear cell not pinned (or a pinned one that is now decided); a seeded pseudonym on a page of a role with no
patient row. Each finding has its own strict xfail test. ``ROLE_WALK_OUT`` (``python -m tools.role_walk inproc``)
writes the results for the report; ``ROLE_WALK_DRAFT=<file>`` writes a draft of the table from a traced walk."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
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
)
from tests.console.test_role_route_matrix import ROUTE_ACTIONS
from tools import role_walk as rw

PW = "role-walk-password-0001"
UNCLEAR = Path(__file__).parent / "data" / "role_walk_unclear.txt"
A = "a" * 32


class RoleWalkFinding(AssertionError):
    """Raised only by the check a strict xfail names: a fixture error can never satisfy the mark."""


def tagged_login(app: Any, user: str, pw: str) -> tuple[TestClient, str]:
    c = TestClient(rw.Tagged(app))
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    r = c.post("/login", data={"username": user, "password": pw, "login_csrf": token.group(1)}, follow_redirects=False)
    assert r.status_code == 303, r.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
    assert csrf
    return c, csrf.group(1)


def clients(b: dict[str, Any]) -> dict[str, tuple[TestClient, str, TestClient]]:
    """One page client (cookie, CSRF token) and one API client (bearer token) per column, both on
    :class:`tools.role_walk.Tagged`; the GZQO log names ``pi`` as PI, ``sub`` a sub-investigator ticked
    :data:`tools.role_walk.SUB_TICKS`, and ``cro_mon`` a monitor."""
    from console.teamstore import TeamStore

    users = b["users"]
    out: dict[str, tuple[TestClient, str, TestClient]] = {}
    for col in rw.COLUMNS:
        if col.role is None:
            out[col.name] = (TestClient(rw.Tagged(b["app"])), "", TestClient(rw.Tagged(b["app"])))
            continue
        name = {"admin": "admin", "viewer": "viewer"}.get(col.name, f"w{col.name.replace('_', '')}")
        pw = {"admin": ADMIN_PW, "viewer": VIEWER_PW}.get(col.name, PW)
        if users.get(name) is None:
            users.create(name, col.role, pw, f"{name}@hospa.test")
        if col.affiliation != "hospital" or col.studies:
            users.set_scope(name, col.affiliation, col.studies, None)
        page, csrf = tagged_login(b["app"], name, pw)
        token, _ = users.new_session(users.get(name), via="api")
        out[col.name] = (page, csrf, TestClient(rw.Tagged(b["app"]), headers={"Authorization": f"Bearer {token}"}))
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
    signs every patient read (``_registry_call`` -> ``console.actor.read_headers``, D-717), which asks ``phi.view``
    of the signed-in account and refuses (403, ``console.denied``) before the orchestrator is called. The walk puts
    that layer back on the stand-in's registry reads, so the page answers as on a box (V2-04)."""
    from console.actor import read_headers

    bk = b["backend"]
    rows = bk.registry_rows

    def signed_rows(ruleset: str) -> Any:
        read_headers("GET", f"/registry/{ruleset}")
        return rows(ruleset)

    bk.registry_rows = signed_rows


def study_store(b: dict[str, Any], tmp_path: Path) -> Iterator[None]:
    """A study store in process: the orchestrator's data core, life-cycle, sponsor, EDC, clinical-conflict and
    instrument routers behind ``backend.study_api`` (as ``test_data_pages`` and ``test_edc_pages`` wire it), called
    through a strict signed client: the console signs every call itself, as on a box."""
    from types import SimpleNamespace

    from console.backend import problem_of
    from fastapi import FastAPI
    from omop import schema
    from orchestrator.conflicts_api import router as conflicts_router
    from orchestrator.datacore_api import DataService
    from orchestrator.datacore_api import router as datacore_router
    from orchestrator.edc_api import router as edc_router
    from orchestrator.lifecycle_api import router as lifecycle_router
    from orchestrator.setup_api import router as setup_router
    from orchestrator.sponsor_api import router as sponsor_router
    from sitesetup.store import SetupStore
    from tb_common.audit import AuditLog

    from tests import edc_kit as k
    from tests.actor3 import SignedClient

    edc, _, _ = k.service(tmp_path)
    dsvc = DataService(edc.dc, AuditLog(tmp_path / "orch-audit"), lambda: datetime(2026, 11, 8, 1, 0, tzinfo=UTC),
                       edc.client)  # fmt: skip
    held: dict[str, Any] = {}

    def omop() -> Any:
        if "db" not in held:
            held["db"] = schema.connect()
        return held["db"]

    site: Any = SimpleNamespace(store=SetupStore(), stamp=lambda: "2026-11-16T09:00:00+00:00",
                           audit=AuditLog(tmp_path / "orch-audit"))  # fmt: skip
    api = FastAPI()
    for r in (datacore_router(lambda: dsvc), lifecycle_router(lambda: dsvc), sponsor_router(lambda: dsvc),
              edc_router(lambda: edc), conflicts_router(omop),
              setup_router(lambda: site, lambda rid: {}, lambda rid: {}, lambda rid: None, lambda: False,
                           lambda *a: None)):  # fmt: skip
        api.include_router(r)
    coc = SignedClient(api, strict=True, raise_server_exceptions=False)  # a route this stand-in cannot serve: 500

    def study_api(method: str, path: str, body: dict[str, Any] | None = None,
                  headers: dict[str, str] | None = None) -> Any:  # fmt: skip
        if path == "/redcap/connections":
            return {"connections": [{"token_ref": "edc"}]}
        kw: dict[str, Any] = {"headers": headers} if headers else {}
        r = coc.request(method, path, json=body, **kw) if body is not None else coc.request(method, path, **kw)
        if r.status_code >= 400:
            raise problem_of(r.status_code, r.text)
        return r.json()

    b["backend"].study_api = study_api
    yield
    edc.dc.close()


# ---------------------------------------------------------------------------------------------- valid bodies
def preparer(b: dict[str, Any], job_id: str) -> rw.Prepare:
    """A valid body and fresh state per call, for the changing routes that matter most (plan 8 V8's list): an
    allowed column gets past validation and succeeds, a refused one is refused. The rest send the CSRF token."""
    from console.breakglass_store import BreakGlassStore
    from datacore.dataops import DataOps
    from tb_common.audit import AuditLog

    n = {"i": 0}
    declared = rw.load_declared()

    def fresh() -> str:
        n["i"] += 1
        return f"{n['i']:032x}".replace("0", "c")

    def night() -> int:
        ops = DataOps()
        try:
            batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.held", source="csv",
                                        snapshot=f"2026-10-{1 + n['i'] % 28:02d}", passed=False, held=True,
                                        by="adapter", at="2026-11-11T02:00:00+09:00", actor="adapter",
                                        detail={"incomplete": ["lab: missing"]})  # fmt: skip
            n["i"] += 1
            return int(batch.id)
        finally:
            ops.close()

    def ended_grant() -> int:
        store = BreakGlassStore()
        try:
            now = b["app"].state.helpers.clock()
            g, _ = store.open("walk-grantee", reason="support", note="a support call for the walk", kind="patient",
                              ruleset=rw.STUDY, pid=A, now=now)  # fmt: skip
            store.end(g.id, "walk-grantee", now)
            return int(g.id)
        finally:
            store.close()

    def throwaway() -> str:
        name = f"wthrow{n['i']}"
        n["i"] += 1
        b["users"].create(name, "viewer", PW, None)
        return name

    def prepare(method: str, path: str, col: str) -> dict[str, Any] | None:
        reveal = {"reason": "contact"}
        table: dict[tuple[str, str], Any] = {
            ("POST", "/data-ops/batches/{bid}/decide"): lambda: {"params": {"bid": night()},
                                                               "form": {"decision": "reject", "reason": "role walk"}},
            ("POST", "/api/v1/data/batches/{bid}/decide"): lambda: {"params": {"bid": night()},
                                                                  "json": {"decision": "reject", "reason": "role walk"}},
            ("POST", "/breakglass"): lambda: {"form": {"kind": "patient", "ruleset": rw.STUDY, "pid": A,
                                                       "reason": "support", "note": "a support call for the walk"}},
            ("POST", "/breakglass/{gid}/review"): lambda: {"params": {"gid": ended_grant()}, "form": {"note": "ok"}},
            ("POST", "/site/opt-outs"): lambda: {"form": {"pid": fresh(), "source": "paper"}},
            ("POST", "/api/v1/site/opt-outs"): lambda: {"json": {"pid": fresh()}},
            ("POST", "/studies/{rs}/patients/{pid}/reveal"): lambda: {"form": reveal},
            ("POST", "/studies/{rs}/candidates/{pid}/reveal"): lambda: {"form": {"purpose": "eligibility", **reveal}},
            ("POST", "/pilot/jobs/{job_id}/reveal"): lambda: {"form": {"pid": A, **reveal}},
            ("POST", "/studies/{rs}/patients/{pid}/mark"): lambda: {"form": {"mark": "need_info"}},
            ("POST", "/ops/users"): lambda: {"form": {"action": "disable", "username": throwaway()}},
            ("POST", "/api/v1/studies/{rs}/patients/{pid}/reveal"): lambda: {"json": reveal},
            ("POST", "/api/v1/studies/{rs}/patients/{pid}/mark"): lambda: {"json": {"mark": "need_info"}},
        }  # fmt: skip
        make = table.get((method, path))
        if make is None:
            return None
        # a refused column is also probed with no body first: its refusal must come before validation
        # (dataops_page.py: "the session and the right first; the body only then")
        probe = not rw.expected_of(rw.BY_NAME[col], method, path, declared[(method, path)])
        if not path.startswith("/breakglass"):
            no_grants()  # a grant an earlier call opened would open the patient (D-430): every call starts without
        return {**make(), "probe": probe}

    def no_grants() -> None:
        store = BreakGlassStore()
        try:
            store.db.execute("UPDATE grants SET ended_at = ? WHERE ended_at IS NULL",
                             (b["app"].state.helpers.clock().isoformat(),))  # fmt: skip
        finally:
            store.close()

    return prepare


#: the changing routes the walk sends a valid body (``preparer``): every other changing route sends its CSRF token
#: only, so an allowed column stops at validation and the cell is unclear (pinned)
PREPARED = (  # a valid body to the columns its row allows; the refused columns send the CSRF token only
    "POST /data-ops/batches/{bid}/decide", "POST /api/v1/data/batches/{bid}/decide", "POST /breakglass",
    "POST /breakglass/{gid}/review", "POST /site/opt-outs", "POST /api/v1/site/opt-outs",
    "POST /studies/{rs}/patients/{pid}/reveal", "POST /studies/{rs}/candidates/{pid}/reveal",
    "POST /pilot/jobs/{job_id}/reveal", "POST /studies/{rs}/patients/{pid}/mark", "POST /ops/users",
    "POST /api/v1/studies/{rs}/patients/{pid}/reveal", "POST /api/v1/studies/{rs}/patients/{pid}/mark",
)  # fmt: skip


def run_walk(b: dict[str, Any], tmp_path: Path, tracer: rw.Tracer | None = None) -> list[dict[str, Any]]:
    from tests.console.dataops_orch import attach

    attach(b["backend"], b["audit"])
    faithful_reads(b)
    _done_feas(b["backend"])
    job_id = _ulid(990)
    _done_screen(b["backend"], job_id)
    tap = rw.AuditTap(b["audit"])
    calls = rw.BackendTap()
    store = study_store(b, tmp_path)
    next(store)
    cl = clients(b)
    if tracer:
        tracer.install()
    try:
        return rw.console_walk(b["app"], cl, tap, job_id, preparer(b, job_id), tracer, calls)
    finally:
        if tracer:
            tracer.uninstall()
        tap.close()
        calls.close()
        next(store, None)


def pinned_unclear() -> set[str]:
    return {ln.strip() for ln in UNCLEAR.read_text("utf-8").splitlines() if ln.strip() and not ln.startswith("#")}


def unclear_now(rows: list[dict[str, Any]]) -> set[str]:
    return {f"{r['method']} {r['path']} {n}" for r in rows for n, c in r["cells"].items() if c["verdict"] == "unclear"}


#: refused cells the console let through to the orchestrator, which refused them: "<method> <path> <column>"
BACKEND_REFUSED: set[str] = set()
#: prepared routes that read the body before they refuse a column: "<method> <path> <column>: <status>"
#: (the two reveal pages ask the purpose or the reason before the one reveal path asks the role: team.py
#: candidate_reveal, app.py job reveal; the role is still refused with a valid body)
VALIDATES_FIRST: set[str] = {
    "POST /pilot/jobs/{job_id}/reveal admin: 400", "POST /pilot/jobs/{job_id}/reveal inv: 400",
    "POST /studies/{rs}/candidates/{pid}/reveal admin: 400", "POST /studies/{rs}/candidates/{pid}/reveal inv: 400",
    "POST /studies/{rs}/candidates/{pid}/reveal privacy: 400",
    "POST /studies/{rs}/candidates/{pid}/reveal steward: 400",
}  # fmt: skip


#: answers against the declared row that a finding names: (method, path, column) -> finding id
KNOWN: dict[tuple[str, str, str], str] = {
    ("GET", "/api/v1/studies/{rs}/edc/copy", "pi"): "V2-05",
    ("GET", "/api/v1/studies/{rs}/edc/export/odm", "pi"): "V2-05",
    ("POST", "/api/v1/studies/{rs}/edc/send", "pi"): "V2-05",
}


@pytest.fixture
def walked(box: dict[str, Any], tmp_path: Path) -> list[dict[str, Any]]:  # noqa: F811
    draft = os.environ.get("ROLE_WALK_DRAFT")
    raw = run_walk(box, tmp_path, rw.Tracer() if draft else None)
    if draft:
        Path(draft).write_text(rw.draft_table(raw, ROUTE_ACTIONS), "utf-8")
    rows = rw.judge_declared(raw, rw.load_declared())
    rw.save_fragment("console", {"routes": rows, "prepared": list(PREPARED)})
    return rows


def test_every_console_route_answers_every_column_as_its_declared_row(walked: list[dict[str, Any]]) -> None:
    from tb_common.authz import permit

    rows = walked
    assert len(rows) > 300  # the walk reached the router table
    problems = rw.table_problems(rows, rw.load_declared())
    assert not problems, "\n".join(problems)
    bad = {(r["method"], r["path"], n): c["verdict"] for r in rows for n, c in r["cells"].items()
           if c["verdict"] in (rw.ALLOWED_X, rw.REFUSED_X) and (r["method"], r["path"], n) not in KNOWN}  # fmt: skip
    assert not bad, "answers against the declared row:\n" + "\n".join(f"{k}: {v}" for k, v in sorted(bad.items()))
    now, pinned = unclear_now(rows), pinned_unclear()
    assert not now - pinned, "unclear cells not pinned:\n" + "\n".join(sorted(now - pinned))
    assert not pinned - now, "pinned unclear cells now decided (take them off the list):\n" + "\n".join(
        sorted(pinned - now)
    )
    # the data half: a column whose role reads no patient row (phi.view) sees none of the seeded pseudonyms, but
    # the rows that show pseudonyms by their own right (the audit trail's ids)
    leaks = [f"{r['method']} {r['path']} as {n}: {c['shows']}" for r in rows for n, c in r["cells"].items()
             if c["shows"] and not (rw.BY_NAME[n].role and permit(str(rw.BY_NAME[n].role), "phi.view").allowed)
             and not (r["path"].startswith("/audit") and permit(str(rw.BY_NAME[n].role), "audit.ids").allowed)]  # fmt: skip
    assert not leaks, "a pseudonym on a page of a role with no patient row:\n" + "\n".join(leaks)
    # D-483: the console refuses what the matrix refuses before it calls the orchestrator ("it cannot sign what it
    # would not allow"); a refused cell whose request reached a stand-in was refused by the backend, not the console
    late = {f"{r['method']} {r['path']} {n}" for r in rows for n, c in r["cells"].items()
            if c["got"] == "R" and c["expected"] == "R" and c["backend"]}  # fmt: skip
    assert late <= BACKEND_REFUSED, "refused only by the backend:\n" + "\n".join(sorted(late - BACKEND_REFUSED))
    assert late >= BACKEND_REFUSED, "now refused by the console: take off the list\n" + "\n".join(
        sorted(BACKEND_REFUSED - late)
    )
    # the right first, the body only then: a refused column probed with no body is refused, not told what is wrong
    first = {f"{r['method']} {r['path']} {n}: {c['probe']}" for r in rows for n, c in r["cells"].items()
             if c["probe"] not in (None, "refused")}  # fmt: skip
    assert first == VALIDATES_FIRST, "a refused column got past the check to validation:\n" + "\n".join(
        sorted(first ^ VALIDATES_FIRST)
    )
    # every prepared route got past validation for at least one allowed column
    for key in PREPARED:
        m, p = key.split(" ", 1)
        row = next(r for r in rows if r["method"] == m and r["path"] == p)
        assert any(c["got"] == "A" for c in row["cells"].values()), (
            key,
            {n: c["status"] for n, c in row["cells"].items()},
        )


def test_a_new_route_with_no_row_fails_the_walk(box: dict[str, Any]) -> None:  # noqa: F811
    """The tripwire: a route the table does not name is reported (the walk's test fails on it)."""

    def extra(rs: str) -> dict[str, str]:
        return {"rs": rs}

    box["app"].add_api_route("/walk-extra/{rs}", extra, methods=["GET"])

    problems = rw.table_problems(rw.console_routes(box["app"]), rw.load_declared())
    assert problems == ["GET /walk-extra/{rs}: a route with no row in route_actions.yaml"]


#: V2-02: refusals that write no ``console.denied`` record (see the page): route -> the columns refused silently
UNAUDITED: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/studies/{rs}/patients/{pid}"): ("admin", "steward", "privacy"),
    ("GET", "/studies/{rs}/week"): ("admin", "steward", "privacy"),
    ("GET", "/week"): ("viewer",),
    ("GET", "/ops/users"): ("crc", "steward"),
    ("GET", "/ops/identity"): ("crc", "steward"),
    ("GET", "/reports/research-office"): ("pi", "steward"),
    ("GET", "/pilot/jobs/{job_id}/sponsor-pack.zip"): ("pi", "steward"),
}


@pytest.mark.xfail(strict=True, raises=RoleWalkFinding, reason="V2-02: refusals on these routes write no record")
def test_v2_02_every_refusal_of_these_routes_is_in_the_audit_trail(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(990))
    users = box["users"]
    tap = rw.AuditTap(box["audit"])
    silent = []
    for (method, path), cols in UNAUDITED.items():
        for name in cols:
            col = rw.BY_NAME[name]
            user = "admin" if name == "admin" else f"wu{name}"
            if users.get(user) is None:
                users.create(user, str(col.role), PW, f"{user}@hospa.test")
            page, _ = tagged_login(box["app"], user, ADMIN_PW if name == "admin" else PW)
            tag = f"{method} {path} {name}"
            r = page.request(method, rw.fill(path, _ulid(990)), headers={rw.TAG_HEADER: tag}, follow_redirects=False)
            assert r.status_code == 403, (path, name, r.status_code)
            if not tap.by_tag.get(tag):
                silent.append(f"{method} {path} as {name}")
    tap.close()
    if silent:
        raise RoleWalkFinding("refused with no audit record: " + "; ".join(silent))
