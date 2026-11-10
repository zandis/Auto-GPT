"""Reverse pseudonym table ``pid -> MRN`` (SPEC §4.6), kept only in the box.

MRNs are stored AES-256-GCM encrypted (associated data = pid) with a key from ``secrets/pid_map.key``; the key file
is TPM-sealed on the appliance (DECISIONS D-10). Used solely to render MRNs into lists for internal recipients.

The rows live in schema ``pidmap`` of the trial database (D-126). Each map is the one of its key file (one per
secrets directory, so one per site): rows carry ``key_id``, a one-way fingerprint of the key, so maps under different
keys never mix and every service that mounts the same secrets reads the same map.

Chart numbers are written the site's way before they are hashed or stored (:func:`pseudonym`, ``tb_common.chartno``,
R-48, D-301): a sheet's ``123456`` and the feed's ``00123456`` are one patient under a ``digits:8`` rule. Under the
default rule a chart number already written the hospital's way is stored and hashed exactly as before.

The site key (T-612, DATA-004). Table ``site_key`` holds the fingerprint of each site's ``site_hmac.key`` as first
seen. :meth:`PidMap.site_key_problem` says when the key in hand is another one: its fingerprint differs from the
stored one, or it does not give back the pseudonyms the map holds (a box from before the table).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from tb_common import chartno
from tb_common.crypto import aes_decrypt, aes_encrypt, key_fingerprint, load_or_create_key, pid_for_mrn
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
    # T-612: the fingerprint of each site's pseudonymisation key, as first seen (tb_common.crypto.key_fingerprint)
    """
CREATE TABLE IF NOT EXISTS site_key (
  site_id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  recorded_at TEXT NOT NULL
)
""",
)


def pseudonym(site_key: bytes, chart_no: str) -> tuple[str, str]:
    """``(pid, chart number written the site's way)``: the pair the map stores."""
    norm = chartno.normalise(None, chart_no)
    return pid_for_mrn(site_key, norm), norm


def key_id(key: bytes) -> str:
    """The map's namespace: a domain-separated SHA-256 of the key (reveals nothing about it)."""
    return hashlib.sha256(b"trialbox pid_map key id\x00" + key).hexdigest()[:32]


class PidMap:
    def __init__(self, key_path: Path, url: str | None = None) -> None:
        """``key_path``: ``secrets/pid_map.key`` (created on first use, as before: it encrypts the rows and changes no
        pseudonym; the site key never is, T-612). ``url``: the trial database
        (``TB_DB_URL`` when None; :class:`tb_common.db.DatabaseError` if unset)."""
        self.key = load_or_create_key(key_path)
        self.key_id = key_id(self.key)
        self._db = Database.connect(url if url is not None else os.environ.get(DB_URL_ENV), SCHEMA_NAME)
        self._db.migrate(MIGRATIONS)

    def site_key_problem(self, site_id: str, site_key: bytes, probe: int = 5) -> str | None:
        """T-612: why ``site_key`` is not the key this map was built with, or None. Compares its fingerprint with the
        one stored for ``site_id``, then checks that it gives back the pseudonyms of up to ``probe`` stored rows."""
        fp = key_fingerprint(site_key)
        stored = self.stored_site_key(site_id)
        if stored is not None and stored != fp:
            return f"its fingerprint {fp} differs from the stored one {stored} (site {site_id})"
        rows = self._db.fetchall(
            "SELECT pid, mrn FROM pid_map WHERE key_id = ? ORDER BY pid LIMIT ?", (self.key_id, probe)
        )
        for pid, blob in rows:
            mrn = aes_decrypt(self.key, bytes(blob), str(pid).encode()).decode()
            if pid_for_mrn(site_key, mrn) != pid:
                return f"it does not give the pseudonyms the pid map holds (fingerprint {fp})"
        return None

    def record_site_key(self, site_id: str, site_key: bytes) -> None:
        """Store the site key's fingerprint the first time; never replaced (a changed key is refused, not recorded)."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.transaction() as tx:
            tx.execute(
                "INSERT INTO site_key (site_id, fingerprint, recorded_at) VALUES (?,?,?)"
                " ON CONFLICT (site_id) DO NOTHING",
                (site_id, key_fingerprint(site_key), now),
            )

    def stored_site_key(self, site_id: str) -> str | None:
        """The fingerprint stored for ``site_id``, or None."""
        row = self._db.fetchone("SELECT fingerprint FROM site_key WHERE site_id = ?", (site_id,))
        return str(row[0]) if row is not None else None

    def upsert_many(self, pairs: list[tuple[str, str]]) -> int:
        # one row per pseudonym: two spellings of one chart number (R-48) are one patient; the first is kept
        pairs = list({pid: (pid, mrn) for pid, mrn in reversed(pairs)}.values())[::-1]
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.transaction() as tx:
            existing = {r[0] for r in tx.fetchall("SELECT pid FROM pid_map WHERE key_id = ?", (self.key_id,))}
            new = [
                (self.key_id, pid, aes_encrypt(self.key, chartno.normalise(None, mrn).encode(), pid.encode()), now, now)
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
