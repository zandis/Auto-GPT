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
register withholds, whoever inserts it (the drain, :func:`catch_up`, :func:`rebuild`, a hand-run SQL), and
:func:`sweep` deletes the ones a restore put back. :func:`check` asks the same function, so an erased row is neither
written back nor reported missing.

The repair obligation after a restore, a downgrade or a failed write lives in ``<audit dir>/PROVENANCE_STATE``
(:func:`read_state`, :func:`write_state`), the one store the restore does not roll back; :func:`search` refuses
while it is not ``clean``.

A connection here is a psycopg connection (``con.execute(sql, args)``), as the drain holds.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
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
-- what pg_restore loaded before the trigger existed, and what slipped in before a register row committed
CREATE OR REPLACE FUNCTION provenance.sweep() RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  n integer := 0;
BEGIN
  PERFORM pg_advisory_xact_lock(211989);
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'optout' AND c.relname = 'optout_events') THEN
    DELETE FROM provenance.model_uses u
      WHERE u.pid IN (SELECT e.pid FROM optout.optout_events e) AND provenance.withheld(u.pid, u.at);
    GET DIAGNOSTICS n = ROW_COUNT;
  END IF;
  RETURN n;
END
$fn$;
REVOKE ALL ON FUNCTION provenance.withheld(text, timestamptz), provenance.withhold(), provenance.sweep()
  FROM PUBLIC;
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
#: P-19: the repair obligation, a file in the audit directory (the one store a restore does not put back), written
#: by the drain alone
STATE = "PROVENANCE_STATE"
CLEAN, REQUIRED, REPAIRING = "clean", "repair-required", "repairing"


class ProvenanceUnderRepair(RuntimeError):
    """The index is being put back after a restore: it may still hold rows the register withholds."""


def read_state(directory: Path) -> dict[str, Any]:
    """The repair obligation; a missing file is owed (an upgraded box repairs once)."""
    try:
        return dict(json.loads((directory / STATE).read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return {"state": REQUIRED, "reason": "start", "attempts": 0}


def write_state(directory: Path, **fields: Any) -> None:
    """Replace the marker whole: a temporary file, fsync, rename, fsync the directory."""
    # ponytail: same body as P03's _write_state; lift both into tb_common when the second copy lands
    body = {"version": 1, **fields, "updated_at": datetime.now(UTC).isoformat(timespec="seconds")}
    tmp = directory / f".{STATE}.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(body, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, directory / STATE)
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
    "AND t.tgrelid = 'provenance.model_uses'::regclass AND t.tgenabled IN ('O', 'A') "
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


def sweep(con: Any) -> int:
    """Delete every use row the register withholds (a restore's, or one written before a register row committed);
    the rows deleted."""
    return int(con.execute("SELECT provenance.sweep()").fetchone()[0])


#: the console's record of an opt-out (``services/console/team.py``): after a batch that drained one the drain
#: sweeps, by then the register row that came before the journal row is committed
OPT_OUT = "console.opt_out"


def catch_up(con: Any, directory: Path) -> int:
    """P-19: write the rows of every row-bearing chain line the index does not hold (a restore, a downgrade, a write
    that failed); the rows the lines give. A line written twice is a no-op and the register's trigger withholds
    what it must, so it is safe at every start and a retry finds every hole, old and new (review P19-D3, D4)."""
    # ponytail: whole-chain diff; a day-file lower bound from the marker when the chain is years long. Rows, not line
    # hashes: a line the old autocommit loop wrote half is completed (review P19-N2); a withheld row is asked again
    have = {(t, str(a), str(b)) for t in TABLES for a, b in con.execute(_KEYS[t]).fetchall()}
    n = 0
    for rec in chain_records(directory):
        calls, uses = rows_of(rec)
        keys = [("provenance.model_calls", c.rec_hash, c.call_id) for c in calls]
        keys += [("provenance.model_uses", u.rec_hash, u.call_id) for u in uses]
        if any(k not in have for k in keys):
            n += add(con, rec)
    return n


def rebuild(con: Any, directory: Path) -> tuple[int, int]:
    """Empty both tables and write them again from the chain; (calls, uses) written. Opted-out patients stay out.
    One transaction: a rebuild stopped half way leaves the index it found (review P19-X8)."""
    with con.transaction():
        con.execute("DELETE FROM provenance.model_uses")
        con.execute("DELETE FROM provenance.model_calls")
        for rec in chain_records(directory):
            add(con, rec)
        sweep(con)
    return _count(con, "provenance.model_calls"), _count(con, "provenance.model_uses")


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
    register is the authority (its trigger and :func:`sweep`); this is the console's immediate removal, in its
    opt-out transaction under the trigger's lock 211989."""
    got = sorted(set(pids))
    if not got:
        return 0
    cur = con.execute("DELETE FROM provenance.model_uses WHERE pid = ANY(%s)", (got,))
    return int(getattr(cur, "rowcount", 0) or 0)


def search(
    con: Any,
    *,
    model: str | None = None,
    build_sha: str | None = None,
    prompt_sha: str | None = None,
    prompt_id: str | None = None,
    prompt_version: str | None = None,
    limit: int = 1000,
    directory: Path | None = None,
) -> list[dict[str, Any]]:
    """The records the calls matching every given filter touched, newest first: one indexed join. At least one
    filter is required (an unfiltered search would list every record a model ever touched). ``directory`` (the
    audit directory): refused while the repair obligation there is not ``clean`` (P-19)."""
    if directory is not None and read_state(directory).get("state") != CLEAN:
        raise ProvenanceUnderRepair(
            "the provenance index is being put back after a restore; try again when the audit writer reports it clean"
        )
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
