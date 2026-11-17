"""A path to send a person back to, taken from a request, is a path on this console or nothing (security review
2026-11-13). A browser reads ``/\\host/x`` as ``//host/x``, another site, and drops tabs and newlines inside a URL,
so a value with a backslash or a control character is refused as well as one that starts with ``//``."""

from __future__ import annotations

import unicodedata

#: lane J's finding (the integrator's High): the Unicode categories refused anywhere in a path to send a person back
#: to: controls, formats (zero-width, direction marks, the byte-order mark), line and paragraph separators
REFUSED_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")


def refused_char(c: str) -> bool:
    """A character such a path may not hold: below 0x21 (every ASCII control, and the space), DEL, or a Unicode
    control, format or line separator. A browser drops some of them from a URL, so "/<tab>/evil.example" would read
    as "//evil.example": another site."""
    return ord(c) < 0x21 or c == "\x7f" or unicodedata.category(c) in REFUSED_CATEGORIES


def is_local(v: str) -> bool:
    """Whether ``v`` is a path on this site: it starts with one "/", holds no backslash and no refused character, and
    is not "//" once whitespace is taken out."""
    if not v.startswith("/") or "\\" in v or any(refused_char(c) for c in v):
        return False
    return not "".join(c for c in v if not c.isspace()).startswith("//")


def local_path(value: str, default: str) -> str:
    """``value`` when it is a path on this site, else ``default``."""
    v = value or ""
    return v if is_local(v) else default
