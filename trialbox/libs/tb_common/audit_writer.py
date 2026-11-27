"""One audit writer (T-211b, D-394, register CR-042): the services hand their events to the database; one process writes
the chain.

Before this, six service containers mounted the audit volume read-write and each appended to the hash chain itself
(:class:`tb_common.audit.AuditLog`): any of them could rewrite history. Now:

* **The journal.** ``audit.journal`` in the trial database is append-only. Its schema, the table and the one way in,
  ``audit.append(event, ts, fields)``, belong to ``audit_writer``: a role nobody signs in as, and no service can
  become (its one member is ``trialbox``, the host tools' admin, which drops and restores schemas as for every store
  group of D-378). The function is ``SECURITY DEFINER``, so it inserts as ``audit_writer``; it records the signed-in
  role (``session_user``), which the caller cannot choose. The service roles of D-378 may only call it: they cannot
  insert, read, change or delete a row. ``audit_writer`` itself has no UPDATE, DELETE or TRUNCATE, and a trigger
  refuses all three to everyone, the superuser included. The SQL is :data:`JOURNAL_SQL`; the role script
  ``deploy/docker/db-init/30-service-roles.sh`` runs it (``tests/unit/test_audit_writer.py`` checks they match).
* **The services** call :func:`open_audit` instead of building an ``AuditLog``. With ``TB_AUDIT_WRITER=db`` (each
  service in ``deploy/docker-compose.yml``) it returns a :class:`DbAuditWriter`: ``append`` calls ``audit.append``
  over the service's own ``TB_DB_URL``; the service mounts the audit volume read-only (its pages read the chain).
  Unset, it returns the file writer as before (a developer shell, the tests, the single-process demos).
* **The drain** (``python -m tb_common.audit_writer drain``, the ``audit-writer`` service, role ``tb_audit_writer``
  with SELECT on the journal and nothing else) is the only process that writes the chain. It appends each journal row
  in ``seq`` order through ``AuditLog`` with ``journal: {seq, role, at}``, so the chain says which database role
  sent each event. Where it stands is read back from the chain (the last line with a ``journal``), never kept
  elsewhere. ``audit.append`` takes a lock, so ``seq`` order is commit order and no row is passed over.
* **A journal that does not match the chain** (the database restored to an older point, as an update rollback does,
  or replaced): the row the chain names last is gone or different. The drain records an ``audit.journal_resync``
  event (what the chain said, what the journal holds) and goes on with the rows written after the chain's last one,
  so nothing written since is passed over and the gap is visible in the chain.

A disk-full or broken-anchor chain stops the drain, not the services: the events wait in the journal, and the drain
writes them when a person has fixed the chain (``tools/audit_verify.py``).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import logging
import math
import os
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tb_common.audit import AuditLog, _day_files, lines_backward
from tb_common.db import split_url

log = logging.getLogger("tb.audit_writer")

#: ``TB_AUDIT_WRITER``: ``db`` sends events to the journal; empty or ``file`` writes the chain in-process.
MODE_ENV = "TB_AUDIT_WRITER"
#: The drain's heartbeat (the compose health check reads its age).
ALIVE = Path(os.environ.get("TB_AUDIT_WRITER_ALIVE") or Path(tempfile.gettempdir()) / "tb-audit-writer.alive")
NOTIFY = "tb_audit"

# BEGIN JOURNAL SQL (D-394)
JOURNAL_SQL = """\
DO $aw$
DECLARE
  m record;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'audit_writer') THEN
    CREATE ROLE audit_writer NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tb_audit_writer') THEN
    CREATE ROLE tb_audit_writer LOGIN;
  END IF;
  -- no service acts as the journal's owner: its one member is trialbox, the host tools' admin (backup, restore),
  -- as for every store group of D-378
  FOR m IN SELECT pg_get_userbyid(member) AS who, pg_get_userbyid(grantor) AS by FROM pg_auth_members
           WHERE roleid = 'audit_writer'::regrole AND member <> 'trialbox'::regrole LOOP
    EXECUTE format('REVOKE audit_writer FROM %I GRANTED BY %I', m.who, m.by);
  END LOOP;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO tb_audit_writer', current_database());
