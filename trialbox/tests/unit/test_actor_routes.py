"""T-715 (D-483; trust review F2, TR-3): where every changing route of the orchestrator takes its person from.

The acceptance of the card: a walk over the app's routes fails on a changing route without the dependency, or with
a request field that names a person (``by``, ``signer``, ``approved_by``). The walk is ``orchestrator.actor``'s own
(``route_problems``, which also stops the service at import); here it runs on the real app, and on small apps that
have each defect, so that it is seen to fail. Then the dependency itself: every way a call can be for another
person, right, study, request or body is refused on the real app in the production trust configuration.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from orchestrator import actor as ra
from pydantic import BaseModel
from tb_common import actor_v3 as v3
from tb_common import service_auth as sa
from tb_common.authz import MATRIX, Standing

from tests.actor3 import signed
from tests.service_tokens import per_service_tokens, token_of

ROOT = Path(__file__).resolve().parents[2]
STEP = "/studies/GZQO/subjects/GZQO-0001/step"
BODY = {"to": "enrolled"}


# ---------------------------------------------------------------------------------------------------- the walk
def test_the_real_app_is_staged_as_the_table_says() -> None:
    from orchestrator.app import CALLER_GATE, app

    assert ra.route_problems(app, CALLER_GATE.table.group_of) == []
    rows = ra.walk(app)
    refuse = [r for r in rows if r[2] == "refuse"]
    report = [r for r in rows if r[2] == "report" and r[0] not in sa.SAFE_METHODS]
    # lifecycle, sponsor, the registry and the study router converted; the rest counted
    assert len(refuse) >= 44 and len(report) == 0  # T-715f/g (D-799, D-803): the data core and the setup router
    # D-717: a patient read names the actions it takes (phi.view, or monitor.read too); each is a matrix row
    assert {a for r in refuse for a in ((r[3],) if isinstance(r[3], str) else r[3])} <= set(MATRIX)
    # NEW-SEC-1 (D-717): a refuse route takes no person from its request; the two EDC reads of the v2 group keep
    # their v2 handler, whose `by` is a fallback name refused outside DEV and TEST (D-162)
    v2_reads = {"GET /studies/{rs}/edc/copy", "GET /studies/{rs}/edc/export/odm"}
    assert all(r[4] == () for r in refuse if f"{r[0]} {r[1]}" not in v2_reads)
    # the stage is the group's: every changing lifecycle and sponsor route, and no other, refuses
    # NEW-SEC-1 (D-717): a patient read refuses whatever its group's stage; the groups are those of the changing routes
    groups = {CALLER_GATE.table.group_of(f"{m} {p}") for m, p, *_ in refuse if m not in sa.SAFE_METHODS}
    # T-716: the chart number; T-715b (D-550): the registry; T-715d (D-554): the study router
    assert (
        groups
        == set(ra.TABLE["refuse"])
        == {
            "lifecycle",
            "sponsor",
            "job_reveal",
            "registry",
            "study",
            "dataops",
            "datacore",
            "setup",
            "omop_conflicts",
            "job_cancel",
            "job_retry_scheduled",
            "notices",
        }
    )  # T-715f (D-799); NEW-ARCH-3 slice 2 (D-865): the steward's clinical conflicts; T-715 refuse mode (D-871,
    # D-1150: the notices, by four service principals)
    changing = [r for r in rows if r[0] not in sa.SAFE_METHODS]
    assert all(r[2] or CALLER_GATE.table.group_of(f"{r[0]} {r[1]}") in (*ra.TABLE["v2"], *ra.TABLE["no_person"])
               for r in changing)  # fmt: skip


class _Named(BaseModel):
    to: str
    by: str


class _Plain(BaseModel):
    to: str


class _Outer(BaseModel):
    rows: list[_Named]


class _Confirmed(BaseModel):
    to: str
    confirmed_by: str


def _toy(defect: str) -> FastAPI:
    app = FastAPI()
    dep = ra.require_actor("study.setup")

    if defect == "no dependency":

        @app.post("/studies/{rs}/x")
        def bare(rs: str, body: _Plain) -> dict[str, str]:
            return {}
    elif defect == "body names a person":

        @app.post("/studies/{rs}/x")
        def named(rs: str, body: _Named, who: v3.Claim = dep) -> dict[str, str]:
            return {}
    elif defect == "query names a person":

        @app.post("/studies/{rs}/x")
        def query(rs: str, body: _Plain, approved_by: str = "", who: v3.Claim = dep) -> dict[str, str]:
            return {}
    elif defect == "not a matrix action":

        @app.post("/studies/{rs}/x")
        def unknown(rs: str, body: _Plain, who: v3.Claim = ra.require_actor("life.anything")) -> dict[str, str]:  # noqa: B008
            return {}
    elif defect == "report only":

        @app.post("/studies/{rs}/x", dependencies=[ra.report_actor])
        def reported(rs: str, body: _Plain) -> dict[str, str]:
            return {}
    elif defect == "nested person":

        @app.post("/studies/{rs}/x")
        def nested(rs: str, body: _Outer, who: v3.Claim = dep) -> dict[str, str]:
            return {}
    elif defect == "free body":

        @app.post("/studies/{rs}/x")
        def free(rs: str, body: dict[str, Any], who: v3.Claim = dep) -> dict[str, str]:
            return {}
    elif defect == "confirmed_by":

        @app.post("/studies/{rs}/x")
        def confirmed(rs: str, body: _Confirmed, who: v3.Claim = dep) -> dict[str, str]:
            return {}
    else:

        @app.post("/studies/{rs}/x")
        def good(rs: str, body: _Plain, who: v3.Claim = dep) -> dict[str, str]:
            return {}

    return app


TOY_TABLE: dict[str, Any] = {"refuse": ["g"], "report": [], "v2": [], "no_person": [], "principals": {}}


@pytest.mark.parametrize(("defect", "says"), [
    ("no dependency", "a changing route of a refuse group without require_actor"),
    ("report only", "a changing route of a refuse group without require_actor"),
    ("body names a person", "the request still names a person (by)"),
    ("query names a person", "the request still names a person (approved_by)"),
    ("not a matrix action", "which is not a row of the matrix"),
    ("nested person", "the request still names a person (by)"),  # review M2: at any depth of the body model
    ("free body", "the request still names a person (*)"),  # a free mapping could carry any name
    ("confirmed_by", "the request still names a person (confirmed_by)"),
])  # fmt: skip
def test_the_walk_fails_on_each_defect(defect: str, says: str) -> None:
    bad = ra.route_problems(_toy(defect), lambda key: "g", TOY_TABLE)
    assert len(bad) == 1 and says in bad[0] and bad[0].startswith("POST /studies/{rs}/x: ")
    assert ra.route_problems(_toy("none"), lambda key: "g", TOY_TABLE) == []


def test_every_console_call_that_changes_the_registry_passes_a_signer() -> None:
    """T-715b (the review): the registry's backend methods take the signer as their third argument, and the
    console's backend object is untyped where pages use it, so a call without one is found only when it runs:
    a contact outcome was such a call. Every call in the console's code is read here."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "services" / "console"
    calls = []
    for f in sorted(root.glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("registry_update", "registry_promote")):  # fmt: skip
                calls.append((f.name, n.lineno, len(n.args) + len(n.keywords)))
    assert len(calls) >= 4, calls  # the registry page's two, a contact outcome and its undo
    assert [c for c in calls if c[2] < 3] == []


