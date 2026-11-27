"""D-989 step 2c: the provenance index, derived from the audit chain and rebuildable from it.

"Which records did model, build or prompt version X influence" is one indexed join over two append-only tables in
schema ``provenance`` (:data:`INDEX_SQL`), never a scan of every chain event:

* ``provenance.model_calls``: one row per ``llm.call`` that names its call (D-989 step 1): the call id, the served
  model, the build, the prompt id, version and sha, and when;
* ``provenance.model_uses``: one row per call named by an ``ai.used`` or ``ai.confirmed`` (step 2b): the record's kind
  and reference, the patient's pseudonym when the record names one, the event (``used`` / ``confirmed``) and, for a
  confirmation, the decision and who made it.

Each row keeps the chain line it came from (``rec_hash``), so writing a line twice is a no-op and :func:`check` can
compare the index with the chain line by line. The chain is the one source of truth: :func:`rebuild` writes the
tables again from it, :func:`check` diffs them (the doctor runs it), and when the two disagree the chain wins.

Erasure (D-989 point 5): at an opt-out the ``model_uses`` rows naming the patient are deleted (:func:`erase`); the
chain keeps its events, as every other audit event does. The opt-out register (``optout.optout_events``) is the one
authority on what stays out, asked inside the database on every write (P-19): a trigger withholds a use row the
register withholds, whoever inserts it (the drain, :func:`rebuild`, a hand-run SQL). :func:`check` asks the same
function, so an erased row is neither written back nor reported missing.

P-19 (P19-DESIGN-3, detect and refuse): the index is never repaired in place. A restore or a downgrade empties it and
sets ``<audit dir>/PROVENANCE_STATE`` to rebuild-required (:func:`require_rebuild`, the one setter); until one
:func:`rebuild` from the chain completes, :func:`search` and the drain's index writes are refused, naming the command
(:func:`read_marker`). The register's writes are never coupled to the index.

A connection here is a psycopg connection (``con.execute(sql, args)``), as the drain holds.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tb_common.provenance import CONFIRMED, USED

#: the two tables, in a schema of their own (not the journal's ``audit``), owned like the journal by ``audit_writer``;
#: the role script runs this (lane D, with its grants)
INDEX_SQL = """\
CREATE SCHEMA IF NOT EXISTS provenance;
SET search_path = provenance, pg_catalog;
CREATE TABLE IF NOT EXISTS model_calls (
  rec_hash text NOT NULL,
  call_id text NOT NULL,
  model text NOT NULL DEFAULT '',
  build_sha text NOT NULL DEFAULT '',
  prompt_id text NOT NULL DEFAULT '',
  prompt_version text NOT NULL DEFAULT '',
  prompt_sha text NOT NULL DEFAULT '',
  at timestamptz NOT NULL,
  PRIMARY KEY (rec_hash, call_id)
);
CREATE INDEX IF NOT EXISTS model_calls_call ON model_calls (call_id);
CREATE INDEX IF NOT EXISTS model_calls_build ON model_calls (build_sha);
CREATE INDEX IF NOT EXISTS model_calls_prompt_sha ON model_calls (prompt_sha);
CREATE INDEX IF NOT EXISTS model_calls_prompt ON model_calls (prompt_id, prompt_version);
CREATE INDEX IF NOT EXISTS model_calls_model ON model_calls (model);
CREATE TABLE IF NOT EXISTS model_uses (
  rec_hash text NOT NULL,
  call_id text NOT NULL,
  event text NOT NULL CHECK (event IN ('used', 'confirmed')),
  record_kind text NOT NULL,
  record_ref text NOT NULL,
  pid text,
  decision text,
  by_whom text,
  at timestamptz NOT NULL,
  PRIMARY KEY (rec_hash, call_id)
);
CREATE INDEX IF NOT EXISTS model_uses_call ON model_uses (call_id);
CREATE INDEX IF NOT EXISTS model_uses_pid ON model_uses (pid);
RESET search_path;
-- P-19: the opt-out register (optout.optout_events) is the one authority on which use rows stay out, asked inside
-- the database on every insert. The role script gives the three functions to provenance_keeper, the one role that
-- may read the register here, and grants EXECUTE (D-997's grants live there, as the tables' owner does).
-- A use row of time p_at is withheld while the patient's opt-out is in force, and when its event is not after the
-- latest lift (rows erased before a lift stay erased; a back-dated row falls on the withheld side). No register
-- table yet: nobody has opted out (tb_common.optout.opted_out reads it the same way)
CREATE OR REPLACE FUNCTION provenance.withheld(p_pid text, p_at timestamptz) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  last_action text;
BEGIN
  IF p_pid IS NULL OR NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                  WHERE n.nspname = 'optout' AND c.relname = 'optout_events') THEN
    RETURN false;
  END IF;
  SELECT e.action INTO last_action FROM optout.optout_events e WHERE e.pid = p_pid ORDER BY e.at DESC, e.id DESC
    LIMIT 1;
  IF last_action IS NULL THEN
    RETURN false;
  END IF;
  RETURN last_action = 'opt_out' OR coalesce(p_at <= (SELECT max(e.at)::timestamptz FROM optout.optout_events e
                                                       WHERE e.pid = p_pid AND e.action = 'lift'), true);
