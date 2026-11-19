"""Card V-8 (b) and (c): every changing route writes an audit event that says who, what, when and which record, and
no audit row holds a name, a chart number or identifying free text.

The routes come from the live app objects (``tools.audit_trail_check.changing_routes``), never a hand list. A small
walker (the idea of card V-2's ``tools/role_walk.py``, written again here) calls the routes it can bring to success
on the console's test box, as a role the route admits, with a valid body, and reads every audit line that request
wrote, in every audit folder under the box. ``AUDIT_TRAIL_OUT=<folder>`` writes ``routes.json`` for the page.

All values are synthetic. The identifying-shaped ones are built at run time, so the source holds none."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console.test_console_app import ADMIN_PW, _done_screen, _ulid, box  # noqa: F401 - the fixture by name
from tools import audit_trail_check as atc

A = "a" * 32
PW = "audit-trail-password-01"
#: the columns the walk signs in as: role, and an entry in GZQO's delegation log
ACCOUNTS = {"admin": ("admin", ""), "crc": ("coordinator", ""), "pi": ("investigator", "pi"),
            "steward": ("steward", ""), "privacy": ("privacy", "")}  # fmt: skip

# synthetic identifying-shaped values, built at run time (a chart number, a name after a label, a phone, an e-mail)
CHART = "".join(("7", "0", "0", "0", "4", "2", "1", "9"))
NAME = "Name: " + "Synthia " + "Testperson"
PHONE = "-".join(("0912", "000", "111"))
MAIL = "synthia.testperson" + "@" + "example.invalid"
PLANTED = {"chart": CHART, "name": "Synthia Testperson", "phone": PHONE, "email": MAIL}


def free_text() -> str:
    return f"call about chart {CHART}, {NAME}, phone {PHONE}, mail {MAIL}"


def _login(app: Any, user: str, pw: str) -> tuple[TestClient, str]:
    c = TestClient(app, raise_server_exceptions=False)
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    r = c.post("/login", data={"username": user, "password": pw, "login_csrf": token.group(1)}, follow_redirects=False)
    assert r.status_code == 303, r.text[-300:]
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
    assert csrf
    return c, csrf.group(1)


def _clients(b: dict[str, Any]) -> dict[str, tuple[TestClient, str, TestClient]]:
    from console.teamstore import TeamStore

    users = b["users"]
    out = {}
    team = TeamStore()
    for col, (role, log) in ACCOUNTS.items():
        name, pw = (col, ADMIN_PW) if col == "admin" else (f"at{col}", PW)
        if users.get(name) is None:
            users.create(name, role, pw, f"{name}@hospa.test")
        if log == "pi":
            team.add_entry("GZQO", username=name, name="Dr Trail PI", role="pi", tasks=(), start="2026-01-01",
                           end=None, training_day="2026-01-01", training_ref=None, by="stw",
                           at="2026-01-01T00:00:00+00:00")  # fmt: skip
        page, csrf = _login(b["app"], name, pw)
        token, _ = users.new_session(users.get(name), via="api")
        api = TestClient(b["app"], raise_server_exceptions=False, headers={"Authorization": f"Bearer {token}"})
        out[col] = (page, csrf, api)
    team.close()
    return out


class Lines:
    """Every audit line under the box's folder, so a request's new lines are read from the files themselves."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.seen = self._count()

    def _count(self) -> dict[Path, int]:
        return {f: len(f.read_text("utf-8").splitlines()) for f in self.root.rglob("*.jsonl")}

    def new(self) -> list[dict[str, Any]]:
        now, out = self._count(), []
        for f in now:
            lines = f.read_text("utf-8").splitlines()
            out += [json.loads(x) for x in lines[self.seen.get(f, 0) :]]
        self.seen = now
        return out


