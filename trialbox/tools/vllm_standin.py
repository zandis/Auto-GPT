"""A strict stand-in for one vLLM server (D-177): the box-install rehearsal runs it where the GPU would be.

It takes vLLM's own command line, so the compose file's ``command:`` for ``llm-service`` and ``llm-verifier`` is used
unchanged, and it is stricter than vLLM where a box goes wrong:

* **Served names.** It answers only the exact ``--served-model-name`` (one or more; the last path part of ``--model``
  when none is given, as vLLM). Any other ``model`` gets vLLM's 404 ``NotFoundError``.
* **Key.** It needs an API key (``--api-key`` or ``VLLM_API_KEY``, as vLLM) and refuses to start without one; every
  ``/v1`` call without ``Authorization: Bearer <key>`` gets 401. ``/health`` is open, as in vLLM.
* **Open routes, as vLLM.** ``POST /invocations`` (SageMaker: chat) and ``POST /tokenize`` answer without the key,
  as vLLM v0.32 does (it checks the key on ``/v1``, ``/v2``, ``/inference`` and ``/cohere`` only), so a rehearsal
  without ``model-guard`` in front would show the hole (``trialbox doctor --serving`` probes them). ``/tokenize``
  takes a ``prompt`` or ``messages`` and returns token ids (one per character: a stand-in's tokenizer).
* **Metrics.** ``GET /metrics`` answers without the key, as vLLM's does, in Prometheus text with vLLM's names
  (prompt and generation tokens, requests, time to first token, queue time, running, waiting, KV cache), counted
  from the answered calls: the complete run scrapes it around every part (review test G-3).
* **Answers.** The deterministic answers of ``services/llm_stub`` (by the ``X-TB-Prompt-Id`` header the gateway
  forwards); the response's ``model`` is the served name, so the gateway's served-model echo check runs for real.
* **Counts.** ``GET /standin/stats`` (with the key) returns the count of model calls by status (200, 400, 401, 404,
  503), so a rehearsal can assert "no 401 and no 404" on a good box. A model call is a ``POST`` to
  ``/v1/chat/completions`` or ``/v1/completions``; ``/health``, ``/v1/models``, ``/standin/stats`` and unknown paths
  are not counted there (the container health check polls ``/health`` every few seconds). ``/v1/models`` answers are
  counted apart, under ``listings``.

Other vLLM flags (``--max-model-len``, ``--gpu-memory-utilization`` ...) are accepted and ignored.

    python -m tools.vllm_standin --model=/models/gemma-4-26b-a4b-it-4bit --served-model-name=gemma-4-26b-a4b-it \\
        --api-key "$KEY" [--host 0.0.0.0] [--port 8000] [--load-delay 5]

Standard library only, plus ``services/llm_stub/handlers.py`` (pure Python). Never a model: plumbing, names, keys.
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_BLOCK = re.compile(r"```json\s*(.*?)```", re.S)
MAX_BODY = 8 * 1024 * 1024  # bytes of one request body
# The listen backlog: uvicorn's default (2048), which vLLM's OpenAI server listens with, so a burst of calls waits in
# the kernel's queue while the accept loop is slow, as on vLLM. socketserver's default is 5: a burst of 16 (G-4 sends
# the judge's slots at once) behind an accept loop starved of CPU and of the GIL overflowed it, the kernel answered
# with SYN cookies, and one connection was reset before the stand-in read it (train 16 and PR #613: 127 of 128 calls
# answered, the 128th "Connection reset by peer").
BACKLOG = 2048
OPEN_ROUTES = ("/invocations", "/tokenize")  # vLLM answers these without the key (counted under "open")


def tokenize(body: dict[str, Any]) -> dict[str, Any]:
    """vLLM's ``/tokenize`` answer for a ``prompt`` or ``messages`` body: one id per character of the text (chat
    messages as ``<role>\\n<content>\\n`` each), so equal texts give equal ids and nothing else does."""
    if body.get("messages"):
        text = "".join(f"<{m.get('role', '')}>\n{m.get('content', '')}\n" for m in body["messages"]
                       if isinstance(m, dict))  # fmt: skip
    else:
        text = str(body.get("prompt") or "")
    ids = [ord(c) for c in text]
    return {"count": len(ids), "max_model_len": 32768, "tokens": ids}


def metrics_text(served: str, requests: int = 0, prompt_tokens: int = 0, generation_tokens: int = 0) -> str:
    """``GET /metrics`` as vLLM v0.32 names it, for one served model: counters from the answered calls; a stand-in
    answers at once, so nothing waits and the time to first token is a nominal 10 ms a call."""
    lab = f'{{model_name="{served}"}}'
    rows = [("vllm:prompt_tokens_total", "counter", prompt_tokens),
            ("vllm:generation_tokens_total", "counter", generation_tokens),
            ("vllm:request_success_total", "counter", requests),
            ("vllm:time_to_first_token_seconds_sum", "histogram", round(0.01 * requests, 3)),
            ("vllm:time_to_first_token_seconds_count", "", requests),
            ("vllm:request_queue_time_seconds_sum", "histogram", 0.0),
            ("vllm:request_queue_time_seconds_count", "", requests),
            ("vllm:e2e_request_latency_seconds_sum", "histogram", round(0.02 * requests, 3)),
            ("vllm:e2e_request_latency_seconds_count", "", requests),
            ("vllm:num_requests_running", "gauge", 0), ("vllm:num_requests_waiting", "gauge", 0),
            ("vllm:kv_cache_usage_perc", "gauge", 0.0)]  # fmt: skip
    out = []
    for name, kind, value in rows:
        if kind:
            out.append(f"# TYPE {name.removesuffix('_sum') if kind == 'histogram' else name} {kind}")
        out.append(f"{name}{lab} {float(value)}")
    return "\n".join(out) + "\n"


class Standin:
    """The served names, the key and the counters of one stand-in server."""

    def __init__(self, served: list[str], key: str, load_delay: float = 0.0) -> None:
        if not served:
            raise ValueError("no served model name")
        if not key:
            raise ValueError("no API key (--api-key or VLLM_API_KEY): the strict stand-in does not run open")
        self.served = list(dict.fromkeys(served))
        self.key = key
        self.ready_at = time.monotonic() + max(0.0, load_delay)
        self.counts: Counter[int] = Counter()  # model calls (POST /v1/chat/completions, /v1/completions) by status
        self.listings: Counter[int] = Counter()  # GET /v1/models by status
        self.open_calls: Counter[int] = Counter()  # /invocations, /tokenize (no key, as vLLM) by status
        self.tokens: Counter[str] = Counter()  # prompt and generation tokens of the answered calls (/metrics)
        self.lock = threading.Lock()

    def count(self, status: int, kind: str = "call") -> None:
        with self.lock:
            {"call": self.counts, "listing": self.listings, "open": self.open_calls}[kind][status] += 1

    def stats(self) -> dict[str, Any]:
        with self.lock:
            return {
                "served": self.served,
                "counts": {str(k): v for k, v in sorted(self.counts.items())},
                "listings": {str(k): v for k, v in sorted(self.listings.items())},
                "open": {str(k): v for k, v in sorted(self.open_calls.items())},
            }

    def authorised(self, header: str | None) -> bool:
        scheme, _, token = (header or "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(token.strip().encode(), self.key.encode())

    def models(self) -> dict[str, Any]:
        now = int(time.time())
        data = [{"id": n, "object": "model", "created": now, "owned_by": "vllm", "root": n} for n in self.served]
        return {"object": "list", "data": data}

    def complete(self, body: dict[str, Any], prompt_id: str) -> tuple[int, dict[str, Any]]:
        """(status, payload) for one chat completion: 404 for a name not served, 400 for an input the stub cannot
        answer, else the stub's deterministic answer under the served name."""
        model = body.get("model")
        if model not in self.served:
            return 404, _error(f"The model `{model}` does not exist.", "NotFoundError", 404)
        from llm_stub.handlers import HANDLERS, MESSAGE_HANDLERS

        messages = list(body.get("messages") or [])
        try:
            if prompt_id in MESSAGE_HANDLERS:
                answer = MESSAGE_HANDLERS[prompt_id](messages)
            else:
                handler = HANDLERS.get(prompt_id)
                if handler is None:
                    return 400, _error(f"stand-in has no answer for prompt {prompt_id!r}", "BadRequestError", 400)
                user = next((str(m.get("content", "")) for m in messages if m.get("role") == "user"), "")
                m = _BLOCK.search(user)
                if not m:
                    return 400, _error("no ```json input block in the user message", "BadRequestError", 400)
                answer = handler(json.loads(m.group(1)))
        except (ValueError, KeyError, TypeError) as exc:
            return 400, _error(f"stand-in could not answer: {exc}", "BadRequestError", 400)
        content = json.dumps(answer, ensure_ascii=False)
        n_in = sum(len(str(x.get("content", ""))) for x in messages) // 4
        n_out = len(content) // 4
        with self.lock:
            self.tokens.update({"prompt": n_in, "generation": n_out})
        return 200, {
            "id": f"chatcmpl-standin-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out},
        }


