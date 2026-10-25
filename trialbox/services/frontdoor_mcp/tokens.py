"""Relay token map (spec v4 §9.3 "Token resolution", HER-12).

channel-relay replaces identifiers in a message with message-scoped tokens (``[MRN-1]``, ``[NAME-1]``) before any
model sees the text. The map from token to value is bound to the original message hash, its sender and its
conversation, and expires after 24 hours. Only the front-door server resolves tokens; the conversation engine
(Hermes or native) never receives the map, only the tokenised text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from orchestrator.db_pg import SqlBackend, apply_schema

Clock = Callable[[], float]  # epoch seconds
TOKEN_TTL_S = 24 * 3600


class TokenMap(Protocol):
    """What channel-relay (mint) and frontdoor-mcp (resolve) need: :class:`RelayTokenMap` in one process,
    :class:`SqlRelayTokenMap` across processes."""

    def mint(self, *, msg: str, sender: str, conv: str, kind: str, value: str) -> str: ...

    def resolve(self, token: str, *, msg: str, sender: str, conv: str) -> str: ...


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


TOKEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS relay_token (
  msg TEXT NOT NULL,
  token TEXT NOT NULL,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  sender TEXT NOT NULL,
  conv TEXT NOT NULL,
  expires DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (msg, token)
)
"""


class SqlRelayTokenMap:
    """:class:`RelayTokenMap` on the orchestrator's SQL backend, for a deployment where channel-relay (mints) and
    frontdoor-mcp (resolves) are separate processes. Same binding and expiry rules. The table is inside the
    perimeter (workflow-db); neither Hermes nor the native engine can reach it (HER-12)."""

    def __init__(self, backend: SqlBackend, clock: Clock, ttl_s: int = TOKEN_TTL_S) -> None:
        self.backend = backend
        self.clock = clock
        self.ttl_s = ttl_s
        apply_schema(backend, TOKEN_SCHEMA)

    def mint(self, *, msg: str, sender: str, conv: str, kind: str, value: str) -> str:
        with self.backend.transaction() as tx:
            hit = tx.fetchone(
                f"SELECT token FROM relay_token WHERE msg = ? AND kind = ? AND value = ?{self.backend.row_lock}",
                (msg, kind, value),
            )
            if hit is not None:
                return str(hit[0])
            rows = tx.fetchall("SELECT token FROM relay_token WHERE msg = ? AND kind = ?", (msg, kind))
            token = f"[{kind}-{len(rows) + 1}]"
            tx.execute(
                "INSERT INTO relay_token (msg, token, kind, value, sender, conv, expires) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg, token, kind, value, sender, conv, self.clock() + self.ttl_s),
            )
        return token

    def resolve(self, token: str, *, msg: str, sender: str, conv: str) -> str:
        with self.backend.transaction() as tx:
            row = tx.fetchone(
                "SELECT value, sender, conv, expires FROM relay_token WHERE msg = ? AND token = ?", (msg, token)
            )
        if row is None:
            raise TokenRefused("token_unknown", f"token {token} was not minted for this message")
        value, t_sender, t_conv, expires = row
        if t_sender != sender or t_conv != conv:
            raise TokenRefused("token_binding", f"token {token} is bound to another sender or conversation")
        if self.clock() > float(expires):
            raise TokenRefused("token_expired", f"token {token} expired")
        return str(value)

    def purge(self) -> int:
        with self.backend.transaction() as tx:
            return tx.execute("DELETE FROM relay_token WHERE expires < ?", (self.clock(),))
