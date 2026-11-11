"""Recorded REDCap API exchanges ("cassettes") for the ICD-04 calls (STD-060, CR-062; T-115, D-368).

TrialBox had never talked to a real REDCap: every test ran against the simulator, which answered the way its author
thought REDCap answers (the version call was wrong for that reason). A cassette is what one real REDCap test project
answered to the ICD-04 list, recorded once by ``tools.rc_cassette record`` and replayed in CI on every change:

* :func:`icd04_run` makes the calls in a fixed order (version, project, metadata, events and form-event mapping on a
  longitudinal project, data access groups, the record export, the export with ``dateRangeBegin``, and with
  ``write`` an import with ``forceAutoNumber``) and answers what the client made of each;
* :class:`Recording` is an ``httpx`` transport that keeps each request (its form without the token) and the answer;
* :func:`replay_client` answers each request from a cassette: a request the cassette does not hold fails the test.

The token is never written to a cassette. Only a test project holding synthetic records may be recorded.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx

from rc_bridge.client import RcError, RedcapClient

FORMAT = 1  # the cassette file's own version


def request_key(request: httpx.Request) -> list[list[str]]:
    """A request as the cassette keeps it: its form fields in order, without the token."""
    form = parse_qsl(request.content.decode("utf-8"), keep_blank_values=True)
    return [[k, v] for k, v in sorted(form) if k != "token"]


class Recording(httpx.BaseTransport):
    """Pass each request on to ``inner`` and keep it with its answer."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.exchanges: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        resp = self.inner.handle_request(request)
        body = resp.read()
        self.exchanges.append({"request": request_key(request), "status": resp.status_code,
                               "content_type": resp.headers.get("content-type", ""),
                               "body": body.decode("utf-8", "replace")})  # fmt: skip
        return httpx.Response(resp.status_code, headers={"content-type": resp.headers.get("content-type", "")},
                              content=body)  # fmt: skip


class CassetteMiss(AssertionError):
    """A request the cassette does not hold: the client asks something the recorded REDCap was never asked."""


def replay_client(exchanges: list[dict[str, Any]]) -> httpx.Client:
    """An ``httpx`` client that answers each request from ``exchanges`` (each one once, in any order)."""
    left = list(exchanges)

    def handler(request: httpx.Request) -> httpx.Response:
        key = request_key(request)
        for i, x in enumerate(left):
            if x["request"] == key:
                left.pop(i)
                return httpx.Response(int(x["status"]), headers={"content-type": str(x["content_type"])},
                                      content=str(x["body"]).encode("utf-8"))  # fmt: skip
        raise CassetteMiss(f"the cassette holds no answer to {key}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def icd04_run(c: RedcapClient, since: str = "", write: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """The ICD-04 list against one project, in a fixed order; what the client made of each answer (an error by its
    code). ``write``: rows imported with ``forceAutoNumber`` (only on a test project)."""
    out: dict[str, Any] = {}

    def step(name: str, call: Callable[[], Any]) -> Any:
        try:
            out[name] = call()
        except RcError as exc:
            out[name] = {"error": exc.code}
        return out[name]

    step("version", c.check_version)
    proj = step("project", c.project)
    step("metadata", c.metadata)
    if isinstance(proj, dict) and int(proj.get("is_longitudinal") or 0):
        step("event", c.events)
        step("formEventMapping", c.form_event_mapping)
    step("dag", c.dags)
    step("record", c.records)
    if since:
        step("record_since", lambda: c.records(since=since))
    if write:
        step("import", lambda: c.import_records(write, auto_number=True))
    return out


def save(path: Path, *, version: str, source: str, results: dict[str, Any], exchanges: list[dict[str, Any]],
         since: str = "", write: list[dict[str, str]] | None = None) -> None:  # fmt: skip
    body = {"format": FORMAT, "redcap_version": version, "source": source, "since": since, "write": write or [],
            "results": results, "exchanges": exchanges}  # fmt: skip
    text = json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if '"token"' in text:  # never: request_key drops it; checked again before anything is written
        raise ValueError("a cassette must not hold a token")
    path.write_text(text, encoding="utf-8")


def replay(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the ICD-04 list against the cassette at ``path``: (what the client makes of it now, what it made when
    recorded). Equal when the client still reads that REDCap's answers the same way."""
    body = json.loads(path.read_text(encoding="utf-8"))
    if int(body.get("format") or 0) != FORMAT:
        raise ValueError(f"{path.name}: cassette format {body.get('format')!r} is not {FORMAT}")
    c = RedcapClient("https://redcap.cassette/", "0" * 32, http=replay_client(list(body["exchanges"])))
    return icd04_run(c, str(body.get("since") or ""), list(body.get("write") or []) or None), dict(body["results"])
