"""The weekly PI sample of "criteria not matched" and the site's check that opens the list (T-310a, D-446).

URS-PI-05: the investigator sees the patients whose records did not match a criterion; the list is shown only after
the site's real-data check (the dry run) is within its thresholds; and ten of these patients a week are sampled for
the study's PI. Schema ``tuned`` of the trial database (``TB_DB_URL``) holds both, for the console, the orchestrator's
weekly job and Study A (T-627) alike:

* ``tuned_patients``: one row per sampled patient: the study, the week (ISO week of the site's calendar), the
  pseudonym, the screening run it was drawn from and **that run's own snapshot** (T-305a, D-383: the sample reads the
  run's stored list, never the lake's current snapshot), the criteria not matched, and the PI's answer (``agree``: the
  records do not match, as the run said; ``send_back``: the patient goes back to the PI's weekly list) with who and
  when. A patient is drawn at most once per study and week; an answer is given once.
* ``not_matched_check``: the site's check, an event log; the latest row is the record. ``passed`` with the id of the
  dry-run record opens the list; a later row that says "not passed" closes it again.

The draw is deterministic: the run's patients ordered by ``sha256(study | week | job | pseudonym)``, the first ten
taken. A patient on the opt-out register is never drawn (``tb_common.optout``), and never answered for later.

Where the check applies (:func:`gate_on`): ``TB_NOT_MATCHED_GATE`` ``auto`` (default) holds the list in VALIDATION and
PRODUCTION, where real data is read, and not in DEV and TEST (D-311: synthetic data only); ``on`` holds it anywhere;
``off`` is refused in VALIDATION and PRODUCTION.

Nothing here holds a chart number or a name.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from tb_common.config import environment_name
from tb_common.db import ENV, Database

SCHEMA = "tuned"
SAMPLE_SIZE = 10
ANSWERS = ("agree", "send_back")
GATE_ENVS = ("VALIDATION", "PRODUCTION")  # where the list waits for the site's check and the gate cannot be off
NOTE_MAX = 300
RECORD_MAX = 80
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")

SCHEMA_V1 = """
CREATE TABLE tuned_patients (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  week TEXT COLLATE "C" NOT NULL,
  pid TEXT NOT NULL,
  job_id TEXT NOT NULL,
  snapshot TEXT NOT NULL DEFAULT '',
  ruleset_version TEXT NOT NULL DEFAULT '',
  criteria TEXT NOT NULL DEFAULT '',
  drawn_by TEXT NOT NULL,
  drawn_at TEXT COLLATE "C" NOT NULL,
  answer TEXT,
  note TEXT,
  answered_by TEXT,
  answered_at TEXT COLLATE "C",
  UNIQUE (ruleset, week, pid)
);
CREATE INDEX tuned_patients_week ON tuned_patients (ruleset, week, id);
CREATE TABLE not_matched_check (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  passed BOOLEAN NOT NULL,
  record TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX not_matched_check_rs ON not_matched_check (ruleset, id)
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1,)
_COLS = ("ruleset, week, pid, job_id, snapshot, ruleset_version, criteria, drawn_by, drawn_at, answer, note, "
         "answered_by, answered_at")  # fmt: skip


class NotMatchedError(ValueError):
    """A sample answer or a check that cannot be recorded: the key of the message to show."""


@dataclass(frozen=True)
class Tuned:
    """One sampled patient."""

    ruleset: str
    week: str
    pid: str
    job_id: str
    snapshot: str
    ruleset_version: str
    criteria: tuple[str, ...]
    drawn_by: str
    drawn_at: str
    answer: str | None
    note: str | None
    answered_by: str | None
    answered_at: str | None


@dataclass(frozen=True)
class Check:
    """The site's check of one study's not-matched list, as last recorded."""

    ruleset: str
    passed: bool
    record: str
    note: str
    by: str
    at: str


def _tuned(r: Any) -> Tuned:
    crit = tuple(c for c in str(r[6] or "").split(",") if c)
    return Tuned(str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), crit, str(r[7]), str(r[8]),
                 r[9], r[10], r[11], r[12])  # fmt: skip


