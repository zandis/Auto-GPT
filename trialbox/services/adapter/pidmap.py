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

The map's key under the KEK (T-210b, D-347). :func:`load_map_key` opens ``pid_map.key`` wrapped under the box's KEK
(``tb_common.kek``) or plain. A box whose ``TB_ENV`` says VALIDATION or PRODUCTION (``install.sh`` writes it) never
makes it on first use: only the install ceremony does, so a lost or locked key is refused instead of replaced by an
empty map. :meth:`PidMap.rekey` re-encrypts every row under a new key (``python -m tools.keys rotate pid_map``).

The patient index as an alias table (D-370 §3, T-659b, DATA-002). When the hospital merges two chart numbers (A into
B), :meth:`PidMap.merge` adds one row to ``pid_alias``: the pid of A, the surviving pid of B, the reason, the ticket
and the time. The table is append-only: a row is never changed or removed, and no pid is re-keyed. Both chart numbers
then resolve to one pid (:meth:`PidMap.surviving`); the ingest writes the night's records under the surviving pid
(:func:`adapter.pipeline.apply_aliases`).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from tb_common import chartno
from tb_common.crypto import KeyMissingError, aes_decrypt, aes_encrypt, key_fingerprint, pid_for_mrn
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
    # T-659b (D-370): the patient index as an append-only alias table; old pid -> surviving pid
    """
CREATE TABLE IF NOT EXISTS pid_alias (
  old_pid TEXT PRIMARY KEY,
  pid TEXT NOT NULL,
  reason TEXT NOT NULL,
  ticket TEXT NOT NULL,
  merged_at TEXT NOT NULL
)
""",
    # T-723 (D-489): a night's chart numbers wait here until the night is published (it passed the gate, or a
    # steward accepted it); a held night's never reach the reverse map. Encrypted as the map's own rows are
    """
CREATE TABLE IF NOT EXISTS pending (
  snapshot TEXT NOT NULL,
  key_id TEXT NOT NULL,
  pid TEXT NOT NULL,
  mrn BYTEA NOT NULL,
  blob BYTEA,
  PRIMARY KEY (snapshot, key_id, pid)
)
""",
)


class AliasError(ValueError):
    """A merge the alias table refuses: a pid merged into itself, a pid already merged elsewhere, or a cycle."""


def pseudonym(site_key: bytes, chart_no: str) -> tuple[str, str]:
    """``(pid, chart number written the site's way)``: the pair the map stores."""
    norm = chartno.normalise(None, chart_no)
    return pid_for_mrn(site_key, norm), norm


def _follow(raw: Mapping[str, str], pid: str) -> str:
    seen = {pid}
    while pid in raw:
        pid = raw[pid]
        if pid in seen:
            raise AliasError(f"the alias table has a cycle at {pid}")
        seen.add(pid)
    return pid


def key_id(key: bytes) -> str:
    """The map's namespace: a domain-separated SHA-256 of the key (reveals nothing about it)."""
    return hashlib.sha256(b"trialbox pid_map key id\x00" + key).hexdigest()[:32]


def load_map_key(key_path: Path, env: Mapping[str, str] | None = None) -> bytes:
    """T-210b: the key of ``key_path`` (``secrets/pid_map.key``), wrapped under the KEK or plain. Made when absent in
    DEV and TEST, and by tools that set no ``TB_ENV`` (demos, fixtures; it encrypts the rows and changes no
    pseudonym); with ``TB_ENV`` VALIDATION or PRODUCTION
    ``KeyMissingError``: the install ceremony makes it, and a lost key is put back from the backup. A locked KEK is
    ``tb_common.kek.KekLockedError`` (nothing is made)."""
    from tb_common.kek import create_key_file, load_key_file

    env = os.environ if env is None else env
    try:
        key = load_key_file(key_path, env)
    except KeyMissingError:
        named = (env.get("TB_ENV") or "").strip().upper()
        if named in ("VALIDATION", "PRODUCTION"):  # set on purpose, as install.sh does (D-127)
            raise KeyMissingError(
                f"{key_path} is missing: in {named} it is made only by the install ceremony "
                f"(`python -m adapter.cli keys-init`); on a box that has run before, put it back from the backup"
            ) from None
        create_key_file(key_path, 32, env)
        key = load_key_file(key_path, env)
    if len(key) != 32:
        raise ValueError(f"{key_path}: the pid map key is 32 bytes, this one is {len(key)}")
    return key


