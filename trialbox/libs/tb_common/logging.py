"""Structured JSON logging to stdout with a PHI scrubber (SPEC §4, §10.1 "No PHI in logs (pids only)").

T-212d (D-450, PV-10): :func:`setup_logging`, which every TrialBox service runs at start, switches every rule on:
the identifier patterns below, the site's chart-number pattern (``settings.mrn_regex``; the contract's default when
no site configuration is readable, so the rule is never off), and the secrets: a value written after a secret's
name (``token=...``, ``"api_key": "..."``, ``Authorization: Bearer ...``) and every secret value the process itself
holds (the environment variables and ``*_FILE`` files named like a password, key, token or secret).
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import logging
import os
import re
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from tb_common.decode_scrub import decode_then_scrub

_D = "[0-9０-９]"  # ASCII or full-width digits (Japanese forms often use full-width)
_SEP = "[-\\s‐－ー]?"
_PHI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?!\d)"), "[TWID]"),
    # Japan (D-121): マイナンバー (12 digits, 4-4-4), insurer and insured numbers after their label, 〒 postcodes,
    # +81 and domestic phone numbers. Labelled numbers go first so the bare-digit rules do not split them.
    (re.compile(rf"(?:個人番号|マイナンバー)[\s:：]*{_D}{{4}}{_SEP}{_D}{{4}}{_SEP}{_D}{{4}}"), "[MYNUMBER]"),
    (re.compile(rf"(?<!{_D}){_D}{{4}}[-\s‐－]{_D}{{4}}[-\s‐－]{_D}{{4}}(?!{_D})"), "[MYNUMBER]"),
    (re.compile(rf"(?:保険者番号|被保険者番号|記号番号|記号|番号)[\s:：]*(?:{_D}|[・･\-－]){{6,12}}"), "[INSURANCE]"),
    (re.compile(rf"〒[\s]?{_D}{{3}}{_SEP}{_D}{{4}}"), "[POSTCODE]"),
    (re.compile(rf"(?<!{_D})\+81{_SEP}\(?{_D}{{1,4}}\)?{_SEP}{_D}{{1,4}}{_SEP}{_D}{{4}}(?!{_D})"), "[PHONE]"),
    (re.compile(rf"(?<!{_D})[0０][5-9５-９]0{_SEP}{_D}{{4}}{_SEP}{_D}{{4}}(?!{_D})"), "[PHONE]"),
    (re.compile(r"(?<!\d)(?:\+886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\(?0\d{1,2}\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"), "[PHONE]"),
    (re.compile(rf"(?<!{_D})[0０]{_D}{{1,3}}[-‐－]{_D}{{1,4}}[-‐－]{_D}{{4}}(?!{_D})"), "[PHONE]"),
]
_EXTRA_MRN: list[re.Pattern[str]] = []
#: a value written after a secret's name; the name stays, the value goes
_SECRET_LABEL = re.compile(
    r"(?i)((?<![A-Za-z0-9])(?:authorization|x-tb-service-token|service[_-]?token|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"client[_-]?secret|api[_-]?key|apikey|secret|token|password|passwd|pass|pw)"
    r"[\"']?\s*[:=]\s*[\"']?(?:(?:bearer|basic|token)\s+)?)([^\s\"',;&}]{6,})"
)
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
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
    _NAMES.clear()


def register_secret(value: str) -> None:
    """A secret value this process holds: never written to a log line."""
    v = (value or "").strip()
    if len(v) >= MIN_SECRET:
        _SECRET_VALUES.add(v)
        _NAMES.clear()


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


#: LOG-JA (D-927): what a log line holds that the note masker would mask is masked too, its kind in capitals
WITHHELD = "[message withheld: the PHI scrubber failed]"
#: D-927 (the review's MEDIUM-5): a line longer than this is cut to its first and last halves before it is scrubbed
#: (``TB_LOG_SCRUB_MAX_CHARS``): the masker reads about 1 µs a character (a 50 kB traceback, 56 ms), and the
#: formatter holds the handler's lock while it does; what is cut is never written
SCRUB_MAX_ENV = "TB_LOG_SCRUB_MAX_CHARS"


def _scrub_max() -> int:
    from tb_common.config import DECLARED

    try:
        return max(1024, int(os.environ.get(SCRUB_MAX_ENV) or DECLARED[SCRUB_MAX_ENV].default))
    except ValueError:
        return int(DECLARED[SCRUB_MAX_ENV].default)


def _cut(text: str) -> str:
    limit = _scrub_max()
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]} …[{len(text) - 2 * half} characters cut before scrubbing]… {text[-half:]}"


def redact(text: str) -> str:
    """Everything the note masker masks (LOG-JA, D-927), read on the line as written, then Taiwan IDs, Japanese My
    Number / insurance numbers / postcodes, phone numbers, MRN-shaped tokens and secrets (a value after a secret's
    name, a bearer token, a secret value the process holds). Then each line that holds an encoded character (``%40``
    in any number of layers up to eight, ``&#61;``, ``\\u0040``, ``=3D``) is read again decoded, and kept decoded
    and scrubbed when that finds something (H-79, D-1358: the support bundle's decoding, ``tb_common.decode_scrub``).
    A scrubber that fails withholds the message, naming the error's type: never a line it did not scrub."""
    try:
        # decoded first: a rule that reads the encoded text (eight digits of ``%25252536``) would break the encoding
        return _redact(decode_then_scrub(_cut(text), _redact)[0])
    except Exception as exc:  # a log line must never stop the service, nor go out unscrubbed
        return f"{WITHHELD[:-1]} ({type(exc).__name__})]"


#: H-79 (the review's R22-21): how far a value given through ``extra=`` is walked, and how many values one line takes
MAX_DEPTH = 8
MAX_VALUES = 1000
CYCLE = "[withheld: a value that holds itself]"
TOO_MANY = "[withheld: more values than a log line takes]"
MASK = "[SECRET]"  # what a value under a secret's name becomes
#: what a secret's name may hold and still say nothing about the secret: a flag, a count of three digits or fewer
_NOT_A_SECRET = frozenset({"", "true", "false", "yes", "no", "on", "off", "none", "null", MASK.lower()})


def _secret_key(key: str) -> bool:
    """Whether a value under ``key`` is a secret's, by the text rule itself: ``key=<value>`` names a secret when
    :data:`_SECRET_LABEL` finds its name inside ``key`` (``password``, ``db_password``, ``dbPassword``, ``apiKey``)."""
    probe = _CAMEL.sub("_", key) + "=" + "x" * 8
    m = _SECRET_LABEL.search(probe)
    return m is not None and m.start(2) == len(probe) - 8


def _text_of(value: Any) -> str:
    """A value's text form, never trusted: ``str()`` may raise or return what is not a text."""
    try:
        text = str(value)
    except Exception:
        text = None
    return text if isinstance(text, str) else f"<{type(value).__name__}: its text could not be read>"


class _Walk:
    """One log line's walk of its non-text values (H-79): every value becomes JSON of texts that were scrubbed,
    numbers whose text the scrub leaves alone, flags and nulls. Bounded by depth, by the count of values and by
    cycles; a value that cannot be read is withheld alone, the rest of the line is kept."""

    def __init__(self) -> None:
        self.left = MAX_VALUES
        self.path: set[int] = set()

    def key(self, key: Any) -> str:
        return _name(key) if isinstance(key, str) and len(key) <= 64 else redact(_text_of(key))

    def value(self, value: Any, depth: int = 0, *, secret: bool = False) -> Any:
        try:
            return self._value(value, depth, secret)
        except Exception as exc:  # one value that cannot be read is withheld, the line is kept
            return f"{WITHHELD[:-1]} ({type(exc).__name__})]"

    def _value(self, value: Any, depth: int, secret: bool) -> Any:
        self.left -= 1
        if self.left < 0:
            return TOO_MANY
        if value is None or isinstance(value, bool):
            return value
        if secret:
            text = value if isinstance(value, str | int | float) else None
            if text is not None and (str(text).strip().lower() in _NOT_A_SECRET or re.fullmatch(r"\d{1,3}", str(text))):
                return value
            return MASK
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, int | float):
            text = _text_of(value)
            clean = _name(text) if len(text) <= 24 else redact(text)  # a number's text: few, cached
            return value if clean == text else clean
        if depth > MAX_DEPTH:  # deeper than any log field: withheld, not walked
            return WITHHELD
        if isinstance(value, bytes | bytearray | memoryview):
            return redact(bytes(value[: _scrub_max() * 4]).decode("utf-8", "backslashreplace"))
        if isinstance(value, BaseException):
            return redact(f"{type(value).__name__}: {_text_of(value)}")
        pairs = self._pairs(value)
        items = None if pairs is not None else self._items(value)
        if pairs is None and items is None:
            return redact(_text_of(value))  # an object: its text, scrubbed like any other
        if id(value) in self.path:
            return CYCLE
        self.path.add(id(value))
        try:
            if pairs is not None:
                out: dict[str, Any] = {}
                seen: dict[str, int] = {}
                for k, v in itertools.islice(pairs, max(self.left, 0) + 1):
                    raw = k if isinstance(k, str) else _text_of(k)
                    name = _unique(out, self.key(raw), seen)
                    out[name] = self.value(v, depth + 1, secret=_secret_key(raw))
                return out
            return [self.value(v, depth + 1) for v in itertools.islice(items or (), max(self.left, 0) + 1)]
        finally:
            self.path.discard(id(value))

    @staticmethod
    def _pairs(value: Any) -> Any:
        if isinstance(value, Mapping):
            return iter(value.items())
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return ((f.name, getattr(value, f.name, None)) for f in dataclasses.fields(value))
        fields = getattr(value, "_fields", None) if isinstance(value, tuple) else None
        if isinstance(fields, tuple):  # a named tuple
            return zip(fields, value, strict=False)
        dump = getattr(type(value), "model_dump", None)
        if callable(dump) and not isinstance(value, type):
            dumped = value.model_dump()
            return iter(dumped.items()) if isinstance(dumped, Mapping) else None
        return None

    @staticmethod
    def _items(value: Any) -> Any:
        if isinstance(value, list | tuple | set | frozenset):
            return iter(value)
        return None


def _unique(out: Mapping[str, Any], name: str, seen: dict[str, int]) -> str:
    """Two keys the scrub made alike (``[EMAIL]``) both stay: the second gets ``~2`` (``seen`` keeps the last
    number of each name, so a thousand alike keys cost a thousand steps, not a million)."""
    if name not in out:
        return name
    n = seen.get(name, 1) + 1
    while f"{name}~{n}" in out:
        n += 1
    seen[name] = n
    return f"{name}~{n}"


def redact_value(value: Any, depth: int = 0) -> Any:
    """``value`` with every text inside it scrubbed (the review's HIGH-1, then H-79 and R22-21): a mapping's keys and
    values, a list's, tuple's or set's items, a dataclass's or named tuple's fields, an exception's type and text,
    bytes as text, a number whose text the scrub would change, and any other object's text form. A value under a
    secret's name is ``[SECRET]``. Bounded: depth, the count of values, cycles."""
    return _Walk().value(value, depth)


#: logger, level and service names, extra keys and numbers' texts, scrubbed once each (at most 4096 kept; cleared
#: when a secret or the chart-number rule is added). Never a value's text: a value is not kept past its line
_NAMES: dict[str, str] = {}


def _name(text: Any) -> str:
    key = text if isinstance(text, str) else _text_of(text)
    clean = _NAMES.get(key)
    if clean is None:
        clean = redact(key)
        if len(_NAMES) < 4096:
            _NAMES[key] = clean
    return clean


def _redact(text: str) -> str:
    """Every rule reads the line as it was written, and the spans they find are joined and replaced once (the
    review's HIGH-2: applied one after another, a secret's token took the label a name was found by, and the
    masker, run first, could cut a secret value so that its exact match no longer held). A span the secret rules
    found says ``[SECRET]``; else the identifier rule's or the masker's kind."""
    from tb_common.phi_guard import note_spans  # here, not at import: nearly every module imports logging

    found: list[tuple[int, int, int, str]] = []  # (start, end, rank, label): 0 secret, 1 identifier rule, 2 masker
    for v in _SECRET_VALUES:
        at = text.find(v)
        while at >= 0:
            found.append((at, at + len(v), 0, "SECRET"))
            at = text.find(v, at + 1)
    for rx in (_SECRET_LABEL, _BEARER, _URL_PASSWORD):
        for m in rx.finditer(text):
            found.append((m.start(2), m.end(2), 0, "SECRET"))
    for pat, repl in _PHI_PATTERNS:
        for m in pat.finditer(text):
            found.append((m.start(), m.end(), 1, repl.strip("[]")))
    for pat in _EXTRA_MRN:
        for m in pat.finditer(text):
            found.append((m.start(), m.end(), 1, "MRN"))
    for kind, start, end in note_spans(text):
        found.append((start, end, 2, kind.upper()))
    merged: list[list[Any]] = []  # [start, end, rank, label]
    for start, end, rank, label in sorted(f for f in found if f[1] > f[0]):
        if merged and start < merged[-1][1]:
            last = merged[-1]
            last[1] = max(last[1], end)
            if rank < last[2]:
                last[2], last[3] = rank, label
        else:
            merged.append([start, end, rank, label])
    if not merged:
        return text
    out, pos = [], 0
    for start, end, _rank, label in merged:
        out.append(text[pos:start])
        out.append(f"[{label}]")
        pos = end
    out.append(text[pos:])
    return "".join(out)


class JsonFormatter(logging.Formatter):
    """One JSON line per record. Every value that enters the line is scrubbed: the message (with its arguments), the
    logger, level and service names, every ``extra=`` value of any type and its keys (H-79), and the traceback. A
    record the formatter cannot render still gives a line: it says the message was withheld, with the logger and the
    level, never the raw text (H-79, the review's R22-22: an error here went to the error stream with the raw
    arguments)."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        try:
            return self._format(record)
        except Exception as exc:  # never the raw text, never an exception out of the formatter
            return self._withheld(record, exc)

    def _format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": _name(record.levelname),
            "service": _name(self.service),
            "logger": _name(record.name),
            "msg": redact(record.getMessage()),
        }
        walk = _Walk()
        seen: dict[str, int] = {}
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                name = walk.key(key)
                name = name if name == key else _unique(payload, name, seen)
                payload[name] = walk.value(val, secret=_secret_key(key))
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        line = json.dumps(payload, ensure_ascii=False, default=_text_of)
        if not line.isascii():
            try:
                line.encode("utf-8")
            except UnicodeEncodeError:  # a lone surrogate in the record: escaped, so the line can be written
                line = json.dumps(payload, ensure_ascii=True, default=_text_of)
        return line

    def _withheld(self, record: logging.LogRecord, exc: Exception) -> str:
        def safe(read: Any, fallback: str) -> str:
            try:
                text = read()
                return text if isinstance(text, str) and text.isascii() and len(text) <= 200 else fallback
            except Exception:
                return fallback

        return json.dumps(
            {
                "ts": datetime.fromtimestamp(time.time(), tz=UTC).isoformat(timespec="milliseconds"),
                "level": safe(lambda: _name(record.levelname), "[level withheld]"),
                "service": safe(lambda: _name(self.service), "[service withheld]"),
                "logger": safe(lambda: _name(record.name), "[logger withheld]"),
                "msg": f"{WITHHELD[:-1]} ({type(exc).__name__})]",
            },
            ensure_ascii=True,
        )


def setup_logging(service: str, level: str = "INFO") -> logging.Logger:
    """Configure the root logger for JSON output with every scrubber rule on (D-450); idempotent. A masker that
    cannot be loaded stops the start (D-927): every line would otherwise be withheld, with no word why."""
    import importlib

    importlib.import_module("tb_common.phi_guard")  # loaded now, loudly, not at the first line

    site_rule_on()
    register_process_secrets()
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root.addHandler(handler)
    root.setLevel(level.upper())
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
