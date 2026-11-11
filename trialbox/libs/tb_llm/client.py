"""The only LLM client library (spec v4 §8.2, ENG-04; S1-06): talks to ``tb-gateway`` and nothing else.

Every call carries its labels as ``X-TB-*`` headers — data class, study, purpose, context of use, role, prompt, and
the caller's service id — and, for every role except free-form ones, a ``json_schema`` response format. Labels are
set by the calling step from the data it read (§7.1); this library never infers them.

An answer from an alias the call did not expect raises :class:`GatewayUnexpectedAlias` (T-601, deep review LLM-003):
an alias other than the one the call named, an answer that another alias gave after the expected one failed
(``tb.fallbacks``, ``X-TB-Fallbacks``) unless the client was made with ``allow_fallback=True``, or an answer that does
not say which alias gave it. So one role is never answered by another role's model without the caller knowing.

:meth:`GatewayClient.context` gives an alias's context in tokens from the gateway's ``GET /v1/models`` (T-603), so a
caller sizes its prompt and its answer budget from the model it will get (:mod:`tb_llm.budget`). The one retry of an
answer cut off for length asks for at most what fits beside the prompt in the answering alias's context (LLM-018).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from tb_llm.budget import estimate_messages, retry_max_tokens

FREE_FORM_ROLES = frozenset({"frontdesk_converse"})


class GatewayError(RuntimeError):
    """The gateway could not be reached or answered with an unexpected error."""


class GatewayUnexpectedAlias(GatewayError):
    """The gateway answered, but not from the alias this call expected (T-601): the answer is not used."""

    def __init__(self, message: str, *, expected: str = "", alias: str = "", call_id: str = "") -> None:
        super().__init__(message)
        self.expected = expected
        self.alias = alias
        self.call_id = call_id


class GatewayRefused(GatewayError):
    """The gateway refused the call; ``reason`` is its stable refusal code (``no_route``, ``phi_tripwire`` …)."""

    def __init__(self, reason: str, status: int, message: str, call_id: str = "") -> None:
        super().__init__(f"gateway refused ({status} {reason}): {message}")
        self.reason = reason
        self.status = status
        self.call_id = call_id


@dataclass(frozen=True)
class CallLabels:
    data_class: str
    purpose: str
    study_id: str
    context_of_use: str
    role: str
    prompt: str = ""  # prompt_id@version
    step_id: str = ""
    flags: tuple[str, ...] = ()
    prompt_sha: str = ""  # the registry's sha256 of the prompt text (D-300); the gateway refuses a mismatch

    def headers(self, caller: str) -> dict[str, str]:
        missing = [
            n for n in ("data_class", "purpose", "study_id", "context_of_use", "role") if not getattr(self, n).strip()
        ]
        if not caller:
            missing.append("caller")
        if self.role not in FREE_FORM_ROLES and not self.prompt:
            missing.append("prompt")
        if missing:
            raise ValueError(f"tb_llm: labels required (ENG-04): {', '.join(missing)}")
        h = {
            "X-TB-Caller": caller,
            "X-TB-Data-Class": self.data_class,
            "X-TB-Purpose": self.purpose,
            "X-TB-Study": self.study_id,
            "X-TB-Context-Of-Use": self.context_of_use,
            "X-TB-Role": self.role,
        }
        if self.prompt:
            h["X-TB-Prompt"] = self.prompt
        if self.prompt_sha:
            h["X-TB-Prompt-Sha"] = self.prompt_sha
        if self.step_id:
            h["X-TB-Step"] = self.step_id
        if self.flags:
            h["X-TB-Flags"] = ",".join(self.flags)
        return h


@dataclass
class ChatResult:
    content: str
    payload: dict[str, Any]
    model: str
    call_id: str
    alias: str
    build_sha: str
    cache: str
    tokens_in: int
    tokens_out: int
    data: Any = field(default=None)


def json_schema_format(name: str, schema: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": strict}}


class GatewayClient:
    """``model`` (or ``TB_GATEWAY_MODEL`` via :meth:`from_env`) is a default alias the client asks for when a call
    names none; the gateway still decides whether that alias is on the route and pinned (it never widens a route).

    ``allow_fallback``: accept an answer from the next build of a route that allows it (``fallback: any``) when the
    expected one failed. Off by default; an alias the call named must answer in every case (T-601)."""

    def __init__(
        self,
        base_url: str,
        caller: str,
        *,
        http: httpx.Client | None = None,
        timeout: float = 600.0,
        model: str | None = None,
        allow_fallback: bool = False,
    ) -> None:
        if not base_url:
            raise ValueError("tb_llm: gateway URL required")
        self.base_url = base_url.rstrip("/")
        self.caller = caller
        self.http = http or httpx.Client(timeout=timeout)
        self.model = model or None
        self.allow_fallback = allow_fallback
        self._contexts: dict[str, int | None] = {}
        self._contexts_at = 0.0

    CONTEXT_TTL_S = 300.0  # the gateway's contexts change only with a new pin (a restart): asked again after this

    def contexts(self) -> dict[str, int | None]:
        """Alias -> context in tokens, from ``GET /v1/models`` (T-603); None for an alias with none recorded. An
        unreachable gateway gives an empty map (the caller keeps its own default; the gateway still checks)."""
        now = time.monotonic()
        if self._contexts and now - self._contexts_at < self.CONTEXT_TTL_S:
            return dict(self._contexts)
        try:
            resp = self.http.get(f"{self.base_url}/models")
            data = resp.json().get("data", []) if resp.status_code == 200 else []
        except (httpx.HTTPError, ValueError, AttributeError):
            return {}
        out: dict[str, int | None] = {}
        for m in data if isinstance(data, list) else []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            raw = m.get("context_length") or m.get("max_model_len")
            out[str(m["id"])] = int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else None
        self._contexts, self._contexts_at = out, now
        return dict(out)

    def context(self, alias: str | None = None) -> int | None:
        """The context of ``alias`` (default: this client's ``model``); with no alias named, the smallest context any
        alias records (the gateway then picks the route's build, which on one box shares the profile's context)."""
        ctx = self.contexts()
        name = alias or self.model
        if name:
            return ctx.get(name)
        known = [v for v in ctx.values() if v]
        return min(known) if known else None

    @classmethod
    def from_env(cls, caller: str | None = None) -> GatewayClient:
        return cls(
            os.environ.get("TB_GATEWAY_URL", ""),
            caller or os.environ.get("TB_SERVICE_NAME", ""),
            model=os.environ.get("TB_GATEWAY_MODEL") or None,
        )

    def complete(self, body: dict[str, Any], labels: CallLabels) -> dict[str, Any]:
        """Send an OpenAI-style chat body; returns the raw payload (with the gateway's ``tb`` extension)."""
        if labels.role not in FREE_FORM_ROLES:
            rf = body.get("response_format")
            if not isinstance(rf, dict) or rf.get("type") != "json_schema":
                raise ValueError("tb_llm: a json_schema response_format is required (ENG-04, LLM-22)")
        from tb_common.service_auth import auth_headers

        headers = {**auth_headers(), **labels.headers(self.caller)}  # D-127 (F-11): the gateway checks the token
        if self.model and not body.get("model"):
            body = {**body, "model": self.model}
        try:
            resp = self.http.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as e:
            raise GatewayError(f"gateway unreachable: {e}") from e
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error") or {}
            except ValueError:
                err = {}
            if err.get("type") == "tb_refusal":
                raise GatewayRefused(
                    str(err.get("code")), resp.status_code, str(err.get("message")), str(err.get("call_id") or "")
                )
            raise GatewayError(f"gateway error {resp.status_code}: {resp.text[:500]}")
        payload: dict[str, Any] = resp.json()
        self._check_alias(payload, str(body.get("model") or ""), resp.headers.get("x-tb-fallbacks", ""))
        return payload

    def _check_alias(self, payload: dict[str, Any], named: str, header_fallbacks: str) -> None:
        """Raise :class:`GatewayUnexpectedAlias` unless the answer came from the alias this call expected (T-601)."""
        tb = payload.get("tb") if isinstance(payload, dict) else None
        tb = tb if isinstance(tb, dict) else {}
        alias = str(tb.get("alias") or "")
        call_id = str(tb.get("call_id") or "")
        expected = named or str(tb.get("expected_alias") or "")
        if not alias:
            raise GatewayUnexpectedAlias(
                "tb_llm: the answer does not say which build gave it (no tb.alias): not used", expected=expected
            )
        if named and alias != named:
            raise GatewayUnexpectedAlias(
                f"tb_llm: asked for {named!r}, answered by {alias!r}: not used",
                expected=named,
                alias=alias,
                call_id=call_id,
            )
        try:
            fallbacks = max(int(tb.get("fallbacks") or 0), int(header_fallbacks or 0))
        except (TypeError, ValueError):
            fallbacks = 1  # cannot tell: as if another build answered
        if self.allow_fallback:
            return
        if fallbacks > 0 or (expected and alias != expected):
            raise GatewayUnexpectedAlias(
                f"tb_llm: {alias!r} answered after {fallbacks} other build(s) failed"
                + (f" (expected {expected!r})" if expected else "")
                + "; pass allow_fallback=True to accept another build's answer",
                expected=expected,
                alias=alias,
                call_id=call_id,
            )

    def chat(
        self,
        messages: list[dict[str, Any]],
        labels: CallLabels,
        *,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {"messages": messages}
        if response_format is not None:
            body["response_format"] = response_format
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if model:
            body["model"] = model
        payload = self.complete(body, labels)
        retry = None
        if response_format is not None and payload["choices"][0].get("finish_reason") == "length":
            # reasoning models (gpt-oss, nemotron) spend the budget on reasoning and the JSON is cut off: ask the same
            # question once more with room to finish (stress test 2026-10-25), but never more than the answering
            # alias's context leaves beside the prompt (T-603, review LLM-018: 16,384 on an 8k model was an HTTP 400)
            alias = str((payload.get("tb") or {}).get("alias") or "")
            retry = retry_max_tokens(self.context(alias or None), estimate_messages(messages), int(max_tokens or 1024))
        if retry is not None:
            body["max_tokens"] = retry
            first = payload.get("usage") or {}
            payload = self.complete(body, labels)
            again = payload.get("usage") or {}
            payload["usage"] = {
                k: int(first.get(k) or 0) + int(again.get(k) or 0) for k in ("prompt_tokens", "completion_tokens")
            }
        content = str(payload["choices"][0]["message"].get("content") or "")
        tb = payload.get("tb") or {}
        usage = payload.get("usage") or {}
        data: Any = None
        if response_format is not None:
            try:
                data = json.loads(content)
            except ValueError:
                data = None
        return ChatResult(
            content=content,
            payload=payload,
            model=str(payload.get("model") or ""),
            call_id=str(tb.get("call_id") or ""),
            alias=str(tb.get("alias") or ""),
            build_sha=str(tb.get("build_sha") or ""),
            cache=str(tb.get("cache") or ""),
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            data=data,
        )

    def models(self) -> list[str]:
        resp = self.http.get(f"{self.base_url}/models")
        resp.raise_for_status()
        return [str(m["id"]) for m in resp.json().get("data", [])]


# ------------------------------------------------------------------------------------------------ v1 shim support
_V1_ROLES_PATH = os.path.join(os.path.dirname(__file__), "v1_roles.yaml")


def v1_labels(
    prompt_id: str,
    version: int,
    *,
    phi: bool,
    study_id: str | None,
    data_class: str | None = None,
    prompt_sha: str = "",
) -> CallLabels:
    """Labels for a v1 ``chat_json`` call routed through the gateway (``tb_common.llm`` shim, one milestone)."""
    import yaml

    with open(_V1_ROLES_PATH, encoding="utf-8") as fh:
        table: dict[str, dict[str, str]] = yaml.safe_load(fh) or {}
    row = table.get(prompt_id)
    if row is None:
        raise ValueError(f"tb_llm: prompt {prompt_id!r} has no role in v1_roles.yaml")
    dc = data_class or os.environ.get("TB_DATA_CLASS") or ("D3" if phi else "D1")
    return CallLabels(
        data_class=dc,
        purpose=row["purpose"],
        study_id=study_id or "none",
        context_of_use=row["context_of_use"],
        role=row["role"],
        prompt=f"{prompt_id}@{version}",
        step_id=os.environ.get("TB_STEP_ID", ""),
        prompt_sha=prompt_sha,
    )
