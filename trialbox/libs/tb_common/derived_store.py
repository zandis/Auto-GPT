"""Stored derived rows (WS-04.3, D-190): one compute engine writes each score the box derives as a row with its
provenance, in schema ``derived`` of the trial database (D-126).

* ``definition``: the catalogue definitions in use (``def_version`` = ``<score_id>@<version>``, the YAML's sha256 and
  its body), loaded from :mod:`tb_common.scores`. A definition never changes under the same version: the store
  refuses to open when the generated file has a different text for a ``def_version`` it already holds.
* ``score_row``: one row per (patient, score, anchor row) with the value, or no value and the reason
  (``derived_missing_input:<c>`` / ``derived_unit:<c>``, never a value of 0 or FALSE), the definition version and
  sha, the site mapping version, the unit of the value, and ``inputs``: each input with its source table, source row
  id, date, value and unit as recorded, status, and the value and unit the formula used. A recomputed row supersedes
  the old one (``superseded_at``, ``superseded_by``); rows are never updated in place or deleted.
* ``input_link``: one row per input ("derived from", the OMOP ``FACT_RELATIONSHIP`` of the design).
* ``conflict``: a documented score (written by a physician, or a proposed fact read from a chart) that differs from
  the computed row near its date by more than the score's tolerance (:data:`tb_common.scores.TOLERANCE`) opens a
  ``derived_vs_documented`` conflict. Neither value is overwritten; the score reads as unknown until a person
  resolves it (``keep_derived``, ``keep_documented`` or ``both_at_dates``). A recomputed row takes over the conflicts
  of the row it replaces (``carried_from``), checked against the stored documented value even when the caller does
  not pass the documented scores again; a person's resolution stays unless the new value differs from the value it
  was made against (``resolved_value``) by more than the tolerance, and then the conflict opens again.

**Recompute only on a change.** Each row carries a fingerprint of its definition version and sha, the mapping
version and its inputs (ids, values, units, dates, statuses; age and sex for eGFR). :meth:`DerivedStore.recompute`
is given all of one patient's component rows; for each anchor row (the joint count of a CDAI, the creatinine of an
eGFR) it computes the score with :func:`tb_common.derived.compute` and writes a row only when the fingerprint differs
from the current row's: an input added, corrected, confirmed or removed, a new mapping version, or a new definition
version. An anchor that is gone (deleted at the source) retires its row. Nothing else writes.

**Proposed facts never count.** Only rows whose status is in :data:`tb_common.derived.COUNTS` are inputs. A proposed
value is ignored until it is confirmed; then the inputs change and the row is recomputed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from tb_common import derived, scores
from tb_common.db import ENV, Database, Tx

log = logging.getLogger("derived_store")

SCHEMA = "derived"
# the scores stored as rows: each has a catalogue definition and an engine formula
STORED: tuple[str, ...] = tuple(scores.ENGINE)
CONFLICT_KIND = "derived_vs_documented"
DECISIONS = ("keep_derived", "keep_documented", "both_at_dates")
SUPERSEDED = "superseded"  # a conflict whose derived row was recomputed: checked again against the new row
NOT_DOCUMENTED = frozenset({"rejected", "entered-in-error", "cancelled", "tombstoned"})

MIGRATIONS = [
    """
