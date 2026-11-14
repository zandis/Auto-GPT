"""Data operations, first half (T-112a, D-427, deep review CR-067 and FIT-017): the ``dataops`` schema and the batch
states of an ingest night.

**One row per night.** Every ingest run is one ``dataops.batch`` row (source, snapshot, attempt): a re-run of the
same night is the next attempt, so a held night stays on the list until a steward decides it. The adapter opens the
row at the start of the run and closes it (``record_night``) at the end, in the same step as its
``ingest.done`` / ``ingest.held`` / ``ingest.failed`` audit event.

**States.** ``LANDED -> VALIDATED -> MAPPED -> PSEUDONYMISED -> PUBLISHED`` is the main line. Any state before
``PUBLISHED`` may go to ``HELD`` (the night is kept for a person to look at; ``CURRENT`` still names the previous
snapshot) or ``FAILED`` (the run stopped). ``HELD`` is left only by a steward's decision (``decide``), with a
reason: accept moves it to ``PUBLISHED`` (the caller's ``promote`` runs inside the same transaction, so a failed
promotion leaves the night held), reject moves it to ``REJECTED`` (the previous snapshot stays). ``PUBLISHED``,
``FAILED`` and ``REJECTED`` take no further step. ``NEXT`` is the only list of legal steps.

**The trail.** Every change is a row in ``batch_step`` (old, new, who, at, reason, and the audit event that
recorded it). ``batch_step`` is append-only (a trigger refuses UPDATE, DELETE and TRUNCATE). A deferred constraint
trigger on ``batch`` refuses, at commit, a batch row whose state has no step row for it: a batch row cannot be
written without its trail. The audit event is appended while that transaction is open, before the step rows
that name it: if the audit refuses (disk full, journal down), nothing is stored.

**Reading (T-112b, D-443).** ``history`` (newest first, filtered and cut here), ``sources`` (the newest night of each
source) and ``counts`` feed the steward's ``/data-ops`` page and ``/api/v1/data/*`` (``console.dataops_page``);
``newest_night`` feeds the readiness page without migrating. The steward check (``permit``) is the page's; this module
only refuses a decision without a person and a reason.

**A row from the start (T-723, D-489).** ``open_night`` writes the row when the run starts (``LANDED``); the running
night writes its step into the row's detail (``note``); ``record_night`` closes that row. A row left open by a run
that died is closed ``FAILED`` ("interrupted") when the next run of that night opens its own. The steward's accept
publishes through the adapter (``adapter.publish``; ``console.dataops_page`` gets its promoter).

What is not here yet: the record status and consent tables.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from tb_common.db import ENV, Database, DatabaseError

from datacore import pgfunc

LANDED, VALIDATED, MAPPED, PSEUDONYMISED, PUBLISHED = "LANDED", "VALIDATED", "MAPPED", "PSEUDONYMISED", "PUBLISHED"
HELD, FAILED, REJECTED = "HELD", "FAILED", "REJECTED"
LINE = (LANDED, VALIDATED, MAPPED, PSEUDONYMISED, PUBLISHED)
STATES = (*LINE, HELD, FAILED, REJECTED)
FINAL = (PUBLISHED, FAILED, REJECTED)
NEXT: dict[str, tuple[str, ...]] = {
    LANDED: (VALIDATED, HELD, FAILED),
    VALIDATED: (MAPPED, HELD, FAILED),
    MAPPED: (PSEUDONYMISED, HELD, FAILED),
    PSEUDONYMISED: (PUBLISHED, HELD, FAILED),
    HELD: (PUBLISHED, REJECTED),  # only through ``decide``
    PUBLISHED: (),
    FAILED: (),
    REJECTED: (),
}
DECISIONS = {"accept": PUBLISHED, "reject": REJECTED}
EVENT_DECIDE = "dataops.decide"
EVENT_STEP = "dataops.step"
# what a batch row keeps from the night's audit detail (tables and counts only, never a row)
DETAIL_KEYS = (
    "gate",
    "incomplete",
    "orphans",
    "quarantined",
    "duplicate_keys",
    "unmapped",
    "unmapped_kinds",  # NEW-B-39 (D-740): the same rows per table split by kind, counts only
    "error",
    "step",
    "table",
    "publish",
)
NOTE_KEYS = ("step", "publish")  # what a running night writes into its row (T-723): step names and states only
INTERRUPTED = "interrupted: the run ended without a result; a later run of this night started"
#: T-723 review (HIGH-2): a held night whose accept was recorded and whose publish has started. It stays HELD in the
#: row until the publish is known to have ended, but it can no longer be rejected: only accepted again, which
#: resumes the publish or records that it ended
ACCEPTING = "accept:publishing"
NOT_PUBLISHED = "accept:not published"
MAX_PAGE = 200  # T-112b: the most batch rows one page or API call reads

_STATE_LIST = ", ".join(f"'{s}'" for s in STATES)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS batch (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, source TEXT NOT NULL,
  snapshot TEXT NOT NULL, attempt INTEGER NOT NULL, state TEXT NOT NULL CHECK (state IN ({_STATE_LIST})),
  seq INTEGER NOT NULL, started_at TEXT NOT NULL, changed_at TEXT NOT NULL, changed_by TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{{}}', UNIQUE (source, snapshot, attempt));
CREATE TABLE IF NOT EXISTS batch_step (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  batch BIGINT NOT NULL REFERENCES batch (id), seq INTEGER NOT NULL, old TEXT NOT NULL DEFAULT '',
  new TEXT NOT NULL CHECK (new IN ({_STATE_LIST})), who TEXT NOT NULL, at TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '', audit_event TEXT NOT NULL, audit_ref TEXT NOT NULL, UNIQUE (batch, seq));
CREATE INDEX IF NOT EXISTS batch_by_state ON batch (state, snapshot)
"""