class PidMap:
    def __init__(self, key_path: Path, url: str | None = None) -> None:
        """``key_path``: ``secrets/pid_map.key``, plain or wrapped under the KEK (:func:`load_map_key`; made on first
        use outside VALIDATION and PRODUCTION; the site key never is, T-612). ``url``: the trial database
        (``TB_DB_URL`` when None; :class:`tb_common.db.DatabaseError` if unset)."""
        self.key = load_map_key(key_path)
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

    # ------------------------------------------------------------------ staging (T-723, D-489; lifecycle F-12)
    def stage(self, snapshot: str, pairs: list[tuple[str, str]], identities: list[tuple[str, dict[str, str]]]) -> int:
        """Keep a night's (pid, chart number) pairs and identities aside, in place of an earlier staging of the
        same night. The reverse map (:meth:`resolve`) does not know them until :meth:`commit`."""
        ident = dict(identities)
        rows = [
            (
                snapshot,
                self.key_id,
                pid,
                aes_encrypt(self.key, chartno.normalise(None, mrn).encode(), pid.encode()),
                aes_encrypt(self.key, json.dumps(ident[pid], ensure_ascii=False, sort_keys=True).encode(), pid.encode())
                if pid in ident
                else None,
            )
            for pid, mrn in {pid: (pid, mrn) for pid, mrn in reversed(pairs)}.values()
        ]
        with self._db.transaction() as tx:
            tx.execute("DELETE FROM pending WHERE snapshot = ? AND key_id = ?", (snapshot, self.key_id))
            tx.executemany("INSERT INTO pending (snapshot, key_id, pid, mrn, blob) VALUES (?,?,?,?,?)", rows)
        return len(rows)

    def commit(self, snapshot: str) -> int:
        """The night is published: its staged rows enter the map (a pid the map knows keeps its first chart number,
        its ``last_seen`` moves; an identity replaces the stored one) and leave the staging, in one transaction.
        Returns the pids new to the map. Nothing staged: 0 (a second call, a night with no patient table)."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.transaction() as tx:
            new = tx.execute(
                "INSERT INTO pid_map (key_id, pid, mrn, first_seen, last_seen) SELECT key_id, pid, mrn, ?, ? "
                "FROM pending WHERE snapshot = ? AND key_id = ? ON CONFLICT (key_id, pid) DO NOTHING",
                (now, now, snapshot, self.key_id),
            )
            tx.execute(
                "UPDATE pid_map m SET last_seen = ? FROM pending p WHERE p.snapshot = ? AND p.key_id = ? "
                "AND m.key_id = p.key_id AND m.pid = p.pid",
                (now, snapshot, self.key_id),
            )
            tx.execute(
                "INSERT INTO identity (key_id, pid, blob) SELECT key_id, pid, blob FROM pending WHERE snapshot = ? "
                "AND key_id = ? AND blob IS NOT NULL ON CONFLICT (key_id, pid) DO UPDATE SET blob = excluded.blob",
                (snapshot, self.key_id),
            )
            tx.execute("DELETE FROM pending WHERE snapshot = ? AND key_id = ?", (snapshot, self.key_id))
        return int(new)

    def staged(self) -> dict[str, int]:
        """``night -> staged pids`` (counts only)."""
        rows = self._db.fetchall(
            "SELECT snapshot, count(*) FROM pending WHERE key_id = ? GROUP BY snapshot", (self.key_id,)
        )
        return {str(s): int(n) for s, n in rows}

    def discard(self, keep: set[str]) -> int:
        """Delete the staged rows of every night not in ``keep`` (a rejected night, a night replaced by a later
        run); returns the rows deleted."""
        with self._db.transaction() as tx:
            return int(tx.execute("DELETE FROM pending WHERE NOT (snapshot = ANY(?))", (sorted(keep),)))

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

    def merge(self, site_key: bytes, old_chart: str, new_chart: str, reason: str, ticket: str) -> tuple[str, str]:
        """Chart number ``old_chart`` was merged into ``new_chart`` at the hospital: add the alias row
        ``pid(old) -> surviving pid(new)`` (append-only). Returns ``(old pid, surviving pid)``. Recording the same
        merge again does nothing; a merge that would move an already merged pid elsewhere, or close a cycle, is
        refused (:class:`AliasError`)."""
        if not reason.strip() or not ticket.strip():
            raise AliasError("a merge needs a reason and a ticket")
        old, _ = pseudonym(site_key, old_chart)
        new = self.surviving(pseudonym(site_key, new_chart)[0])
        if old == new:
            raise AliasError("the two chart numbers are already one patient")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.transaction() as tx:
            row = tx.fetchone("SELECT pid FROM pid_alias WHERE old_pid = ?", (old,))
            if row is not None:
                if str(row[0]) == new:
                    return old, new
                raise AliasError("the old chart number was already merged into another patient")
            tx.execute(
                "INSERT INTO pid_alias (old_pid, pid, reason, ticket, merged_at) VALUES (?,?,?,?,?)",
                (old, new, reason.strip(), ticket.strip(), now),
            )
        return old, new

    def aliases(self) -> dict[str, str]:
        """Every old pid with its surviving pid (chains followed to the end)."""
        raw = {str(a): str(b) for a, b in self._db.fetchall("SELECT old_pid, pid FROM pid_alias")}
        return {a: _follow(raw, a) for a in raw}

    def surviving(self, pid: str) -> str:
        """The pid a reader uses for ``pid``: itself, or the surviving pid of its merge."""
        return self.aliases().get(pid, pid)

    def rekey(self, new_key: bytes) -> int:
        """T-210b (OPS-058): re-encrypt every row of this map (``pid_map`` and ``identity``) under ``new_key`` in one
        transaction; the rows under the old key are removed. Returns the rows moved. Run again after an interruption,
        it moves what is left (none). The caller stores the new key (``tools.keys rotate pid_map``)."""
        if len(new_key) != 32:
            raise ValueError("the pid map key is 32 bytes")
        new_id = key_id(new_key)
        if new_id == self.key_id:
            return 0

        def again(pid: str, blob: bytes) -> bytes:
            return aes_encrypt(new_key, aes_decrypt(self.key, bytes(blob), pid.encode()), pid.encode())

        with self._db.transaction() as tx:
            rows = tx.fetchall("SELECT pid, mrn, first_seen, last_seen FROM pid_map WHERE key_id = ?", (self.key_id,))
            tx.executemany(
                "INSERT INTO pid_map (key_id, pid, mrn, first_seen, last_seen) VALUES (?,?,?,?,?)"
                " ON CONFLICT (key_id, pid) DO NOTHING",
                [(new_id, pid, again(pid, blob), first, last) for pid, blob, first, last in rows],
            )
            ids = tx.fetchall("SELECT pid, blob FROM identity WHERE key_id = ?", (self.key_id,))
            tx.executemany(
                "INSERT INTO identity (key_id, pid, blob) VALUES (?,?,?) ON CONFLICT (key_id, pid) DO NOTHING",
                [(new_id, pid, again(pid, blob)) for pid, blob in ids],
            )
            tx.execute("DELETE FROM pid_map WHERE key_id = ?", (self.key_id,))
            tx.execute("DELETE FROM identity WHERE key_id = ?", (self.key_id,))
            moved = len(rows) + len(ids)
        self.key, self.key_id = new_key, new_id
        return moved

    def close(self) -> None:
        self._db.close()