def _prep(b: dict[str, Any]) -> dict[tuple[str, str], tuple[str, Callable[[], dict[str, Any]]]]:
    """(method, path) -> (column, a valid body and fresh state). The bodies follow the console's own page tests
    (and card V-2's walk). ``{text}`` is replaced by the free text of the case."""
    from console.breakglass_store import BreakGlassStore
    from datacore.dataops import DataOps
    from tb_common.audit import AuditLog

    n = {"i": 0}

    def fresh() -> str:
        n["i"] += 1
        return f"{n['i']:032x}".replace("0", "c")

    def night() -> int:
        ops = DataOps()
        try:
            n["i"] += 1
            batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.held", source="csv",
                                        snapshot=f"2026-10-{1 + n['i'] % 28:02d}", passed=False, held=True,
                                        by="adapter", at="2026-11-11T02:00:00+09:00", actor="adapter",
                                        detail={"incomplete": ["lab: missing"]})  # fmt: skip
            return int(batch.id)
        finally:
            ops.close()

    def ended_grant() -> int:
        store = BreakGlassStore()
        try:
            now = b["app"].state.helpers.clock()
            g, _ = store.open("trail-grantee", reason="support", note="a support call", kind="patient",
                              ruleset="GZQO", pid=A, now=now)  # fmt: skip
            store.end(g.id, "trail-grantee", now)
            return int(g.id)
        finally:
            store.close()

    def throwaway() -> str:
        n["i"] += 1
        name = f"atthrow{n['i']}"
        b["users"].create(name, "viewer", PW, None)
        return name

    reveal = {"reason": "contact"}
    return {
        ("POST", "/breakglass"): ("admin", lambda: {"form": {"kind": "patient", "ruleset": "GZQO", "pid": A,
                                                             "reason": "support", "note": "{text}"}}),
        ("POST", "/breakglass/{gid}/review"): ("steward", lambda: {"params": {"gid": ended_grant()},
                                                                   "form": {"note": "{text}"}}),
        ("POST", "/data-ops/batches/{bid}/decide"): ("steward", lambda: {
            "params": {"bid": night()}, "form": {"decision": "reject", "reason": "{text}"}}),
        ("POST", "/api/v1/data/batches/{bid}/decide"): ("steward", lambda: {
            "params": {"bid": night()}, "json": {"decision": "reject", "reason": "{text}"}}),
        ("POST", "/site/opt-outs"): ("privacy", lambda: {"form": {"pid": fresh(), "source": "paper"}}),
        ("POST", "/api/v1/site/opt-outs"): ("privacy", lambda: {"json": {"pid": fresh()}}),
        ("POST", "/studies/{rs}/patients/{pid}/reveal"): ("crc", lambda: {"form": reveal}),
        ("POST", "/studies/{rs}/candidates/{pid}/reveal"): ("crc", lambda: {"form": {"purpose": "eligibility",
                                                                                      **reveal}}),
        ("POST", "/pilot/jobs/{job_id}/reveal"): ("crc", lambda: {"form": {"pid": A, **reveal}}),
        ("POST", "/api/v1/studies/{rs}/patients/{pid}/reveal"): ("crc", lambda: {"json": reveal}),
        ("POST", "/studies/{rs}/patients/{pid}/mark"): ("pi", lambda: {"form": {"mark": "need_info",
                                                                                "note": "{text}"}}),
        ("POST", "/api/v1/studies/{rs}/patients/{pid}/mark"): ("pi", lambda: {"json": {"mark": "need_info",
                                                                                       "note": "{text}"}}),
        ("POST", "/ops/users"): ("admin", lambda: {"form": {"action": "add", "username": f"atnew{fresh()[-6:]}",
                                                            "role": "viewer"}}),
        ("POST", "/ops/users#disable"): ("admin", lambda: {"form": {"action": "disable", "username": throwaway(),
                                                                    "confirm": "yes"}}),
        ("POST", "/studies/{rs}/patients/{pid}/reveal#other"): ("crc", lambda: {"form": {"reason": "other",
                                                                                          "note": "{text}"}}),
        ("POST", "/studies/{rs}/irb"): ("crc", lambda: {"form": {"approval_no": "IRB-T-1",
                                                                 "approved_on": "2026-01-02", "reason": "{text}"}}),
        ("POST", "/audit/verify"): ("privacy", lambda: {"form": {}}),
        ("POST", "/api/v1/audit/verify"): ("privacy", lambda: {"json": {}}),
    }  # fmt: skip


