"""frontdoor-mcp: the only tools Hermes (or the native engine) can call (spec v4 §9.3; S1-09, HER-1, HER-8 … HER-15).

A transport-agnostic MCP handler: :meth:`FrontDoorServer.handle` takes one JSON-RPC 2.0 message plus the identity
assertion and session conversation that the Streamable HTTP layer (mTLS) carries, and returns the JSON-RPC response.
Supported methods are ``initialize``, ``ping``, ``tools/list`` and ``tools/call``. The server advertises the
``tools`` capability only: sampling, roots, logging, prompts, resources and elicitation are not offered.

Each ``tools/call`` runs these steps in order; every refusal is audited:
1. the tool name must be one of the eight §9.3 tools (HER-8);
2. the identity assertion is verified (signature, audience, expiry, conversation; HER-15). An unauthenticated call is
   refused, alarmed (``alarm: true`` in the audit record) and never reaches a tool;
3. the arguments are validated against the tool's contract (``tb_contracts.frontdoor``);
4. the orchestrator policy context resolves roles and delegations and checks tier, profile and rate (§9.3, HER-17);
5. the audit event is written **before the tool acts** (``frontdoor.call.intent``); a ledger failure fails the call;
6. the tool runs; aggregates pass controlled rounding and the accountant (HER-10);
7. the result event (decision, result size) is written **before the result is returned** (HER-14).

Results are marked untrusted for the gateway's injection screen (``_meta["tb/untrusted"]``, HER-13).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from guard.guard import Guard
from orchestrator.db_pg import OutboxMessage, StepResult, StepStore, canonical_json, sha256_text
from pydantic import BaseModel, ValidationError
from tb_contracts.frontdoor import (
    FRONTDOOR_TOOLS,
    RELAY_TOKEN,
    SCHEMA_VERSION,
    SERVER_NAME,
    TOOL_MODELS,
    TOOL_NAMES,
    AggregateQueryIn,
    AggregateQueryOut,
    AskProtocolIn,
    AtlasDescribeIn,
    AtlasDescribeOut,
    FrontdoorAuditEvent,
    IdentityAssertion,
    OpsReadIn,
    OpsReadOut,
    RegistrySearchIn,
    RegistrySearchOut,
    ResendIn,
    ResendOut,
    StatusIn,
    StatusItem,
    StatusOut,
    SubmitRequestIn,
    SubmitRequestOut,
    ToolSpec,
    tool_spec,
)

from frontdoor_mcp.backends import (
    AggregateSource,
    AtlasSource,
    OpsSource,
    ProtocolAnswerer,
    RegistryIndex,
    ReleaseIndex,
)
from frontdoor_mcp.identity import AssertionRefused, AssertionVerifier
from frontdoor_mcp.metrics import Catalogue, PrivacyAccountant, rounded_rows
from frontdoor_mcp.policy import OrchestratorPolicyContext, Principal
from frontdoor_mcp.requests import RequestStore
from frontdoor_mcp.tokens import TokenMap

PROTOCOL_VERSION = "2026-07-28"  # MCP specification revision named in §9.3
# Handshake-era revisions a client may ask for in ``initialize``. Hermes v0.22.2 ships the MCP Python SDK 2.0, whose
# ``ClientSession`` performs the ``initialize`` handshake and refuses a server answer outside these revisions (the
# 2026-07-28 single-exchange mode needs no handshake). The server answers with the requested revision when it is one
# of these and with :data:`PROTOCOL_VERSION` otherwise; the method set is the same in every revision.
HANDSHAKE_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SMALL_CELL = 5

# JSON-RPC error codes (the -32000 range is implementation-defined)
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
UNAUTHENTICATED = -32001
AUDIT_FAILED = -32002


class AuditSink(Protocol):
    def append(self, event: str, **fields: Any) -> dict[str, Any]: ...


class ToolRefused(PermissionError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def tools_list() -> list[dict[str, Any]]:
    """``tools/list`` body: exactly the §9.3 tools, with input and output JSON Schemas (HER-8 snapshot)."""
    out = []
    for spec in FRONTDOOR_TOOLS:
        inp, outp = TOOL_MODELS[spec.name]
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": inp.model_json_schema(),
                "outputSchema": outp.model_json_schema(),
                "annotations": {
                    "readOnlyHint": spec.name not in ("tb.submit_request", "tb.resend_released_file"),
                    "destructiveHint": False,
                    "openWorldHint": False,
                    "tb/tier": spec.tier.value,
                    "tb/roles": list(spec.roles),
                    "tb/limit": f"{spec.limit}/{spec.per}",
                },
            }
        )
    return out


@dataclass
class FrontDoorServer:
    verifier: AssertionVerifier
    policy: OrchestratorPolicyContext
    requests: RequestStore
    audit: AuditSink
    tokens: TokenMap
    registry: RegistryIndex
    protocol: ProtocolAnswerer
    atlas: AtlasSource
    aggregates: AggregateSource
    ops: OpsSource
    releases: ReleaseIndex
    steps: StepStore
    catalogue: Catalogue = field(default_factory=Catalogue.load)
    accountant: PrivacyAccountant = field(default_factory=PrivacyAccountant)
    guard: Guard = field(default_factory=lambda: Guard(None))
    on_alarm: Callable[[str, str], None] | None = None  # (reason, conv) -> page the security on-call

    # ------------------------------------------------------------------------------------------------ MCP surface
    def list_tools(self) -> list[dict[str, Any]]:
        return tools_list()

    def handle(
        self,
        message: Any,
        *,
        assertion: str | None = None,
        conv: str | None = None,
        client: str = "converse-native",
        peer: str | None = None,
    ) -> dict[str, Any] | None:
        """One JSON-RPC message. ``peer`` is the mTLS client certificate's common name when the transport verified
        one (``frontdoor_mcp.listener``); it admits ``tools/list`` without a conversation, because an MCP client lists
        tools when it connects, before any conversation exists. Every ``tools/call`` still needs the assertion."""
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            return _error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        mid = message.get("id")
        method = message["method"]
        params = message.get("params") or {}
        if mid is None:  # notification (e.g. notifications/initialized): no response
            return None
        if method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            version = requested if requested in HANDSHAKE_VERSIONS else PROTOCOL_VERSION
            return _result(
                mid,
                {
                    "protocolVersion": version,
                    "serverInfo": {"name": SERVER_NAME, "version": SCHEMA_VERSION},
                    "capabilities": {"tools": {"listChanged": False}},
                },
            )
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            if assertion is None and peer:
                self.audit.append("frontdoor.tools_list", actor=peer, detail={"peer": peer, "client": client})
                return _result(mid, {"tools": self.list_tools()})
            try:
                self.verifier.verify(assertion, conv=conv)
            except AssertionRefused as e:
                self._alarm("tools/list", e.reason, conv)
                return _error(mid, UNAUTHENTICATED, f"unauthenticated: {e.reason}")
            return _result(mid, {"tools": self.list_tools()})
        if method == "tools/call":
            if not isinstance(params, dict):
                return _error(mid, INVALID_PARAMS, "params must be an object")
            return self._call(mid, params, assertion, conv, client)
        return _error(mid, METHOD_NOT_FOUND, f"method {method!r} is not offered")

    # ------------------------------------------------------------------------------------------------ hook decision
    def decide(self, tool: str, assertion: str | None, conv: str | None, args_sha256: str = "") -> tuple[bool, str]:
        """The ``pre_tool_call`` decision for Hermes (``tb_policy_audit`` -> ``POST /policy/decide``): assertion,
        principal, tier, channel profile and role, audited; no rate budget is spent and nothing runs. The call itself
        is checked again in full by :meth:`handle` (HER-1: three independent layers)."""
        if tool not in TOOL_NAMES:
            reason = "tool_unknown"
            self.audit.append(
                "frontdoor.policy.decide", actor="?", detail={"tool": tool, "allow": False, "reason": reason}
            )
            return False, reason
        try:
            claims = self.verifier.verify(assertion, conv=conv)
        except AssertionRefused as e:
            self._alarm(tool, e.reason, conv)
            return False, e.reason
        try:
            self.policy.preview(claims, tool_spec(tool))
            allow, reason = True, "allow"
        except PermissionError as e:
            allow, reason = False, str(getattr(e, "reason", "policy"))
        self.audit.append(
            "frontdoor.policy.decide",
            actor=claims.sub,
            input_sha=args_sha256 or None,
            detail={"tool": tool, "allow": allow, "reason": reason, "conv": claims.conv, "channel": claims.channel},
        )
        return allow, reason

    # ------------------------------------------------------------------------------------------------ tools/call
    def _call(
        self, mid: Any, params: dict[str, Any], assertion: str | None, conv: str | None, client: str
    ) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        args_sha = sha256_text(canonical_json(args)) if isinstance(args, dict) else sha256_text(str(args))
        if not isinstance(name, str) or name not in TOOL_NAMES:
            self._write(
                "frontdoor.call",
                FrontdoorAuditEvent(
                    user="?", tool=str(name), args_sha256=args_sha, decision="refuse", reason="tool_unknown"
                ),
            )
            return _error(mid, INVALID_PARAMS, f"unknown tool {name!r}")
        spec = tool_spec(name)
        try:
            claims = self.verifier.verify(assertion, conv=conv)
        except AssertionRefused as e:
            self._alarm(name, e.reason, conv)
            return _error(mid, UNAUTHENTICATED, f"unauthenticated: {e.reason}")

        def event(decision: str, reason: str | None = None, size: int = 0) -> FrontdoorAuditEvent:
            return FrontdoorAuditEvent(
                user=claims.sub,
                tool=name,
                args_sha256=args_sha,
                decision=decision,  # type: ignore[arg-type]
                reason=reason,
                result_size=size,
                conv=claims.conv,
                channel=claims.channel,
            )

        in_model = TOOL_MODELS[name][0]
        try:
            parsed = in_model.model_validate(args)
        except ValidationError as e:
            # the caller learns which field is wrong and why, never the value it sent (stress test #26)
            problems = _problems(e)
            return self._refuse(
                mid,
                event("refuse", "invalid_arguments"),
                "invalid_arguments",
                extra={"problems": problems, **({"example": EXAMPLES[name]} if name in EXAMPLES else {})},
                audit_extra={"fields": [p["field"] for p in problems]},
            )
        study = getattr(parsed, "study", None)
        try:
            principal = self.policy.authorise(claims, spec, study if study != "NEW" else None)
        except PermissionError as e:
            reason = str(getattr(e, "reason", "policy"))
            return self._refuse(mid, event("refuse", reason), reason)
        try:
            self._write("frontdoor.call.intent", event("intent"))  # the ledger first, then the act (HER-14)
        except Exception:
            return _error(mid, AUDIT_FAILED, "audit ledger unavailable; nothing was done")
        try:
            out = self._run(spec, parsed, claims, principal, client)
        except PermissionError as e:
            reason = str(getattr(e, "reason", "refused"))
            return self._refuse(mid, event("refuse", reason), reason)
        body = out.model_dump(mode="json")
        text = json.dumps(body, ensure_ascii=False, sort_keys=True)
        try:
            self._write("frontdoor.call", event("allow", size=len(text.encode("utf-8"))))
        except Exception:
            return _error(mid, AUDIT_FAILED, "audit ledger unavailable; result withheld")
        return _result(
            mid,
            {
                "content": [{"type": "text", "text": text}],
                "structuredContent": body,
                "isError": False,
                "_meta": {"tb/untrusted": True, "tb/data_class": spec.output_class.tag},
            },
        )

    def _refuse(
        self,
        mid: Any,
        ev: FrontdoorAuditEvent,
        reason: str,
        *,
        extra: dict[str, Any] | None = None,
        audit_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            self._write("frontdoor.call", ev, audit_extra)
        except Exception:
            return _error(mid, AUDIT_FAILED, "audit ledger unavailable")
        body: dict[str, Any] = {"refused": reason, **(extra or {})}
        return _result(
            mid,
            {
                "content": [{"type": "text", "text": json.dumps(body)}],
                "structuredContent": body,
                "isError": True,
                "_meta": {"tb/untrusted": True},
            },
        )

    def _write(self, event: str, ev: FrontdoorAuditEvent, extra: dict[str, Any] | None = None) -> None:
        detail = ev.model_dump(mode="json") | (extra or {})
        self.audit.append(event, actor=ev.user, input_sha=ev.args_sha256, detail=detail)

    def _alarm(self, tool: str, reason: str, conv: str | None) -> None:
        ev = FrontdoorAuditEvent(user="?", tool=tool, args_sha256="", decision="refuse", reason=reason, conv=conv)
        self.audit.append("frontdoor.auth.refuse", actor="?", detail={**ev.model_dump(mode="json"), "alarm": True})
        if self.on_alarm is not None:
            self.on_alarm(reason, conv or "")

    # ------------------------------------------------------------------------------------------------ tools
    def _run(
        self, spec: ToolSpec, parsed: BaseModel, claims: IdentityAssertion, principal: Principal, client: str
    ) -> BaseModel:
        if isinstance(parsed, SubmitRequestIn):
            return self._submit(parsed, claims, principal, client)
        if isinstance(parsed, StatusIn):
            return self._status(parsed, principal)
        if isinstance(parsed, AskProtocolIn):
            return self.protocol.answer(parsed.study, parsed.question)
        if isinstance(parsed, RegistrySearchIn):
            return RegistrySearchOut(records=self.registry.search(parsed.query, parsed.limit))
        if isinstance(parsed, AtlasDescribeIn):
            snap, rows = self.atlas.describe(parsed.domain)
            rounded = [
                r.model_copy(update={"coverage_pct": None if r.coverage_pct is None else 5 * round(r.coverage_pct / 5)})
                for r in rows
            ]
            return AtlasDescribeOut(snapshot=snap, rows=rounded)
        if isinstance(parsed, AggregateQueryIn):
            return self._aggregate(parsed, principal)
        if isinstance(parsed, ResendIn):
            return self._resend(parsed, claims, principal)
        if isinstance(parsed, OpsReadIn):
            return OpsReadOut(panel=parsed.panel, rows=self.ops.read(parsed.panel))
        raise ToolRefused("tool_unknown", spec.name)  # unreachable: TOOL_MODELS covers every tool

    def _submit(
        self, req: SubmitRequestIn, claims: IdentityAssertion, principal: Principal, client: str
    ) -> SubmitRequestOut:
        if req.study and req.study != "NEW" and req.study not in principal.delegations:
            raise ToolRefused("not_delegated", "requests on an existing study need a delegation on it")
        refs: dict[str, str] = {}
        for key, val in req.params.items():
            if not isinstance(val, str):
                continue
            if RELAY_TOKEN.match(val):
                # HER-12: resolvable only for this message, sender and conversation, until expiry
                refs[val] = self.tokens.resolve(val, msg=claims.msg, sender=claims.sub, conv=claims.conv)
                continue
            if self.guard.tripwire(val).hit:
                raise ToolRefused("identifier_in_params", f"parameter {key} carries an identifier (HER-11)")
        p = self.requests.propose(
            req.type,
            req.study,
            req.params,
            language=req.language,
            sender=claims.sub,
            channel=claims.channel,
            conv=claims.conv,
            msg=claims.msg,
            actor_type="hermes" if client == "hermes" else "agent",
            refs=refs,
        )
        return SubmitRequestOut(
            ticket_id=p.ticket_id,
            commands=p.commands,
            restatement=p.restatement,
            confirm_instruction=p.confirm_instruction,
            expires_at=p.expires_at,
        )

    def _status(self, req: StatusIn, principal: Principal) -> StatusOut:
        props = self.requests.for_sender(principal.sub, req.study)
        if req.ticket_id:
            props = [p for p in props if p.ticket_id == req.ticket_id]
        items = [
            StatusItem(
                ticket_id=p.ticket_id,
                type=p.type,
                state=p.state,
                study=p.study,
                next_gate="confirmation" if p.state.value == "proposed" else None,
                due=p.expires_at.date().isoformat() if p.state.value == "proposed" else None,
            )
            for p in props
        ]
        by_state: dict[str, int] = {}
        for p in props:
            by_state[p.state.value] = by_state.get(p.state.value, 0) + 1
        counts = {r.key: r.value for r in rounded_rows(by_state, SMALL_CELL)}
        return StatusOut(items=items, counts=counts)

    def _aggregate(self, req: AggregateQueryIn, principal: Principal) -> AggregateQueryOut:
        self.catalogue.check(req.metric, req.breakdown)
        data_cut, counts = self.aggregates.counts(req.metric, req.breakdown, req.study)
        rows = rounded_rows(counts, self.catalogue.threshold)
        entry = self.accountant.record(principal.sub, req.metric, req.breakdown, req.study, len(rows))
        return AggregateQueryOut(
            metric=req.metric, breakdown=req.breakdown, rows=rows, data_cut=data_cut, accountant_entry_id=entry
        )

    def _resend(self, req: ResendIn, claims: IdentityAssertion, principal: Principal) -> ResendOut:
        rel = self.releases.get(req.release_id)
        if rel is None or principal.sub not in rel.recipients:
            # same answer for unknown and not-yours: the tool does not reveal which releases exist
            return ResendOut(status="refused", reason="not_a_recipient")
        msg = OutboxMessage(
            kind="release_resend",
            recipient=principal.address,
            channel="email",
            payload={"release_id": rel.release_id, "requested_by": principal.sub},
            key="resend",
            payload_ref=rel.payload_ref,
        )
        self.steps.run_step(
            rel.job_id,
            f"resend:{rel.release_id}",
            sha256_text(canonical_json({"release": rel.release_id, "msg": claims.msg, "sub": principal.sub})),
            lambda: StepResult(output={"release_id": rel.release_id, "resent_to": principal.sub}, sends=[msg]),
        )
        return ResendOut(status="sent")


# A well-formed call per tool, returned with ``invalid_arguments`` so a model can correct itself on the next step.
EXAMPLES: dict[str, dict[str, Any]] = {
    "tb.submit_request": {"type": "FEAS", "study": "GZQO", "params": {"lookback": "36m"}, "language": "en"},
    "tb.ask_protocol": {"study": "GZQO", "question": "What is the upper age limit?"},
    "tb.status": {"study": "GZQO"},
}


def _problems(e: ValidationError) -> list[dict[str, str]]:
    """Field path and reason of each validation error, without the offending input (it may carry an identifier)."""
    out = []
    for err in e.errors(include_input=False, include_url=False)[:8]:
        loc = ".".join(str(x) for x in err.get("loc", ())) or "arguments"
        out.append({"field": loc, "problem": str(err.get("msg", "invalid"))[:200]})
    return out


def _result(mid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
