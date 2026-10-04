"""Deterministic OpenAI-compatible LLM stub (phase 0: health + model list)."""

from __future__ import annotations

from typing import Any

from tb_common.http import make_app

app = make_app("llm-stub")


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": "trialbox-stub", "object": "model", "owned_by": "trialbox"}]}
