"""Deterministic OpenAI-compatible LLM stub (``TB_LLM_MODE=stub``): ``/v1/chat/completions``, ``/v1/models``.

The prompt is identified by the ``X-TB-Prompt-Id`` header that ``tb_common.llm`` sends; the structured input is the
fenced JSON block of the first user message. See ``handlers.py`` for what each prompt returns.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import HTTPException, Request
from tb_common.http import make_app

from llm_stub.handlers import HANDLERS

app = make_app("llm-stub")
_BLOCK = re.compile(r"```json\s*(.*?)```", re.S)


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": "trialbox-stub", "object": "model", "owned_by": "trialbox"}]}


@app.post("/v1/chat/completions")
async def completions(request: Request) -> dict[str, Any]:
    body = await request.json()
    prompt_id = request.headers.get("x-tb-prompt-id", "")
    handler = HANDLERS.get(prompt_id)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"stub has no handler for prompt {prompt_id!r}")
    user = next((m["content"] for m in body.get("messages", []) if m.get("role") == "user"), "")
    m = _BLOCK.search(user)
    if not m:
        raise HTTPException(status_code=400, detail="no ```json input block in the user message")
    content = json.dumps(handler(json.loads(m.group(1))), ensure_ascii=False)
    n_in = sum(len(str(x.get("content", ""))) for x in body.get("messages", [])) // 4
    return {
        "id": f"stub-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "trialbox-stub"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": n_in,
            "completion_tokens": len(content) // 4,
            "total_tokens": n_in + len(content) // 4,
        },
    }
