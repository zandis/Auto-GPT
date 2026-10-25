"""The single path from the TrialGPT port to a model.

The port called a local model server over HTTP. In TrialBox every model call goes through the gateway client
library (``libs/tb_llm``, S1-06), which this package does not import: the caller injects a client callable that
satisfies :class:`ChatClient`, and :func:`call_model` is the only function here that invokes it. With no client
injected, :func:`call_model` raises :class:`NoClientInjected`, so a missing wiring fails loudly instead of falling
back to some default endpoint.

:class:`LLMClient` keeps the port's behaviour around that call: an optional on-disk cache keyed by (model label,
messages, json mode), cassette replay for tests, and call counters. The cache is off by default because prompts
contain the patient note; benchmark runs on the public synthetic cohorts turn it on for resumability.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from matching.registry_match.config import Settings, settings

Messages = list[dict[str, str]]


class LLMError(RuntimeError):
    pass


class NoClientInjected(LLMError):
    """No model client was injected: registry_match reaches models only through the gateway client."""


class ContextOverflow(LLMError):
    """The prompt did not fit the model's context: the model would have seen a truncated prompt. Raised by clients."""


class DegenerateOutput(LLMError):
    """The server aborted the generation (for example a token-repeat limit). Deterministic at temperature 0, so it is
    not retried: the call yields no output, like an unparseable answer. Raised by clients."""


@dataclass(frozen=True)
class ChatReply:
    text: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatClient(Protocol):
    """A chat-completion callable. Implementations send ``messages`` to a model with temperature 0 and, when
    ``json_mode`` is true, ask for a JSON object; they raise :class:`ContextOverflow` when the prompt does not fit and
    :class:`DegenerateOutput` when the generation was aborted."""

    def __call__(self, messages: Messages, *, json_mode: bool) -> ChatReply: ...


def call_model(client: ChatClient | None, messages: Messages, *, json_mode: bool = True) -> ChatReply:
    """Send one chat request through the injected client. Every model call of this package goes through here."""
    if client is None:
        raise NoClientInjected(
            "registry_match has no model client: inject one (the tb-gateway client) into LLMClient(client=...)"
        )
    return client(messages, json_mode=json_mode)


@dataclass
class LLMResult:
    text: str
    data: Any  # parsed JSON, or None when the output is not JSON
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    cached: bool = False
    error: str | None = None  # why there is no output (degenerate generation), None otherwise


def extract_json(text: str) -> Any:
    """Parse the model output as JSON: strips code fences (NCBI did ``strip('`').strip('json')``) and falls back to the
    first JSON object in the text. Returns None when there is none."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(t[i:])
                return obj
            except json.JSONDecodeError:
                continue
    return None


def _key(model: str, messages: Messages, json_mode: bool) -> str:
    blob = json.dumps({"m": model, "msg": messages, "json": json_mode}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class LLMClient:
    def __init__(self, client: ChatClient | None = None, cfg: Settings | None = None, *, cache: bool = False) -> None:
        """``client``: the injected chat callable (None: every live call raises :class:`NoClientInjected`).
        ``cache=True`` writes responses to disk; use it only for the public synthetic cohorts, never for patients."""
        self.client = client
        self.cfg = cfg or settings()
        self.cache = cache
        self.calls = 0
        self.cache_hits = 0

    # ---------------------------------------------------------------- cache / cassette
    def _store(self) -> Path:
        return self.cfg.cassette_dir if self.cfg.llm_mode in ("cassette", "record") else self.cfg.cache_dir / "llm"

    def _load(self, key: str) -> dict[str, Any] | None:
        path = self._store() / key[:2] / f"{key}.json"
        if path.exists():
            return dict(json.loads(path.read_text(encoding="utf-8")))
        return None

    def _save(self, key: str, rec: dict[str, Any]) -> None:
        path = self._store() / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    # ---------------------------------------------------------------- calls
    def chat_json(self, messages: Messages, *, json_mode: bool = True) -> LLMResult:
        key = _key(self.cfg.model, messages, json_mode)
        hit = self._load(key) if self.cache or self.cfg.llm_mode == "cassette" else None
        if hit is not None:
            self.cache_hits += 1
            return LLMResult(
                text=hit["text"],
                data=extract_json(hit["text"]),
                model=hit.get("model", self.cfg.model),
                prompt_tokens=int(hit.get("prompt_tokens", 0)),
                completion_tokens=int(hit.get("completion_tokens", 0)),
                seconds=float(hit.get("seconds", 0.0)),
                cached=True,
            )
        if self.cfg.llm_mode == "cassette":
            raise LLMError(f"cassette miss {key[:12]} (record it with TB_MATCH_LLM_MODE=record)")
        t0 = time.perf_counter()
        try:
            reply = call_model(self.client, messages, json_mode=json_mode)
        except DegenerateOutput as exc:  # not cached: a later model or setting may answer
            self.calls += 1
            return LLMResult("", None, self.cfg.model, seconds=time.perf_counter() - t0, error=str(exc))
        secs = time.perf_counter() - t0
        self.calls += 1
        model = reply.model or self.cfg.model
        result = LLMResult(
            reply.text, extract_json(reply.text), model, reply.prompt_tokens, reply.completion_tokens, secs
        )
        if self.cache or self.cfg.llm_mode == "record":
            self._save(
                key,
                {
                    "model": model,
                    "json_mode": json_mode,
                    "messages_sha": key,
                    "text": reply.text,
                    "prompt_tokens": reply.prompt_tokens,
                    "completion_tokens": reply.completion_tokens,
                    "seconds": round(secs, 3),
                },
            )
        return result
