"""A path to send a person back to, taken from a request, is a path on this console or nothing (security review
2026-11-13). A browser reads ``/\\host/x`` as ``//host/x``, another site, and drops tabs and newlines inside a URL,
so a value with a backslash or a control character is refused as well as one that starts with ``//``."""

from __future__ import annotations


def local_path(value: str, default: str) -> str:
    """``value`` when it is a path on this site, else ``default``."""
    v = value or ""
    if not v.startswith("/") or v.startswith("//") or "\\" in v:
        return default
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in v):
        return default
    return v