# T-725 (D-491): which generation each derived artefact (the FHIR store's night, the derived rows, the twins, the
# vectors) is built from, and whether that build finished; one row per artefact, no patient data. ``ref``: what the
# build made, in the store's own terms (the derive batch's run id), so a reader takes that and no other
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS built (artefact TEXT PRIMARY KEY, snapshot TEXT NOT NULL, seq INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('building', 'finished')), started_at TEXT NOT NULL, finished_at TEXT,
  ref TEXT NOT NULL DEFAULT '')
"""
# NEW-B-4 (D-525): the finished generations of an artefact whose store keeps its history (the derived rows: a batch
# is read "as of"), one row per generation with what its newest finished build made. ``built`` stays the one row
# that says what the artefact is built from now; this says what may still be read. No patient data
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS built_kept (artefact TEXT NOT NULL, snapshot TEXT NOT NULL, seq INTEGER NOT NULL,
  finished_at TEXT NOT NULL, ref TEXT NOT NULL, PRIMARY KEY (artefact, snapshot, seq))
"""
#: ``migrate`` versions of schema ``dataops`` (append-only)
MIGRATIONS = (SCHEMA, SCHEMA_V2, SCHEMA_V3)

# plpgsql bodies hold ``;`` (``Database.migrate`` splits on it), so the triggers are made after the migration
_FUNCTIONS = (
    "CREATE OR REPLACE FUNCTION dataops_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
    "RAISE EXCEPTION USING MESSAGE = 'dataops.' || TG_TABLE_NAME || ' is append-only', "
    "ERRCODE = 'insufficient_privilege'; END $$",
    "CREATE OR REPLACE FUNCTION dataops_batch_has_step() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
    "IF NOT EXISTS (SELECT 1 FROM batch_step s WHERE s.batch = NEW.id AND s.seq = NEW.seq AND s.new = NEW.state) "
    "THEN RAISE EXCEPTION USING MESSAGE = 'dataops.batch ' || NEW.id || ' has no step for state ' || NEW.state, "
    "ERRCODE = 'integrity_constraint_violation'; END IF; RETURN NULL; END $$",
)
_TRIGGERS = {
    "batch_step_append_only": "CREATE TRIGGER batch_step_append_only BEFORE UPDATE OR DELETE ON batch_step "
    "FOR EACH ROW EXECUTE FUNCTION dataops_append_only()",
    "batch_step_no_truncate": "CREATE TRIGGER batch_step_no_truncate BEFORE TRUNCATE ON batch_step "
    "FOR EACH STATEMENT EXECUTE FUNCTION dataops_append_only()",
    "batch_has_step": "CREATE CONSTRAINT TRIGGER batch_has_step AFTER INSERT OR UPDATE ON batch "
    "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION dataops_batch_has_step()",
}


