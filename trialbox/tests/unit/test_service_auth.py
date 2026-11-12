"""D-114: the orchestrator's changing calls need the box's service token; the audit actor comes from X-TB-Actor."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tb_common import service_auth as sa
from tb_common.http import ServiceClient

from tests.service_tokens import per_service_tokens, token_of

TOKEN = token_of("console")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from orchestrator import app as oapp

    return TestClient(oapp.app)


def test_changing_calls_need_the_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    body = {"pid": "PID-00000001"}
    r = client.post("/jobs/J1/reveal", json=body)
    assert r.status_code == 401 and "X-TB-Service-Token" in r.json()["detail"]
    r = client.post("/jobs/J1/reveal", json=body, headers={sa.TOKEN_HEADER: "wrong"})
    assert r.status_code == 403
    for path in ("/jobs", "/notices", "/jobs/J1/cancel", "/registry/X", "/studies"):
        assert client.post(path, json={}).status_code == 401, path
    # with the token the call reaches the route (an unknown route answers 404, not 401/403)
    assert client.post("/no-such-route", json={}, headers={sa.TOKEN_HEADER: TOKEN}).status_code == 404


def test_no_token_fails_closed_outside_dev_and_test(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert client.post("/no-such-route", json={}).status_code == 503
    monkeypatch.setenv("TB_SERVICE_TOKEN", "change-me-service-token")  # the .env.example placeholder is no token
    assert client.post("/no-such-route", json={}).status_code == 503
    monkeypatch.setenv("TB_ENV", "TEST")
    assert client.post("/no-such-route", json={}).status_code == 404
    monkeypatch.delenv("TB_ENV")
    assert client.post("/no-such-route", json={}).status_code == 503  # unset TB_ENV is PRODUCTION


def test_reads_need_the_token_too(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan v4 F4 (D-130): jobs, outputs, registry and study reads are patient level; only /healthz stays open."""
    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert client.get("/healthz").status_code not in (401, 403)
    for path in ("/jobs", "/jobs/J1", "/registry", "/registry/GZQO", "/registry/GZQO/events", "/models",
                 "/rulesets/GZQO", "/studies", "/api/v1/studies/GZQO/forms"):  # fmt: skip
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={sa.TOKEN_HEADER: "wrong"}).status_code == 403, path
    assert client.head("/jobs").status_code == 401
    assert client.get("/no-such-route", headers={sa.TOKEN_HEADER: TOKEN}).status_code == 404  # reached the router


