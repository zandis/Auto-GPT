"""Breached-password check for console passwords, offline (D-447; CR-033 rest).

A box has no network at run time, so the list is a file the operator puts on the box and names in
``TB_CONSOLE_BREACHED_PASSWORDS_FILE``. Nothing is shipped: the useful public list (Have I Been Pwned "Pwned
Passwords", CC BY 4.0) is tens of gigabytes and changes; the operator downloads it, or any other list, where the
network is, and copies it over. The tests use a tiny synthetic list (``tests/console/data/breached-synthetic.txt``).

The file: one upper- or lower-case hexadecimal SHA-1 per line, optionally followed by ``:count`` (the HIBP download's
"ordered by hash" form), **sorted by hash**. A line may be a prefix of the hash instead of all 40 digits (a
"hash-prefix set", at least 10 digits; every line of the file the same length), which keeps a smaller file at the
cost of rare false matches (a false match only asks the person for another password). The file is searched by
seeking (binary search), never read whole, so a 40 GB file costs some twenty reads per check and no memory.

Settings: unset means no check (DEV, TEST, a box whose operator has not provided a list; the runbook's identity
section says how to provide one). Set and unreadable, or not in the format above, means every new password is
refused (fail closed): the operator sees the reason in the console log, the person a message that the password
cannot be checked.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO

ENV = "TB_CONSOLE_BREACHED_PASSWORDS_FILE"
MIN_PREFIX = 10
_HEX = re.compile(rb"^[0-9A-F]+$")

log = logging.getLogger("tb.console.breached")


class BreachedListError(RuntimeError):
    """The configured list cannot be used; the message names the file's problem, never a password."""


def _key(line: bytes) -> bytes:
    return line.split(b":", 1)[0].strip().upper()


def _line_after(f: BinaryIO, pos: int) -> bytes:
    """The first full line that starts at or after byte ``pos`` (b"" at the end of the file)."""
    if pos == 0:
        f.seek(0)
    else:
        f.seek(pos - 1)
        f.readline()  # up to and including the newline that ends the line ``pos - 1`` is in
    return f.readline()


def _width(f: BinaryIO) -> int:
    f.seek(0)
    first = _key(f.readline())
    if not first:
        raise BreachedListError("the list is empty")
    if not _HEX.match(first) or not MIN_PREFIX <= len(first) <= 40:
        raise BreachedListError(f"the first line is not a SHA-1 or a prefix of {MIN_PREFIX} to 40 hex digits")
    return len(first)


def listed(password: str, path: Path) -> bool:
    """True when the SHA-1 of ``password`` (or its prefix, for a prefix list) is a line of the sorted file."""
    target = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper().encode("ascii")
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            width = _width(f)
            want = target[:width]
            lo, hi = 0, size
            while lo < hi:
                mid = (lo + hi) // 2
                key = _key(_line_after(f, mid))
                if not key or key >= want:
                    hi = mid
                else:
                    lo = mid + 1
            found = _key(_line_after(f, lo))
    except OSError as exc:
        raise BreachedListError(f"the list {path} cannot be read: {type(exc).__name__}") from exc
    if found and (len(found) != width or not _HEX.match(found)):
        raise BreachedListError("the list has lines of different lengths or that are not hex digits")
    return found == want


def configured(env: Mapping[str, str] | None = None) -> Path | None:
    raw = ((os.environ if env is None else env).get(ENV) or "").strip()
    return Path(raw) if raw else None


def check(password: str, env: Mapping[str, str] | None = None) -> bool:
    """True when the password is on the configured list; False when it is not or no list is configured. Raises
    :class:`BreachedListError` when a list is configured and cannot be used (the caller refuses the password)."""
    path = configured(env)
    if path is None:
        return False
    try:
        return listed(password, path)
    except BreachedListError as exc:
        log.error("breached-password list refused (%s): every new password is refused until it is fixed", exc)
        raise
