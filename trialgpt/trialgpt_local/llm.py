"""Local LLM client replacing NCBI's ``AzureOpenAI`` client.

Backends:
* ``ollama`` (default): native ``/api/chat`` with ``format: json``, ``temperature 0``, a fixed ``seed`` and an explicit
  ``num_ctx``. The OpenAI-compatible ``/v1`` route of Ollama ignores ``num_ctx``, so long TrialGPT prompts would be
  truncated silently there. A prompt that fills the window raises :class:`ContextOverflow` instead.
* ``openai``: any OpenAI-compatible ``/v1/chat/completions`` (vLLM, llama.cpp server, LM Studio, ...).

Every response is cached on disk by a hash of (backend, model, messages, options), so runs are resumable and
re-runs are free. ``TG_LLM_MODE=cassette`` replays recorded responses (tests, CI) and fails on a miss.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from trialgpt_local.config import Settings, settings

Messages = list[dict[str, str]]


class LLMError(RuntimeError):
    pass


class ContextOverflow(LLMError):
    """The prompt does not fit in ``num_ctx``: the model would have seen a truncated prompt."""


class DegenerateOutput(LLMError):
    """The server aborted the generation (e.g. Ollama's "token repeat limit reached" when a model loops). Deterministic
    at temperature 0, so it is not retried: the call yields no output, like an unparseable answer."""


_DEGENERATE = ("prediction aborted", "repeat limit")


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


def _key(backend: str, model: str, messages: Messages, options: dict[str, Any]) -> str:
    blob = json.dumps({"b": backend, "m": model, "msg": messages, "o": options}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class LLMClient:
    def __init__(self, cfg: Settings | None = None, http: httpx.Client | None = None, *, cache: bool = True) -> None:
        """``cache=False`` for interactive use with real patients: prompts contain the note, so nothing is written to
        disk (benchmark runs on the public synthetic cohorts keep the cache for resumability)."""
        self.cfg = cfg or settings()
        self.cache = cache
        self.http = http or httpx.Client(timeout=self.cfg.llm_timeout)
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
    def options(self) -> dict[str, Any]:
        opts: dict[str, Any] = {"temperature": 0, "seed": self.cfg.llm_seed}
        if self.cfg.llm_backend == "ollama":
            opts["num_ctx"] = self.cfg.llm_num_ctx
            if self.cfg.llm_think:  # only when on, so cache keys of earlier runs stay valid
                opts["think"] = True
        return opts

    def chat_json(self, messages: Messages, *, json_mode: bool = True) -> LLMResult:
        opts = {**self.options(), "json": json_mode}
        key = _key(self.cfg.llm_backend, self.cfg.llm_model, messages, opts)
        hit = self._load(key) if self.cache or self.cfg.llm_mode == "cassette" else None
        if hit is not None:
            self.cache_hits += 1
            return LLMResult(
                text=hit["text"],
                data=extract_json(hit["text"]),
                model=hit.get("model", self.cfg.llm_model),
                prompt_tokens=int(hit.get("prompt_tokens", 0)),
                completion_tokens=int(hit.get("completion_tokens", 0)),
                seconds=float(hit.get("seconds", 0.0)),
                cached=True,
            )
        if self.cfg.llm_mode == "cassette":
            raise LLMError(f"cassette miss {key[:12]} (record it with TG_LLM_MODE=record)")
        t0 = time.perf_counter()
        try:
            if self.cfg.llm_backend == "ollama":
                text, pt, ct = self._ollama(messages, json_mode)
            else:
                text, pt, ct = self._openai(messages, json_mode)
        except DegenerateOutput as exc:  # not cached: a later model or setting may answer
            self.calls += 1
            return LLMResult("", None, self.cfg.llm_model, seconds=time.perf_counter() - t0, error=str(exc))
        secs = time.perf_counter() - t0
        self.calls += 1
        if not self.cache and self.cfg.llm_mode != "record":
            return LLMResult(text, extract_json(text), self.cfg.llm_model, pt, ct, secs)
        self._save(
            key,
            {
                "model": self.cfg.llm_model,
                "backend": self.cfg.llm_backend,
                "options": opts,
                "messages_sha": key,
                "text": text,
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "seconds": round(secs, 3),
            },
        )
        return LLMResult(text, extract_json(text), self.cfg.llm_model, pt, ct, secs)

    def _ollama(self, messages: Messages, json_mode: bool) -> tuple[str, int, int]:
        body: dict[str, Any] = {
            "model": self.cfg.llm_model,
            "messages": messages,
            "stream": False,
            "think": self.cfg.llm_think,  # false is accepted by models without a thinking mode too
            "options": {
                "temperature": 0,
                "seed": self.cfg.llm_seed,
                "num_ctx": self.cfg.llm_num_ctx,
                "num_predict": 4096,
            },
        }
        if json_mode:
            body["format"] = "json"
        resp = self._post(f"{self.cfg.llm_base_url.rstrip('/')}/api/chat", body, {})
        pt = int(resp.get("prompt_eval_count") or 0)
        ct = int(resp.get("eval_count") or 0)
        # Ollama truncates the start of an over-long prompt and reports the kept part: a prompt that fills the window
        # was (almost certainly) cut — the patient note comes first and would be lost
        if pt >= self.cfg.llm_num_ctx - 8:
            raise ContextOverflow(
                f"prompt used {pt} of num_ctx={self.cfg.llm_num_ctx} tokens: "
                "raise TG_LLM_NUM_CTX (and the model's memory)"
            )
        return str(resp.get("message", {}).get("content", "")), pt, ct

    def _openai(self, messages: Messages, json_mode: bool) -> tuple[str, int, int]:
        body: dict[str, Any] = {
            "model": self.cfg.llm_model,
            "messages": messages,
            "temperature": 0,
            "seed": self.cfg.llm_seed,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        base = self.cfg.llm_base_url.rstrip("/")
        url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
        resp = self._post(url, body, {"Authorization": f"Bearer {self.cfg.llm_api_key}"})
        usage = resp.get("usage") or {}
        text = str(resp["choices"][0]["message"]["content"] or "")
        if resp["choices"][0].get("finish_reason") == "length":
            raise ContextOverflow("the model hit its output/context limit (finish_reason=length)")
        return text, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))

    def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.http.post(url, json=body, headers=headers)
                if r.status_code >= 500 and any(s in r.text for s in _DEGENERATE):
                    raise DegenerateOutput(f"generation aborted by the server: {r.text[:300]}")
                if r.status_code >= 500:
                    raise LLMError(f"LLM server {r.status_code}: {r.text[:300]}")
                if r.status_code >= 400:
                    raise LLMError(f"LLM request refused {r.status_code}: {r.text[:300]}")
                return dict(r.json())
            except (httpx.TransportError, LLMError) as exc:
                if isinstance(exc, DegenerateOutput) or (isinstance(exc, LLMError) and "refused" in str(exc)):
                    raise
                last = exc
                time.sleep(2**attempt)
        raise LLMError(f"LLM call to {url} failed 3 times: {last}")
