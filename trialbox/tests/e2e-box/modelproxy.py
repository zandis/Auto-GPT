"""A forwarding stand-in for one of the box's model servers (e2e-box only): every request goes on unchanged, headers
included, to the host's served model named on the command line (``modelproxy.py http://10.0.2.2:PORT``)."""

import http.client
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UP = urllib.parse.urlparse(sys.argv[1])


class Forward(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def go(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else None
        c = http.client.HTTPConnection(UP.hostname or "", UP.port, timeout=900)
        c.request(
            self.command,
            self.path,
            body,
            {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")},
        )
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
