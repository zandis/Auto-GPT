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
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from tb_common.audit import AuditLog, _day_files
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
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                rec = json.loads(line)
            except ValueError:
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
_SHARED = ("audit", "flag", "flow", "llm", "mail")  # written through tb_common by the service that hosts the call
_ORCH = ("actor", "case", "cohort", "consent", "data", "derive", "edc", "feas", "job", "lake", "life", "microbatch",
         "nav", "notice", "notmatched", "opportunity", "optout", "redcap", "registry", "rerun", "retention",
         "scheduler", "screen", "selftest", "service", "setup", "sponsor", "study", "terminology", "twpas")  # fmt: skip
_CONSOLE = ("console", "dataops", "demo", "edc", "feedback", "instrument", "notmatched", "optout", "registry",
            "setup", "sponsor", "terminology")  # fmt: skip
#: The host's `trialbox` tools (backup, update, watchdog, the operations runner) and `deploy/install.sh` send their
#: events from inside the orchestrator's container (`compose exec -T orchestrator python -c "... open_audit()"`),
#: so the journal records them under the orchestrator's role, not the administrator's (the review's H1).
_HOST_TOOLS = ("backup", "ops", "update")
#: one event of another role's family that a role sends, each with its reason (never the whole family)
EXACT_EVENTS: dict[str, dict[str, str]] = {
    "tb_orchestrator": {
        "console.ops": "the operations runner of the host (tools/trialbox/ops.py) sends it from the "
        "orchestrator's container"
    },
}
#: what an edge service writes beyond its own folder's events, and why
EDGE_EXTRA: dict[str, dict[str, str]] = {
    "tb_criteria_compiler": {"llm": "its model calls go through tb_common.llm, which audits them in the caller's log"},
}
ROLE_EVENTS: dict[str, frozenset[str]] = {
    "tb_console": frozenset({*_CONSOLE, *_SHARED}),
    "tb_orchestrator": frozenset({*_ORCH, *_SHARED, *_HOST_TOOLS, "dataops"}),  # it imports datacore.dataops
    "tb_mail_gateway": frozenset({"mail"}),
    "tb_gateway": frozenset({"llm"}),
    "tb_lake": frozenset({"lake"}),
    "tb_adapter": frozenset({"ingest", "terminology"}),
    "tb_criteria_compiler": frozenset({"approve", "compile", "ctgov", "llm"}),
    "tb_audit_writer": frozenset({"audit"}),
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
        stamp = datetime.fromisoformat(_iso(at))  # the journal's own time of the row
        detail.setdefault("sent_ts", str(ts)[:64])
        f["detail"] = detail
        problem.append("time")
    return f, stamp, problem


class Drain:
    """Copies the journal into the chain in ``directory``, in ``seq`` order; the only writer of the chain on a box."""

    BATCH = 500

    def __init__(self, url: str, directory: Path, tz: str, *, connect: Callable[[], Any] | None = None):
        self.chain = AuditLog(directory, tz)
        self.directory = directory
        self._dsn = _dsn(url)
        self._connect = connect or (lambda: _psycopg().connect(self._dsn, autocommit=True, connect_timeout=10))
        self.con: Any = None
        self.cursor: Cursor | None = None
        self._after: str | None = None  # after a resync: the next batch is the rows inserted after this time

    def open(self) -> None:
        self.con = self._connect()
        self.con.execute(f"LISTEN {NOTIFY}")
        self.cursor = last_drained(self.directory)
        if self.cursor is None:
            return
        row = self.con.execute("SELECT at FROM audit.journal WHERE seq = %s", (self.cursor.seq,)).fetchone()
        if row is not None and _same_time(_iso(row[0]), self.cursor.at):
            return
        top = self.con.execute("SELECT coalesce(max(seq), 0) FROM audit.journal").fetchone()[0]
        problem = (
            f"the chain's last journal row is seq {self.cursor.seq} at {self.cursor.at}, but the journal "
            + ("has no such row" if row is None else f"has it at {_iso(row[0])}")
            + f" (its last row is seq {top}): the database was restored or replaced"
        )
        log.error("%s: recorded as audit.journal_resync; going on with the rows written after it", problem)
        self.chain.append("audit.journal_resync", actor="tb_common.audit_writer",
                          detail={"chain_seq": self.cursor.seq, "chain_at": self.cursor.at, "journal_last": int(top),
                                  "problem": problem})  # fmt: skip
        self._after = self.cursor.at

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

    def step(self) -> int:
        """Write the next batch to the chain; the number written."""
        rows = self._rows()
        for seq, at, role, event, ts, fields in rows:
            f, stamp, problem = _readable(at, ts, fields)
            journal: dict[str, Any] = {"seq": int(seq), "role": role, "at": _iso(at)}
            if problem:  # security review 2026-11-13: a malformed row is written, marked; it never stops the drain
                journal["unreadable"] = problem
            # T-721 (D-488): who may say what, and when. The mark is part of the record the event is written in,
            # so there is no moment at which the event is in the chain without it.
            if marks := flags_of(str(role), str(event), stamp, at):
                journal["flag"] = marks
                # the event's name is the sender's own text: it stays in the record, not in the log line
                log.warning("audit journal row %s from %s marked %s", seq, role, ", ".join(marks))
            self.chain.append(event, ts=stamp, journal=journal, **f)
            self.cursor = Cursor(int(seq), _iso(at))
            self._after = None
        return len(rows)

    def wait(self, timeout: float) -> None:
        """Until a new row is announced or ``timeout`` seconds pass."""
        for _ in self.con.notifies(timeout=timeout, stop_after=1):
            break

    def run(self, *, once: bool = False, poll: float = 1.0, alive: Path | None = ALIVE) -> int:
        """Drain until stopped (``once``: until the journal is empty). A chain that cannot take a write (disk full, a
        broken anchor) stops ``once`` with the error, and the loop retries it each minute. Returns the count."""
        total = 0
        while True:
            try:
                n = self.step()
            except OSError as exc:
                if once:
                    raise
                log.error("the audit chain refused a write (%s): retrying in 60 s", exc)
                time.sleep(60)
                continue
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
