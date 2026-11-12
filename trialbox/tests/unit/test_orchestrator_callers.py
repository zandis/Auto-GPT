"""T-713 (D-464; review 2026-11-12 trust F2, F7, F12, card TR-2): which verified calling service may reach which
orchestrator route. The walk tries every route of the app (``app.routes``, included routers flattened) with every
service's token in registry mode; a route in no group of ``route_callers.yaml`` fails it. Synthetic data only."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from tb_common import service_auth as sa
from tb_common.subject import COMMANDS
from tb_contracts import Job

from tools.trialbox.svc_secrets import IDENTITIES

ULID = "01JB0000000000000000000713"
_T = "2026-11-12T09:00:00+08:00"


def _job(message_id: str | None = None, job_type: str = "SCREEN") -> Job:
    return Job.model_validate({"job_id": ULID, "type": job_type, "ruleset": "GZQO", "requested_by": "crc@hospa.test",
                               "received_at": _T, "updated_at": _T, "state": "received", "options": {},
                               "message_id": message_id})  # fmt: skip


def _fake(events: list[dict[str, Any]], state: dict[str, Any]) -> SimpleNamespace:
    def create(req: Any, role: str = "", by: str = "") -> Job:
        state["created"].append(req)
        return _job(req.message_id, str(req.type))

    return SimpleNamespace(
        audit=SimpleNamespace(append=lambda kind, **kw: events.append({"kind": kind, **kw})),
        db=SimpleNamespace(get=lambda _id: state["job"], url=None),
        create=create,
    )


def _token(name: str) -> str:
    return f"t713-token-of-{name}-0123456789abcdef"


def _registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: str | None = None) -> None:
    doc: dict[str, Any] = {"schema": sa.REGISTRY_SCHEMA,
                           "services": {n: sa.token_hash(_token(n)) for n in IDENTITIES}}  # fmt: skip
    if legacy:
        doc["legacy"] = sa.token_hash(legacy)
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv(sa.REGISTRY_ENV, str(path))


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[dict[str, Any]], dict[str, Any]]:
    from orchestrator import app as oapp

    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    _registry(tmp_path, monkeypatch)
    events: list[dict[str, Any]] = []
    state: dict[str, Any] = {"job": _job("<m1@hospa.test>"), "created": []}
    monkeypatch.setattr(oapp, "orch", lambda: _fake(events, state))
    return TestClient(oapp.app, raise_server_exceptions=False), events, state


def _concrete(template: str) -> str:
    return re.sub(r"\{[^}]+\}", "T713X", template)


def _routes() -> list[tuple[str, str]]:
    from orchestrator.app import app
    from orchestrator.callers import route_templates

    return list(route_templates(app))


def test_every_route_is_in_exactly_one_group_and_the_table_names_no_ghost() -> None:
    from orchestrator.app import CALLER_GATE

    table = CALLER_GATE.table
    keys = {f"{m} {t}" for m, t in _routes()}
    assert len(keys) > 100  # the routers of the data core, lifecycle, EDC, study, set-up and sponsor are walked
    placed = table.keys()
    missing = sorted(keys - placed)
    assert not missing, f"routes in no group of services/orchestrator/route_callers.yaml (place each): {missing}"
    ghosts = sorted(placed - keys)
    assert not ghosts, f"route_callers.yaml names routes the app does not have: {ghosts}"
    for prefix in ("/studies/{rs}/subjects", "/studies/{rs}/edc", "/setup/", "/studies/{rs}/sponsor", "/redcap/"):
        assert any(prefix in k for k in keys), prefix


def test_every_route_resolves_to_its_own_template() -> None:
    from orchestrator.app import CALLER_GATE, app

    for method, template in _routes():
        assert CALLER_GATE.resolve(app, method, _concrete(template)) == f"{method} {template}"


def test_every_identity_has_a_row_and_the_rows_are_what_the_card_says() -> None:
    from console.step4 import INTERNAL_PRINCIPALS
    from orchestrator.app import CALLER_GATE
    from orchestrator.core import SYSTEM_SENDERS

    rows = CALLER_GATE.table.services
    assert set(IDENTITIES) <= set(rows)
    mail = rows["mail-gateway"]
    assert mail.routes == {"POST /jobs", "GET /jobs/{job_id}"} and mail.own_jobs == "mail"
    # the commands the mail intake accepts (tb_common.subject)
    assert mail.job_types is not None and set(mail.job_types) == set(COMMANDS)
    for svc in ("adapter", "lake", "criteria-compiler", "doc-parser", "gateway", "embed-service", "orchestrator"):
        assert rows[svc].routes == frozenset(), svc
    assert rows["scheduler"].in_process and not rows["scheduler"].routes
    assert CALLER_GATE.table.principals == set(SYSTEM_SENDERS) == set(INTERNAL_PRINCIPALS)
    # the operator's host token: reads of jobs and models, never a chart number, a study write or a job start
    op = rows["operator"].routes
    assert "GET /jobs" in op and not any(k.startswith(("POST", "PUT", "DELETE")) for k in op)


def test_the_route_walk_with_every_service_token(box: Any) -> None:
    """The acceptance: every route, every token. A route outside the service's row is refused before the handler
    runs: 403 (``route_not_allowed`` audited with the verified service, or the token layer's own refusal of a
    service that may not call the orchestrator at all)."""
    from orchestrator.app import CALLER_GATE

    client, events, _ = box
    rows = CALLER_GATE.table.services
    walked = 0
    for name in IDENTITIES:
        row = rows[name]
        for method, template in _routes():
            key = f"{method} {template}"
            if key in CALLER_GATE.table.open:
                continue
            if key in row.routes:
                assert CALLER_GATE.decide(name, key) is None, (name, key)
                continue
            n = len(events)
            r = client.request(method, _concrete(template), headers={sa.TOKEN_HEADER: _token(name)})
            assert r.status_code == 403, (name, key, r.status_code)
            walked += 1
            if name in sa.CALLERS["orchestrator"] or name == sa.OPERATOR:
                assert r.headers.get("X-TB-Refusal") == "route_not_allowed", (name, key)
                ev = events[n]
                assert ev["kind"] == "service.route_refused" and ev["actor"] == f"service:{name}"
                assert ev["detail"] == {"service": name, "route": key, "path": _concrete(template)[:120],
                                        "reason": "route_not_allowed"}  # fmt: skip
            else:  # CALLERS refuses it first
                assert "may not call orchestrator" in r.text, (name, key)
    assert walked > 800


def test_the_mail_gateway_reaches_two_routes_and_its_own_jobs(box: Any) -> None:
    client, events, state = box
    h = {sa.TOKEN_HEADER: _token("mail-gateway")}
    body = {"type": "SCREEN", "ruleset": "GZQO", "requested_by": "crc@hospa.test", "message_id": "<m1@hospa.test>"}
    r = client.post("/jobs", json=body, headers=h)
    assert r.status_code == 200 and state["created"][-1].requested_by == "crc@hospa.test"
    assert client.get(f"/jobs/{ULID}", headers=h).status_code == 200  # came in by mail
    state["job"] = _job(None)  # started on the console: not the mail gateway's
    r = client.get(f"/jobs/{ULID}", headers=h)
    assert r.status_code == 403 and r.headers["X-TB-Refusal"] == "route_not_allowed"
    assert events[-1]["kind"] == "service.route_refused" and events[-1]["detail"]["route"] == "GET /jobs/{job_id}"
    assert client.get(f"/jobs/{ULID}", headers={sa.TOKEN_HEADER: _token("console")}).status_code == 200
    for jtype in ("MICROBATCH", "INGEST", "RETENTION", "CALIBRATION"):  # the scheduler's, not mail commands
        r = client.post("/jobs", json={**body, "type": jtype}, headers=h)
        assert r.status_code == 403 and r.headers["X-TB-Refusal"] == "route_not_allowed", jtype
        assert events[-1]["detail"]["service"] == "mail-gateway"
    # the review's F2 case: a study setting under any name with the mail gateway's token
    r = client.put("/studies/RS/settings", json={"by": "dr_tanaka"}, headers=h)
    assert r.status_code == 403 and events[-1]["detail"]["route"] == "PUT /studies/{rs}/settings"
    for path in ("/jobs", "/registry", "/studies/RS/subjects"):
        assert client.get(path, headers=h).status_code == 403, path


@pytest.mark.parametrize("who", ["scheduler", "SYSTEM", " <Scheduler> "])
@pytest.mark.parametrize("caller", ["console", "mail-gateway"])
def test_an_internal_principal_is_refused_over_http(box: Any, who: str, caller: str) -> None:
    client, events, state = box
    body = {"type": "MICROBATCH" if caller == "console" else "SCREEN", "ruleset": "GZQO", "requested_by": who}
    r = client.post("/jobs", json=body, headers={sa.TOKEN_HEADER: _token(caller)})
    assert r.status_code == 403 and r.headers["X-TB-Refusal"] == "internal_principal"
    assert not state["created"]
    assert events[-1]["kind"] == "service.route_refused"
    assert events[-1]["detail"]["reason"] == "internal_principal" and events[-1]["detail"]["service"] == caller


def test_an_internal_principal_is_refused_on_an_open_dev_box_too(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import app as oapp

    for var in ("TB_SERVICE_TOKEN", "TB_SERVICE_TOKEN_FILE", sa.REGISTRY_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TB_ENV", "DEV")
    events: list[dict[str, Any]] = []
    state: dict[str, Any] = {"job": _job(None), "created": []}
    monkeypatch.setattr(oapp, "orch", lambda: _fake(events, state))
    client = TestClient(oapp.app)
    r = client.post("/jobs", json={"type": "FEAS", "ruleset": "GZQO", "requested_by": "scheduler"})
    assert r.status_code == 403 and events[-1]["detail"] == {"service": "", "route": "POST /jobs", "path": "/jobs",
                                                             "reason": "internal_principal"}  # fmt: skip
    assert (
        client.post("/jobs", json={"type": "FEAS", "ruleset": "GZQO", "requested_by": "crc@x.test"}).status_code == 200
    )
    assert client.get("/registry/GZQO/events").status_code != 403  # no token on a DEV box: no identity, no gate


@pytest.mark.parametrize(
    ("env", "passes"), [("DEV", True), ("TEST", True), ("VALIDATION", False), ("PRODUCTION", False)]
)
def test_the_legacy_shared_token_only_in_dev_and_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: str, passes: bool
) -> None:
    from orchestrator import app as oapp

    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_ENV", env)
    events: list[dict[str, Any]] = []
    state: dict[str, Any] = {"job": _job(None), "created": []}
    monkeypatch.setattr(oapp, "orch", lambda: _fake(events, state))
    client = TestClient(oapp.app)
    shared = "t713-the-old-shared-token-0123456789"
    for mode in ("registry", "shared"):
        if mode == "registry":  # the legacy hash in a token registry
            monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
            _registry(tmp_path, monkeypatch, legacy=shared)
        else:  # a box before step 8: one shared token, no registry
            monkeypatch.delenv(sa.REGISTRY_ENV, raising=False)
            monkeypatch.setenv("TB_SERVICE_TOKEN", shared)
        r = client.get(f"/jobs/{ULID}", headers={sa.TOKEN_HEADER: shared})
        if passes:
            assert r.status_code == 200, mode
        else:
            assert r.status_code == 403 and r.headers["X-TB-Refusal"] == "caller_unverified", mode
            assert events[-1]["detail"]["reason"] == "caller_unverified" and events[-1]["actor"] == "service:legacy"
    assert client.get("/healthz").status_code in (200, 503)  # open to everyone


def test_a_refusal_stays_a_refusal_when_the_audit_fails(box: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator import app as oapp

    client, _, _ = box

    def broken() -> Any:
        raise RuntimeError("audit down")

    monkeypatch.setattr(oapp, "orch", broken)
    assert client.get("/registry", headers={sa.TOKEN_HEADER: _token("mail-gateway")}).status_code == 403


def test_options_and_unknown_paths_pass_the_gate_to_fastapi(box: Any) -> None:
    client, events, _ = box
    h = {sa.TOKEN_HEADER: _token("mail-gateway")}
    assert client.get("/no-such-route", headers=h).status_code == 404
    assert client.options("/registry", headers=h).status_code != 403
    assert not events


@pytest.mark.parametrize(
    ("doc", "why"),
    [
        ({"schema": "other"}, "not a tb-orchestrator-callers/1"),
        ({"schema": "tb-orchestrator-callers/1", "groups": {"a": ["GET /x"], "b": ["GET /x"]}}, "two groups"),
        ({"schema": "tb-orchestrator-callers/1", "groups": {"a": ["FETCH /x"]}}, "METHOD /path"),
        ({"schema": "tb-orchestrator-callers/1", "groups": {"a": "GET /x"}}, "a list"),
        ({"schema": "tb-orchestrator-callers/1", "services": {"s": {"groups": ["nope"]}}}, "unknown groups"),
        ({"schema": "tb-orchestrator-callers/1", "services": {"s": {"own_jobs": "all"}}}, "own_jobs"),
        ({"schema": "tb-orchestrator-callers/1", "services": {"s": {"principals": ["x"]}}}, "in-process row holds"),
        (
            {
                "schema": "tb-orchestrator-callers/1",
                "groups": {"a": ["GET /x"]},
                "services": {"s": {"groups": ["a"], "in_process": True}},
            },
            "reaches no HTTP route",
        ),
        ({"schema": "tb-orchestrator-callers/1", "services": {"s": ["a"]}}, "a mapping"),
    ],
)
def test_a_bad_table_is_refused(doc: dict[str, Any], why: str) -> None:
    from orchestrator.callers import TableError, parse

    with pytest.raises(TableError, match=why):
        parse(doc)


def test_an_unreadable_table_is_refused(tmp_path: Path) -> None:
    from orchestrator.callers import TableError, load

    with pytest.raises(TableError):
        load(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("groups: [unclosed", encoding="utf-8")
    with pytest.raises(TableError):
        load(bad)


def test_the_shipped_table_is_plain_yaml_with_a_schema() -> None:
    from orchestrator.callers import SCHEMA, TABLE_PATH

    assert yaml.safe_load(TABLE_PATH.read_text(encoding="utf-8"))["schema"] == SCHEMA
