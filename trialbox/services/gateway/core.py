"""tb-gateway v0 request pipeline (spec v4 §8.2; S1-06, S1-07).

Processing order for ``POST /v1/chat/completions`` (each step passes or refuses; every refusal is audited):

1. caller identity: ``X-TB-Caller`` must be on the allowlist, with the role and purpose it asks for (LLM-48);
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
4. PHI tripwire on D0–D2 calls (LLM-15): a hit blocks the call, it is never relabelled;
5. registry resolution of each candidate alias to a pinned build (S1-07; unpinned builds are refused); a candidate
   outside the perimeter (``external``, ``dev_public``) also needs a provider pin for that endpoint (S1-14), because a
   weight hash cannot vouch for what a third party serves (``provider_unpinned``);
6. response cache keyed by (prompt sha, model sha) for cacheable D0/D1 roles (§8.12);
7. dispatch with forced sampling (MOD-4) and structured-output pass-through; fallback only down the route list;
8. served-model echo check (the upstream must report the build's served name and, for a provider-pinned build, the
   pinned provider; the request asked for that provider only, with no fallback);
9. audit record appended before the response is returned (LLM-5), then the redacted trace (§8.14).

The call record holds hashes, labels, tokens, latency and cost — never prompt or response text, and never request
headers (the endpoint API key is added to the upstream request only). Cost is the upstream's reported ``usage.cost``
when it reports one (OpenRouter does), else the routing-table price.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from guard.guard import Guard
from registry.registry import Registry, RegistryError, Resolved, check_served, provider_routing
from tb_common.audit import AuditLog, canonical
from tb_common.config import environment_name
from tb_common.crypto import sha256_text
from tb_common.policy.classes import Environment, Topology
from tb_common.ulid import new_ulid
from tb_contracts.dataclass import ClassLabel, DataClass
from tb_llm.prompt_registry import (
    PATIENT_CLASSES,
    PromptRegistry,
    PromptRegistryError,
    default_registry,
    parse_ref,
    schema_sha,
)
from tracestore.store import TraceStore

from gateway.policy import Candidate, Refusal, RoutingPolicy, _match, parse_label
from gateway.swap import ModelSwap

StepConfirm = Callable[[str, str, str], bool]  # (caller, study, step) -> live and delegated
# interactive roles (routing.yaml ``interactive: true``, the front desk) wait this long for the model, then get
# ``model_busy``: a person is waiting, while batch roles keep the long limit of the HTTP client
INTERACTIVE_TIMEOUT_S = 30.0
BUSY_MESSAGE = "the model is busy (a screening run is using the GPU); try again in a few minutes"
REQUIRED = ("x-tb-caller", "x-tb-data-class", "x-tb-purpose", "x-tb-role", "x-tb-study", "x-tb-context-of-use")


@dataclass(frozen=True)
class GatewayConfig:
    topology: Topology = Topology.A
    environment: Environment = Environment.DEV
    profile: str = "P-GB10"
    cloud_opt_in: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GatewayConfig:
        e = os.environ if env is None else env
        return cls(
            topology=Topology(e.get("TB_TOPOLOGY", "A")),
            environment=Environment(environment_name(e)),
            profile=e.get("TB_PROFILE", "P-GB10"),
            cloud_opt_in=e.get("TB_CLOUD_OPT_IN", "").lower() in ("1", "true", "yes"),
        )


@dataclass
class GatewayResponse:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class _Call:
    call_id: str
    caller: str = ""
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
    endpoint: str = ""
    zone: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0
    cache: str = "miss"
    output_sha: str = ""
    schema_valid: bool | None = None
    guard: str = "not_run"
    fallbacks: int = 0
    step_basis: str = ""  # D3/D4: "step" (confirmed), "intake" (FR-CONV-8) or "box_policy" (D-142)


def _content_text(messages: Any) -> str:
    parts: list[str] = []
    for m in messages if isinstance(messages, list) else []:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            parts.extend(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return "\n".join(parts)


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
        self.http = http or httpx.Client(timeout=600.0)
        self.guard = guard or Guard.from_settings()
        self.traces = traces
        self.step_confirm = step_confirm
        self.env: Mapping[str, str] = os.environ if env is None else env
        self.swap = swap  # TB_MODEL_SWAP=sleep: judge and verifier time-share one GPU (gateway.swap)
        self.interactive_timeout_s = float(self.env.get("TB_GATEWAY_INTERACTIVE_TIMEOUT_S") or INTERACTIVE_TIMEOUT_S)
        self.cache: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
        self.cache_size = cache_size
        self._cache_lock = threading.Lock()  # the HTTP app runs calls in a thread pool
        self.prompts = prompts or default_registry()
        if self.config.environment == Environment.PRODUCTION:
            # D-300: a changed prompt file, or a version without a qualification record, stops the start
            self.prompts.check(Environment.PRODUCTION.value)

    # ------------------------------------------------------------------------------------------------ public
    def activate(self, caller: str, endpoint: str, hold: bool = False) -> GatewayResponse:
        """Wake ``endpoint`` and put the other swappable one to sleep (``POST /v1/serving/activate``). Allowed for
        callers whose allowlist entry may use the ``judge`` role (the orchestrator, matching, eval). ``hold``: a
        screening run keeps the card until :meth:`release` (no wake on demand meanwhile, D-116)."""
        from gateway.swap import SwapError

        if self.swap is None:
            return GatewayResponse(200, {"swap": "off", "active": None})
        c = self.policy.callers.get(caller)
        if c is None or not _match("judge", c.roles):
            msg = f"caller {caller!r} may not swap models"
            return GatewayResponse(403, {"error": {"type": "tb_refusal", "code": "caller_unknown", "message": msg}})
        try:
            st = self.swap.activate(endpoint, hold=hold)
        except SwapError as e:
            self.audit.append(
                "llm.gateway.swap_failed", detail={"caller": caller, "endpoint": endpoint, "error": str(e)}
            )
            return GatewayResponse(502, {"error": {"type": "swap_failed", "message": str(e)}})
        self.audit.append("llm.gateway.swap", detail={"caller": caller, **st})
        return GatewayResponse(200, st)

    def release(self, caller: str) -> GatewayResponse:
        """``POST /v1/serving/release``: the screening run lets go of the card; nothing is swapped back now."""
        if self.swap is None:
            return GatewayResponse(200, {"swap": "off", "active": None})
        c = self.policy.callers.get(caller)
        if c is None or not _match("judge", c.roles):
            msg = f"caller {caller!r} may not swap models"
            return GatewayResponse(403, {"error": {"type": "tb_refusal", "code": "caller_unknown", "message": msg}})
        st = self.swap.release()
        self.audit.append("llm.gateway.swap_release", detail={"caller": caller, **st})
        return GatewayResponse(200, st)

    def models(self) -> list[str]:
        """Aliases only (§8.2): no builds, hashes or endpoint addresses."""
        return sorted(self.registry.aliases)

    def chat(self, headers: Mapping[str, str], body: dict[str, Any]) -> GatewayResponse:
        call = _Call(call_id=new_ulid())
        h = {k.lower(): v for k, v in headers.items()}
        try:
            return self._chat(call, h, body)
        except Refusal as r:
            self._record("llm.gateway.refuse", call, reason=r.reason, message=str(r))
            return GatewayResponse(
                r.status,
                {"error": {"type": "tb_refusal", "code": r.reason, "message": str(r), "call_id": call.call_id}},
                {"X-TB-Call-Id": call.call_id, "X-TB-Refusal": r.reason},
            )

    # ------------------------------------------------------------------------------------------------ pipeline
    def _chat(self, call: _Call, h: dict[str, str], body: dict[str, Any]) -> GatewayResponse:
        call.caller = h.get("x-tb-caller", "")
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

        # 1-2 identity and headers
        if not call.caller or call.caller not in self.policy.callers:
            raise Refusal("caller_unknown", f"caller {call.caller!r} is not on the gateway allowlist")
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

        # 4 tripwire
        if label.data_class.rank <= 2:
            verdict = self.guard.tripwire(_content_text(messages))
            call.guard = "hit:" + ",".join(verdict.kinds) if verdict.hit else "clear"
            if verdict.hit:
                raise Refusal("phi_tripwire", f"PHI tripwire hit on a {label.tag} call ({', '.join(verdict.kinds)})")

        # 5-8 resolve, cache, dispatch, echo
        registry_refusals: list[RegistryError] = []
        upstream_errors: list[str] = []
        for cand in candidates:
            try:
                res = self.registry.resolve(cand.alias, cand.endpoint.name, role=call.role, env=cfg.environment)
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
            out = self._try(call, cand, res, label, body, free_form, upstream_errors)
            if out is not None:
                return out
            call.fallbacks += 1
        if upstream_errors and all(e.endswith(": busy") for e in upstream_errors):
            raise Refusal("model_busy", BUSY_MESSAGE, status=503)
        if upstream_errors:
            raise Refusal("upstream_failed", "; ".join(upstream_errors)[:500], status=502)
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
        call.endpoint, call.zone = ep.name, ep.zone
        sampling = {} if free_form else dict(self.policy.sampling)
        cacheable = (
            bool(self.policy.roles.get(call.role, {}).get("cacheable")) and label.data_class.rank <= 1 and not free_form
        )
        key = (call.rendered_sha, res.build.model_sha, canonical(sampling))
        hit: dict[str, Any] | None = None
        if cacheable:
            with self._cache_lock:
                if key in self.cache:
                    self.cache.move_to_end(key)
                    hit = json.loads(json.dumps(self.cache[key]))
        if hit is not None:
            call.cache = "hit"
            return self._allow(call, hit, label, body)

        upstream = {k: v for k, v in body.items() if k not in ("model", "stream")}
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
        if ep.api_key_env and self.env.get(ep.api_key_env):
            headers["Authorization"] = f"Bearer {self.env[ep.api_key_env]}"
        url = ep.url(dict(self.env))
        if not url:
            errors.append(f"{ep.name}: no URL configured")
            return None
        interactive = bool(self.policy.roles.get(call.role, {}).get("interactive"))
        if self.swap is not None and ep.name in self.swap.urls:
            if not self.swap.awake(ep.name):
                was = self.swap.active
                if not self.swap.ensure(ep.name):
                    # held by a screening run: not sent, and no fallback either (the judge's route falls back to
                    # the verifier build, which must never answer in the judge's place during the verifier pass)
                    if interactive:
                        raise Refusal("model_busy", BUSY_MESSAGE, status=503)
                    raise Refusal("model_asleep", f"{ep.name} is asleep (one-GPU swap); activate it first", status=503)
                self.audit.append(
                    "llm.gateway.swap",
                    detail={"caller": "on-demand", "from": was, "role": call.role, **self.swap.status()},
                )
            elif not interactive:
                self.swap.touch()
        t0 = time.perf_counter()
        try:
            if interactive:
                resp = self.http.post(
                    f"{url.rstrip('/')}/chat/completions",
                    json=upstream,
                    headers=headers,
                    timeout=self.interactive_timeout_s,
                )
            else:
                resp = self.http.post(f"{url.rstrip('/')}/chat/completions", json=upstream, headers=headers)
        except httpx.TimeoutException as e:
            errors.append(f"{ep.name}: busy" if interactive else f"{ep.name}: {type(e).__name__}")
            return None
        except httpx.HTTPError as e:
            errors.append(f"{ep.name}: {type(e).__name__}")
            return None
        call.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        if resp.status_code >= 400:
            # vLLM answers 404 to a model name it does not serve: name the one sent (the pin's served name)
            hint = f" (model {res.served_name!r} not served there?)" if resp.status_code == 404 else ""
            errors.append(f"{ep.name}: HTTP {resp.status_code}{hint}")
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
        call.tokens_in = int(usage.get("prompt_tokens") or 0)
        call.tokens_out = int(usage.get("completion_tokens") or 0)
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
        if cacheable:
            with self._cache_lock:
                self.cache[key] = json.loads(json.dumps(payload))
                while len(self.cache) > self.cache_size:
                    self.cache.popitem(last=False)
        return self._allow(call, payload, label, body)

    def _allow(self, call: _Call, payload: dict[str, Any], label: ClassLabel, body: dict[str, Any]) -> GatewayResponse:
        if call.cache == "hit":
            content = str(payload["choices"][0]["message"].get("content") or "")
            call.output_sha = sha256_text(content)
            call.schema_valid = _schema_ok(content, body.get("response_format"))
            call.latency_ms = 0.0
            call.tokens_in = call.tokens_out = 0
            call.cost = 0.0
        self._record("llm.gateway.call", call)  # LLM-5: the ledger first, then the response
        payload["tb"] = {
            "call_id": call.call_id,
            "alias": call.alias,
            "build_id": call.build_id,
            "build_sha": call.build_sha,
            "route_id": call.route_id,
            "policy_version": self.policy.version,
            "registry_version": self.registry.version,
            "cache": call.cache,
        }
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
            {"X-TB-Call-Id": call.call_id, "X-TB-Model-Alias": call.alias, "X-TB-Build-Sha": call.build_sha},
        )

    def _record(self, event: str, call: _Call, **extra: Any) -> None:
        detail = {
            "call_id": call.call_id,
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
            "cost": call.cost,
            "cache": call.cache,
            "guard": call.guard,
            "schema_valid": call.schema_valid,
            "fallbacks": call.fallbacks,
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
