"""``tb_policy_audit``: Hermes policy and audit hooks (spec v4 §9.6 items 8–9, HER-1, HER-21; S1-11).

One of the three independent layers that keep Hermes to the front-door tools (HER-1): the profile's tool list, this
``pre_tool_call`` decision (``tb_common.policy`` through the orchestrator) and the front-door server's own check.
:class:`TbPolicyAudit` blocks on a deny, on any error and on a decision slower than 5 s (Hermes v0.22.2 also fails
``pre_tool_call`` closed at ``plugins.hook_callback_timeout: 5``); block beats approve. It logs hashes, never
arguments or content.

:func:`register` wires it into the pinned release's plugin API: ``pre_tool_call`` returns
``{"action": "block", "message"}`` on block and, on allow, ``{"action": "modify", "args": {"_tb_identity": {...}}}``:
the current turn's relay-minted identity assertion and its conversation, attached to the call's arguments (spec §9.4,
HER-15). Hermes' MCP client sends only static headers, so the arguments are the one per-call field that reaches the
front door; ``frontdoor_mcp.listener`` removes the key before validation and the server refuses any call without a
valid assertion. The key is overwritten here on every call, so a value the model wrote itself never survives.
``post_tool_call``, ``pre_llm_call``,
``post_llm_call``, ``on_session_start`` and ``on_session_end`` write hash-only audit events. Hermes names MCP tools
``mcp__<server>__<tool>`` with ``.`` replaced by ``_``; :func:`frontdoor_tool` maps them back to the ``tb.*`` names.

Deployment inputs (env): ``TB_POLICY_DECIDE_URL`` (orchestrator decision endpoint, https + mTLS via
``TB_POLICY_CA``/``TB_POLICY_CLIENT_CERT``/``TB_POLICY_CLIENT_KEY``). Without it every tool call is blocked
(``policy_unconfigured``). Not built here: OTel spans and the hash-chained ledger over mTLS (HER-21); audit events go
to the ``tb_policy_audit`` logger as JSON lines for the log shipper.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import importlib
import json
import logging
import os
import re
import ssl
import sys
import threading
import types
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, Protocol

logger = logging.getLogger("tb_policy_audit")

Decision = Literal["allow", "block"]
HOOK_TIMEOUT_S = 5.0
MCP_SERVER = "frontdoor"
BLOCK_MESSAGE = "Blocked by TrialBox policy. Use the grammar line or ask the research office."
IDENTITY_KEY = "_tb_identity"  # frontdoor_mcp.listener.IDENTITY_KEY
_SHARED = "tb_hermes_shared_context"


class AuditSink(Protocol):
    def append(self, event: str, **fields: Any) -> dict[str, Any]: ...


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def frontdoor_tool(hermes_name: str, profile_tools: Iterable[str]) -> str:
    """``mcp__frontdoor__tb_status`` -> ``tb.status`` when it is one of ``profile_tools``; otherwise unchanged."""
    by_wire = {f"mcp__{MCP_SERVER}__{_sanitize(t)}": t for t in profile_tools}
    return by_wire.get(hermes_name, hermes_name)


class TbPolicyAudit:
    def __init__(
        self,
        profile_tools: frozenset[str],
        decide: Callable[[str, Mapping[str, Any], Mapping[str, Any]], bool],
        audit: AuditSink,
        timeout_s: float = HOOK_TIMEOUT_S,
    ) -> None:
        self.profile_tools = profile_tools
        self.decide = decide
        self.audit = audit
        self.timeout_s = timeout_s
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="tb_policy")

    def pre_tool_call(self, tool: str, args: Mapping[str, Any], context: Mapping[str, Any]) -> Decision:
        reason = "allow"
        decision: Decision = "block"
        try:
            if tool not in self.profile_tools:
                reason = "not_in_profile"
            elif not context.get("assertion"):
                reason = "assertion_missing"
            else:
                fut = self._pool.submit(self.decide, tool, args, context)
                ok = fut.result(timeout=self.timeout_s)
                decision, reason = ("allow", "allow") if ok is True else ("block", "policy_deny")
        except concurrent.futures.TimeoutError:
            decision, reason = "block", "policy_timeout"
        except Exception:
            decision, reason = "block", "policy_error"
        args_sha = _sha(dict(args))
        try:
            self.audit.append(
                "hermes.pre_tool_call",
                actor=str(context.get("sub") or "?"),
                detail={"tool": tool, "decision": decision, "reason": reason, "args_sha256": args_sha},
            )
        except Exception:
            return "block"  # no audit, no tool
        return decision


class LogAuditSink:
    """JSON-line audit events on the ``tb_policy_audit`` logger (hashes only)."""

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        rec = {"event": event, **fields}
        logger.info("%s", json.dumps(rec, sort_keys=True, default=str))
        return rec


def _shared() -> dict[str, dict[str, Any]]:
    """Same store as ``tb_relay_adapter.shared_context`` (each Hermes plugin is loaded as its own module)."""
    mod = sys.modules.get(_SHARED)
    if mod is None:
        fresh = types.ModuleType(_SHARED)
        fresh.store = {"senders": {}, "sessions": {}}  # type: ignore[attr-defined]
        fresh.lock = threading.Lock()  # type: ignore[attr-defined]
        mod = sys.modules.setdefault(_SHARED, fresh)
    store: dict[str, dict[str, Any]] = mod.store
    return store


def session_context(session_id: str | None) -> dict[str, Any]:
    """Assertion and channel of the relay conversation bound to a Hermes session (empty when unknown)."""
    store = _shared()
    conv = store["sessions"].get(session_id or "")
    ctx = dict(store["senders"].get(conv or "", {}))
    if ctx:
        ctx["conv"] = conv
    return ctx


def http_decide(url: str) -> Callable[[str, Mapping[str, Any], Mapping[str, Any]], bool]:
    """Ask the orchestrator's policy endpoint; anything but ``{"allow": true}`` is a deny."""

    def decide(tool: str, args: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
        ctx = ssl.create_default_context(cafile=os.environ.get("TB_POLICY_CA") or None)
        if os.environ.get("TB_POLICY_CLIENT_CERT"):
            ctx.load_cert_chain(os.environ["TB_POLICY_CLIENT_CERT"], os.environ.get("TB_POLICY_CLIENT_KEY") or None)
        body = json.dumps(
            {
                "tool": tool,
                "args_sha256": _sha(dict(args)),
                "assertion": context.get("assertion"),
                "conv": context.get("conv"),
            }
        ).encode()
        hdrs = {"content-type": "application/json"}
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")  # noqa: S310 (https only)
        with urllib.request.urlopen(req, timeout=HOOK_TIMEOUT_S, context=ctx) as resp:  # noqa: S310
            return json.loads(resp.read()).get("allow") is True

    return decide


def _deny(tool: str, args: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    return False


class HermesHooks:
    """The Hermes-facing callbacks (keyword arguments as fired by v0.22.2; extra ones are ignored)."""

    def __init__(self, policy: TbPolicyAudit, audit: AuditSink) -> None:
        self.policy = policy
        self.audit = audit

    def pre_tool_call(self, tool_name: str = "", args: Any = None, session_id: str | None = None, **_: Any) -> Any:
        try:
            tool = frontdoor_tool(tool_name, self.policy.profile_tools)
            ctx = session_context(session_id)
            clean = {k: v for k, v in args.items() if k != IDENTITY_KEY} if isinstance(args, Mapping) else {}
            decision = self.policy.pre_tool_call(tool, clean, ctx)
        except Exception:
            decision = "block"
        if decision != "allow":
            return {"action": "block", "message": BLOCK_MESSAGE}
        return {"action": "modify", "args": {IDENTITY_KEY: {"assertion": ctx["assertion"], "conv": ctx["conv"]}}}

    def _observe(self, event: str, session_id: str | None, **detail: Any) -> None:
        try:
            self.audit.append(event, actor=str(session_context(session_id).get("conv") or "?"), detail=detail)
        except Exception:
            logger.warning("audit write failed for %s", event)

    def post_tool_call(self, tool_name: str = "", result: Any = None, session_id: str | None = None, **_: Any) -> None:
        self._observe("hermes.post_tool_call", session_id, tool=tool_name, result_sha256=_sha(result))

    def pre_llm_call(
        self, session_id: str | None = None, sender_id: str = "", user_message: Any = None, **_: Any
    ) -> None:
        if session_id and sender_id:
            _shared()["sessions"][session_id] = sender_id  # the relay adapter uses the conversation as user id
        self._observe("hermes.pre_llm_call", session_id, message_sha256=_sha(user_message))

    def post_llm_call(self, session_id: str | None = None, **kw: Any) -> None:
        out = kw.get("assistant_response", kw.get("response"))
        self._observe("hermes.post_llm_call", session_id, response_sha256=_sha(out))

    def on_session_start(self, session_id: str | None = None, platform: str = "", **_: Any) -> None:
        self._observe("hermes.session_start", session_id, platform=platform)

    def on_session_end(self, session_id: str | None = None, **_: Any) -> None:
        self._observe("hermes.session_end", session_id)


def _profile_tools_from_config() -> frozenset[str]:
    cfg = importlib.import_module("hermes_cli.config").load_config_readonly() or {}
    include = (((cfg.get("mcp_servers") or {}).get(MCP_SERVER) or {}).get("tools") or {}).get("include") or []
    return frozenset(str(t) for t in include)


def register(ctx: Any) -> None:
    """Hermes plugin entry point (``plugin.yaml`` + ``register(ctx)``, v0.22.2 plugin API)."""
    url = os.environ.get("TB_POLICY_DECIDE_URL", "")
    audit = LogAuditSink()
    policy = TbPolicyAudit(
        _profile_tools_from_config(), http_decide(url) if url.startswith("https://") else _deny, audit
    )
    hooks = HermesHooks(policy, audit)
    for name in (
        "pre_tool_call",
        "post_tool_call",
        "pre_llm_call",
        "post_llm_call",
        "on_session_start",
        "on_session_end",
    ):
        ctx.register_hook(name, getattr(hooks, name))
    logger.info("tb_policy_audit registered; profile tools %s; decision %s", sorted(policy.profile_tools), bool(url))
