"""The only LLM entry point in TrialBox (SPEC §4.7, §7): ``chat_json(prompt_id, variables, schema)``.

* Prompts are registry objects (D-300, :mod:`tb_llm.prompt_registry`): files ``libs/tb_llm/prompts/<id>_v<n>.md``
  with YAML front matter (``PromptMeta``) and ``## system`` / ``## user`` Jinja2 sections, each listed in
  ``registry.yaml`` with its sha256; a file whose bytes differ from the registry is refused. The newest registered
  version is used unless pinned (``"judge_v3"``).
* Output is constrained with ``response_format: json_schema`` (vLLM guided decoding), validated with jsonschema,
  retried once with the violations; a second violation raises :class:`LlmSchemaError`.
* Routing: ``model_class: cloud`` prompts go to ``CLOUD_LLM_BASE_URL`` only when (a) the calling service is
  ``criteria-compiler``, (b) ``settings.models.cloud_enabled``, (c) a :class:`PhiClearance` for exactly the call's
  variables (``phi_guard.variables_text``, everything that is not fixed template text) is supplied. Everything else
  goes to the local endpoint (``LLM_BASE_URL``).
* Every call appends ``llm.call`` to the audit chain with prompt id/version, model, input/output sha.
* **Gateway shim (spec v4 S1-06, one milestone).** With ``TB_GATEWAY_URL`` set (or a ``gateway`` client passed), the
  request goes through ``libs/tb_llm`` to ``tb-gateway`` with the v4 labels instead of to an endpoint directly; the
  gateway chooses the route and build. ``data_class=`` on :meth:`LlmClient.chat_json` sets the class (else
  ``TB_DATA_CLASS``, else D3 for ``phi`` prompts and D1 otherwise). A call made for a job sends the job id as its
  step (``X-TB-Step``, unless ``TB_STEP_ID`` names one), so a gateway with a step confirmer can check it (LLM-2;
  T-604). In PRODUCTION :meth:`LlmClient.from_config` refuses to build a client without ``TB_GATEWAY_URL``: no
  service there calls ``LLM_BASE_URL`` or ``CLOUD_LLM_BASE_URL`` itself (T-604, D-388; review LLM-038).
* **Context (T-603, review LLM-015, LLM-018).** :meth:`LlmClient.context_tokens` is the model's context: the
  gateway's ``GET /v1/models`` for the alias, or ``TB_LLM_CONTEXT`` on a direct call (DEV).
  :meth:`LlmClient.text_budget` is what a caller may put in the variable part of a prompt (excerpts, a chart).
  ``max_tokens`` is cut to what fits beside the prompt; a prompt that leaves less than
  :data:`tb_llm.budget.MIN_ANSWER_TOKENS` is refused here (:class:`LlmPromptTooLong`) and never sent; the retry of a
  cut-off answer asks for at most what fits.
* **Timeouts (T-608, D-445; review LLM-023).** A call waits 240 s (``TB_LLM_TIMEOUT_S``), longer than the gateway's
  budget for one call (:mod:`tb_llm.timeouts`); a dropped connection is sent once more, a read timeout is not.
"""

from __future__ import annotations

import json
import os
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache, partial
from pathlib import Path
from typing import Any

import httpx
import yaml
from jinja2 import Environment, StrictUndefined
from tb_contracts import PromptMeta, inline_schema, load_schema, null_absent, schema_errors
from tb_contracts.schema import schema_error_codes
from tb_llm.budget import MIN_ANSWER_TOKENS, answer_room, estimate_messages, retry_max_tokens, text_budget
from tb_llm.outage import MODEL_FAULTS
from tb_llm.timeouts import caller_timeout, once_more

from tb_common.audit import AuditLog
from tb_common.audit_writer import open_audit
from tb_common.crypto import sha256_text
from tb_common.output_gate import OutputRefused, prepare_output
from tb_common.phi_guard import PhiClearance, variables_text

_FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
_SECTION = re.compile(r"^##\s+(system|user)\s*$", re.M)
_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=False)  # noqa: S701


def tojson_block(value: Any) -> str:
    """The data of a prompt's fenced JSON block (filter ``tojson_pretty``). Every backtick is written as the JSON
    escape ``\\u0060``: the same JSON value, but a note or protocol that holds a fence (three backticks) cannot close
    the block and put its own text outside it, where it would read as part of the prompt (T-208, D-346; LLM-034)."""
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True).replace("`", "\\u0060")