def _no_grants(b: dict[str, Any]) -> None:
    from console.breakglass_store import BreakGlassStore

    store = BreakGlassStore()
    try:
        store.db.execute("UPDATE grants SET ended_at = ? WHERE ended_at IS NULL",
                         (b["app"].state.helpers.clock().isoformat(),))  # fmt: skip
    finally:
        store.close()


def _fill(path: str, params: dict[str, Any], job_id: str) -> str:
    vals = {"rs": "GZQO", "ruleset": "GZQO", "pid": A, "job_id": job_id, **params}
    return re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: str(vals.get(m.group(1), "1")), path)


def _sub(value: Any, text: str) -> Any:
    if isinstance(value, dict):
        return {k: _sub(v, text) for k, v in value.items()}
    return text if value == "{text}" else value


def call(b: dict[str, Any], cl: dict[str, Any], method: str, path: str, col: str, body: dict[str, Any],
         job_id: str, text: str) -> Any:  # fmt: skip
    page, csrf, api = cl[col]
    path = path.partition("#")[0]
    url = _fill(path, body.get("params", {}), job_id)
    if path.startswith("/api/v1/"):
        return api.request(method, url, json=_sub(body.get("json", {}), text), follow_redirects=False)
    return page.request(method, url, data={"csrf": csrf, **_sub(body.get("form", {}), text)}, follow_redirects=False)


def success(resp: Any) -> bool:
    if resp.status_code == 303:
        return "/login" not in str(resp.headers.get("location", ""))
    return 200 <= int(resp.status_code) < 300


def _username(col: str) -> str:
    return col if col == "admin" else f"at{col}"


def named(path: str, body: dict[str, Any], job_id: str) -> list[str]:
    """The record ids the request names: the path's study, patient and job, the body's patient or account, and the
    batch or grant it acts on."""
    out = []
    if "{rs}" in path or "{ruleset}" in path:
        out.append("GZQO")
    if "{pid}" in path:
        out.append(A)
    if "{job_id}" in path:
        out.append(job_id)
    out += [str(v) for v in body.get("params", {}).values()]
    form = {**body.get("form", {}), **body.get("json", {})}
    out += [str(form[k]) for k in ("pid", "username") if k in form]
    return out


def walk(b: dict[str, Any], text: str = "a plain note") -> list[dict[str, Any]]:
    """Each prepared route once, as its column; the audit lines its request wrote, read from the files."""
    from tests.console.dataops_orch import attach

    attach(b["backend"], b["audit"])
    job_id = _ulid(991)
    _done_screen(b["backend"], job_id)
    cl = _clients(b)
    lines = Lines(Path(b["dir"]))
    out = []
    for (method, path), (col, make) in _prep(b).items():
        if not path.startswith("/breakglass"):
            _no_grants(b)  # a grant an earlier call opened would open the patient (D-430)
        body = make()
        lines.new()
        resp = call(b, cl, method, path, col, body, job_id, text)
        events = lines.new()
        out.append({"method": method, "path": path, "column": col, "status": resp.status_code,
                    "success": success(resp), "events": events, "actor": f"console:{_username(col)}",
                    "named": named(path, body, job_id)})  # fmt: skip
    return out


