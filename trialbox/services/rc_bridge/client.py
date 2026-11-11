"""REDCap API client (ICD-04 R1-R3, R7, R8 reads; the record import for the write-back, D-123) over httpx.

The ICD names PyCap as the client; PyCap is not a dependency of the build, and the five read methods are one form
post each, so the connector posts the documented form fields itself (D-109). Errors map to the ICD register:
403 -> RC-TOKEN, 429/503 -> RC-RATE, any other error -> RC-UPSTREAM, unsupported major version -> RC-VERSION. The
token is never logged or put in an error message.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, ClassVar

import httpx

SUPPORTED_MAJORS = (14, 15, 16)  # LTS lines the connector is tested on; the pilot sites run 16.x (FR-RC-14)
TOKEN_RE = re.compile(r"^[0-9A-F]{32}$")
INPROC_PREFIX = "inproc://"  # demo and test only: a URL served by an in-process ASGI app (the simulator)
_LOCAL: dict[str, Callable[[], httpx.Client]] = {}


class RcError(RuntimeError):
    """An ICD-04 error: ``code`` from the register, ``status`` the HTTP status TrialBox answers with."""

    STATUS: ClassVar[dict[str, int]] = {
        "RC-TOKEN": 409,
        "RC-VERSION": 409,
        "RC-UPSTREAM": 502,
        "RC-RATE": 503,
        "RC-FORBIDDEN": 403,
    }

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = self.STATUS.get(code, 409)


def register_local(url: str, factory: Callable[[], httpx.Client], replace: bool = True) -> None:
    """Route an ``inproc://`` base URL to an in-process client (the demo's and tests' simulator). ``replace=False``
    keeps a route someone registered first (a demo's own fresh simulator)."""
    if not url.startswith(INPROC_PREFIX):
        raise ValueError("only inproc:// URLs are routed in-process")
    if replace or url.rstrip("/") not in _LOCAL:
        _LOCAL[url.rstrip("/")] = factory


def check_token(token: str) -> str:
    tok = token.strip().upper()
    if not TOKEN_RE.match(tok):
        raise RcError("RC-TOKEN", "a REDCap API token is 32 hexadecimal characters")
    return tok


def api_url(base: str) -> str:
    """The ``/api/`` endpoint of a REDCap base URL (``https://redcap.example/`` or ``.../api/``). Only ``https://``:
    the token travels in every request body, so plain ``http://`` is refused (SEC-14, T-115). ``inproc://`` is the
    demo's and tests' in-process simulator."""
    b = base.strip()
    if not (b.lower().startswith("https://") or b.startswith(INPROC_PREFIX)):
        raise RcError("RC-UPSTREAM", "the REDCap URL must start with https://")
    b = b.rstrip("/")
    return b if b.endswith("/api") else b + "/api"


def major_of(version: str) -> int:
    m = re.match(r"^\s*(\d+)\.", version or "")
    if not m:
        raise RcError("RC-VERSION", f"REDCap reported an unreadable version {version!r}")
    return int(m.group(1))


class RedcapClient:
    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None, timeout: float = 10.0) -> None:
        self.url = api_url(base_url)
        self.token = check_token(token)
        self._own = http is None
        if http is None:
            key = self.url[: -len("/api")]
            if key.startswith(INPROC_PREFIX):
                if key not in _LOCAL:
                    raise RcError("RC-UPSTREAM", f"no in-process REDCap is registered at {key}")
                http = _LOCAL[key]()
                self.url = "/api/"
            else:
                http = httpx.Client(timeout=timeout)
        self.http = http

    def close(self) -> None:
        if self._own:
            self.http.close()

    def __enter__(self) -> RedcapClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _send(self, content: str, extra: dict[str, str] | None = None) -> httpx.Response:
        """One API call; the answer when REDCap says 200, an :class:`RcError` otherwise."""
        data = {"token": self.token, "content": content, "format": "json", "returnFormat": "json", **(extra or {})}
        url = self.url if self.url.endswith("/") else self.url + "/"
        try:
            resp = self.http.post(url, data=data)
        except httpx.HTTPError as exc:
            raise RcError("RC-UPSTREAM", f"REDCap did not answer ({type(exc).__name__})") from exc
        if resp.status_code == 200:
            return resp
        if resp.status_code == 403:
            raise RcError("RC-TOKEN", "REDCap refused the token (no API rights for this project)")
        if resp.status_code in (429, 503):
            raise RcError("RC-RATE", "REDCap's API rate limit was reached; try again later")
        try:
            msg = str(resp.json().get("error") or "")
        except (ValueError, AttributeError):
            msg = ""
        raise RcError("RC-UPSTREAM", f"REDCap returned {resp.status_code}" + (f": {msg[:200]}" if msg else ""))

    def _post(self, content: str, extra: dict[str, str] | None = None) -> Any:
        resp = self._send(content, extra)
        try:
            return resp.json()
        except ValueError as exc:
            raise RcError("RC-UPSTREAM", "REDCap answered with something that is not JSON") from exc

    # ------------------------------------------------------------------ ICD-04 R1-R3, R7, R8
    def version(self) -> str:
        """REDCap answers ``content=version`` with plain text (``16.0.8``), whatever the format asked (STD-060,
        D-281); a JSON string (``"16.0.8"``) is read too."""
        return self._send("version").text.strip().strip('"').strip()

    def check_version(self) -> str:
        v = self.version()
        if major_of(v) not in SUPPORTED_MAJORS:
            raise RcError(
                "RC-VERSION", f"REDCap {v} is not a supported version ({', '.join(map(str, SUPPORTED_MAJORS))}.x)"
            )
        return v

    def project(self) -> dict[str, Any]:
        out = self._post("project")
        if not isinstance(out, dict):
            raise RcError("RC-UPSTREAM", "project info is not an object")
        return out

    def metadata(self) -> list[dict[str, Any]]:
        out = self._post("metadata")
        if not isinstance(out, list):
            raise RcError("RC-UPSTREAM", "the data dictionary is not a list")
        return [dict(m) for m in out]

    def dags(self) -> list[dict[str, Any]]:
        out = self._post("dag")
        return [dict(d) for d in out] if isinstance(out, list) else []

    def events(self) -> list[dict[str, Any]]:
        """A longitudinal project's events (arm, unique name, ``day_offset``, ``offset_min``, ``offset_max``)."""
        out = self._post("event")
        return [dict(e) for e in out] if isinstance(out, list) else []

    def form_event_mapping(self) -> list[dict[str, Any]]:
        """A longitudinal project's instrument designations: ``{arm_num, unique_event_name, form}`` per pair."""
        out = self._post("formEventMapping")
        return [dict(m) for m in out] if isinstance(out, list) else []

    def records(
        self,
        fields: list[str] | None = None,
        events: list[str] | None = None,
        since: str | None = None,
        records: list[str] | None = None,
        dags: bool = False,
    ) -> list[dict[str, Any]]:
        extra: dict[str, str] = {"type": "flat", "rawOrLabel": "raw", "rawOrLabelHeaders": "raw"}
        for name, vals in (("fields", fields), ("events", events), ("records", records)):
            for i, v in enumerate(vals or []):
                extra[f"{name}[{i}]"] = v
        if since:
            extra["dateRangeBegin"] = since
        if dags:
            extra["exportDataAccessGroups"] = "true"
        out = self._post("record", extra)
        if not isinstance(out, list):
            raise RcError("RC-UPSTREAM", "the record export is not a list")
        return [dict(r) for r in out]

    # ------------------------------------------------------------------ import (write-back, D-123)
    def import_records(self, rows: list[dict[str, str]], auto_number: bool = False) -> list[str]:
        """Import flat rows with ``overwriteBehavior=normal`` (a blank never erases a value). Returns the record ids
        written; with ``auto_number`` REDCap names new records itself and the ids are the names it gave, in order."""
        if not rows:
            return []
        import json

        extra = {
            "type": "flat",
            "overwriteBehavior": "normal",
            "forceAutoNumber": "true" if auto_number else "false",
            "returnContent": "auto_ids" if auto_number else "ids",
            "data": json.dumps(rows, ensure_ascii=False),
        }
        out = self._post("record", extra)
        if not isinstance(out, list):
            raise RcError("RC-UPSTREAM", "the record import did not answer with the record ids")
        if auto_number:  # "new_id,given_name" pairs
            return [str(x).split(",", 1)[0] for x in out]
        return [str(x) for x in out]