def _iso(at: str) -> str:
    dt = datetime.fromisoformat(at)
    if dt.tzinfo is None:
        raise NotMatchedError("times carry an offset")
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def iso_week(day: date) -> str:
    """``2026-W46``: the ISO week of a site calendar day (the caller gives the site's day, D-270)."""
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def gate_on(env: Mapping[str, str]) -> bool:
    """Is the not-matched list held until the study's site check passes? ``TB_NOT_MATCHED_GATE``: ``auto`` (on in
    VALIDATION and PRODUCTION), ``on`` or ``off``; ``off`` is refused in VALIDATION and PRODUCTION (ValueError)."""
    mode = (env.get("TB_NOT_MATCHED_GATE") or "auto").strip().lower()
    if mode not in ("auto", "on", "off"):
        raise ValueError(f"TB_NOT_MATCHED_GATE must be auto, on or off, got {mode!r}")
    name = environment_name(env)
    if mode == "off" and name in GATE_ENVS:
        raise ValueError(f"TB_NOT_MATCHED_GATE=off is refused in {name}")
    return name in GATE_ENVS if mode == "auto" else mode == "on"


def draw(
    rows: Iterable[Mapping[str, Any]], seed: str, skip: Iterable[str] = (), n: int = SAMPLE_SIZE
) -> list[dict[str, Any]]:
    """``n`` rows of a run's not-matched list, the same ones for the same ``seed``: ordered by
    ``sha256(seed | pseudonym)``. ``skip``: pseudonyms never drawn (the opt-out register). One row per pseudonym."""
    out = set(skip)
    seen: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = str(r.get("pid") or "")
        if _PID.match(pid) and pid not in out and pid not in seen:
            seen[pid] = dict(r)

    def key(pid: str) -> str:
        return hashlib.sha256(f"{seed}|{pid}".encode()).hexdigest()

    return [seen[p] for p in sorted(seen, key=key)[: max(0, n)]]


def criteria_of(row: Mapping[str, Any]) -> tuple[str, ...]:
    """The criterion ids a not-matched row names; a row the run's own rule removed (scope, consent) names ``rule``."""
    ids = [str(c.get("id")) for c in row.get("criteria") or [] if c.get("id")]
    return tuple(dict.fromkeys(ids)) or ("rule",)


