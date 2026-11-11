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
  ``TB_DATA_CLASS``, else D3 for ``phi`` prompts and D1 otherwise). Without it nothing changes.
* **Context (T-603, review LLM-015, LLM-018).** :meth:`LlmClient.context_tokens` is the model's context: the
  gateway's ``GET /v1/models`` for the alias, or the server's own (vLLM ``max_model_len``) on a direct call.
  :meth:`LlmClient.text_budget` is what a caller may put in the variable part of a prompt (excerpts, a chart).
  ``max_tokens`` is cut to what fits beside the prompt; a prompt that leaves less than
  :data:`tb_llm.budget.MIN_ANSWER_TOKENS` is refused here (:class:`LlmPromptTooLong`) and never sent; the retry of a
  cut-off answer asks for at most what fits.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import yaml
from jinja2 import Environment, StrictUndefined
from tb_contracts import PromptMeta, inline_schema, load_schema, null_absent, schema_errors
from tb_llm.budget import MIN_ANSWER_TOKENS, answer_room, estimate_messages, retry_max_tokens, text_budget

from tb_common.audit import AuditLog
from tb_common.crypto import sha256_text
from tb_common.phi_guard import PhiClearance, variables_text

_FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
_SECTION = re.compile(r"^##\s+(system|user)\s*$", re.M)
_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=False)  # noqa: S701
_env.filters["tojson_pretty"] = lambda v: json.dumps(v, ensure_ascii=False, indent=1, sort_keys=True)
CLOUD_SERVICE = "criteria-compiler"


class LlmError(RuntimeError):
    pass


class LlmSchemaError(LlmError):
    pass


class LlmPromptTooLong(LlmError):
    """The prompt does not fit the model's context with room for an answer (T-603): not sent. The gateway's refusal
    ``prompt_too_long`` (before dispatch, or the server's own HTTP 400) is raised as this too."""


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