def _error(message: str, kind: str, code: int) -> dict[str, Any]:
    return {"object": "error", "message": message, "type": kind, "param": None, "code": code}


class StandinServer(ThreadingHTTPServer):
    """The stand-in's HTTP server: a thread per connection, listening with vLLM's backlog (:data:`BACKLOG`)."""

    request_queue_size = BACKLOG


def serve(s: Standin, host: str = "127.0.0.1", port: int = 0) -> StandinServer:
    """A server for ``s``, bound and listening (port 0: a free one); the caller runs ``serve_forever``."""
    return StandinServer((host, port), make_handler(s))


def make_handler(s: Standin) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "vllm-standin"

        def log_message(self, format: str, *args: Any) -> None:  # one line per call on stderr, never the key
            sys.stderr.write("standin %s\n" % (format % args))

        def _send(self, status: int, payload: dict[str, Any] | None, kind: str = "") -> None:
            """Send one answer; ``kind`` "call" (a model call) or "listing" (``/v1/models``) counts it, "" does not."""
            if kind:
                s.count(status, kind)
            data = json.dumps(payload or {}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _gate(self, kind: str = "") -> bool:
            """True when the call may go on; else the 503 (loading) or 401 (key) answer is sent."""
            if time.monotonic() < s.ready_at:
                self._send(503, _error("the model is loading", "ServiceUnavailableError", 503), kind)
                return False
            if not s.authorised(self.headers.get("Authorization")):
                self._send(401, {"error": "Unauthorized"}, kind)
                return False
            return True

        def _open_route(self, path: str, raw: bytes) -> None:
            """vLLM's routes outside /v1: they answer without the key, so only model-guard keeps them off model-net."""
            if time.monotonic() < s.ready_at:
                self._send(503, _error("the model is loading", "ServiceUnavailableError", 503), "open")
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = {}
            body = body if isinstance(body, dict) else {}
            if path == "/tokenize":
                self._send(200, tokenize(body), "open")
            elif "messages" in body:  # /invocations: SageMaker's chat route
                status, payload = s.complete({**body, "model": body.get("model") or s.served[0]},
                                             self.headers.get("X-TB-Prompt-Id", ""))  # fmt: skip
                self._send(status, payload, "open")
            else:
                self._send(400, _error("no messages", "BadRequestError", 400), "open")

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                ok = time.monotonic() >= s.ready_at
                self._send(200 if ok else 503, {} if ok else _error("loading", "ServiceUnavailableError", 503))
            elif path == "/v1/models":
                if self._gate("listing"):
                    self._send(200, s.models(), "listing")
            elif path == "/metrics":  # open, as vLLM's; not counted (the run scrapes it around every part)
                with s.lock:
                    text = metrics_text(s.served[0], s.counts[200], s.tokens["prompt"], s.tokens["generation"])
                data = text.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif path == "/standin/stats":
                if self._gate():
                    self._send(200, s.stats())
            else:
                self._send(404, {"detail": "Not Found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:  # never read a body it would not take, key or no key
                self.close_connection = True
                self._send(413 if length > MAX_BODY else 400, _error("bad Content-Length", "BadRequestError", 400))
                return
            raw = self.rfile.read(length) if length else b""
            if path in OPEN_ROUTES:  # as vLLM: no key on these (vLLM guards /v1, /v2, /inference, /cohere only)
                self._open_route(path, raw)
                return
            if path not in ("/v1/chat/completions", "/v1/completions"):
                self._send(404, {"detail": "Not Found"})
                return
            if not self._gate("call"):
                return
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body is not an object")
            except ValueError as exc:
                self._send(400, _error(f"bad JSON: {exc}", "BadRequestError", 400), "call")
                return
            if path == "/v1/completions":  # the box never calls it; served-name and key rules still apply
                if body.get("model") not in s.served:
                    msg = f"The model `{body.get('model')}` does not exist."
                    self._send(404, _error(msg, "NotFoundError", 404), "call")
                else:
                    msg = "the stand-in answers chat completions only"
                    self._send(400, _error(msg, "BadRequestError", 400), "call")
                return
            status, payload = s.complete(body, self.headers.get("X-TB-Prompt-Id", ""))
            self._send(status, payload, "call")

    return Handler


def parse(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    ap = argparse.ArgumentParser(prog="vllm_standin", description=__doc__.split("\n\n", 1)[0], allow_abbrev=False)
    ap.add_argument("--model", default="")
    ap.add_argument("--served-model-name", action="append", nargs="+", default=[])
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--load-delay", type=float, default=float(os.environ.get("TB_STANDIN_LOAD_DELAY", "0") or 0))
    return ap.parse_known_args(argv)


def build(argv: list[str], env: dict[str, str] | None = None) -> tuple[Standin, argparse.Namespace, list[str]]:
    a, ignored = parse(argv)
    e = os.environ if env is None else env
    served = [n for group in a.served_model_name for n in group]
    if not served and a.model:
        served = [a.model.rstrip("/").rsplit("/", 1)[-1]]
    key = a.api_key if a.api_key is not None else e.get("VLLM_API_KEY", "")
    return Standin(served, key, a.load_delay), a, ignored


def main(argv: list[str] | None = None) -> int:
    try:
        s, a, ignored = build(sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        print(f"vllm_standin: {exc}", file=sys.stderr)
        return 2
    srv = serve(s, a.host, a.port)
    flags = sum(1 for x in ignored if x.startswith("--"))
    print(f"vllm_standin: serving {s.served} on {a.host}:{a.port} (key required; {flags} vLLM flags ignored)",
          file=sys.stderr, flush=True)  # fmt: skip
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