class Audit(Protocol):
    def append(self, event: str, **fields: Any) -> dict[str, Any]: ...


class DataOpsError(ValueError):
    def __init__(self, why: str, message: str) -> None:
        super().__init__(f"{why}: {message}")
        self.why = why
        self.message = message


@dataclass(frozen=True)
class Batch:
    id: int
    source: str
    snapshot: str
    attempt: int
    state: str
    seq: int
    started_at: str
    changed_at: str
    changed_by: str
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _shown(detail: dict[str, Any]) -> dict[str, Any]:
    """The hold reasons a steward is shown for a held night, as the row keeps them (``DETAIL_KEYS``: tables and
    counts, never a row or an identifier), for the audit of the decision."""
    return {k: detail[k] for k in ("gate", "incomplete", "orphans", "quarantined", "duplicate_keys", "error")
            if detail.get(k)}  # fmt: skip


def can_step(cur: str, to: str) -> str | None:
    """Why the step ``cur -> to`` is refused, or ``None`` when it is legal."""
    if cur not in NEXT or to not in NEXT:
        return f"unknown state {cur if cur not in NEXT else to!r}"
    if cur in FINAL:
        return f"{cur} is final"
    if to not in NEXT[cur]:
        return f"{cur} -> {to} is not a step"
    return None


def night_path(passed: bool, held: bool) -> tuple[str, ...]:
    """The states a night went through, from the pipeline's outcome. A held night is held at the gate (validation,
    completeness, contracts or the lake's refusal), recorded from ``LANDED``; a run that stopped is ``FAILED``."""
    if passed:
        return LINE
    return (LANDED, HELD) if held else (LANDED, FAILED)


def _ref(rec: Mapping[str, Any]) -> str:
    """The audit record's reference: its hash in the chain, or its journal sequence (``TB_AUDIT_WRITER=db``)."""
    if rec.get("hash"):
        return str(rec["hash"])
    journal = rec.get("journal") or {}
    if isinstance(journal, Mapping) and journal.get("seq") is not None:
        return f"journal:{journal['seq']}"
    raise DataOpsError("audit_ref", "the audit writer returned no hash and no journal sequence")


def _batch(row: Mapping[str, Any]) -> Batch:
    return Batch(int(row["id"]), str(row["source"]), str(row["snapshot"]), int(row["attempt"]), str(row["state"]),
                 int(row["seq"]), str(row["started_at"]), str(row["changed_at"]), str(row["changed_by"]),
                 json.loads(row["detail"] or "{}"))  # fmt: skip


def newest_night(url: str | None = None) -> Batch | None:
    """T-112b (D-443): the newest night of any source, read without migrating (the readiness page asks on every
    view). ``None`` when no night is recorded; raises ``DatabaseError`` when the store or the schema is not there, so
    the caller can fall back to the audit chain."""
    db = Database.connect(url or os.environ.get(ENV), "dataops")
    try:
        rows = db.fetchdicts("SELECT * FROM batch ORDER BY snapshot DESC, attempt DESC, id DESC LIMIT 1")
    except Exception as exc:  # no table yet (no night ever recorded with this schema)
        raise DatabaseError(f"dataops not readable: {type(exc).__name__}") from exc
    finally:
        db.close()
    return _batch(rows[0]) if rows else None


