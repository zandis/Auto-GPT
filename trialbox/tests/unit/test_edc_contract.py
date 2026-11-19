"""Contract version 1 with the internal EDC (D-1042): schedule, events, map, tools, OIDC, and the study read.

The demo path is the unset backend. These tests set the variables themselves.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from pathlib import Path

import pytest
from edc_backend import linkmap
from edc_backend.connection import connect
from edc_backend.study import accept_version
from fastapi.testclient import TestClient
from orchestrator.study_api import StudyService
from rc_bridge.client import RcError, RedcapClient
from rc_sim.app import create_app

from tests.rc_kit import TOKEN_A

pytestmark = pytest.mark.nodb

BODY = {
    "spec": "trialbox.edc.event.v1",
    "id": "11111111-1111-1111-1111-111111111111",
    "type": "record.saved",
    "project_id": "proj-1",
    "record_id": "1001",
    "occurred_at": "2026-11-16T00:00:00Z",
    "data": {"instrument": "adverse_event"},
}


def _sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class _Store:
    def token(self, ref: str) -> str | None:
        return TOKEN_A if ref == "main" else None


def test_unset_backend_still_rejects_an_unsupported_redcap(monkeypatch: pytest.MonkeyPatch) -> None:
    # E-EDCB-1: master's study link accepts 13 since RC13-F (D-852, the owner's D-1024); 12 is still refused
    monkeypatch.delenv("TB_EDC_BACKEND", raising=False)
    app = create_app(version="12.5.0")
    http = TestClient(app, base_url="http://rc")
    rc = RedcapClient("https://rc.example/", TOKEN_A, http=http)
    rc.url = "/api/"
    with pytest.raises(RcError) as err:
        accept_version(rc)
    assert err.value.code == "RC-VERSION"


def test_the_study_link_uses_the_backend_and_accepts_13(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_EDC_BACKEND", "internal")
    monkeypatch.setenv("TB_EDC_INTERNAL_URL", "inproc://rc-sim")
    monkeypatch.setenv("TB_EDC_INTERNAL_TOKEN", TOKEN_A)
    from rc_sim.app import app as default_app
    from rc_sim.app import register_inproc

    register_inproc(create_app(version="13.7.23"))
    svc = StudyService(store=_Store(), registry=None, audit=None, now=datetime.now)  # type: ignore[arg-type]
    rc = svc.client("main")
    try:
        assert rc.url == "/api/"
        assert svc._version(rc) == "13.7.23"
    finally:
        rc.close()
        register_inproc(default_app)


def test_an_empty_project_gains_arms_and_events() -> None:
    app = create_app()
    http = TestClient(app, base_url="http://rc")
    made = http.post(
        "/sim/projects",
        json={"title": "empty", "metadata": [{"field_name": "record_id", "form_name": "visit", "field_type": "text"}]},
    ).json()
    conn = connect(
        {"TB_EDC_BACKEND": "redcap", "TB_REDCAP_API_URL": "https://rc.example/", "TB_REDCAP_API_TOKEN": made["token"]},
        http=http,
    )
    assert conn is not None
    conn.client.url = "/api/"
    out = conn.ensure_schedule(
        arms=[{"arm_num": 1, "name": "Main"}],
        events=[{"arm_num": 1, "unique_event_name": "week1_arm_1", "event_name": "Week 1", "day_offset": 7}],
        mapping=[{"arm_num": 1, "unique_event_name": "week1_arm_1", "form": "visit"}],
    )
    assert out["arms"]["count"] == 1 and out["events"]["count"] == 1
    assert conn.events()[0]["unique_event_name"] == "week1_arm_1"
    assert conn.arms()[0]["name"] == "Main"


def test_the_map_joins_a_project_to_a_study(tmp_path: Path) -> None:
    linkmap.save(
        str(tmp_path),
        {"studies": {"gzqo": "proj-1"}, "sites": {"linkou": "dag_linkou"}, "subjects": {"GZQO": {"S-1": "1001"}}},
    )
    assert linkmap.study_for_project(str(tmp_path), "proj-1") == "GZQO"
    saved = linkmap.load(str(tmp_path))
    assert saved["sites"]["linkou"] == "dag_linkou" and saved["subjects"]["GZQO"]["S-1"] == "1001"
