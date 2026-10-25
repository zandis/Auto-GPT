"""Relay token map (spec v4 §9.3 "Token resolution", HER-12).

channel-relay replaces identifiers in a message with message-scoped tokens (``[MRN-1]``, ``[NAME-1]``) before any
model sees the text. The map from token to value is bound to the original message hash, its sender and its
conversation, and expires after 24 hours. Only the front-door server resolves tokens; the conversation engine
(Hermes or native) never receives the map, only the tokenised text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

Clock = Callable[[], float]  # epoch seconds
TOKEN_TTL_S = 24 * 3600


class TokenRefused(PermissionError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class _Entry:
    value: str
    msg: str
    sender: str
    conv: str
    expires: float


class RelayTokenMap:
    def __init__(self, clock: Clock, ttl_s: int = TOKEN_TTL_S) -> None:
        self.clock = clock
        self.ttl_s = ttl_s
        self._entries: dict[tuple[str, str], _Entry] = {}  # (msg, token) -> entry
        self._counters: dict[tuple[str, str], int] = {}

    def mint(self, *, msg: str, sender: str, conv: str, kind: str, value: str) -> str:
        """Return the token for ``value`` in this message (the same value in one message gets the same token)."""
        for (m, tok), e in self._entries.items():
            if m == msg and e.value == value and tok.startswith(f"[{kind}-"):
                return tok
        n = self._counters.get((msg, kind), 0) + 1
        self._counters[(msg, kind)] = n
        token = f"[{kind}-{n}]"
        self._entries[(msg, token)] = _Entry(value, msg, sender, conv, self.clock() + self.ttl_s)
        return token

    def resolve(self, token: str, *, msg: str, sender: str, conv: str) -> str:
        e = self._entries.get((msg, token))
        if e is None:
            raise TokenRefused("token_unknown", f"token {token} was not minted for this message")
        if e.sender != sender or e.conv != conv:
            raise TokenRefused("token_binding", f"token {token} is bound to another sender or conversation")
        if self.clock() > e.expires:
            raise TokenRefused("token_expired", f"token {token} expired")
        return e.value

    def purge(self) -> int:
        now = self.clock()
        stale = [k for k, e in self._entries.items() if now > e.expires]
        for k in stale:
            del self._entries[k]
        return len(stale)
