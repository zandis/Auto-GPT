"""The EDC door's own state in the trial database (E-EDCB-2, D-1044): schema ``edcdoor``.

Three things used to live in one process's memory or in a file in the system's temp folder, so a second console
process (or a restart) did not see them:

* ``oidc_code``: an OIDC code's sha256, the account it signs in, the client and the redirect it was issued for, and
  when it expires (120 s). It is redeemed by one ``DELETE ... RETURNING``: a code works once, in any process.
* ``proposal``: a write tool call held until the same person confirms it (``actor``), for :data:`PROPOSAL_S`. It is
  taken by one ``DELETE ... RETURNING``: a confirmation works once.
* ``event``: the id of each EDC event taken in. The id is the primary key; the insert and the re-read the event asks
  for run in one transaction, so a re-read that fails leaves the id unrecorded (the EDC sends it again) and the
  route answers 2xx only after the commit. A second delivery of an id finds it and answers ``fresh: false``.

No column holds a field value or a name: the account in ``oidc_code`` is a staff account, and ``event`` and
``proposal`` hold the EDC's project and record ids (their erasure entries: ``libs/tb_common/erasure.py``).

No database configured is no storage: :func:`default_store` raises :class:`NoStorage`, which the door answers 503.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tb_common.db import ENV, Database

SCHEMA = "edcdoor"
CODE_S = 120.0  # an OIDC code's life (the contract's single-use code)
PROPOSAL_S = 900.0  # a held write waits a quarter of an hour for its confirmation

SCHEMA_V1 = """
CREATE TABLE oidc_code (
  code_sha256 TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  client_id TEXT NOT NULL DEFAULT '',
  redirect_uri TEXT NOT NULL DEFAULT '',
  expires_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE proposal (
  id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  tool TEXT NOT NULL,
  project_id TEXT NOT NULL,
  record_id TEXT NOT NULL DEFAULT '',
  expires_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE event (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  project_id TEXT NOT NULL DEFAULT '',
  record_id TEXT NOT NULL DEFAULT '',
  instrument TEXT NOT NULL DEFAULT '',
  occurred_at TEXT NOT NULL DEFAULT '',
  received_at DOUBLE PRECISION NOT NULL
)
"""
MIGRATIONS = (SCHEMA_V1,)


class NoStorage(RuntimeError):
    """No trial database for the EDC door's state: the door answers 503, never a temp file."""


@dataclass(frozen=True)
class Code:
    username: str
    client_id: str
    redirect_uri: str


def code_key(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class DoorStore:
    """Schema ``edcdoor`` of the trial database at ``url`` (``TB_DB_URL`` when not given)."""

    def __init__(self, url: str | None = None, clock: Callable[[], float] = time.time) -> None:
        self.db = Database.connect(url if url is not None else os.environ.get(ENV), SCHEMA)
        self.db.migrate(list(MIGRATIONS))
        self.clock = clock

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ OIDC codes
    def issue_code(self, username: str, *, client_id: str = "", redirect_uri: str = "") -> str:
        code = secrets.token_urlsafe(24)
        self.db.execute(
            "INSERT INTO oidc_code (code_sha256, username, client_id, redirect_uri, expires_at) VALUES (?,?,?,?,?)",
            (code_key(code), username, client_id, redirect_uri, self.clock() + CODE_S),
        )
        return code

    def take_code(self, code: str) -> Code | None:
        """The code's row, once: deleted as it is read, by whichever process asks first. An expired code is gone
        and answers None."""
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "DELETE FROM oidc_code WHERE code_sha256 = ? RETURNING username, client_id, redirect_uri, expires_at",
                (code_key(code),),
            )
            tx.execute("DELETE FROM oidc_code WHERE expires_at < ?", (self.clock(),))
        if row is None or float(row[3]) < self.clock():
            return None
        return Code(str(row[0]), str(row[1]), str(row[2]))

    # ------------------------------------------------------------------ write proposals
    def hold(self, actor: str, tool: str, project_id: str, record_id: str) -> str:
        pid = uuid.uuid4().hex
        with self.db.transaction() as tx:
            tx.execute("DELETE FROM proposal WHERE expires_at < ?", (self.clock(),))
            tx.execute(
                "INSERT INTO proposal (id, actor, tool, project_id, record_id, expires_at) VALUES (?,?,?,?,?,?)",
                (pid, actor, tool, project_id, record_id, self.clock() + PROPOSAL_S),
            )
        return pid

    def open_ids(self) -> list[str]:
        rows = self.db.fetchall("SELECT id FROM proposal WHERE expires_at >= ? ORDER BY expires_at", (self.clock(),))
        return [str(r[0]) for r in rows]

    def take(self, actor: str, proposal_id: str) -> dict[str, str] | None:
        """The held write, once and only for the person who held it, while it has not expired."""
        row = self.db.fetchone(
            "DELETE FROM proposal WHERE id = ? AND actor = ? AND expires_at >= ? "
            "RETURNING actor, tool, project_id, record_id",
            (proposal_id, actor, self.clock()),
        )
        if row is None:
            return None
        return {"actor": str(row[0]), "tool": str(row[1]), "project_id": str(row[2]), "record_id": str(row[3])}

    # ------------------------------------------------------------------ events
    def take_event(self, row: dict[str, str], reread: Callable[[], Any] | None) -> bool:
        """Record the event's id and run its re-read in one transaction; True when the id is new. A repeated id
        (also one another process is taking in at the same moment) is False and runs nothing. When ``reread``
        raises, nothing is recorded and the exception goes to the caller."""
        with self.db.transaction() as tx:
            got = tx.fetchval(
                "INSERT INTO event (id, type, project_id, record_id, instrument, occurred_at, received_at) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING RETURNING id",
                (
                    row["id"],
                    row["type"],
                    row.get("project_id", ""),
                    row.get("record_id", ""),
                    row.get("instrument", ""),
                    row.get("occurred_at", ""),
                    self.clock(),
                ),
            )
            if got is None:
                return False
            if reread is not None:
                reread()
            return True

    def events(self) -> list[dict[str, Any]]:
        return self.db.fetchdicts("SELECT * FROM event ORDER BY received_at, id")


_DEFAULT: dict[str, DoorStore] = {}
_LOCK = threading.Lock()


def default_store(environ: dict[str, str] | None = None) -> DoorStore:
    """The store of ``TB_DB_URL``, one per URL in this process. :class:`NoStorage` when none is set or it cannot be
    opened."""
    env = os.environ if environ is None else environ
    url = (env.get(ENV) or "").strip()
    if not url:
        raise NoStorage(f"{ENV} is not set: the EDC door keeps its state in the trial database")
    with _LOCK:
        if url not in _DEFAULT:
            try:
                _DEFAULT[url] = DoorStore(url)
            except Exception as exc:  # unreachable, refused, not migrated: no storage, never a fallback
                raise NoStorage(f"the EDC door's store cannot be opened ({type(exc).__name__})") from exc
        return _DEFAULT[url]
