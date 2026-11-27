"""tb-gateway v0 request pipeline (spec v4 §8.2; S1-06, S1-07).

Processing order for ``POST /v1/chat/completions`` (each step passes or refuses; every refusal is audited):

1. caller identity: ``X-TB-Caller`` must be on the allowlist, with the role and purpose it asks for (LLM-48), and a
   name the verified service may claim: the service the request's service token identifies (T-212b, D-437, CR-040;
   :meth:`gateway.policy.RoutingPolicy.check_claim`), else ``caller_unverified``;
2. header validation: class, purpose, role, study, context of use and prompt are required (LLM-2, ENG-04); D3/D4
   also need a study and step that the step confirmer accepts as live, except a D3 (never D4) call without a step
   on the intake role of a conversation engine whose caller entry sets ``d3_intake_without_step`` (FR-CONV-8: intake
   precedes any study step), or, with no step confirmer wired, a D3 call the box policy allows (``phi_on_box``,
   D-142: topology A, listed callers, perimeter endpoints only, because the data never leaves the box); a
   schema-constrained ``response_format`` is required except for free-form roles (LLM-22); the prompt is resolved
   by ``(id, version)`` in the prompt registry (D-300, :mod:`tb_llm.prompt_registry`) and the request is bound to
   it: an unknown version, a registered text or schema whose sha differs from the registry, a version without a
   qualification record in PRODUCTION, a prompt with no schema on a patient route (D2-D4), messages that are not
   the registered template rendered (the literal text between its ``{{ }}`` expressions, in order, anchored at both
   ends of the system and of the user message; what the expressions render to is not checked), a response schema
   that is not the registered one, and, outside DEV and TEST, a missing ``X-TB-Prompt-Sha`` are refused; an id the
   registry does not list passes only in DEV and TEST (synthetic data) or on a D0 call (the public evaluation
   suites); a free-form role (no prompt header) is not resolved;
3. route lookup: ``(role, class, topology, environment, profile)`` → ordered candidates, each checked with
   ``may_reach`` (§7.2) — no route or no permitted endpoint is refused (``no_route``, ``class_route_mismatch``);
4. PHI tripwire on D0–D2 calls (LLM-15, D-792): a hit keeps the call on the box (topology A's perimeter) or blocks
   it when no on-box build is left; it is never relabelled;
5. registry resolution of each candidate alias to a pinned build (S1-07; unpinned builds are refused); a candidate
   outside the perimeter (``external``, ``dev_public``) also needs a provider pin for that endpoint (S1-14), because a
   weight hash cannot vouch for what a third party serves (``provider_unpinned``); a request whose estimated size
   (:mod:`tb_llm.budget`: the messages plus ``max_tokens``) is over the build's ``context_length`` is refused
   ``prompt_too_long`` (HTTP 413) before anything is sent, with no other build tried (T-603, review LLM-015).
   ``GET /v1/models`` gives each alias's context, so callers size their prompts from it;
6. response cache keyed by (messages and response format, model sha, sampling, ``max_tokens``) for cacheable D0/D1
   roles (§8.12); only a complete answer is kept: one cut off (``finish_reason`` other than ``stop``) or outside its
   schema is not, so a retry with a larger budget reaches the model (T-603, review LLM-017);
7. dispatch with forced sampling (MOD-4) and structured-output pass-through. A transport error or an HTTP 5xx is
   retried once on the same build. Another alias answers only where the route says ``fallback: any`` and the role
   is not a patient role (T-601, D-276; deep review LLM-002, LLM-003): a patient role gets the build it named, or
   the route's first build, or an error. An upstream HTTP 400 or 404 (and any 4xx but 408 and 429) is a
   configuration fault: it ends the call (``prompt_too_long`` when the server says the prompt is over its context,
   else ``upstream_failed``), with no retry and no other build. A timeout is not retried (the request may still be
   running on the server);
   under load (T-608, D-445; review LLM-023): one call has a budget (``TB_GATEWAY_CALL_BUDGET_S``, 210 s) that its
   retry and fallbacks share, each attempt reads at most 180 s (batch) or 30 s (interactive) and no longer than
   the budget left; an endpoint takes at most its slots (:mod:`gateway.load`: the server's ``max_num_seqs``), an
   interactive call that finds none within 0.5 s gets ``model_busy``; an endpoint whose breaker is open is not
   sent to (``model_busy`` for an interactive role, ``model_unavailable`` for a batch one, both 503 with
   ``Retry-After``); while a screening run holds the one-GPU swap, only the holder's own batch calls hear
   ``model_asleep``, every other call ``model_busy`` at once, and no call wakes the sleeping model (D-445 §6);
8. served-model echo check (the upstream must report the build's served name and, for a provider-pinned build, the
   pinned provider; the request asked for that provider only, with no fallback);
9. audit record appended before the response is returned (LLM-5), then the redacted trace (§8.14). The response
   names the build that answered (``tb.build_id``, ``tb.build_sha``, headers ``X-TB-Build-Id`` and
   ``X-TB-Build-Sha``), the alias the call was meant to get (``tb.expected_alias``) and how many other candidates
   failed first (``tb.fallbacks``, header ``X-TB-Fallbacks``; ``tb_llm`` raises on an answer from another alias).

The call record holds hashes, labels, tokens, latency and cost — never prompt or response text, and never request
headers (the endpoint API key is added to the upstream request only). Cost is the upstream's reported ``usage.cost``
when it reports one (OpenRouter does), else the routing-table price.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from guard.guard import Guard
from registry.registry import Registry, RegistryError, Resolved, check_served, provider_routing
from tb_common import egress_edge
from tb_common.audit import AuditLog, canonical
from tb_common.config import environment_name
from tb_common.crypto import sha256_text
from tb_common.policy.classes import Environment, Topology
from tb_common.ulid import new_ulid
from tb_contracts.dataclass import ClassLabel, DataClass
from tb_llm.budget import estimate_messages, over_context
from tb_llm.prompt_registry import (
    PATIENT_CLASSES,
    PromptRegistry,
    PromptRegistryError,
    default_registry,
    parse_ref,
    schema_sha,
)
from tb_llm.timeouts import CALL_BUDGET_S, CONNECT_S, UPSTREAM_READ_S
from tracestore.store import TraceStore

from gateway.load import INTERACTIVE_SLOT_WAIT_S, PROBE_TIMEOUT_S, LoadControl
from gateway.policy import Candidate, Refusal, RoutingPolicy, _match, endpoint_key, parse_label
from gateway.swap import ModelSwap

StepConfirm = Callable[[str, str, str], bool]  # (caller, study, step) -> live and delegated
# interactive roles (routing.yaml ``interactive: true``, the front desk) wait this long for the model, then get
# ``model_busy``: a person is waiting, while batch roles keep the long limit of the HTTP client
INTERACTIVE_TIMEOUT_S = 30.0
BUSY_MESSAGE = "the model is busy (a screening run is using the GPU); try again in a few minutes"
UNAVAILABLE_MESSAGE = "the model server does not answer (its breaker is open); try again later"
# Retry-After (seconds) on the 503 refusals (T-608)
# ``upstream_down`` (T-689 review, D-456): a batch caller may send the call again; the breaker turns a server that
# stays down into ``model_unavailable`` after a few of these
RETRY_AFTER = {"model_busy": "5", "model_asleep": "5", "model_unavailable": "30", "upstream_down": "5"}
_BUSY = ": busy"  # an error the caller may retry soon (an interactive timeout, no slot)


class Upstream(str):
    """One error of an attempt on an endpoint: its text (for the audit and the answer) and its kind. D-636: what the
    gateway answers (busy, unavailable, down, failed) is decided from the kind, never from how the text ends."""

    kind: str

    def __new__(cls, text: str, kind: str = "other") -> Upstream:
        self = super().__new__(cls, text)
        self.kind = kind  # busy | open | retried | timeout | other
        return self


def only_kinds(errors: Sequence[str], kinds: set[str]) -> bool:
    """There were errors and every one is of one of ``kinds``; a plain text has the kind ``other``."""
    return bool(errors) and all(getattr(e, "kind", "other") in kinds for e in errors)


_OPEN = ": unavailable (breaker open)"
_RETRIED = " (tried twice)"  # a server error or a transport error that the one retry on the same build met again
# T-601: a transport error or HTTP 5xx is tried once more on the same build after this pause
RETRY_DELAY_S = 0.5
# the body fields a caller may send on to the model server (T-605, D-431, review LLM-019); sampling is then forced
UPSTREAM_FIELDS = frozenset(
    {
        "messages",
        "max_tokens",
        "max_completion_tokens",
        "response_format",
        "temperature",
        "top_p",
        "seed",
        "reasoning",
        "reasoning_effort",
    }
)
# an upstream 4xx is the call's own fault or a configuration fault, so no other build is tried; except these two
_TRANSIENT_4XX = (408, 429)
# what vLLM (and OpenAI-compatible servers) say when the prompt plus max_tokens is over the model's context
_TOO_LONG = ("maximum context length", "context length", "context_length", "too many tokens", "prompt is too long")
# chat() and activate() called inside the gateway's own process (``trialbox doctor``'s judge-route check, tests): no
# network boundary, so no service token to bind the caller to (D-437). The HTTP app always passes the verified service
log = logging.getLogger("gateway")
#: P-29: one line per answered call with its token counts, so the model's tokens can be measured from the service log
#: on the box (the ledger's ``llm.gateway.call`` holds the same counts). Counts and labels only, never text.
token_log = logging.getLogger("gateway.tokens")


def _count(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _log_tokens(call: _Call) -> None:
    token_log.info(
        "call %s: %d tokens in, %d out",
        call.call_id,
        call.tokens_in,
        call.tokens_out,
        extra={
            "call_id": call.call_id,
            "alias": call.alias,
            "build_id": call.build_id,
            "cache": call.cache,
            "tokens_in": call.tokens_in,
            "tokens_out": call.tokens_out,
            "tokens_reported": call.tokens_reported,
            "tokens_estimated": call.tokens_estimated,
            "latency_ms": call.latency_ms,
        },
    )


IN_PROCESS = "<in-process>"
REQUIRED = ("x-tb-caller", "x-tb-data-class", "x-tb-purpose", "x-tb-role", "x-tb-study", "x-tb-context-of-use")


@dataclass(frozen=True)
class GatewayConfig:
    topology: Topology = Topology.A
    environment: Environment = Environment.DEV
    profile: str = "P-GB10"
    cloud_opt_in: bool = False
    # D-506 (the owner's ruling, blocker 4): the PHI tripwire guards the routes that leave the box; on by default,
    # TB_GATEWAY_PHI_TRIPWIRE=off turns it off
    phi_tripwire: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GatewayConfig:
        e = os.environ if env is None else env
        return cls(
            topology=Topology(e.get("TB_TOPOLOGY", "A")),
            environment=Environment(environment_name(e)),
            profile=e.get("TB_PROFILE", "P-GB10"),
            cloud_opt_in=e.get("TB_CLOUD_OPT_IN", "").lower() in ("1", "true", "yes"),
            phi_tripwire=_tripwire_setting(e.get("TB_GATEWAY_PHI_TRIPWIRE")),
        )


def _tripwire_setting(raw: str | None) -> bool:
    """``TB_GATEWAY_PHI_TRIPWIRE`` (D-792): ``off`` (``0``, ``false``, ``no``) turns the tripwire off; unset, ``on``
    (``1``, ``true``, ``yes``) keeps it on; any other value keeps it on and says so."""
    v = (raw or "on").strip().lower()
    if v in ("off", "0", "false", "no"):
        return False
    if v not in ("on", "1", "true", "yes"):
        log.warning("TB_GATEWAY_PHI_TRIPWIRE=%r is neither on nor off: the PHI tripwire stays on", raw)
    return True


@dataclass
class GatewayResponse:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _Call:
    call_id: str
    caller: str = ""
    service: str = ""  # the verified service (its token's identity, D-437); "" when none or in-process
    role: str = ""
    purpose: str = ""
    study: str = ""
    step: str = ""
    context_of_use: str = ""
    prompt: str = ""  # id@version
    prompt_sha: str = ""  # the registry's sha256 of that version (D-300)
    prompt_registered: bool | None = None
    data_class: str = ""
    rendered_sha: str = ""
    route_id: str = ""
    alias: str = ""
    build_id: str = ""
    build_sha: str = ""
    thinking_control: str | None = None
    endpoint: str = ""
    zone: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    slot_wait_ms: float = 0.0  # D-627: waiting for an endpoint slot, summed over the endpoints tried
    cost: float = 0.0
    cache: str = "miss"
    output_sha: str = ""
    schema_valid: bool | None = None
    guard: str = "not_run"
    fallbacks: int = 0  # candidates that failed before the one that answered
    retries: int = 0  # second tries on the same build (T-601)
    expected_alias: str = ""  # the alias this call was meant to get: the one it named, else the route's first
    tokens_est: int = 0  # the request's estimated prompt size (T-603, tb_llm.budget)
    context: int | None = None  # the context of the build tried last (registry context_length)
    step_basis: str = ""  # D3/D4: "step" (confirmed), "intake" (FR-CONV-8) or "box_policy" (D-142)
    deadline: float = 0.0  # time.monotonic() by which this call ends (T-608, the call budget)
    tokens_estimated: bool = False  # the upstream said its token counts are estimates (the stub, LLM-046)
    tokens_reported: bool = False  # P-29: the upstream gave both counts; else the zeros are not counts


def _content_text(messages: Any) -> str:
    parts: list[str] = []
    for m in messages if isinstance(messages, list) else []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.extend(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return "\n".join(parts)


def _leaves(v: Any) -> Iterator[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict | list):
        for x in v.values() if isinstance(v, dict) else v:
            yield from _leaves(x)


def _body_text(body: Mapping[str, Any]) -> str:
    """Every text of a call that would leave the box: its messages with their tool calls, the answer's schema, the
    tools (OCR 1523-13). A part that is no text cannot be read: refused."""
    for m in body.get("messages") or []:
        parts = m.get("content") if isinstance(m, dict) else None
        if isinstance(parts, list) and any(not isinstance(p, dict) or p.get("type", "text") != "text" for p in parts):
            raise egress_edge.Refused("model.offbox", "unreadable")
    return "\n".join(_leaves({k: v for k, v in body.items() if k != "model"}))


def _schema_ok(content: str, response_format: Any) -> bool | None:
    try:
        schema = response_format["json_schema"]["schema"]
    except (KeyError, TypeError):
        return None
    try:
        import jsonschema
        from tb_contracts import null_absent

        jsonschema.validate(null_absent(schema, json.loads(content)), schema)  # null == absent (strict schemas)
        return True
    except Exception:
        return False


class Gateway:
    def __init__(
        self,
        policy: RoutingPolicy,
        registry: Registry,
        audit: AuditLog,
        config: GatewayConfig | None = None,
        *,
        http: httpx.Client | None = None,
        guard: Guard | None = None,
        traces: TraceStore | None = None,
        step_confirm: StepConfirm | None = None,
        env: Mapping[str, str] | None = None,
        cache_size: int = 1024,
        swap: ModelSwap | None = None,
        prompts: PromptRegistry | None = None,
    ) -> None:
        self.policy = policy
        self.registry = registry
        self.audit = audit
        self.config = config or GatewayConfig()
        if not self.config.phi_tripwire and self.config.environment.value == "PRODUCTION":  # M3: refused at start
            raise ValueError("TB_GATEWAY_PHI_TRIPWIRE=off is refused on a PRODUCTION box: set it to on")
        if not self.config.phi_tripwire:  # D-792: the owner's setting; said once at start, and on every call's audit
            log.warning(
                "the PHI tripwire is off (TB_GATEWAY_PHI_TRIPWIRE=off): D0-D2 calls may leave the box unchecked "
                "(environment %s)",
                self.config.environment.value,
            )
        # T-608 (D-445): connect 5 s, read 180 s; each attempt is cut to the call's budget left
        self.http = http or httpx.Client(timeout=httpx.Timeout(UPSTREAM_READ_S, connect=CONNECT_S))
        self.guard = guard or Guard.from_settings()
        self.traces = traces
        self.step_confirm = step_confirm
        self.env: Mapping[str, str] = os.environ if env is None else env
        self.swap = swap  # TB_MODEL_SWAP=sleep: judge and verifier time-share one GPU (gateway.swap)
        self.interactive_timeout_s = float(self.env.get("TB_GATEWAY_INTERACTIVE_TIMEOUT_S") or INTERACTIVE_TIMEOUT_S)
        self.retry_delay_s = float(self.env.get("TB_GATEWAY_RETRY_DELAY_S") or RETRY_DELAY_S)
        self.upstream_read_s = float(self.env.get("TB_GATEWAY_UPSTREAM_READ_S") or UPSTREAM_READ_S)
        self.call_budget_s = float(self.env.get("TB_GATEWAY_CALL_BUDGET_S") or CALL_BUDGET_S)
        self.load = LoadControl(policy.endpoints, self.env, probe=self._probe)  # slots and breakers (T-608)
        self.cache: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
        self.cache_size = cache_size
        self._cache_lock = threading.Lock()  # the HTTP app runs calls in a thread pool
        self.prompts = prompts or default_registry()
        if self.config.environment == Environment.PRODUCTION:
            # D-300: a changed prompt file, or a version without a qualification record, stops the start
            self.prompts.check(Environment.PRODUCTION.value)

    # ------------------------------------------------------------------------------------------------ public
    def _auth_open(self) -> bool:
        """The service-token layer admits calls without a token here (``TB_ENV`` DEV or TEST, as
        :func:`tb_common.service_auth.authorize` reads it, from this process's environment); a call without a service
        identity can only come from it."""
        return environment_name(os.environ) in ("DEV", "TEST")

    def _probe(self, endpoint: str) -> bool:
        """The stall check's question (T-608): does ``endpoint``'s server answer ``GET /models`` within 3 s?"""
        ep = self.policy.endpoints.get(endpoint)
        url = ep.url(dict(self.env)).rstrip("/") if ep is not None else ""
        if not url:
            return True  # nothing to ask: not a stalled server
        key = endpoint_key(ep.api_key_env, self.env) if ep is not None and ep.api_key_env else ""
        try:
            r = self.http.get(
                f"{url}/models",
                headers={"Authorization": f"Bearer {key}"} if key else {},
                timeout=min(PROBE_TIMEOUT_S, max(0.1, self.load.stall_s)),
            )
        except httpx.HTTPError:
            return False
        return r.status_code < 500

    def _swap_refusal(self, caller: str, service: str | None) -> GatewayResponse | None:
        """None when ``service`` (the verified token identity, D-437) may drive the swap as ``caller``: a service of
        ``serving_control`` with a caller it may claim whose entry may use the ``judge`` role; else the audited 403."""
        c = self.policy.callers.get(caller)
        code, msg = "", ""
        if c is None or not _match("judge", c.roles):
            code, msg = "caller_unknown", f"caller {caller!r} may not swap models"
        elif service != IN_PROCESS:
            try:
                self.policy.check_claim(service, caller, self.config.environment, auth_open=self._auth_open())
            except Refusal as r:
                code, msg = r.reason, str(r)
            else:
                verified = service and service != "legacy"
                if verified and service not in self.policy.serving_control:
                    code, msg = "caller_unverified", f"service {service} may not swap models"
        if not code:
            return None
        who = "" if service == IN_PROCESS else (service or "")
        self.audit.append("llm.gateway.swap_refused", detail={"caller": caller, "service": who, "reason": code})
        return GatewayResponse(403, {"error": {"type": "tb_refusal", "code": code, "message": msg}})

    def activate(
        self, caller: str, endpoint: str, hold: bool = False, *, service: str | None = IN_PROCESS
    ) -> GatewayResponse:
        """Wake ``endpoint`` and put the other swappable one to sleep (``POST /v1/serving/activate``). Allowed for
        the verified services of ``serving_control`` (the orchestrator, the operator) calling as a caller they may
        claim whose allowlist entry may use the ``judge`` role (T-212b, D-437). ``hold``: a screening run keeps the
        card until :meth:`release` (no wake on demand meanwhile, D-116)."""
        from gateway.swap import SwapError

        if self.swap is None:
            return GatewayResponse(200, {"swap": "off", "active": None})
        refused = self._swap_refusal(caller, service)
        if refused is not None:
            return refused
        who = "" if service == IN_PROCESS else (service or "")
        try:
            st = self.swap.activate(endpoint, hold=hold, holder=who)  # D-445: the hold names its service
        except SwapError as e:
            detail = {"caller": caller, "service": who, "endpoint": endpoint, "error": str(e)}
            self.audit.append("llm.gateway.swap_failed", detail=detail)
            return GatewayResponse(502, {"error": {"type": "swap_failed", "message": str(e)}})
        self.audit.append("llm.gateway.swap", detail={"caller": caller, "service": who, **st})
        return GatewayResponse(200, st)

    def release(self, caller: str, *, service: str | None = IN_PROCESS) -> GatewayResponse:
        """``POST /v1/serving/release``: the screening run lets go of the card; nothing is swapped back now. Same
        rule as :meth:`activate`."""
        if self.swap is None:
            return GatewayResponse(200, {"swap": "off", "active": None})
        refused = self._swap_refusal(caller, service)
        if refused is not None:
            return refused
        st = self.swap.release()
        who = "" if service == IN_PROCESS else (service or "")
        self.audit.append("llm.gateway.swap_release", detail={"caller": caller, "service": who, **st})
        return GatewayResponse(200, st)

    def models(self) -> list[str]:
        """Aliases only (§8.2): no builds, hashes or endpoint addresses."""
        return sorted(self.registry.aliases)

    def contexts(self) -> dict[str, int | None]:
        """Each alias's context in tokens (T-603, review LLM-015): the ``context_length`` of the builds the alias can
        route to here (not retired or suspended; pinned, or the stub in DEV/TEST), the smallest when several could;
        None when none of them records one. Callers size prompts from it; the gateway checks each call against the
        build that takes it."""
        env = self.config.environment
        sandbox = env in (Environment.DEV, Environment.TEST)
        out: dict[str, int | None] = {}
        for alias in sorted(self.registry.aliases):
            sizes = [
                int(b.context_length)
                for b in self.registry.builds
                if b.alias == alias
                and b.status.value not in ("retired", "suspended")
                and (b.pinned or (b.serving == "stub" and sandbox))
                and b.context_length
            ]
            out[alias] = min(sizes) if sizes else None
        return out

    def chat(
        self, headers: Mapping[str, str], body: dict[str, Any], *, service: str | None = IN_PROCESS
    ) -> GatewayResponse:
        """One model call. ``service``: the service the request's token identifies (``request.state.tb_caller``;
        None without one), which binds ``X-TB-Caller`` (D-437); :data:`IN_PROCESS` for a call from inside this
        process."""
        call = _Call(call_id=new_ulid(), deadline=time.monotonic() + self.call_budget_s)
        h = {k.lower(): v for k, v in headers.items()}
        try:
            return self._chat(call, h, body, service)
        except Refusal as r:
            said: dict[str, Any] = {"upstream_kinds": list(r.upstream_kinds)} if r.upstream_kinds else {}
            self._record("llm.gateway.refuse", call, reason=r.reason, message=str(r), **said)
            self._trace_refusal(call, body, r)
            headers = {
                "X-TB-Call-Id": call.call_id,
                "X-TB-Refusal": r.reason,
                "X-TB-Fallbacks": str(call.fallbacks),
                "X-TB-Retries": str(call.retries),
            }
            if r.reason in RETRY_AFTER:
                headers["Retry-After"] = RETRY_AFTER[r.reason]
            return GatewayResponse(
                r.status,
                {"error": {"type": "tb_refusal", "code": r.reason, "message": str(r), "call_id": call.call_id, **said}},
                headers,
            )

    #: the refusals of a call that was cleared for a model and failed there: its prompt is kept with the reason
    #: (D-911); a refusal of the call itself (its class, its caller, its prompt's registration) keeps no prompt
    MODEL_REFUSALS = frozenset({"upstream_failed", "upstream_down", "prompt_too_long"})

    def _trace_refusal(self, call: _Call, body: dict[str, Any], r: Refusal) -> None:
        """A refused call leaves a trace with its reason (D-911; red of lane G's run: 11 ``ir_extract`` calls refused
        as ``upstream_failed`` left nothing in the trace store to read). A failing trace write never changes the
        answer."""
        if self.traces is None:
            return
        attributes = {
            "tb.call_id": call.call_id,
            "tb.data_class": call.data_class,
            "tb.model_alias": call.alias,
            "tb.role": call.role,
            "tb.purpose": call.purpose,
            "tb.study_id": call.study,
            "tb.prompt": call.prompt,
            "tb.refusal": r.reason,
            "tb.upstream_kinds": list(r.upstream_kinds),
        }
        kept = r.reason in self.MODEL_REFUSALS
        with contextlib.suppress(Exception):
            self.traces.write(
                {
                    "call_id": call.call_id,
                    "span": "refusal",
                    "sc": kept,  # a kept prompt is read as special-category: never less guarded than an allowed call
                    "attributes": attributes,
                    "prompt": body.get("messages") if kept else None,
                    "output": None,
                }
            )

    # ------------------------------------------------------------------------------------------------ pipeline
    def _chat(self, call: _Call, h: dict[str, str], body: dict[str, Any], service: str | None) -> GatewayResponse:
        call.caller = h.get("x-tb-caller", "")
        call.service = "" if service == IN_PROCESS else (service or "")
        call.role = h.get("x-tb-role", "")
        call.purpose = h.get("x-tb-purpose", "")
        call.study = h.get("x-tb-study", "")
        call.step = h.get("x-tb-step", "")
        call.context_of_use = h.get("x-tb-context-of-use", "")
        call.prompt = h.get("x-tb-prompt", "")
        call.data_class = h.get("x-tb-data-class", "")
        messages = body.get("messages")
        response_format = body.get("response_format")
        call.rendered_sha = sha256_text(canonical({"messages": messages, "response_format": response_format}))
        call.tokens_est = estimate_messages(messages) if isinstance(messages, list) else 0

        # 1-2 identity and headers
        if not call.caller or call.caller not in self.policy.callers:
            raise Refusal("caller_unknown", f"caller {call.caller!r} is not on the gateway allowlist")
        if service != IN_PROCESS:
            # T-212b (D-437, CR-040): the header is a claim; the token's service must be allowed to make it
            self.policy.check_claim(service, call.caller, self.config.environment, auth_open=self._auth_open())
        missing = [k for k in REQUIRED if not h.get(k)]
        free_form = bool(self.policy.roles.get(call.role, {}).get("free_form"))
        if not free_form and not call.prompt:
            missing.append("x-tb-prompt")
        if missing:
            raise Refusal("header_missing", f"missing headers: {', '.join(missing)}")
        label = parse_label(call.data_class)
        call.data_class = label.tag
        caller = self.policy.check_caller(call.caller, call.role, call.purpose)
        intake = (
            caller.d3_intake_without_step
            and call.role == caller.intake_role
            and label.data_class == DataClass.D3
            and not call.step
        )
        box_only = False
        if intake:
            call.step_basis = "intake"
        elif label.data_class.rank >= 3:
            cfg = self.config
            if self.step_confirm is not None and call.step and self.step_confirm(call.caller, call.study, call.step):
                call.step_basis = "step"
            elif self.step_confirm is None and self.policy.box_phi.allows(
                call.caller, label, cfg.topology, cfg.environment
            ):
                # D-142: on an on-prem box without a step confirmer the data never leaves the box; perimeter
                # endpoints only (below). Where a confirmer is wired (LLM-2), its answer alone decides.
                call.step_basis, box_only = "box_policy", True
            else:
                raise Refusal("step_unconfirmed", "D3/D4 calls need a live, delegated study step (LLM-2)")
        if not isinstance(messages, list) or not messages:
            raise Refusal("request_invalid", "messages must be a non-empty list")
        if not free_form:
            rf = response_format if isinstance(response_format, dict) else {}
            if rf.get("type") != "json_schema" or not isinstance(rf.get("json_schema"), dict):
                raise Refusal("schema_required", "a json_schema response_format is required for this role (LLM-22)")
        self._resolve_prompt(call, h, label, messages, response_format, free_form)

        # 3 route
        flags = frozenset(x.strip() for x in h.get("x-tb-flags", "").split(",") if x.strip())
        cfg = self.config
        route, candidates = self.policy.candidates(
            call.role, label, cfg.topology, cfg.environment, cfg.profile, cloud_opt_in=cfg.cloud_opt_in, flags=flags
        )
        call.route_id = route.id
        if box_only:
            candidates = [c for c in candidates if c.endpoint.zone == "perimeter"]
            if not candidates:
                raise Refusal("step_unconfirmed", "D3 without a confirmed step goes to on-box models only (D-142)")
        wanted = body.get("model")
        if wanted:
            candidates = [c for c in candidates if c.alias == wanted]
            if not candidates:
                raise Refusal("class_route_mismatch", f"model {wanted!r} is not on route {route.id} for {label.tag}")
        if self.policy.no_fallback(route, call.role, call.context_of_use):
            # D-276 (review LLM-002): a judge whose server failed was answered by the next build of the route, the
            # verifier, which then confirmed its own answer. For these roles a failed build is the call's error.
            # T-601: the build is the one named, else the route's *declared* first build, never the first one left
            # after the filters above (a perimeter or environment filter that drops the judge build must not make
            # the verifier build the judge)
            call.expected_alias = str(wanted) if wanted else route.builds[0][0]
            candidates = [c for c in candidates if c.alias == call.expected_alias]
            if not candidates:
                raise Refusal(
                    "no_eligible_build",
                    f"{call.expected_alias} may not take this {label.tag} call on route {route.id}, and role "
                    f"{call.role} never falls back to another build",
                )
        else:
            call.expected_alias = candidates[0].alias

        # 4 tripwire (D-506, blocker 4): it guards the routes that leave the box. A hit drops the candidates outside
        # the box and the call goes on to an on-box model; it is refused only when none is left. A declared setting
        # turns it off (on by default)
        if label.data_class.rank <= 2 and not cfg.phi_tripwire:
            call.guard = "off"
        elif label.data_class.rank <= 2:
            verdict = self.guard.tripwire(_content_text(messages))
            call.guard = "hit:" + ",".join(verdict.kinds) if verdict.hit else "clear"
            if verdict.hit:
                # on the box: a perimeter endpoint on topology A only. On topology B the perimeter is the tenant's
                # serving router, which is not on the box (D-142, ``RoutingPolicy.perimeter_checked``; review of D-792)
                on_box = [c for c in candidates if c.endpoint.zone == "perimeter" and cfg.topology == Topology.A]
                if not on_box:
                    raise Refusal(
                        "phi_tripwire", f"PHI tripwire hit on a {label.tag} call ({', '.join(verdict.kinds)})"
                    )
                if call.expected_alias not in {c.alias for c in on_box}:
                    call.expected_alias = on_box[
                        0
                    ].alias  # defensive: no shipped route puts an external build first (D-792)
                candidates = on_box
                call.guard += ":on_box"

        # 5-8 resolve, cache, dispatch, echo
        registry_refusals: list[RegistryError] = []
        upstream_errors: list[str] = []
        stopped: Refusal | None = None
        for cand in candidates:
            try:
                res = self.registry.resolve(
                    cand.alias,
                    cand.endpoint.name,
                    role=call.role,
                    env=cfg.environment,
                    qualification_probe=route.id == "qualify" and label.data_class == DataClass.D0,
                )
            except RegistryError as e:
                registry_refusals.append(e)
                call.fallbacks += 1
                continue
            pin, ep = res.build.provider_pin, cand.endpoint
            if ep.zone in ("external", "dev_public") and not (pin and pin["endpoint"] == ep.name):
                msg = f"build {res.build.build_id} has no provider pin for {ep.name} ({ep.zone})"
                registry_refusals.append(RegistryError("provider_unpinned", msg))
                call.fallbacks += 1
                continue
            if ep.zone != "perimeter":  # M3: a call that leaves the box passes the egress edge
                try:
                    egress_edge.leave("model.offbox", ep.name, _body_text(body) if cfg.phi_tripwire else "",
                                      audit=self.audit, actor=call.caller,
                                      unchecked=not cfg.phi_tripwire)  # fmt: skip
                except egress_edge.Refused as e:  # OCR 1523-13: a later candidate may be on the box
                    stopped = Refusal("phi_tripwire", f"the call may not leave the box ({e.reason})")
                    call.fallbacks += 1
                    continue
            out = self._try(call, cand, res, label, body, free_form, upstream_errors)
            if out is not None:
                return out
            call.fallbacks += 1
        if stopped is not None and not upstream_errors:
            raise stopped
        interactive = bool(self.policy.roles.get(call.role, {}).get("interactive"))
        if only_kinds(upstream_errors, {"busy"}):
            raise Refusal("model_busy", BUSY_MESSAGE, status=503)
        if only_kinds(upstream_errors, {"busy", "open"}):
            # T-608: nothing was sent to a server whose breaker is open; the front desk hears "busy"
            if interactive:
                raise Refusal("model_busy", BUSY_MESSAGE, status=503)
            raise Refusal("model_unavailable", UNAVAILABLE_MESSAGE, status=503)
        if upstream_errors:
            # T-689 review (D-456): the server did not answer and the retry met the same (5xx, a dropped or refused
            # connection): ``upstream_down``, the one 502 a batch caller sends again. A timeout (the server may still
            # be working on the call), a malformed answer or a spent budget stays ``upstream_failed``, as a
            # configuration fault (400, 404) does: never sent again by anyone
            down = only_kinds(upstream_errors, {"busy", "open", "retried"})
            code = "upstream_down" if down else "upstream_failed"
            kinds = tuple(sorted({getattr(e, "kind", "other") for e in upstream_errors}))
            raise Refusal(code, "; ".join(upstream_errors)[:500], status=502, upstream_kinds=kinds)
        first = registry_refusals[0] if registry_refusals else None
        raise Refusal(first.reason if first else "no_eligible_build", str(first) if first else "no candidate")

    def _resolve_prompt(
        self, call: _Call, h: dict[str, str], label: ClassLabel, messages: Any, response_format: Any, free_form: bool
    ) -> None:
        """D-300: resolve ``X-TB-Prompt`` (``id@version``) in the prompt registry and bind the request to it, or
        refuse (module docstring). A free-form role sends no prompt and is not checked here (D-300 records it)."""
        if not call.prompt:
            return
        env = self.config.environment
        sandbox = env in (Environment.DEV, Environment.TEST)
        pid = call.prompt.partition("@")[0]
        if pid not in self.prompts.ids:
            if sandbox or label.data_class == DataClass.D0:
                call.prompt_registered = False
                return
            raise Refusal("prompt_unregistered", f"prompt {pid!r} is not in the prompt registry ({label.tag} call)")
        call.prompt_registered = True
        try:
            pid, ver = parse_ref(call.prompt)
            if ver is None:
                raise PromptRegistryError("prompt_unknown", f"prompt {call.prompt!r}: name it as id@version")
            got = self.prompts.get(pid, ver, environment=env.value, patient=label.data_class.value in PATIENT_CLASSES)
            call.prompt = got.ref  # canonical (judge@4, never judge@04)
            self.prompts.check_messages(got, messages)
        except PromptRegistryError as e:
            raise Refusal(e.reason, str(e)) from e
        call.prompt_sha = got.sha256
        sent = h.get("x-tb-prompt-sha", "")
        if not sent and not sandbox:
            raise Refusal("prompt_changed", f"{got.ref}: X-TB-Prompt-Sha is required for a registered prompt")
        if sent and sent != got.sha256:
            raise Refusal("prompt_changed", f"{got.ref}: the caller's prompt text is not the registered one")
        want = got.entry.schema_sha256
        if want and not free_form:
            try:
                sent_schema = response_format["json_schema"]["schema"]
            except (KeyError, TypeError):
                sent_schema = None
            if schema_sha(sent_schema) != want:
                raise Refusal("prompt_schema_changed", f"{got.ref}: the response schema sent is not {got.entry.schema}")

    def _try(
        self,
        call: _Call,
        cand: Candidate,
        res: Resolved,
        label: ClassLabel,
        body: dict[str, Any],
        free_form: bool,
        errors: list[str],
    ) -> GatewayResponse | None:
        ep = cand.endpoint
        call.alias, call.build_id, call.build_sha = cand.alias, res.build.build_id, res.build.model_sha
        call.thinking_control = res.build.thinking_control
        call.endpoint, call.zone = ep.name, ep.zone
        call.context = int(res.build.context_length) if res.build.context_length else None
        max_tokens = body.get("max_tokens")
        max_tokens = max_tokens if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) else None
        if over_context(call.context, call.tokens_est, max_tokens):
            # T-603 (review LLM-015): the server would answer HTTP 400; nothing is sent and no other build is tried
            # (another build of the role has no larger context on this box, and on a patient route it is not allowed)
            raise Refusal(
                "prompt_too_long",
                f"about {call.tokens_est} prompt tokens + max_tokens {max_tokens or 0} is over {call.alias}'s context "
                f"of {call.context} tokens; size the prompt from GET /v1/models",
                status=413,
            )
        sampling = {} if free_form else dict(self.policy.sampling)
        cacheable = (
            bool(self.policy.roles.get(call.role, {}).get("cacheable")) and label.data_class.rank <= 1 and not free_form
        )
        # T-603 (review LLM-017): max_tokens is in the key, so a retry with a larger budget is not the cut-off answer
        key = (call.rendered_sha, res.build.model_sha, canonical({**sampling, "max_tokens": max_tokens}))
        hit: dict[str, Any] | None = None
        if cacheable:
            with self._cache_lock:
                if key in self.cache:
                    self.cache.move_to_end(key)
                    hit = json.loads(json.dumps(self.cache[key]))
        if hit is not None:
            call.cache = "hit"
            return self._allow(call, hit, label, body)

        # only allow-listed fields go upstream (T-605, review LLM-019): no n, logit_bias, stop or chat_template_kwargs
        upstream = {k: v for k, v in body.items() if k in UPSTREAM_FIELDS}
        upstream.update(sampling)
        upstream.pop("provider", None)  # provider routing comes from the registry pin only, never from the caller
        upstream["model"] = res.served_name
        if res.build.provider_pin is not None:
            upstream["provider"] = provider_routing(res.build.provider_pin)
        headers = {"X-TB-Call-Id": call.call_id}
        if call.prompt:
            pid, _, ver = call.prompt.partition("@")
            headers["X-TB-Prompt-Id"] = pid
            headers["X-TB-Prompt-Version"] = ver
            if call.prompt_sha:
                headers["X-TB-Prompt-Sha"] = call.prompt_sha
        ep_key = endpoint_key(ep.api_key_env, self.env) if ep.api_key_env else ""
        if ep_key:  # TB_LLM_API_KEY_FILE (a compose secret, D-437) before TB_LLM_API_KEY
            headers["Authorization"] = f"Bearer {ep_key}"
        url = ep.url(dict(self.env))
        if not url:
            errors.append(f"{ep.name}: no URL configured")
            return None
        interactive = bool(self.policy.roles.get(call.role, {}).get("interactive"))
        if self.swap is not None and ep.name in self.swap.urls:
            if not self.swap.awake(ep.name):
                was = self.swap.active
                if not self.swap.ensure(ep.name):  # D-445 §6: never across a hold (checked under the swap's lock)
                    # not sent, and no fallback either (the judge's route falls back to the verifier build, which
                    # must never answer in the judge's place during the verifier pass)
                    if self.swap.held and not interactive and call.service == self.swap.holder:
                        raise Refusal(
                            "model_asleep", f"{ep.name} is asleep (one-GPU swap); activate it first", status=503
                        )
                    if self.swap.held or interactive:
                        raise Refusal("model_busy", BUSY_MESSAGE, status=503)
                    raise Refusal("model_asleep", f"{ep.name} could not be woken (one-GPU swap)", status=503)
                self.audit.append(
                    "llm.gateway.swap",
                    detail={
                        "caller": "on-demand",
                        "service": call.service,
                        "from": was,
                        "role": call.role,
                        **self.swap.status(),
                    },
                )
            elif not interactive:
                self.swap.touch(call.service)  # D-445: only the holder's own calls keep its hold alive
        lane = self.load.endpoints.get(ep.name)
        if lane is not None and not lane.breaker.allow():
            errors.append(
                Upstream(f"{ep.name}{_OPEN}", "open")
            )  # T-608: not sent; a fallback-any route tries its next build
            return None
        ticket = None
        if lane is not None:
            left = call.deadline - time.monotonic()
            t_slot = time.perf_counter()
            ticket = lane.acquire(INTERACTIVE_SLOT_WAIT_S if interactive else left)
            # D-627: the queue in front of the server, apart from latency_ms (the server's own time); got or not
            call.slot_wait_ms = round(call.slot_wait_ms + (time.perf_counter() - t_slot) * 1000, 2)
            if ticket is None:
                lane.breaker.cancel()
                errors.append(Upstream(f"{ep.name}{_BUSY}", "busy"))  # every slot taken: model_busy (T-608)
                return None
        try:
            resp = self._send(call, ep.name, url, upstream, headers, interactive, lane, errors)
        finally:
            if lane is not None and ticket is not None:
                lane.release(ticket)
        if resp is None:
            return None
        if resp.status_code >= 400:
            # vLLM answers 404 to a model name it does not serve: name the one sent (the pin's served name)
            hint = f" (model {res.served_name!r} not served there?)" if resp.status_code == 404 else ""
            if resp.status_code < 500 and resp.status_code not in _TRANSIENT_4XX:
                # T-601 (review LLM-003): a 400 (prompt over the context, a bad request) or a 404 (a name the server
                # does not serve) is a fault of this call or of the box's set-up; another build answering would hide
                # it and, on a patient route, answer one role with another role's model. The call ends here
                text = resp.text[:2000].casefold()
                if resp.status_code in (400, 413) and any(k in text for k in _TOO_LONG):
                    raise Refusal(
                        "prompt_too_long",
                        f"{ep.name}: HTTP {resp.status_code}: the prompt is longer than {call.alias}'s context",
                        status=413,
                    )
                raise Refusal(
                    "upstream_failed",
                    f"{ep.name}: HTTP {resp.status_code}{hint}; a configuration fault, no other build is tried",
                    status=502,
                )
            again = resp.status_code >= 500  # a server error that the one retry on the same build met again
            text = f"{ep.name}: HTTP {resp.status_code}{hint}{_RETRIED if again else ''}"
            errors.append(Upstream(text, "retried" if again else "other"))
            return None
        try:
            payload = resp.json()
            content = str(payload["choices"][0]["message"].get("content") or "")
        except (ValueError, KeyError, IndexError, TypeError):
            errors.append(f"{ep.name}: malformed response")
            return None
        try:
            check_served(res, payload.get("model"), payload.get("provider"))
        except RegistryError as e:
            raise Refusal(e.reason, str(e), status=502) from e
        usage = payload.get("usage") or {}
        call.tokens_estimated = bool(usage.get("estimated"))  # LLM-046: the stub's counts are estimates
        call.tokens_in = int(usage.get("prompt_tokens") or 0)
        call.tokens_out = int(usage.get("completion_tokens") or 0)
        call.tokens_reported = all(_count(usage.get(k)) for k in ("prompt_tokens", "completion_tokens"))
        c = ep.cost
        reported = usage.get("cost")
        if isinstance(reported, int | float) and not isinstance(reported, bool):
            call.cost = round(float(reported), 8)
        else:
            call.cost = round(
                call.tokens_in / 1000 * c.get("usd_per_1k_in", 0.0)
                + call.tokens_out / 1000 * c.get("usd_per_1k_out", 0.0)
                + call.latency_ms / 1000 * c.get("gpu_second_usd", 0.0),
                8,
            )
        call.output_sha = sha256_text(content)
        call.schema_valid = _schema_ok(content, body.get("response_format"))
        finish = payload["choices"][0].get("finish_reason") if isinstance(payload["choices"][0], dict) else None
        # T-603 (review LLM-017): only a complete answer in its schema is kept; a cut-off or invalid one would be handed
        # back to the retry that asks for it again with more room. A server that reports no finish_reason is
        # taken as complete (the schema check still applies)
        complete = finish in (None, "stop") and call.schema_valid is not False
        if cacheable and complete:
            with self._cache_lock:
                self.cache[key] = json.loads(json.dumps(payload))
                while len(self.cache) > self.cache_size:
                    self.cache.popitem(last=False)
        return self._allow(call, payload, label, body)

    def _send(
        self,
        call: _Call,
        name: str,
        url: str,
        upstream: dict[str, Any],
        headers: dict[str, str],
        interactive: bool,
        lane: Any,
        errors: list[str],
    ) -> httpx.Response | None:
        """POST the call, with T-601's one retry on the same build, inside the call's budget (T-608). Each outcome
        tells the endpoint's breaker: an answer below 500 closes it; a connection error, a batch read timeout or a
        5xx after the retry counts toward opening it; an interactive read timeout counts for nothing (busy, not
        dead)."""
        breaker = lane.breaker if lane is not None else None
        resp: httpx.Response | None = None
        for attempt in (1, 2):
            left = call.deadline - time.monotonic()
            if attempt == 2:
                if left <= self.retry_delay_s + 1.0:
                    break  # no budget for the retry: the first answer (or error) stands
                call.retries += 1
                if self.retry_delay_s > 0:
                    time.sleep(self.retry_delay_s)
                left = call.deadline - time.monotonic()
            if left < 1.0:
                # walk step 5: the call ran out of time (its wait for a slot included), as a read timeout does
                errors.append(Upstream(f"{name}: the call's budget of {self.call_budget_s:.0f}s is spent", "timeout"))
                if breaker is not None:
                    breaker.cancel()
                return None
            limit = min(self.interactive_timeout_s if interactive else self.upstream_read_s, left)
            t0 = time.perf_counter()
            try:
                resp = self.http.post(
                    f"{url.rstrip('/')}/chat/completions",
                    json=upstream,
                    headers=headers,
                    timeout=httpx.Timeout(limit, connect=min(CONNECT_S, limit)),
                )
            except httpx.TimeoutException as e:
                # not tried again: the server may still be working on it, and a person may be waiting
                if breaker is not None:
                    if interactive and not isinstance(e, httpx.ConnectTimeout):
                        breaker.cancel()
                    else:
                        breaker.failure("timeouts")
                # D-728: a batch timeout is a kind of its own, so the refusal can say it as a field
                errors.append(
                    Upstream(f"{name}{_BUSY}", "busy")
                    if interactive
                    else Upstream(f"{name}: {type(e).__name__}", "timeout")
                )
                return None
            except httpx.HTTPError as e:
                if attempt == 1:
                    resp = None
                    continue  # T-601: a transport error is tried once more on the same build
                if breaker is not None:
                    breaker.failure("connection errors")
                errors.append(Upstream(f"{name}: {type(e).__name__}{_RETRIED}", "retried"))
                return None
            call.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            if resp.status_code >= 500 and attempt == 1:
                continue  # T-601: a server error is tried once more on the same build
            break
        if resp is None:
            if breaker is not None:
                breaker.failure("connection errors")
            errors.append(f"{name}: no answer (the call's budget left no retry)")
            return None
        if breaker is not None:
            if resp.status_code >= 500:
                breaker.failure("server errors")
            else:
                breaker.success()
        return resp

    def _allow(self, call: _Call, payload: dict[str, Any], label: ClassLabel, body: dict[str, Any]) -> GatewayResponse:
        if call.cache == "hit":
            content = str(payload["choices"][0]["message"].get("content") or "")
            call.output_sha = sha256_text(content)
            call.schema_valid = _schema_ok(content, body.get("response_format"))
            call.latency_ms = 0.0
            call.tokens_in = call.tokens_out = 0
            call.cost = 0.0
        self._record("llm.gateway.call", call)  # LLM-5: the ledger first, then the response
        _log_tokens(call)
        payload["tb"] = {
            "call_id": call.call_id,
            "alias": call.alias,
            "build_id": call.build_id,
            "build_sha": call.build_sha,
            "route_id": call.route_id,
            "policy_version": self.policy.version,
            "registry_version": self.registry.version,
            "cache": call.cache,
            "expected_alias": call.expected_alias,
            "fallbacks": call.fallbacks,
            "retries": call.retries,
        }
        if call.thinking_control is not None:
            payload["tb"]["thinking_control"] = call.thinking_control
        if self.traces is not None:
            self.traces.write(
                {
                    "call_id": call.call_id,
                    "span": "chat",
                    "sc": label.special_category,
                    "attributes": {
                        "tb.call_id": call.call_id,
                        "tb.data_class": call.data_class,
                        "tb.route_id": call.route_id,
                        "tb.model_alias": call.alias,
                        "tb.build_sha": call.build_sha,
                        "tb.cache": call.cache,
                        "tb.policy_version": self.policy.version,
                        "tb.context_of_use": call.context_of_use,
                        "tb.role": call.role,
                        "tb.purpose": call.purpose,
                        "tb.study_id": call.study,
                        # prompt_id@version (D-300); its sha is in the ledger record (the trace redactor reads
                        # long digit runs inside a hex digest as identifiers)
                        "tb.prompt": call.prompt,
                        "tb.prompt_registered": call.prompt_registered,
                    },
                    "prompt": body.get("messages"),
                    "output": payload["choices"][0]["message"].get("content"),
                }
            )
        return GatewayResponse(
            200,
            payload,
            {
                "X-TB-Call-Id": call.call_id,
                "X-TB-Model-Alias": call.alias,
                "X-TB-Build-Id": call.build_id,
                "X-TB-Build-Sha": call.build_sha,
                "X-TB-Fallbacks": str(call.fallbacks),
                "X-TB-Retries": str(call.retries),
            },
        )

    def _record(self, event: str, call: _Call, **extra: Any) -> None:
        detail = {
            "call_id": call.call_id,
            "service": call.service,  # the verified service behind X-TB-Caller (D-437)
            "decision": "refuse" if event.endswith("refuse") else "allow",
            "class": call.data_class,
            "purpose": call.purpose,
            "role": call.role,
            "study": call.study,
            "step": call.step,
            "step_basis": call.step_basis,
            "context_of_use": call.context_of_use,
            "prompt_sha": call.prompt_sha,
            "prompt_registered": call.prompt_registered,
            "prompt_registry_version": self.prompts.version,
            "route_id": call.route_id,
            "policy_version": self.policy.version,
            "registry_version": self.registry.version,
            "build_id": call.build_id,
            "model_sha": call.build_sha,
            "endpoint": call.endpoint,
            "zone": call.zone,
            "tokens_in": call.tokens_in,
            "tokens_out": call.tokens_out,
            "latency_ms": call.latency_ms,
            "slot_wait_ms": call.slot_wait_ms,
            "cost": call.cost,
            "cache": call.cache,
            "guard": call.guard,
            "schema_valid": call.schema_valid,
            "fallbacks": call.fallbacks,
            "retries": call.retries,
            "expected_alias": call.expected_alias,
            "tokens_est": call.tokens_est,
            "tokens_estimated": call.tokens_estimated,
            "tokens_reported": call.tokens_reported,
            "context": call.context,
            "topology": self.config.topology.value,
            "environment": self.config.environment.value,
            **extra,
        }
        self.audit.append(
            event,
            actor=call.caller or "?",
            model=call.alias or None,
            prompt_version=call.prompt or None,
            input_sha=call.rendered_sha or None,
            output_sha=call.output_sha or None,
            detail=detail,
        )
