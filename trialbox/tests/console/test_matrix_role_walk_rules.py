"""Card V-2 (plan 8 activity V8): the two-person rules, break-glass and its review, forged and stale sessions.

One test per two-person rule of the box (the rules that compare two *people*; D-877 records that a step split by role
alone, such as a criteria approval, may be done by one person holding both roles on a test box):

* D-719: a protected account is opened, re-scoped or reset only when a second person with ``account.confirm``
  confirms; nobody confirms their own request;
* D-280, D-430: the steward reviews each break-glass grant; nobody reviews their own;
* D-368 (E-14): the blind re-entry result that lets prefill go on is recorded by someone other than the PI who turns
  prefill on.

Each: the same person is refused, a second person with the right role is allowed, a second person with the wrong
role is refused, and one person who holds both roles and switches the acting role in one session (D-877) is refused.
Synthetic accounts and pseudonyms only. With ``ROLE_WALK_OUT`` set the results are written for the report."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from console.breakglass_store import BreakGlassStore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tb_common.service_auth import actor_header

from tests import edc_kit as k
from tests.actor3 import SignedClient
from tests.console.test_console_app import ADMIN_PW, _done_screen, _ulid, box, login  # noqa: F401 - the fixture by name
from tests.console.test_d280_breakglass import A, B, _events, _open, _shift
from tests.console.test_no_one_holds_both_factors import (
    STEWARD_PW,
    _add,
    _box,
    _request_ids,
    _requests,
    _signin,
)
from tests.console.test_role_pages import PW, _csrf, _user
from tools import role_walk as rw

ROWS: list[dict[str, str]] = []
TEST = "tests/console/test_matrix_role_walk_rules.py"


def _row(rule: str, where: str, same: str, right: str, wrong: str, acting: str, test: str) -> None:
    ROWS.append({"rule": rule, "where": where, "same person": same, "second person, right role": right,
                 "second person, wrong role": wrong, "one person switching roles": acting, "test": test})  # fmt: skip
    rw.save_fragment("two_person", ROWS)


def _acting_on(users: Any, audit: Any) -> None:
    from tb_common.flags import Flags

    if Flags(audit=audit).get("steps.acting_role", "off") != "on":
        Flags(audit=audit).set("steps.acting_role", "on", "console:admin", "the role walk's two-person tests")
    assert users is not None


# ---------------------------------------------------------------------------------------------- D-719
@pytest.mark.usefixtures("held_dir")
def test_two_person_account_confirm(tmp_path: Path) -> None:
    app, users, _, _ = _box(tmp_path, steward=True)
    users.create("crc9", "coordinator", "crc-own-password-0009", "crc9@hospa.test")
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    assert 'data-testid="account-requested"' in _add(admin, csrf, "shadow1", "coordinator").text
    (rid,) = _request_ids(_requests(admin))
    same = admin.post("/ops/accounts/requests", data={"csrf": csrf, "request": rid, "decision": "confirm"})
    assert same.status_code == 403 and users.get("shadow1") is None
    crc, ccsrf = _signin(app, "crc9", "crc-own-password-0009")
    wrong = crc.post("/ops/accounts/requests", data={"csrf": ccsrf, "request": rid, "decision": "confirm"})
    assert wrong.status_code == 403 and users.get("shadow1") is None
    # one person, the administrator's account also holding the steward's role (D-877), switches in one session
    from tb_common.audit import AuditLog

    _acting_on(users, AuditLog(tmp_path / "audit"))
    users.grant_roles("admin", ["steward"], allowed=True)
    assert admin.post("/role", data={"csrf": csrf, "role": "steward"}, follow_redirects=False).status_code == 303
    acting = admin.post("/ops/accounts/requests", data={"csrf": csrf, "request": rid, "decision": "confirm"})
    assert acting.status_code == 403 and users.get("shadow1") is None
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    right = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    assert right.status_code == 200 and users.get("shadow1") is not None
    _row("D-719: a protected account waits for a second person", "/ops/accounts/requests",
         f"refused ({same.status_code})", f"allowed ({right.status_code})", f"refused ({wrong.status_code}, coordinator)",
         f"refused ({acting.status_code}, admin acting as steward)", f"{TEST}::test_two_person_account_confirm")  # fmt: skip


# ---------------------------------------------------------------------------------------------- D-280, D-430
def test_two_person_breakglass_review(box: dict[str, Any]) -> None:  # noqa: F811
    from tb_common.flags import Flags

    _done_screen(box["backend"], _ulid(990))
    stw = _user(box, "stw1", "steward")
    crc = _user(box, "crc1", "coordinator")
    users = box["users"]
    users.create("ops9", "admin", PW, "ops9@hospa.test")  # an administrator who also holds the steward's role
    if Flags(audit=box["audit"]).get("steps.acting_role", "off") != "on":
        Flags(audit=box["audit"]).set("steps.acting_role", "on", "console:admin", "the role walk's two-person tests")
    users.grant_roles("ops9", ["steward"], allowed=True)
    ops, ocsrf = login(box["app"], "ops9", PW)
    assert _open(ops, kind="patient", ruleset="GZQO", pid=A).status_code == 303
    store = BreakGlassStore()
    gid = max(g.id for g in store.grants() if g.username == "ops9")
    assert ops.post(f"/breakglass/{gid}/end", data={"csrf": ocsrf}, follow_redirects=False).status_code == 303
    same = ops.post(f"/breakglass/{gid}/review", data={"csrf": ocsrf}, follow_redirects=False)
    assert same.status_code == 403  # the administrator's role has no review row
    assert ops.post("/role", data={"csrf": ocsrf, "role": "steward"}, follow_redirects=False).status_code == 303
    acting = ops.post(f"/breakglass/{gid}/review", data={"csrf": ocsrf}, follow_redirects=False)
    assert acting.status_code == 303 and "err=bg.err.self" in acting.headers["location"]
    wrong = crc.post(f"/breakglass/{gid}/review", data={"csrf": _csrf(crc.get("/account").text)},
                     follow_redirects=False)  # fmt: skip
    assert wrong.status_code == 403
    assert store.get(gid).reviewed_at is None  # type: ignore[union-attr]
    right = stw.post(f"/breakglass/{gid}/review", data={"csrf": _csrf(stw.get("/breakglass").text), "note": "ok"},
                     follow_redirects=False)  # fmt: skip
    assert right.status_code == 303 and right.headers["location"] == "/breakglass?done=review"
    assert store.get(gid).reviewed_by == "stw1"  # type: ignore[union-attr]
    store.close()
    _row("D-280, D-430: the steward reviews each break-glass grant, never their own", "/breakglass/{gid}/review",
         f"refused ({same.status_code}, the grantee as administrator)", f"allowed ({right.status_code}, steward)",
         f"refused ({wrong.status_code}, coordinator)", "refused (bg.err.self, the grantee acting as steward)",
         f"{TEST}::test_two_person_breakglass_review")  # fmt: skip


# ---------------------------------------------------------------------------------------------- D-368 (E-14)
def test_two_person_edc_reentry_and_switch_on(tmp_path: Path) -> None:
    """The orchestrator's EDC routes (the person from the console's signed assertion, D-162): an administrator
    records the blind re-entry result; the PI turns prefill on; the two must be different people."""
    from orchestrator.edc_api import router

    svc, _, _ = k.service(tmp_path)
    svc.typed_reentry = lambda: False  # a PRODUCTION box: only a stored result counts
    k.ready(svc, on=False)
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = SignedClient(app)
    reentry = f"/studies/{k.STUDY}/edc/reentry"
    switch = f"/studies/{k.STUDY}/edc/switch"
    on = {"on": True, **k.ACK}
    body = {"pages": 30, "accuracy": 0.99, "document": "QA-RE-WALK-1"}
    wrong = c.post(reentry, json=body, headers=actor_header("crc7", role="coordinator"))
    assert wrong.status_code == 403
    # one person: records the result in the administrator's role, then turns prefill on as the study's PI
    assert c.post(reentry, json=body, headers=actor_header("drboth", role="admin")).status_code == 200
    same = c.post(switch, json=on, headers=actor_header("drboth", role="investigator"))
    assert same.status_code >= 400 and "reentry_same_person" in same.text
    assert c.post(reentry, json={**body, "document": "QA-RE-WALK-2"},
                  headers=actor_header("admin1", role="admin")).status_code == 200  # fmt: skip
    right = c.post(switch, json=on, headers=actor_header("drboth", role="investigator"))
    assert right.status_code == 200 and right.json()["state"] == "on"
    _row("D-368 (E-14): the re-entry result is recorded by someone other than the PI who turns prefill on",
         "orchestrator /studies/{rs}/edc/reentry, /edc/switch", f"refused ({same.status_code}, edc.reentry_same_person)",
         f"allowed ({right.status_code}, a result another administrator recorded)",
         f"refused ({wrong.status_code}, a coordinator records)",
         "refused: the same name in two roles is the same person (the store compares names)",
         f"{TEST}::test_two_person_edc_reentry_and_switch_on")  # fmt: skip


# ---------------------------------------------------------------------------------------------- break-glass
def test_breakglass_who_opens_what_for_how_long_every_use_recorded(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _ulid(990)
    _done_screen(box["backend"], jid)
    out: list[dict[str, str]] = []

    def check(
        what: str, ok: bool, test: str = "test_breakglass_who_opens_what_for_how_long_every_use_recorded"
    ) -> None:
        out.append({"check": what, "result": "holds" if ok else "FAILS", "test": f"{TEST}::{test}"})
        assert ok, what

    admin, _ = login(box["app"])
    refused = {}
    for name, role in (("crcb", "coordinator"), ("vwb", "viewer"), ("crob", "cro"), ("stwb", "steward"),
                       ("dpob", "privacy")):  # fmt: skip
        c = _user(box, name, role, **({"affiliation": "cro", "studies": "GZQO"} if role == "cro" else {}))
        refused[role] = _open(c, kind="patient", ruleset="GZQO", pid=A).status_code
    check("the roles without breakglass.open are refused a grant (coordinator, viewer, CRO, steward, privacy): "
          + ", ".join(f"{r} {s}" for r, s in refused.items()), set(refused.values()) == {403})  # fmt: skip
    r = _open(admin, kind="patient", ruleset="GZQO", pid=A)
    check("the administrator opens one grant for one patient", r.status_code == 303)
    store = BreakGlassStore()
    g = max(store.grants(), key=lambda x: x.id)
    check(
        "the grant row names the person, the reason, the note and the one patient (breakglass.grants)",
        g.username == "admin" and g.reason == "support" and g.pid == A and g.ruleset == "GZQO",
    )
    opened, ends = g.opened_at, g.ends_at
    check(
        "the grant ends 60 minutes after it opens",
        str(ends) > str(opened) and g.active(box["app"].state.helpers.clock()),
    )
    check("under the grant the named patient's page opens", admin.get(f"/studies/GZQO/patients/{A}").status_code == 200)
    check("another patient's page stays refused", admin.get(f"/studies/GZQO/patients/{B}").status_code == 403)
    check(
        "the job's list of patients stays closed",
        'data-testid="screen-rows"' not in admin.get(f"/pilot/jobs/{jid}").text,
    )
    uses = store.uses_of([g.id]).get(g.id, [])
    check(
        "each use is a row (breakglass.uses) and an audit event (console.breakglass_use)",
        len(uses) >= 1 and all(u.pid == A for u in uses) and len(_events(box, "console.breakglass_use")) == len(uses),
    )
    stw = _user(box, "stwr", "steward")
    page = stw.get("/breakglass").text
    check("the steward's review list shows the grant", f'data-grant="{g.id}"' in page)
    _shift(box, 61)
    check(
        "after 60 minutes the patient's page is refused again",
        admin.get(f"/studies/GZQO/patients/{A}").status_code == 403,
    )
    check("an ended grant writes no new use", len(store.uses_of([g.id]).get(g.id, [])) == len(uses))
    store.close()
    rw.save_fragment("breakglass", out)


# ---------------------------------------------------------------------------------------------- forged and stale
def test_forged_and_stale_console_sessions_are_refused(box: dict[str, Any]) -> None:  # noqa: F811
    """A sample of each kind on a page and on ``/api/v1``. The console's session is a random token whose hash is
    the row (no signature: a forged or tampered token is simply no session)."""
    users = box["users"]
    app = box["app"]
    out: list[dict[str, str]] = []
    count = {"n": 0}
    orig = box["audit"].append

    def append(*a: Any, **kw: Any) -> Any:
        count["n"] += 1
        return orig(*a, **kw)

    box["audit"].append = append

    def probe(kind: str, client: TestClient, path: str, refused: set[int], note: str = "") -> None:
        n = count["n"]
        r = client.get(path, follow_redirects=False)
        loc = r.headers.get("location", "")
        ok = r.status_code in refused and (r.status_code != 303 or loc.split("?")[0].endswith("/login"))
        out.append({"service": "console", "kind": kind, "route": f"GET {path}", "status": str(r.status_code),
                    "refused": "yes" if ok else "NO", "audited": "yes" if count["n"] > n else "no", "note": note})  # fmt: skip

    page = "/studies/GZQO/team"
    api = "/api/v1/studies/GZQO/delegation"
    probe("a made-up cookie", TestClient(app, cookies={"tb_console": "x" * 43}), page, {303})
    probe("a made-up bearer token", TestClient(app, headers={"Authorization": f"Bearer {'y' * 43}"}), api, {401})
    users.create("crcs", "coordinator", PW, "crcs@hospa.test")
    c, csrf = login(app, "crcs", PW)
    tok, _ = users.new_session(users.get("crcs"), via="api")
    probe("a bearer token sent as the page's cookie", TestClient(app, cookies={"tb_console": tok}), page, {303})
    c.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    probe("a session replayed after sign-out", c, page, {303})
    c, _ = login(app, "crcs", PW)
    users.db.execute("UPDATE users SET role = 'viewer' WHERE username = 'crcs'")
    probe("a session whose account's role was changed after sign-in (coordinator to viewer)", c, page, {403},
          "the next request reads the role from the account")  # fmt: skip
    users.db.execute("UPDATE users SET role = 'coordinator' WHERE username = 'crcs'")
    api_c = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    users.disable("crcs")
    probe("a session of a disabled account", c, page, {303})
    probe("a bearer token of a disabled account", api_c, api, {401})
    users.enable("crcs")
    c, _ = login(app, "crcs", PW)
    clock = users.clock
    users.clock = lambda: clock() + timedelta(hours=13)
    probe("a session past its idle and absolute limits", c, page, {303})
    users.clock = clock
    c, _ = login(app, "crcs", PW)
    users.db.execute("DELETE FROM users WHERE username = 'crcs'")  # the row gone, the session row left behind
    probe("a session of an account that no longer exists", c, page, {303})
    box["audit"].append = orig
    rw.save_fragment("forged_console", out)
    assert [o for o in out if o["refused"] != "yes"] == []
