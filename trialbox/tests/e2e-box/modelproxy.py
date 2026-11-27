"""The card-0 forwarder for one of the box's model servers (e2e-box only, test VM: no GPU in a VM). Not a stand-in: every
answer is the host's served pinned model's (same image, weights, served names and options as the box's pin).

    modelproxy.py http://10.0.2.2:PORT        (in the model server's container, from the site's host-models.yml)

A /v1 call must carry the box's own key (``VLLM_API_KEY``, 401 otherwise, as vLLM does); it goes on with the host
server's key instead (``/hostkey``, a root-only ``VLLM_API_KEY=...`` file). Neither key is logged."""

import http.client
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UP = urllib.parse.urlparse(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:1")


def host_key(path: str = "/hostkey") -> str:
    """The host server's key from a ``VLLM_API_KEY=...`` line (or a bare key)."""
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip().split("=", 1)[-1]


def allowed(path: str, auth: str, mine: str) -> bool:
    """A /v1 call passes only with the box's own non-empty key; health and the rest need none."""
    return not path.startswith("/v1") or (bool(mine) and auth == f"Bearer {mine}")


class Forward(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def go(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else None
        h = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection", "authorization")}
        if not allowed(self.path, self.headers.get("authorization", ""), os.environ.get("VLLM_API_KEY", "")):
            self.send_response(401)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        if self.path.startswith("/v1"):
            h["Authorization"] = f"Bearer {host_key()}"
        c = http.client.HTTPConnection(UP.hostname or "", UP.port, timeout=900)
        c.request(self.command, self.path, body, h)
        r = c.getresponse()
        data = r.read()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                self.send_header(k, v)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = go

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Forward).serve_forever()
