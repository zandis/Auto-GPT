"""Egress allowlist rendering (deploy/egress.py; SPEC §2, §10.1) without root or docker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _egress() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tb_egress", ROOT / "deploy" / "egress.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_egress"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_allowlist_from_env() -> None:
    eg = _egress()
    env = {
        "SMTP_HOST": "smtp.hospa.test",
        "SMTP_PORT": "587",
        "IMAP_HOST": "imap.hospa.test",
        "IMAP_PORT": "993",
        "CLOUD_LLM_BASE_URL": "https://llm.example.com/v1",
        "NHI_TWPAS_BASE_URL": "https://twpas.nhi.example:8443/api",
        "TB_CTGOV_MODE": "cassette",
        "EGRESS_EXTRA": "adapter=10.1.2.3:1433",
    }
    got = [(a.service, a.host, a.port) for a in eg.allowlist(env)]
    assert got == [
        ("mail-gateway", "smtp.hospa.test", 587),
        ("mail-gateway", "imap.hospa.test", 993),
        ("gateway", "llm.example.com", 443),  # v4: the cloud LLM is reached by tb-gateway only (NFR-B9)
        ("orchestrator", "twpas.nhi.example", 8443),
        ("adapter", "10.1.2.3", 1433),
    ]
    # unset variables add nothing; ClinicalTrials.gov only in live mode; no dev endpoint outside DEV
    assert [(a.service, a.host) for a in eg.allowlist({})] == [("criteria-compiler", "clinicaltrials.gov")]


def test_render_default_deny_and_rules() -> None:
    eg = _egress()
    box = eg.Box(
        subnets=["172.18.0.0/16", "172.19.0.0/16"],
        addresses={
            "orchestrator": ["172.18.0.5", "172.19.0.5"],
            "mail-gateway": ["172.19.0.7"],
            "lake": ["172.18.0.9"],
        },
    )
    allows = [
        eg.Allow("orchestrator", "twpas.nhi.example", 443, "NHI"),
        eg.Allow("mail-gateway", "smtp.hospa.test", 587, "mail"),
        eg.Allow("criteria-compiler", "llm.example.com", 443, "cloud"),  # not running -> skipped with a warning
        eg.Allow("mail-gateway", "nowhere.invalid", 25, "mail"),  # does not resolve -> skipped
    ]
    dns = {"twpas.nhi.example": ["203.0.113.10"], "smtp.hospa.test": ["10.0.0.25", "2001:db8::25"]}
    script, warnings = eg.render(box, allows, lambda h: dns.get(h, []))
    lines = script.splitlines()
    assert lines[:3] == [
        "table inet trialbox_egress",
        "delete table inet trialbox_egress",
        "table inet trialbox_egress {",
    ]
    assert "type filter hook forward priority -10; policy accept;" in script
    body = [ln.strip() for ln in lines]
    rules = [ln for ln in body if "accept comment" in ln or "drop comment" in ln]
    assert rules[0].startswith("ip saddr { 172.18.0.0/16, 172.19.0.0/16 } ip daddr { 172.18.0.0/16, 172.19.0.0/16 }")
    assert rules[1].startswith("ip saddr { 172.18.0.5, 172.19.0.5 } ip daddr { 203.0.113.10 } tcp dport 443 accept")
    assert rules[2].startswith("ip saddr { 172.19.0.7 } ip daddr { 10.0.0.25 } tcp dport 587 accept")
    assert rules[-1] == 'ip saddr { 172.18.0.0/16, 172.19.0.0/16 } counter drop comment "trialbox default deny"'
    assert len(rules) == 4  # no rule for the stopped compiler, the unresolvable host, or IPv6 without a v6 source
    assert any("criteria-compiler: no running container" in w for w in warnings)
    assert any("nowhere.invalid: does not resolve" in w for w in warnings)


def test_render_without_stack_warns() -> None:
    eg = _egress()
    script, warnings = eg.render(eg.Box(), [], lambda h: [])
    assert "drop" not in script and any("nothing is filtered" in w for w in warnings)


MODEL_ENV = {
    "TB_ENV": "DEV",
    "TB_EP_OPENROUTER_URL": "https://openrouter.example/api/v1",
    "TB_EP_EXTERNAL_URL": "https://vendor.example:8443/v1",
    "CLOUD_LLM_BASE_URL": "https://llm.example.com/v1",
    "SMTP_HOST": "smtp.hospa.test",
    "NHI_TWPAS_BASE_URL": "https://twpas.nhi.example/api",
}


@pytest.mark.req("NFR-B9", "SEC-40", "S1-06")
def test_only_the_gateway_gets_model_host_rules() -> None:
    """Rules come from models/routing.yaml; every model host (any zone, plus CLOUD_LLM_BASE_URL) is reachable
    only from the gateway container. The unapproved external endpoint (no G5 record) gets no rule at all."""
    eg = _egress()
    hosts = eg.model_hosts(MODEL_ENV)
    assert {"openrouter.example", "vendor.example", "llm.example.com", "llm-stub", "llm-service"} <= hosts
    allows = eg.allowlist(MODEL_ENV)
    model_rules = [a for a in allows if a.host in hosts]
    assert model_rules and {a.service for a in model_rules} == {"gateway"}
    assert ("gateway", "openrouter.example", 443) in [(a.service, a.host, a.port) for a in allows]
    assert "vendor.example" not in {a.host for a in allows}  # g5_record: null -> closed
    assert all(a.service != "gateway" or a.host in hosts for a in allows)
    # outside DEV the bake-off endpoint is closed too
    prod = eg.allowlist({**MODEL_ENV, "TB_ENV": "PRODUCTION"})
    assert "openrouter.example" not in {a.host for a in prod}
    # the rendered ruleset: model-host destinations appear only with the gateway's source addresses
    box = eg.Box(subnets=["172.18.0.0/16"], addresses={"gateway": ["172.18.0.2"], "orchestrator": ["172.18.0.3"]})
    dns = {"openrouter.example": ["198.51.100.7"], "llm.example.com": ["198.51.100.8"]}
    script, _ = eg.render(box, allows, lambda h: dns.get(h, []))
    for line in script.splitlines():
        if "198.51.100.7" in line or "198.51.100.8" in line:
            assert "saddr { 172.18.0.2 }" in line and "gateway ->" in line


@pytest.mark.req("NFR-B9", "SEC-40")
def test_egress_extra_cannot_give_another_container_a_model_host() -> None:
    eg = _egress()
    for item in (
        "orchestrator=openrouter.example:443",
        "criteria-compiler=llm.example.com:443",
        "hermes=llm-stub:8000",
    ):
        with pytest.raises(SystemExit, match="model host"):
            eg.allowlist({**MODEL_ENV, "EGRESS_EXTRA": item})
    ok = eg.allowlist({**MODEL_ENV, "EGRESS_EXTRA": "gateway=llm2.example:443,adapter=10.1.2.3:1433"})
    assert ("adapter", "10.1.2.3", 1433) in [(a.service, a.host, a.port) for a in ok]
