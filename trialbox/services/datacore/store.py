"""The data core's store (D-123): schema ``datacore`` of the trial database (D-126).

* ``form``: each study's Questionnaires (FHIR JSON), from a REDCap data dictionary or TrialBox's built-in forms.
* ``value``: one row per (study, record, event, field) with the raw value, who changed it last and when, and, for
  each source, the value last seen there (``seen``) and last pushed there (``pushed``). A record is keyed by the
  TrialBox screening number or pseudonym, never a chart number or name.
* ``owner``: which side owns a field (``trialbox`` or a source name). With no source attached every field is
  TrialBox's; attaching a source hands it the fields it maps.
* ``history``: every change (old, new, by, at, source). ``conflict``: listed, never forced; resolved by a person.
* ``src_record``: the source's own record id for a TrialBox record (REDCap's record_id).
"""

from __future__ import annotations

import json
import os
from typing import Any

from tb_common.db import ENV, Database

from datacore.forms import Field, fields_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS form (study TEXT NOT NULL, name TEXT NOT NULL, body TEXT NOT NULL, origin TEXT NOT NULL,
  at TEXT NOT NULL, seq BIGINT GENERATED ALWAYS AS IDENTITY, PRIMARY KEY (study, name));
CREATE TABLE IF NOT EXISTS owner (study TEXT NOT NULL, field TEXT NOT NULL, owner TEXT NOT NULL,
  PRIMARY KEY (study, field));
CREATE TABLE IF NOT EXISTS value (study TEXT NOT NULL, record TEXT NOT NULL, event TEXT NOT NULL DEFAULT '',
  field TEXT NOT NULL, value TEXT NOT NULL, changed_by TEXT NOT NULL, changed_at TEXT NOT NULL,
  seen TEXT, pushed TEXT, PRIMARY KEY (study, record, event, field));