class DataOps:
    """The ``dataops`` schema of the trial database (D-126)."""

    def __init__(self, url: str | None = None) -> None:
        self._db = Database.connect(url or os.environ.get(ENV), "dataops")
        self._db.migrate(list(MIGRATIONS))
        with self._db.transaction() as tx:
            pgfunc.ensure(tx, "dataops_triggers", _FUNCTIONS, _TRIGGERS)

    @property
    def db(self) -> Database:
        return self._db

    def close(self) -> None:
        self._db.close()

    # ------------------------------------------------------------------ reading
    def batch(self, batch_id: int) -> Batch | None:
        rows = self._db.fetchdicts("SELECT * FROM batch WHERE id = ?", (batch_id,))
        return _batch(rows[0]) if rows else None

    def batches(self, state: str | None = None, source: str | None = None) -> list[Batch]:
        sql, args = "SELECT * FROM batch WHERE 1 = 1", list[str]()
        if state is not None:
            sql, args = sql + " AND state = ?", [*args, state]
        if source is not None:
            sql, args = sql + " AND source = ?", [*args, source]
        return [_batch(r) for r in self._db.fetchdicts(sql + " ORDER BY snapshot, attempt, id", tuple(args))]

    def held(self) -> list[Batch]:
        return self.batches(HELD)

    def history(self, state: str | None = None, source: str | None = None, *, limit: int = 50,
                before: int | None = None) -> list[Batch]:  # fmt: skip
        """T-112b (D-443): the ingest history the console shows, newest first, filtered and cut by the store (never
        a whole table read and filtered in the page). ``before``: the id the previous page ended on."""
        sql, args = "SELECT * FROM batch WHERE 1 = 1", list[Any]()
        for col, val in (("state", state), ("source", source)):
            if val is not None:
                sql, args = sql + f" AND {col} = ?", [*args, val]
        if before is not None:
            sql, args = sql + " AND id < ?", [*args, before]
        limit = max(1, min(int(limit), MAX_PAGE))
        return [_batch(r) for r in self._db.fetchdicts(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    def sources(self) -> list[Batch]:
        """T-112b: the newest night of every source (its light on the console)."""
        sql = "SELECT DISTINCT ON (source) * FROM batch ORDER BY source, snapshot DESC, attempt DESC, id DESC"
        return [_batch(r) for r in self._db.fetchdicts(sql)]

    def counts(self) -> dict[str, int]:
        """T-112b: how many nights are in each state."""
        return {str(r[0]): int(r[1]) for r in self._db.fetchall("SELECT state, count(*) FROM batch GROUP BY state")}

    def steps(self, batch_id: int) -> list[dict[str, Any]]:
        return self._db.fetchdicts("SELECT * FROM batch_step WHERE batch = ? ORDER BY seq", (batch_id,))

    # ------------------------------------------------------------------ writing
    def open_night(self, audit: Audit, *, source: str, snapshot: str, by: str, at: str) -> Batch:
        """T-723 (D-489): the night's row, opened when its run starts (``LANDED``, the next attempt), so a running
        night is on the list. An earlier attempt of this night that is still open (a run that died: not final, not
        held) is closed ``FAILED`` with the reason "interrupted" in the same transaction: no night shows as running
        for ever. :meth:`record_night` closes the row with the night's audit event."""
        with self._db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"dataops.batch:{source}:{snapshot}",))
            stale = tx.fetchdicts(
                "SELECT * FROM batch WHERE source = ? AND snapshot = ? AND state = ANY(?) ORDER BY id FOR UPDATE",
                (source, snapshot, list(LINE[:-1])),
            )
            for srow in stale:
                old = _batch(srow)
                rec = audit.append(
                    EVENT_STEP,
                    snapshot=snapshot,
                    actor=by,
                    detail={"batch": old.id, "source": source, "attempt": old.attempt, "old": old.state,
                            "new": FAILED, "reason": INTERRUPTED},
                )  # fmt: skip
                tx.execute("UPDATE batch SET state = ?, seq = ?, changed_at = ?, changed_by = ? WHERE id = ?",
                           (FAILED, old.seq + 1, at, by, old.id))  # fmt: skip
                self._step(tx, old.id, old.seq + 1, old.state, FAILED, by, at, INTERRUPTED, EVENT_STEP, _ref(rec))
            attempt = int(tx.fetchval("SELECT coalesce(max(attempt), 0) + 1 FROM batch WHERE source = ? AND "
                                      "snapshot = ?", (source, snapshot), 1))  # fmt: skip
            new_row = tx.fetchone(
                "INSERT INTO batch (source, snapshot, attempt, state, seq, started_at, changed_at, changed_by, "
                "detail) VALUES (?,?,?,?,?,?,?,?,?) RETURNING id",
                (source, snapshot, attempt, LANDED, 1, at, at, by, json.dumps({"step": "start"})),
            )
            assert new_row is not None
            bid = int(new_row[0])
            rec = audit.append(
                EVENT_STEP,
                snapshot=snapshot,
                actor=by,
                detail={"batch": bid, "source": source, "attempt": attempt, "old": "", "new": LANDED, "reason": ""},
            )
            self._step(tx, bid, 1, "", LANDED, by, at, "", EVENT_STEP, _ref(rec))
        got = self.batch(bid)
        assert got is not None
        return got

    @staticmethod
    def _step(tx: Any, batch: int, seq: int, old: str, new: str, who: str, at: str, reason: str, event: str,
              ref: str) -> None:  # fmt: skip
        tx.execute(
            "INSERT INTO batch_step (batch, seq, old, new, who, at, reason, audit_event, audit_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (batch, seq, old, new, who, at, reason, event, ref),
        )

    def note(self, batch_id: int, **detail: Any) -> None:
        """Write where a running night is into its row's detail (``step``, ``publish``: names and states only, never
        a row). The state and the trail do not change. A row that is final is left alone."""
        with self._db.transaction() as tx:
            rows = tx.fetchdicts("SELECT * FROM batch WHERE id = ? FOR UPDATE", (batch_id,))
            if not rows or rows[0]["state"] in FINAL:
                return
            cur = json.loads(rows[0]["detail"] or "{}")
            cur.update({k: v for k, v in detail.items() if k in NOTE_KEYS})
            tx.execute("UPDATE batch SET detail = ? WHERE id = ?",
                       (json.dumps(cur, ensure_ascii=False, sort_keys=True), batch_id))  # fmt: skip

    def record_night(
        self,
        audit: Audit,
        event: str,
        *,
        source: str,
        snapshot: str,
        passed: bool,
        held: bool,
        by: str,
        at: str,
        started_at: str = "",
        batch_id: int | None = None,
        **fields: Any,
    ) -> tuple[Batch, dict[str, Any]]:
        """The adapter's hook: the night's batch row, its steps and the night's audit event, in one transaction.
        Returns the batch and the audit record. The audit event's ``detail`` gains ``batch`` (the row's id and
        state). ``batch_id``: the row :meth:`open_night` opened for this run (T-723, D-489); it is closed along the
        rest of its path. Without one (or when that row is gone or already final) a row is written whole, as before."""
        path = night_path(passed, held)
        detail = fields.get("detail") or {}
        kept = {k: detail[k] for k in DETAIL_KEYS if isinstance(detail, Mapping) and detail.get(k) is not None}
        with self._db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"dataops.batch:{source}:{snapshot}",))
            opened = tx.fetchdicts("SELECT * FROM batch WHERE id = ? FOR UPDATE", (batch_id,)) if batch_id else []
            if opened and opened[0]["state"] == LANDED and int(opened[0]["seq"]) == 1:
                bid, attempt, first = int(opened[0]["id"]), int(opened[0]["attempt"]), 2
                tx.execute("UPDATE batch SET state = ?, seq = ?, changed_at = ?, changed_by = ?, detail = ? "
                           "WHERE id = ?", (path[-1], len(path), at, by,
                                            json.dumps(kept, ensure_ascii=False, sort_keys=True), bid))  # fmt: skip
            else:
                attempt = int(tx.fetchval("SELECT coalesce(max(attempt), 0) + 1 FROM batch WHERE source = ? AND "
                                          "snapshot = ?", (source, snapshot), 1))  # fmt: skip
                row = tx.fetchone(
                    "INSERT INTO batch (source, snapshot, attempt, state, seq, started_at, changed_at, changed_by, "
                    "detail) VALUES (?,?,?,?,?,?,?,?,?) RETURNING id",
                    (source, snapshot, attempt, path[-1], len(path), started_at or at, at, by,
                     json.dumps(kept, ensure_ascii=False, sort_keys=True)),
                )  # fmt: skip
                assert row is not None
                bid, first = int(row[0]), 1
            fields["detail"] = {**detail, "batch": {"id": bid, "attempt": attempt, "state": path[-1]}}
            rec = audit.append(event, snapshot=snapshot, **fields)
            ref = _ref(rec)
            for seq, new in enumerate(path, start=1):
                if seq >= first:
                    tx.execute(
                        "INSERT INTO batch_step (batch, seq, old, new, who, at, reason, audit_event, audit_ref) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (bid, seq, path[seq - 2] if seq > 1 else "", new, by, at, "", event, ref),
                    )
        got = self.batch(bid)
        assert got is not None
        return got, rec

    def advance(self, audit: Audit, batch_id: int, to: str, *, by: str, at: str, reason: str = "") -> Batch:
        """One step along the line, or to ``HELD`` / ``FAILED``; ``HELD`` is never left here (``decide``)."""
        cur = self.batch(batch_id)
        if cur is None:
            raise DataOpsError("not_found", f"no batch {batch_id}")
        if cur.state == HELD:
            raise DataOpsError("held", "a held night is left only by a steward's accept or reject")
        return self._move(audit, batch_id, to, by=by, at=at, reason=reason, event=EVENT_STEP)

    def decide(self, audit: Audit, batch_id: int, decision: str, *, by: str, at: str, reason: str,
               promote: Callable[[Batch], None] | None = None) -> Batch:  # fmt: skip
        """A steward's accept or reject of a held night, with a reason. Accept runs ``promote`` (the publish of the
        night): if it raises, the night stays held. An exception that says ``nothing_served`` leaves an ordinary
        held night; any other leaves the accept recorded (see below)."""
        if decision not in DECISIONS:
            raise DataOpsError("decision", f"decision must be one of {sorted(DECISIONS)}")
        if not by.strip():
            raise DataOpsError("by", "a decision names the person who took it")
        if not reason.strip():
            raise DataOpsError("reason", "a decision on a held night needs a reason")
        cur = self.batch(batch_id)
        if cur is None:
            raise DataOpsError("not_found", f"no batch {batch_id}")
        if cur.state != HELD:
            raise DataOpsError("not_held", f"batch {batch_id} is {cur.state}, not HELD")
        if decision == "reject":
            if cur.detail.get("step") == ACCEPTING:
                raise DataOpsError(
                    "publishing",
                    f"batch {batch_id} is being published or has been published (its accept was recorded): accept "
                    "it again to record the end; it can no longer be rejected",
                )
            return self._move(audit, batch_id, REJECTED, by=by, at=at, reason=reason, event=EVENT_DECIDE,
                              decision=decision)  # fmt: skip
        if promote is None:
            return self._move(audit, batch_id, PUBLISHED, by=by, at=at, reason=reason, event=EVENT_DECIDE,
                              decision=decision)  # fmt: skip
        # T-723 review (HIGH-2): the accept is recorded before anything is published (the audit and the row), the
        # publish runs outside any transaction, and its end is recorded after it. A publish whose end is not known
        # (the console lost the adapter's job) leaves the accept recorded: the night cannot be rejected any more,
        # and a second accept resumes the publish or records that it ended
        base = {"batch": batch_id, "source": cur.source, "attempt": cur.attempt, "decision": decision,
                "reason": reason, "shown": _shown(cur.detail)}  # fmt: skip
        with self._db.transaction() as tx:
            rows = tx.fetchdicts("SELECT * FROM batch WHERE id = ? FOR UPDATE", (batch_id,))
            if not rows or rows[0]["state"] != HELD:
                raise DataOpsError("not_held", f"batch {batch_id} is no longer HELD")
            before = json.loads(rows[0]["detail"] or "{}").get("step")
            detail = {**json.loads(rows[0]["detail"] or "{}"), "step": ACCEPTING}
            tx.execute("UPDATE batch SET detail = ? WHERE id = ?",
                       (json.dumps(detail, ensure_ascii=False, sort_keys=True), batch_id))  # fmt: skip
            audit.append(EVENT_DECIDE, snapshot=cur.snapshot, actor=by, detail={**base, "phase": "started"})
        try:
            promote(cur)
        except Exception as exc:
            nothing = bool(getattr(exc, "nothing_served", False))
            # second review (H4): refused before anything started. This accept changed nothing, so the row says
            # what it said before: an earlier accept whose end is not known stays recorded
            unstarted = bool(getattr(exc, "not_started", False))
            if nothing or (unstarted and before != ACCEPTING):  # an ordinary held night again
                self.note(batch_id, step=NOT_PUBLISHED)
            outcome = "not published" if nothing else "not started" if unstarted else "unknown"
            audit.append(EVENT_DECIDE, snapshot=cur.snapshot, actor=by, detail={
                **base, "phase": "ended", "outcome": outcome, "error": type(exc).__name__})  # fmt: skip
            raise
        return self._move(audit, batch_id, PUBLISHED, by=by, at=at, reason=reason, event=EVENT_DECIDE,
                          decision=decision, outcome="published")  # fmt: skip

    def _move(self, audit: Audit, batch_id: int, to: str, *, by: str, at: str, reason: str, event: str,
              decision: str = "", hook: Callable[[Batch], None] | None = None, outcome: str = "") -> Batch:  # fmt: skip
        with self._db.transaction() as tx:
            rows = tx.fetchdicts("SELECT * FROM batch WHERE id = ? FOR UPDATE", (batch_id,))
            if not rows:
                raise DataOpsError("not_found", f"no batch {batch_id}")
            cur = _batch(rows[0])
            why = can_step(cur.state, to)
            if why is not None:
                raise DataOpsError("step", why)
            if to == REJECTED and cur.detail.get("step") == ACCEPTING:
                # second review (M1): asked again under the row's lock; an accept recorded since the caller read
                # the row wins
                raise DataOpsError(
                    "publishing",
                    f"batch {batch_id} is being published or has been published (its accept was recorded): accept "
                    "it again to record the end; it can no longer be rejected",
                )
            seq = cur.seq + 1
            tx.execute("UPDATE batch SET state = ?, seq = ?, changed_at = ?, changed_by = ? WHERE id = ?",
                       (to, seq, at, by, batch_id))  # fmt: skip
            if hook is not None:
                hook(cur)
            detail: dict[str, Any] = {"batch": batch_id, "source": cur.source, "attempt": cur.attempt,
                                      "old": cur.state, "new": to, "reason": reason}  # fmt: skip
            if decision:
                detail["decision"] = decision
                detail["shown"] = _shown(cur.detail)  # what the steward was shown: counts and names, no identifier
            if outcome:
                detail["outcome"] = outcome
            rec = audit.append(event, snapshot=cur.snapshot, actor=by, detail=detail)
            tx.execute("INSERT INTO batch_step (batch, seq, old, new, who, at, reason, audit_event, audit_ref) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", (batch_id, seq, cur.state, to, by, at, reason, event,
                                                      _ref(rec)))  # fmt: skip
        got = self.batch(batch_id)
        assert got is not None
        return got