END
$fn$;
-- the lock (apart from audit.append's 211394) orders an insert against the console's opt-out transaction
CREATE OR REPLACE FUNCTION provenance.withhold() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  PERFORM pg_advisory_xact_lock(211989);
  IF NEW.pid IS NOT NULL AND provenance.withheld(NEW.pid, NEW.at) THEN
    RETURN NULL;
  END IF;
  RETURN NEW;
END
$fn$;
CREATE OR REPLACE TRIGGER model_uses_withhold BEFORE INSERT ON provenance.model_uses
  FOR EACH ROW EXECUTE FUNCTION provenance.withhold();
-- P19-DESIGN-3: nothing repairs the index in place any more (an earlier script's sweep goes)
DROP FUNCTION IF EXISTS provenance.sweep();
REVOKE ALL ON FUNCTION provenance.withheld(text, timestamptz), provenance.withhold() FROM PUBLIC;
"""
TABLES = ("provenance.model_calls", "provenance.model_uses")
#: each table's statements written out whole (no SQL is built from a name)
_COUNT = {
    "provenance.model_calls": "SELECT count(*) FROM provenance.model_calls",
    "provenance.model_uses": "SELECT count(*) FROM provenance.model_uses",
}
_KEYS = {
    "provenance.model_calls": "SELECT rec_hash, call_id FROM provenance.model_calls",
    "provenance.model_uses": "SELECT rec_hash, call_id FROM provenance.model_uses",
}
#: one statement for every search: a filter not given is NULL and matches every row
_SEARCH = (
    "SELECT u.record_kind, u.record_ref, u.event, u.decision, u.by_whom, u.at, c.call_id, c.model, c.build_sha, "
    "c.prompt_id, c.prompt_version, c.prompt_sha FROM provenance.model_calls c JOIN provenance.model_uses u "
    "ON u.call_id = c.call_id WHERE (%(model)s::text IS NULL OR c.model = %(model)s) "
    "AND (%(build_sha)s::text IS NULL OR c.build_sha = %(build_sha)s) "
    "AND (%(prompt_sha)s::text IS NULL OR c.prompt_sha = %(prompt_sha)s) "
    "AND (%(prompt_id)s::text IS NULL OR c.prompt_id = %(prompt_id)s) "
    "AND (%(prompt_version)s::text IS NULL OR c.prompt_version = %(prompt_version)s) "
    "ORDER BY u.at DESC LIMIT %(limit)s"
)
_EVENT = {USED: "used", CONFIRMED: "confirmed"}
#: P-19: the marker, a file in the audit directory (the one store a restore of the database does not put back)
STATE = "PROVENANCE_STATE"
VERSION = 2
#: the trigger's lock against the opt-out worker's :func:`erase` (taken by those two only)
CONSENT_LOCK = 211989
#: a session lock between the drain's batch and the rebuild: no chain line is appended while the rebuild reads it
WRITER_LOCK = 211990
#: a setting: how long the rebuild waits for the drain to finish its batch (one batch of ``Drain.BATCH`` lines)
REBUILD_LOCK_WAIT_S = 300
TEXT = (
    "the provenance index must be rebuilt ({reason}, since {since}); provenance search and index writes are refused "
    "until then: run trialbox provenance --rebuild"
)


class ProvenanceRebuildRequired(RuntimeError):
    """The index may not equal the chain filtered by the register: nothing is served until one rebuild completes."""


class RebuildRefused(RuntimeError):
    """The rebuild cannot run here, for the reason named; the marker is left as it was."""


@dataclass(frozen=True)
class Marker:
    """``PROVENANCE_STATE`` as read. CLEAN is derived, never stored: readable, version 2 and ``verified``."""

    clean: bool
    reason: str
    since: str = ""
    attempts: int = 0
    done_through: str = ""  # the last day file an unfinished rebuild committed ("": start from empty)

    @property
    def text(self) -> str:
        return TEXT.format(reason=self.reason, since=self.since or "unknown")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def read_marker(directory: Path) -> Marker:
    """The marker; anything but a readable version-2 file that says ``verified`` is rebuild-required, with the reason
    named (fail closed: no file, a file this process may not read, bad JSON, the version-1 marker)."""
    try:
        body = json.loads((Path(directory) / STATE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Marker(False, "no marker")
    except OSError as exc:
        return Marker(False, f"unreadable: {type(exc).__name__}")
    except ValueError:
        return Marker(False, "unreadable: not JSON")
    if not isinstance(body, dict) or body.get("version") != VERSION:
        got = body.get("version") if isinstance(body, dict) else None
        return Marker(False, f"unreadable: version {got}")
    if body.get("verified") is True:
        return Marker(True, "verified", str(body.get("built_at") or ""))
    return Marker(False, str(body.get("reason") or "unreadable: no reason"), str(body.get("since") or ""),
                  int(body.get("attempts") or 0), str(body.get("done_through") or ""))  # fmt: skip


def require_rebuild(directory: Path, reason: str) -> None:
    """The one setter of rebuild-required (a restore, a downgrade, a journal resync, a failed index write). It clears
    an unfinished rebuild's progress, so a restore in the middle of one starts it again from empty. Raises OSError."""
    prev = read_marker(directory)
    since = prev.since if not prev.clean and prev.since else _now()
    _write_marker(directory, {"verified": False, "reason": reason, "since": since, "attempts": prev.attempts,
                              "done_through": ""})  # fmt: skip


def _write_marker(directory: Path, body: dict[str, Any]) -> None:
    """Replace the marker whole: a temporary file of this writer's own (mode 0644), fsync, rename, fsync the folder."""
    # ponytail: same body as P03's _write_intent; lift both into tb_common when the second copy lands
    directory = Path(directory)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{STATE}.")
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({**body, "version": VERSION, "updated_at": _now()}, fh, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, directory / STATE)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    dfd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


@dataclass(frozen=True)
class Call:
    rec_hash: str
    call_id: str
    model: str
    build_sha: str
    prompt_id: str
    prompt_version: str
    prompt_sha: str
    at: str


@dataclass(frozen=True)
class Use:
    rec_hash: str
    call_id: str
    event: str
    record_kind: str
    record_ref: str
    pid: str | None
    decision: str | None
    by_whom: str | None
    at: str


def _prompt(version: str) -> tuple[str, str]:
    """``judge_v4`` -> (``judge``, ``4``); a value without the suffix is the id with no version."""
    pid, sep, ver = version.rpartition("_v")
    return (pid, ver) if sep and ver.isdigit() else (version, "")


def rows_of(rec: dict[str, Any]) -> tuple[list[Call], list[Use]]:
    """The index rows one chain record gives: none for any other event, or for a record without its line hash."""
    event, h, at = str(rec.get("event") or ""), str(rec.get("hash") or ""), str(rec.get("ts") or "")
    detail = rec.get("detail") or {}
    if not h or not at or not isinstance(detail, dict):
        return [], []
    if event == "llm.call":
        call_id = str(detail.get("call_id") or "")
        if not call_id:  # a call from before D-989 step 1 names none
            return [], []
        pid, ver = _prompt(str(rec.get("prompt_version") or ""))
        return [Call(h, call_id, str(rec.get("model") or ""), str(detail.get("build_sha") or ""), pid, ver,
                     str(detail.get("prompt_sha") or ""), at)], []  # fmt: skip
    if event in _EVENT:
        ref = detail.get("record_ref") or {}
        if not isinstance(ref, dict):
            return [], []
        text = json.dumps(ref, sort_keys=True, ensure_ascii=False)
        pid_ = str(ref["pid"]) if ref.get("pid") else None
        uses = [
            Use(
                h,
                str(c),
                _EVENT[event],
                str(detail.get("record_kind") or ""),
                text,
                pid_,
                detail.get("decision"),
                detail.get("by"),
                at,
            )
            for c in dict.fromkeys(detail.get("calls") or [])
            if c
        ]
        return [], uses
    return [], []


def chain_records(directory: Path) -> Iterator[dict[str, Any]]:
    """Every record of the chain in ``directory``, in chain order (day files by name, lines in order)."""
    from tb_common.audit import _day_files

    for path in _day_files(directory):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def installed(con: Any) -> bool:
    """Whether both tables exist and the register's trigger is on them (the role script creates them; until then
    the drain writes no index, and never one the register does not filter)."""
    return all(con.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is not None for t in TABLES) and (
        con.execute(_TRIGGER).fetchone() is not None
    )


#: the trigger that filters: on ``model_uses``, running ``provenance.withhold``, enabled for an ordinary session (a
#: disabled one, left by an interrupted data restore, or one of that name elsewhere is no filter: review P19-X4)
_TRIGGER = (
    "SELECT 1 FROM pg_trigger t WHERE t.tgname = 'model_uses_withhold' "
    "AND t.tgenabled IN ('O', 'A') AND t.tgrelid IN (SELECT c.oid FROM pg_class c JOIN pg_namespace n "
    "ON n.oid = c.relnamespace WHERE n.nspname = 'provenance' AND c.relname = 'model_uses') "
    "AND t.tgfoid IN (SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
    "WHERE n.nspname = 'provenance' AND p.proname = 'withhold')"
)


def add(con: Any, rec: dict[str, Any]) -> int:
    """Write one chain record's rows (a row already indexed is a no-op); the number of rows written (a row the
    register's trigger withholds, or one already there, is not: review P19-F6). The line's rows are written whole or
    not at all (P-19)."""
    calls, uses = rows_of(rec)
    if not calls and not uses:
        return 0
    n = 0
    with con.transaction():
        for c in calls:
            cur = con.execute(
                "INSERT INTO provenance.model_calls (rec_hash, call_id, model, build_sha, prompt_id, prompt_version, "
                "prompt_sha, at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (c.rec_hash, c.call_id, c.model, c.build_sha, c.prompt_id, c.prompt_version, c.prompt_sha, c.at),
            )
            n += _written(cur)
        for u in uses:
            cur = con.execute(
                "INSERT INTO provenance.model_uses (rec_hash, call_id, event, record_kind, record_ref, pid, decision, "
                "by_whom, at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (u.rec_hash, u.call_id, u.event, u.record_kind, u.record_ref, u.pid, u.decision, u.by_whom, u.at),
            )
            n += _written(cur)
    return n


def _written(cur: Any) -> int:
    return int(getattr(cur, "rowcount", 0) or 0)


#: a register table of the same name in another schema: the trigger reads ``optout.optout_events`` alone (Y3, G6)
_OTHER_REGISTERS = (
    "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = 'optout_events' "
    "AND c.relkind IN ('r', 'p') AND n.nspname <> 'optout' ORDER BY 1"
)
#: whether the role the index's functions run as (their owner: provenance_keeper on a box) may read the register;
#: no row: no register yet, nobody has opted out (G3). By catalog, not by name: the caller may not see the schema
_KEEPER_READS = (
    "SELECT pg_get_userbyid(p.proowner), has_schema_privilege(p.proowner, cn.oid, 'USAGE') "
    "AND has_table_privilege(p.proowner, c.oid, 'SELECT') FROM pg_proc p "
    "JOIN pg_namespace pn ON pn.oid = p.pronamespace, pg_class c JOIN pg_namespace cn ON cn.oid = c.relnamespace "
    "WHERE pn.nspname = 'provenance' AND p.proname = 'withheld' AND cn.nspname = 'optout' "
    "AND c.relname = 'optout_events'"
)


def rebuild(con: Any, directory: Path, *, say: Callable[[str], None] | None = None) -> tuple[int, int]:
    """P19-DESIGN-3 §3: the index written again from the chain, every use row through the register's trigger; then
    the marker says ``verified``. (calls, uses) in the index after it.

    Refused by name, the marker untouched (:class:`RebuildRefused`): a connection that is not autocommit, no index,
    a second register schema, a register the functions' owner cannot read, a drain that does not yield the writer's
    lock. One transaction per day file, the marker's ``done_through`` after each: a rebuild killed at any point is
    resumed by the next (a day committed but not yet recorded is written again as a no-op); only a rebuild from empty
    deletes the tables first. ``say``: progress, one line per day file."""
    directory = Path(directory)
    if getattr(con, "autocommit", None) is not True:
        raise RebuildRefused("the rebuild needs an autocommit connection")
    if not installed(con):
        raise RebuildRefused("not installed: the role script creates provenance.model_calls and model_uses")
    other = [str(r[0]) for r in con.execute(_OTHER_REGISTERS).fetchall()]
    if other:
        raise RebuildRefused(f"the index's filter reads optout.optout_events; this database also holds "
                             f"{', '.join(o + '.optout_events' for o in other)}: not supported")  # fmt: skip
    keeper = con.execute(_KEEPER_READS).fetchone()
    if keeper is not None and not keeper[1]:
        raise RebuildRefused(f"{keeper[0]} cannot read the register: re-run 30-service-roles.sh")
    con.execute(f"SET lock_timeout = '{int(REBUILD_LOCK_WAIT_S)}s'")
    try:
        con.execute("SELECT pg_advisory_lock(%s)", (WRITER_LOCK,))
    except Exception as exc:
        if type(exc).__name__ == "LockNotAvailable":
            raise RebuildRefused(f"the audit writer did not yield in {REBUILD_LOCK_WAIT_S} s") from exc
        raise
    finally:
        con.execute("RESET lock_timeout")
    try:
        return _rebuild_locked(con, directory, say or (lambda _s: None))
    finally:
        con.execute("SELECT pg_advisory_unlock(%s)", (WRITER_LOCK,))


def _rebuild_locked(con: Any, directory: Path, say: Callable[[str], None]) -> tuple[int, int]:
    from tb_common.audit import _day_files

    m = read_marker(directory)
    by = {"pid": os.getpid(), "start": _now()}  # diagnostic only
    done = m.done_through
    since = m.since if not m.clean and m.since else _now()
    if not done:
        with con.transaction():
            con.execute("DELETE FROM provenance.model_uses")
            con.execute("DELETE FROM provenance.model_calls")
        _write_marker(directory, {"verified": False, "reason": "rebuilding", "since": since, "done_through": "",
                                  "attempts": m.attempts + 1, "by": by})  # fmt: skip
    head = ""
    for path in _day_files(directory):
        if done and path.name <= done:
            continue
        t0, lines = time.monotonic(), 0
        with con.transaction(), path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    add(con, json.loads(line))
                    lines += 1
        _write_marker(directory, {"verified": False, "reason": "rebuilding", "since": since,
                                  "done_through": path.name, "attempts": m.attempts + (0 if done else 1),
                                  "by": by})  # fmt: skip
        say(f"provenance index: {path.name} {lines} line(s), {lines / max(time.monotonic() - t0, 1e-6):.0f} lines/s")
    files = _day_files(directory)
    if files:
        from tb_common.audit import _last_line

        last = _last_line(files[-1])
        head = str(json.loads(last).get("hash") or "") if last else ""
    rows = [_count(con, "provenance.model_calls"), _count(con, "provenance.model_uses")]
    _write_marker(directory, {"verified": True, "built_at": _now(), "chain_head": head, "rows": rows, "by": by})
    return rows[0], rows[1]


def _count(con: Any, table: str) -> int:
    return int(con.execute(_COUNT[table]).fetchone()[0])


@dataclass
class Diff:
    """What the index holds that the chain does not (``extra``), and what it lacks (``missing``), by line and call."""

    missing: list[tuple[str, str, str]] = field(default_factory=list)  # (table, rec_hash, call_id)
    extra: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra


def check(con: Any, directory: Path) -> Diff:
    """The index against the chain, row for row (a use row the register withholds is expected gone: the same
    function the trigger asks, so the doctor and the writer agree)."""
    want: dict[str, set[tuple[str, str]]] = {t: set() for t in TABLES}
    every: list[Use] = []
    for rec in chain_records(directory):
        calls, uses = rows_of(rec)
        want["provenance.model_calls"] |= {(c.rec_hash, c.call_id) for c in calls}
        every += uses
    asked = sorted({(u.pid, u.at) for u in every if u.pid})
    gone: set[tuple[str | None, str]] = set()
    if asked:
        got = con.execute(
            "SELECT i FROM unnest(%s::text[], %s::timestamptz[]) WITH ORDINALITY AS t(pid, at, i) "
            "WHERE provenance.withheld(pid, at)",
            ([p for p, _ in asked], [a for _, a in asked]),
        ).fetchall()
        gone = {asked[int(r[0]) - 1] for r in got}
    want["provenance.model_uses"] |= {(u.rec_hash, u.call_id) for u in every if (u.pid, u.at) not in gone}
    out = Diff()
    for t in TABLES:
        have = {(str(a), str(b)) for a, b in con.execute(_KEYS[t]).fetchall()}
        out.missing += [(t, *k) for k in sorted(want[t] - have)]
        out.extra += [(t, *k) for k in sorted(have - want[t])]
    return out


def erase(con: Any, pids: Iterable[str]) -> int:
    """D-989 point 5: delete the use rows naming these patients (the chain keeps its events). Rows deleted. The
    register is the authority (the trigger); this is the opt-out worker's removal, in its own transaction under the
    trigger's lock, so a row a trigger let in before the register row committed is gone after it (P19-DESIGN-3 R3)."""
    got = sorted(set(pids))
    if not got:
        return 0
    with con.transaction():
        con.execute("SELECT pg_advisory_xact_lock(%s)", (CONSENT_LOCK,))
        cur = con.execute("DELETE FROM provenance.model_uses WHERE pid = ANY(%s)", (got,))
    return int(getattr(cur, "rowcount", 0) or 0)


def search(
    con: Any,
    *,
    directory: Path,
    model: str | None = None,
    build_sha: str | None = None,
    prompt_sha: str | None = None,
    prompt_id: str | None = None,
    prompt_version: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """The records the calls matching every given filter touched, newest first: one indexed join. At least one
    filter is required (an unfiltered search would list every record a model ever touched). ``directory`` (the
    audit directory, required: G8): refused while its marker is not clean (:class:`ProvenanceRebuildRequired`)."""
    m = read_marker(directory)
    if not m.clean:
        raise ProvenanceRebuildRequired(m.text)
    filters = {"model": model, "build_sha": build_sha, "prompt_sha": prompt_sha, "prompt_id": prompt_id,
               "prompt_version": prompt_version}  # fmt: skip
    if not any(filters.values()):
        raise ValueError("search: name a model, build, prompt sha, or prompt id (and version)")
    args = {k: (v or None) for k, v in filters.items()}
    rows = con.execute(_SEARCH, {**args, "limit": int(limit)}).fetchall()
    keys = ("record_kind", "record_ref", "event", "decision", "by", "at", "call_id", "model", "build_sha",
            "prompt_id", "prompt_version", "prompt_sha")  # fmt: skip
    out = []
    for r in rows:
        d = dict(zip(keys, r, strict=True))
        d["record_ref"] = json.loads(d["record_ref"])
        d["at"] = str(d["at"])
        out.append(d)
    return out


def main(argv: list[str] | None = None) -> int:
    """``python -m tb_common.provenance_index rebuild | require-rebuild --reason R`` (inside a box's container: the
    chain is ``TB_AUDIT_DIR``, the database ``TB_DB_URL``)."""
    ap = argparse.ArgumentParser(prog="python -m tb_common.provenance_index")
    ap.add_argument("--audit-dir", default=os.environ.get("TB_AUDIT_DIR") or "/data/audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rebuild")
    sub.add_parser("require-rebuild").add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    directory = Path(a.audit_dir)
    if a.cmd == "require-rebuild":
        require_rebuild(directory, a.reason)
        print(f"provenance index: rebuild required ({a.reason})")
        return 0
    from tb_common.audit_writer import _dsn, _psycopg

    url = os.environ.get("TB_DB_URL") or ""
    if not url:
        print("provenance index: TB_DB_URL is not set", file=sys.stderr)
        return 2
    with _psycopg().connect(_dsn(url), autocommit=True) as con:
        try:
            calls, uses = rebuild(con, directory, say=print)
        except RebuildRefused as exc:
            print(f"provenance index: the rebuild was refused: {exc}", file=sys.stderr)
            return 1
    print(f"provenance index rebuilt from {directory}: {calls} call(s), {uses} use(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