def judge(row: dict[str, Any]) -> dict[str, Any]:
    """Who: every event's actor is the account that made the request (``console:<username>``). What: an event.
    When: a timestamp. Which: every record the request named (study, patient, batch, grant, account, job) stands in
    the request's events."""
    evs = [e for e in row["events"] if not str(e.get("event", "")).startswith("audit.")]
    who = bool(evs) and all(e.get("actor") == row["actor"] for e in evs)
    when = bool(evs) and all(e.get("ts") for e in evs)
    raw = json.dumps(evs, ensure_ascii=False)
    missing = [v for v in row["named"] if str(v) not in raw]
    return {"route": f"{row['method']} {row['path']}", "column": row["column"], "status": row["status"],
            "success": row["success"], "events": sorted({str(e.get("event")) for e in evs}),
            "who": who, "what": bool(evs), "when": when, "which": bool(evs) and not missing,
            "named": [str(v) for v in row["named"]], "not_named": missing}  # fmt: skip


def leaks(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Per route, which planted values stand in clear in its audit lines."""
    out: dict[str, list[str]] = {}
    for row in rows:
        raw = json.dumps(row["events"], ensure_ascii=False)
        hit = [k for k, v in PLANTED.items() if v in raw]
        if hit:
            out[f"{row['method']} {row['path']}"] = hit
    return out


#: the order of the change and its audit event, read from the code (basis: hypothesis) for the driven routes;
#: shown where a test makes the audit write fail (this file, or tests/console/test_d273_privacy_guards.py)
ORDER: dict[str, tuple[str, str]] = {
    "POST /breakglass": ("change first", "services/console/breakglass.py:205 (V3-18, shown there)"),
    "POST /breakglass/{gid}/review": ("change first", "services/console/breakglass.py:239 bg.review, then :242"),
    "POST /data-ops/batches/{bid}/decide": ("one transaction", "services/datacore/dataops.py:470-498"),
    "POST /api/v1/data/batches/{bid}/decide": ("one transaction", "services/datacore/dataops.py:470-498"),
    "POST /site/opt-outs": ("one transaction", "D-273; shown by tests/console/test_d273_privacy_guards.py"),
    "POST /api/v1/site/opt-outs": ("one transaction", "D-273, the same register call as the page"),
    "POST /studies/{rs}/patients/{pid}/mark": (
        "one transaction",
        "services/console/home.py:1218 (D-273), shown by test_d273_privacy_guards.py",
    ),
    "POST /api/v1/studies/{rs}/patients/{pid}/mark": ("one transaction", "services/console/home.py:1218 (D-273)"),
    "POST /ops/users": ("change first", "services/console/app.py:1257 us.create, then :1259 (shown here)"),
    "POST /studies/{rs}/irb": ("change first", "services/console/team.py:821 team.save_irb, then :824"),
    "POST /ops/users#disable": ("change first", "services/console/app.py:1328 us.disable, then :1329"),
}


def _inventory(app: Any) -> list[dict[str, Any]]:
    import mail_gateway.app as mg
    import orchestrator.app as orch

    rows = []
    for service, a in (("console", app), ("orchestrator", orch.app), ("mail_gateway", mg.app)):
        rows += [{"service": service, **r} for r in atc.changing_routes(a)]
    return rows


@pytest.fixture
def walked(box: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    rows = walk(box, free_text())
    judged = [judge(r) for r in rows]
    lk = leaks(rows)
    for j in judged:
        j["leaks"] = lk.get(j["route"], [])
        j["order"] = ORDER.get(j["route"], ("no change of state", ""))[0]
    out = {"rows": rows, "judged": judged, "leaks": lk}
    if os.environ.get("AUDIT_TRAIL_OUT"):
        inv = _inventory(box["app"])
        done = {j["route"].split("#")[0] for j in judged if j["success"]}
        for r in inv:
            r["driven"] = r["service"] == "console" and f"{r['method']} {r['path']}" in done
        dest = Path(os.environ["AUDIT_TRAIL_OUT"]) / "routes.json"
        dest.write_text(json.dumps({"inventory": inv, "driven": judged,
                                    "order": {k: list(v) for k, v in ORDER.items()}},
                                   indent=1, ensure_ascii=False) + "\n")  # fmt: skip
    return out


def test_the_inventory_comes_from_the_live_apps(box: dict[str, Any]) -> None:  # noqa: F811
    inv = _inventory(box["app"])
    by = {s: sum(1 for r in inv if r["service"] == s) for s in ("console", "orchestrator", "mail_gateway")}
    assert all(by.values()), by
    assert any(r["path"] == "/breakglass" for r in inv)  # a known changing route is found


#: the routes whose event names no record, and why that is right
NO_RECORD = {"POST /audit/verify": "the check of the whole chain", "POST /api/v1/audit/verify": "the same check"}


def test_each_driven_route_succeeds_and_records_who_what_when_which(walked: dict[str, Any]) -> None:
    bad = []
    for j in walked["judged"]:
        if not j["success"]:
            bad.append(f"{j['route']}: not brought to success ({j['status']})")
            continue
        need = ("who", "what", "when") + (() if j["route"] in NO_RECORD else ("which",))
        bad += [f"{j['route']}: {k} missing" for k in need if not j[k]]
    assert not bad, bad


@pytest.mark.parametrize("route", ["POST /data-ops/batches/{bid}/decide", "POST /api/v1/data/batches/{bid}/decide"])
def test_the_data_ops_reason_is_not_in_clear_in_the_audit(walked: dict[str, Any], route: str) -> None:
    row = next(j for j in walked["judged"] if j["route"] == route)
    # only the leak counts: a fix may also refuse identifying text with a 4xx
    assert not row["leaks"], f"{route}: in clear in the audit: {row['leaks']}"


def test_the_irb_reason_is_not_in_clear_in_the_audit(walked: dict[str, Any]) -> None:
    row = next(j for j in walked["judged"] if j["route"] == "POST /studies/{rs}/irb")
    assert not row["leaks"], f"in clear in the audit: {row['leaks']}"


def test_the_notes_that_are_masked_or_not_kept_stay_out(walked: dict[str, Any]) -> None:
    """Shown clean: the break-glass review note and the PI's mark note do not reach the audit in clear (the
    break-glass opening note is masked too since D-1158: V3-14)."""
    for route in ("POST /breakglass/{gid}/review", "POST /studies/{rs}/patients/{pid}/mark",
                  "POST /api/v1/studies/{rs}/patients/{pid}/mark"):  # fmt: skip
        row = next(j for j in walked["judged"] if j["route"] == route)
        assert row["success"] and not row["leaks"], row


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="V8-04: /ops/users makes the account before its audit event; a failed write keeps it")  # fmt: skip
def test_an_account_is_not_made_when_its_audit_event_cannot_be_written(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the audit volume reading full (``TB_AUDIT_MIN_FREE_MB`` huge, so ``AuditLog.append`` raises
    ``AuditFull``), adding an account must leave no account behind: either the event comes first or both are
    undone. A control call first shows the same body succeeds with its event."""
    page, csrf = _login(box["app"], "admin", ADMIN_PW)
    lines = Lines(Path(box["dir"]))
    r = page.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "atcontrol", "role": "viewer"},
                  follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and any(e.get("event") == "console.user" for e in lines.new())
    monkeypatch.setenv("TB_AUDIT_MIN_FREE_MB", str(2**40))
    r = page.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "atfull", "role": "viewer"},
                  follow_redirects=False)  # fmt: skip
    made = box["users"].get("atfull") is not None
    told = any(e.get("event") == "console.user" and "atfull" in json.dumps(e) for e in lines.new())
    assert not made or told, f"the account was made with no audit event ({r.status_code})"  # a refusal is a fix too


def test_no_driven_route_writes_typed_text_in_clear(walked: dict[str, Any]) -> None:
    """The register's V3-14, V8-03, V8-07 (D-1158): every route the walk drives with the identifying probe text
    (a chart number, a labelled name, a phone, an e-mail) keeps none of it in clear in the audit, whatever key the
    text was typed into."""
    leaks = [f"{j['route']}: {j['leaks']}" for j in walked["judged"] if j["leaks"]]
    assert not leaks, leaks
