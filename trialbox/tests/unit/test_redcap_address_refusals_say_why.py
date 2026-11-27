"""E2E P-13: the REDCap link refused without a remedy or without a word.

* ``/admin/redcap`` with an ``http://`` address re-rendered the page with no message: the connector's refusal came
  back as ``RC-UPSTREAM`` (HTTP 502, "REDCap did not answer"), so the console showed only "unavailable". It is the
  form's error (``RC-FIELD``, 400) with the connector's own reason, which the page prints ("Check the form: ...").
* A study link to a REDCap on a private address was refused "the REDCap address is not allowed (private)" with nothing
  about the box's egress table; the line now names the remedy. On-premise REDCap normally sits on a private address.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from console.i18n_step3 import EN as STEP3_EN
from edc_backend import tools as edc_tools
from fastapi import FastAPI
from orchestrator.study_api import router
from rc_bridge.client import HOSPITAL_NETWORK, refused_line
from tb_common.http import DECLARABLE, NEVER, EgressGuard, EgressRefused, address_class

from tests.actor3 import SignedClient
from tests.rc_kit import LINK_A, TOKEN_A, study_service


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


@pytest.mark.parametrize("url", ["https://[10.0.2.2:28443/redcap/", "https://[fd12::1]:port/redcap/"])
def test_a_malformed_address_is_the_form_s_error_never_a_500(tmp_path: Path, url: str) -> None:
    """Review L1: a malformed bracketed host (or port) is a 400 RC-FIELD with its reason, not a crash, and not saved."""
    with study_service(tmp_path) as (svc, _sim, _clock):
        app = FastAPI()
        app.include_router(router(lambda: svc))
        c = SignedClient(app)
        r = c.put("/redcap/connections/main", json={"url": url, "token": TOKEN_A, "by": "admin"})
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == {"code": "RC-FIELD", "message": "the REDCap URL is not a valid address"}
        saved = [x["token_ref"] for x in c.get("/redcap/connections").json()["connections"]]
        assert "main" not in saved


@pytest.mark.parametrize("reason", ["private", "shared"])
def test_a_refused_hospital_address_names_the_egress_table(reason: str) -> None:
    line = refused_line(EgressRefused("10.0.2.2", reason, "not declared"))
    assert f"not allowed ({reason}): 10.0.2.2" in line
    assert "EGRESS_EXTRA=orchestrator=<host>:<port>" in line and "deploy/network.sh apply" in line


@pytest.mark.parametrize("reason", ["metadata", "link_local", "scheme", "does_not_resolve", "loopback", "reserved"])
def test_an_address_never_allowed_gets_no_such_remedy(reason: str) -> None:
    assert "EGRESS_EXTRA" not in refused_line(EgressRefused("169.254.169.254", reason, "x"))


PROD = {"TB_ENV": "PRODUCTION"}


def test_the_remedy_names_classes_the_guard_really_gives() -> None:
    """Review M1: the remedy's classes are the guard's own declarable ones, and every class the guard gives is
    public, declarable or never: none can fall between them."""
    assert set(HOSPITAL_NETWORK) <= set(DECLARABLE) and "loopback" not in HOSPITAL_NETWORK
    samples = ("10.0.2.2", "172.16.5.4", "192.168.1.9", "fd12::1", "100.64.3.2", "127.0.0.1", "::1", "240.0.0.1",
               "169.254.169.254", "169.254.1.1", "0.0.0.0", "224.0.0.1", "255.255.255.255", "8.8.8.8")  # fmt: skip
    got = {address_class(a) for a in samples}
    assert got <= {"public", *DECLARABLE, *NEVER} and {"private", "shared", "loopback"} <= got


@pytest.mark.parametrize(
    ("url", "reason", "remedy"),
    [
        ("https://10.0.2.2:28443/redcap/api/", "private", True),
        ("https://100.64.3.2/redcap/api/", "shared", True),
        ("https://127.0.0.1:8001/redcap/api/", "loopback", False),
        ("https://169.254.169.254/latest/", "metadata", False),
    ],
)
def test_the_real_guard_refusal_gets_the_remedy_only_on_the_hospital_network(
    url: str, reason: str, remedy: bool
) -> None:
    with pytest.raises(EgressRefused) as got:
        EgressGuard("orchestrator", env=PROD).check(url)
    assert got.value.reason == reason
    assert ("EGRESS_EXTRA=orchestrator=<host>:<port>" in refused_line(got.value)) is remedy


def test_the_remedy_it_names_lets_the_address_through() -> None:
    """Review M2: EGRESS_EXTRA=orchestrator=<host>:<port> is the table's real syntax: declared, the call may go."""
    env = {**PROD, "EGRESS_EXTRA": "orchestrator=10.0.2.2:28443"}
    assert EgressGuard("orchestrator", env=env).check("https://10.0.2.2:28443/redcap/api/") == "10.0.2.2"
    with pytest.raises(EgressRefused):  # the box's own loopback stays refused unless declared, and is never advised
        EgressGuard("orchestrator", env=env).check("https://127.0.0.1:28443/redcap/api/")


