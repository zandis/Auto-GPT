"""Deterministic OpenAI-compatible LLM stub (``TB_LLM_MODE=stub``): ``/v1/chat/completions``, ``/v1/models``.

The prompt is identified by the ``X-TB-Prompt-Id`` header that ``tb_common.llm`` sends; the structured input is the
fenced JSON block of the first user message. See ``handlers.py`` for what each prompt returns.

It serves a fixed list of model names (:func:`served_models`) and answers 404 to any other, as vLLM does. Some names
are test personas (``handlers.PERSONAS``): a judge that disagrees, is unsure, misquotes, misdates or is down, so the
rules that keep a contested note answer from excluding a patient can be tested over the real HTTP path (D-276).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from tb_common.http import make_app

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


@app.get("/v1/models")
def models() -> dict[str, Any]:
    # ``root`` as vLLM gives it: each name is its own model here (the stub plays every one of them)
    data = [{"id": n, "object": "model", "owned_by": "trialbox", "root": n} for n in served_models()]
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions")
async def completions(request: Request) -> Any:
    body = await request.json()
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
    if model == "stub-down":
        return JSONResponse({"object": "error", "message": "stub-down: no answer", "code": 503}, status_code=503)
    prompt_id = request.headers.get("x-tb-prompt-id", "")
    if prompt_id in MESSAGE_HANDLERS:
        try:
            answer = MESSAGE_HANDLERS[prompt_id](list(body.get("messages", [])))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    n_in = sum(len(str(x.get("content", ""))) for x in body.get("messages", [])) // 4
    n_out = len(json.dumps(message, ensure_ascii=False)) // 4
    return {
        "id": f"stub-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body["model"],  # the served name it was asked under, as vLLM answers
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out},
    }
