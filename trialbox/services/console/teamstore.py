"""The study team and the referral path (owner decisions 2026-11-09, D-147), schema ``team`` of the trial database.

* **Delegation log** per study (ICH E6 style): who is on the team, their role (PI, sub-PI, CRC, other), the tasks the
  PI ticked (screen and see candidates, mark Approach, request referrals, enter data), start and end dates, the GCP
  training date and certificate reference, and who signed. It is the box's *copy* of the trial office's signed log:
  the copy grants the rights in TrialBox; ``delegation_checks`` records the monthly comparison with the signed log.
* **Staff directory** and **department contacts**, kept by the steward (the referral's "who to ask").
* **Referrals**: one row per request to a treating physician, its route (suggested from the data, picked from the
  directory, typed, arranged outside TrialBox, or the department contact), the answer the CRC records (agree to
  introduce, decline with a reason, discuss) and the events behind it.
* **IRB approval and the current consent-form version** per study, and every Approach marked despite a warning.
* **Approved consent-form (ICF) versions** per study as history rows (D-399): version, its date, the IRB's approval,
  the first day it is used, and whether subjects on study consent again on it.
* **Candidate views and chart-number reveals** (study, patient, purpose, who, when), which also carry the rate limit.

Stored in the trial database (PostgreSQL ``trialbox_wf``, schema ``team``; D-126). Pseudonyms only: no chart number
or patient name is kept here. Staff names are staff names.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from tb_common.authz import STUDY_TASKS

from console.storedb import open_db

TASKS = STUDY_TASKS  # the role table's study tasks (tb_common.authz, D-147)
LOG_ROLES = ("pi", "sub_pi", "crc", "other")
ROUTES = ("suggested", "directory", "typed", "outside", "department")
ANSWERS = ("agree", "decline", "discuss")
STATES = ("asked", "agreed", "declined", "discuss")
CHANNELS = ("phone", "in_person", "emr", "mail", "other")
DECLINE_REASONS = ("not_suitable", "unwell", "other_trial", "patient_wish", "other")
CHECK_RESULTS = ("match", "differs")
VIEW_PURPOSES = ("eligibility", "referral", "contact", "other")
ANSWER_STATE = {"agree": "agreed", "decline": "declined", "discuss": "discuss"}

SCHEMA_V1 = """
CREATE TABLE delegation (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  username TEXT,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  tasks TEXT NOT NULL DEFAULT '',
  start_day TEXT NOT NULL,
  end_day TEXT,
  training_day TEXT,
  training_ref TEXT,
  signed_by TEXT NOT NULL,
  signed_at TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  updated_at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX delegation_rs ON delegation (ruleset);
CREATE TABLE delegation_history (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  entry_id BIGINT NOT NULL,
  action TEXT NOT NULL,
  body TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX delegation_history_rs ON delegation_history (ruleset, at);
CREATE TABLE delegation_checks (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  result TEXT NOT NULL,
  note TEXT,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX delegation_checks_rs ON delegation_checks (ruleset, at);
CREATE TABLE staff (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name TEXT NOT NULL,
  department TEXT,
  practitioner_id TEXT,
  role TEXT,
  contact TEXT,
  username TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  by TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE dept_contacts (
  department TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  contact TEXT,
  by TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE referrals (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  state TEXT NOT NULL,
  route TEXT NOT NULL,
  physician TEXT,
  physician_id TEXT,
  department TEXT,
  suggested TEXT,
  suggested_source TEXT,
  note TEXT,
  requested_by TEXT NOT NULL,
  requested_at TEXT COLLATE "C" NOT NULL,
  answer TEXT,
  reason TEXT,
  channel TEXT,
  answered_by TEXT,
  answered_at TEXT
);
CREATE INDEX referrals_rs ON referrals (ruleset, pid, requested_at);
CREATE TABLE referral_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  referral_id BIGINT NOT NULL,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  action TEXT NOT NULL,
  body TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX referral_events_rs ON referral_events (ruleset, pid, at);
CREATE TABLE irb (
  ruleset TEXT PRIMARY KEY,
  approval_no TEXT,
  approved_on TEXT,
  expires_on TEXT,
  icf_version TEXT,
  icf_date TEXT,
  by TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE approach_overrides (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  warnings TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX approach_overrides_rs ON approach_overrides (ruleset, pid);
CREATE TABLE candidate_views (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  purpose TEXT NOT NULL,
  kind TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX candidate_views_by ON candidate_views (by, kind, at)
"""
# D-399 (T-302a, FIT-009, LIFE-018): the study's approved consent-form (ICF) versions as history rows. Every add, change
# and withdrawal is a new row; the list is the newest row of each version that is not withdrawn. ``irb.icf_version``
# stays as it was saved and is read from this list once the list has a row.
SCHEMA_V2 = """
CREATE TABLE icf_versions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  version TEXT NOT NULL,
  version_date TEXT,
  irb_approved_on TEXT,
  effective_from TEXT NOT NULL DEFAULT '',
  reconsent INTEGER NOT NULL DEFAULT 1,
  action TEXT NOT NULL,
  note TEXT,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX icf_versions_rs ON icf_versions (ruleset, at)
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2)
ICF_ACTIONS = ("add", "withdraw")
_ICF_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()-]{0,39}$")


class TeamError(ValueError):
    pass


def _day(value: str | None, what: str) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError as exc:
        raise TeamError("dates are YYYY-MM-DD") from exc


def _tasks(tasks: Any) -> str:
    got = [t for t in TASKS if t in set(tasks or ())]
    return ",".join(got)


@dataclass(frozen=True)
class Entry:
    id: int
    ruleset: str
    username: str | None
    name: str
    role: str
    tasks: tuple[str, ...]
    start: str
    end: str | None
    training_day: str | None
    training_ref: str | None
    signed_by: str
    signed_at: str
    updated_by: str
    updated_at: str

    def active_on(self, day: date) -> bool:
        d = day.isoformat()
        return self.start <= d and (self.end is None or d <= self.end)


@dataclass(frozen=True)
class Staff:
    id: int
    name: str
    department: str
    practitioner_id: str
    role: str
    contact: str
    username: str
    active: bool


@dataclass(frozen=True)
class Contact:
    department: str
    name: str
    contact: str


@dataclass(frozen=True)
class Referral:
    id: int
    ruleset: str
    pid: str
    state: str
    route: str
    physician: str
    physician_id: str
    department: str
    suggested: str
    suggested_source: str
    note: str
    requested_by: str
    requested_at: str
    answer: str
    reason: str
    channel: str
    answered_by: str
    answered_at: str

    @property
    def open(self) -> bool:
        return self.state in ("asked", "discuss")


@dataclass
class Irb:
    approval_no: str = ""
    approved_on: str = ""
    expires_on: str = ""
    icf_version: str = ""
    icf_date: str = ""
    by: str = ""
    at: str = ""

    def warnings(self, today: date) -> list[str]:
        """Why an Approach needs a second look (owner decision: a warning, not a gate)."""
        out = []
        if not self.approved_on:
            out.append("irb_missing")
        elif self.expires_on and self.expires_on < today.isoformat():
            out.append("irb_expired")
        if not self.icf_version:  # an expired approval also expires the consent form approved under it
            out.append("icf_missing")
        return out


@dataclass(frozen=True)
class IcfVersion:
    """One approved consent-form version of a study (D-399): its version, the date printed on it, the IRB's approval
    of it, the first day it is used ('' = from the start), and whether subjects on study consent again on it."""

    version: str
    version_date: str = ""
    irb_approved_on: str = ""
    effective_from: str = ""
    reconsent: bool = True
    note: str = ""
    action: str = "add"
    by: str = ""
    at: str = ""
    seq: int = 0

    def as_row(self) -> dict[str, Any]:
        """The plain row ``datacore.lifecycle``'s ICF checks read."""
        return {"version": self.version, "version_date": self.version_date, "irb_approved_on": self.irb_approved_on,
                "effective_from": self.effective_from, "reconsent": self.reconsent, "note": self.note,
                "by": self.by, "at": self.at, "seq": self.seq}  # fmt: skip


@dataclass(frozen=True)
class Event:
    action: str
    body: dict[str, Any] = field(default_factory=dict)
    by: str = ""
    at: str = ""


_ENTRY = (
    "id, ruleset, username, name, role, tasks, start_day, end_day, training_day, training_ref, signed_by, signed_at, "
    "updated_by, updated_at"
)
_REF = (
    "id, ruleset, pid, state, route, physician, physician_id, department, suggested, suggested_source, note, "
    "requested_by, requested_at, answer, reason, channel, answered_by, answered_at"
)


def _entry(r: tuple[Any, ...]) -> Entry:
    tasks = tuple(t for t in str(r[5] or "").split(",") if t)
    return Entry(int(r[0]), str(r[1]), r[2], str(r[3]), str(r[4]), tasks, str(r[6]), r[7], r[8], r[9], str(r[10]),
                 str(r[11]), str(r[12]), str(r[13]))  # fmt: skip


def _ref(r: tuple[Any, ...]) -> Referral:
    v = [("" if x is None else x) for x in r]
    return Referral(int(v[0]), *(str(x) for x in v[1:]))


class TeamStore:
    """Schema ``team`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = open_db(url, "team", MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ delegation log
    def entries(self, ruleset: str) -> list[Entry]:
        rows = self.db.fetchall(f"SELECT {_ENTRY} FROM delegation WHERE ruleset = ? ORDER BY id", (ruleset,))
        return [_entry(r) for r in rows]

    def entry(self, ruleset: str, eid: int) -> Entry | None:
        row = self.db.fetchone(f"SELECT {_ENTRY} FROM delegation WHERE ruleset = ? AND id = ?", (ruleset, eid))
        return _entry(row) if row else None

    def pi_of(self, ruleset: str, day: date) -> Entry | None:
        """The study's PI on ``day`` per the log (the last PI entry active that day), or None."""
        pis = [e for e in self.entries(ruleset) if e.role == "pi" and e.active_on(day)]
        return pis[-1] if pis else None

    def add_entry(
        self,
        ruleset: str,
        *,
        username: str | None,
        name: str,
        role: str,
        tasks: Any,
        start: str,
        end: str | None,
        training_day: str | None,
        training_ref: str | None,
        by: str,
        at: str,
    ) -> int:
        if role not in LOG_ROLES:
            raise TeamError("choose the role: PI, sub-investigator, CRC or other")
        name = name.strip()[:120]
        if not name:
            raise TeamError("give the person's name")
        s = _day(start, "the start date")
        if s is None:
            raise TeamError("give the start date")
        e = _day(end, "the end date")
        if e is not None and e < s:
            raise TeamError("the end date is before the start date")
        t = _tasks(TASKS if role == "pi" else tasks)
        td = _day(training_day, "the training date")
        body = {"username": username, "name": name, "role": role, "tasks": t, "start": s, "end": e,
                "training_day": td, "training_ref": (training_ref or "")[:80]}  # fmt: skip
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "INSERT INTO delegation (ruleset, username, name, role, tasks, start_day, end_day, training_day, "
                "training_ref, signed_by, signed_at, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "RETURNING id",
                (ruleset, username or None, name, role, t, s, e, body["training_day"], body["training_ref"] or None,
                 by, at, by, at),
            )  # fmt: skip
            assert row is not None
            eid = int(row[0])
            tx.execute(
                "INSERT INTO delegation_history (ruleset, entry_id, action, body, by, at) VALUES (?,?,?,?,?,?)",
                (ruleset, eid, "add", json.dumps(body, ensure_ascii=False, sort_keys=True), by, at),
            )
        return eid

    def update_entry(
        self,
        ruleset: str,
        eid: int,
        *,
        tasks: Any,
        end: str | None,
        training_day: str | None,
        training_ref: str | None,
        by: str,
        at: str,
    ) -> Entry:
        cur = self.entry(ruleset, eid)
        if cur is None:
            raise TeamError("no such entry in this study's log")
        e = _day(end, "the end date")
        if e is not None and e < cur.start:
            raise TeamError("the end date is before the start date")
        t = _tasks(TASKS if cur.role == "pi" else tasks)
        td = _day(training_day, "the training date")
        body = {"tasks": t, "end": e, "training_day": td, "training_ref": (training_ref or "")[:80],
                "before": {"tasks": ",".join(cur.tasks), "end": cur.end, "training_day": cur.training_day}}  # fmt: skip
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE delegation SET tasks = ?, end_day = ?, training_day = ?, training_ref = ?, updated_by = ?, "
                "updated_at = ? WHERE ruleset = ? AND id = ?",
                (t, e, td, body["training_ref"] or None, by, at, ruleset, eid),
            )
            tx.execute(
                "INSERT INTO delegation_history (ruleset, entry_id, action, body, by, at) VALUES (?,?,?,?,?,?)",
                (ruleset, eid, "update", json.dumps(body, ensure_ascii=False, sort_keys=True), by, at),
            )
        out = self.entry(ruleset, eid)
        assert out is not None
        return out

    def history(self, ruleset: str) -> list[tuple[int, Event]]:
        rows = self.db.fetchall(
            "SELECT entry_id, action, body, by, at FROM delegation_history WHERE ruleset = ? ORDER BY at, id",
            (ruleset,),
        )
        return [(int(r[0]), Event(str(r[1]), json.loads(r[2]), str(r[3]), str(r[4]))) for r in rows]

    def add_check(self, ruleset: str, result: str, note: str, by: str, at: str) -> None:
        if result not in CHECK_RESULTS:
            raise TeamError("say whether the copy matches the signed log")
        self.db.execute(
            "INSERT INTO delegation_checks (ruleset, result, note, by, at) VALUES (?,?,?,?,?)",
            (ruleset, result, note.strip()[:300] or None, by, at),
        )

    def checks(self, ruleset: str) -> list[Event]:
        rows = self.db.fetchall(
            "SELECT result, note, by, at FROM delegation_checks WHERE ruleset = ? ORDER BY at DESC, id DESC",
            (ruleset,),
        )
        return [Event(str(r[0]), {"note": r[1] or ""}, str(r[2]), str(r[3])) for r in rows]

    # ------------------------------------------------------------------ staff directory, department contacts
    def staff(self, active_only: bool = True) -> list[Staff]:
        q = "SELECT id, name, department, practitioner_id, role, contact, username, active FROM staff"
        rows = self.db.fetchall(q + (" WHERE active = 1" if active_only else "") + " ORDER BY department, name, id")
        out = []
        for r in rows:
            dept, prac, role, contact, user = (str(x or "") for x in r[2:7])
            out.append(Staff(int(r[0]), str(r[1]), dept, prac, role, contact, user, bool(r[7])))
        return out

    def staff_member(self, sid: int) -> Staff | None:
        return next((s for s in self.staff(active_only=False) if s.id == sid), None)

    def add_staff(self, name: str, department: str, practitioner_id: str, role: str, contact: str, username: str,
                  by: str, at: str) -> int:  # fmt: skip
        name = name.strip()[:120]
        if not name:
            raise TeamError("give the person's name")
        row = self.db.fetchone(
            "INSERT INTO staff (name, department, practitioner_id, role, contact, username, by, at) "
            "VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (name, department.strip()[:40] or None, practitioner_id.strip()[:40] or None, role.strip()[:40] or None,
             contact.strip()[:120] or None, username.strip()[:32] or None, by, at),
        )  # fmt: skip
        assert row is not None
        return int(row[0])

    def set_staff_active(self, sid: int, active: bool, by: str, at: str) -> None:
        n = self.db.execute("UPDATE staff SET active = ?, by = ?, at = ? WHERE id = ?", (int(active), by, at, sid))
        if n != 1:
            raise TeamError("no such person in the directory")

    def contacts(self) -> list[Contact]:
        rows = self.db.fetchall("SELECT department, name, contact FROM dept_contacts ORDER BY department")
        return [Contact(str(r[0]), str(r[1]), str(r[2] or "")) for r in rows]

    def save_contact(self, department: str, name: str, contact: str, by: str, at: str) -> None:
        dept, name = department.strip()[:40], name.strip()[:120]
        if not dept or not name:
            raise TeamError("give the department and who answers for it")
        self.db.execute(
            "INSERT INTO dept_contacts (department, name, contact, by, at) VALUES (?,?,?,?,?) ON CONFLICT "
            "(department) DO UPDATE SET name = excluded.name, contact = excluded.contact, by = excluded.by, "
            "at = excluded.at",
            (dept, name, contact.strip()[:120] or None, by, at),
        )

    # ------------------------------------------------------------------ referrals
    def referrals(self, ruleset: str, pid: str | None = None) -> list[Referral]:
        q = f"SELECT {_REF} FROM referrals WHERE ruleset = ?"
        args: tuple[Any, ...] = (ruleset,)
        if pid is not None:
            q, args = q + " AND pid = ?", (ruleset, pid)
        return [_ref(r) for r in self.db.fetchall(q + " ORDER BY requested_at, id", args)]

    def referral(self, ruleset: str, rid: int) -> Referral | None:
        row = self.db.fetchone(f"SELECT {_REF} FROM referrals WHERE ruleset = ? AND id = ?", (ruleset, rid))
        return _ref(row) if row else None

    def latest_referrals(self, ruleset: str) -> dict[str, Referral]:
        out: dict[str, Referral] = {}
        for r in self.referrals(ruleset):
            out[r.pid] = r
        return out

    def add_referral(
        self,
        ruleset: str,
        pid: str,
        *,
        route: str,
        physician: str,
        physician_id: str,
        department: str,
        suggested: str,
        suggested_source: str,
        note: str,
        by: str,
        at: str,
    ) -> int:
        if route not in ROUTES:
            raise TeamError("choose how the treating doctor is asked")
        vals = (physician.strip()[:120], physician_id.strip()[:40], department.strip()[:40], suggested.strip()[:120],
                suggested_source.strip()[:120], note.strip()[:300])  # fmt: skip
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "INSERT INTO referrals (ruleset, pid, state, route, physician, physician_id, department, suggested, "
                "suggested_source, note, requested_by, requested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (ruleset, pid, "asked", route, *(v or None for v in vals), by, at),
            )
            assert row is not None
            rid = int(row[0])
            body = {"route": route, "physician": vals[0], "physician_id": vals[1], "department": vals[2],
                    "suggested": vals[3]}  # fmt: skip
            tx.execute(
                "INSERT INTO referral_events (referral_id, ruleset, pid, action, body, by, at) VALUES (?,?,?,?,?,?,?)",
                (rid, ruleset, pid, "requested", json.dumps(body, ensure_ascii=False, sort_keys=True), by, at),
            )
        return rid

    def answer(self, ruleset: str, rid: int, answer: str, reason: str, channel: str, note: str, by: str,
               at: str) -> Referral:  # fmt: skip
        if answer not in ANSWERS:
            raise TeamError("choose the doctor's answer: agree, decline or discuss")
        cur = self.referral(ruleset, rid)
        if cur is None:
            raise TeamError("no such referral in this study")
        if not cur.open:
            raise TeamError("this referral has its answer already; ask again with a new request")
        why = (reason if reason in DECLINE_REASONS else "other") if answer == "decline" else ""
        ch = channel if channel in CHANNELS else "other"
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE referrals SET state = ?, answer = ?, reason = ?, channel = ?, answered_by = ?, answered_at = ? "
                "WHERE ruleset = ? AND id = ?",
                (ANSWER_STATE[answer], answer, why or None, ch, by, at, ruleset, rid),
            )
            body = {"answer": answer, "reason": why, "channel": ch, "note": note.strip()[:300]}
            tx.execute(
                "INSERT INTO referral_events (referral_id, ruleset, pid, action, body, by, at) VALUES (?,?,?,?,?,?,?)",
                (rid, ruleset, cur.pid, "answered", json.dumps(body, ensure_ascii=False, sort_keys=True), by, at),
            )
        out = self.referral(ruleset, rid)
        assert out is not None
        return out

    def referral_events(self, ruleset: str, pid: str) -> list[tuple[int, Event]]:
        rows = self.db.fetchall(
            "SELECT referral_id, action, body, by, at FROM referral_events WHERE ruleset = ? AND pid = ? "
            "ORDER BY at, id",
            (ruleset, pid),
        )
        return [(int(r[0]), Event(str(r[1]), json.loads(r[2]), str(r[3]), str(r[4]))) for r in rows]

    # ------------------------------------------------------------------ IRB approval and consent-form version
    def irb(self, ruleset: str) -> Irb:
        """The study's IRB record; its consent-form version is the newest on the ICF list once the list has one."""
        row = self.db.fetchone(
            "SELECT approval_no, approved_on, expires_on, icf_version, icf_date, by, at FROM irb WHERE ruleset = ?",
            (ruleset,),
        )
        rec = Irb(*(str(x or "") for x in row)) if row else Irb()
        icf = self.icf_list(ruleset)
        if icf:
            newest = max(icf, key=lambda v: (v.effective_from, v.seq))
            rec.icf_version, rec.icf_date = newest.version, newest.version_date or newest.effective_from
        return rec

    def save_irb(self, ruleset: str, rec: Irb, by: str, at: str) -> Irb:
        approved = _day(rec.approved_on, "the approval date") or ""
        expires = _day(rec.expires_on, "the expiry date") or ""
        icf_date = _day(rec.icf_date, "the consent form's date") or ""
        if approved and expires and expires < approved:
            raise TeamError("the approval expires before it was given")
        vals = (rec.approval_no.strip()[:60], approved, expires, rec.icf_version.strip()[:40], icf_date)
        self.db.execute(
            "INSERT INTO irb (ruleset, approval_no, approved_on, expires_on, icf_version, icf_date, by, at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (ruleset) DO UPDATE SET approval_no = excluded.approval_no, "
            "approved_on = excluded.approved_on, expires_on = excluded.expires_on, icf_version = excluded.icf_version, "
            "icf_date = excluded.icf_date, by = excluded.by, at = excluded.at",
            (ruleset, *(v or None for v in vals), by, at),
        )
        listed = {v.version.casefold() for v in self.icf_list(ruleset)}
        if vals[3] and _ICF_VERSION.match(vals[3]) and vals[3].casefold() not in listed:
            # D-399: a version typed on the IRB record joins the ICF list, approved with the IRB record's date
            self.add_icf(ruleset, IcfVersion(vals[3], icf_date, approved, ""), by, at)
        return self.irb(ruleset)

    # ------------------------------------------------------------------ approved consent-form versions (D-399)
    _ICF = "id, version, version_date, irb_approved_on, effective_from, reconsent, action, note, by, at"

    @staticmethod
    def _icf(r: tuple[Any, ...]) -> IcfVersion:
        return IcfVersion(str(r[1]), str(r[2] or ""), str(r[3] or ""), str(r[4] or ""), bool(r[5]), str(r[7] or ""),
                          str(r[6]), str(r[8]), str(r[9]), int(r[0]))  # fmt: skip

    def icf_history(self, ruleset: str) -> list[IcfVersion]:
        """Every row of the study's ICF list, oldest first (adds, changes and withdrawals)."""
        rows = self.db.fetchall(f"SELECT {self._ICF} FROM icf_versions WHERE ruleset = ? ORDER BY at, id", (ruleset,))
        return [self._icf(r) for r in rows]

    def icf_list(self, ruleset: str) -> list[IcfVersion]:
        """The approved versions now: the newest row of each version, without the withdrawn ones, in the order they
        come into force."""
        last: dict[str, IcfVersion] = {}
        for v in self.icf_history(ruleset):
            last[v.version.casefold()] = v
        live = [v for v in last.values() if v.action != "withdraw"]
        return sorted(live, key=lambda v: (v.effective_from, v.seq))

    def add_icf(self, ruleset: str, rec: IcfVersion, by: str, at: str) -> IcfVersion:
        """Add a version, or change one (the same version again: a new row). The effective date is the IRB approval
        date when left empty, and never before it."""
        version = rec.version.strip()
        if not _ICF_VERSION.match(version):
            raise TeamError("the version is letters, digits, spaces and . _ / ( ) -, at most 40")
        printed = _day(rec.version_date, "the form's date") or ""
        approved = _day(rec.irb_approved_on, "the IRB approval date") or ""
        effective = _day(rec.effective_from, "the first day it is used") or approved
        if approved and effective < approved:
            raise TeamError("a version is used only from its IRB approval date")
        self.db.execute(
            "INSERT INTO icf_versions (ruleset, version, version_date, irb_approved_on, effective_from, reconsent, "
            "action, note, by, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ruleset, version, printed or None, approved or None, effective, 1 if rec.reconsent else 0, "add",
             rec.note.strip()[:200] or None, by, at),
        )  # fmt: skip
        return next(v for v in self.icf_list(ruleset) if v.version.casefold() == version.casefold())

    def withdraw_icf(self, ruleset: str, version: str, note: str, by: str, at: str) -> None:
        """Take a version off the list (entered by mistake); the history keeps it. A note says why."""
        cur = next((v for v in self.icf_list(ruleset) if v.version.casefold() == version.strip().casefold()), None)
        if cur is None:
            raise TeamError("that version is not on the list")
        if not note.strip():
            raise TeamError("say why the version is taken off the list")
        self.db.execute(
            "INSERT INTO icf_versions (ruleset, version, version_date, irb_approved_on, effective_from, reconsent, "
            "action, note, by, at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ruleset, cur.version, cur.version_date or None, cur.irb_approved_on or None, cur.effective_from,
             1 if cur.reconsent else 0, "withdraw", note.strip()[:200], by, at),
        )  # fmt: skip

    def add_override(self, ruleset: str, pid: str, warnings: list[str], by: str, at: str) -> None:
        self.db.execute(
            "INSERT INTO approach_overrides (ruleset, pid, warnings, by, at) VALUES (?,?,?,?,?)",
            (ruleset, pid, ",".join(warnings), by, at),
        )

    def overrides(self, ruleset: str) -> list[tuple[str, list[str], str, str]]:
        """(pid, warnings, by, at), oldest first."""
        rows = self.db.fetchall(
            "SELECT pid, warnings, by, at FROM approach_overrides WHERE ruleset = ? ORDER BY at, id", (ruleset,)
        )
        return [(str(r[0]), [w for w in str(r[1]).split(",") if w], str(r[2]), str(r[3])) for r in rows]

    # ------------------------------------------------------------------ candidate views (logged, rate-limited)
    def record_view(self, ruleset: str, pid: str, purpose: str, kind: str, by: str, at: str) -> None:
        self.db.execute(
            "INSERT INTO candidate_views (ruleset, pid, purpose, kind, by, at) VALUES (?,?,?,?,?,?)",
            (ruleset, pid, purpose, kind, by, at),
        )

    def take(self, ruleset: str, pid: str, purpose: str, kind: str, by: str, at: str, since: str, limit: int) -> bool:
        """D-273: one capped use. In one transaction, serialised per person and kind, count the uses since ``since``
        and record this one only when it is within ``limit``; False when the cap is reached. Parallel requests can no
        longer all pass a count taken before any of them is recorded."""
        with self.db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"candidate_views:{by}:{kind}",))
            n = tx.fetchval(
                "SELECT count(*) FROM candidate_views WHERE by = ? AND kind = ? AND at >= ?", (by, kind, since)
            )
            if int(n or 0) >= limit:
                return False
            tx.execute(
                "INSERT INTO candidate_views (ruleset, pid, purpose, kind, by, at) VALUES (?,?,?,?,?,?)",
                (ruleset, pid, purpose, kind, by, at),
            )
        return True

    def count_views(self, by: str, kind: str, since: str) -> int:
        return int(
            self.db.fetchval(
                "SELECT count(*) FROM candidate_views WHERE by = ? AND kind = ? AND at >= ?", (by, kind, since)
            )
        )

    def views(self, ruleset: str, pid: str) -> list[tuple[str, str, str, str]]:
        """(kind, purpose, by, at) of one candidate, newest first."""
        rows = self.db.fetchall(
            "SELECT kind, purpose, by, at FROM candidate_views WHERE ruleset = ? AND pid = ? ORDER BY at DESC, id DESC",
            (ruleset, pid),
        )
        return [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]
