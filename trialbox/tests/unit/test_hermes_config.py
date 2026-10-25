"""Hermes configuration surface (spec v4 §9.2, §9.5, §9.6; S1-11, blocked on the pin).

What is testable without a pinned release: every hardening setting of the three profiles, the pin check against
``hermes.lock`` (the shipped lock is unpinned and must be refused), the relay adapter's envelope checks and the
``tb_policy_audit`` fail-closed hook. The ``tb_relay_adapter`` contract test against the release's plugin API (HER-7)
is a skeleton that skips until a release is vendored (``TB_HERMES_SRC``).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from frontdoor_mcp.policy import PROFILE_TOOLS

from integrations.hermes.lock import LOCK_PATH, HermesLock, pin_problems
from integrations.hermes.tb_policy_audit import TbPolicyAudit
from integrations.hermes.tb_relay_adapter import REQUIRED_HOOKS, EnvelopeRefused, TbRelayAdapter, contract_problems

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "integrations" / "hermes" / "profiles"
REQUIRED_DISABLED = {
    "terminal",
    "file",
    "browser",
    "web",
    "code_execution",
    "delegate",
    "cronjob",
    "skills_manage",
    "memory",
    "image_gen",
    "tts",
}
EXPECTED_TOOLS = {
    "tb-staff": PROFILE_TOOLS["email"],
    "tb-line": frozenset(),
    "tb-admin": PROFILE_TOOLS["admin_tui"],
}


def profile(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((PROFILES / name / "config.yaml").read_text(encoding="utf-8"))
    return doc


@pytest.mark.req("HER-1", "HER-2", "HER-3", "HER-5", "HER-20", "S1-11")
@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_profile_hardening_settings(name: str) -> None:
    c = profile(name)
    assert c["profile"] == name
    assert set(c["agent"]["disabled_toolsets"]) >= REQUIRED_DISABLED
    servers = c["mcp"]["servers"]
    assert list(servers) == ["frontdoor"] and c["mcp"]["catalogue"] is False
    fd = servers["frontdoor"]
    assert set(fd["tools"]["include"]) == EXPECTED_TOOLS[name]
    assert "tb.ops_read" not in fd["tools"]["include"] or name == "tb-admin"
    for off in ("prompts", "resources", "sampling", "elicitation"):
        assert fd[off] is False
    assert fd["mtls"]["client_cert"] and fd["timeout_s"] == 30
    a = c["approvals"]
    assert a["mode"] == "manual" and a["deny"] == ["*"]
    assert a["cron_mode"] == a["single_query_mode"] == a["unattended_mode"] == "deny"
    assert c["cron"] == {"allow_agent_scheduling": False, "jobs": []}
    assert c["memory"]["enabled"] is False and c["memory"]["external_providers"] == []
    assert c["delegation"]["max_spawn_depth"] == 0
    assert c["model"]["base_url"].startswith("http://gateway:") and c["model"]["fallback_providers"] == []
    assert c["model"]["context_length"] >= 65536
    assert c["plugins"]["allow"] == ["tb_relay_adapter", "tb_policy_audit"]
    assert c["plugins"]["project_plugins"] is False and c["plugins"]["hooks_auto_accept"] is False
    assert c["plugins"]["hook_callback_timeout"] == 5
    assert all(v is False for v in c["surfaces"].values()) and len(c["surfaces"]) == 6
    assert c["security"] == {"allow_lazy_installs": False, "private_urls": False}
    assert c["auth"]["adopt_external_logins"] is False
    assert {"HERMES_YOLO_MODE", "GATEWAY_ALLOW_ALL_USERS"} <= set(c["env"]["forbid"])


def _pinned(**over: Any) -> HermesLock:
    d = "sha256:" + "ab" * 32
    raw: dict[str, Any] = {
        "version": "v0.22.2",
        "tag": "v0.22.2",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
        "upstream_image": f"nousresearch/hermes-agent:v0.22.2@{d}",
        "upstream_digest": d,
        "mirror_image": f"registry.internal/hermes-agent@{d}",
        "mirror_digest": d,
        "verified": True,
    }
    raw.update(over)
    return HermesLock(raw)


@pytest.mark.req("HER-18", "ENG-08", "S1-11")
def test_pin_check_refuses_the_shipped_unpinned_lock() -> None:
    shipped = HermesLock.load(LOCK_PATH)
    problems = pin_problems(shipped)
    assert any("commit_sha" in p for p in problems) and any("digest" in p for p in problems)
    assert shipped.raw["status"] == "blocked"
    assert pin_problems(_pinned()) == []
    assert any("below the floor" in p for p in pin_problems(_pinned(version="v0.21.5", tag="v0.21.5")))
    assert any("differs" in p for p in pin_problems(_pinned(mirror_digest="sha256:" + "cd" * 32)))
    assert any("mutable" in p for p in pin_problems(_pinned(mirror_image="registry.internal/hermes-agent:v0.22.2")))
    assert any("running image" in p for p in pin_problems(_pinned(), running_digest="sha256:" + "ee" * 32))
    assert pin_problems(HermesLock({})) == ["hermes.lock missing or empty"]


@pytest.mark.req("HER-6", "S1-11")
def test_relay_adapter_accepts_only_relay_envelopes_with_an_assertion() -> None:
    replies: list[tuple[str, str]] = []
    ad = TbRelayAdapter(lambda conv, text: replies.append((conv, text)))
    good = {
        "origin": "channel-relay",
        "conv": "c1",
        "msg_sha256": "s",
        "channel": "email",
        "assertion": "a.b.c",
        "text": "這個試驗做得起來嗎",
    }
    assert ad.accept(good).conv == "c1"
    for bad, reason in (
        ({**good, "origin": "webhook"}, "not_from_relay"),
        ({**good, "assertion": ""}, "envelope_incomplete"),
        ({**good, "assertion": "nojws"}, "assertion_missing"),
        ({**good, "channel": "line"}, "line_never_reaches_hermes"),
    ):
        with pytest.raises(EnvelopeRefused) as e:
            ad.accept(bad)
        assert e.value.reason == reason
    ad.send_outbound("c1", "ok")
    assert replies == [("c1", "ok")]


@pytest.mark.req("HER-7", "S1-11")
def test_tb_relay_adapter_contract_against_pinned_release() -> None:
    """Skeleton: runs on every upgrade once a release is vendored; blocked in this build (no verified pin)."""
    src = os.environ.get("TB_HERMES_SRC")
    if not src or pin_problems(HermesLock.load(LOCK_PATH)):
        pytest.skip("S1-11 blocked: no Hermes release pinned by tag + SHA + digest and vendored (TB_HERMES_SRC)")
    pytest.fail("contract extraction from the vendored release is implemented at pinning (§9.12)")  # pragma: no cover


@pytest.mark.req("HER-7")
def test_contract_checker_reports_missing_hooks_and_parameters() -> None:
    def register_platform(name: str, adapter: object) -> None: ...
    def deliver_inbound(platform: str, chat_id: str, text: str) -> None: ...

    api: dict[str, Callable[..., Any]] = {"register_platform": register_platform, "deliver_inbound": deliver_inbound}
    problems = contract_problems(api)
    assert "hook send_outbound missing" in problems and "hook pre_gateway_dispatch missing" in problems
    assert any("deliver_inbound lacks parameters ['metadata']" in p for p in problems)
    assert set(REQUIRED_HOOKS) == {"register_platform", "deliver_inbound", "send_outbound", "pre_gateway_dispatch"}


class _Audit:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail = fail

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        if self.fail:
            raise OSError("ledger down")
        self.events.append({"event": event, **fields})
        return {}


@pytest.mark.req("HER-1", "HER-21", "S1-11")
def test_policy_hook_fails_closed() -> None:
    tools = frozenset({"tb.status"})
    ctx = {"assertion": "a.b.c", "sub": "crc1@hospa.test"}
    audit = _Audit()
    assert TbPolicyAudit(tools, lambda t, a, c: True, audit).pre_tool_call("tb.status", {}, ctx) == "allow"
    assert TbPolicyAudit(tools, lambda t, a, c: True, audit).pre_tool_call("terminal", {}, ctx) == "block"
    assert TbPolicyAudit(tools, lambda t, a, c: True, audit).pre_tool_call("tb.status", {}, {}) == "block"
    assert TbPolicyAudit(tools, lambda t, a, c: False, audit).pre_tool_call("tb.status", {}, ctx) == "block"

    def boom(t: str, a: Any, c: Any) -> bool:
        raise RuntimeError("policy down")

    assert TbPolicyAudit(tools, boom, audit).pre_tool_call("tb.status", {}, ctx) == "block"

    def slow(t: str, a: Any, c: Any) -> bool:
        time.sleep(0.3)
        return True

    assert TbPolicyAudit(tools, slow, audit, timeout_s=0.05).pre_tool_call("tb.status", {}, ctx) == "block"
    reasons = [e["detail"]["reason"] for e in audit.events]
    assert reasons == ["allow", "not_in_profile", "assertion_missing", "policy_deny", "policy_error", "policy_timeout"]
    assert TbPolicyAudit(tools, lambda t, a, c: True, _Audit(fail=True)).pre_tool_call("tb.status", {}, ctx) == "block"
