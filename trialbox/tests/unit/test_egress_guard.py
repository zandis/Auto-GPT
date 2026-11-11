"""T-212d (D-450): the one SSRF guard of ``tb_common.http`` and the callers that use it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from tb_common import http as tbh

ROOT = Path(__file__).resolve().parents[2]
PROD = {"TB_ENV": "PRODUCTION"}


def _dns(table: dict[str, list[str]]) -> tbh.Resolver:
    def resolve(host: str, port: int) -> list[str]:
        try:
            return tbh.resolve_now(host, port) if host[0].isdigit() or ":" in host else table.get(host, [])
        except IndexError:
            return []

    return resolve


def _guard(env: dict[str, str] | None = None, dns: dict[str, list[str]] | None = None, **kw: Any) -> tbh.EgressGuard:
    return tbh.EgressGuard(kw.pop("service", "orchestrator"), env=env or PROD, resolver=_dns(dns or {}), **kw)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://127.0.0.1/", "loopback"),
        ("https://10.0.0.5/api/", "private"),
        ("https://172.18.0.4:8010/", "private"),
        ("https://192.168.1.10/", "private"),
        ("https://169.254.169.254/latest/meta-data/", "metadata"),
        ("https://169.254.10.1/", "link_local"),
        ("https://100.100.100.200/", "metadata"),
        ("https://0.0.0.0/", "unspecified"),
        ("https://100.64.1.1/", "shared"),
        ("https://[::1]/", "loopback"),
        ("https://[fe80::1]/", "link_local"),
        ("https://[fd00:ec2::254]/", "metadata"),
        ("https://[fc00::5]/", "private"),
        ("https://[::ffff:127.0.0.1]/", "loopback"),
        ("https://[::ffff:169.254.169.254]/", "metadata"),
        ("https://[64:ff9b::a9fe:a9fe]/", "metadata"),  # NAT64 spelling of 169.254.169.254
        ("https://[2002:7f00:1::]/", "loopback"),  # 6to4 spelling of 127.0.0.1
        ("https://2130706433/", "odd_address"),  # decimal 127.0.0.1
        ("https://0x7f000001/", "odd_address"),  # hexadecimal
        ("https://0177.0.0.1/", "odd_address"),  # octal
        ("https://127.1/", "odd_address"),  # short form
        ("https://0xa9.0xfe.0xa9.0xfe/", "odd_address"),  # hexadecimal metadata
        ("http://93.184.216.34/", "http_outside_dev"),
        ("ftp://93.184.216.34/", "scheme"),
        ("https://nowhere.invalid/", "does_not_resolve"),
    ],
)
def test_internal_and_odd_addresses_are_refused(url: str, reason: str) -> None:
    with pytest.raises(tbh.EgressRefused) as exc:
        _guard().check(url)
    assert exc.value.reason == reason


def test_a_public_address_passes_and_is_the_one_connected_to() -> None:
    g = _guard(dns={"redcap.example.org": ["93.184.216.34"]})
    assert g.check("https://redcap.example.org/api/") == "93.184.216.34"
    assert g.check("https://[2606:4700::1111]/") == "2606:4700::1111"


def test_a_declared_lan_host_passes_but_never_to_metadata_or_link_local() -> None:
    env = {**PROD, "EGRESS_EXTRA": "orchestrator=redcap.hosp.lan:443,console=other.lan:443"}
    dns = {"redcap.hosp.lan": ["10.20.0.7"], "other.lan": ["10.20.0.8"]}
    g = _guard(env, dns)
    assert g.check("https://redcap.hosp.lan/api/") == "10.20.0.7"
    with pytest.raises(tbh.EgressRefused, match="not on the egress table"):
        g.check("https://redcap.hosp.lan:8443/api/")  # another port is another destination
    with pytest.raises(tbh.EgressRefused):
        g.check("https://other.lan/")  # the console's row, not the orchestrator's
    rebound = _guard(env, {"redcap.hosp.lan": ["169.254.169.254"]})
    with pytest.raises(tbh.EgressRefused) as exc:
        rebound.check("https://redcap.hosp.lan/api/")
    assert exc.value.reason == "metadata"


def test_one_bad_address_among_several_refuses_the_name() -> None:
    g = _guard(dns={"mixed.example.org": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(tbh.EgressRefused) as exc:
        g.check("https://mixed.example.org/")
    assert exc.value.reason == "loopback"


def test_http_only_in_dev_and_test() -> None:
    dev = _guard({"TB_ENV": "DEV"}, {"svc.example.org": ["93.184.216.34"]})
    assert dev.check("http://svc.example.org/") == "93.184.216.34"
    with pytest.raises(tbh.EgressRefused):
        dev.check("http://127.0.0.1/")  # DEV does not open the box


def test_the_address_is_resolved_at_connect_time_and_pinned() -> None:
    """DNS rebinding: the name answers a public address first and the box's address second; the second call is
    refused, and the first one connected to the address that was checked, with the name kept for Host and TLS."""
    answers = [["93.184.216.34"], ["127.0.0.1"]]
    seen: list[httpx.Request] = []

    def resolver(host: str, port: int) -> list[str]:
        return answers.pop(0)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    with tbh.guarded_client("orchestrator", env=PROD, resolver=resolver, inner=httpx.MockTransport(handler)) as c:
        assert c.get("https://rebind.example.org/x").status_code == 200
        with pytest.raises(tbh.EgressRefused):
            c.get("https://rebind.example.org/x")
    assert len(seen) == 1
    assert seen[0].url.host == "93.184.216.34" and seen[0].headers["host"] == "rebind.example.org"
    assert seen[0].extensions["sni_hostname"] == "rebind.example.org"


def test_a_redirect_to_an_internal_address_is_refused() -> None:
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        if request.url.path == "/hop":
            return httpx.Response(302, headers={"Location": "https://[::1]:8010/v1/jobs"})
        return httpx.Response(200)

    dns = _dns({"public.example.org": ["93.184.216.34"]})
    env = {"TB_ENV": "DEV"}
    with tbh.guarded_client("orchestrator", env=env, resolver=dns, inner=httpx.MockTransport(handler),
                            follow_redirects=True) as c:  # fmt: skip
        with pytest.raises(tbh.EgressRefused) as exc:
            c.get("https://public.example.org/start")
        assert exc.value.reason == "metadata"
        with pytest.raises(tbh.EgressRefused) as exc:
            c.get("https://public.example.org/hop")
        assert exc.value.reason == "loopback"
    assert all("169.254" not in h and "[::1]" not in h for h in hits)


def test_proxy_variables_are_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    c = tbh.guarded_client("orchestrator", env=PROD)
    assert not c._mounts and c._trust_env is False  # a proxy would connect on the guard's behalf
    c.close()


def test_the_declared_table_matches_the_box_egress_table() -> None:
    """``declared_egress`` reads the same settings as ``deploy/egress.py`` (the gateway's model hosts aside)."""
    from tests.unit.test_egress_rules import _egress

    egress = _egress()
    env = {
        "SMTP_HOST": "smtp.hosp.lan", "IMAP_HOST": "imap.hosp.lan", "IMAP_PORT": "143", "TB_CTGOV_MODE": "live",
        "NHI_TWPAS_BASE_URL": "https://twpas.nhi.example/fhir",
        "EGRESS_EXTRA": "orchestrator=redcap.hosp.lan:443,authelia=ldap.hosp.lan:636",
    }  # fmt: skip
    rows = [a for a in egress.allowlist(env, routing=None) if a.service != egress.GATEWAY]
    for svc in {a.service for a in rows} | {"console", "gateway"}:
        want = {(a.host, a.port) for a in rows if a.service == svc}
        assert tbh.declared_egress(svc, env) == want, svc


def test_redcap_client_uses_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from rc_bridge.client import RcError, RedcapClient

    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setenv("TB_SERVICE_NAME", "orchestrator")
    monkeypatch.delenv("EGRESS_EXTRA", raising=False)
    rc = RedcapClient("https://169.254.169.254/", "0" * 32)
    assert isinstance(rc.http._transport, tbh.GuardedTransport)
    with pytest.raises(RcError, match="not allowed") as exc:
        rc._send("version")
    assert exc.value.code == "RC-UPSTREAM"
    rc.close()


def test_ctgov_live_and_nhi_submit_use_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from criteria_compiler import ctgov
    from tb_contracts import CtgovSearchRequest

    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    cg = ctgov.CtGov(mode="live", base_url="https://127.0.0.1:8010/api/v2")
    with pytest.raises(ctgov.CtgovError, match="not allowed"):
        cg._live(CtgovSearchRequest(condition="asthma"))

    from orchestrator.scenarios import submit

    with pytest.raises(submit.NotSubmitted, match="not allowed"):
        submit.post_bundle("https://[::1]:8010/fhir", b"{}")


def test_oidc_discovery_and_the_endpoints_it_names_use_the_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from console import oidc

    secret = tmp_path / "oidc_client_secret"
    secret.write_text("synthetic-client-secret\n")
    base = {"TB_OIDC_ENABLED": "1", "TB_OIDC_CLIENT_ID": "c", "TB_OIDC_CLIENT_SECRET_FILE": str(secret),
            "TB_OIDC_REDIRECT_URL": "https://tb.test/auth/oidc/callback", "TB_OIDC_LOGOUT_URL": "https://a.test/out",
            "TB_OIDC_GROUP_ROLES": "tb-crc:coordinator"}  # fmt: skip
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    st = oidc.OidcSettings.from_env({**base, "TB_OIDC_ISSUER": "https://169.254.169.254"})
    with pytest.raises(oidc.OidcError, match="not allowed"):
        oidc.OidcClient(st).metadata()  # the issuer is declared, but a metadata address never is a destination
    # a declared on-box issuer (Caddy's alias) passes; an endpoint its document points at the box does not
    client = oidc.OidcClient(oidc.OidcSettings.from_env({**base, "TB_OIDC_ISSUER": "https://auth.hosp.lan"}))
    guard = client._guard()
    guard.resolver = _dns({"auth.hosp.lan": ["172.18.0.9"], "evil.example.org": ["10.0.0.1"]})
    assert guard.check("https://auth.hosp.lan/.well-known/openid-configuration") == "172.18.0.9"
    with pytest.raises(tbh.EgressRefused):
        guard.check("https://evil.example.org/token")
