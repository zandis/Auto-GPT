"""Hermes configuration surface (spec v4 §9.2, §9.5, §9.6, §9.12; S1-11).

The pin (``hermes.lock``: v0.22.2 by tag, commit SHA and multi-arch index digest; mirror pending, so DEV/TEST only),
the three profiles (real v0.22.2 ``config.yaml`` files), the two plugins and the compose fragment. Tests marked
"vendored" read the pinned release's source with :mod:`integrations.hermes.contract` from ``TB_HERMES_SRC`` or
``.cache/hermes-src/<tag>`` (``git clone --depth 1 --branch v0.22.2 https://github.com/NousResearch/hermes-agent``);
they skip only when no source tree is present.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from frontdoor_mcp.policy import PROFILE_TOOLS

from integrations.hermes.contract import (
    REQUIRED_HOOKS,
    REQUIRED_SIGNATURES,
    HermesSurface,
    contract_problems,
    default_source,
    extra_config_keys,
    extract,
    unknown_config_keys,
)
from integrations.hermes.lock import (
    LOCK_PATH,
    MIRROR_PENDING,
    HermesLock,
    expected_digest,
    pin_notes,
    pin_problems,
    run_image,
)
from integrations.hermes.tb_policy_audit import HermesHooks, TbPolicyAudit, frontdoor_tool
from integrations.hermes.tb_relay_adapter import EnvelopeRefused, TbRelayAdapter, pre_gateway_dispatch, shared_context

ROOT = Path(__file__).resolve().parents[2]
HERMES = ROOT / "integrations" / "hermes"
PROFILES = HERMES / "profiles"
COMPOSE = ROOT / "deploy" / "hermes" / "docker-compose.hermes.yml"
LOCK = HermesLock.load(LOCK_PATH)
SRC = default_source(LOCK.get("tag"))
vendored = pytest.mark.skipif(SRC is None or not SRC.is_dir(), reason="no vendored Hermes source (TB_HERMES_SRC)")
EXPECTED_TOOLS = {
    "tb-staff": PROFILE_TOOLS["email"],
    "tb-line": frozenset(),
    "tb-admin": PROFILE_TOOLS["admin_tui"],
}
GATEWAY = "http://gateway:8020/v1"
SPEC_DISABLED = {"terminal", "file", "browser", "web", "code_execution", "cronjob", "memory", "image_gen", "tts"}


def profile(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((PROFILES / name / "config.yaml").read_text(encoding="utf-8"))
    return doc


def meta(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((PROFILES / name / "trialbox.yaml").read_text(encoding="utf-8"))
    return doc


@pytest.fixture(scope="module")
def surface() -> HermesSurface:
    assert SRC is not None
    return extract(SRC)


# ------------------------------------------------------------------------------------------------ profiles
@pytest.mark.req("HER-1", "HER-2", "HER-3", "HER-5", "HER-16", "HER-20", "HER-23", "HER-24", "HER-25", "S1-11")
@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_profile_hardening_settings(name: str) -> None:
    c, m = profile(name), meta(name)
    assert m["profile"] == name and PROFILE_TOOLS[m["frontdoor_profile"]] == EXPECTED_TOOLS[name]
    # item 3 / HER-1 layer 1: only the front-door MCP toolset, every spec-listed built-in suppressed
    assert set(c["agent"]["disabled_toolsets"]) >= SPEC_DISABLED | {"delegation", "skills"}
    tools_on = ["frontdoor"] if EXPECTED_TOOLS[name] else []
    assert c["platform_toolsets"] == {"cli": tools_on, "tb_relay": tools_on}
    assert c["tools"]["tool_search"]["enabled"] is False and c["tools"]["connectors"]["enabled"] is False
    # item 4: one MCP server, explicit include, utilities/sampling/elicitation off, mTLS, 30 s
    servers = c["mcp_servers"]
    assert list(servers) == ["frontdoor"]
    fd = servers["frontdoor"]
    assert fd["url"].startswith("https://frontdoor-mcp:") and fd["timeout"] == 30
    assert set(fd["tools"]["include"]) == EXPECTED_TOOLS[name] and isinstance(fd["tools"]["include"], list)
    assert fd["tools"]["prompts"] is False and fd["tools"]["resources"] is False
    assert fd["sampling"] == {"enabled": False} and fd["elicitation"] == {"enabled": False}
    assert fd["client_cert"] and fd["client_key"] and "ssl_verify" not in fd
    # item 5: approvals
    a = c["approvals"]
    assert a["mode"] == "manual" and a["deny"] == ["*"]
    assert a["cron_mode"] == a["single_query_mode"] == a["unattended_mode"] == "deny"
    assert c["command_allowlist"] == []
    # HER-2: cron
    assert c["cron"]["allow_agent_scheduling"] is False and "cronjob" in c["agent"]["disabled_toolsets"]
    # item 12: delegation toolset off; v0.22.2 floors max_spawn_depth at 1
    assert c["delegation"]["max_spawn_depth"] == 1 and c["delegation"]["orchestrator_enabled"] is False
    # HER-23, HER-25
    mem = c["memory"]
    assert mem["memory_enabled"] is False and mem["user_profile_enabled"] is False
    assert mem["write_approval"] is True and mem["provider"] == ""
    sk = c["skills"]
    assert sk["external_dirs"] == [] and sk["project_discovery"] is False and sk["write_approval"] is True
    assert c["curator"]["enabled"] is False
    # item 7: gateway only, no fallback, every side model on a gateway alias
    model = c["model"]
    assert model["provider"] == "custom" and model["base_url"] == GATEWAY and model["default"] == "f-frontdesk"
    assert model["context_length"] >= 65536 and c["fallback_providers"] == [] and c["providers"] == {}
    assert model["default_headers"]["X-TB-Caller"] == "hermes"
    for task, aux in c["auxiliary"].items():
        if isinstance(aux, dict) and aux.get("enabled") is not False:
            assert aux["base_url"] == GATEWAY and aux["model"] in {"g-guard", "f-frontdesk"}, task
    assert c["model_catalog"]["enabled"] is False
    # item 8 and 9: plugins and hooks
    p = c["plugins"]
    assert p["enabled"] == ["tb_relay_adapter", "tb_policy_audit"] and p["hook_callback_timeout"] == 5
    assert p["auto_apply"] is False and c["hooks"] == {} and c["hooks_auto_accept"] is False
    # item 2 / HER-5: only the relay platform; API server and webhook off
    assert c["platforms"] == {
        "tb_relay": {"enabled": True},
        "api_server": {"enabled": False},
        "webhook": {"enabled": False},
    }
    assert c["gateway"]["allow_all_users"] is False and c["gateway"]["multiplex_profiles"] is False
    s = c["security"]
    assert s["allow_private_urls"] is False and s["allow_lazy_installs"] is False and s["redact_secrets"] is True
    assert c["auth"]["adopt_external_logins"] is False
    # HER-24: session retention
    assert c["sessions"]["auto_prune"] is True and c["sessions"]["retention_days"] <= 30
    assert c["telemetry"]["shared_metrics"]["send"] is False and c["updates"]["check"] is False
    # item 6 / HER-16: forbidden env
    assert {"HERMES_YOLO_MODE", "GATEWAY_ALLOW_ALL_USERS"} <= set(m["env"]["forbid"])


@pytest.mark.req("HER-1", "S1-11", "S1-07")
@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_profile_model_aliases_are_registered_and_routed(name: str) -> None:
    """Every alias a profile names (main and side models) is a registry alias on a route: DEV/TEST answer it from a
    stub build, VALIDATION/PRODUCTION only from the converse / guard routes (item 7)."""
    from gateway.policy import RoutingPolicy
    from registry.registry import Registry
    from tb_common.policy.classes import Environment

    c = yaml.safe_load((PROFILES / name / "config.yaml").read_text(encoding="utf-8"))
    aliases = {c["model"]["default"]} | {
        a["model"] for a in c["auxiliary"].values() if isinstance(a, dict) and a.get("model")
    }
    reg, policy = Registry.load(), RoutingPolicy.load()
    routed = {alias for r in policy.routes for alias, _ in r.builds}
    assert aliases <= set(reg.aliases) and aliases <= routed, aliases - set(reg.aliases)
    for alias in aliases:
        assert reg.resolve(alias, "stub", role="frontdesk_converse", env=Environment.TEST).build.serving == "stub"


@pytest.mark.req("HER-1", "HER-20", "HER-37", "S1-11")
@vendored
@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_profile_matches_the_vendored_release(name: str, surface: HermesSurface) -> None:
    """Configuration diff (§9.12, HER-37 (h)): every key is one v0.22.2 reads; every built-in is suppressed."""
    assert SRC is not None
    c = profile(name)
    assert unknown_config_keys(c, surface.default_config, extra_config_keys(SRC)) == []
    leaf = {t for t, is_leaf in surface.toolsets.items() if is_leaf}
    assert leaf and set(c["agent"]["disabled_toolsets"]) >= leaf
    bundled = {
        str(f.parent.relative_to(SRC / "plugins"))
        for f in (SRC / "plugins").glob("*/*/plugin.yaml")
        if (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("kind") in ("backend", "platform")
    }
    assert bundled and set(c["plugins"]["disabled"]) >= bundled
    assert c["approvals"]["mode"] in surface.approval_modes
    assert surface.min_spawn_depth == c["delegation"]["max_spawn_depth"]  # 0 is not expressible (§9.6 item 12)


# ------------------------------------------------------------------------------------------------ pin
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
def test_shipped_lock_is_pinned_and_mirror_rule_holds() -> None:
    assert LOCK.get("tag") == LOCK.get("version") == "v0.22.2"
    assert LOCK.get("commit_sha") == "d923a5eb487a17c0a68801bba9ef0f56c81040a8"
    index = "sha256:36099926da316742423544e055d4734777105ffe6341873af5459b957d0c2919"
    assert LOCK.get("upstream_digest") == index and LOCK.get("upstream_image").endswith("@" + index)
    assert set(LOCK.raw["platform_digests"]) == {"linux/amd64", "linux/arm64"}
    assert LOCK.mirror_pending and LOCK.raw["verified"] is True
    for env in ("DEV", "TEST"):
        assert pin_problems(LOCK, environment=env) == []
        assert pin_notes(LOCK, env) and run_image(LOCK, env) == LOCK.get("upstream_image")
        assert pin_problems(LOCK, environment=env, running_digest=index) == []
        assert expected_digest(LOCK, env) == index
    for env in ("VALIDATION", "PRODUCTION"):
        assert any("mirror pending" in p for p in pin_problems(LOCK, environment=env))
    assert any("running image" in p for p in pin_problems(LOCK, running_digest="sha256:" + "ee" * 32))


@pytest.mark.req("HER-18", "ENG-08", "S1-11")
def test_pin_check_refuses_every_unpinned_shape() -> None:
    assert pin_problems(_pinned()) == [] and pin_problems(_pinned(), environment="PRODUCTION") == []
    assert pin_notes(_pinned(), "DEV") == []
    assert any("below the floor" in p for p in pin_problems(_pinned(version="v0.21.5", tag="v0.21.5")))
    assert any("differs" in p for p in pin_problems(_pinned(mirror_digest="sha256:" + "cd" * 32)))
    assert any("mutable" in p for p in pin_problems(_pinned(mirror_image="registry.internal/hermes-agent:v0.22.2")))
    assert any("mutable" in p for p in pin_problems(_pinned(upstream_image="nousresearch/hermes-agent:v0.22.2")))
    assert any("running image" in p for p in pin_problems(_pinned(), running_digest="sha256:" + "ee" * 32))
    assert any("commit_sha" in p for p in pin_problems(_pinned(commit_sha=None)))
    half = _pinned(mirror_image=MIRROR_PENDING)  # placeholder only counts when both mirror fields carry it
    assert any("mirror_image" in p for p in pin_problems(half, environment="DEV"))
    assert any("not verified" in p for p in pin_problems(_pinned(verified=False)))
    assert pin_problems(HermesLock({})) == ["hermes.lock missing or empty"]


@pytest.mark.req("HER-7", "HER-18", "ENG-08", "S1-11")
@vendored
def test_vendored_source_is_the_pinned_commit() -> None:
    assert SRC is not None
    head = SRC / ".git" / "HEAD"
    if not head.is_file():
        pytest.skip("vendored tree has no .git (exported archive); HEAD cannot be checked")
    assert head.read_text(encoding="utf-8").strip() == LOCK.get("commit_sha")


# ------------------------------------------------------------------------------------------------ relay adapter
GOOD = {
    "origin": "channel-relay",
    "conv": "c1",
    "msg_sha256": "s",
    "channel": "email",
    "assertion": "a.b.c",
    "text": "這個試驗做得起來嗎",
}


@pytest.mark.req("HER-6", "S1-11")
def test_relay_adapter_accepts_only_relay_envelopes_with_an_assertion() -> None:
    replies: list[tuple[str, str]] = []
    ad = TbRelayAdapter(lambda conv, text: replies.append((conv, text)))
    assert ad.accept(GOOD).conv == "c1"
    for bad, reason in (
        ({**GOOD, "origin": "webhook"}, "not_from_relay"),
        ({**GOOD, "assertion": ""}, "envelope_incomplete"),
        ({**GOOD, "assertion": "nojws"}, "assertion_missing"),
        ({**GOOD, "channel": "line"}, "line_never_reaches_hermes"),
    ):
        with pytest.raises(EnvelopeRefused) as e:
            ad.accept(bad)
        assert e.value.reason == reason
    ad.send_outbound("c1", "ok")
    assert replies == [("c1", "ok")]


def _event(platform: str = "tb_relay", chat: str = "c1", **raw: Any) -> SimpleNamespace:
    marked = {"tb_relay_envelope": True, "conv": "c1", "channel": "email", "assertion": "a.b.c", **raw}
    return SimpleNamespace(
        source=SimpleNamespace(platform=SimpleNamespace(value=platform), chat_id=chat), raw_message=marked
    )


@pytest.mark.req("HER-6", "HER-26", "S1-11")
def test_pre_gateway_dispatch_fails_closed() -> None:
    """§9.6 item 10: Hermes runs this hook unbounded and treats a raise as allow, so it must decide every case."""
    assert pre_gateway_dispatch(event=_event()) is None
    cases = {
        "not_from_relay": _event(platform="telegram"),
        "not_injected_by_adapter": SimpleNamespace(source=_event().source, raw_message={"conv": "c1"}),
        "assertion_missing": _event(assertion="nojws"),
        "conversation_mismatch": _event(chat="c2"),
        "line_never_reaches_hermes": _event(channel="line"),
        "adapter_error": object(),
    }
    for reason, ev in cases.items():
        res = pre_gateway_dispatch(event=ev)
        assert res == {"action": "skip", "reason": f"tb_relay_adapter:{reason}"} or (
            reason == "adapter_error" and res is not None and res["action"] == "skip"
        ), reason
    ticks = iter([0.0, 3.0])
    slow = pre_gateway_dispatch(event=_event(), clock=lambda: next(ticks))
    assert slow == {"action": "skip", "reason": "tb_relay_adapter:dispatch_timeout"}


# ------------------------------------------------------------------------------------------------ contract (HER-7)
@pytest.mark.req("HER-7", "HER-21", "S1-11")
@vendored
def test_tb_relay_adapter_contract_against_pinned_release(surface: HermesSurface) -> None:
    """Runs on every upgrade (§9.12): the plugin API surface the two plugins rely on, read from the release."""
    assert contract_problems(surface) == []
    assert surface.signatures["gateway.platforms.base.BasePlatformAdapter.send"][:2] == ("chat_id", "content")
    assert "pre_gateway_dispatch" not in surface.bounded_hooks  # why the adapter enforces its own 2 s budget
    assert {"sampling", "elicitation", "include", "client_cert"} <= surface.mcp_keys_read
    assert SRC is not None  # prompts/resources are read in a loop over this literal tuple
    assert 'for f in ("resources", "prompts")' in (SRC / "tools" / "mcp_tool_registration.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.req("HER-7")
def test_contract_checker_reports_missing_hooks_and_parameters() -> None:
    sigs = {q: p for q, p in REQUIRED_SIGNATURES.items() if not q.endswith("register_hook")}
    sigs["gateway.platforms.base.BasePlatformAdapter.send"] = ("chat_id", "content")
    s = HermesSurface(
        signatures=sigs,
        valid_hooks=frozenset(REQUIRED_HOOKS - {"pre_gateway_dispatch"}),
        fail_closed_hooks=frozenset(),
        hook_kwargs={"pre_tool_call": frozenset({"tool_name", "args"})},
        message_event_fields=frozenset({"text"}),
        approval_modes=("smart",),
    )
    problems = contract_problems(s)
    assert "hermes_cli.plugins.PluginContext.register_hook missing" in problems
    assert any("BasePlatformAdapter.send lacks parameters ['reply_to', 'metadata']" in p for p in problems)
    assert any("pre_gateway_dispatch" in p and "VALID_HOOKS" in p for p in problems)
    assert any("pre_tool_call fire site lacks kwargs ['session_id', 'task_id']" in p for p in problems)
    assert any("no longer fails closed" in p for p in problems)
    assert any("MessageEvent lacks" in p for p in problems) and any("'manual' not offered" in p for p in problems)
    defaults = {"approvals": {"mode": None}, "auxiliary": {"vision": None}}
    cfg = {
        "approvals": {"mode": "manual", "bogus": 1},
        "auxiliary": {"vision": {"model": "x", "nope": 1}},
        "model": {"a": 1},
    }
    assert unknown_config_keys(cfg, defaults) == ["approvals.bogus", "auxiliary.vision.nope"]


# ------------------------------------------------------------------------------------------------ policy hook
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


@pytest.mark.req("HER-1", "HER-15", "HER-21", "S1-11")
def test_hermes_hooks_map_mcp_names_and_bind_sessions() -> None:
    tools = frozenset(PROFILE_TOOLS["email"])
    assert frontdoor_tool("mcp__frontdoor__tb_status", tools) == "tb.status"
    assert frontdoor_tool("mcp__frontdoor__tb_ops_read", tools) == "mcp__frontdoor__tb_ops_read"
    audit = _Audit()
    hooks = HermesHooks(TbPolicyAudit(tools, lambda t, a, c: c.get("conv") == "c9", audit), audit)
    assert hooks.pre_tool_call(tool_name="mcp__frontdoor__tb_status", args={}, session_id="s9")["action"] == "block"
    shared_context()["senders"]["c9"] = {"assertion": "h.p.s", "channel": "email"}
    hooks.pre_llm_call(session_id="s9", sender_id="c9", user_message="hi")
    allowed = hooks.pre_tool_call(tool_name="mcp__frontdoor__tb_status", args={"q": 1}, session_id="s9")
    # allow = attach this turn's assertion and conversation to the call (HER-15, spec §9.4)
    assert allowed == {"action": "modify", "args": {"_tb_identity": {"assertion": "h.p.s", "conv": "c9"}}}
    forged = {"q": 1, "_tb_identity": {"assertion": "x.y.z", "conv": "other"}}  # the model wrote one itself
    assert hooks.pre_tool_call(tool_name="mcp__frontdoor__tb_status", args=forged, session_id="s9") == allowed
    assert hooks.pre_tool_call(tool_name="terminal", args={}, session_id="s9")["action"] == "block"
    hooks.post_tool_call(tool_name="mcp__frontdoor__tb_status", result={"rows": 1}, session_id="s9")
    events = [e["event"] for e in audit.events]
    assert events.count("hermes.pre_tool_call") == 4 and "hermes.post_tool_call" in events
    assert all("hi" not in str(e) and "'q': 1" not in str(e) for e in audit.events)  # hashes, never content


# ------------------------------------------------------------------------------------------------ compose
@pytest.mark.req("HER-5", "HER-18", "HER-20", "ENG-08", "S1-11")
def test_compose_fragment_pins_digest_and_isolates_hermes() -> None:
    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    h = doc["services"]["hermes"]
    default_image = h["image"].split(":-", 1)[1].rstrip("}")
    assert default_image == LOCK.get("upstream_image") and "@sha256:" in default_image
    assert "ports" not in h and "expose" not in h and "env_file" not in h
    assert h["networks"] == ["hermes-net"] and doc["networks"]["hermes-net"]["internal"] is True
    assert h["user"] == "10000:10000" and h["read_only"] is True and h["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in h["security_opt"] and h["init"] is True
    assert h["pids_limit"] and h["mem_limit"] and h["cpus"]
    forbidden = set(meta("tb-staff")["env"]["forbid"])
    assert not forbidden & set(h["environment"]) and not any(k.endswith("_ALLOW_ALL_USERS") for k in h["environment"])
    mounts = {m.group(1): v for v in h["volumes"] if (m := re.search(r":(/[^:]+)(?::ro)?$", v))}
    for target in (
        "/etc/hermes/config.yaml",
        "/opt/data/config.yaml",
        "/opt/data/plugins/tb_relay_adapter",
        "/opt/data/plugins/tb_policy_audit",
        "/run/secrets/tb-ca.pem",
    ):
        assert mounts[target].endswith(":ro"), target
    assert doc["services"]["gateway"]["networks"] == ["hermes-net"]


@pytest.mark.req("HER-22")
@pytest.mark.parametrize("name", ["tb-staff", "tb-admin", "tb-line"])
def test_each_profile_has_a_read_only_front_desk_identity(name: str) -> None:
    """Stress test #26: without instructions a real model answered "no record of study GZQO" instead of proposing.
    SOUL.md is Hermes' identity prompt; it is mounted read-only and names only tools the profile includes."""
    soul = (PROFILES / name / "SOUL.md").read_text(encoding="utf-8")
    assert soul.strip()
    named = set(re.findall(r"`(tb\.[a-z_]+)`", soul))
    cfg = yaml.safe_load((PROFILES / name / "config.yaml").read_text())
    assert named <= set(cfg["mcp_servers"]["frontdoor"]["tools"]["include"]), named
    assert not re.search(r"ignore\s+(previous|all|above|prior)|you\s+are\s+now\s", soul, re.I)  # Hermes context scan
    mounts = yaml.safe_load(COMPOSE.read_text())["services"]["hermes"]["volumes"]
    assert any(m.endswith("/SOUL.md:/opt/data/SOUL.md:ro") for m in mounts)