def test_reads_without_a_token_open_only_in_dev_and_test(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("TB_SERVICE_TOKEN_FILE", raising=False)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert client.get("/no-such-route").status_code == 503
    for env in ("DEV", "TEST"):
        monkeypatch.setenv("TB_ENV", env)
        assert client.get("/no-such-route").status_code == 404


def test_token_from_file(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    f = tmp_path / "service_token"
    f.write_text(TOKEN + "\n")
    monkeypatch.setenv("TB_SERVICE_TOKEN_FILE", str(f))
    assert sa.service_token() == TOKEN
    assert sa.check("POST", TOKEN, "PRODUCTION") is None


_LIMITS: dict[str, Any] = {}


def limits_store() -> Any:
    """T-103 (D-438): the orchestrator's identifier caps live in its store (``orch.id_limits``); a fake box keeps them
    in this test's own database, one store per test database."""
    import os

    from orchestrator.db import JobDB

    url = os.environ["TB_DB_URL"]
    if url not in _LIMITS:
        _LIMITS[url] = JobDB()
    return _LIMITS[url]


def _fake_box(events: list[dict[str, Any]]) -> SimpleNamespace:
    import json as _json

    out = SimpleNamespace(filename="candidate_list_RS_v1.json", minio_key="outputs/J1/candidate_list_RS_v1.json")
    job = SimpleNamespace(type="SCREEN", state="done", ruleset="RS", outputs=[out])
    lists = {out.minio_key: _json.dumps({"rows": [{"pid": "PID-00000001"}, {"pid": "PID-00000002"}]}).encode()}
    return SimpleNamespace(
        db=SimpleNamespace(get=lambda _id: job, url=None, take_limit=limits_store().take_limit),
        _now=lambda: datetime.now(UTC),
        cfg=SimpleNamespace(env=SimpleNamespace(secrets_dir="/nonexistent")),
        audit=SimpleNamespace(append=lambda kind, **kw: events.append({"kind": kind, **kw})),
        store=SimpleNamespace(get=lambda key: lists[key]),
    )


def test_reveal_only_for_a_patient_on_the_jobs_list_and_at_a_bounded_rate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Security review 2026-11-08 F-03: reveal used to resolve any pseudonym in the hospital through any job."""
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    per_service_tokens(tmp_path, monkeypatch)  # D-464: in PRODUCTION the orchestrator names its caller
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "2")
    monkeypatch.setattr(oapp, "REVEALS", oapp.RevealLimit())
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(oapp, "orch", lambda: _fake_box(events))
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids, _url=None: {p: "MRN-1" for p in pids})
    # D-447 (SEC-17): an assertion is accepted once, so each call signs again (``resign``), as the console does
    h = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("crc1", role="coordinator", scope="*")}
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-99999999"}, headers=sa.resign(h))
    assert r.status_code == 403 and events[-1]["kind"] == "screen.reveal_refused"
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=sa.resign(h)).status_code == 200
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000002"}, headers=sa.resign(h)).status_code == 200
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=sa.resign(h))
    assert r.status_code == 429 and events[-1]["detail"]["reason"] == "rate limit"
    other = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("crc2", role="coordinator", scope="*")}
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=other).status_code == 200


def test_reveal_audits_the_header_actor_not_the_body(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    per_service_tokens(tmp_path, monkeypatch)  # D-464: in PRODUCTION the orchestrator names its caller
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    events: list[dict[str, Any]] = []
    fake = _fake_box(events)
    monkeypatch.setattr(oapp, "orch", lambda: fake)
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids, _url=None: {p: "MRN-1" for p in pids})
    ok = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("山田 花子", role="investigator", scope="RS")}
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001", "by": "someone-else"}, headers=ok)
    assert r.status_code == 200 and r.json()["mrn"] == "MRN-1"
    assert events[-1]["actor"] == "山田 花子"  # from the authenticated header, the body's "by" is ignored
    # a token holder that names no user is refused, and nothing is revealed
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001", "by": "x"}, headers={sa.TOKEN_HEADER: TOKEN})
    assert r.status_code == 400 and len(events) == 1


def test_service_client_sends_the_token_to_every_trialbox_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    seen: dict[str, httpx.Headers] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen[req.url.host] = req.headers
        return httpx.Response(200, json={})

    for host, service in (("orchestrator", "orchestrator"), ("mail", "mail-gateway")):
        c = ServiceClient(f"http://{host}", service, retries=0)
        c.client = httpx.Client(transport=httpx.MockTransport(handler))
        c.post_raw("/x", {}, sa.actor_header("佐藤"))
    assert seen["orchestrator"][sa.TOKEN_HEADER] == TOKEN
    assert sa.actor_of(seen["orchestrator"][sa.ACTOR_HEADER], None) == "佐藤"
    assert seen["mail"][sa.TOKEN_HEADER] == TOKEN  # D-127 (F-11): every service checks it now


def test_a_token_holder_cannot_name_a_user_or_reset_the_cap_and_exports_are_audited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Review 2026-11-09 S-09 (D-143): an unsigned X-TB-Actor is refused and audited; the reveal cap is per verified
    person; the screening-log export with chart numbers needs a signed user, is audited with the file's sha256 and
    is capped."""
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    per_service_tokens(tmp_path, monkeypatch)  # D-464: in PRODUCTION the orchestrator names its caller
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_REVEAL_MAX_PER_HOUR", "1")
    monkeypatch.setenv("TB_EXPORT_MAX_PER_HOUR", "1")
    monkeypatch.setattr(oapp, "REVEALS", oapp.RevealLimit())
    monkeypatch.setattr(oapp, "EXPORTS", oapp.RevealLimit("TB_EXPORT_MAX_PER_HOUR", 10))
    events: list[dict[str, Any]] = []
    fake = _fake_box(events)
    monkeypatch.setattr(oapp, "orch", lambda: fake)
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids, _url=None: {p: "MRN-1" for p in pids})
    unsigned = {sa.TOKEN_HEADER: TOKEN, sa.ACTOR_HEADER: "dr_tanaka"}
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=unsigned)
    assert r.status_code == 403 and events[-1]["kind"] == "actor.refused"
    # D-447 (SEC-17): each call carries its own assertion (``resign``); the person and session stay the same
    signed = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("dr_tanaka", "s1", role="investigator", scope="GZQO,RS")}
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=sa.resign(signed)).status_code == 200
    assert events[-1]["detail"]["session"] == "s1" and events[-1]["detail"]["verified"] is True
    # a new session is the same person
    again = {sa.TOKEN_HEADER: TOKEN, **sa.actor_header("dr_tanaka", "s2", role="investigator", scope="GZQO,RS")}
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000002"}, headers=again).status_code == 429
    monkeypatch.setattr(oapp, "registry_of", lambda _o: SimpleNamespace(export_xlsx=lambda _rs, _site: b"PK-xlsx"))
    fake.cfg = SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(id="S1")), env=fake.cfg.env)
    assert client.get("/registry/GZQO/export.xlsx", headers={sa.TOKEN_HEADER: TOKEN}).status_code == 400
    assert client.get("/registry/GZQO/export.xlsx", headers=unsigned).status_code == 403
    r = client.get("/registry/GZQO/export.xlsx", headers=sa.resign(signed))
    assert r.status_code == 200 and r.content == b"PK-xlsx"
    ev, flow = events[-2], events[-1]  # D-149: the export ledger row follows the export event
    assert ev["kind"] == "registry.export" and ev["actor"] == "dr_tanaka" and ev["output_sha"]
    assert flow["kind"] == "flow.export" and flow["output_sha"] == ev["output_sha"]
    assert flow["detail"]["identifier_level"] == "identified"
    assert client.get("/registry/GZQO/export.xlsx", headers=sa.resign(signed)).status_code == 429
    assert events[-1]["kind"] == "registry.export_refused"