CREATE TABLE IF NOT EXISTS definition (def_version TEXT PRIMARY KEY, score_id TEXT NOT NULL, version BIGINT NOT NULL,
  sha256 TEXT NOT NULL, body TEXT NOT NULL, loaded_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS score_row (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, pid TEXT NOT NULL,
  score TEXT NOT NULL, def_version TEXT NOT NULL REFERENCES definition (def_version), def_sha TEXT NOT NULL,
  mapping_version TEXT NOT NULL, anchor_oid TEXT NOT NULL, anchor_date DATE NOT NULL, value DOUBLE PRECISION,
  unit TEXT NOT NULL, reason TEXT, inputs TEXT NOT NULL, fingerprint TEXT NOT NULL, computed_at TEXT NOT NULL,
  superseded_at TEXT, superseded_by BIGINT, CHECK ((value IS NULL) <> (reason IS NULL)));
CREATE UNIQUE INDEX IF NOT EXISTS score_row_current ON score_row (pid, score, anchor_oid) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS score_row_pid ON score_row (pid, score, anchor_date);
CREATE TABLE IF NOT EXISTS input_link (row_id BIGINT NOT NULL REFERENCES score_row (id), component TEXT NOT NULL,
  source_table TEXT NOT NULL, source_id TEXT NOT NULL, PRIMARY KEY (row_id, component));
CREATE TABLE IF NOT EXISTS conflict (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, kind TEXT NOT NULL,
  pid TEXT NOT NULL, score TEXT NOT NULL, row_id BIGINT NOT NULL REFERENCES score_row (id),
  documented_id TEXT NOT NULL, documented_status TEXT NOT NULL, documented_value DOUBLE PRECISION NOT NULL,
  documented_date DATE NOT NULL, derived_value DOUBLE PRECISION NOT NULL, tolerance DOUBLE PRECISION NOT NULL,
  opened_at TEXT NOT NULL, resolution TEXT, resolved_by TEXT, resolved_at TEXT, resolved_value DOUBLE PRECISION,
  carried_from BIGINT REFERENCES conflict (id), UNIQUE (row_id, documented_id))
""",
    # D-442: one row per derive batch over a lake snapshot. Screening reads a stored row only when the batch of the
    # snapshot it screens finished under the definitions the box computes now; a patient whose recompute failed in
    # that batch reads as unknown
    """
CREATE TABLE IF NOT EXISTS batch_run (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, snapshot TEXT NOT NULL,
  mapping_version TEXT NOT NULL, defs TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, patients BIGINT,
  inserted BIGINT, failed BIGINT, failed_pids TEXT);
CREATE INDEX IF NOT EXISTS batch_run_snapshot ON batch_run (snapshot, id)
""",
]


class DerivedError(ValueError):
    """A definition changed under its version, an unknown score, or a bad conflict decision."""


@dataclass(frozen=True)
class Documented:
    """A score as written by a person or read from a chart (``status``: ``signed``, ``confirmed``, ``proposed``)."""

    pid: str
    score: str
    value: float
    on: date
    did: str
    status: str = "proposed"


@dataclass
class Report:
    """What one recompute did: rows written, rows left as they were, rows superseded or retired, conflicts opened,
    conflicts (open or resolved) carried to a recomputed row, resolved conflicts reopened; and, for a batch, the
    patients whose recompute failed (the batch goes on with the next patient)."""

    inserted: int = 0
    unchanged: int = 0
    superseded: int = 0
    retired: int = 0
    conflicts: int = 0
    carried: int = 0
    reopened: int = 0
    failed: int = 0
    failed_pids: list[str] = field(default_factory=list)

    def add(self, other: Report) -> None:
        for k in ("inserted", "unchanged", "superseded", "retired", "conflicts", "carried", "reopened", "failed"):
            setattr(self, k, getattr(self, k) + getattr(other, k))
        self.failed_pids.extend(other.failed_pids)


@dataclass
class Latest:
    """The value a reader takes for a score: a value, or none and the reason (unknown, never FALSE)."""

    value: float | None
    reason: str | None
    row_id: int | None = None
    anchor_date: date | None = None
    def_version: str | None = None
    source: str = "derived"  # or "documented" after a person kept the documented value
    inputs: list[dict[str, Any]] = field(default_factory=list)
    anchor_oid: str | None = None  # D-442: the anchor row, matched against the visit the screening engine used
    def_sha: str | None = None


@dataclass(frozen=True)
class Batch:
    """D-442: the first finished derive batch of a snapshot: its definitions, when it finished and the patients it
    failed. Screening reads the stored rows as they stood when it finished (:meth:`DerivedStore.latest_many`
    ``as_of``), so a re-run of a job reads what the job read."""

    run_id: int
    snapshot: str
    defs: dict[str, str]
    failed_pids: frozenset[str]
    finished_at: str = ""

    def current(self) -> bool:
        """Whether the batch ran under the definitions this box computes now (:func:`current_defs`)."""
        return self.defs == current_defs()

    def holds(self, pins: Mapping[str, Any] | None) -> bool:
        """Whether the batch ran under the definitions a ruleset pinned (each pinned version with its sha); with no
        pins (approved before D-442), under the definitions this box computes now."""
        if not pins:
            return self.current()
        for raw in pins.values():
            pin = scores.pin_fields(raw)
            if self.defs.get(str(pin.get("def_version"))) != pin.get("sha256"):
                return False
        return True


def current_defs() -> dict[str, str]:
    """``{def_version: sha256}`` of every stored score's definition on this box."""
    out = {}
    for s in STORED:
        d = scores.definition(s)
        out[str(d["def_version"])] = str(d["sha256"])
    return out


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _anchor_key(o: derived.Obs, comp: str) -> str:
    return o.oid or f"{comp}|{o.on.isoformat()}|{o.value!r}|{o.unit or ''}"


def provenance(
    score: str, res: derived.Derived, pid: str, age: int | None, female: bool | None
) -> list[dict[str, Any]]:
    """Each input with its source row: table, id, date, value and unit as recorded, status, and what the formula
    used (value converted to its unit). eGFR also names the age and sex it used."""
    out: list[dict[str, Any]] = []
    for comp in derived.COMPONENTS[score]:
        o = res.inputs.get(comp)
        if o is None:
            continue
        used, _why = derived.convert(comp, o.value, o.unit)
        target = derived.UNITS[comp][0] if comp in derived.UNITS else (o.unit or "")
        out.append(
            {
                "component": comp,
                "table": "observation",
                "id": o.oid,
                "date": o.on.isoformat(),
                "value": o.value,
                "unit": o.unit,
                "status": o.status,
                "used_value": used,
                "used_unit": target,
            }
        )
    if score.startswith("egfr"):
        out.append({"component": "age", "table": "patient", "id": pid, "value": age, "unit": "a"})
        sex = None if female is None else ("female" if female else "male")
        out.append({"component": "sex", "table": "patient", "id": pid, "value": sex, "unit": None})
    return out


def fingerprint(def_version: str, def_sha: str, mapping_version: str, inputs: list[dict[str, Any]]) -> str:
    doc = {"def": def_version, "sha": def_sha, "mapping": mapping_version, "inputs": inputs}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class DerivedStore:
    """Schema ``derived`` of the trial database."""

    def __init__(self, url: str | None = None) -> None:
        self._db = Database.connect(url or os.environ.get(ENV), SCHEMA)
        self._db.migrate(MIGRATIONS)
        self._load_definitions()

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------------------------------------ definitions
    def _load_definitions(self) -> None:
        with self._db.transaction() as tx:
            for s in STORED:
                d = scores.definition(s)
                have = tx.fetchval("SELECT sha256 FROM definition WHERE def_version = ?", (d["def_version"],))
                if have is None:
                    # two stores opening at once: the second insert does nothing, and the re-read compares its sha
                    tx.execute(
                        "INSERT INTO definition (def_version, score_id, version, sha256, body, loaded_at) "
                        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (def_version) DO NOTHING",
                        (
                            d["def_version"],
                            d["score_id"],
                            int(d["version"]),
                            d["sha256"],
                            json.dumps(d, sort_keys=True, ensure_ascii=False),
                            _now(),
                        ),
                    )
                    have = tx.fetchval("SELECT sha256 FROM definition WHERE def_version = ?", (d["def_version"],))
                if have != d["sha256"]:
                    raise DerivedError(
                        f"definition {d['def_version']} changed under the same version: bump its version in "
                        f"{d['file']} (stored rows name {have[:12]})"
                    )

    # ------------------------------------------------------------------------------------------ compute
    def recompute(
        self,
        pid: str,
        rows: Mapping[str, Iterable[derived.Obs]],
        *,
        mapping_version: str,
        birth: date | None = None,
        female: bool | None = None,
        documented: Iterable[Documented] = (),
        only: Sequence[str] | None = None,
    ) -> Report:
        """Compute every stored score of one patient from all of their component rows (``{component: [Obs]}``) and
        write what changed. ``only`` limits the scores (default: all of :data:`STORED`). ``documented``: the patient's
        documented scores, checked against the computed rows (:meth:`check_documented`)."""
        if not mapping_version:
            raise DerivedError("a mapping version is required: it is part of every row's provenance")
        todo = list(only or STORED)
        bad = [s for s in todo if s not in STORED]
        if bad:
            raise DerivedError(f"not a stored score: {', '.join(bad)}")
        counted = {c: [o for o in rs if o.status in derived.COUNTS] for c, rs in rows.items()}
        fresh: dict[tuple[str, str], tuple[derived.Obs, derived.Derived, list[dict[str, Any]], str]] = {}
        for score in todo:
            d = scores.definition(score)
            anchor_comp = derived.COMPONENTS[score][0]
            for anchor in sorted(counted.get(anchor_comp, []), key=lambda o: (o.on, o.oid)):
                age = derived.age_at(birth, anchor.on) if birth is not None else None
                res = derived.compute(score, {**counted, anchor_comp: [anchor]}, age=age, female=female)
                prov = provenance(score, res, pid, age, female)
                fp = fingerprint(d["def_version"], d["sha256"], mapping_version, prov)
                fresh[(score, _anchor_key(anchor, anchor_comp))] = (anchor, res, prov, fp)
        rep = Report()
        now = _now()
        mine = [x for x in documented if x.pid == pid and x.score in todo]
        given = {(x.score, x.did): x for x in mine}
        with self._db.transaction() as tx:
            # one recompute per patient at a time (a night batch and an on-change recompute side by side)
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"{SCHEMA}:{pid}",))
            current = {
                (r[1], r[2]): (int(r[0]), str(r[3]))
                for r in tx.fetchall(
                    "SELECT id, score, anchor_oid, fingerprint FROM score_row WHERE pid = ? AND superseded_at IS NULL",
                    (pid,),
                )
                if r[1] in todo
            }
            for key, (anchor, res, prov, fp) in fresh.items():
                old = current.get(key)
                if old is not None and old[1] == fp:
                    rep.unchanged += 1
                    continue
                held = self._conflicts_of(tx, old[0]) if old is not None else []
                if old is not None:
                    self._supersede(tx, old[0], now)
                new_id = self._insert(tx, pid, key, anchor, res, prov, fp, mapping_version, now)
                if old is not None:
                    tx.execute("UPDATE score_row SET superseded_by = ? WHERE id = ?", (new_id, old[0]))
                    rep.superseded += 1
                    value = res.value if res.reason is None else None
                    carried, reopened = self._carry(tx, held, new_id, value, anchor.on, given, now)
                    rep.carried += carried
                    rep.reopened += reopened
                rep.inserted += 1
            for key, (row_id, _fp) in current.items():
                if key not in fresh:  # the anchor row is gone (deleted at the source, or no longer counts)
                    self._supersede(tx, row_id, now)
                    rep.retired += 1
            rep.conflicts = self._check(tx, mine, now)
        return rep

    def _conflicts_of(self, tx: Tx, row_id: int) -> list[dict[str, Any]]:
        """The open and person-resolved conflicts of a row (not those the engine closed as superseded)."""
        cols = ("id", "score", "documented_id", "documented_status", "documented_value", "documented_date",
                "derived_value", "tolerance", "resolution", "resolved_by", "resolved_at", "resolved_value")  # fmt: skip
        got = tx.fetchall(
            f"SELECT {', '.join(cols)} FROM conflict WHERE row_id = ? AND (resolution IS NULL OR resolution IN "
            f"({', '.join('?' for _ in DECISIONS)})) ORDER BY id",
            (row_id, *DECISIONS),
        )
        return [dict(zip(cols, r, strict=True)) for r in got]

    def _carry(
        self,
        tx: Tx,
        held: list[dict[str, Any]],
        new_id: int,
        value: float | None,
        anchor_date: date,
        given: Mapping[tuple[str, str], Documented],
        now: str,
    ) -> tuple[int, int]:
        """Carry the conflicts of a superseded row to the row that replaced it, checked against the stored documented
        value (the caller need not pass the documented scores again). A conflict is carried when the same documented
        record still applies: the caller did not pass a different version of it, its date is still near the anchor,
        and the new value still differs from it by more than the tolerance (else there is nothing to resolve). A
        person's resolution is kept unless the new value differs from the value it was made against by more than the
        tolerance: then the conflict opens again. Returns (carried, reopened)."""
        carried = reopened = 0
        for c in held:
            if value is None:
                continue  # no value: the row reads as unknown on its own
            doc = given.get((c["score"], c["documented_id"]))
            same = (c["documented_value"], c["documented_date"], c["documented_status"])
            if doc is not None and (doc.value, doc.on, doc.status) != same:
                continue  # the documented record changed: the caller's version is checked as new (_check)
            if abs((anchor_date - c["documented_date"]).days) > scores.DOCUMENTED_SPREAD_DAYS:
                continue
            tol = float(c["tolerance"])
            if abs(value - float(c["documented_value"])) <= tol:
                continue
            resolution, by, at, against = c["resolution"], c["resolved_by"], c["resolved_at"], c["resolved_value"]
            if resolution is not None:
                against = float(against if against is not None else c["derived_value"])
                if abs(value - against) > tol:  # the value the person decided on has moved: ask again
                    resolution = by = at = against = None
                    reopened += 1
            n = tx.execute(
                "INSERT INTO conflict (kind, pid, score, row_id, documented_id, documented_status, documented_value, "
                "documented_date, derived_value, tolerance, opened_at, resolution, resolved_by, resolved_at, "
                "resolved_value, carried_from) SELECT kind, pid, score, CAST(? AS BIGINT), documented_id, "
                "documented_status, documented_value, documented_date, CAST(? AS DOUBLE PRECISION), tolerance, "
                "CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS TEXT), CAST(? AS DOUBLE PRECISION), id "
                "FROM conflict WHERE id = ? ON CONFLICT (row_id, documented_id) DO NOTHING",
                (new_id, value, now, resolution, by, at, against, c["id"]),
            )
            carried += n
        return carried, reopened

    def _supersede(self, tx: Tx, row_id: int, now: str) -> None:
        tx.execute("UPDATE score_row SET superseded_at = ? WHERE id = ?", (now, row_id))
        tx.execute(
            "UPDATE conflict SET resolution = ?, resolved_by = ?, resolved_at = ? WHERE row_id = ? AND resolution "
            "IS NULL",
            (SUPERSEDED, "derived-engine", now, row_id),
        )

    def _insert(
        self,
        tx: Tx,
        pid: str,
        key: tuple[str, str],
        anchor: derived.Obs,
        res: derived.Derived,
        prov: list[dict[str, Any]],
        fp: str,
        mapping_version: str,
        now: str,
    ) -> int:
        score, anchor_oid = key
        d = scores.definition(score)
        value = res.value if res.reason is None else None
        reason = res.reason if value is None else None
        if value is None and reason is None:  # pragma: no cover - compute always says why
            reason = derived.MISSING
        new_id = int(
            tx.fetchval(
                "INSERT INTO score_row (pid, score, def_version, def_sha, mapping_version, anchor_oid, anchor_date, "
                "value, unit, reason, inputs, fingerprint, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "RETURNING id",
                (
                    pid,
                    score,
                    d["def_version"],
                    d["sha256"],
                    mapping_version,
                    anchor_oid,
                    anchor.on,
                    value,
                    scores.output_unit(score),
                    reason,
                    json.dumps(prov, sort_keys=True, ensure_ascii=False),
                    fp,
                    now,
                ),
            )
        )
        tx.executemany(
            "INSERT INTO input_link (row_id, component, source_table, source_id) VALUES (?, ?, ?, ?)",
            [(new_id, p["component"], p["table"], p["id"]) for p in prov if p["table"] == "observation"],
        )
        return new_id

    # ------------------------------------------------------------------------------------------ documented scores
    def check_documented(self, documented: Iterable[Documented]) -> int:
        """Compare documented scores with the computed rows near their date; open a conflict for each that differs
        by more than the tolerance. Returns the number of conflicts opened (an open one is never opened twice)."""
        with self._db.transaction() as tx:
            return self._check(tx, list(documented), _now())

    def _check(self, tx: Tx, documented: list[Documented], now: str) -> int:
        opened = 0
        for doc in documented:
            if doc.score not in scores.TOLERANCE:
                raise DerivedError(f"no tolerance for {doc.score}")
            if doc.status in NOT_DOCUMENTED:
                continue
            lo = doc.on - timedelta(days=scores.DOCUMENTED_SPREAD_DAYS)
            hi = doc.on + timedelta(days=scores.DOCUMENTED_SPREAD_DAYS)
            near = tx.fetchall(
                "SELECT id, value, anchor_date FROM score_row WHERE pid = ? AND score = ? AND superseded_at IS NULL "
                "AND value IS NOT NULL AND anchor_date BETWEEN ? AND ?",
                (doc.pid, doc.score, lo, hi),
            )
            if not near:
                continue  # no computable counterpart: the documented value stands alone as what it is
            row_id, value, _on = min(near, key=lambda r: (abs((r[2] - doc.on).days), -r[2].toordinal(), -r[0]))
            tol = scores.TOLERANCE[doc.score]
            if abs(float(value) - doc.value) <= tol:
                continue
            n = tx.execute(
                "INSERT INTO conflict (kind, pid, score, row_id, documented_id, documented_status, documented_value, "
                "documented_date, derived_value, tolerance, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (row_id, documented_id) DO NOTHING",
                (CONFLICT_KIND, doc.pid, doc.score, row_id, doc.did, doc.status, doc.value, doc.on, value, tol, now),
            )
            opened += n
        return opened

    def conflicts(self, pid: str | None = None, open_only: bool = True) -> list[dict[str, Any]]:
        q = "SELECT * FROM conflict WHERE (CAST(? AS TEXT) IS NULL OR pid = ?)"
        if open_only:
            q += " AND resolution IS NULL"
        return self._db.fetchdicts(q + " ORDER BY id", (pid, pid))

    def resolve(self, conflict_id: int, decision: str, by: str) -> None:
        """A person closes a conflict: ``keep_derived``, ``keep_documented`` or ``both_at_dates``."""
        if decision not in DECISIONS:
            raise DerivedError(f"decision must be one of {', '.join(DECISIONS)}")
        if not by:
            raise DerivedError("who resolved the conflict is required")
        n = self._db.execute(
            "UPDATE conflict SET resolution = ?, resolved_by = ?, resolved_at = ?, resolved_value = derived_value "
            "WHERE id = ? AND resolution IS NULL",
            (decision, by, _now(), conflict_id),
        )
        if n != 1:
            raise DerivedError(f"conflict {conflict_id} is not open")

    # ------------------------------------------------------------------------------------------ readers
    def rows(self, pid: str, score: str | None = None, current: bool = True) -> list[dict[str, Any]]:
        q = "SELECT * FROM score_row WHERE pid = ? AND (CAST(? AS TEXT) IS NULL OR score = ?)"
        if current:
            q += " AND superseded_at IS NULL"
        out = self._db.fetchdicts(q + " ORDER BY score, anchor_date, id", (pid, score, score))
        for r in out:
            r["inputs"] = json.loads(r["inputs"])
        return out

    def latest(self, pid: str, score: str, on: date, window_days: int | None = None) -> Latest:
        """The score a reader takes at ``on``: the newest current row anchored on or before it (within
        ``window_days`` when given). No row, a row with no value, or an open conflict is no value with a reason."""
        lo = on - timedelta(days=window_days if window_days is not None else derived.DEFAULT_WINDOW_DAYS[score])
        return self.latest_many([pid], score, lo, on)[pid]

    def latest_many(
        self, pids: Sequence[str], score: str, lo: date | None, hi: date, as_of: str | None = None
    ) -> dict[str, Latest]:
        """:meth:`latest` for many patients at once (D-442, the screening read): per patient the newest row
        anchored between ``lo`` (None: no lower bound) and ``hi``, newest anchor date first, then the larger anchor
        row id. ``as_of`` (a batch's ``finished_at``): the rows and conflicts as they stood then, so the same job
        reads the same rows on a re-run; None: the current rows and conflicts. Every patient asked for is in the
        answer."""
        out = {p: Latest(None, f"{derived.MISSING}:{derived.COMPONENTS[score][0]}") for p in pids}
        if not pids:
            return out
        valid = (
            "superseded_at IS NULL"
            if as_of is None
            else "computed_at <= ? AND (superseded_at IS NULL OR superseded_at > ?)"
        )
        rows = self._db.fetchall(
            "SELECT DISTINCT ON (pid) pid, id, value, reason, anchor_date, def_version, inputs, anchor_oid, def_sha "
            f"FROM score_row WHERE pid = ANY(?) AND score = ? AND {valid} AND anchor_date <= ? "
            "AND (CAST(? AS DATE) IS NULL OR anchor_date >= ?) "
            "ORDER BY pid, anchor_date DESC, anchor_oid DESC, id DESC",
            (list(pids), score, *(() if as_of is None else (as_of, as_of)), hi, lo, lo),
        )
        held: dict[int, list[tuple[Any, Any]]] = {}
        with_value = [int(r[1]) for r in rows if r[2] is not None]
        if with_value:
            for row_id, resolution, resolved_at, opened_at, documented in self._db.fetchall(
                "SELECT row_id, resolution, resolved_at, opened_at, documented_value FROM conflict "
                "WHERE row_id = ANY(?) ORDER BY id DESC",
                (with_value,),
            ):
                if as_of is not None:
                    if opened_at > as_of:
                        continue  # opened after the batch: not what the batch's readers saw
                    if resolution is not None and (resolved_at or "") > as_of:
                        resolution = None  # resolved later: it was open then
                if resolution is None or resolution == "keep_documented":
                    held.setdefault(int(row_id), []).append((resolution, documented))
        for pid, row_id, value, reason, anchor_date, def_version, inputs, anchor_oid, def_sha in rows:
            base = {"row_id": int(row_id), "anchor_date": anchor_date, "def_version": def_version,
                    "inputs": json.loads(inputs), "anchor_oid": anchor_oid, "def_sha": def_sha}  # fmt: skip
            cs = held.get(int(row_id), [])
            if value is None:
                out[pid] = Latest(None, reason, **base)
            elif any(c[0] is None for c in cs):
                out[pid] = Latest(None, CONFLICT_KIND, **base)
            elif cs:  # a person kept the documented value
                out[pid] = Latest(float(cs[0][1]), None, source="documented", **base)
            else:
                out[pid] = Latest(float(value), None, **base)
        return out

    # ------------------------------------------------------------------------------------------ batches (D-442)
    def begin_batch(self, snapshot: str, mapping_version: str) -> int:
        return int(
            self._db.fetchval(
                "INSERT INTO batch_run (snapshot, mapping_version, defs, started_at) VALUES (?, ?, ?, ?) RETURNING id",
                (snapshot, mapping_version, json.dumps(current_defs(), sort_keys=True), _now()),
            )
        )

    def finish_batch(self, run_id: int, rep: Report, patients: int) -> None:
        self._db.execute(
            "UPDATE batch_run SET finished_at = ?, patients = ?, inserted = ?, failed = ?, failed_pids = ? "
            "WHERE id = ?",
            (_now(), patients, rep.inserted, rep.failed, json.dumps(sorted(rep.failed_pids)), run_id),
        )

    def batch(self, snapshot: str) -> Batch | None:
        """The first finished derive batch of ``snapshot`` (a later batch of the same snapshot never changes what
        its readers read), or None when none finished: screening then reads every stored score as unknown."""
        r = self._db.fetchone(
            "SELECT id, defs, failed_pids, finished_at FROM batch_run WHERE snapshot = ? AND finished_at IS NOT NULL "
            "ORDER BY id LIMIT 1",
            (snapshot,),
        )
        if r is None:
            return None
        return Batch(int(r[0]), snapshot, dict(json.loads(r[1])), frozenset(json.loads(r[2] or "[]")), str(r[3]))

    def batch_by_id(self, run_id: int) -> Batch | None:
        """The finished derive batch with this run id (T-725, D-491: the batch a generation's build made), or None."""
        r = self._db.fetchone(
            "SELECT id, snapshot, defs, failed_pids, finished_at FROM batch_run "
            "WHERE id = ? AND finished_at IS NOT NULL",
            (run_id,),
        )
        if r is None:
            return None
        return Batch(int(r[0]), str(r[1]), dict(json.loads(r[2])), frozenset(json.loads(r[3] or "[]")), str(r[4]))

    def newest_batch_id(self, snapshot: str) -> int | None:
        """The run id of the newest finished derive batch of ``snapshot`` (the one a build that just ended made)."""
        got = self._db.fetchval(
            "SELECT max(id) FROM batch_run WHERE snapshot = ? AND finished_at IS NOT NULL", (snapshot,)
        )
        return int(got) if got is not None else None

    def last_batch(self) -> dict[str, Any] | None:
        """The newest derive batch, finished or not (readiness and health, D-442): snapshot, started, finished
        (None: it never finished), failed count."""
        got = self._db.fetchdicts(
            "SELECT snapshot, started_at, finished_at, patients, failed FROM batch_run ORDER BY id DESC LIMIT 1", ()
        )
        return got[0] if got else None


