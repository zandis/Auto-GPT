"""tb-gateway v0 request pipeline (spec v4 §8.2; S1-06, S1-07).

Processing order for ``POST /v1/chat/completions`` (each step passes or refuses; every refusal is audited):

1. caller identity: ``X-TB-Caller`` must be on the allowlist, with the role and purpose it asks for (LLM-48);
2. header validation: class, purpose, role, study, context of use and prompt are required (LLM-2, ENG-04); D3/D4
   also need a study and step that the step confirmer accepts as live; a schema-constrained ``response_format`` is
   required except for free-form roles (LLM-22);
3. route lookup: ``(role, class, topology, environment, profile)`` → ordered candidates, each checked with
   ``may_reach`` (§7.2) — no route or no permitted endpoint is refused (``no_route``, ``class_route_mismatch``);
4. PHI tripwire on D0–D2 calls (LLM-15): a hit blocks the call, it is never relabelled;
5. registry resolution of each candidate alias to a pinned build (S1-07; unpinned builds are refused);
6. response cache keyed by (prompt sha, model sha) for cacheable D0/D1 roles (§8.12);
7. dispatch with forced sampling (MOD-4) and structured-output pass-through; fallback only down the route list;
8. served-model echo check (the upstream must report the build's served name);
9. audit record appended before the response is returned (LLM-5), then the redacted trace (§8.14).

The call record holds hashes, labels, tokens, latency and cost — never prompt or response text.
"""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from guard.guard import Guard
from registry.registry import Registry, RegistryError, Resolved, check_served
from tb_common.audit import AuditLog, canonical
from tb_common.crypto import sha256_text
from tb_common.policy.classes import Environment, Topology
from tb_common.ulid import new_ulid
from tb_contracts.dataclass import ClassLabel
from tracestore.store import TraceStore

from gateway.policy import Candidate, Refusal, RoutingPolicy, parse_label

StepConfirm = Callable[[str, str, str], bool]  # (caller, study, step) -> live and delegated
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
            environment=Environment(e.get("TB_ENV", "DEV")),
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
    prompt: str = ""
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

        jsonschema.validate(json.loads(content), schema)
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
        self.cache: OrderedDict[tuple[str, str, str], dict[str, Any]] = OrderedDict()
        self.cache_size = cache_size

    # ------------------------------------------------------------------------------------------------ public
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
        self.policy.check_caller(call.caller, call.role, call.purpose)
        if label.data_class.rank >= 3:
            confirmed = self.step_confirm is not None and bool(call.step)
            if not confirmed or not self.step_confirm(call.caller, call.study, call.step):  # type: ignore[misc]
                raise Refusal("step_unconfirmed", "D3/D4 calls need a live, delegated study step (LLM-2)")
        if not isinstance(messages, list) or not messages:
            raise Refusal("request_invalid", "messages must be a non-empty list")
        if not free_form:
            rf = response_format if isinstance(response_format, dict) else {}
            if rf.get("type") != "json_schema" or not isinstance(rf.get("json_schema"), dict):
                raise Refusal("schema_required", "a json_schema response_format is required for this role (LLM-22)")

        # 3 route
        flags = frozenset(x.strip() for x in h.get("x-tb-flags", "").split(",") if x.strip())
        cfg = self.config
        route, candidates = self.policy.candidates(
            call.role, label, cfg.topology, cfg.environment, cfg.profile, cloud_opt_in=cfg.cloud_opt_in, flags=flags
        )
        call.route_id = route.id
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
            out = self._try(call, cand, res, label, body, free_form, upstream_errors)
            if out is not None:
                return out
            call.fallbacks += 1
        if upstream_errors:
            raise Refusal("upstream_failed", "; ".join(upstream_errors)[:500], status=502)
        first = registry_refusals[0] if registry_refusals else None
        raise Refusal(first.reason if first else "no_eligible_build", str(first) if first else "no candidate")

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
        if cacheable and key in self.cache:
            self.cache.move_to_end(key)
            payload = json.loads(json.dumps(self.cache[key]))
            call.cache = "hit"
            return self._allow(call, payload, label, body)

        upstream = {k: v for k, v in body.items() if k not in ("model", "stream")}
        upstream.update(sampling)
        upstream["model"] = res.served_name
        headers = {"X-TB-Call-Id": call.call_id}
        if call.prompt:
            pid, _, ver = call.prompt.partition("@")
            headers["X-TB-Prompt-Id"] = pid
            headers["X-TB-Prompt-Version"] = ver
        if ep.api_key_env and self.env.get(ep.api_key_env):
            headers["Authorization"] = f"Bearer {self.env[ep.api_key_env]}"
        url = ep.url(dict(self.env))
        if not url:
            errors.append(f"{ep.name}: no URL configured")
            return None
        t0 = time.perf_counter()
        try:
            resp = self.http.post(f"{url.rstrip('/')}/chat/completions", json=upstream, headers=headers)
        except httpx.HTTPError as e:
            errors.append(f"{ep.name}: {type(e).__name__}")
            return None
        call.latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        if resp.status_code >= 400:
            errors.append(f"{ep.name}: HTTP {resp.status_code}")
            return None
        try:
            payload = resp.json()
            content = str(payload["choices"][0]["message"].get("content") or "")
        except (ValueError, KeyError, IndexError, TypeError):
            errors.append(f"{ep.name}: malformed response")
            return None
        try:
            check_served(res, payload.get("model"))
        except RegistryError as e:
            raise Refusal(e.reason, str(e), status=502) from e
        usage = payload.get("usage") or {}
        call.tokens_in = int(usage.get("prompt_tokens") or 0)
        call.tokens_out = int(usage.get("completion_tokens") or 0)
        c = ep.cost
        call.cost = round(
            call.tokens_in / 1000 * c.get("usd_per_1k_in", 0.0)
            + call.tokens_out / 1000 * c.get("usd_per_1k_out", 0.0)
            + call.latency_ms / 1000 * c.get("gpu_second_usd", 0.0),
            8,
        )
        call.output_sha = sha256_text(content)
        call.schema_valid = _schema_ok(content, body.get("response_format"))
        if cacheable:
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
            "context_of_use": call.context_of_use,
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