CREATE TABLE IF NOT EXISTS history (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  record TEXT NOT NULL, event TEXT NOT NULL, field TEXT NOT NULL, old TEXT, new TEXT NOT NULL, "by" TEXT NOT NULL,
  at TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conflict (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  record TEXT NOT NULL, event TEXT NOT NULL, field TEXT NOT NULL, owner TEXT NOT NULL, source TEXT NOT NULL,
  trialbox TEXT, theirs TEXT NOT NULL, at TEXT NOT NULL, resolved TEXT, resolved_by TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS source_cfg (study TEXT NOT NULL, name TEXT NOT NULL, body TEXT NOT NULL,
  last_sync TEXT, last_result TEXT, PRIMARY KEY (study, name));
CREATE TABLE IF NOT EXISTS src_record (study TEXT NOT NULL, source TEXT NOT NULL, record TEXT NOT NULL,
  source_id TEXT NOT NULL, PRIMARY KEY (study, source, record))
"""
TRIALBOX = "trialbox"


class DataError(ValueError):
    def __init__(self, code: str, message: str, problems: list[dict[str, str]] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.problems = problems or []  # per field: {field, code, ...} (a whole-form save, TB-PLAN-04 step 4)
        self.fields = [p["field"] for p in self.problems]


class DataCore:
    def __init__(self, url: str | None = None) -> None:
        """``url``: the trial database (``TB_DB_URL`` when ``None``)."""
        self._db = Database.connect(url or os.environ.get(ENV), "datacore")
        self._db.migrate([SCHEMA])

    def close(self) -> None:
        self._db.close()

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return self._db.fetchdicts(sql, args)

    def _run(self, sql: str, args: tuple[Any, ...]) -> None:
        self._db.execute(sql, args)

    # ------------------------------------------------------------------ forms and ownership
    def put_form(self, study: str, questionnaire: dict[str, Any], origin: str, at: str) -> None:
        self._run("INSERT INTO form (study, name, body, origin, at) VALUES (?,?,?,?,?) "
                  "ON CONFLICT(study, name) DO UPDATE SET body = excluded.body, "
                  "origin = excluded.origin, at = excluded.at",
                  (study, questionnaire["name"], json.dumps(questionnaire, ensure_ascii=False), origin,
                   at))  # fmt: skip

    def forms(self, study: str) -> list[dict[str, Any]]:
        return [json.loads(r["body"]) for r in self._all("SELECT body FROM form WHERE study = ? ORDER BY seq",
                                                         (study,))]  # fmt: skip

    def fields(self, study: str) -> dict[str, Field]:
        return {f.name: f for q in self.forms(study) for f in fields_of(q)}

    def owner(self, study: str, field: str) -> str:
        rows = self._all("SELECT owner FROM owner WHERE study = ? AND field = ?", (study, field))
        return str(rows[0]["owner"]) if rows else TRIALBOX

    def owners(self, study: str) -> dict[str, str]:
        return {r["field"]: r["owner"] for r in self._all("SELECT field, owner FROM owner WHERE study = ?", (study,))}

    def set_owner(self, study: str, field: str, owner: str) -> None:
        self._run("INSERT INTO owner (study, field, owner) VALUES (?,?,?) "
                  "ON CONFLICT(study, field) DO UPDATE SET owner = excluded.owner",
                  (study, field, owner))  # fmt: skip

    # ------------------------------------------------------------------ values
    def get(self, study: str, record: str, event: str, field: str) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM value WHERE study = ? AND record = ? AND event = ? AND field = ?",
                         (study, record, event, field))  # fmt: skip
        return rows[0] if rows else None

    def values(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        if record is None:
            return self._all("SELECT * FROM value WHERE study = ? ORDER BY record, event, field", (study,))
        return self._all("SELECT * FROM value WHERE study = ? AND record = ? ORDER BY event, field", (study, record))

    def record(self, study: str, record: str, event: str = "") -> dict[str, str]:
        return {r["field"]: r["value"] for r in self.values(study, record) if r["event"] == event}

    def records(self, study: str) -> list[str]:
        return [r["record"] for r in self._all("SELECT DISTINCT record FROM value WHERE study = ? ORDER BY record",
                                               (study,))]  # fmt: skip

    def write(self, study: str, record: str, event: str, field: str, value: str, by: str, at: str, source: str,
              seen: str | None = None, keep_seen: bool = True) -> bool:  # fmt: skip
        """Set a value (no ownership check here; ``DataService`` and ``SyncEngine`` check). False if unchanged."""
        with self._db.transaction() as tx:
            rows = tx.fetchdicts("SELECT * FROM value WHERE study = ? AND record = ? AND event = ? AND field = ? "
                                 "FOR UPDATE", (study, record, event, field))  # fmt: skip
            cur = rows[0] if rows else None
            if cur is not None and cur["value"] == value and (seen is None or cur["seen"] == seen):
                return False
            new_seen = seen if seen is not None else (cur["seen"] if cur and keep_seen else None)
            tx.execute(
                "INSERT INTO value (study, record, event, field, value, changed_by, changed_at, seen, pushed) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(study, record, event, field) DO UPDATE SET "
                "value = excluded.value, changed_by = excluded.changed_by, changed_at = excluded.changed_at, "
                "seen = excluded.seen",
                (study, record, event, field, value, by, at, new_seen, cur["pushed"] if cur else None),
            )
            if cur is None or cur["value"] != value:
                tx.execute(
                    'INSERT INTO history (study, record, event, field, old, new, "by", at, source) VALUES '
                    "(?,?,?,?,?,?,?,?,?)",
                    (study, record, event, field, cur["value"] if cur else None, value, by, at, source),
                )
            return True

    def mark(self, study: str, record: str, event: str, field: str, *, seen: str | None = None,
             pushed: str | None = None) -> None:  # fmt: skip
        if seen is not None:
            self._run("UPDATE value SET seen = ? WHERE study = ? AND record = ? AND event = ? AND field = ?",
                      (seen, study, record, event, field))  # fmt: skip
        if pushed is not None:
            self._run("UPDATE value SET pushed = ? WHERE study = ? AND record = ? AND event = ? AND field = ?",
                      (pushed, study, record, event, field))  # fmt: skip

    def history(self, study: str, record: str | None = None) -> list[dict[str, Any]]:
        if record is None:
            return self._all("SELECT * FROM history WHERE study = ? ORDER BY id", (study,))
        return self._all("SELECT * FROM history WHERE study = ? AND record = ? ORDER BY id", (study, record))

    # ------------------------------------------------------------------ conflicts
    def add_conflict(self, study: str, record: str, event: str, field: str, owner: str, source: str,
                     trialbox: str | None, theirs: str, at: str) -> int | None:  # fmt: skip
        """List a conflict once (the same open conflict is not listed twice)."""
        same = self._all("SELECT id FROM conflict WHERE study = ? AND record = ? AND event = ? AND field = ? AND "
                         "source = ? AND theirs = ? AND resolved IS NULL",
                         (study, record, event, field, source, theirs))  # fmt: skip
        if same:
            return None
        with self._db.transaction() as tx:
            return int(tx.fetchval(
                "INSERT INTO conflict (study, record, event, field, owner, source, trialbox, theirs, at) VALUES "
                "(?,?,?,?,?,?,?,?,?) RETURNING id",
                (study, record, event, field, owner, source, trialbox, theirs, at),
            ))  # fmt: skip

    def conflicts(self, study: str, open_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM conflict WHERE study = ?" + (" AND resolved IS NULL" if open_only else "") + " ORDER BY id"
        return self._all(sql, (study,))

    def conflict(self, cid: int) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM conflict WHERE id = ?", (cid,))
        return rows[0] if rows else None

    def close_conflict(self, cid: int, keep: str, by: str, at: str) -> None:
        self._run("UPDATE conflict SET resolved = ?, resolved_by = ?, resolved_at = ? WHERE id = ?",
                  (keep, by, at, cid))  # fmt: skip

    # ------------------------------------------------------------------ source record ids
    def source_id(self, study: str, source: str, record: str) -> str | None:
        rows = self._all("SELECT source_id FROM src_record WHERE study = ? AND source = ? AND record = ?",
                         (study, source, record))  # fmt: skip
        return str(rows[0]["source_id"]) if rows else None

    def put_source_id(self, study: str, source: str, record: str, source_id: str) -> None:
        self._run("INSERT INTO src_record (study, source, record, source_id) VALUES (?,?,?,?) "
                  "ON CONFLICT(study, source, record) DO UPDATE SET "
                  "source_id = excluded.source_id", (study, source, record, source_id))  # fmt: skip

    # ------------------------------------------------------------------ source settings
    def put_source(self, study: str, name: str, body: dict[str, Any]) -> None:
        self._run("INSERT INTO source_cfg (study, name, body) VALUES (?,?,?) ON CONFLICT(study, name) DO UPDATE SET "
                  "body = excluded.body", (study, name, json.dumps(body, ensure_ascii=False)))  # fmt: skip

    def drop_source(self, study: str, name: str) -> None:
        self._run("DELETE FROM source_cfg WHERE study = ? AND name = ?", (study, name))

    def sources(self, study: str) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM source_cfg WHERE study = ? ORDER BY name", (study,))
        for r in rows:
            r["body"] = json.loads(r["body"])
            r["last_result"] = json.loads(r["last_result"]) if r["last_result"] else None
        return rows

    def synced(self, study: str, name: str, at: str, result: dict[str, Any]) -> None:
        self._run("UPDATE source_cfg SET last_sync = ?, last_result = ? WHERE study = ? AND name = ?",
                  (at, json.dumps(result, ensure_ascii=False), study, name))  # fmt: skip