# ---------------------------------------------------------------------------------------------- the stores
FLAG = "derived.stored_read"
_lock = threading.Lock()
_stores: dict[str, DerivedStore] = {}


def shared_store(url: str | None = None) -> DerivedStore | None:
    """One derived store per trial database URL for the process (``TB_DB_URL`` when None); None without one. A
    store whose connection or schema went away (a restarted database) is opened again."""
    url = url or os.environ.get(ENV)
    if not url:
        return None
    with _lock:
        st = _stores.get(url)
        if st is not None:
            try:
                st.batch("")
            except Exception:
                st = None
        if st is None:
            st = _stores[url] = DerivedStore(url)
        return st


def stored_read(url: str | None = None) -> DerivedStore | None:
    """D-442: the store every screening path reads, or None. The audited flag ``derived.stored_read`` decides, for
    every path alike: off (the default) no path reads the store; on, each path reads it. A caller reads it once when
    its work starts and keeps it for the whole job."""
    from tb_common.flags import read

    url = url or os.environ.get(ENV)
    if not url or read(FLAG, url) != "on":
        return None
    return shared_store(url)


# ---------------------------------------------------------------------------------------------- the nightly batch
def rows_from_lake(
    lake: Any, pids: Sequence[str] | None = None, snapshot: str | None = None
) -> dict[str, tuple[dict[str, list[derived.Obs]], date | None, bool | None]]:
    """Each patient's component rows of the stored scores from a lake snapshot (``observation`` holds only the
    hospital feed and confirmed facts; proposed facts stay in ``site_fact`` and are never read here), with birth date
    and sex: ``{pid: ({component: [Obs]}, birth, female)}``.

    The lake's ``observation`` table has no status column, so each row's status is recorded as
    :data:`tb_common.derived.NOT_RECORDED` (it counts), never an invented ``final``. Until the lake carries
    ``Observation.status``, an entered-in-error or preliminary feed row is not filtered out here."""
    comps = sorted({c for s in STORED for c in derived.COMPONENTS[s]})
    by_code = {derived.CODES[c]: c for c in comps}
    pairs = ", ".join(f"('{sy}', '{co}')" for sy, co in sorted(by_code))  # constants, never user input
    obs = lake.query(
        "SELECT pid, system, code, value_num, unit, oid, CAST(effective AS DATE) AS d FROM observation "
        f"WHERE (system, code) IN ({pairs}) AND ($1::VARCHAR[] IS NULL OR list_contains($1::VARCHAR[], pid)) "
        "ORDER BY pid, d, oid",
        [list(pids) if pids is not None else None],
        snapshot,
    ).to_pylist()
    pats = lake.query(
        "SELECT pid, birth_date, sex FROM patient WHERE ($1::VARCHAR[] IS NULL OR list_contains($1::VARCHAR[], pid))",
        [list(pids) if pids is not None else None],
        snapshot,
    ).to_pylist()
    out: dict[str, tuple[dict[str, list[derived.Obs]], date | None, bool | None]] = {}
    for p in pats:
        sex = p["sex"]
        out[p["pid"]] = ({}, p["birth_date"], None if sex not in ("female", "male") else sex == "female")
    for r in obs:
        if r["pid"] not in out or r["d"] is None:
            continue
        comp = by_code[(r["system"], r["code"])]
        out[r["pid"]][0].setdefault(comp, []).append(
            derived.Obs(r["value_num"], r["unit"], r["d"], str(r["oid"]), derived.NOT_RECORDED)
        )
    return out