END
$aw$;
GRANT audit_writer TO trialbox;
ALTER ROLE audit_writer NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE tb_audit_writer LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE SCHEMA IF NOT EXISTS audit AUTHORIZATION audit_writer;
ALTER SCHEMA audit OWNER TO audit_writer;
REVOKE ALL ON SCHEMA audit FROM PUBLIC;
SET search_path = audit, pg_catalog;
CREATE TABLE IF NOT EXISTS journal (
  seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT clock_timestamp(),
  db_role text NOT NULL,
  event text NOT NULL CHECK (event <> ''),
  ts text NOT NULL,
  fields jsonb NOT NULL
);
RESET search_path;
ALTER TABLE audit.journal OWNER TO audit_writer;
CREATE OR REPLACE FUNCTION audit.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
  RAISE EXCEPTION 'audit.journal is append-only (D-394): % refused', TG_OP USING ERRCODE = 'insufficient_privilege';
END
$fn$;
ALTER FUNCTION audit.refuse_change() OWNER TO audit_writer;
DROP TRIGGER IF EXISTS journal_append_only ON audit.journal;
CREATE TRIGGER journal_append_only BEFORE UPDATE OR DELETE ON audit.journal
  FOR EACH ROW EXECUTE FUNCTION audit.refuse_change();
DROP TRIGGER IF EXISTS journal_no_truncate ON audit.journal;
CREATE TRIGGER journal_no_truncate BEFORE TRUNCATE ON audit.journal
  FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_change();
REVOKE ALL ON audit.journal FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON audit.journal FROM audit_writer;
CREATE OR REPLACE FUNCTION audit.append(p_event text, p_ts text, p_fields jsonb) RETURNS bigint
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  n bigint;
BEGIN
  -- one at a time, to the end of the transaction: seq order is commit order, so the drain passes no row over
  PERFORM pg_advisory_xact_lock(211394);
  INSERT INTO audit.journal (db_role, event, ts, fields)
    VALUES (session_user, p_event, p_ts, coalesce(p_fields, '{}'::jsonb)) RETURNING seq INTO n;
  PERFORM pg_notify('tb_audit', n::text);
  RETURN n;
END
$fn$;
ALTER FUNCTION audit.append(text, text, jsonb) OWNER TO audit_writer;
REVOKE ALL ON FUNCTION audit.append(text, text, jsonb), audit.refuse_change() FROM PUBLIC;
GRANT USAGE ON SCHEMA audit TO tb_lake, tb_criteria_compiler, tb_adapter, tb_orchestrator, tb_mail_gateway,
  tb_gateway, tb_console, tb_audit_writer, trialbox;
GRANT EXECUTE ON FUNCTION audit.append(text, text, jsonb) TO tb_lake, tb_criteria_compiler, tb_adapter,
  tb_orchestrator, tb_mail_gateway, tb_gateway, tb_console;
