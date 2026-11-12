"""D-273 (PV-2, PV-4, PV-5, PV-15): the orchestrator's chart-number routes check the signed role and study scope,
refuse a NAV job and never reveal a patient on the opt-out register. Synthetic pseudonyms only."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import optout as optout_mod
from tb_common import service_auth as sa

from tests.actor3 import log_pi, reveal_headers
from tests.service_tokens import per_service_tokens, token_of
from tests.unit.test_service_auth import limits_store

TOKEN = token_of("console")  # D-464: a PRODUCTION orchestrator admits a caller it can name


def _box(events: list[dict[str, Any]], job_type: str = "SCREEN") -> SimpleNamespace:
    out = SimpleNamespace(filename="candidate_list_RS_v1.json", minio_key="outputs/J1/candidate_list_RS_v1.json")
    job = SimpleNamespace(type=job_type, state="done", ruleset="RS", outputs=[out])
    lists = {out.minio_key: json.dumps({"rows": [{"pid": "PID-00000001"}, {"pid": "PID-00000002"}]}).encode()}
    return SimpleNamespace(
        db=SimpleNamespace(get=lambda _id: job, url=None, take_limit=limits_store().take_limit),
        _now=lambda: datetime.now(UTC),
        today=lambda: date(2026, 11, 12),  # the site's day, for the delegation log (T-716)
        cfg=SimpleNamespace(
            env=SimpleNamespace(secrets_dir="/nonexistent"),
            settings=SimpleNamespace(site=SimpleNamespace(id="S1")),
        ),
        audit=SimpleNamespace(append=lambda kind, **kw: events.append({"kind": kind, **kw})),
        store=SimpleNamespace(get=lambda key: lists[key]),
    )


@pytest.fixture
def box(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[TestClient, list[dict[str, Any]], dict[str, Any]]:
    from orchestrator import app as oapp
    from orchestrator.scenarios import screen

    per_service_tokens(tmp_path, monkeypatch)
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


def _reveal(client: TestClient, pid: str = "PID-00000001", role: str = "coordinator", study: str = "RS",
            name: str = "crc1", **kw: Any) -> Any:  # fmt: skip
    """``POST /jobs/J1/reveal`` as a signed person (T-716, D-484: a v3 assertion for this request)."""
    body = {"pid": pid}
    headers = {sa.TOKEN_HEADER: TOKEN, **reveal_headers(study, "J1", body, sub=f"console:{name}", role=role, **kw)}
    return client.post("/jobs/J1/reveal", json=body, headers=headers)


def test_reveal_checks_the_signed_role_and_study(box: Any) -> None:
    client, events, _ = box
    # a role the matrix gives no identifiers: refused by the dependency, before the job is looked at
    for role in ("viewer", "cro", "admin", "steward", "breakglass"):  # D-280: never the administrator's own role;
        r = _reveal(client, role=role)  # T-716: and there is no role "breakglass" any more
        assert r.status_code == 403 and r.json()["detail"]["reason"] == "right", role
        assert events[-1]["kind"] == "actor.refused" and events[-1]["detail"]["action"] == "id.reveal"
    # the study of the claim is the job's study, or nothing is given
    for study in ("OTHER", ""):
        r = _reveal(client, study=study)
        assert r.status_code == 403, study
        assert events[-1]["kind"] == "screen.reveal_refused" and events[-1]["detail"]["reason"] == "study scope"
    # an investigator the study's delegation log does not name: the orchestrator reads the log itself
    r = _reveal(client, role="investigator", name="drsato")
    assert r.status_code == 403 and events[-1]["detail"]["reason"] == "delegation"
    assert not any(e["kind"] == "screen.reveal" for e in events)
    log_pi("drsato", "RS")
    assert _reveal(client, role="investigator", name="drsato").json()["mrn"] == "MRN-1"
    assert _reveal(client).json()["mrn"] == "MRN-1"  # the coordinator's row needs no log


def test_a_scope_that_is_not_signed_does_not_count(box: Any) -> None:
    """The older assertion, on the route that still takes it (the whole-list export)."""
    client, events, _ = box
    h = _h("coordinator", "OTHER")
    h[sa.SCOPE_HEADER] = "GZQO"  # widened after signing
    r = client.get("/registry/GZQO/export.xlsx", headers=h)
    assert r.status_code == 403 and events[-1]["kind"] == "actor.refused"


def test_reveal_refuses_a_nav_job(box: Any) -> None:
    client, _, state = box
    state["type"] = "NAV"
    assert _reveal(client).status_code == 409


def test_reveal_refuses_an_opted_out_patient(box: Any) -> None:
    """PV-4: a patient who opted out after the job ran is still on its list; the chart number is not given."""
    client, events, state = box
    state["gone"] = frozenset({"PID-00000001"})
    r = _reveal(client)
    assert r.status_code == 403 and events[-1]["detail"]["reason"] == "opted out"
    assert not any(e["kind"] == "screen.reveal" for e in events)
    assert _reveal(client, pid="PID-00000002").status_code == 200


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
