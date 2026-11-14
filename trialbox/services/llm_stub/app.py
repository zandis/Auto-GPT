"""Deterministic OpenAI-compatible LLM stub (``TB_LLM_MODE=stub``): ``/v1/chat/completions``, ``/v1/models``.

The prompt is identified by the ``X-TB-Prompt-Id`` header that ``tb_common.llm`` sends; the structured input is the
fenced JSON block of the first user message. See ``handlers.py`` for what each prompt returns.

It serves a fixed list of model names (:func:`served_models`) and answers 404 to any other, as vLLM does. Some names
are test personas (``handlers.PERSONAS``): a judge that disagrees, is unsure, misquotes, misdates or is down, so the
rules that keep a contested note answer from excluding a patient can be tested over the real HTTP path (D-276).

**Context limit (T-603).** ``TB_STUB_CONTEXT`` (tokens) or a ``stub-ctx-8k`` / ``stub-ctx-16k`` / ``stub-ctx-32k``
persona makes the stub enforce a context as vLLM does: a request whose prompt (estimated with
:func:`tb_llm.budget.estimate_messages`) plus ``max_tokens`` is over it gets vLLM's HTTP 400 "maximum context
length", and ``/v1/models`` reports ``max_model_len``. So a test shows that what callers size from the gateway's
context is accepted by a server that enforces it.

**Token counts are estimates (T-608, D-445; review LLM-046).** ``usage`` counts tokens with the same estimate as the
callers' budgets (:mod:`tb_llm.budget`: a CJK character about one token, Latin about four characters per token) and
says so (``usage.estimated: true``); the gateway's call record carries ``tokens_estimated``. No figure from a stub run
is a measured token count.

**The slow model stand-in (T-687, D-471).** The scale gate needs a model that is slow and fails the way a real server
does, over real HTTP: ``TB_STUB_LATENCY_S`` (seconds) delays every answer; ``TB_STUB_OUTAGE_AFTER`` (a call count)
and ``TB_STUB_OUTAGE_S`` (seconds) make every chat call answer 502 (or ``TB_STUB_OUTAGE_STATUS``) for that many
seconds once the n-th call has arrived (a vLLM restart behind a proxy). ``/v1/models`` keeps answering, as a proxy
in front of a restarting server does. A restart of the stand-in is the test killing and starting this process
(``tb_testkit.scale.SlowModel``).
Unset, the stub answers at once, as before.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from tb_common.http import make_app
from tb_llm.budget import estimate_messages, estimate_tokens

from llm_stub.handlers import HANDLERS, MESSAGE_HANDLERS, OBEYING, PERSONAS, obey

app = make_app("llm-stub", service_token=False)  # the stub stands in for vLLM, which has no box token
_BLOCK = re.compile(r"```json\s*(.*?)```", re.S)


# The names this stub answers to when ``TB_STUB_MODELS`` is not set. Like vLLM (``--served-model-name``) it refuses
# every other name with 404: before D-276 it answered to any name, so a mistyped or unserved model name passed every
# test, and "two models" could be one name asked twice (review S-3, P-34).
# ``trialbox-stub``: the registry's stub builds; ``stub`` / ``stub-verifier``: the judge and the verifier of the
# in-process tests and tools; the two ``local/`` names: the pair's served names (``tools/pin_model.py``), which the
# cloud rehearsal's vLLM stand-in (``tests/rehearsal/vllm_standin.py``) forwards unchanged.
DEFAULT_MODELS = (
    "trialbox-stub",
    "stub",
    "stub-verifier",
    "local/gemma-4-26b-a4b-nvfp4",
    "local/qwen3.5-9b-awq",
)


def served_models() -> list[str]:
    """``TB_STUB_MODELS`` (comma separated) or :data:`DEFAULT_MODELS`, then the test personas (``PERSONAS``)."""
    raw = os.environ.get("TB_STUB_MODELS", "")
    names = [n.strip() for n in raw.split(",") if n.strip()] or list(DEFAULT_MODELS)
    return [*names, *(p for p in PERSONAS if p not in names)]


class _Outage:
    """The stand-in's call count and outage window (T-687): process state, so a restart starts it again."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls = 0
        self.until: float | None = None

    def tick(self, environ: Mapping[str, str] | None = None) -> bool:
        """Count one chat call; True while the outage lasts."""
        environ = os.environ if environ is None else environ
        after = _float(environ.get("TB_STUB_OUTAGE_AFTER"))
        length = _float(environ.get("TB_STUB_OUTAGE_S"))
        now = time.monotonic()
        with self.lock:
            self.calls += 1
            if after is not None and length and self.until is None and self.calls >= after:
                self.until = now + length
            return self.until is not None and now < self.until


def _float(raw: str | None) -> float | None:
    try:
        v = float(raw) if raw not in (None, "") else None
    except ValueError:
        return None
    return v if v is not None and v >= 0 else None