class NotMatchedStore:
    """Schema ``tuned`` of the trial database. ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = Database.connect(url if url is not None else os.environ.get(ENV), SCHEMA)
        self.db.migrate(MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ the sample
    def sample(self, ruleset: str, week: str) -> list[Tuned]:
        rows = self.db.fetchall(f"SELECT {_COLS} FROM tuned_patients WHERE ruleset = ? AND week = ? ORDER BY id",
                                (ruleset, week))  # fmt: skip
        return [_tuned(r) for r in rows]

    def history(self, ruleset: str, limit: int = 500) -> list[Tuned]:
        """Every sampled patient of a study, newest week first (Study A reads the table itself)."""
        rows = self.db.fetchall(
            f"SELECT {_COLS} FROM tuned_patients WHERE ruleset = ? ORDER BY week DESC, id LIMIT ?", (ruleset, limit)
        )
        return [_tuned(r) for r in rows]

    def counts(self, ruleset: str) -> dict[str, int]:
        """The study's counter: weeks sampled, patients sampled, answered, sent back."""
        r = self.db.fetchone(
            "SELECT COUNT(DISTINCT week), COUNT(*), COUNT(answer), "
            "COALESCE(SUM(CASE WHEN answer = 'send_back' THEN 1 ELSE 0 END), 0) FROM tuned_patients WHERE ruleset = ?",
            (ruleset,),
        )
        weeks, n, answered, back = (int(x or 0) for x in (r or (0, 0, 0, 0)))
        return {"weeks": weeks, "sampled": n, "answered": answered, "sent_back": back}

    def record_sample(self, ruleset: str, week: str, rows: list[dict[str, Any]], *, job_id: str, snapshot: str,
                      version: str, by: str, at: str) -> tuple[list[Tuned], bool]:  # fmt: skip
        """Store the week's sample unless the study has one for the week already. Returns (the week's sample, whether
        this call drew it). Two drawers at once (the weekly job and a page view) keep one sample."""
        if not _RS.match(ruleset):
            raise NotMatchedError("nm.err.study")
        drawn = False
        with self.db.transaction() as tx:
            have = tx.fetchval("SELECT COUNT(*) FROM tuned_patients WHERE ruleset = ? AND week = ?", (ruleset, week))
            if not int(have or 0) and rows:
                for r in rows:
                    tx.execute(
                        "INSERT INTO tuned_patients (ruleset, week, pid, job_id, snapshot, ruleset_version, criteria, "
                        "drawn_by, drawn_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (ruleset, week, pid) DO NOTHING",
                        (ruleset, week, str(r["pid"]), job_id, snapshot, version, ",".join(criteria_of(r))[:400],
                         by, _iso(at)),
                    )  # fmt: skip
                drawn = True
        return self.sample(ruleset, week), drawn

    def answer(self, ruleset: str, week: str, pid: str, answer: str, note: str, by: str, at: str,
               before_commit: Callable[[], None] | None = None) -> Tuned:  # fmt: skip
        """The PI's answer for one sampled patient, once. ``before_commit`` (the caller's audit append) runs inside
        the write's transaction, so a failed append keeps nothing."""
        if answer not in ANSWERS:
            raise NotMatchedError("nm.err.answer")
        note = " ".join((note or "").split())[:NOTE_MAX]
        with self.db.transaction() as tx:
            n = tx.execute(
                "UPDATE tuned_patients SET answer = ?, note = ?, answered_by = ?, answered_at = ? "
                "WHERE ruleset = ? AND week = ? AND pid = ? AND answer IS NULL",
                (answer, note or None, by, _iso(at), ruleset, week, pid),
            )
            if n != 1:
                known = tx.fetchval(
                    "SELECT COUNT(*) FROM tuned_patients WHERE ruleset = ? AND week = ? AND pid = ?",
                    (ruleset, week, pid),
                )
                raise NotMatchedError("nm.err.answered" if int(known or 0) else "nm.err.not_sampled")
            if before_commit is not None:
                before_commit()
        got = next(t for t in self.sample(ruleset, week) if t.pid == pid)
        return got

    # ------------------------------------------------------------------ the site's check
    def check(self, ruleset: str) -> Check | None:
        r = self.db.fetchone(
            "SELECT ruleset, passed, record, note, by, at FROM not_matched_check WHERE ruleset = ? "
            "ORDER BY id DESC LIMIT 1",
            (ruleset,),
        )
        return Check(str(r[0]), bool(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5])) if r else None

    def record_check(self, ruleset: str, *, passed: bool, record: str, note: str, by: str, at: str,
                     before_commit: Callable[[], None] | None = None) -> Check:  # fmt: skip
        """Record the site's check. "Passed" needs the id of the check's record (the dry-run record); taking it back
        ("not passed") needs a note. ``before_commit`` as in :meth:`answer`."""
        record = " ".join((record or "").split())[:RECORD_MAX]
        note = " ".join((note or "").split())[:NOTE_MAX]
        if not _RS.match(ruleset):
            raise NotMatchedError("nm.err.study")
        if passed and not record:
            raise NotMatchedError("nm.err.record")
        if not passed and not note:
            raise NotMatchedError("nm.err.note")
        with self.db.transaction() as tx:
            tx.execute("INSERT INTO not_matched_check (ruleset, passed, record, note, by, at) VALUES (?,?,?,?,?,?)",
                       (ruleset, passed, record, note, by, _iso(at)))  # fmt: skip
            if before_commit is not None:
                before_commit()
        got = self.check(ruleset)
        assert got is not None
        return got

    def shown(self, ruleset: str, gated: bool) -> bool:
        """Is the study's not-matched list (and its sample) open? Always without the gate; with it, only while the
        latest check passed."""
        if not gated:
            return True
        c = self.check(ruleset)
        return c is not None and c.passed


def sample_week(store: NotMatchedStore, ruleset: str, week: str, doc: Mapping[str, Any], *, job_id: str,
                snapshot: str, gone: Iterable[str], by: str, at: str) -> tuple[list[Tuned], bool]:  # fmt: skip
    """Draw and store the week's sample of one study from a screening run's stored not-matched list ``doc``
    (``excluded_*.json``, made from the run's own snapshot), leaving out the pseudonyms ``gone`` (opted out)."""
    seed = f"{ruleset}|{week}|{job_id}"
    rows = draw(doc.get("rows") or [], seed, gone)
    return store.record_sample(ruleset, week, rows, job_id=job_id, snapshot=snapshot,
                               version=str(doc.get("version") or ""), by=by, at=at)  # fmt: skip


__all__ = [
    "ANSWERS",
    "GATE_ENVS",
    "SAMPLE_SIZE",
    "Check",
    "NotMatchedError",
    "NotMatchedStore",
    "Tuned",
    "criteria_of",
    "draw",
    "gate_on",
    "iso_week",
    "sample_week",
]
