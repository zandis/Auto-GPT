"""Egress allowlist rendering (deploy/egress.py; SPEC §2, §10.1) without root or docker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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
        ("criteria-compiler", "llm.example.com", 443),
        ("orchestrator", "twpas.nhi.example", 8443),
        ("adapter", "10.1.2.3", 1433),
    ]
    # unset variables add nothing; ClinicalTrials.gov only in live mode
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