@lru_cache(maxsize=128)
def load_prompt(prompt_id: str) -> Prompt:
    """``judge`` -> the newest registered version; ``judge_v3`` -> exactly version 3. Resolved through the prompt
    registry (D-300): an unregistered id or version, or a file whose sha256 differs from the registry, is refused."""
    from tb_llm.prompt_registry import PromptRegistryError, default_registry

    pinned = re.fullmatch(r"(.+)_v(\d+)", prompt_id)
    base, want = (pinned.group(1), int(pinned.group(2))) if pinned else (prompt_id, None)
    try:
        resolved = default_registry().get(base, want)
    except PromptRegistryError as exc:
        raise LlmError(f"prompt {prompt_id!r} refused ({exc.reason}): {exc}") from exc
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
        timeout: float = 600.0,
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
        self.http = httpx.Client(timeout=timeout)
        self.gateway = gateway  # tb_llm.GatewayClient (shim path) or None
        self._context: tuple[float, int | None] | None = None

    CONTEXT_TTL_S = 300.0

    def context_tokens(self) -> int | None:
        """The model's context in tokens, or None when it cannot be told (T-603). Through the gateway: its
        ``GET /v1/models`` for this client's alias (:meth:`tb_llm.GatewayClient.context`). Direct: the server's
        ``GET /models`` entry for this model (vLLM ``max_model_len``). Asked again after :attr:`CONTEXT_TTL_S`."""
        now = time.monotonic()
        if self._context is not None and now - self._context[0] < self.CONTEXT_TTL_S:
            return self._context[1]
        ctx: int | None = None
        if self.gateway is not None:
            ctx = self.gateway.context()
        else:
            try:
                resp = self.http.get(f"{self.base_url}/models")
                data = resp.json().get("data", []) if resp.status_code == 200 else []
            except (httpx.HTTPError, ValueError, AttributeError):
                data = []
            for m in data if isinstance(data, list) else []:
                if isinstance(m, dict) and m.get("id") == self.model:
                    raw = m.get("max_model_len") or m.get("context_length")
                    ctx = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else None
        self._context = (now, ctx)
        return ctx

    def text_budget(self, prompt_id: str, fixed: dict[str, Any]) -> int | None:
        """Tokens a caller may put in the variable part of ``prompt_id`` (T-603): the context, less the safety share,
        the prompt rendered with ``fixed`` (the variable part empty) and the prompt's ``max_tokens``. None when the
        context is not known (the caller keeps its own default; the gateway still refuses what is over)."""
        ctx = self.context_tokens()
        if not ctx:
            return None
        prompt = load_prompt(prompt_id)
        return text_budget(ctx, estimate_messages(render(prompt, fixed)), prompt.meta.max_tokens)

    @classmethod
    def from_config(cls, audit: AuditLog | None = None) -> LlmClient:
        from tb_common.config import get_config

        cfg = get_config()
        models = cfg.settings.models
        gateway = None
        if os.environ.get("TB_GATEWAY_URL"):
            from tb_llm import GatewayClient

            gateway = GatewayClient(
                os.environ["TB_GATEWAY_URL"], cfg.env.service_name, model=os.environ.get("TB_GATEWAY_MODEL") or None
            )
        return cls(
            cfg.env.llm_base_url,
            cfg.env.llm_model,
            cloud_base_url=cfg.env.cloud_llm_base_url,
            cloud_api_key=cfg.env.cloud_llm_api_key,
            cloud_model=(models.cloud_model if models else "") or "",
            cloud_enabled=bool(models and models.cloud_enabled),
            service_name=cfg.env.service_name,
            audit=audit or AuditLog(cfg.env.audit_path, cfg.env.tz),
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
        prompt = load_prompt(prompt_id)
        schema_name = schema or prompt.meta.output_schema
        json_schema = inline_schema(schema_name)
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
        build_sha = ""
        errors: list[str] = []
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
            else:
                try:
                    resp = self.http.post(f"{base}/chat/completions", json=body, headers=headers)
                except httpx.HTTPError as exc:
                    raise LlmError(f"LLM endpoint unreachable ({target}): {exc}") from exc
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
                errors = schema_errors(schema_name, data)
            except (json.JSONDecodeError, ValueError) as exc:
                data, errors = None, [f"not JSON: {exc}"]
            if not errors and isinstance(data, dict):
                output_sha = sha256_text(json.dumps(data, sort_keys=True, ensure_ascii=False))
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
                            "ms": round((time.perf_counter() - t0) * 1000),
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
                )
            if truncated:
                # a reasoning model (gpt-oss, nemotron) spends max_tokens on reasoning before the JSON: the answer was
                # cut off, not wrong, so ask the same question again with room to finish, never more than fits beside
                # the prompt (T-603, review LLM-018); when nothing larger fits, the retry is not sent
                more = retry_max_tokens(context, estimate_messages(messages), max_tokens)
                if more is None:
                    errors = [*errors, "the answer was cut off and no larger answer fits the model's context"]
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
                detail={"errors": errors[:5]},
            )
        raise LlmSchemaError(f"{prompt_id}: output violated schema twice: {errors[:5]}")

    def _via_gateway(
        self, body: dict[str, Any], prompt: Prompt, job_id: str | None, data_class: str | None
    ) -> dict[str, Any]:
        """Shim path: the gateway picks the build, so ``model`` is dropped; labels go as ``X-TB-*`` headers."""
        from tb_llm import GatewayError, GatewayRefused
        from tb_llm.client import v1_labels

        meta = prompt.meta
        labels = v1_labels(
            meta.id, meta.version, phi=bool(meta.phi), study_id=job_id, data_class=data_class, prompt_sha=prompt.sha256
        )
        req = {k: v for k, v in body.items() if k != "model"}
        try:
            payload: dict[str, Any] = self.gateway.complete(req, labels)
        except GatewayRefused as exc:
            if exc.reason == "prompt_too_long":
                raise LlmPromptTooLong(f"gateway refused {meta.id}: {exc.reason}") from exc
            raise LlmError(f"gateway refused {meta.id}: {exc.reason}") from exc
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
