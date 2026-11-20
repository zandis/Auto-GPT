"""Structured JSON logging to stdout with a PHI scrubber (SPEC §4, §10.1 "No PHI in logs (pids only)").

T-212d (D-450, PV-10): :func:`setup_logging`, which every TrialBox service runs at start, switches every rule on:
the identifier patterns below, the site's chart-number pattern (``settings.mrn_regex``; the contract's default when
no site configuration is readable, so the rule is never off), and the secrets: a value written after a secret's
name (``token=...``, ``"api_key": "..."``, ``Authorization: Bearer ...``) and every secret value the process itself
holds (the environment variables and ``*_FILE`` files named like a password, key, token or secret).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

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


#: LOG-JA (D-927): what a log line holds that the note masker would mask is masked too, its kind in capitals
WITHHELD = "[message withheld: the PHI scrubber failed]"
#: A line longer than this is withheld before scrubbing: its ends can depend on a name cue in the middle
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
    # A cut can separate a name from its title or its first mention. Neither end
    # can be safely released without analysing the omitted text.
    return f"[{len(text)} characters cut before scrubbing]"


def redact(text: str) -> str:
    """Everything the note masker masks (LOG-JA, D-927), read on the line as written, then Taiwan IDs, Japanese My
    Number / insurance numbers / postcodes, phone numbers, MRN-shaped tokens and secrets (a value after a secret's
    name, a bearer token, a secret value the process holds). A scrubber that fails withholds the message, naming
    the error's type: never a line it did not scrub."""
    try:
        return _redact(_cut(text))
    except Exception as exc:  # a log line must never stop the service, nor go out unscrubbed
        return f"{WITHHELD[:-1]} ({type(exc).__name__})]"


def redact_value(value: Any, depth: int = 0) -> Any:
    """``value`` with every text inside it scrubbed: a dict's keys and values, a list's or tuple's items (the
    review's HIGH-1: an extra field that is not a text went out as written); other values as they are."""
    if isinstance(value, str):
        return redact(value)
    if depth > 8:  # deeper than any log field: withheld, not walked
        return WITHHELD
    if isinstance(value, dict):
        return {redact_value(k, depth + 1): redact_value(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_value(v, depth + 1) for v in value]
    return value


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
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = redact_value(val)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


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
