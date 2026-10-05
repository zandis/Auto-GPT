"""Email subject grammar (SPEC §5, with the D-15 extensions)::

    subject = cmd SP ruleset *(SP option) [SP "--" SP comment]
    cmd     = "FEAS" / "SCREEN" / "COHORT" / "NAV" / "APPROVE" / "STATUS" / "CANCEL" / "SUBMIT" / "FEEDBACK"
    ruleset = 1*16(ALPHA / DIGIT / "-" / "_")        ; STATUS / CANCEL take a job id (ULID) instead
    option  = key "=" value
    key     = "window" / "pract" / "dept" / "lookback" / "version" / "variant" / "since" / "pid" / "bundle" / "site"
    value   = 1*32(ALPHA / DIGIT / "-" / "," / "." / ":")   ; ":" allowed for variant=bmi:24,25,27 (spec example)

Leading reply/forward prefixes (``Re:``, ``RE:``, ``Fwd:``, ``回覆:``, ``轉寄:``) are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COMMANDS = ("FEAS", "SCREEN", "COHORT", "NAV", "APPROVE", "STATUS", "CANCEL", "SUBMIT", "FEEDBACK")
KEYS = ("window", "pract", "dept", "lookback", "version", "variant", "since", "pid", "bundle", "site")
_RULESET = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_VALUE = re.compile(r"^[A-Za-z0-9,.:\-]{1,32}$")
_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|aw|回覆|回复|轉寄|转发)\s*[:：]\s*)+", re.I)
JOB_ID_COMMANDS = ("STATUS", "CANCEL")


class SubjectError(ValueError):
    pass


@dataclass(frozen=True)
class Subject:
    cmd: str
    ruleset: str
    options: dict[str, str] = field(default_factory=dict)
    comment: str | None = None

    @property
    def job_id(self) -> str | None:
        return self.ruleset if self.cmd in JOB_ID_COMMANDS else None


def parse_subject(raw: str) -> Subject:
    text = _PREFIX.sub("", raw.replace("　", " ")).strip()
    comment: str | None = None
    if " -- " in f"{text} ":
        text, _, comment = (text + " ").partition(" -- ")
        comment = comment.strip() or None
        text = text.strip()
    parts = text.split()
    if len(parts) < 2:
        raise SubjectError("subject must be '<COMMAND> <ruleset> [key=value ...] [-- comment]'")
    cmd = parts[0].upper()
    if cmd not in COMMANDS:
        raise SubjectError(f"unknown command {parts[0]!r}; expected one of {', '.join(COMMANDS)}")
    target = parts[1]
    if cmd in JOB_ID_COMMANDS:
        target = target.upper()
        if not _ULID.match(target):
            raise SubjectError(f"{cmd} needs a job id (26-character ULID), got {parts[1]!r}")
    elif not _RULESET.match(target):
        raise SubjectError(f"invalid ruleset {target!r} (1-16 letters, digits, '-' or '_')")
    else:
        target = target.upper()  # ruleset ids are upper case (criterion id pattern); accept any case in mail
    options: dict[str, str] = {}
    for tok in parts[2:]:
        key, sep, value = tok.partition("=")
        if not sep:
            raise SubjectError(f"option {tok!r} must be key=value")
        key = key.lower()
        if key not in KEYS:
            raise SubjectError(f"unknown option {key!r}; allowed: {', '.join(KEYS)}")
        if not _VALUE.match(value):
            raise SubjectError(f"invalid value for {key}: {value!r}")
        if key in options:
            raise SubjectError(f"option {key} given twice")
        options[key] = value
    return Subject(cmd, target, options, comment)


def format_subject(s: Subject) -> str:
    opts = " ".join(f"{k}={v}" for k, v in sorted(s.options.items()))
    out = f"{s.cmd} {s.ruleset}" + (f" {opts}" if opts else "")
    return out + (f" -- {s.comment}" if s.comment else "")