OUTAGE = _Outage()


def _outage_status() -> int:
    """The status of the outage's answers: 502 (a restarting server behind a proxy), or ``TB_STUB_OUTAGE_STATUS``
    (an HTTP error status) so a test can play an outage the callers do not wait through (T-687)."""
    raw = (os.environ.get("TB_STUB_OUTAGE_STATUS") or "").strip()
    return int(raw) if raw.isdigit() and 400 <= int(raw) <= 599 else 502


CONTEXT_PERSONAS = {"stub-ctx-8k": 8192, "stub-ctx-16k": 16384, "stub-ctx-32k": 32768}


def context_limit(model: str) -> int | None:
    """The context this name enforces: a ``stub-ctx-*`` persona's, else ``TB_STUB_CONTEXT``, else none (T-603)."""
    if model in CONTEXT_PERSONAS:
        return CONTEXT_PERSONAS[model]
    raw = os.environ.get("TB_STUB_CONTEXT", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


@app.get("/v1/models")
def models() -> dict[str, Any]:
    # ``root`` as vLLM gives it: each name is its own model here (the stub plays every one of them)
    data: list[dict[str, Any]] = []
    for n in served_models():
        row: dict[str, Any] = {"id": n, "object": "model", "owned_by": "trialbox", "root": n}
        limit = context_limit(n)
        if limit:
            row["max_model_len"] = limit
        data.append(row)
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions")
async def completions(request: Request) -> Any:
    body = await request.json()
    latency = _float(os.environ.get("TB_STUB_LATENCY_S"))
    if latency:  # the slow stand-in (T-687): a model that takes seconds per call
        await asyncio.sleep(latency)
    if OUTAGE.tick():
        status = _outage_status()
        return JSONResponse(
            {"object": "error", "message": "stub outage: upstream unavailable", "code": status}, status_code=status
        )
    model = str(body.get("model") or served_models()[0])  # no name: the first served one (review F-08)
    if model not in served_models():
        return JSONResponse(
            {
                "object": "error",
                "message": f"The model `{model}` does not exist.",
                "type": "NotFoundError",
                "param": None,
                "code": 404,
            },
            status_code=404,
        )
    body = {**body, "model": model}
    limit = context_limit(model)
    if limit:
        mt = body.get("max_tokens")
        need = estimate_messages(body.get("messages") or []) + (mt if isinstance(mt, int) else 0)
        if need > limit:  # vLLM's answer to a prompt plus max_tokens over --max-model-len
            msg = (
                f"This model's maximum context length is {limit} tokens. However, you requested {need} tokens "
                f"in the messages and max_tokens. Please reduce the length of the messages or completion."
            )
            return JSONResponse(
                {"object": "error", "message": msg, "type": "BadRequestError", "param": None, "code": 400},
                status_code=400,
            )
    if model == "stub-down":
        return JSONResponse({"object": "error", "message": "stub-down: no answer", "code": 503}, status_code=503)
    prompt_id = request.headers.get("x-tb-prompt-id", "")
    if prompt_id in MESSAGE_HANDLERS:
        try:
            answer = MESSAGE_HANDLERS[prompt_id](list(body.get("messages", [])))
        except ValueError as exc:  # D-636: a fixed sentence and the type; the handler's text stays in the trace
            detail = f"the stub's handler for {prompt_id} could not read the messages ({type(exc).__name__})"
            raise HTTPException(status_code=400, detail=detail) from exc
        content = json.dumps(answer, ensure_ascii=False)
    else:
        handler = HANDLERS.get(prompt_id)
        if handler is None:
            raise HTTPException(status_code=400, detail=f"stub has no handler for prompt {prompt_id!r}")
        user = next((m["content"] for m in body.get("messages", []) if m.get("role") == "user"), "")
        m = _BLOCK.search(user)
        if not m:
            raise HTTPException(status_code=400, detail="no ```json input block in the user message")
        inp = json.loads(m.group(1))
        answer = handler(inp)
        if model in OBEYING:  # the injection suite's negative control (T-208): it follows a planted instruction
            answer = obey(prompt_id, inp, answer)
        elif prompt_id == "judge" and model in PERSONAS:
            answer = PERSONAS[model](answer)
        content = json.dumps(answer, ensure_ascii=False)
    return _completion(body, {"role": "assistant", "content": content}, "stop")


def _completion(body: dict[str, Any], message: dict[str, Any], finish: str) -> dict[str, Any]:
    # LLM-046: the callers' estimate (CJK-aware), marked as one; characters / 4 was four times low for CJK
    n_in = estimate_messages(body.get("messages") or [])
    n_out = estimate_tokens(str(message.get("content") or ""))
    return {
        "id": f"stub-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body["model"],  # the served name it was asked under, as vLLM answers
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out, "estimated": True},
    }
