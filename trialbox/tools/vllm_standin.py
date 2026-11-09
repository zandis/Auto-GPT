"""A strict stand-in for one vLLM server (D-177): the box-install rehearsal runs it where the GPU would be.

It takes vLLM's own command line, so the compose file's ``command:`` for ``llm-service`` and ``llm-verifier`` is used
unchanged, and it is stricter than vLLM where a box goes wrong:

* **Served names.** It answers only the exact ``--served-model-name`` (one or more; the last path part of ``--model``
  when none is given, as vLLM). Any other ``model`` gets vLLM's 404 ``NotFoundError``.
* **Key.** It needs an API key (``--api-key`` or ``VLLM_API_KEY``, as vLLM) and refuses to start without one; every
  ``/v1`` call without ``Authorization: Bearer <key>`` gets 401. ``/health`` is open, as in vLLM.
* **Answers.** The deterministic answers of ``services/llm_stub`` (by the ``X-TB-Prompt-Id`` header the gateway
  forwards); the response's ``model`` is the served name, so the gateway's served-model echo check runs for real.
* **Counts.** ``GET /standin/stats`` (with the key) returns the count of answers by status (200, 400, 401, 404), so a
  rehearsal can assert "no 401 and no 404" on a good box.

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
        self.counts: Counter[int] = Counter()
        self.lock = threading.Lock()

    def count(self, status: int) -> None:
        with self.lock:
            self.counts[status] += 1

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


def make_handler(s: Standin) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "vllm-standin"

        def log_message(self, format: str, *args: Any) -> None:  # one line per call on stderr, never the key
            sys.stderr.write("standin %s\n" % (format % args))

        def _send(self, status: int, payload: dict[str, Any] | None) -> None:
            s.count(status)
            data = json.dumps(payload or {}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _gate(self) -> bool:
            """True when the call may go on; else the 503 (loading) or 401 (key) answer is sent."""
            if time.monotonic() < s.ready_at:
                self._send(503, _error("the model is loading", "ServiceUnavailableError", 503))
                return False
            if not s.authorised(self.headers.get("Authorization")):
                self._send(401, {"error": "Unauthorized"})
                return False
            return True

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                ok = time.monotonic() >= s.ready_at
                self._send(200 if ok else 503, {} if ok else _error("loading", "ServiceUnavailableError", 503))
            elif path in ("/v1/models", "/standin/stats"):
                if self._gate():
                    if path == "/v1/models":
                        self._send(200, s.models())
                    else:
                        with s.lock:
                            counts = {str(k): v for k, v in sorted(s.counts.items())}
                        self._send(200, {"served": s.served, "counts": counts})
            else:
                self._send(404, {"detail": "Not Found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if path not in ("/v1/chat/completions", "/v1/completions"):
                self._send(404, {"detail": "Not Found"})
                return
            if not self._gate():
                return
            try:
                body = json.loads(raw or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("body is not an object")
            except ValueError as exc:
                self._send(400, _error(f"bad JSON: {exc}", "BadRequestError", 400))
                return
            if path == "/v1/completions":  # the box never calls it; served-name and key rules still apply
                if body.get("model") not in s.served:
                    self._send(404, _error(f"The model `{body.get('model')}` does not exist.", "NotFoundError", 404))
                else:
                    self._send(400, _error("the stand-in answers chat completions only", "BadRequestError", 400))
                return
            status, payload = s.complete(body, self.headers.get("X-TB-Prompt-Id", ""))
            self._send(status, payload)

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
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(s))
    flags = sum(1 for x in ignored if x.startswith("--"))
    print(f"vllm_standin: serving {s.served} on {a.host}:{a.port} (key required; {flags} vLLM flags ignored)",
          file=sys.stderr, flush=True)  # fmt: skip
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