def test_the_admin_test_and_the_study_link_meet_the_same_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P-13 ruling: the administrator's connection test is not outside the egress guard. Both it and the study link
    to an undeclared hospital address are refused by the guard with the same line, before anything is sent."""
    for k in ("EGRESS_EXTRA", "TB_EDC_BACKEND", "EDC_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TB_SERVICE_NAME", "orchestrator")
    with study_service(tmp_path) as (svc, _sim, _clock):
        svc.store.save_connection("main", "https://10.0.2.2:28443/redcap", "admin", "2026-11-07T20:00:00+09:00")
        svc.store.put_token("main", TOKEN_A)
        app = FastAPI()
        app.include_router(router(lambda: svc))
        c = SignedClient(app)
        admin = c.post("/redcap/connections/main/test")
        link = c.put("/studies/GZQO/redcap-link", json={"link": {**LINK_A, "token_ref": "main"}, "by": "crc"})
        for r in (admin, link):
            assert r.status_code == 502, r.text
            assert r.json()["detail"]["code"] == "RC-UPSTREAM"
            assert "not allowed (private): 10.0.2.2" in r.json()["detail"]["message"]
            assert "EGRESS_EXTRA=orchestrator=<host>:<port>" in r.json()["detail"]["message"]  # review M3
            assert "deploy/network.sh apply" in r.json()["detail"]["message"]
        assert admin.json()["detail"]["message"] == link.json()["detail"]["message"]


def test_the_edc_admin_connection_check_goes_through_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """P-13 ruling: ``/admin/edc``'s connection check (the tool door's client) was a plain client, outside the guard.
    It is the guarded client now: its own declared host only, never metadata, never http on a production box."""
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_SERVICE_NAME", "console")
    monkeypatch.delenv("EGRESS_EXTRA", raising=False)
    monkeypatch.setenv("TB_EDC_TOOL_URL", "https://169.254.169.254")
    with edc_tools.http_client() as http, pytest.raises(EgressRefused) as got:
        http.get("https://169.254.169.254/api/v1/capabilities")
    assert got.value.reason == "metadata"
    monkeypatch.setenv("TB_EDC_TOOL_URL", "https://10.0.2.3:8443")
    with edc_tools.http_client() as http:
        with pytest.raises(EgressRefused) as other:  # another private address than the one the operator set
            http.get("https://10.0.2.4:8443/api/v1/capabilities")
        assert other.value.reason == "private"
        with pytest.raises(EgressRefused) as plain:
            http.get("http://10.0.2.3:8443/api/v1/capabilities")
        assert plain.value.reason == "http_outside_dev"
    status = edc_tools.connection_status("https://10.0.2.4:8443", "tool-token", edc_tools.http_client())
    assert status["reachable"] is False and "did not answer" in status["reason"]
    assert isinstance(other.value, httpx.ConnectError)  # caught where any connection failure is


def test_the_edc_tool_route_reaches_only_the_configured_edc_host() -> None:
    """P-13 ruling: ``edc.tool`` goes to the site's configured EDC host only, is recorded as itself (never
    ``edc.write``), and with no EDC configured nothing leaves."""
    from tb_common import egress_edge

    class Audit:
        def __init__(self) -> None:
            self.lines: list[dict[str, object]] = []

        def append(self, event: str, **kw: object) -> None:
            self.lines.append({"event": event, **kw})

    audit = Audit()
    assert egress_edge.leave("edc.tool", "edc.example", "", audit=audit, actor="console", named=["edc.example"]) == ""
    for host, named in (("other.example", ["edc.example"]), ("169.254.169.254", ["edc.example"]),
                        ("edc.example", []), ("", [])):  # fmt: skip
        with pytest.raises(egress_edge.Refused) as got:
            egress_edge.leave("edc.tool", host, "", audit=audit, actor="console", named=named)
        assert got.value.reason == "not_named"
    rows = [x["detail"] for x in audit.lines]
    assert [r["route"] for r in rows] == ["edc.tool"] * 5
    assert [r["result"] for r in rows] == ["sent"] + ["refused"] * 4
