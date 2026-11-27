"""E2E P-13: the REDCap link refused without a remedy or without a word.

* ``/admin/redcap`` with an ``http://`` address re-rendered the page with no message: the connector's refusal came
  back as ``RC-UPSTREAM`` (HTTP 502, "REDCap did not answer"), so the console showed only "unavailable". It is the
  form's error (``RC-FIELD``, 400) with the connector's own reason, which the page prints ("Check the form: ...").
* A study link to a REDCap on a private address was refused "the REDCap address is not allowed (private)" with nothing
  about the box's egress table; the line now names the remedy. On-premise REDCap normally sits on a private address.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from console.i18n_step3 import EN as STEP3_EN
from fastapi import FastAPI
from orchestrator.study_api import router
from rc_bridge.client import refused_line
from tb_common.http import EgressRefused

from tests.actor3 import SignedClient
from tests.rc_kit import TOKEN_A, study_service


def test_an_http_address_is_the_form_s_error_with_its_reason(tmp_path: Path) -> None:
    with study_service(tmp_path) as (svc, _sim, _clock):
        app = FastAPI()
        app.include_router(router(lambda: svc))
        c = SignedClient(app)
        body = {"url": "http://10.0.2.2:28080/redcap/", "token": TOKEN_A, "by": "admin"}
        r = c.put("/redcap/connections/main", json=body)
        assert r.status_code == 400, r.text
        assert r.json()["detail"]["code"] == "RC-FIELD" and "https://" in r.json()["detail"]["message"]
        assert "{msg}" in STEP3_EN["rc.err.RC-FIELD"]  # the admin page prints the reason
        saved = [x["token_ref"] for x in c.get("/redcap/connections").json()["connections"]]
        assert "main" not in saved  # nothing saved


@pytest.mark.parametrize("reason", ["private", "loopback", "shared", "reserved"])
def test_a_refused_hospital_address_names_the_egress_table(reason: str) -> None:
    line = refused_line(EgressRefused("10.0.2.2", reason, "not declared"))
    assert f"not allowed ({reason}): 10.0.2.2" in line
    assert "EGRESS_EXTRA=orchestrator=<host>:<port>" in line and "deploy/network.sh apply" in line


@pytest.mark.parametrize("reason", ["metadata", "link_local", "scheme", "does_not_resolve"])
def test_an_address_never_allowed_gets_no_such_remedy(reason: str) -> None:
    assert "EGRESS_EXTRA" not in refused_line(EgressRefused("169.254.169.254", reason, "x"))