_env.filters["tojson_pretty"] = tojson_block
CLOUD_SERVICE = "criteria-compiler"


class LlmError(RuntimeError):
    pass


class LlmSchemaError(LlmError):
    pass


class LlmPromptUnqualified(LlmError):
    """The gateway refused the prompt version as unqualified (``prompt_unqualified``): a PRODUCTION box (D-359)."""


class LlmPromptTooLong(LlmError):
    """The prompt does not fit the model's context with room for an answer (T-603): not sent. The gateway's refusal
    ``prompt_too_long`` (before dispatch, or the server's own HTTP 400) is raised as this too."""


class LlmUpstreamFailed(LlmError):
    """G4 of the P1b review: the gateway gave up on the answer (``upstream_failed``: its read timeout, an answer past
    the cap, a malformed one) or the endpoint's read timed out. A shorter request may get one; the same one will not.
    Never a model that is down (:class:`LlmModelFault`)."""


class LlmModelFault(LlmError):
    """The model did not answer, and not because of this request (T-689, D-456): one of :data:`MODEL_FAULTS`, a
    gateway or model endpoint that cannot be reached (never a timeout), or an HTTP 5xx without a refusal code. The
    same call may be sent again later.
    ``reason``: the refusal code, ``unreachable`` or ``http_5xx``; ``retry_after``: the gateway's ``Retry-After``."""

    def __init__(self, message: str, reason: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.retry_after = retry_after


@dataclass(frozen=True)
class Prompt:
    meta: PromptMeta
    system: str
    user: str
    path: Path
    sha256: str = ""  # the registry's sha of the file (D-300): sent as X-TB-Prompt-Sha, recorded in the audit


@dataclass
class LlmResult:
    data: dict[str, Any]
    prompt_id: str
    prompt_version: int
    model: str
    target: str  # local | cloud
    input_sha: str
    output_sha: str
    tokens_in: int
    tokens_out: int
    attempts: int
    prompt_sha: str = ""
    build_sha: str = ""  # through the gateway: the build that answered (weights digest); "" on a direct call (D-276)
    call_id: str = ""  # D-989: the gateway's call id (``llm.gateway.call``); ``direct-<output sha>`` on a direct call


#: H-16 (lane H's offline review, H-18): what the call in this thread is asked for, set by a caller around a model call
#: and written beside it in ``llm.call`` (``asking``): the cascade's stage (S3 or S4) and role, the patient's
#: pseudonym, the criterion's canonical hash, the window and the digest of the question shown. Ids and hashes only,
#: never text; None outside such a call.
CALL_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("tb_llm_call_context", default=None)


def no_sentinel_date(data: dict[str, Any]) -> dict[str, Any]:
    """G8 of the P1b review (D-958): a quote date that is no real date ("0000-01-01", a model's way of saying it has
    none) is no date: null, so an "unknown" with it is an answer, not a reply outside the schema. Applied to every
    model answer that has a ``quote_date`` (the note judge on SCREEN's path here, the cascade's gateway judge too)."""
    if "quote_date" not in data:
        return data
    qd = data.get("quote_date")
    if qd is None:
        return data
    try:
        ok = date.fromisoformat(str(qd)[:10]).year >= 1900
    except ValueError:
        ok = False
    return data if ok else {**data, "quote_date": None}


def load_prompt(prompt_id: str, environment: str | None = None) -> Prompt:
    """``judge`` -> the served version (the newest; in PRODUCTION the newest qualified one, D-359); ``judge_v3`` ->
    exactly version 3. Resolved through the prompt registry (D-300): an unregistered id or version, or a file whose
    sha256 differs from the registry, is refused. ``environment`` defaults to this process's ``TB_ENV``."""
    from tb_common.config import environment_name

    return _load_prompt(prompt_id, (environment or environment_name(os.environ)).strip().upper())


@lru_cache(maxsize=128)
def _load_prompt(prompt_id: str, environment: str) -> Prompt:
    from tb_llm.prompt_registry import PromptRegistryError, default_registry

    pinned = re.fullmatch(r"(.+)_v(\d+)", prompt_id)
    base, want = (pinned.group(1), int(pinned.group(2))) if pinned else (prompt_id, None)
    try:
        resolved = default_registry().get(base, want, environment=environment)
    except PromptRegistryError as exc:
        # an unqualified version is the request's fault, not the model's: callers that count model failures (the
        # SCREEN breaker, orchestrator.jobs.NOT_DOWN) must be able to tell, as for the gateway's own refusal
        kind = LlmPromptUnqualified if exc.reason == "prompt_unqualified" else LlmError
        raise kind(f"prompt {prompt_id!r} refused ({exc.reason}): {exc}") from exc
    path = resolved.path
    m = _FM.match(resolved.text)
    if not m:
        raise LlmError(f"{path}: missing YAML front matter")
    meta = PromptMeta.model_validate(yaml.safe_load(m.group(1)))
    parts = _SECTION.split(m.group(2))
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if "system" not in sections or "user" not in sections:
        raise LlmError(f"{path}: needs '## system' and '## user' sections")
    return Prompt(meta, sections["system"], sections["user"], path, resolved.sha256)


def render(prompt: Prompt, variables: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _env.from_string(prompt.system).render(**variables)},
        {"role": "user", "content": _env.from_string(prompt.user).render(**variables)},
    ]


