"""A FHIR store stand-in over HTTP, run as its own process (E2E P-03): the real loader (``adapter.load_fhir``) and
the real check (``adapter.publish.verify_fhir``) talk to it as to the box's store.

    python tests/fhir_store_stub.py <port file>

It keeps resources by type and id in memory and answers a transaction bundle of PUT and DELETE entries (``POST
/fhir``), a count (``GET /fhir/<Type>?_summary=count``) and the ids, paged (``GET /fhir/<Type>?_elements=id``).
The test steers it (``POST /_control``): ``sleep`` seconds per request, ``drop`` (refs whose DELETE it answers and
does not do), ``kill`` (``{"pid", "type", "after"}``: SIGKILL that process once ``after`` PUTs of ``type`` are in),
``fail_after`` (transactions after that many more are answered 500, nothing written). ``GET /_log`` is every request it
was sent; ``GET /_ids`` what it holds; ``POST /_seed`` puts resources in by hand. Synthetic data only."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

STORE: dict[str, dict[str, dict[str, Any]]] = {}
LOG: list[str] = []
CTL: dict[str, Any] = {"sleep": 0.0, "drop": [], "kill": None, "fail_after": None}
PUTS: dict[str, int] = {}
TX = [0]
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # quiet: the test reads ``/_log``
        pass

    def _answer(self, body: Any, code: int = 200) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> Any:
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/_log":
            with LOCK:
                return self._answer(list(LOG))
        if url.path == "/_ids":
            with LOCK:
                return self._answer({t: sorted(r) for t, r in STORE.items() if r})
        time.sleep(float(CTL["sleep"]))
        rtype = url.path.rstrip("/").rsplit("/", 1)[-1]
        with LOCK:
            LOG.append(f"GET {rtype} {'count' if q.get('_summary') == 'count' else 'ids'}")
            ids = sorted(STORE.get(rtype, {}))
        if q.get("_summary") == "count":
            return self._answer({"resourceType": "Bundle", "type": "searchset", "total": len(ids)})
        size, start = int(q.get("_count") or 1000), int(q.get("_offset") or 0)
        page = {"resourceType": "Bundle", "type": "searchset", "total": len(ids),
                "entry": [{"resource": {"resourceType": rtype, "id": i}} for i in ids[start : start + size]]}  # fmt: skip
        if start + size < len(ids):
            nxt = f"http://{self.headers['Host']}{url.path}?_elements=id&_count={size}&_offset={start + size}"
            page["link"] = [{"relation": "next", "url": nxt}]
        return self._answer(page)

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        body = self._body()
        if url.path == "/_control":
            with LOCK:
                CTL.update(body)
                if body.get("fail_after") is not None:  # counted from now
                    CTL["fail_after"] = TX[0] + int(body["fail_after"])
            return self._answer({})
        if url.path == "/_seed":
            with LOCK:
                for r in body:
                    STORE.setdefault(r["resourceType"], {})[str(r["id"])] = r
            return self._answer({})
        time.sleep(float(CTL["sleep"]))
        entries = body.get("entry") or []
        with LOCK:
            TX[0] += 1
            kinds = sorted({f"{e['request']['method']} {e['request']['url'].split('/')[0]}" for e in entries})
            LOG.append(f"POST {len(entries)} {', '.join(kinds)}")
            if CTL["fail_after"] is not None and TX[0] > int(CTL["fail_after"]):
                return self._answer({"resourceType": "OperationOutcome"}, 500)
            kill = None
            for e in entries:
                rtype, _, rid = e["request"]["url"].partition("/")
                if e["request"]["method"] == "PUT":
                    STORE.setdefault(rtype, {})[rid] = e["resource"]
                    PUTS[rtype] = PUTS.get(rtype, 0) + 1
                    k = CTL["kill"]
                    if k and rtype == k["type"] and PUTS[rtype] >= int(k["after"]):
                        kill = int(k["pid"])
                elif e["request"]["url"] not in CTL["drop"]:
                    STORE.get(rtype, {}).pop(rid, None)
            if kill is not None:  # the loader dies here, with its bundle in: no handler of its runs
                CTL["kill"] = None
                LOG.append(f"KILL {kill}")
                os.kill(kill, signal.SIGKILL)
        return self._answer({"resourceType": "Bundle", "type": "transaction-response"})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port_file = Path(sys.argv[1])
    port_file.with_suffix(".tmp").write_text(str(server.server_address[1]), encoding="utf-8")
    port_file.with_suffix(".tmp").replace(port_file)
    server.serve_forever()


if __name__ == "__main__":
    main()
