"""Reverse pseudonym table ``pid -> MRN`` (SPEC §4.6), kept only in the box.

MRNs are stored AES-256-GCM encrypted (associated data = pid) with a key from ``secrets/pid_map.key``; the key file
is TPM-sealed on the appliance (DECISIONS D-10). Used solely to render MRNs into lists for internal recipients.

The rows live in schema ``pidmap`` of the trial database (D-126). Each map is the one of its key file (one per
secrets directory, so one per site): rows carry ``key_id``, a one-way fingerprint of the key, so maps under different
keys never mix and every service that mounts the same secrets reads the same map.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from tb_common.crypto import aes_decrypt, aes_encrypt, load_or_create_key
from tb_common.db import ENV as DB_URL_ENV
from tb_common.db import Database

SCHEMA_NAME = "pidmap"
#: ``migrate`` versions of schema ``pidmap`` (append-only)
MIGRATIONS = (
    """
CREATE TABLE IF NOT EXISTS pid_map (
  key_id TEXT NOT NULL,
  pid TEXT NOT NULL,
  mrn BYTEA NOT NULL,
  first_seen TEXT,
  last_seen TEXT,
  PRIMARY KEY (key_id, pid)
);
CREATE TABLE IF NOT EXISTS identity (
  key_id TEXT NOT NULL,
  pid TEXT NOT NULL,
  blob BYTEA NOT NULL,
  PRIMARY KEY (key_id, pid)
)
""",
)


def key_id(key: bytes) -> str:
    """The map's namespace: a domain-separated SHA-256 of the key (reveals nothing about it)."""
    return hashlib.sha256(b"trialbox pid_map key id\x00" + key).hexdigest()[:32]


class PidMap:
    def __init__(self, key_path: Path, url: str | None = None) -> None:
        """``key_path``: ``secrets/pid_map.key`` (created on first use, as before). ``url``: the trial database
        (``TB_DB_URL`` when None; :class:`tb_common.db.DatabaseError` if unset)."""
        self.key = load_or_create_key(key_path)
        self.key_id = key_id(self.key)
        self._db = Database.connect(url if url is not None else os.environ.get(DB_URL_ENV), SCHEMA_NAME)
        self._db.migrate(MIGRATIONS)

    def upsert_many(self, pairs: list[tuple[str, str]]) -> int:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.transaction() as tx:
            existing = {r[0] for r in tx.fetchall("SELECT pid FROM pid_map WHERE key_id = ?", (self.key_id,))}
            new = [
                (self.key_id, pid, aes_encrypt(self.key, mrn.encode(), pid.encode()), now, now)
                for pid, mrn in pairs
                if pid not in existing
            ]
            tx.executemany("INSERT INTO pid_map (key_id, pid, mrn, first_seen, last_seen) VALUES (?,?,?,?,?)", new)
            tx.executemany(
                "UPDATE pid_map SET last_seen=? WHERE key_id=? AND pid=?",
                [(now, self.key_id, p) for p, _ in pairs if p in existing],
            )
        return len(new)

    def upsert_identity(self, rows: list[tuple[str, dict[str, str]]]) -> None:
        with self._db.transaction() as tx:
            tx.executemany(
                "INSERT INTO identity (key_id, pid, blob) VALUES (?,?,?)"
                " ON CONFLICT (key_id, pid) DO UPDATE SET blob = excluded.blob",
                [
                    (
                        self.key_id,
                        pid,
                        aes_encrypt(self.key, json.dumps(v, ensure_ascii=False, sort_keys=True).encode(), pid.encode()),
                    )
                    for pid, v in rows
                ],
            )

    def identity(self, pid: str) -> dict[str, str] | None:
        row = self._db.fetchone("SELECT blob FROM identity WHERE key_id=? AND pid=?", (self.key_id, pid))
        if row is None:
            return None
        data: dict[str, str] = json.loads(aes_decrypt(self.key, bytes(row[0]), pid.encode()))
        return data

    def resolve(self, pid: str) -> str | None:
        row = self._db.fetchone("SELECT mrn FROM pid_map WHERE key_id=? AND pid=?", (self.key_id, pid))
        if row is None:
            return None
        return aes_decrypt(self.key, bytes(row[0]), pid.encode()).decode()

    def resolve_many(self, pids: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for pid in pids:
            mrn = self.resolve(pid)
            if mrn is not None:
                out[pid] = mrn
        return out

    def close(self) -> None:
        self._db.close()
