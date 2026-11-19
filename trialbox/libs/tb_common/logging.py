"""Structured JSON logging to stdout with a PHI scrubber (SPEC §4, §10.1 "No PHI in logs (pids only)").

T-212d (D-450, PV-10): :func:`setup_logging`, which every TrialBox service runs at start, switches every rule on:
the privacy guard's identifier rules (10C-1c: ``tb_common.phi_guard``, every language it knows; this module has no
identifier pattern of its own), the site's chart-number pattern (``settings.mrn_regex``; the contract's default when
no site configuration is readable, so the rule is never off), and the secrets: a value written after a secret's
name (``token=...``, ``"api_key": "..."``, ``Authorization: Bearer ...``) and every secret value the process itself
holds (the environment variables and ``*_FILE`` files named like a password, key, token or secret).

The scrubber is the second line of defence: patient content is not logged at all (SPEC NFR-72, "Logs are structured
JSON and PHI-free"; pids, counts and kinds only). It runs in the one handler every service writes through (the root
logger's, so third-party libraries' loggers too), on the message with its arguments, the extra fields, the exception
and its traceback; a record it cannot scrub within :data:`SCRUB_BUDGET_S` is written as "scrub failed", never as is.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import warnings
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

#: 10C-1c: the identifier rules are the privacy guard's (``tb_common.phi_guard.note_spans``: names, phone numbers,
#: chart, ID and insurance numbers, dates of birth, addresses, email addresses, bed and room numbers, in Traditional
#: Chinese, Japanese and English), the spans the note masker masks and the check before a model call refuses. This
#: module holds no identifier pattern of its own; it only names what the guard found (:func:`_token`). The guard is
#: imported on the first record scrubbed (about 0.2 s of regular expressions), not when this module is.
_GUARD: Any = None
#: the longest text of one field that is scrubbed; the rest is cut and not logged (the guard is linear in the length:
#: at most about 2.5 microseconds a character on the adversarial inputs of its own tests, so 16k characters take at
#: most about 40 ms)
MAX_FIELD = 16384
#: the time one record may take to scrub; a record over it is replaced by :func:`failed_line`, never written unscrubbed
SCRUB_BUDGET_S = 0.25
_EXTRA_MRN: list[re.Pattern[str]] = []
#: a value written after a secret's name; the name stays, the value goes
_SECRET_LABEL = re.compile(
    r"(?i)((?<![A-Za-z0-9])(?:authorization|x-tb-service-token|service[_-]?token|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"client[_-]?secret|api[_-]?key|apikey|secret|token|password|passwd|pass|pw)"
    r"[\"']?\s*[:=]\s*[\"']?(?:(?:bearer|basic|token)\s+)?)([^\s\"',;&}]{6,})"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._~+/=-]{12,})")
_URL_PASSWORD = re.compile(r"(://[^:/\s@]+:)([^@\s/]+)@")  # postgresql://user:password@db
_SECRET_NAME = re.compile(r"PASS|KEY|TOKEN|SECRET|_PW_|_PW$")
_SECRET_VALUES: set[str] = set()
MIN_SECRET = 8  # shorter values are not registered: they would scrub ordinary words

_RESERVED = set(vars(logging.LogRecord("x", 0, "x", 0, "", None, None))) | {"message", "asctime"}


def set_mrn_regex(pattern: str) -> None:
    """Register the site MRN pattern (from settings.mrn_regex) for scrubbing; anchors are removed."""
    body = pattern.strip("^$")
    _EXTRA_MRN.clear()
    _EXTRA_MRN.append(re.compile(rf"(?<![0-9A-Za-z]){body}(?![0-9A-Za-z])"))


def register_secret(value: str) -> None:
    """A secret value this process holds: never written to a log line."""
    v = (value or "").strip()
    if len(v) >= MIN_SECRET:
        _SECRET_VALUES.add(v)


def register_process_secrets(env: Mapping[str, str] | None = None) -> int:
    """Register every secret the process holds: environment variables named like a password, key, token or secret,
    and the files their ``*_FILE`` variables name (read once, at most 64 KiB). Returns how many were registered."""
    e = os.environ if env is None else env
    before = len(_SECRET_VALUES)
    for name, value in e.items():
        if not _SECRET_NAME.search(name.upper()) or not value:
            continue
        if name.upper().endswith("_FILE"):
            try:
                with open(value, encoding="utf-8", errors="replace") as fh:
                    text = fh.read(65536)
            except OSError:
                continue
            for line in text.splitlines():
                register_secret(line.split("=", 1)[1] if "=" in line and not line.startswith("-") else line)
        elif not value.startswith(("/", "./")):  # a path, not a secret
            register_secret(value)
    return len(_SECRET_VALUES) - before


def site_rule_on() -> str:
    """Switch the chart-number rule on (PV-10): the site's ``settings.mrn_regex``, else the contract's default."""
    pattern: str | None = None
    try:
        from tb_common.phi_guard import site_mrn_regex

        pattern = site_mrn_regex()
    except Exception:  # a broken configuration must not stop logging
        pattern = None
    if not pattern:
        from tb_contracts.generated.models import Settings

        pattern = str(Settings.model_fields["mrn_regex"].default)
    set_mrn_regex(pattern)
    return pattern


def _guard() -> Any:
    global _GUARD
    if _GUARD is None:
        from tb_common import phi_guard

        _GUARD = phi_guard
    return _GUARD


def _token(kind: str, text: str, s: int, e: int) -> str:
    """The name a span is replaced by: the guard's kind, with the older names of the log scrubber kept where the guard's
    own definitions tell them apart (a Taiwan ID, twelve digits, a number after an insurance or My Number label, a
    postal code after 〒). A name only: what is replaced is decided by the guard alone."""
    pg, before = _guard(), text[max(0, s - 8) : s]
    if kind == "id":
        value = text[s:e]
        if pg.TW_ID.fullmatch(value):
            return "[TWID]"
        if pg.TWELVE_DIGITS_ANY.fullmatch(value) or "個人番号" in before or "マイナンバー" in before:
            return "[MYNUMBER]"
        if "保険" in before:
            return "[INSURANCE]"
    if kind == "address" and ("〒" in before[-2:] or "郵便" in before):
        return "[POSTCODE]"
    return f"[{kind.upper()}]"


def scrub_identifiers(text: str, mrn: re.Pattern[str] | None = None) -> tuple[str, int]:
    """Every span the guard finds (and the site's chart-number pattern ``mrn``) replaced by its name; the text and the
    number of spans replaced."""
    if not text:
        return text, 0
    found = list(_guard().note_spans(text))
    if mrn is not None:
        found.extend(("mrn", m.start(), m.end()) for m in mrn.finditer(text))
    if not found:
        return text, 0
    merged: list[tuple[str, int, int]] = []
    for kind, s, e in sorted(found, key=lambda f: (f[1], -f[2])):
        if merged and s < merged[-1][2]:
            merged[-1] = (merged[-1][0], merged[-1][1], max(merged[-1][2], e))
        elif e > s:
            merged.append((kind, s, e))
    out, pos = [], 0
    for kind, s, e in merged:
        out += [text[pos:s], _token(kind, text, s, e)]
        pos = e
    out.append(text[pos:])
    return "".join(out), len(merged)


def redact_secrets(text: str) -> str:
    """A value after a secret's name, a bearer token, a URL's password, a secret value the process holds."""
    for v in _SECRET_VALUES:
        if v in text:
            text = text.replace(v, "[SECRET]")
    text = _SECRET_LABEL.sub(lambda m: m.group(1) + "[SECRET]", text)
    text = _BEARER.sub(lambda m: m.group(1) + " [SECRET]", text)
    return _URL_PASSWORD.sub(lambda m: m.group(1) + "[SECRET]@", text)


def redact(text: str) -> str:
    """Secrets (:func:`redact_secrets`), then every identifier the privacy guard finds and the site's chart number
    (:func:`scrub_identifiers`)."""
    return scrub_identifiers(redact_secrets(text), _EXTRA_MRN[0] if _EXTRA_MRN else None)[0]


def _cut(text: str, keep_end: bool = False) -> str:
    """At most :data:`MAX_FIELD` characters, cut at a line break or a space so no word is split; a traceback keeps its
    end (the exception), anything else its start."""
    if len(text) <= MAX_FIELD:
        return text
    if keep_end:
        part = text[-MAX_FIELD:]
        i = max(part.find("\n"), 0) if "\n" in part[:2048] else max(part.find(" "), 0)
        return f"[cut: {len(text) - len(part) + i} characters not logged]" + part[i:]
    part = text[:MAX_FIELD]
    i = part.rfind("\n", MAX_FIELD - 2048)
    i = i if i > 0 else max(part.rfind(" "), 0) or MAX_FIELD
    return part[:i] + f"[cut: {len(text) - i} characters not logged]"


TRACE_FRAMES = 30  # of each error of the chain, so that one line of the log stays a line
TRACE_CHAIN = 5


def error_trace(exc: BaseException) -> str:
    """An error without its own text (D-557): the frames it passed (file, line, function, the line of code) and its
    type, then those of the errors it came from. 10C-1c: what the formatter writes for every exception of a record,
    ``log.exception`` and ``exc_info=True`` included: an error's text quotes what its author put in it (a validation
    error prints its input, a database error its values), which is patient content the scrubber cannot know."""
    parts: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(parts) < TRACE_CHAIN:
        seen.add(id(cur))
        frames = "".join(traceback.format_tb(cur.__traceback__, limit=-TRACE_FRAMES))  # the last ones: where it broke
        parts.append(f"{frames}{type(cur).__name__}")
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    return "\n-- raised while handling --\n".join(parts)


class _Overrun(Exception):
    pass


def _scrub_value(val: Any, deadline: float) -> Any:
    """A field of the record scrubbed: text, and the text inside a dict, list or tuple (ENG-008); numbers and other
    values as they are."""
    if time.perf_counter() > deadline:
        raise _Overrun
    if isinstance(val, str):
        out = redact(_cut(val))
        if time.perf_counter() > deadline:
            raise _Overrun
        return out
    if isinstance(val, Mapping):
        return {redact(str(k)): _scrub_value(v, deadline) for k, v in val.items()}
    if isinstance(val, list | tuple | set | frozenset):
        return [_scrub_value(v, deadline) for v in val]
    if isinstance(val, int | float | bool) or val is None:
        return val
    return _scrub_value(str(val), deadline)


def failed_line(service: str, record: logging.LogRecord) -> str:
    """What is written instead of a record that could not be scrubbed in time or at all: its time, level and logger
    and "scrub failed", nothing of its text."""
    return json.dumps(
        {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": service,
            "logger": record.name,
            "msg": "scrub failed",
        },
        ensure_ascii=False,
    )


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        """The record as one JSON line, every text in it scrubbed: the message with its arguments, the extra fields
        (inside dicts and lists too), the exception with its traceback and the stack. A record that raises while it
        is formatted or scrubbed, or takes more than :data:`SCRUB_BUDGET_S`, is written as :func:`failed_line`."""
        deadline = time.perf_counter() + SCRUB_BUDGET_S
        try:
            payload: dict[str, Any] = {
                "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "service": self.service,
                "logger": record.name,
                "msg": _scrub_value(record.getMessage(), deadline),
            }
            for key, val in record.__dict__.items():
                if key not in _RESERVED and not key.startswith("_"):
                    payload[key] = _scrub_value(val, deadline)
            if record.exc_info and record.exc_info[1] is not None:  # the type and the frames, never the text (D-557)
                payload["exc"] = redact(_cut(error_trace(record.exc_info[1]), keep_end=True))
            if record.stack_info:
                payload["stack"] = redact(_cut(self.formatStack(record.stack_info), keep_end=True))
            if time.perf_counter() > deadline:
                raise _Overrun
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:  # an overrun, a guard error, a message whose arguments do not format: never the raw text
            return failed_line(self.service, record)


def _log_warning(message: Warning | str, category: type[Warning], filename: str, lineno: int, *_a: Any) -> None:
    """A warning as its category and place: its text can quote a value (a serializer warning prints the field's)."""
    logging.getLogger("py.warnings").warning("%s at %s:%d", category.__name__, filename, lineno)


def _log_uncaught(kind: type[BaseException], value: BaseException, tb: Any) -> None:
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, value, tb)
        return
    logging.getLogger("uncaught").critical("uncaught %s", kind.__name__, exc_info=(kind, value, tb))


def _log_uncaught_thread(args: threading.ExceptHookArgs) -> None:
    if args.exc_value is not None:
        exc = (args.exc_type, args.exc_value, args.exc_traceback)
        logging.getLogger("uncaught").critical("uncaught %s in a thread", args.exc_type.__name__, exc_info=exc)


def setup_logging(service: str, level: str = "INFO") -> logging.Logger:
    """Configure the root logger for JSON output with every scrubber rule on (D-450); idempotent."""
    site_rule_on()
    register_process_secrets()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root.addHandler(handler)
    root.setLevel(level.upper())
    # 10C-1c: an uncaught exception and a warning go through the scrubber too, not straight to stderr
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_thread
    warnings.showwarning = _log_warning
    for noisy in ("httpx", "httpcore", "urllib3", "matplotlib", "fontTools", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # requests are logged by our middleware
    return logging.getLogger(service)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
