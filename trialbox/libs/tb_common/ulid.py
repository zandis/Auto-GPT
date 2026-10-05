"""ULID generation (Crockford base32, 48-bit ms time + 80-bit randomness, monotonic within a millisecond)."""

from __future__ import annotations

import os
import re
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_lock = threading.Lock()
_last_ms = -1
_last_rand = 0


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid(now_ms: int | None = None) -> str:
    """Return a new ULID string; strictly increasing for calls within the same process."""
    global _last_ms, _last_rand
    with _lock:
        ms = int(time.time() * 1000) if now_ms is None else now_ms
        if ms <= _last_ms:
            ms = _last_ms
            rand = (_last_rand + 1) & ((1 << 80) - 1)
            if rand == 0:  # overflow: move to the next millisecond
                ms += 1
                rand = int.from_bytes(os.urandom(10), "big")
        else:
            rand = int.from_bytes(os.urandom(10), "big")
        _last_ms, _last_rand = ms, rand
        return _encode(ms, 10) + _encode(rand, 16)


def is_ulid(value: str) -> bool:
    return bool(_ULID_RE.match(value))


def ulid_timestamp_ms(value: str) -> int:
    """Milliseconds since epoch encoded in ``value``."""
    if not is_ulid(value):
        raise ValueError(f"not a ULID: {value!r}")
    ms = 0
    for ch in value[:10]:
        ms = ms * 32 + _ALPHABET.index(ch)
    return ms
