"""The only LLM entry point in TrialBox (SPEC §4.7, §7): ``chat_json(prompt_id, variables, schema)``.

* Prompts are files ``services/*/prompts/<id>_v<n>.md`` with YAML front matter (``PromptMeta``) and ``## system`` /
  ``## user`` Jinja2 sections; the newest version is used unless pinned (``"judge_v3"``).
* Output is constrained with ``response_format: json_schema`` (vLLM guided decoding), validated with jsonschema,
  retried once with the violations; a second violation raises :class:`LlmSchemaError`.
* Routing: ``model_class: cloud`` prompts go to ``CLOUD_LLM_BASE_URL`` only when (a) the calling service is
  ``criteria-compiler``, (b) ``settings.models.cloud_enabled``, (c) a :class:`PhiClearance` for exactly the call's
  variables (``phi_guard.variables_text``, everything that is not fixed template text) is supplied. Everything else
  goes to the local endpoint (``LLM_BASE_URL``).
* Every call appends ``llm.call`` to the audit chain with prompt id/version, model, input/output sha.
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
from tb_contracts import PromptMeta, inline_schema, schema_errors

from tb_common.audit import AuditLog
from tb_common.crypto import sha256_text
from tb_common.phi_guard import PhiClearance, variables_text

REPO = Path(__file__).resolve().parents[2]
_FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)
_SECTION = re.compile(r"^##\s+(system|user)\s*$", re.M)
_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=False)  # noqa: S701
_env.filters["tojson_pretty"] = lambda v: json.dumps(v, ensure_ascii=False, indent=1, sort_keys=True)
CLOUD_SERVICE = "criteria-compiler"


class LlmError(RuntimeError):
    pass


class LlmSchemaError(LlmError):
    pass


@dataclass(frozen=True)
class Prompt:
    meta: PromptMeta
    system: str
    user: str
    path: Path


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


def prompt_dirs() -> list[Path]:
    env = os.environ.get("TB_PROMPT_DIRS")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p]
    return sorted((REPO / "services").glob("*/prompts"))


@lru_cache(maxsize=128)
def load_prompt(prompt_id: str) -> Prompt:
    """``judge`` -> newest ``judge_v<n>.md``; ``judge_v3`` -> exactly version 3."""
    pinned = re.fullmatch(r"(.+)_v(\d+)", prompt_id)
    base, want = (pinned.group(1), int(pinned.group(2))) if pinned else (prompt_id, None)
    found: list[tuple[int, Path]] = []
    for d in prompt_dirs():
        for p in d.glob(f"{base}_v*.md"):
            m = re.fullmatch(rf"{re.escape(base)}_v(\d+)\.md", p.name)
            if m:
                found.append((int(m.group(1)), p))
    if want is not None:
        found = [f for f in found if f[0] == want]
    if not found:
        raise LlmError(f"prompt {prompt_id!r} not found in {[str(d) for d in prompt_dirs()]}")
    _, path = max(found)
    m = _FM.match(path.read_text(encoding="utf-8"))
    if not m:
        raise LlmError(f"{path}: missing YAML front matter")
    meta = PromptMeta.model_validate(yaml.safe_load(m.group(1)))
    parts = _SECTION.split(m.group(2))
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if "system" not in sections or "user" not in sections:
        raise LlmError(f"{path}: needs '## system' and '## user' sections")
    return Prompt(meta, sections["system"], sections["user"], path)


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

    @classmethod
    def from_config(cls, audit: AuditLog | None = None) -> LlmClient:
        from tb_common.config import get_config

        cfg = get_config()
        models = cfg.settings.models
        return cls(
            cfg.env.llm_base_url,
            cfg.env.llm_model,
            cloud_base_url=cfg.env.cloud_llm_base_url,
            cloud_api_key=cfg.env.cloud_llm_api_key,
            cloud_model=(models.cloud_model if models else "") or "",
            cloud_enabled=bool(models and models.cloud_enabled),
            service_name=cfg.env.service_name,
            audit=audit or AuditLog(cfg.env.audit_path, cfg.env.tz),
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
    ) -> LlmResult:
        prompt = load_prompt(prompt_id)
        schema_name = schema or prompt.meta.output_schema
        json_schema = inline_schema(schema_name)
        messages = render(prompt, variables)
        input_text = "\n".join(m["content"] for m in messages)
        input_sha = sha256_text(input_text)
        target = self._target(prompt.meta, variables, clearance)
        base, model = (self.cloud_base_url, self.cloud_model) if target == "cloud" else (self.base_url, self.model)
        headers = {"X-TB-Prompt-Id": prompt.meta.id, "X-TB-Prompt-Version": str(prompt.meta.version)}
        if target == "cloud" and self.cloud_api_key:
            headers["Authorization"] = f"Bearer {self.cloud_api_key}"
        tokens_in = tokens_out = 0
        errors: list[str] = []
        convo = list(messages)
        for attempt in (1, 2):
            body = {
                "model": model,
                "messages": convo,
                "temperature": prompt.meta.temperature,
                "max_tokens": prompt.meta.max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": prompt.meta.id, "schema": json_schema, "strict": True},
                },
            }
            t0 = time.perf_counter()
            try:
                resp = self.http.post(f"{base}/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise LlmError(f"LLM endpoint unreachable ({target}): {exc}") from exc
            if resp.status_code >= 400:
                raise LlmError(f"LLM endpoint error {resp.status_code}: {resp.text[:500]}")
            payload = resp.json()
            usage = payload.get("usage") or {}
            tokens_in += int(usage.get("prompt_tokens", 0))
            tokens_out += int(usage.get("completion_tokens", 0))
            content = payload["choices"][0]["message"].get("content") or ""
            try:
                data = _extract_json(content)
                errors = schema_errors(schema_name, data)
            except (json.JSONDecodeError, ValueError) as exc:
                data, errors = None, [f"not JSON: {exc}"]
            if not errors and isinstance(data, dict):
                output_sha = sha256_text(json.dumps(data, sort_keys=True, ensure_ascii=False))
                if self.audit is not None:
                    self.audit.append(
                        "llm.call",
                        job_id=job_id,
                        model=model,
                        prompt_version=f"{prompt.meta.id}_v{prompt.meta.version}",
                        input_sha=input_sha,
                        output_sha=output_sha,
                        detail={
                            "target": target,
                            "attempts": attempt,
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "phi_guard_hit": phi_guard_hit,
                            "ms": round((time.perf_counter() - t0) * 1000),
                        },
                    )
                return LlmResult(
                    data,
                    prompt.meta.id,
                    prompt.meta.version,
                    model,
                    target,
                    input_sha,
                    output_sha,
                    tokens_in,
                    tokens_out,
                    attempt,
                )
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
                model=model,
                input_sha=input_sha,
                prompt_version=f"{prompt.meta.id}_v{prompt.meta.version}",
                detail={"errors": errors[:5]},
            )
        raise LlmSchemaError(f"{prompt_id}: output violated schema twice: {errors[:5]}")


_default: LlmClient | None = None


def default_client() -> LlmClient:
    global _default
    if _default is None:
        _default = LlmClient.from_config()
    return _default


def chat_json(prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
    """SPEC §4.7 wrapper over the process-wide client."""
    return default_client().chat_json(prompt_id, variables, schema, **kw)
