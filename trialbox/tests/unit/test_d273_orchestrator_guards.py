"""D-273 (PV-2, PV-4, PV-5, PV-15): the orchestrator's chart-number routes check the signed role and study scope,
refuse a NAV job and never reveal a patient on the opt-out register. Synthetic pseudonyms only."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import optout as optout_mod
from tb_common import service_auth as sa

TOKEN = "test-service-token-0123456789"


def _box(events: list[dict[str, Any]], job_type: str = "SCREEN") -> SimpleNamespace:
    out = SimpleNamespace(filename="candidate_list_RS_v1.json", minio_key="outputs/J1/candidate_list_RS_v1.json")
    job = SimpleNamespace(type=job_type, state="done", ruleset="RS", outputs=[out])
    lists = {out.minio_key: json.dumps({"rows": [{"pid": "PID-00000001"}, {"pid": "PID-00000002"}]}).encode()}
    return SimpleNamespace(
        db=SimpleNamespace(get=lambda _id: job, url=None),
        cfg=SimpleNamespace(
            env=SimpleNamespace(secrets_dir="/nonexistent"),
            settings=SimpleNamespace(site=SimpleNamespace(id="S1")),
        ),
        audit=SimpleNamespace(append=lambda kind, **kw: events.append({"kind": kind, **kw})),
        store=SimpleNamespace(get=lambda key: lists[key]),
    )


@pytest.fixture
def box(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list[dict[str, Any]], dict[str, Any]]:
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    monkeypatch.setenv("TB_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setattr(oapp, "REVEALS", oapp.RevealLimit())
    monkeypatch.setattr(oapp, "EXPORTS", oapp.RevealLimit("TB_EXPORT_MAX_PER_HOUR", 10))
    events: list[dict[str, Any]] = []
    state: dict[str, Any] = {"type": "SCREEN", "gone": frozenset()}
    monkeypatch.setattr(oapp, "orch", lambda: _box(events, state["type"]))
    monkeypatch.setattr(screen, "resolve_mrns", lambda _d, pids, _url=None: {p: "MRN-1" for p in pids})
    monkeypatch.setattr(optout_mod, "opted_out", lambda url=None, as_of=None: state["gone"])
    monkeypatch.setattr(oapp, "registry_of", lambda _o: SimpleNamespace(export_xlsx=lambda _rs, _site: b"PK-xlsx"))
    return TestClient(oapp.app), events, state


def _h(role: str = "coordinator", scope: str = "*", name: str = "crc1") -> dict[str, str]:
    return {sa.TOKEN_HEADER: TOKEN, **sa.actor_header(name, "s1", role=role, scope=scope)}


def test_reveal_checks_the_signed_role_and_study(box: Any) -> None:
    client, events, _ = box
    body = {"pid": "PID-00000001"}
    for role, scope, why in (
        ("viewer", "*", "role"),
        ("cro", "RS", "role"),
        ("", "*", "role"),  # a verified assertion must name the role
        ("coordinator", "OTHER", "study scope"),
        ("investigator", "", "study scope"),  # and the studies
    ):
        r = client.post("/jobs/J1/reveal", json=body, headers=_h(role, scope))
        assert r.status_code == 403, (role, scope)
        assert events[-1]["kind"] == "screen.reveal_refused" and events[-1]["detail"]["reason"] == why
    assert not any(e["kind"] == "screen.reveal" for e in events)
    for role, scope in (("coordinator", "*"), ("investigator", "OTHER,RS"), ("admin", "*")):
        r = client.post("/jobs/J1/reveal", json=body, headers=_h(role, scope))
        assert r.status_code == 200 and r.json()["mrn"] == "MRN-1", (role, scope)


def test_a_scope_that_is_not_signed_does_not_count(box: Any) -> None:
    client, events, _ = box
    h = _h("coordinator", "OTHER")
    h[sa.SCOPE_HEADER] = "RS"  # widened after signing
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=h)
    assert r.status_code == 403 and events[-1]["kind"] == "actor.refused"


def test_reveal_refuses_a_nav_job(box: Any) -> None:
    client, _, state = box
    state["type"] = "NAV"
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=_h())
    assert r.status_code == 409


def test_reveal_refuses_an_opted_out_patient(box: Any) -> None:
    """PV-4: a patient who opted out after the job ran is still on its list; the chart number is not given."""
    client, events, state = box
    state["gone"] = frozenset({"PID-00000001"})
    r = client.post("/jobs/J1/reveal", json={"pid": "PID-00000001"}, headers=_h())
    assert r.status_code == 403 and events[-1]["detail"]["reason"] == "opted out"
    assert not any(e["kind"] == "screen.reveal" for e in events)
    assert client.post("/jobs/J1/reveal", json={"pid": "PID-00000002"}, headers=_h()).status_code == 200


def test_registry_export_checks_the_signed_role_and_study(box: Any) -> None:
    """PV-5: a signed name alone no longer gets every chart number of a study."""
    client, events, _ = box
    for role, scope in (("viewer", "*"), ("cro", "GZQO"), ("coordinator", "OTHER"), ("investigator", "")):
        r = client.get("/registry/GZQO/export.xlsx", headers=_h(role, scope))
        assert r.status_code == 403, (role, scope)
        assert events[-1]["kind"] == "registry.export_refused"
    assert not any(e["kind"] == "registry.export" for e in events)
    r = client.get("/registry/GZQO/export.xlsx", headers=_h("investigator", "GZQO"))
    assert r.status_code == 200 and r.content == b"PK-xlsx"


def test_scope_helpers() -> None:
    assert sa.scope_of(()) == "*"
    assert sa.scope_of(("rs", "ABC", "RS")) == "ABC,RS"
    assert sa.in_scope("*", None) and sa.in_scope("ABC,RS", "rs")
    assert not sa.in_scope("ABC", "RS") and not sa.in_scope("ABC", None) and not sa.in_scope("", "RS")
    with pytest.raises(sa.ActorError):
        sa.verify_actor("crc1", None, scope="rs; drop")
