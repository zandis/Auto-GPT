"""A plain SMTP sink for the box-install rehearsal (D-176): it accepts every message, keeps none, and prints one line
per message (sender, recipients, size) so the rehearsal can see that SCREEN mailed its results. Python standard library
only. It answers STARTTLS with 502, so the rehearsal turns STARTTLS off for its mail-gateway. Never on a real box.

    python -m tools.rehearse_box.smtp_sink [--host 0.0.0.0] [--port 587]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import socketserver
import sys
import threading
from typing import Any


class Sink(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr: tuple[str, int]) -> None:
        super().__init__(addr, _Handler)
        self.lock = threading.Lock()
        self.messages: list[dict[str, Any]] = []

    def record(self, msg: dict[str, Any]) -> None:
        with self.lock:
            self.messages.append(msg)
            n = len(self.messages)
        print(json.dumps({"smtp_sink": n, **msg}), flush=True)


class _Handler(socketserver.StreamRequestHandler):
    server: Sink

    def _say(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode("ascii"))
        self.wfile.flush()

    def handle(self) -> None:
        with contextlib.suppress(ConnectionError):  # the healthcheck connects and goes
            self._session()

    def _session(self) -> None:
        self._say("220 rehearsal SMTP sink")
        sender, rcpts = "", list[str]()
        while raw := self.rfile.readline(65536):
            verb = raw.decode("utf-8", "replace").strip().split(" ", 1)[0].upper()
            arg = raw.decode("utf-8", "replace").strip()[len(verb) :].strip()
            if verb in ("EHLO", "HELO"):
                self._say("250 rehearsal-sink")
            elif verb == "MAIL":
                sender, rcpts = arg.partition(":")[2].strip(), []
                self._say("250 OK")
            elif verb == "RCPT":
                rcpts.append(arg.partition(":")[2].strip())
                self._say("250 OK")
            elif verb == "DATA":
                self._say("354 end with <CRLF>.<CRLF>")
                size = 0
                while (line := self.rfile.readline(1 << 20)) and line.rstrip(b"\r\n") != b".":
                    size += len(line)
                self.server.record({"from": sender, "to": rcpts, "bytes": size})
                self._say("250 OK")
            elif verb in ("RSET", "NOOP"):
                self._say("250 OK")
            elif verb == "QUIT":
                self._say("221 bye")
                return
            else:  # STARTTLS, AUTH and the rest
                self._say("502 not implemented")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="smtp_sink", allow_abbrev=False)
    ap.add_argument("--host", default="0.0.0.0")  # inside its own container
    ap.add_argument("--port", type=int, default=587)
    a = ap.parse_args(argv)
    with Sink((a.host, a.port)) as srv:
        print(f"rehearsal SMTP sink on {a.host}:{a.port}", file=sys.stderr, flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
