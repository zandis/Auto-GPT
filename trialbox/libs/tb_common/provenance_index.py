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
chain keeps its events, as every other audit event does. :func:`rebuild` and :func:`check` skip the pseudonyms the
register holds, so an erased row is neither written back nor reported missing.

A connection here is a psycopg connection (``con.execute(sql, args)``), as the drain holds.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
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
    """Whether both tables exist (the role script creates them; until then the drain writes no index)."""
    return all(con.execute("SELECT to_regclass(%s)", (t,)).fetchone()[0] is not None for t in TABLES)


def add(con: Any, rec: dict[str, Any], erased: Callable[[str], bool] = lambda _pid: False) -> int:
    """Write one chain record's rows (a line already indexed is a no-op); the number of rows the record gives."""
    calls, uses = rows_of(rec)
    for c in calls:
        con.execute(
            "INSERT INTO provenance.model_calls (rec_hash, call_id, model, build_sha, prompt_id, prompt_version, "
            "prompt_sha, at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (c.rec_hash, c.call_id, c.model, c.build_sha, c.prompt_id, c.prompt_version, c.prompt_sha, c.at),
        )
    for u in uses:
        if u.pid and erased(u.pid):
            continue
        con.execute(
            "INSERT INTO provenance.model_uses (rec_hash, call_id, event, record_kind, record_ref, pid, decision, "
            "by_whom, at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (u.rec_hash, u.call_id, u.event, u.record_kind, u.record_ref, u.pid, u.decision, u.by_whom, u.at),
        )
    return len(calls) + len(uses)


def rebuild(con: Any, directory: Path, erased: Iterable[str] = ()) -> tuple[int, int]:
    """Empty both tables and write them again from the chain; (calls, uses) written. Opted-out patients stay out."""
    gone = frozenset(erased)
    con.execute("DELETE FROM provenance.model_uses")
    con.execute("DELETE FROM provenance.model_calls")
    for rec in chain_records(directory):
        add(con, rec, gone.__contains__)
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


def check(con: Any, directory: Path, erased: Iterable[str] = ()) -> Diff:
    """The index against the chain, row for row (an opted-out patient's use rows are expected gone)."""
    gone = frozenset(erased)
    want: dict[str, set[tuple[str, str]]] = {t: set() for t in TABLES}
    for rec in chain_records(directory):
        calls, uses = rows_of(rec)
        want["provenance.model_calls"] |= {(c.rec_hash, c.call_id) for c in calls}
        want["provenance.model_uses"] |= {(u.rec_hash, u.call_id) for u in uses if not (u.pid and u.pid in gone)}
    out = Diff()
    for t in TABLES:
        have = {(str(a), str(b)) for a, b in con.execute(_KEYS[t]).fetchall()}
        out.missing += [(t, *k) for k in sorted(want[t] - have)]
        out.extra += [(t, *k) for k in sorted(have - want[t])]
    return out


def erase(con: Any, pids: Iterable[str]) -> int:
    """D-989 point 5: delete the use rows naming these patients (the chain keeps its events). Rows deleted."""
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
) -> list[dict[str, Any]]:
    """The records the calls matching every given filter touched, newest first: one indexed join. At least one
    filter is required (an unfiltered search would list every record a model ever touched)."""
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
