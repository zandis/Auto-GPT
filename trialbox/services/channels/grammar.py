"""Deterministic grammar lines (spec v4 App. D, v1 ``SPEC.md`` §5; FR-CONV-1, FR-UX-10).

:func:`parse_line` returns a :class:`Line` for a text that is a grammar line, ``None`` for text that is not one (it then
goes to the conversation engine), and raises :class:`GrammarError` for a text that starts with a command keyword but
is malformed (the sender gets the error and the accepted lines; no model sees it). A line that parses never reaches a
model. The v1 subject grammar (``tb_common.subject``) stays valid as the typed fallback.

Commands must be typed in upper case, except ``OK``, so that English free text such as "status of GZQO?" is
conversation, not a malformed line.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from tb_common.subject import COMMANDS as V1_COMMANDS
from tb_common.subject import SubjectError, parse_subject

V4_COMMANDS = (
    "FEAS",
    "QFILL",
    "ASK",
    "WHATIF",
    "SCREEN",
    "STUDY",
    "CONFIRM",
    "REJECT",
    "DEFER",
    "STATE",
    "ANSWERS",
    "MONITOR",
    "ATLAS",
    "STATUS",
    "HELP",
    "DIGEST",
    "OK",
    "APPROVE",
    "REJECTGATE",
    "MATCH",
    "FULLREVIEW",
    "SAE",
    "QUERY",
)
ALL_COMMANDS = frozenset(V4_COMMANDS) | frozenset(V1_COMMANDS)
APPROVAL_COMMANDS = frozenset({"APPROVE", "REJECTGATE"})  # email only (FR-SIG-8); never proposed
NEVER_PROPOSED = APPROVAL_COMMANDS | {"MATCH", "FULLREVIEW", "SAE", "QUERY", "RELEASE"}
STUDY_STATUS = ("recruiting", "follow_up", "closed", "declined")
STATES = (
    "contacted",
    "consented",
    "screened",
    "randomized",
    "declined",
    "screen_failed",
    "withdrawn",
    "not_contactable",
)
PARAM_KEYS = frozenset(
    {"scope", "lookback", "deadline", "cadence", "window", "pract", "dept", "version", "variant", "since", "site"}
)
HELP_LINES = (
    "FEAS NEW scope=hospital lookback=24m deadline=YYYY-MM-DD",
    'ASK <study> "question"',
    "STATUS [<study>]",
    "OK",
    "HELP",
)

_STUDY = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}$")
_ALIAS = re.compile(r"^P\d{4}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALUE = re.compile(r"^[A-Za-z0-9,.:_\-]{1,64}$")
_PREFIX = re.compile(r"^\s*(?:(?:re|fw|fwd|aw|回覆|回复|轉寄|转发)\s*[:：]\s*)+", re.I)
_REASON = re.compile(r"^R0[1-7]$")
_ANSWER = re.compile(r"^\d+[YN?]$")
_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class GrammarError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    command: str
    study: str | None = None
    args: tuple[str, ...] = ()
    params: dict[str, str] = field(default_factory=dict)
    text: str = ""
    grammar: str = "v4"

    @property
    def approval(self) -> bool:
        return self.command in APPROVAL_COMMANDS


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).replace("　", " ")
    return _PREFIX.sub("", t).strip()


def _params(tokens: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for tok in tokens:
        k, sep, v = tok.partition("=")
        if not sep:
            raise GrammarError(f"{tok!r} must be key=value")
        k = k.lower()
        if k not in PARAM_KEYS:
            raise GrammarError(f"unknown parameter {k!r}; allowed: {', '.join(sorted(PARAM_KEYS))}")
        if not _VALUE.match(v):
            raise GrammarError(f"invalid value for {k}: {v!r}")
        if k in out:
            raise GrammarError(f"parameter {k} given twice")
        if k == "deadline" and not _DATE.match(v):
            raise GrammarError("deadline must be YYYY-MM-DD")
        out[k] = v
    return out


def _study(tok: str | None, *, allow_new: bool = False) -> str:
    if tok is None:
        raise GrammarError("a study code is required")
    s = tok.upper()
    if allow_new and s == "NEW":
        return s
    if not _STUDY.match(s):
        raise GrammarError(f"invalid study code {tok!r}")
    return s


def parse_line(raw: str) -> Line | None:
    text = normalise(raw)
    if not text:
        return None
    parts = text.split()
    head = parts[0]
    if head.upper() == "OK" and len(parts) == 1:
        return Line("OK", text="OK")
    if head not in ALL_COMMANDS:  # case-sensitive: lower-case words are conversation
        return None
    cmd, rest = head, parts[1:]
    nxt = rest[0] if rest else None
    if cmd in ("FEAS", "SCREEN"):
        try:
            study = _study(nxt, allow_new=cmd == "FEAS")
            return Line(cmd, study, params=_params(rest[1:]), text=text)
        except GrammarError:
            v1 = _v1(text)
            if v1 is not None:
                return v1
            raise
    if cmd in ("QFILL",):
        if len(rest) != 1:
            raise GrammarError("QFILL takes exactly one study code")
        return Line(cmd, _study(nxt), text=text)
    if cmd == "ASK":
        m = re.match(r'^ASK\s+(\S+)\s+"([^"]{1,500})"\s*$', text)
        if not m:
            raise GrammarError('ASK needs a study code and a quoted question: ASK GZQO "question"')
        return Line(cmd, _study(m.group(1)), args=(m.group(2),), text=text)
    if cmd == "WHATIF":
        if len(rest) < 3:
            raise GrammarError("WHATIF <study> drop <criterion> | set <criterion> key=value")
        return Line(cmd, _study(nxt), args=tuple(" ".join(rest[1:]).split(";")), text=text)
    if cmd == "STUDY":
        if len(rest) != 2 or rest[1] not in STUDY_STATUS:
            raise GrammarError(f"STUDY <study> {'|'.join(STUDY_STATUS)}")
        return Line(cmd, _study(nxt), args=(rest[1],), text=text)
    if cmd == "CONFIRM":
        if not rest or not all(_ALIAS.match(a) for a in rest):
            raise GrammarError("CONFIRM takes candidate aliases such as P0156")
        return Line(cmd, args=tuple(rest), text=text)
    if cmd == "REJECT":
        if len(rest) < 2 or not _ALIAS.match(rest[0]) or not _REASON.match(rest[1]):
            raise GrammarError("REJECT <alias> <R01-R07> [free text]")
        if rest[1] == "R07" and len(rest) < 3:
            raise GrammarError("R07 needs free text")
        return Line(cmd, args=(rest[0], rest[1], " ".join(rest[2:])), text=text)
    if cmd == "DEFER":
        if not rest or not _ALIAS.match(rest[0]) or (len(rest) > 1 and not _DATE.match(rest[1])) or len(rest) > 2:
            raise GrammarError("DEFER <alias> [YYYY-MM-DD]")
        return Line(cmd, args=tuple(rest), text=text)
    if cmd == "STATE":
        if len(rest) not in (2, 3) or not _ALIAS.match(rest[0]) or rest[1] not in STATES:
            raise GrammarError(f"STATE <alias> {'|'.join(STATES)} [YYYY-MM-DD]")
        if len(rest) == 3 and not _DATE.match(rest[2]):
            raise GrammarError("STATE date must be YYYY-MM-DD")
        return Line(cmd, args=tuple(rest), text=text)
    if cmd == "ANSWERS":
        if not rest or not all(_ANSWER.match(a) for a in rest):
            raise GrammarError("ANSWERS 1Y 2N 3?")
        return Line(cmd, args=tuple(rest), text=text)
    if cmd == "MONITOR":
        if len(rest) != 2 or not _DATE.match(rest[1]):
            raise GrammarError("MONITOR <study> YYYY-MM-DD")
        return Line(cmd, _study(nxt), args=(rest[1],), text=text)
    if cmd == "ATLAS":
        if len(rest) > 1:
            raise GrammarError("ATLAS [domain]")
        return Line(cmd, args=tuple(rest), text=text)
    if cmd == "STATUS":
        if len(rest) > 1:
            raise GrammarError("STATUS [study | job id]")
        if rest and _ULID.match(rest[0].upper()):
            return Line(cmd, args=(rest[0].upper(),), text=text, grammar="v1")
        return Line(cmd, _study(nxt) if rest else None, text=text)
    if cmd == "HELP":
        return Line(cmd, text=text)
    if cmd == "DIGEST":
        if len(rest) != 1 or rest[0] not in ("daily", "weekly", "off"):
            raise GrammarError("DIGEST daily|weekly|off")
        return Line(cmd, args=tuple(rest), text=text)
    if cmd in ("APPROVE", "REJECTGATE"):
        v1 = _v1(text)
        if v1 is not None:
            return Line(cmd, v1.study, params=v1.params, text=text, grammar="v1")
        if not rest:
            raise GrammarError(f"{cmd} <gate-id> sha=…")
        return Line(cmd, args=tuple(rest), text=text)
    if cmd in ("MATCH", "FULLREVIEW", "SAE", "QUERY"):
        if not rest:
            raise GrammarError(f"{cmd} needs its arguments")
        return Line(cmd, args=tuple(rest), text=text)
    v1 = _v1(text)
    if v1 is None:
        raise GrammarError(f"{cmd}: not a valid line")
    return v1


def _v1(text: str) -> Line | None:
    try:
        s = parse_subject(text)
    except SubjectError:
        return None
    return Line(s.cmd, s.ruleset, params=dict(s.options), text=text, grammar="v1")