def run_batch(
    store: DerivedStore,
    lake: Any,
    *,
    mapping_version: str,
    pids: Sequence[str] | None = None,
    snapshot: str | None = None,
    documented: Iterable[Documented] = (),
    skip: Iterable[str] = (),
) -> Report:
    """The ``derive`` batch: recompute every patient of a lake snapshot (or ``pids``); writes only what changed. A
    patient whose recompute fails is counted in ``failed`` (and ``failed_pids``, pseudonyms) and the batch goes on
    with the next one: that patient's transaction is rolled back and their stored rows stay as they were.

    ``skip`` (D-798, T-206b): the opted-out pseudonyms; never recomputed, so the opt-out worker's clear of their rows
    holds."""
    docs: dict[str, list[Documented]] = {}
    for x in documented:
        docs.setdefault(x.pid, []).append(x)
    total = Report()
    # D-442: a batch over a named snapshot of every patient is recorded; screening of that snapshot reads its rows
    run_id = store.begin_batch(snapshot, mapping_version) if snapshot is not None and pids is None else None
    gone = set(skip)
    patients = {p: v for p, v in rows_from_lake(lake, pids, snapshot).items() if p not in gone}
    for pid, (rows, birth, female) in sorted(patients.items()):
        try:
            rep = store.recompute(
                pid, rows, mapping_version=mapping_version, birth=birth, female=female, documented=docs.get(pid, [])
            )
        except Exception as e:  # one bad patient never stops the night (the error type only: no values in the log)
            log.warning("derive: recompute failed for %s (%s)", pid, type(e).__name__)
            total.failed += 1
            total.failed_pids.append(pid)
            continue
        total.add(rep)
    if run_id is not None:
        store.finish_batch(run_id, total, len(patients))
    return total


def mapping_version_of(lake: Any, snapshot: str | None = None) -> str:
    """The mapping version(s) the snapshot's observation rows were mapped under (``lake.flatten`` provenance), as
    one sorted, comma-joined text; ``unrecorded`` when the rows name none (a lake built before T-106b)."""
    got = lake.query(
        "SELECT DISTINCT mapping_version AS v FROM observation WHERE mapping_version IS NOT NULL ORDER BY v",
        [],
        snapshot,
    ).to_pylist()
    return ",".join(str(r["v"]) for r in got) or "unrecorded"
