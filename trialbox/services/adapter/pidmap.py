"""Reverse pseudonym table ``pid -> MRN`` (SPEC §4.6), kept only in the box.

MRNs are stored AES-256-GCM encrypted (associated data = pid) with a key from ``secrets/pid_map.key``; the key file
is TPM-sealed on the appliance (DECISIONS D-10). Used solely to render MRNs into lists for internal recipients.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tb_common.crypto import aes_decrypt, aes_encrypt, load_or_create_key


class PidMap:
    def __init__(self, db_path: Path, key_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.key = load_or_create_key(key_path)
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS pid_map "
            "(pid TEXT PRIMARY KEY, mrn BLOB NOT NULL, first_seen TEXT, last_seen TEXT)"
        )
        # identity for NHI submissions (name, national id), AES-GCM like the MRN; read only to build TWPAS bundles
        self.con.execute("CREATE TABLE IF NOT EXISTS identity (pid TEXT PRIMARY KEY, blob BLOB NOT NULL)")
        db_path.chmod(0o600)

    def upsert_many(self, pairs: list[tuple[str, str]]) -> int:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        existing = {r[0] for r in self.con.execute("SELECT pid FROM pid_map")}
        new = [
            (pid, aes_encrypt(self.key, mrn.encode(), pid.encode()), now, now)
            for pid, mrn in pairs
            if pid not in existing
        ]
        self.con.executemany("INSERT INTO pid_map VALUES (?,?,?,?)", new)
        self.con.executemany(
            "UPDATE pid_map SET last_seen=? WHERE pid=?", [(now, p) for p, _ in pairs if p in existing]
        )
        self.con.commit()
        return len(new)

    def upsert_identity(self, rows: list[tuple[str, dict[str, str]]]) -> None:
        import json

        self.con.executemany(
            "INSERT OR REPLACE INTO identity VALUES (?,?)",
            [
                (pid, aes_encrypt(self.key, json.dumps(v, ensure_ascii=False, sort_keys=True).encode(), pid.encode()))
                for pid, v in rows
            ],
        )
        self.con.commit()

    def identity(self, pid: str) -> dict[str, str] | None:
        import json

        row = self.con.execute("SELECT blob FROM identity WHERE pid=?", (pid,)).fetchone()
        if row is None:
            return None
        data: dict[str, str] = json.loads(aes_decrypt(self.key, bytes(row[0]), pid.encode()))
        return data

    def resolve(self, pid: str) -> str | None:
        row = self.con.execute("SELECT mrn FROM pid_map WHERE pid=?", (pid,)).fetchone()
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
        self.con.close()