-- the drain reads the journal; trialbox (backups) reads it; nobody else does
GRANT SELECT ON audit.journal TO tb_audit_writer, trialbox;
"""
# END JOURNAL SQL


class AuditUnavailable(OSError):
    """The journal could not take the event: the action must not go ahead unlogged."""


def _psycopg() -> Any:
    return importlib.import_module("psycopg")


def _dsn(url: str) -> str:
    return split_url(url)[0]


class DbAuditWriter(AuditLog):
    """An :class:`AuditLog` whose ``append`` goes to ``audit.append`` in the trial database. ``directory`` is where
    the chain is read (a read-only mount); this writer never touches it."""

    def __init__(self, directory: Path, tz: str, *, url: str) -> None:
        # no AuditLog.__init__: it would make the (read-only) directory
        self.directory = directory
        self.zone = ZoneInfo(tz)
        self._dsn = _dsn(url)
        self._con: Any = None
        self._mutex = threading.Lock()

    def _call(self, event: str, stamp: str, payload: str) -> int:
        psycopg = _psycopg()
        last: Exception | None = None
        for _ in range(2):  # a lost connection is opened again once
            try:
                if self._con is None or self._con.closed:
                    self._con = psycopg.connect(self._dsn, autocommit=True, connect_timeout=10)
                row = self._con.execute("SELECT audit.append(%s, %s, %s::jsonb)", (event, stamp, payload)).fetchone()
                return int(row[0])
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                last = exc
                self._con = None
            except psycopg.Error as exc:
                raise AuditUnavailable(f"the audit journal refused the event: {type(exc).__name__}: {exc}") from exc
        raise AuditUnavailable(f"the audit journal cannot be reached: {type(last).__name__}") from last

    def append(self, event: str, *, ts: datetime | None = None, **fields: Any) -> dict[str, Any]:
        """Send one event to the journal. Returns the record as the chain will hold it, without its hash (the drain
        chains it), and with ``journal.seq``."""
        if "journal" in fields:
            raise ValueError("'journal' is set by the audit writer, not by the caller")
        now = ts or datetime.now(self.zone)
        if now.tzinfo is None:
            raise ValueError("audit timestamps must be timezone-aware")
        stamp = now.isoformat(timespec="milliseconds")
        payload = json.dumps(fields, sort_keys=True, ensure_ascii=False)  # what the chain cannot hold fails here
        with self._mutex:
            seq = self._call(event, stamp, payload)
        body: dict[str, Any] = {"ts": stamp, "event": event}
        detail: dict[str, Any] = dict(fields.pop("detail", None) or {})
        for key, val in fields.items():
            if key in self.FIELDS:
                if val is not None:
                    body[key] = val
            else:
                detail[key] = val
        if detail:
            body["detail"] = detail
        body["journal"] = {"seq": seq}
        return body

    def close(self) -> None:
        with self._mutex:
            if self._con is not None:
                self._con.close()
                self._con = None


def open_audit(directory: Path | None = None, tz: str | None = None, env: Mapping[str, str] | None = None) -> AuditLog:
    """The audit writer a service uses: the journal when ``TB_AUDIT_WRITER=db``, else the chain in ``directory``
    (default ``TB_AUDIT_DIR``, then ``/data/audit``). The one place a service gets a writer (CR-042)."""
    e = os.environ if env is None else env
    where = directory if directory is not None else Path(e.get("TB_AUDIT_DIR") or "/data/audit")
    mode = (e.get(MODE_ENV) or "file").strip().lower()
    if mode == "db":
        url = e.get("TB_DB_URL") or ""
        if not url:
            raise ValueError(f"{MODE_ENV}=db needs TB_DB_URL (the service's own database role)")
        from tb_common.config import site_tz

        return DbAuditWriter(where, site_tz(tz, e), url=url)
    if mode != "file":
        raise ValueError(f"{MODE_ENV} must be 'db' or 'file', got {mode!r}")
    return AuditLog(where, tz) if tz else AuditLog(where)  # no zone given: the file writer's own, as before


# ------------------------------------------------------------------------------------------------ the drain
@dataclass(frozen=True)
class Cursor:
    seq: int
    at: str  # the journal row's insert time, ISO 8601


def last_drained(directory: Path) -> Cursor | None:
    """The last journal row in the chain (newest day file first), or None when no event came from the journal."""
    for path in reversed(_day_files(directory)):
        for line in lines_backward(path):  # T-697: from the end, never the whole day file
            try:
                rec = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue  # a torn last line: AuditLog repairs it on the next write
            j = rec.get("journal") if isinstance(rec, dict) else None
            if isinstance(j, dict) and "seq" in j:
                return Cursor(int(j["seq"]), str(j.get("at") or ""))
    return None


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _same_time(a: str, b: str) -> bool:
    try:
        return datetime.fromisoformat(a) == datetime.fromisoformat(b)
    except ValueError:
        return a == b


# ---------------------------------------------------------------------------------- who may say what (T-721, D-488)
ADMIN_ROLE = "trialbox"  # the host's administrator role (`trialbox` tools, migrations): not judged
SKEW_ENV = "TB_AUDIT_TS_MAX_SKEW_S"
#: The event families (the part of an event's name before the first dot) each service's database role writes. The
#: journal records the role (``session_user``), which the sender cannot choose; the event's name, its actor and
#: its time are the sender's. A row whose family is not its role's is marked by the drain, never dropped: the
#: chain keeps what was sent, and says it should not have come from there.
#: ``tests/unit/test_audit_roles.py`` holds this table against the code. The console and the orchestrator host the
#: shared libraries (and helpers of each other): their rows cover every family written anywhere in the modules
#: they import. A service that reads outside input (mail, model output, hospital files, protocols) has the
#: narrowest row: exactly what its own folder writes, plus :data:`EDGE_EXTRA`, each with its reason.
_SHARED = ("ai", "flag", "flow", "llm", "mail")  # written through tb_common by the service that hosts the call
#: NEW-SEC-2 (D-718): the chain's own records. Its writers write them themselves (the drain, the file writer, the
#: host's signer); none comes through the journal. A row of this family from any role but the audit's own writer and
#: the administrator is written under :data:`RESERVED_NAME`, with the name it was sent as (security review SEC-10).
RESERVED = "audit"
RESERVED_NAME = "journal.reserved_name"
_ORCH = ("actor", "case", "cohort", "consent", "data", "derive", "edc", "feas", "job", "lake", "life", "microbatch",
         "nav", "notice", "notmatched", "opportunity", "optout", "redcap", "registry", "rerun", "retention",
         "scheduler", "screen", "selftest", "service", "setup", "sponsor", "study", "terminology", "twpas")  # fmt: skip
_CONSOLE = ("console", "demo", "edc", "feedback", "instrument", "notmatched", "optout", "registry",
            "setup", "sponsor", "terminology")  # fmt: skip
#: The host's `trialbox` tools (backup, update, watchdog, the operations runner) and `deploy/install.sh` send their
#: events from inside the orchestrator's container (`compose exec -T orchestrator python -c "... open_audit()"`),
#: so the journal records them under the orchestrator's role, not the administrator's (the review's H1).
_HOST_TOOLS = ("backup", "ops", "update")
#: one event of another role's family that a role sends, each with its reason (never the whole family)
EXACT_EVENTS: dict[str, dict[str, str]] = {
    "tb_orchestrator": {
        "console.ops": "the operations runner of the host (tools/trialbox/ops.py) sends it from the "
        "orchestrator's container",
        # D-718: the one record of the chain's own family that comes through the journal. verify trusts no event of
        # it: the signed heads are read from the anchor folders, and a key rotation never from the journal
        "audit.head_signed": "the host's nightly signer (trialbox audit-sign) records its head from the "
        "orchestrator's container",
    },
}
#: what an edge service writes beyond its own folder's events, and why
EDGE_EXTRA: dict[str, dict[str, str]] = {
    "tb_criteria_compiler": {
        "llm": "its model calls go through tb_common.llm, which audits them in the caller's log",
        "ai": "an extracted criterion's ai.used and a review decision's ai.confirmed go through tb_common.provenance "
        "(D-989)",
    },
}
ROLE_EVENTS: dict[str, frozenset[str]] = {
    "tb_console": frozenset({*_CONSOLE, *_SHARED}),
    "tb_orchestrator": frozenset({*_ORCH, *_SHARED, *_HOST_TOOLS, "dataops"}),  # it imports datacore.dataops
    "tb_mail_gateway": frozenset({"mail"}),
    "tb_gateway": frozenset({"llm"}),
    "tb_lake": frozenset({"lake"}),
    "tb_adapter": frozenset({"ingest", "terminology"}),
    "tb_criteria_compiler": frozenset({"ai", "approve", "compile", "ctgov", "llm"}),
    "tb_audit_writer": frozenset({"audit", "journal"}),  # D-718: the drain's own record of a reserved name
}


def max_skew() -> float:
    """How far an event's own time may be from the time the journal received it, in seconds (``TB_AUDIT_TS_MAX_SKEW_S``,
    default 300). A service stamps an event when it happens and sends it in the same request, to a database on the
    same host, so the two differ by the length of a transaction; five minutes is a slow one. It is a setting, not a
    constant, because a site with a database on another host may need more (OD-10)."""
    try:
        value = float(os.environ.get(SKEW_ENV) or 300)
    except ValueError:
        return 300.0
    # not a number of seconds (inf, nan, below zero): the default, so that no value switches the mark off
    return value if math.isfinite(value) and value >= 0 else 300.0


def foreign(role: str, event: str) -> str:
    """Why this event should not have come from this database role ("" when it may): ``role`` when the event's
    family is not one the role writes, ``unknown role`` for a role the table does not know."""
    if role == ADMIN_ROLE:
        return ""
    allowed = ROLE_EVENTS.get(role)
    if allowed is None:
        return "unknown role"
    if event.split(".", 1)[0] in allowed or event in EXACT_EVENTS.get(role, {}):
        return ""
    return "role"


def flags_of(role: str, event: str, ts: datetime, at: Any) -> list[str]:
    """The marks of one journal row: ``role`` / ``unknown role`` (:func:`foreign`) and ``time`` when the event's own
    time is further than :func:`max_skew` from the journal's (a back-dated or post-dated event)."""
    out = [why] if (why := foreign(role, event)) else []
    try:
        received = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
        if abs((ts - received).total_seconds()) > max_skew():
            out.append("time")
    except (TypeError, ValueError):  # a time that cannot be compared is not a time the journal agrees with
        out.append("time")
    return out


