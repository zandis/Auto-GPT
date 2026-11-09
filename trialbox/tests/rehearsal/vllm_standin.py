"""A vLLM stand-in for the rehearsal (D-150): the OpenAI server surface the gateway and the run touch, strict where the
cloud run failed and the local stub is not.

* ``--api-key``: every /v1 request needs ``Authorization: Bearer <key>`` (401 otherwise), /health does not;
* ``--served-model-name``: a request whose ``model`` is not the served name is **404** (vLLM's NotFoundError), the
  failure of the cloud run of 2026-11-09 that the local stub (it echoes any name) could not show;
* the response echoes the served name in ``model`` (the gateway's served-model echo check);
* /health answers 200 only after ``--load-seconds`` (a real vLLM loads weights for minutes).

The answers come from the repository's deterministic stub (``llm_stub.app``) through an in-process ASGI transport, so
only the server surface is vLLM's; a call without the stub's ``X-TB-Prompt-Id`` (the VM's pre-flight chat call) gets a
plain answer. Every call is logged on one line (status, path, model), for ``check.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ap = argparse.ArgumentParser()
ap.add_argument("--host", required=True)
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--served", required=True)
ap.add_argument("--key-file", required=True)
ap.add_argument("--load-seconds", type=float, default=20.0)
ap.add_argument("--name", default="vllm")
ap.add_argument("--repo", default="/rehearsal/repo")
a = ap.parse_args()
for p in (a.repo, f"{a.repo}/libs", f"{a.repo}/services"):
    sys.path.insert(0, p)

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from llm_stub.app import app as stub  # noqa: E402

KEY = Path(a.key_file).read_text(encoding="utf-8").strip()
READY_AT = time.time() + a.load_seconds
app = FastAPI()
stub_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=stub), base_url="http://stub", timeout=120.0)


def log(status: int, path: str, model: Any = "") -> None:
    print(f"[{a.name}] {status} {path} model={model!r} served={a.served!r}", flush=True)


@app.get("/health")
def health() -> Response:
    if time.time() < READY_AT:
        return JSONResponse({"status": "loading"}, status_code=503)
    return JSONResponse({})


def _auth(request: Request) -> Response | None:
    if request.headers.get("authorization", "") != f"Bearer {KEY}":
        log(401, request.url.path)
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None


@app.get("/v1/models")
async def models(request: Request) -> Response:
    if (r := _auth(request)) is not None:
        return r
    log(200, "/v1/models")
    return JSONResponse({"object": "list", "data": [{"id": a.served, "object": "model", "owned_by": "vllm"}]})


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Response:
    if (r := _auth(request)) is not None:
        return r
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        log(400, "/v1/chat/completions")
        return JSONResponse({"object": "error", "message": "invalid JSON", "code": 400}, status_code=400)
    model = body.get("model")
    if model != a.served:
        log(404, "/v1/chat/completions", model)
        return JSONResponse(
            {"object": "error", "message": f"The model `{model}` does not exist.", "type": "NotFoundError",
             "param": None, "code": 404},
            status_code=404,
        )  # fmt: skip
    if "x-tb-prompt-id" not in request.headers:  # the VM's pre-flight call: any answer will do, as from vLLM
        log(200, "/v1/chat/completions", model)
        return JSONResponse({"id": "standin", "object": "chat.completion", "created": int(time.time()), "model": a.served,
                             "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                                          "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}})  # fmt: skip
    # the repository stub picks its handler from the gateway's X-TB-Prompt-* headers: forward all but hop-by-hop ones
    skip = ("host", "content-length", "authorization", "connection")
    fwd = {k: v for k, v in request.headers.items() if k.lower() not in skip}
    up = await stub_client.post("/v1/chat/completions", content=raw, headers=fwd)
    if up.status_code != 200:
        log(up.status_code, "/v1/chat/completions (stub)", model)
        return Response(content=up.content, status_code=up.status_code, media_type="application/json")
    payload = up.json()
    payload["model"] = a.served  # vLLM echoes --served-model-name
    log(200, "/v1/chat/completions", model)
    return JSONResponse(payload)


@app.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def other(rest: str, request: Request) -> Response:
    if rest.startswith("v1") and (r := _auth(request)) is not None:
        return r
    return JSONResponse({"detail": "Not Found"}, status_code=404)


print(f"[{a.name}] stand-in serving {a.served!r} on {a.host}:{a.port}; /health ready in {a.load_seconds}s", flush=True)
uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