def test_the_walk_fails_on_a_refuse_route_whose_study_is_not_rs() -> None:
    """Review M2: ``require_actor`` reads the study from ``{rs}``; a route that names it otherwise would be checked
    against no study."""
    app = FastAPI()

    @app.post("/studies/{study}/x")
    def other(study: str, body: _Plain, who: v3.Claim = ra.require_actor("study.setup")) -> dict[str, str]:  # noqa: B008
        return {}

    bad = ra.route_problems(app, lambda key: "g", TOY_TABLE)
    assert len(bad) == 1 and "require_actor reads {rs}" in bad[0]


REPORT_ROUTES = Path(__file__).parent / "data" / "actor_report_routes.txt"


def test_the_report_list_only_shrinks() -> None:
    """Review M2: the changing routes that still take a typed name are this committed list, exactly. A card that
    converts a router deletes its lines; a new route cannot join the list (it is built with ``require_actor``)."""
    from orchestrator.app import app

    now = sorted(f"{m} {p}" for m, p, stage, *_ in ra.walk(app) if stage == "report" and m not in sa.SAFE_METHODS)
    pinned = [ln for ln in REPORT_ROUTES.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    assert set(now) <= set(pinned), f"a new route takes a typed name: {sorted(set(now) - set(pinned))}"
    assert now == pinned, f"converted routes leave the list: delete {sorted(set(pinned) - set(now))}"


def test_the_walk_fails_on_a_group_in_no_stage_and_on_a_ghost_group() -> None:
    bad = ra.route_problems(_toy("none"), lambda key: "new_group", TOY_TABLE)
    assert bad == [
        "POST /studies/{rs}/x: its group (new_group) is in no stage of route_actors.yaml",
        "group g: in route_actors.yaml but it has no changing route",
    ]
    with pytest.raises(RuntimeError, match="route_actors.yaml and the routes disagree"):
        ra.assert_staged(_toy("no dependency"), lambda key: "lifecycle")


def test_the_table_is_read_strictly(tmp_path: Path) -> None:
    f = tmp_path / "t.yaml"
    f.write_text("schema: other\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a tb-orchestrator-actors/1 table"):
        ra.load(f)
    f.write_text("schema: tb-orchestrator-actors/1\nrefuse: [a]\nreport: [a]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="in two stages"):
        ra.load(f)
    f.write_text("schema: tb-orchestrator-actors/1\nno_person: {a: ''}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="needs its reason"):
        ra.load(f)
    assert set(ra.TABLE["principals"]) == {
        "service:console-notify",
        "service:console-nightly",
        "service:console-optout-check",
        # T-715 refuse mode (D-1150): the senders of the box's own notices
        "service:console-sae-sync",
        "service:console-accounts",
        "service:console-breakglass",
    }


def test_the_console_mints_in_one_place() -> None:
    """``actor_v3.mint`` in ``services/`` is called by ``console/actor.py`` only: a page cannot sign for itself."""
    hits = [str(f.relative_to(ROOT)) for f in sorted((ROOT / "services").rglob("*.py"))
            if re.search(r"\bmint\(", f.read_text(encoding="utf-8"))]  # fmt: skip
    assert hits == ["services/console/actor.py"]


# ---------------------------------------------------------------------------------------------- the dependency
@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[dict[str, Any]]]:
    """The real app in the production trust configuration, on a stand-in for the box's data (the dependency runs
    before any handler; a call that passes it reaches the stand-in and fails there, which is not a refusal)."""
    from orchestrator import app as oapp

    per_service_tokens(tmp_path, monkeypatch)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    events: list[dict[str, Any]] = []
    audit = SimpleNamespace(append=lambda kind, **kw: events.append({"kind": kind, **kw}))
    monkeypatch.setattr(oapp, "orch", lambda: SimpleNamespace(audit=audit))
    client = TestClient(oapp.app, headers={sa.TOKEN_HEADER: token_of("console")}, raise_server_exceptions=False)
    return client, events


class _Lines(logging.Handler):
    """The orchestrator's own log lines, read at the logger itself: the app's logging set-up decides whether a
    line travels further (to pytest's capture), and that depends on which test built the app first."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def lines() -> Iterator[_Lines]:
    h, lg = _Lines(), logging.getLogger("orchestrator")
    lg.addHandler(h)
    try:
        yield h
    finally:
        lg.removeHandler(h)


def test_a_refusal_stays_a_refusal_when_its_record_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lines: _Lines
) -> None:
    """Train 8: an unsigned registry change on a box whose database did not answer was a 500 ("internal error"),
    because writing the ``actor.refused`` record raised and the refusal was lost with it. The person is refused
    all the same (403, the same body), and the record that could not be written is an ERROR line of the log."""
    from orchestrator import app as oapp

    per_service_tokens(tmp_path, monkeypatch)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")

    def no_box() -> Any:
        raise RuntimeError("cannot reach the trial database: OperationalError")

    monkeypatch.setattr(oapp, "orch", no_box)
    client = TestClient(oapp.app, headers={sa.TOKEN_HEADER: token_of("console")}, raise_server_exceptions=False)
    r = client.post("/registry/GZQO", json={"pid": "ab" * 16, "status": "contacted"})
    assert r.status_code == 403, r.text[:200]
    assert "no signed-in user" in _refused(r)
    lost = [x for x in lines.records if x.getMessage() == "actor.refused: not written to the audit trail"]
    assert len(lost) == 1 and getattr(lost[0], "route", "") == "POST /registry/{ruleset}"
    assert getattr(lost[0], "reason", "") and getattr(lost[0], "error", "") == "RuntimeError"
    assert ra.lost_refusals()["routes"].get("POST /registry/{ruleset}", 0) >= 1  # counted: the status shows it


def test_the_older_checks_refusal_stays_one_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lines: _Lines) -> None:
    """The same fault in the older signed-person check (``orchestrator.app._claim``: a job's retry, cancel, the
    notices, the EDC): a person named without a valid assertion was a 500 when the record could not be written."""
    from orchestrator import app as oapp

    per_service_tokens(tmp_path, monkeypatch)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")

    def no_box() -> Any:
        raise RuntimeError("cannot reach the trial database: OperationalError")

    monkeypatch.setattr(oapp, "orch", no_box)
    headers = {sa.TOKEN_HEADER: token_of("console"), sa.ACTOR_HEADER: "console:dr_tanaka",
               sa.ROLE_HEADER: "admin", sa.ASSERTION_HEADER: "not-a-signature"}  # fmt: skip
    client = TestClient(oapp.app, headers=headers, raise_server_exceptions=False)
    before = ra.lost_refusals()["count"]
    r = client.post("/jobs/01HZZZZZZZZZZZZZZZZZZZZZZZ/retry", json={"reply_to": "it@hospa.test"})
    assert r.status_code == 403 and "dr_tanaka" not in r.text, r.text[:200]
    lost = [x for x in lines.records if x.getMessage() == "actor.refused: not written to the audit trail"]
    assert len(lost) == 1 and getattr(lost[0], "route", "") == "POST /jobs/{job_id}/retry"
    assert ra.lost_refusals()["count"] == before + 1


def _refused(r: Any) -> str:
    """The dependency's reason, "" when the call was not refused by it."""
    try:
        detail = r.json().get("detail")
    except ValueError:
        return ""
    return (
        str(detail.get("reason"))
        if r.status_code == 403 and isinstance(detail, dict) and detail.get("code") == "ACTOR"
        else ""
    )


def test_a_signed_call_passes_and_every_other_call_is_refused(box: Any) -> None:
    client, events = box
    ok = client.post(STEP, json=BODY, headers=signed("study.setup", "GZQO", "POST", STEP, BODY))
    assert _refused(ok) == "" and ok.status_code != 403  # past the dependency (the stand-in has no data core)
    cases: list[tuple[str, dict[str, str], Any]] = [
        ("no signed-in user", {}, BODY),
        ("study", signed("study.setup", "OTHER", "POST", STEP, BODY), BODY),
        ("study", signed("study.setup", "", "POST", STEP, BODY), BODY),
        ("action", signed("sae.ack", "GZQO", "POST", STEP, BODY), BODY),
        ("request", signed("study.setup", "GZQO", "POST", STEP.replace("0001", "0002"), BODY), BODY),
        ("request", signed("study.setup", "GZQO", "PUT", STEP, BODY), BODY),
        ("request", signed("study.setup", "GZQO", "POST", STEP + "?today=2026-01-01", BODY), BODY),
        ("body", signed("study.setup", "GZQO", "POST", STEP, BODY), {"to": "withdrawn"}),
        ("body", signed("study.setup", "GZQO", "POST", STEP, BODY), {**BODY, "note": "added"}),
        ("right", signed("study.setup", "GZQO", "POST", STEP, BODY, role="investigator"), BODY),
        ("right", signed("study.setup", "GZQO", "POST", STEP, BODY, role="admin"), BODY),
        ("right", signed("study.setup", "GZQO", "POST", STEP, BODY, role="nobody"), BODY),
        ("principal", signed("study.setup", "GZQO", "POST", STEP, BODY, sub="service:console-notify", role="service"), BODY),
        ("not a v3 assertion", sa.actor_header("console:crc", role="coordinator", scope="GZQO"), BODY),
    ]  # fmt: skip
    for why, headers, body in cases:
        n = len(events)
        r = client.post(STEP, json=body, headers=headers)
        assert why in _refused(r), (why, r.status_code, r.text[:200])
        assert len(events) == n + 1 and events[-1]["kind"] == "actor.refused", why
        d = events[-1]["detail"]
        assert d["route"] == "POST /studies/{rs}/subjects/{record}/step" and d["action"] == "study.setup"
        assert d["caller"] == "console" and why in d["reason"]
    used = signed("study.setup", "GZQO", "POST", STEP, BODY)
    assert _refused(client.post(STEP, json=BODY, headers=used)) == ""
    assert "already used" in _refused(client.post(STEP, json=BODY, headers=used))
    # a body field names nobody: the old way in (review F2)
    r = client.post(STEP, json={**BODY, "by": "dr_tanaka"})
    assert "no signed-in user" in _refused(r) and events[-1]["actor"] is None


def test_every_refuse_route_refuses_an_unsigned_call_and_a_role_without_the_right(box: Any) -> None:
    from orchestrator.app import app

    client, events = box
    routes = [(m, p, a) for m, p, stage, a, _ in ra.walk(app) if stage == "refuse"]
    assert len(routes) >= 20
    for method, template, action in routes:
        path = template.replace("{rs}", "GZQO").replace("{record}", "GZQO-0001").replace("{event}", "ae1")
        path = path.replace("{ruleset}", "GZQO")  # T-715b: the registry names its study so
        path = path.replace("{fmt}", "csv").replace("{job_id}", "J1").replace("{ref}", "rc1")
        # T-715d (D-554): a route of the whole box (a REDCap connection) is claimed with no study
        named = "{rs}" in template or "{ruleset}" in template
        study = "GZQO" if named else ""
        body = None if method == "GET" else {"x": 1}
        kw = {} if body is None else {"json": body}
        assert "no signed-in user" in _refused(client.request(method, path, **kw)), template
        action = action if isinstance(action, str) else action[0]  # D-717: a read's first action
        wrong = signed(action, study, method, path, body, role="viewer")
        assert _refused(client.request(method, path, headers=wrong, **kw)) == "right", template
        if named:  # a job's route has none: its handler compares it
            other = signed(action, "OTHER", method, path, body)
            assert _refused(client.request(method, path, headers=other, **kw)) == "study", template
    with_study = sum("{rs}" in template or "{ruleset}" in template for _, template, _ in routes)
    assert len(events) == 2 * len(routes) + with_study and {e["kind"] for e in events} == {"actor.refused"}


def test_the_notice_timer_is_admitted_only_where_a_route_says_so(box: Any) -> None:
    client, _ = box
    path = "/studies/GZQO/subjects/refresh"
    body: dict[str, Any] = {"screening": {}}
    timer = "service:console-notify"
    r = client.post(
        path, json=body, headers=signed("study.setup", "GZQO", "POST", path, body, sub=timer, role="service")
    )
    assert _refused(r) == ""  # the participants' refresh admits the timer
    r = client.post(path, json=body, headers=signed("study.setup", "GZQO", "POST", path, body,
                                                    sub="service:somebody-else", role="service"))  # fmt: skip
    assert _refused(r) == "principal"
    rule, rb = "/studies/GZQO/sae-rule", {"rule_set": "x"}
    r = client.put(rule, json=rb, headers=signed("study.setup", "GZQO", "PUT", rule, rb, sub=timer, role="service"))
    assert _refused(r) == "principal"  # the same principal on a route that admits no timer


def test_the_standing_in_the_claim_is_what_the_matrix_is_asked_with() -> None:
    """A conditional row: the signed standing decides, and a claim without it is refused (T-716 makes the
    orchestrator read the delegation log itself)."""
    row = next(a for a, r in MATRIX.items() if r.get("investigator") not in (True, False))
    pi = Standing(is_pi=True, log_names_pi=True)

    def mk(st: Standing) -> v3.Claim:
        return v3.Claim(sub="console:dr", role="investigator", study="GZQO", action=row, is_pi=st.is_pi,
                        tasks=tuple(st.tasks), log_names_pi=st.log_names_pi)  # fmt: skip

    assert ra.check(mk(pi), row, "GZQO") in ("", "right")
    assert ra.check(mk(Standing(log_names_pi=True)), row, "GZQO") == "right"
    assert ra.check(mk(pi), row, "OTHER") == "study" and ra.check(mk(pi), "sae.ack", "GZQO") == "action"


# ------------------------------------------------------------------------------------------------ report stage
def _report_route() -> TestClient:
    """T-715g (D-803): no route of the app is in stage `report` any more; the stage (kept for a router that is moved
    there first) is held on a route of its own, with the app's audit (the ``box`` fixture's)."""
    from fastapi import FastAPI

    mini = FastAPI()

    @mini.post("/setup/{ws}/codes", dependencies=[ra.report_actor])
    def x(ws: str) -> dict[str, str]:
        return {"ws": ws}

    @mini.get("/setup/{ws}/codes")
    def y(ws: str) -> dict[str, str]:
        return {"ws": ws}

    return TestClient(mini)


def test_a_report_route_counts_an_unsigned_call_and_lets_it_through(box: Any) -> None:
    _client, events = box
    client = _report_route()
    path, body = "/setup/w1/codes", {"by": "dr_tanaka"}
    key = "POST /setup/{ws}/codes"
    before = sum(n for (route, _), n in ra.UNSIGNED.items() if route == key)
    r = client.post(path, json=body)
    assert _refused(r) == "" and not [e for e in events if e["kind"] == "actor.refused"]  # let through: report
    assert sum(n for (route, _), n in ra.UNSIGNED.items() if route == key) == before + 1
    assert ra.UNSIGNED[(key, "no v3 assertion")] >= 1
    # a valid assertion for this request is not counted; one for another body is
    client.post(path, json=body, headers=signed("site.setup", "", "POST", path, body))
    assert sum(n for (route, _), n in ra.UNSIGNED.items() if route == key) == before + 1
    client.post(path, json=body, headers=signed("site.setup", "", "POST", path, {"other": 1}))
    assert ra.UNSIGNED[(key, "body")] >= 1
    assert client.get(path).status_code == 200 and ra.UNSIGNED.get(("GET /setup/{ws}/codes", "no v3 assertion")) is None


def test_a_report_route_counts_a_claim_for_another_study_or_without_the_right(box: Any) -> None:
    """Review M1: in stage `report` a claim counts as a verified person only when it is for this study and the
    matrix allows its own action to its role; the first of each route and reason is in the audit trail."""
    _client, events = box
    client = _report_route()
    # the other-study case: test_a_report_stage_route_that_names_a_study_counts_a_claim_for_another
    path, body = "/setup/w1/codes", {"by": "dr_tanaka"}
    key = "POST /setup/{ws}/codes"
    for reason, headers in (
        ("right", signed("sae.ack", "", "POST", path, body, role="viewer")),
        ("principal", signed("sae.ack", "", "POST", path, body, sub="service:console-notify", role="service")),
    ):
        before = ra.UNSIGNED[(key, reason)]
        assert _refused(client.post(path, json=body, headers=headers)) == ""  # let through: report
        assert ra.UNSIGNED[(key, reason)] == before + 1, reason
    seen = [(e["detail"]["route"], e["detail"]["reason"]) for e in events if e["kind"] == "actor.unsigned"]
    assert len(seen) == len(set(seen))  # once per route and reason in a process
    assert all(set(e["detail"]) == {"route", "reason", "caller"} for e in events if e["kind"] == "actor.unsigned")


def test_a_count_that_cannot_be_audited_does_not_refuse_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI on the first push: a router of a `report` group used outside the box's app (a page test's own FastAPI)
    has no audit log to write to. The stage lets the call through, so the count must not turn it into an error."""

    def no_audit() -> Any:
        raise PermissionError("no audit log here")

    monkeypatch.setattr(ra, "_audit", no_audit)
    monkeypatch.setattr(ra, "_logged", set())
    app = FastAPI()

    @app.post("/studies/{rs}/x", dependencies=[ra.report_actor])
    def reported(rs: str, body: _Plain) -> dict[str, str]:
        return {"ok": rs}

    key = "POST /studies/{rs}/x"
    before = ra.UNSIGNED[(key, "no v3 assertion")]
    r = TestClient(app).post("/studies/GZQO/x", json={"to": "a"})
    assert r.status_code == 200 and r.json() == {"ok": "GZQO"}
    assert ra.UNSIGNED[(key, "no v3 assertion")] == before + 1


def test_a_report_route_reads_the_study_where_its_path_names_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Found when T-719 met this card: the registry's routes name the study `{ruleset}`, and some routes name none.
    A claim for the study of the path is a verified person there; a claim for another study is counted; on a path
    that names no study the claim's own study is not compared with anything."""
    monkeypatch.setattr(ra, "_audit", None)
    app = FastAPI()
    seen: list[str] = []

    @app.post("/registry/{ruleset}", dependencies=[ra.report_actor])
    def row(ruleset: str, body: _Plain, request: Request) -> dict[str, str]:
        seen.append(getattr(getattr(request.state, "tb_actor", None), "sub", ""))
        return {}

    @app.post("/setup/pseudonym", dependencies=[ra.report_actor])
    def whole_box(body: _Plain, request: Request) -> dict[str, str]:
        seen.append(getattr(getattr(request.state, "tb_actor", None), "sub", ""))
        return {}

    c, body = TestClient(app), {"to": "a"}
    c.post("/registry/GZQO", json=body, headers=signed("request.prepare", "GZQO", "POST", "/registry/GZQO", body))
    c.post("/registry/GZQO", json=body, headers=signed("request.prepare", "OTHER", "POST", "/registry/GZQO", body))
    c.post("/setup/pseudonym", json=body, headers=signed("request.prepare", "GZQO", "POST", "/setup/pseudonym", body))
    assert seen == ["console:crc", "", "console:crc"]
    assert ra.UNSIGNED[("POST /registry/{ruleset}", "study")] >= 1


def test_a_report_route_keeps_why_a_claim_was_not_a_verified_person() -> None:
    """A door behind the stage that refuses (T-719's chart-number door) says why in its own refusal."""
    app = FastAPI()
    why: list[str] = []

    @app.post("/setup/pseudonym", dependencies=[ra.report_actor])
    def whole_box(body: _Plain, request: Request) -> dict[str, str]:
        why.append(getattr(request.state, "tb_actor_why", ""))
        return {}

    c, body = TestClient(app), {"to": "a"}
    c.post(
        "/setup/pseudonym",
        json=body,
        headers=signed("optout.keep", "", "POST", "/setup/pseudonym", body, role="viewer"),
    )
    c.post("/setup/pseudonym", json=body)
    c.post(
        "/setup/pseudonym",
        json=body,
        headers=signed("optout.keep", "", "POST", "/setup/pseudonym", body, role="steward"),
    )
    assert why == ["right", "no v3 assertion", ""]


def test_a_report_stage_route_that_names_a_study_counts_a_claim_for_another() -> None:
    """The review of D-799 (4): the last report routes name no study, so the report stage's study check is held here,
    on a route of its own that names one."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    mini = FastAPI()

    @mini.post("/studies/{rs}/x", dependencies=[ra.report_actor])
    def x(rs: str) -> dict[str, str]:
        return {"rs": rs}

    c, path, body = TestClient(mini), "/studies/GZQO/x", {"a": 1}
    key = "POST /studies/{rs}/x"
    before = ra.UNSIGNED[(key, "study")]
    r = c.post(path, json=body, headers=signed("study.setup", "OTHER", "POST", path, body))
    assert r.status_code == 200 and ra.UNSIGNED[(key, "study")] == before + 1  # let through, counted
    mine = ra.UNSIGNED[(key, "study")]
    c.post(path, json=body, headers=signed("study.setup", "GZQO", "POST", path, body))
    assert ra.UNSIGNED[(key, "study")] == mine  # its own study: not counted
