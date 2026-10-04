"""Structured JSON logging to stdout with a PHI scrubber (SPEC §4, §10.1 "No PHI in logs (pids only)")."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_PHI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?!\d)"), "[TWID]"),
    (re.compile(r"(?<!\d)(?:\+886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\(?0\d{1,2}\)?[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"), "[PHONE]"),
]
_EXTRA_MRN: list[re.Pattern[str]] = []

_RESERVED = set(vars(logging.LogRecord("x", 0, "x", 0, "", None, None))) | {"message", "asctime"}


def set_mrn_regex(pattern: str) -> None:
    """Register the site MRN pattern (from settings.mrn_regex) for scrubbing; anchors are removed."""
    body = pattern.strip("^$")
    _EXTRA_MRN.clear()
    _EXTRA_MRN.append(re.compile(rf"(?<![0-9A-Za-z]){body}(?![0-9A-Za-z])"))


def redact(text: str) -> str:
    """Replace Taiwan IDs, phone numbers and MRN-shaped tokens by placeholders."""
    for pat, repl in _PHI_PATTERNS:
        text = pat.sub(repl, text)
    for pat in _EXTRA_MRN:
        text = pat.sub("[MRN]", text)
    return text


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
                payload[key] = redact(val) if isinstance(val, str) else val
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service: str, level: str = "INFO") -> logging.Logger:
    """Configure the root logger for JSON output; idempotent."""
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
