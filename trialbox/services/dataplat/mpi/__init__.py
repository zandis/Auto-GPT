"""Master patient index client (§5.14.1, §5.14.2, DP-35, PRIV-10; S1-04).

A local SQLite store in Z-IDN stands in for ``tb-vault`` until that service exists (§7.5). It keeps the tables of
§5.14.1: ``mpi_person`` (random 128-bit ``mpi_id``), ``mpi_identifier`` (MRN as an HMAC lookup value plus AES-GCM
ciphertext, never in clear), ``mpi_merge`` (append-only, A40 or steward ticket) and ``pid_alias``.

* ``mpi_id`` is random (never derived from the MRN). The id factory is injectable for reproducible tests.
* ``pid = hex(HMAC-SHA-256(K_pid, mpi_id))[:32]`` with ``K_pid = HKDF-SHA-256(K_root, salt=site_id,
  info="tb/pid/v1")`` (§7.5).
* A merge points the ``from`` person at the surviving ``to`` person; every MRN of either resolves to the survivor,
  so two MRNs map to one ``mpi_id`` and one pid. The old pid gets a ``pid_alias`` row (reason ``merge``).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tb_common.crypto import aes_decrypt, aes_encrypt

from dataplat.common import Clock, hkdf, iso_utc, utc_now

PID_HEX_LEN = 32
MRN_SYSTEM = "mrn"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mpi_person (
  mpi_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('active','merged','erased')), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mpi_identifier (
  mpi_id TEXT NOT NULL REFERENCES mpi_person(mpi_id), system TEXT NOT NULL, value_hmac TEXT NOT NULL,
  value_enc BLOB NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT, PRIMARY KEY (system, value_hmac)
);
CREATE TABLE IF NOT EXISTS mpi_merge (
  from_mpi_id TEXT NOT NULL, to_mpi_id TEXT NOT NULL, source_event TEXT NOT NULL, effective_utc TEXT NOT NULL,
  undone_utc TEXT, PRIMARY KEY (from_mpi_id, source_event)
);
CREATE TABLE IF NOT EXISTS pid_alias (
  old_pid TEXT NOT NULL, new_pid TEXT NOT NULL, reason TEXT NOT NULL, effective_utc TEXT NOT NULL,
  PRIMARY KEY (old_pid, new_pid)
);
"""


@dataclass(frozen=True)
class MergeEvent:
    """An ADT A40-style merge: ``from_mrn`` is merged into the surviving ``to_mrn``."""

    from_mrn: str
    to_mrn: str
    source_event: str


@dataclass(frozen=True)
class SiteKeys:
    """Keys derived from the site root key (§7.5). The root never leaves this object."""

    k_pid: bytes
    k_lookup: bytes
    k_vault: bytes
    k_l2: bytes

    @classmethod
    def derive(cls, root: bytes, site_id: str) -> SiteKeys:
        return cls(
            k_pid=hkdf(root, site_id, "tb/pid/v1"),
            k_lookup=hkdf(root, site_id, "tb/mpi-lookup/v1"),
            k_vault=hkdf(root, site_id, "tb/vault-dek/v1"),
            k_l2=hkdf(root, site_id, "tb/l2-working/v1"),
        )


def pid_for(k_pid: bytes, mpi_id: str) -> str:
    return hmac.new(k_pid, mpi_id.encode("utf-8"), hashlib.sha256).hexdigest()[:PID_HEX_LEN]