def _extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


class LlmClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        cloud_base_url: str = "",
        cloud_api_key: str = "",
        cloud_model: str = "",
        cloud_enabled: bool = False,
        service_name: str = "",
        audit: AuditLog | None = None,
        timeout: float | httpx.Timeout | None = None,
        gateway: Any = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.cloud_base_url = cloud_base_url.rstrip("/")
        self.cloud_api_key = cloud_api_key
        self.cloud_model = cloud_model or model
        self.cloud_enabled = cloud_enabled
        self.service_name = service_name
        self.audit = audit
        self.http = httpx.Client(timeout=caller_timeout() if timeout is None else timeout)
        self.gateway = gateway  # tb_llm.GatewayClient (shim path) or None
        self._context: tuple[float, int | None] | None = None
        self._prompt_env: str | None = None  # set to PRODUCTION once the gateway refuses an unqualified version

    CONTEXT_TTL_S = 300.0

    def context_tokens(self) -> int | None:
        """The model's context in tokens, or None when it cannot be told (T-603). Through the gateway: its
        ``GET /v1/models`` for this client's alias (:meth:`tb_llm.GatewayClient.context`). Direct (DEV, no
        gateway): ``TB_LLM_CONTEXT`` when set. A known context is asked again after :attr:`CONTEXT_TTL_S`; an
        unknown one at the next call."""
        now = time.monotonic()
        if self._context is not None and now - self._context[0] < self.CONTEXT_TTL_S:
            return self._context[1]
        ctx: int | None = None
        if self.gateway is not None:
            fn = getattr(self.gateway, "context", None)
            got = fn() if callable(fn) else None
            ctx = got if isinstance(got, int) and got > 0 else None
        else:
            raw = os.environ.get("TB_LLM_CONTEXT", "").strip()  # a direct call (DEV only): the context, if set
            ctx = int(raw) if raw.isdigit() and int(raw) > 0 else None
        # deep review 2026-11-13 (screening, SCR-18): only a known context is kept. One failed ``GET /v1/models``
        # kept "unknown" for the whole TTL, so every caller in it sized its excerpts from the small default and a
        # run's excerpts, and so its tiers, depended on whether that one request failed
        self._context = (now, ctx) if ctx is not None else None
        return ctx

    def text_budget(self, prompt_id: str, fixed: dict[str, Any]) -> int | None:
        """Tokens a caller may put in the variable part of ``prompt_id`` (T-603): the context, less the safety share,
        the prompt rendered with ``fixed`` (the variable part empty) and the prompt's ``max_tokens``. None when the
        context is not known (the caller keeps its own default; the gateway still refuses what is over)."""
        ctx = self.context_tokens()
        if not ctx:
            return None
        prompt = load_prompt(prompt_id, self._prompt_env or getattr(self.gateway, "prompt_environment", None))
        return text_budget(ctx, estimate_messages(render(prompt, fixed)), prompt.meta.max_tokens)

    @classmethod
    def from_config(cls, audit: AuditLog | None = None) -> LlmClient:
        from tb_common.config import environment_name, get_config

        cfg = get_config()
        models = cfg.settings.models
        gateway = None
        if os.environ.get("TB_GATEWAY_URL", "").strip():
            from tb_llm import GatewayClient

            gateway = GatewayClient(
                os.environ["TB_GATEWAY_URL"], cfg.env.service_name, model=os.environ.get("TB_GATEWAY_MODEL") or None
            )
        elif environment_name(os.environ) == "PRODUCTION":
            # T-604 (review LLM-038): in a hand-made or platform deployment only the environment decides where a
            # prompt goes; on a PRODUCTION box it goes through tb-gateway (routing, audit, PHI rules) or nowhere
            raise LlmError(
                "no TB_GATEWAY_URL in PRODUCTION: a model client is built only through tb-gateway, never straight "
                "to LLM_BASE_URL or CLOUD_LLM_BASE_URL"
            )
        return cls(
            cfg.env.llm_base_url,
            cfg.env.llm_model,
            cloud_base_url=cfg.env.cloud_llm_base_url,
            cloud_api_key=cfg.env.cloud_llm_api_key,
            cloud_model=(models.cloud_model if models else "") or "",
            cloud_enabled=bool(models and models.cloud_enabled),
            service_name=cfg.env.service_name,
            audit=audit or open_audit(cfg.env.audit_path, cfg.env.tz),
            gateway=gateway,
        )

    def _target(self, meta: PromptMeta, variables: dict[str, Any], clearance: PhiClearance | None) -> str:
        """Cloud only for a cloud-class, non-PHI prompt, from the one service allowed out, with a clearance that
        :func:`tb_common.phi_guard.scan` issued for exactly these variables (``variables_text``)."""
        if meta.model_class != "cloud" or meta.phi:
            return "local"
        if not (self.cloud_enabled and self.cloud_base_url and self.service_name == CLOUD_SERVICE):
            return "local"
        if clearance is None or clearance.text_sha != sha256_text(variables_text(variables)):
            return "local"
        return "cloud"

    def chat_json(
        self,
        prompt_id: str,
        variables: dict[str, Any],
        schema: str | None = None,
        *,
        job_id: str | None = None,
        clearance: PhiClearance | None = None,
        phi_guard_hit: bool | None = None,
        data_class: str | None = None,
    ) -> LlmResult:
        kw: dict[str, Any] = {
            "job_id": job_id,
            "clearance": clearance,
            "phi_guard_hit": phi_guard_hit,
            "data_class": data_class,
        }
        # a gateway client may name the environment of the box it stands for (tools.scenarios): its served prompt
        env = self._prompt_env or getattr(self.gateway, "prompt_environment", None)
        prompt = load_prompt(prompt_id, env)
        try:
            return self._chat_json(prompt, variables, schema, **kw)
        except LlmPromptUnqualified:
            # D-359: the gateway is a PRODUCTION box and this version waits for its qualification record. Its served
            # version is the newest qualified one; the gateway still checks that text and its record. Never an
            # unqualified one: none qualified raises (load_prompt in PRODUCTION), and so does a client with no audit
            # log, because every fallback is audited.
            if env == "PRODUCTION" or self.audit is None:
                raise
            used = load_prompt(prompt_id, "PRODUCTION")
            if (used.meta.id, used.meta.version) == (prompt.meta.id, prompt.meta.version):
                raise
            self.audit.append(
                "llm.prompt_fallback",
                job_id=job_id,
                prompt_version=f"{used.meta.id}_v{used.meta.version}",
                detail={
                    "refused": f"{prompt.meta.id}@{prompt.meta.version}",
                    "refused_sha": prompt.sha256,
                    "used": f"{used.meta.id}@{used.meta.version}",
                    "used_sha": used.sha256,
                    "reason": "prompt_unqualified",
                },
            )
            self._prompt_env = "PRODUCTION"
            return self._chat_json(used, variables, schema, **kw)

    def _chat_json(
        self,
        prompt: Prompt,
        variables: dict[str, Any],
        schema: str | None,
        *,
        job_id: str | None,
        clearance: PhiClearance | None,
        phi_guard_hit: bool | None,
        data_class: str | None,
    ) -> LlmResult:
        prompt_id = prompt.meta.id
        schema_name = schema or prompt.meta.output_schema
        json_schema = inline_schema(schema_name)
        if prompt_id in ("assist", "judge", "chart_facts", "crf_prefill", "ie_locate", "draft_doc"):
            try:
                variables = prepare_output(prompt_id, "model", variables)
            except OutputRefused as exc:
                raise LlmError(exc.message()) from exc
        messages = render(prompt, variables)
        input_text = "\n".join(m["content"] for m in messages)
        input_sha = sha256_text(input_text)
        target = "gateway" if self.gateway is not None else self._target(prompt.meta, variables, clearance)
        base, model = (self.cloud_base_url, self.cloud_model) if target == "cloud" else (self.base_url, self.model)
        served = model
        headers = {
            "X-TB-Prompt-Id": prompt.meta.id,
            "X-TB-Prompt-Version": str(prompt.meta.version),
            "X-TB-Prompt-Sha": prompt.sha256,
        }
        if target == "cloud" and self.cloud_api_key:
            headers["Authorization"] = f"Bearer {self.cloud_api_key}"
        tokens_in = tokens_out = 0
        build_sha = call_id = ""
        errors: list[str] = []
        codes: list[str] = []
        convo = list(messages)
        max_tokens = prompt.meta.max_tokens
        context = self.context_tokens()
        if context:
            # T-603 (review LLM-015): the answer budget is what fits beside the prompt; a prompt that leaves no room
            # for an answer is not sent (the caller sizes its excerpts or chart from text_budget)
            room = answer_room(context, estimate_messages(messages))
            if room < MIN_ANSWER_TOKENS:
                raise LlmPromptTooLong(
                    f"{prompt_id}: the prompt (about {estimate_messages(messages)} tokens) leaves no room for an "
                    f"answer in the model's context of {context} tokens"
                )
            max_tokens = min(max_tokens, room)
        for attempt in (1, 2):
            body = {
                "model": model,
                "messages": convo,
                "temperature": prompt.meta.temperature,
                "max_tokens": max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": prompt.meta.id, "schema": json_schema, "strict": True},
                },
            }
            t0 = time.perf_counter()
            if self.gateway is not None:
                payload = self._via_gateway(body, prompt, job_id, data_class)
                model = served = str(payload.get("model") or model)
                build_sha = str((payload.get("tb") or {}).get("build_sha") or "")
                call_id = str((payload.get("tb") or {}).get("call_id") or "")
            else:
                try:
                    body = prepare_output("chat", "model", body, model_names=(model,))
                except OutputRefused as exc:
                    raise LlmError(exc.message()) from exc
                try:  # a dropped connection once more, a timeout never (T-608, D-445)
                    resp = once_more(partial(self.http.post, f"{base}/chat/completions", json=body, headers=headers))
                except httpx.TimeoutException as exc:  # never a model fault: the server may still be working on it
                    raise LlmUpstreamFailed(f"LLM endpoint timed out ({target}): {exc}") from exc
                except httpx.HTTPError as exc:
                    raise LlmModelFault(f"LLM endpoint unreachable ({target}): {exc}", "unreachable") from exc
                if resp.status_code >= 500:
                    raise LlmModelFault(f"LLM endpoint error {resp.status_code}: {resp.text[:500]}", "http_5xx")
                if resp.status_code >= 400:
                    raise LlmError(f"LLM endpoint error {resp.status_code}: {resp.text[:500]}")
                payload = resp.json()
                served = str(payload.get("model") or model)  # the name the server answered under (D-276)
            usage = payload.get("usage") or {}
            tokens_in += int(usage.get("prompt_tokens", 0))
            tokens_out += int(usage.get("completion_tokens", 0))
            content = payload["choices"][0]["message"].get("content") or ""
            truncated = payload["choices"][0].get("finish_reason") == "length"
            try:
                data = null_absent(load_schema(schema_name), _extract_json(content))  # null == absent
                # G8 (D-958), on every path (P2b: SCREEN's note judge failed three protocols on it): a quote date
                # that is no real date is no date, before the schema reads it
                data = no_sentinel_date(data) if isinstance(data, dict) else data
                errors = schema_errors(schema_name, data)
                codes = schema_error_codes(schema_name, data)  # what leaves the call: no model output (T-605)
            except (json.JSONDecodeError, ValueError) as exc:
                data, errors, codes = None, [f"not JSON: {exc}"], ["<root>: not JSON"]
            if not errors and isinstance(data, dict):
                output_sha = sha256_text(json.dumps(data, sort_keys=True, ensure_ascii=False))
                # D-989: every answer names the call that gave it; a direct call (DEV, no gateway) has no gateway
                # record, so its id is derived from its answer: a re-run's records stay the same
                call_id = call_id or f"direct-{output_sha[:16]}"
                if self.audit is not None:
                    self.audit.append(
                        "llm.call",
                        job_id=job_id,
                        model=served,
                        prompt_version=f"{prompt.meta.id}_v{prompt.meta.version}",
                        input_sha=input_sha,
                        output_sha=output_sha,
                        detail={
                            "target": target,
                            "attempts": attempt,
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "phi_guard_hit": phi_guard_hit,
                            "prompt_sha": prompt.sha256,
                            "build_sha": build_sha,  # D-989: the build that answered ("" on a direct call)
                            "call_id": call_id,  # D-989: what a record's ``prov`` names
                            "ms": round((time.perf_counter() - t0) * 1000),
                            "schema": schema,  # H-16: the answer schema the call was made with (None: the prompt's)
                            **({"asking": dict(asking)} if (asking := CALL_CONTEXT.get()) else {}),
                        },
                    )
                return LlmResult(
                    data,
                    prompt.meta.id,
                    prompt.meta.version,
                    served,
                    target,
                    input_sha,
                    output_sha,
                    tokens_in,
                    tokens_out,
                    attempt,
                    prompt.sha256,
                    build_sha,
                    call_id,
                )
            if truncated:
                # a reasoning model (gpt-oss, nemotron) spends max_tokens on reasoning before the JSON: the answer was
                # cut off, not wrong, so ask the same question again with room to finish, never more than fits beside
                # the prompt (T-603, review LLM-018); when nothing larger fits, the retry is not sent
                more = retry_max_tokens(context, estimate_messages(messages), max_tokens)
                if more is None:
                    codes = [*codes, "the answer was cut off and no larger answer fits the model's context"]
                    break
                max_tokens = more
                convo = list(messages)
                continue
            convo = [
                *messages,
                {"role": "assistant", "content": content[:4000]},
                {
                    "role": "user",
                    "content": "Your previous output violated the JSON schema: "
                    + "; ".join(errors[:10])
                    + ". Return only corrected JSON.",
                },
            ]
        if self.audit is not None:
            self.audit.append(
                "llm.schema_violation",
                job_id=job_id,
                model=served,
                input_sha=input_sha,
                prompt_version=f"{prompt.meta.id}_v{prompt.meta.version}",
                detail={"errors": codes[:5]},
            )
        # path and validator only: the model's words never reach the audit chain, job errors or logs (LLM-041)
        raise LlmSchemaError(f"{prompt_id}: output violated schema twice: {codes[:5]}")

    def _via_gateway(
        self, body: dict[str, Any], prompt: Prompt, job_id: str | None, data_class: str | None
    ) -> dict[str, Any]:
        """Shim path: the gateway picks the build, so ``model`` is dropped; labels go as ``X-TB-*`` headers."""
        from tb_llm import GatewayDown, GatewayError, GatewayRefused
        from tb_llm.client import v1_labels

        meta = prompt.meta
        labels = v1_labels(
            meta.id, meta.version, phi=bool(meta.phi), study_id=job_id, data_class=data_class, prompt_sha=prompt.sha256
        )
        if job_id and not labels.step_id:
            labels = replace(labels, step_id=job_id)  # the step the gateway's confirmer checks (LLM-2; T-604)
        try:
            req = prepare_output("chat", "model", {k: v for k, v in body.items() if k != "model"})
        except OutputRefused as exc:
            raise LlmError(exc.message()) from exc
        try:
            payload: dict[str, Any] = self.gateway.complete(req, labels)
        except GatewayRefused as exc:
            if exc.reason == "prompt_too_long":
                raise LlmPromptTooLong(f"gateway refused {meta.id}: {exc.reason}") from exc
            if exc.reason == "prompt_unqualified":
                raise LlmPromptUnqualified(f"gateway refused {meta.id}@{meta.version}: {exc.reason}") from exc
            if exc.reason in MODEL_FAULTS:  # T-689 (F-04): the caller may wait and send the same call again
                raise LlmModelFault(f"gateway refused {meta.id}: {exc.reason}", exc.reason, exc.retry_after) from exc
            if exc.reason == "upstream_failed":  # G4: the gateway gave up on the answer; a shorter request may not
                raise LlmUpstreamFailed(f"gateway refused {meta.id}: {exc.reason}") from exc
            raise LlmError(f"gateway refused {meta.id}: {exc.reason}") from exc
        except GatewayDown as exc:
            raise LlmModelFault(str(exc), "unreachable") from exc
        except GatewayError as exc:
            raise LlmError(str(exc)) from exc
        return payload


_default: LlmClient | None = None


def default_client() -> LlmClient:
    global _default
    if _default is None:
        _default = LlmClient.from_config()
    return _default


def chat_json(prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
    """SPEC §4.7 wrapper over the process-wide client."""
    return default_client().chat_json(prompt_id, variables, schema, **kw)