def flagged(directory: Path) -> list[dict[str, Any]]:
    """Every chain record the drain marked, oldest first: ``{seq, role, event, ts, at, actor, flag}``. What
    ``tools/audit_verify.py --foreign`` prints."""
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                j = rec.get("journal") if isinstance(rec, dict) else None
                if isinstance(j, dict) and j.get("flag"):
                    out.append({"seq": j.get("seq"), "role": j.get("role"), "event": rec.get("event"),
                                "ts": rec.get("ts"), "at": j.get("at"), "actor": rec.get("actor"),
                                "flag": list(j["flag"])})  # fmt: skip
    return out


# What a sender may not set in a journal row's fields: the chain's own keys (security review 2026-11-13). Before,
# a row whose fields held ``ts`` or ``event``, a ``detail`` that was not an object, or a time without a zone stopped
# the drain with a TypeError or ValueError on every start, and the journal is append-only: no event after that row
# reached the chain again. Such values are kept under ``detail`` and the row is marked, never dropped.
_RESERVED = ("ts", "event", "journal", "hash", "prev_hash", "self")


def _readable(at: Any, ts: Any, fields: Any) -> tuple[dict[str, Any], datetime, list[str]]:
    """The fields, the time and what was wrong with one journal row, so that every row can be written."""
    problem: list[str] = []
    try:
        raw = fields if isinstance(fields, dict) else json.loads(fields or "{}")
    except (TypeError, ValueError):
        raw, problem = {"value": str(fields)[:2000]}, ["fields"]
    if not isinstance(raw, dict):
        raw, problem = {"value": raw}, ["fields"]
    f = dict(raw)
    detail = f.pop("detail", None)
    if detail is not None and not isinstance(detail, dict):
        detail, problem = {"value": detail}, [*problem, "detail"]
    detail = dict(detail or {})
    for key in _RESERVED:
        if key in f:
            val = f.pop(key)
            if key != "journal":  # the drain's own record; a sender's copy was always dropped
                detail[f"sent_{key}"] = val
                problem.append(key)
    if detail:
        f["detail"] = detail
    try:
        stamp = datetime.fromisoformat(str(ts))
        if stamp.tzinfo is None:
            raise ValueError("no zone")
    except (TypeError, ValueError):
        stamp = datetime.fromisoformat(_iso(at))  # the journal's own time of the row; the sent text goes in journal
        problem.append("time")
    return f, stamp, problem


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Drain:
    """Copies the journal into the chain in ``directory``, in ``seq`` order; the only writer of the chain on a box."""

    BATCH = 500
    RETRY = 60.0  # P-19: seconds before a catch-up that failed is tried again (it reads the whole chain)

    def __init__(self, url: str, directory: Path, tz: str, *, connect: Callable[[], Any] | None = None):
        self.chain = AuditLog(directory, tz)
        self.directory = directory
        self._dsn = _dsn(url)
        self._connect = connect or (lambda: _psycopg().connect(self._dsn, autocommit=True, connect_timeout=10))
        self.con: Any = None
        self.cursor: Cursor | None = None
        self._after: str | None = None  # after a resync: the next batch is the rows inserted after this time
        self.index = False  # D-989 step 2c: write the provenance index as the chain is written (when installed)
        self._recover = False  # P-19: a repair is owed (mirrors the marker in the audit directory, not the truth)
        self._retry = 0.0  # P-19: the monotonic time from which a failed catch-up is tried again

    def open(self) -> None:
        from tb_common import provenance_index

        self.con = self._connect()
        self.con.execute(f"LISTEN {NOTIFY}")
        self.index = self._index_installed(say=True)  # said once: the drain asks again before each batch (P-19)
        prev = provenance_index.read_state(self.directory)
        # P-19: every start owes a repair, whatever the journal says (review P19-D3) and whether or not the index
        # can be read now (D5): only a completed catch-up clears it
        owed: dict[str, Any] = {"state": provenance_index.REQUIRED, "reason": str(prev.get("reason") or "start"),
                                "since": prev.get("since") or _now(),
                                "attempts": int(prev.get("attempts") or 0)}  # fmt: skip
        self.cursor = last_drained(self.directory)
        row = (
            None
            if self.cursor is None
            else self.con.execute("SELECT at FROM audit.journal WHERE seq = %s", (self.cursor.seq,)).fetchone()
        )
        if self.cursor is not None and not (row is not None and _same_time(_iso(row[0]), self.cursor.at)):
            top = self.con.execute("SELECT coalesce(max(seq), 0) FROM audit.journal").fetchone()[0]
            problem = (
                f"the chain's last journal row is seq {self.cursor.seq} at {self.cursor.at}, but the journal "
                + ("has no such row" if row is None else f"has it at {_iso(row[0])}")
                + f" (its last row is seq {top}): the database was restored or replaced"
            )
            log.error("%s: recorded as audit.journal_resync; going on with the rows written after it", problem)
            self.chain.append("audit.journal_resync", actor="tb_common.audit_writer",
                              detail={"chain_seq": self.cursor.seq, "chain_at": self.cursor.at,
                                      "journal_last": int(top), "problem": problem})  # fmt: skip
            self._after = self.cursor.at
            owed.update(reason="resync", chain_seq=self.cursor.seq, journal_last=int(top))
        provenance_index.write_state(self.directory, **owed)
        self._recover, self._retry = True, 0.0
        if self.index:
            self._catch_up()

    def _index_installed(self, *, say: bool = False) -> bool:
        """Whether the provenance index's tables are there (the role script creates them, D-989 step 2c). Without
        them the drain writes the chain alone, and ``trialbox doctor`` says the index is not installed. ``say``:
        log a confirmed absence (a probe that fails is logged apart, review P19-D5)."""
        from tb_common import provenance_index

        try:
            ok = provenance_index.installed(self.con)
        except Exception as exc:  # an index that cannot be read never stops the drain
            log.warning("provenance index: could not be read (%s)", type(exc).__name__)
            return False
        if not ok and say:
            log.info("provenance index not installed: the chain is written without it")
        return ok

    def _catch_up(self) -> None:
        """P-19: the index's rows of every chain line it does not hold, then the register's sweep
        (``provenance_index.catch_up``, ``sweep``); the marker says ``repairing`` while it runs and ``clean`` only
        after both. Never raised: a failure is logged and stays owed, and ``step`` tries it again after
        :attr:`RETRY` seconds until it is done (review P19-R4)."""
        from tb_common import provenance_index as pi

        owed = {k: v for k, v in pi.read_state(self.directory).items() if k not in ("state", "by", "updated_at")}
        by = {"pid": os.getpid(), "host": socket.gethostname(), "start": _now()}  # diagnostic only
        pi.write_state(self.directory, **{**owed, "state": pi.REPAIRING, "by": by})
        try:
            n = pi.catch_up(self.con, self.directory)
            k = pi.sweep(self.con)
        except Exception as exc:
            with contextlib.suppress(Exception):  # a connection that is not autocommit is usable again (N3)
                self.con.rollback()
            pi.write_state(self.directory, **{**owed, "state": pi.REQUIRED, "reason": "repair failed",
                                              "attempts": int(owed.get("attempts") or 0) + 1,
                                              "last_error": type(exc).__name__})  # fmt: skip
            self._retry = time.monotonic() + self.RETRY
            log.error("provenance index: the repair did not finish (%s); tried again in %.0f s", type(exc).__name__,
                      self.RETRY)  # fmt: skip
            return
        pi.write_state(self.directory, state=pi.CLEAN, verified_at=_now(), rows_written=n)
        self._recover = False
        if n or k:
            log.info("provenance index: %d row(s) of the chain written back, %d withheld row(s) swept", n, k)

    def _index(self, rec: dict[str, Any]) -> None:
        """The record's rows in the provenance index, after its line is in the chain. A write that fails is logged,
        never raised: the chain is the record, and the repair it makes owed puts the rows back."""
        from tb_common import provenance_index as pi

        try:
            pi.add(self.con, rec)
        except Exception as exc:
            log.error("provenance index: a row was not written (%s); put back by the audit writer",
                      type(exc).__name__)  # fmt: skip
            prev = pi.read_state(self.directory)
            # the line is in the chain already: a marker that cannot be written must not write it twice; the next
            # start owes the repair anyway
            with contextlib.suppress(OSError):
                pi.write_state(self.directory, state=pi.REQUIRED, reason="index write failed",
                               since=prev.get("since") or _now(), attempts=int(prev.get("attempts") or 0))  # fmt: skip
            self._recover = True
            self._retry = time.monotonic() + self.RETRY

    def _sweep(self) -> None:
        """P-19: after a batch that drained an opt-out, the register's sweep (logged, never raised)."""
        from tb_common import provenance_index

        try:
            k = provenance_index.sweep(self.con)
        except Exception as exc:
            log.error("provenance index: the sweep after an opt-out failed (%s)", type(exc).__name__)
            return
        if k:
            log.info("provenance index: %d withheld row(s) swept after an opt-out", k)

    def _rows(self) -> list[tuple[Any, ...]]:
        cols = "SELECT seq, at, db_role, event, ts, fields FROM audit.journal"
        args: tuple[Any, ...]
        if self._after is not None:
            q, args = f"{cols} WHERE at > %s::timestamptz ORDER BY seq LIMIT %s", (self._after, self.BATCH)
        else:
            q, args = (
                f"{cols} WHERE seq > %s ORDER BY seq LIMIT %s",
                (self.cursor.seq if self.cursor else 0, self.BATCH),
            )
        return list(self.con.execute(q, args).fetchall())

    def step(self, alive: Path | None = None) -> int:
        """Write the next batch to the chain; the number written. ``alive``: the heartbeat, touched after each event
        (T-697: a batch of slow writes must not read as a dead drain to the health check)."""
        from tb_common.provenance_index import OPT_OUT

        rows = self._rows()
        # P-19: tables made after the drain started are written from the next line on, and a repair owed before
        # they existed runs once they do (review P19-D5)
        if not self.index and (rows or self._recover):
            self.index = self._index_installed()
        if self._recover and self.index and time.monotonic() >= self._retry:
            self._catch_up()
        opted = False
        for seq, at, role, event, ts, fields in rows:
            f, stamp, problem = _readable(at, ts, fields)
            journal: dict[str, Any] = {"seq": int(seq), "role": role, "at": _iso(at)}
            if problem:  # security review 2026-11-13: a malformed row is written, marked; it never stops the drain
                journal["unreadable"] = problem
                if "time" in problem:  # the time the sender wrote, where the sender cannot write
                    journal["sent_ts"] = str(ts)[:64]
            # T-721 (D-488): who may say what, and when. The mark is part of the record the event is written in,
            # so there is no moment at which the event is in the chain without it.
            marks = flags_of(str(role), str(event), stamp, at) + (["unreadable"] if problem else [])
            # the audit's family, and the drain's own (a service sending `journal.reserved_name` itself)
            if str(event).split(".", 1)[0] in (RESERVED, "journal") and foreign(str(role), str(event)):
                # D-718: never a record of the chain's own family from a service; what was sent is kept, flagged
                f["detail"] = {**dict(f.get("detail") or {}), "sent_event": str(event)[:120]}
                event = RESERVED_NAME
                marks.append("reserved")
            if marks:  # an unreadable row is flagged too, so `flagged()` and `audit_verify --foreign` list it
                journal["flag"] = marks
                # the event's name is the sender's own text: it stays in the record, not in the log line
                log.warning("audit journal row %s from %s marked %s", seq, role, ", ".join(marks))
            rec = self.chain.append(event, ts=stamp, journal=journal, **f)
            opted = opted or rec.get("event") == OPT_OUT
            if self.index:
                self._index(rec)
            self.cursor = Cursor(int(seq), _iso(at))
            self._after = None
            if alive is not None:
                with contextlib.suppress(OSError):
                    alive.touch()
        if opted and self.index:
            self._sweep()
        return len(rows)

    def wait(self, timeout: float) -> None:
        """Until a new row is announced or ``timeout`` seconds pass."""
        for _ in self.con.notifies(timeout=timeout, stop_after=1):
            break

    def run(self, *, once: bool = False, poll: float = 1.0, alive: Path | None = ALIVE) -> int:
        """Drain until stopped (``once``: until the journal is empty). A chain that cannot take a write (disk full, a
        broken anchor) stops ``once`` with the error, and the loop retries it: after a minute, then twice as long each
        time up to an hour (R22-36: a chain that waits for a person is not asked every minute). Returns the count."""
        total = 0
        delay = 60
        while True:
            try:
                n = self.step(alive)
            except OSError as exc:
                if once:
                    raise
                log.error("the audit chain refused a write (%s): retrying in %d s", exc, delay)
                time.sleep(delay)
                delay = min(delay * 2, 3600)
                continue
            delay = 60
            total += n
            if alive is not None:
                with contextlib.suppress(OSError):
                    alive.touch()
            if n:
                continue
            if once:
                return total
            self.wait(poll)


def main(argv: Sequence[str] | None = None) -> int:
    from tb_common.config import site_tz

    p = argparse.ArgumentParser(
        prog="python -m tb_common.audit_writer", description=(__doc__ or "").split("\n\n", 1)[0]
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drain", help="copy the audit journal into the chain (the audit-writer service)")
    d.add_argument("--once", action="store_true", help="stop when the journal is empty")
    a = p.parse_args(argv)
    from tb_common.logging import setup_logging

    setup_logging("audit-writer")  # T-212d (D-450): JSON lines with every scrubber rule on
    url = os.environ.get("TB_DB_URL") or ""
    if not url:
        print("audit_writer: TB_DB_URL is not set", file=sys.stderr)
        return 2
    drain = Drain(url, Path(os.environ.get("TB_AUDIT_DIR") or "/data/audit"), site_tz())
    drain.open()
    n = drain.run(once=a.once)
    print(f"audit_writer: {n} events written to the chain")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