class Mpi:
    def __init__(
        self,
        path: Path,
        keys: SiteKeys,
        *,
        clock: Clock = utc_now,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.keys = keys
        self.clock = clock
        self.new_id = id_factory or (lambda: secrets.token_hex(16))
        self.con = sqlite3.connect(str(path))
        self.con.executescript(_SCHEMA)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Mpi:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------------------------------------ lookup
    def _hmac(self, system: str, value: str) -> str:
        return hmac.new(self.keys.k_lookup, f"{system}|{value.strip()}".encode(), hashlib.sha256).hexdigest()

    def direct_id(self, system: str, value: str) -> str | None:
        row = self.con.execute(
            "SELECT mpi_id FROM mpi_identifier WHERE system = ? AND value_hmac = ?", (system, self._hmac(system, value))
        ).fetchone()
        return str(row[0]) if row else None

    def survivor(self, mpi_id: str) -> str:
        """Follow active merges to the surviving person."""
        seen = {mpi_id}
        while True:
            row = self.con.execute(
                "SELECT to_mpi_id FROM mpi_merge WHERE from_mpi_id = ? AND undone_utc IS NULL "
                "ORDER BY effective_utc DESC LIMIT 1",
                (mpi_id,),
            ).fetchone()
            if row is None or row[0] in seen:
                return mpi_id
            mpi_id = str(row[0])
            seen.add(mpi_id)

    def lookup(self, mrn: str, system: str = MRN_SYSTEM) -> str | None:
        """The surviving ``mpi_id`` of an MRN, or ``None`` when the MRN is unknown."""
        found = self.direct_id(system, mrn)
        return self.survivor(found) if found else None

    def register(self, mrn: str, system: str = MRN_SYSTEM) -> str:
        """Resolve an MRN, creating a person with a random ``mpi_id`` when it is new."""
        found = self.lookup(mrn, system)
        if found:
            return found
        mpi_id = self.new_id()
        now = iso_utc(self.clock())
        enc = aes_encrypt(self.keys.k_vault, mrn.strip().encode("utf-8"), mpi_id.encode("utf-8"))
        with self.con:
            self.con.execute("INSERT INTO mpi_person VALUES (?, 'active', ?)", (mpi_id, now))
            self.con.execute(
                "INSERT INTO mpi_identifier VALUES (?, ?, ?, ?, ?, NULL)",
                (mpi_id, system, self._hmac(system, mrn), enc, now),
            )
        return mpi_id

    def pid(self, mpi_id: str) -> str:
        return pid_for(self.keys.k_pid, self.survivor(mpi_id))

    def mrns(self, mpi_id: str) -> list[str]:
        """Decrypt the MRNs held for a person (vault-side use only; never called from L4/L5 code)."""
        rows = self.con.execute(
            "SELECT mpi_id, value_enc FROM mpi_identifier WHERE system = ?", (MRN_SYSTEM,)
        ).fetchall()
        target = self.survivor(mpi_id)
        return sorted(
            aes_decrypt(self.keys.k_vault, bytes(enc), str(mid).encode("utf-8")).decode("utf-8")
            for mid, enc in rows
            if self.survivor(str(mid)) == target
        )

    # ------------------------------------------------------------------------------------------------ merge
    def merge(self, event: MergeEvent) -> tuple[str, str]:
        """Apply an A40-style merge; idempotent per ``source_event``. Returns ``(old_pid, surviving_pid)``."""
        frm = self.register(event.from_mrn)
        to = self.register(event.to_mrn)
        old_pid, new_pid = pid_for(self.keys.k_pid, frm), pid_for(self.keys.k_pid, to)
        if frm == to:
            return old_pid, new_pid
        now = iso_utc(self.clock())
        with self.con:
            self.con.execute(
                "INSERT OR IGNORE INTO mpi_merge VALUES (?, ?, ?, ?, NULL)", (frm, to, event.source_event, now)
            )
            self.con.execute("UPDATE mpi_person SET status = 'merged' WHERE mpi_id = ?", (frm,))
            self.con.execute("INSERT OR IGNORE INTO pid_alias VALUES (?, ?, 'merge', ?)", (old_pid, new_pid, now))
        return old_pid, new_pid

    def aliases(self) -> list[tuple[str, str, str]]:
        rows = self.con.execute("SELECT old_pid, new_pid, reason FROM pid_alias ORDER BY old_pid").fetchall()
        return [(str(a), str(b), str(c)) for a, b, c in rows]


__all__ = ["MRN_SYSTEM", "MergeEvent", "Mpi", "SiteKeys", "pid_for"]
