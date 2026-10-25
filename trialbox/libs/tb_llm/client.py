"""The only LLM client library (spec v4 §8.2, ENG-04; S1-06): talks to ``tb-gateway`` and nothing else.

Every call carries its labels as ``X-TB-*`` headers — data class, study, purpose, context of use, role, prompt, and
the caller's service id — and, for every role except free-form ones, a ``json_schema`` response format. Labels are
set by the calling step from the data it read (§7.1); this library never infers them.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

FREE_FORM_ROLES = frozenset({"frontdesk_converse"})


class GatewayError(RuntimeError):
    """The gateway could not be reached or answered with an unexpected error."""


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
    def __init__(self, base_url: str, caller: str, *, http: httpx.Client | None = None, timeout: float = 600.0) -> None:
        if not base_url:
            raise ValueError("tb_llm: gateway URL required")
        self.base_url = base_url.rstrip("/")
        self.caller = caller
        self.http = http or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls, caller: str | None = None) -> GatewayClient:
        return cls(os.environ.get("TB_GATEWAY_URL", ""), caller or os.environ.get("TB_SERVICE_NAME", ""))

    def complete(self, body: dict[str, Any], labels: CallLabels) -> dict[str, Any]:
        """Send an OpenAI-style chat body; returns the raw payload (with the gateway's ``tb`` extension)."""
        if labels.role not in FREE_FORM_ROLES:
            rf = body.get("response_format")
            if not isinstance(rf, dict) or rf.get("type") != "json_schema":
                raise ValueError("tb_llm: a json_schema response_format is required (ENG-04, LLM-22)")
        headers = labels.headers(self.caller)
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
        return payload

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
    prompt_id: str, version: int, *, phi: bool, study_id: str | None, data_class: str | None = None
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
    )
