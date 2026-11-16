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
from tb_common.http import EgressRefused

# REDCap majors the connector accepts (FR-RC-14). Tested only against rc_sim so far: no real REDCap instance yet;
# each site's version is recorded at go-live (RUNBOOK §6, DEP-026, D-393)
SUPPORTED_MAJORS = (13, 14, 15, 16, 17)  # D-818: 17 on a real instance; RC13-F (D-852): 13 (13.7.23, R1-R9 and ICD-04)
TOKEN_RE = re.compile(r"^[0-9A-F]{32}$")
INPROC_PREFIX = "inproc://"  # demo and test only: a URL served by an in-process ASGI app (the simulator)
_LOCAL: dict[str, Callable[[], httpx.Client]] = {}


_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]*")  # a REDCap variable name
# (what REDCap's text holds, what the box says): the first that matches. A list of field names is given back as
# names; nothing else of REDCap's text is
_KINDS: tuple[tuple[str, str], ...] = (
    ("is locked", "a form of the record is locked"),  # NEW-EDC-7: REDCap's exact sentence is read on our instance (R3)
    # CGRD-B2 (D-818): the same refusals from a REDCap whose interface is Traditional Chinese (its language file's
    # words, seen on a real instance), each beside its English marker's kind
    ("已上鎖", "a form of the record is locked"),
    ("請先解鎖", "a form of the record is locked"),
    ("could not be validated", "a value does not fit its field's validation"),
    ("格式錯誤，無法被驗證", "a value does not fit its field's validation"),
    ("非有效的類別", "a value does not fit its field's validation"),
    ("無效的日期格式", "a value does not fit its field's validation"),
    # the lifecycle's schedule reads the word "classic" in this message (orchestrator/lifecycle_api.py)
    ("classic project", "the project is classic: it has no arms or events"),
    ("fields were not found in the project", "fields that are not in the project"),
    ("不存在專案內", "fields that are not in the project"),
    ("not designated for event", "a field is not on an instrument of the event"),
    # RC13-A (D-847): REDCap 13.7's sentence on a bad repeat instance names the event first, so it is read first
    ("redcap_repeat_instance", "a repeating instrument or its instance number is not valid"),
    ("event name", "the event is missing or is not an event of the project"),
    ("redcap_event_name", "the event is missing or is not an event of the project"),
    ("repeat", "a repeating instrument or its instance number is not valid"),
    # RC13-A (D-847): a write to another group's record, before the group's own kind
    ("not belong to your data access group", "a record belongs to another data access group"),
    ("data access group", "the data access group is not valid"),
    ("record identifier", "the record identifier field is missing"),
    ("not in a valid format", "the import is not in a valid format"),
    # RC13-A (D-847): REDCap 13.7's English sentences, seen on the private 13.7 instance (D-521)
    ("invalid date format", "a value does not fit its field's validation"),
    ("not a valid category", "a value does not fit its field's validation"),
    ("record id field", "the record identifier field is missing"),
    ("not formatted correctly", "the import is not in a valid format"),
)
_UNKNOWN_KIND = "REDCap's own text is not shown: it can quote a record's value"
_MAX_NAMES = 20  # field names given back from one error (a longer list says no more to the person reading it)


def error_kind(text: str) -> str:
    """The kind of a REDCap error, in the box's own words; REDCap's text itself is never returned."""
    low = text.lower()
    for marker, kind in _KINDS:
        if marker not in low:
            continue
        if marker in ("fields were not found in the project", "不存在專案內"):
            sep = ":" if ":" in text else "："  # a Chinese sentence lists after a full-width colon
            listed = text.split(sep, 1)[1] if sep in text else ""
            names = [n.strip() for n in listed.split(",") if _FIELD_NAME.fullmatch(n.strip())]
            return kind + (": " + ", ".join(names[:_MAX_NAMES]) if names else "")
        return kind
    return _UNKNOWN_KIND


class RcError(RuntimeError):
    """An ICD-04 error: ``code`` from the register, ``status`` the HTTP status TrialBox answers with. ``refused``
    (NEW-EDC-7): REDCap answered and said no (HTTP 400 with its error), so nothing of the call applied; a call
    REDCap did not answer, or answered with a server error, may have applied and is not ``refused``."""

    STATUS: ClassVar[dict[str, int]] = {
        "RC-TOKEN": 409,
        "RC-VERSION": 409,
        "RC-UPSTREAM": 502,
        "RC-RATE": 503,
        "RC-FORBIDDEN": 403,
    }

    def __init__(self, code: str, message: str, refused: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.refused = refused
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
            else:  # T-212d (D-450): the URL an administrator typed goes through the SSRF guard
                from tb_common.http import guarded_client

                http = guarded_client(timeout=timeout)
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
        except EgressRefused as exc:
            raise RcError("RC-UPSTREAM", f"the REDCap address is not allowed ({exc.reason}): {exc.host}") from exc
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
        # REDCap's text is not passed on: an import error quotes the record, the field and the value it refused, and
        # this message reaches the set-up page and the stored read log (D-555). The kind of error is said instead
        raise RcError("RC-UPSTREAM", f"REDCap returned {resp.status_code}" + (f": {error_kind(msg)}" if msg else ""),
                      refused=resp.status_code == 400 and bool(msg))  # fmt: skip

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

    def repeating_forms_events(self) -> list[dict[str, Any]]:
        """The project's repeating instruments and events (``event_name`` blank in a classic project, ``form_name``
        blank for a whole repeating event); T-302b."""
        out = self._post("repeatingFormsEvents")
        if not isinstance(out, list):
            raise RcError("RC-UPSTREAM", "the repeating instruments and events are not a list")
        return [dict(r) for r in out]

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
    def import_records(self, rows: list[dict[str, str]], auto_number: bool = False, erase: bool = False) -> list[str]:
        """Import flat rows with ``overwriteBehavior=normal`` (a blank never erases a value). Returns the record ids
        written; with ``auto_number`` REDCap names new records itself and the ids are the names it gave, in order.
        ``erase`` (T-302b, the EDC's erase of a hidden value it wrote): ``overwriteBehavior=overwrite``, so a blank
        erases; the caller sends only the fields it erases."""
        if not rows:
            return []
        import json

        extra = {
            "type": "flat",
            "overwriteBehavior": "overwrite" if erase else "normal",
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
