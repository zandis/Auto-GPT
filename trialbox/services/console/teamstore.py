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
* **The Japan profile's committee record** (10C-4, D-1227): study kind, committee, 設置者, contract, versions, 一括審査,
  and each site's head-of-institution permission, as history rows.
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
from datetime import date, timedelta
from typing import Any

from tb_common import committees as cm
from tb_common.authz import STUDY_TASKS
from tb_common.committees import Committee, Permission, committee_row, permission_row

from console.storedb import open_db

TASKS = STUDY_TASKS  # the role table's study tasks (tb_common.authz, D-147)
LOG_ROLES = ("pi", "sub_pi", "crc", "other", "monitor")  # D-380: "monitor" is a CRO account's grant for a visit
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
# D-436 (T-303, FIT-002): the monitoring-visit record a CRA writes under a monitor grant: the visit date, the CRA (the
# signed-in account), the monitoring-visit id the grant names, the subjects verified and the findings. Append-only by
# code: a correction is a new row.
SCHEMA_V3 = """
CREATE TABLE monitor_visits (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  visit_ref TEXT NOT NULL,
  visit_day TEXT NOT NULL,
  cra TEXT NOT NULL,
  subjects TEXT NOT NULL,
  findings TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX monitor_visits_rs ON monitor_visits (ruleset, at)
"""
# 10C-4 (D-1227, JP-3): a Japanese study's committee record and each site's head-of-institution permission, as
# history rows (a correction is a new row; the newest row is the record). Read and written only under the Japan
# profile (``tb_common.committees``); no patient data. ``committee_open``: each opening of a study under the rule
# (the kind and version that passed) and the marks of the studies open when the rule first applied at a site.
SCHEMA_V4 = """
CREATE TABLE committee (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  kind TEXT NOT NULL,
  external INTEGER NOT NULL DEFAULT 0,
  establisher TEXT NOT NULL DEFAULT '',
  contract_on TEXT NOT NULL DEFAULT '',
  current_version TEXT NOT NULL DEFAULT '',
  approved_version TEXT NOT NULL DEFAULT '',
  approved_on TEXT NOT NULL DEFAULT '',
  central INTEGER NOT NULL DEFAULT 0,
  documents TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL,
  due_on TEXT NOT NULL DEFAULT ''
);
CREATE INDEX committee_rs ON committee (ruleset, at);
CREATE TABLE site_permission (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  site TEXT NOT NULL,
  version TEXT NOT NULL DEFAULT '',
  permitted_on TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX site_permission_rs ON site_permission (ruleset, site, at);
CREATE TABLE committee_open (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  site TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '',
  why TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX committee_open_rs ON committee_open (ruleset, site, at)
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4)
FINDINGS_MAX = 2000  # characters of a monitoring visit's findings
ENDING_DAYS = 14  # 9f-4 (a): a delegation entry is warned about from two weeks before its last day
ICF_ACTIONS = ("add", "withdraw")
_ICF_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()-]{0,39}$")

# 9f-3, 9f-5 (D-1383): a block of its own. ``pi_cover``: a dated cover of a study's PI by a sub-investigator of the
# same log (the cover's start and end are written to the audit trail once each, ``start_logged_at``,
# ``end_logged_at``; an early end is ``ended_on``, the first site day without the cover). ``task_owner``: the owner of
# one task of the opening page as history rows (the newest row of a task is its owner; '' = no owner).
SCHEMA_V5 = """
CREATE TABLE pi_cover (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pi TEXT NOT NULL,
  pi_name TEXT NOT NULL,
  username TEXT NOT NULL,
  name TEXT NOT NULL,
  start_day TEXT NOT NULL,
  end_day TEXT NOT NULL,
  entered_on TEXT NOT NULL,
  ended_on TEXT,
  ended_by TEXT,
  lapse_reason TEXT,
  irb_told_on TEXT,
  irb_told_by TEXT,
  start_logged_at TEXT,
  end_logged_at TEXT,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL,
  CONSTRAINT pi_cover_days CHECK (start_day <= end_day AND entered_on <= start_day AND pi <> username),
  CONSTRAINT pi_cover_lapse CHECK (lapse_reason IS NULL OR lapse_reason IN ('pi_changed', 'entry_ended'))
);
CREATE INDEX pi_cover_rs ON pi_cover (ruleset, start_day);
CREATE TABLE task_owner (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  kind TEXT NOT NULL,
  ref TEXT NOT NULL DEFAULT '',
  owner TEXT NOT NULL DEFAULT '',
  owner_name TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX task_owner_rs ON task_owner (ruleset, kind, ref, at)
"""
MIGRATIONS = (*MIGRATIONS, SCHEMA_V5)
COVER_MAX_DAYS = 90  # 9f-3: the longest cover, start and end day included; a cover with no end is refused
COVER_ROLE = "sub_pi"  # 9f-3: only a sub-investigator on the same study's log may cover its PI
OWNER_ROLES = ("pi", "sub_pi", "crc", "other")  # 9f-5: who on the log may own a task (never a monitor grant)
TASK_KINDS = ("call", "info", "prepare", "refer", "delegation", "cover_irb")  # 9f-5: the opening page's tasks
_TASK_REF = re.compile(r"^[A-Za-z0-9_-]{0,64}$")


class TeamError(ValueError):
    """A refusal of the team store. ``fields`` (9f-3, 9f-5, 9k-6a, D-1376): when the refusal is a value the person
    typed, the (input name, message key) of each field to blame, in the form's order, so the page can show it at the
    field; the text, the conditions and the order of the checks are the same with and without it."""

    def __init__(self, *args: object, fields: tuple[tuple[str, str], ...] = ()) -> None:
        super().__init__(*args)
        self.fields = fields


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

    def days_left(self, day: date) -> int | None:
        """9f-4 (a): the days from ``day`` to this entry's last day when it ends within ``ENDING_DAYS`` (the last day
        itself is 0), else None: no end, already over, not started, or further off. ``day`` is the site's day."""
        if self.end is None or not self.active_on(day):
            return None
        left = (date.fromisoformat(self.end) - day).days
        return left if left <= ENDING_DAYS else None


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
class MonitorVisit:
    """One monitoring-visit record (D-436): the visit date, the CRA's account, the monitoring-visit id of the grant,
    the subjects verified (screening numbers) and the findings."""

    id: int
    visit_ref: str
    visit_day: str
    cra: str
    subjects: tuple[str, ...]
    findings: str
    at: str

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "visit": self.visit_ref, "visit_day": self.visit_day, "cra": self.cra,
                "subjects": list(self.subjects), "findings": self.findings, "at": self.at}  # fmt: skip


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


# ---------------------------------------------------------------------------------------------- 9f-3: the PI's cover
@dataclass(frozen=True)
class Cover:
    """A dated cover of the study's PI (``pi``) by a sub-investigator of the same log (``username``), D-1383.

    In effect on a site day from ``start`` to ``end`` (both included) unless ended early: ``ended_on`` is the first
    day without it."""

    id: int
    ruleset: str
    pi: str
    pi_name: str
    username: str
    name: str
    start: str
    end: str
    ended_on: str | None = None
    ended_by: str | None = None
    irb_told_on: str | None = None
    irb_told_by: str | None = None
    start_logged: bool = False
    end_logged: bool = False
    by: str = ""
    at: str = ""
    entered_on: str = ""
    lapse_reason: str | None = None

    def in_effect_on(self, day: date) -> bool:
        d = day.isoformat()
        return self.start <= d <= self.end and (self.ended_on is None or d < self.ended_on)

    def last_day(self) -> str:
        """The cover's last day in effect: its end, or the day before an early end ('' when it never began)."""
        if self.ended_on is None:
            return self.end
        if self.ended_on <= self.start:
            return ""
        return min(self.end, (date.fromisoformat(self.ended_on) - timedelta(days=1)).isoformat())

    def over_on(self, day: date) -> bool:
        """The cover will never be in effect again from ``day`` on."""
        last = self.last_day()
        return not last or last < day.isoformat()

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "pi": self.pi, "pi_name": self.pi_name, "username": self.username, "name": self.name,
                "start": self.start, "end": self.end, "ended_on": self.ended_on, "irb_told_on": self.irb_told_on,
                "lapse_reason": self.lapse_reason, "by": self.by, "at": self.at}  # fmt: skip


# 9f-3 (D-1383): the rights a cover carries, an allow-list (default deny: a PI right not named here is refused under a
# cover, a PI right added later included, until it is listed here or in COVER_WITHHELD on purpose). The PI's clinical
# rights in the study (the owner's ruling, 2026-11-20): the patient pages and reads (the ``task.*`` rows, the prefill
# pages' read, the weekly sample of criteria-not-matched patients) and the runs the PI may start. SAE acknowledgement
# and sign-off are not PI rows (the ``sae.*`` rows are the role's): the covering person does them in their own name
# either way. A right held through a cover never opens an export (:data:`COVER_NO_EXPORT`, ``LogRights.own``).
COVER_RIGHTS: frozenset[str] = frozenset({
    "task.screen", "task.approach", "task.refer", "task.enter_data", "task.run",
    "command.FEAS", "command.SCREEN", "command.CASE", "edc.view", "notmatched.sample", "notmatched.send_back",
})  # fmt: skip
# ... and the study administration a cover never carries (the log stays the PI's, D-1383; a question is with the
# owner): the log's rows and its monthly check, a monitor grant, the study's state and its reopening, the IRB records
# and the IRB-text answer, prefill on and off, the break-glass review, the research layers, the criteria approval, a
# task's owner and the cover's IRB task (the owner's ruling, 2026-11-20: only as the person's own role allows).
COVER_WITHHELD: frozenset[str] = frozenset({
    "delegation.keep", "delegation.check", "monitor.grant", "study.state", "study.reopen", "study.irb_text",
    "irb.edit", "edc.switch_on", "edc.switch_off", "breakglass.study", "profile.research_layers", "criteria.approve",
    "team.task_owner",
})  # fmt: skip
# 9f-3 (D-1383, the owner's ruling 2026-11-20: a cover gives no export): the matrix rows that are an export in
# themselves (the ODM export of the EDC prefill, the copy-assist sheet and its file). Every other export (the study's
# data export in each format and its ``/api/v1`` twin, the screening log's workbook, the chart-number workbook) asks
# the clinical row (``task.screen``, ``task.enter_data``) through ``LogRights.own``, the standing without the cover.
COVER_NO_EXPORT: frozenset[str] = frozenset({"edc.export", "edc.copy"})
LAPSE_REASONS = ("pi_changed", "entry_ended")


def _pi_on(entries: list[Entry], day: date) -> Entry | None:
    return next((e for e in reversed(entries) if e.role == "pi" and e.active_on(day)), None)


def cover_state(entries: list[Entry], c: Cover, day: date) -> tuple[str, str | None, str | None]:
    """9f-3 (D-1383): what a cover is on site day ``day``: ``(state, lapse reason, last day in effect)``. ``state`` is
    ``waiting`` (before its first day, nothing broken yet), ``effective``, ``over`` (past its last day or ended early,
    never broken while it ran) or ``lapsed``: from the day it was entered the PI it covers stopped being the PI the log
    names (``pi_changed``), or from its first day the covering person's own sub-investigator entry was not active
    (``entry_ended``), on some day up to ``day``. A lapse once stored is final (``lapse_reason``): never revived."""
    if c.lapse_reason:
        return "lapsed", c.lapse_reason, c.last_day() or None
    last = c.last_day()
    upto = min(day.isoformat(), last) if last else ""
    d = date.fromisoformat(c.entered_on or c.start)
    first_broken: tuple[date, str] | None = None
    while upto and d.isoformat() <= upto:
        pi = _pi_on(entries, d)
        if pi is None or pi.username != c.pi:
            first_broken = (d, "pi_changed")
            break
        if d.isoformat() >= c.start and not any(e.username == c.username and e.role == COVER_ROLE and e.active_on(d)
                                                for e in entries):  # fmt: skip
            first_broken = (d, "entry_ended")
            break
        d += timedelta(days=1)
    if first_broken is not None:
        prev = (first_broken[0] - timedelta(days=1)).isoformat()
        return "lapsed", first_broken[1], prev if prev >= c.start else None
    if not last:  # ended before its first day: it never takes effect
        return "over", None, None
    if day.isoformat() < c.start:
        return "waiting", None, None
    if last and day.isoformat() <= last:
        return "effective", None, None
    return "over", None, last or None


@dataclass(frozen=True)
class LogRights:
    """What the study's delegation log, with its covers, gives one account on one site day (9f-3, D-1383): the PI
    the log names; whether the account acts as PI (its own PI entry, or a cover in effect); the tasks ticked for it as
    a sub-investigator; its own entries active that day; and the cover it acts under, if any."""

    pi: Entry | None
    is_pi: bool
    ticked: frozenset[str]
    mine: tuple[Entry, ...]
    cover: Cover | None = None
    pi_rights: frozenset[str] | None = None  # under a cover: COVER_RIGHTS (the PI's own entry: None, every PI row)

    def own(self) -> LogRights:
        """The same reading without the cover: what the account's own entries give (9f-3, D-1383). An export, the
        log's own rows and every right a cover withholds ask this, so a right held only through a cover never
        satisfies them (the owner's ruling, 2026-11-20: a cover gives clinical rights, no export and no
        administration)."""
        if self.cover is None:
            return self
        return LogRights(self.pi, False, self.ticked, self.mine, None, None)


def log_rights(entries: list[Entry], covers: list[Cover], username: str | None, day: date) -> LogRights:
    """The one reading of a study's delegation log (``console.team.standing`` and ``orchestrator.grants`` both ask
    it). A cover gives the PI's standing only when every condition holds that day, else nothing (default deny): the
    cover is in effect (inside its dates, not ended), it names this account, the PI it covers is still the PI the
    log names, and the account's own sub-investigator entry on this log is active, and have held on every day since
    (:func:`cover_state`: a lapsed cover is never revived). Under a cover the PI's rows are only those of
    :data:`COVER_RIGHTS` (``pi_rights``)."""
    pi = _pi_on(entries, day)
    mine = tuple(e for e in entries if username and e.username == username and e.active_on(day))
    ticked = frozenset(t for e in mine if e.role == "sub_pi" for t in e.tasks)
    own_pi = bool(username) and pi is not None and pi.username == username
    cover = None
    if not own_pi and pi is not None and pi.username and username and any(e.role == COVER_ROLE for e in mine):
        cover = next((c for c in reversed(covers) if c.username == username and c.pi == pi.username
                      and c.in_effect_on(day) and cover_state(entries, c, day)[0] == "effective"), None)  # fmt: skip
    return LogRights(pi, own_pi or cover is not None, ticked, mine, cover, COVER_RIGHTS if cover is not None else None)


@dataclass(frozen=True)
class TaskOwner:
    """9f-5: the owner of one task (``owner`` '' = none), who set it and when."""

    kind: str
    ref: str
    owner: str
    owner_name: str
    by: str
    at: str


_ENTRY = (
    "id, ruleset, username, name, role, tasks, start_day, end_day, training_day, training_ref, signed_by, signed_at, "
    "updated_by, updated_at"
)
_REF = (
    "id, ruleset, pid, state, route, physician, physician_id, department, suggested, suggested_source, note, "
    "requested_by, requested_at, answer, reason, channel, answered_by, answered_at"
)

# 9f-1: a constant statement (the columns spelled out, the value bound): no SQL is built from a string here.
_ENTRIES_FOR = (
    "SELECT id, ruleset, username, name, role, tasks, start_day, end_day, training_day, training_ref, signed_by, "
    "signed_at, updated_by, updated_at FROM delegation WHERE username = ? ORDER BY ruleset, id"
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

    def entries_for(self, username: str) -> list[Entry]:
        """9f-1: one account's own entries over all studies (a read of that person's rows only)."""
        rows = self.db.fetchall(_ENTRIES_FOR, (username,))
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
            raise TeamError("choose the role: PI, sub-investigator, CRC, other or monitor")
        name = name.strip()[:120]
        if not name:
            raise TeamError("give the person's name")
        s = _day(start, "the start date")
        if s is None:
            raise TeamError("give the start date")
        e = _day(end, "the end date")
        if e is not None and e < s:
            raise TeamError("the end date is before the start date")
        t = _tasks(TASKS if role == "pi" else () if role == "monitor" else tasks)  # a monitor holds no study task
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

    # ------------------------------------------------------------------ 10C-4: committee and permission (D-1227)
    def committee(self, ruleset: str) -> Committee:
        """The study's committee record (the newest row), or an empty one: no kind, the other-country default."""
        rows = self.committee_history(ruleset)  # a few rows per study: the newest is the record
        return rows[-1] if rows else Committee()

    def committee_history(self, ruleset: str) -> list[Committee]:
        rows = self.db.fetchall(
            "SELECT kind, external, establisher, contract_on, current_version, approved_version, approved_on, central, "
            "documents, by, at, due_on FROM committee WHERE ruleset = ? ORDER BY at, id",
            (ruleset,),
        )
        return [committee_row(r) for r in rows]

    def save_committee(self, ruleset: str, rec: Committee, by: str, at: str) -> Committee:
        self.db.execute(
            "INSERT INTO committee (ruleset, kind, external, establisher, contract_on, current_version, "
            "approved_version, approved_on, central, documents, by, at, due_on) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ruleset, rec.kind, int(rec.external), rec.establisher, rec.contract_on, rec.current_version,
             rec.approved_version, rec.approved_on, int(rec.central), rec.documents, by, at, rec.due_on),
        )  # fmt: skip
        return self.committee(ruleset)

    def permission(self, ruleset: str, site: str) -> Permission | None:
        """This site's newest head-of-institution permission for the study, or None (none, or cleared)."""
        if not site:
            return None
        rows = self.db.fetchall(
            "SELECT site, version, permitted_on, by, at FROM site_permission WHERE ruleset = ? AND site = ? "
            "ORDER BY at, id",
            (ruleset, site),
        )
        return permission_row(rows[-1]) if rows else None

    def opened(self, ruleset: str, site: str) -> cm.Opened | None:
        return cm.opened_of(self.db, ruleset, site)

    def record_open(self, ruleset: str, site: str, opened: cm.Opened, by: str, at: str) -> None:
        cm.record_open(self.db, ruleset, site, opened, by, at)

    def take_baseline(self, site: str, open_now: list[str], by: str, at: str) -> list[str]:
        return cm.take_baseline(self.db, site, open_now, by, at)

    def baseline_taken(self, site: str) -> bool:
        return cm.baseline_taken(self.db, site)

    def save_permission(self, ruleset: str, rec: Permission, by: str, at: str) -> Permission | None:
        self.db.execute(
            "INSERT INTO site_permission (ruleset, site, version, permitted_on, by, at) VALUES (?,?,?,?,?,?)",
            (ruleset, rec.site, rec.version, rec.permitted_on, by, at),
        )
        return self.permission(ruleset, rec.site)

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

    def take_once(self, ruleset: str, key: str, purpose: str, kind: str, by: str, at: str, since: str,
                  limit: int) -> str | None:  # fmt: skip
        """T-103 (D-438): at most one use per person, ``key`` and window. In one transaction, serialised per person
        and kind: ``"again"`` when this person already has a use of ``key`` for ``purpose`` since ``since`` (nothing
        recorded), ``"new"`` when a use is recorded within ``limit``, None at the cap."""
        with self.db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"candidate_views:{by}:{kind}",))
            seen = tx.fetchval(
                "SELECT count(*) FROM candidate_views WHERE by = ? AND kind = ? AND pid = ? AND purpose = ? "
                "AND at >= ?",
                (by, kind, key, purpose, since),
            )
            if int(seen or 0):
                return "again"
            n = tx.fetchval(
                "SELECT count(*) FROM candidate_views WHERE by = ? AND kind = ? AND at >= ?", (by, kind, since)
            )
            if int(n or 0) >= limit:
                return None
            tx.execute(
                "INSERT INTO candidate_views (ruleset, pid, purpose, kind, by, at) VALUES (?,?,?,?,?,?)",
                (ruleset, key, purpose, kind, by, at),
            )
        return "new"

    def used_since(self, key: str, purpose: str, kind: str, by: str, since: str) -> bool:
        """Has this person a use of ``key`` for ``purpose`` since ``since``? Read only."""
        return bool(
            self.db.fetchval(
                "SELECT count(*) FROM candidate_views WHERE by = ? AND kind = ? AND pid = ? AND purpose = ? "
                "AND at >= ?",
                (by, kind, key, purpose, since),
            )
        )

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

    # ------------------------------------------------------------------ monitoring visits (D-436, T-303)
    def add_monitor_visit(self, ruleset: str, *, visit_ref: str, visit_day: str, cra: str, subjects: list[str],
                          findings: str, at: str) -> MonitorVisit:  # fmt: skip
        """Record one monitoring visit. The caller has checked the grant and that each subject is one the monitor
        may open; here: a date, at least one subject, findings within :data:`FINDINGS_MAX`."""
        day = _day(visit_day, "the visit date")
        if day is None:
            raise TeamError("give the visit date")
        subs = list(dict.fromkeys(s.strip() for s in subjects if s.strip()))
        if not subs:
            raise TeamError("name at least one subject verified")
        text = findings.strip()
        if len(text) > FINDINGS_MAX:
            raise TeamError(f"the findings are at most {FINDINGS_MAX} characters")
        with self.db.transaction() as tx:
            new_id = tx.fetchval(
                "INSERT INTO monitor_visits (ruleset, visit_ref, visit_day, cra, subjects, findings, at) "
                "VALUES (?,?,?,?,?,?,?) RETURNING id",
                (ruleset, visit_ref.strip()[:60], day, cra, json.dumps(subs), text, at),
            )
        return MonitorVisit(int(new_id), visit_ref.strip()[:60], day, cra, tuple(subs), text, at)

    def monitor_visits(self, ruleset: str) -> list[MonitorVisit]:
        """The study's monitoring-visit records, newest first."""
        rows = self.db.fetchall(
            "SELECT id, visit_ref, visit_day, cra, subjects, findings, at FROM monitor_visits WHERE ruleset = ? "
            "ORDER BY at DESC, id DESC",
            (ruleset,),
        )
        return [MonitorVisit(int(r[0]), str(r[1]), str(r[2]), str(r[3]), tuple(json.loads(str(r[4]))), str(r[5]),
                             str(r[6])) for r in rows]  # fmt: skip

    # ------------------------------------------------------------------ 9f-3: the PI's cover (D-1383)
    # literal statements, no SQL put together from strings (the S608 ratchet, tools/sql_from_strings.json)
    _COVERS_SQL = ("SELECT id, ruleset, pi, pi_name, username, name, start_day, end_day, ended_on, ended_by, "
                   "irb_told_on, irb_told_by, start_logged_at, end_logged_at, by, at, entered_on, lapse_reason "
                   "FROM pi_cover WHERE ruleset = ? ORDER BY id")  # fmt: skip
    _COVER_SQL = ("SELECT id, ruleset, pi, pi_name, username, name, start_day, end_day, ended_on, ended_by, "
                  "irb_told_on, irb_told_by, start_logged_at, end_logged_at, by, at, entered_on, lapse_reason "
                  "FROM pi_cover WHERE ruleset = ? AND id = ?")  # fmt: skip
    _COVER_LOCK_SQL = ("SELECT id, ruleset, pi, pi_name, username, name, start_day, end_day, ended_on, ended_by, "
                       "irb_told_on, irb_told_by, start_logged_at, end_logged_at, by, at, entered_on, lapse_reason "
                       "FROM pi_cover WHERE ruleset = ? AND id = ? FOR UPDATE")  # fmt: skip

    @staticmethod
    def _cover(r: tuple[Any, ...]) -> Cover:
        return Cover(int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), str(r[6]), str(r[7]), r[8],
                     r[9], r[10], r[11], r[12] is not None, r[13] is not None, str(r[14]), str(r[15]), str(r[16]),
                     r[17])  # fmt: skip

    def covers(self, ruleset: str) -> list[Cover]:
        """The study's covers, oldest first (ended ones included: the record)."""
        rows = self.db.fetchall(self._COVERS_SQL, (ruleset,))
        return [self._cover(r) for r in rows]

    def cover(self, ruleset: str, cid: int) -> Cover | None:
        row = self.db.fetchone(self._COVER_SQL, (ruleset, cid))
        return self._cover(row) if row else None

    def rights(self, ruleset: str, username: str | None, day: date) -> LogRights:
        """:func:`log_rights` on this store's log and covers of ``ruleset`` (two reads)."""
        return log_rights(self.entries(ruleset), self.covers(ruleset), username, day)

    def add_cover(self, ruleset: str, *, username: str, start: str, end: str, today: date, by: str, at: str,
                  before_commit: Any = None) -> Cover:  # fmt: skip
        """9f-3: ``by``, the PI the study's log names today by their own entry, names ``username``, a
        sub-investigator of the same log, to hold the PI's clinical rights in this study (:data:`COVER_RIGHTS`; no
        export, no administration) from ``start`` to ``end``. Refused
        (TeamError): not the PI; the PI names themselves; no end, a start before today, an end before the start or a
        cover longer than :data:`COVER_MAX_DAYS`; a person whose sub-investigator entry does not cover every day;
        another cover of the study for some of the same days. ``before_commit`` (the ``add`` audit event, given the
        stored cover) runs inside the same transaction: if it fails, no cover is stored (D-1383)."""
        if (pi0 := self.pi_of(ruleset, today)) is None or not pi0.username or pi0.username != by:
            raise TeamError("only the PI the study's log names enters a cover")
        who = (username or "").strip().lower()
        if not who:
            raise TeamError("choose the sub-investigator who covers", fields=(("username", "fe.cover.username.none"),))
        if who == by:
            raise TeamError("a cover names another person than the PI", fields=(("username", "fe.cover.username.pi"),))
        try:
            s = _day(start, "the start date")
        except TeamError as exc:
            raise TeamError(str(exc), fields=(("start", "fe.cover.start.date"),)) from exc
        try:
            e = _day(end, "the end date")
        except TeamError as exc:
            raise TeamError(str(exc), fields=(("end", "fe.cover.end.date"),)) from exc
        if s is None or e is None:
            raise TeamError("a cover needs its first and its last day",
                            fields=(("start", "fe.cover.start.none"),) * (s is None)
                            + (("end", "fe.cover.end.none"),) * (e is None))  # fmt: skip
        if s < today.isoformat():
            raise TeamError("a cover starts today or later", fields=(("start", "fe.cover.start.past"),))
        if e < s:
            raise TeamError("the end date is before the start date", fields=(("end", "fe.cover.end.before"),))
        if (date.fromisoformat(e) - date.fromisoformat(s)).days + 1 > COVER_MAX_DAYS:
            raise TeamError(f"a cover is at most {COVER_MAX_DAYS} days", fields=(("end", "fe.cover.end.long"),))
        with self.db.transaction() as tx:
            # one study's covers are checked and written under one lock (the SAE register's form, saerecord): two
            # requests at once never both find the days free
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"pi_cover:{ruleset}",))
            entries = [_entry(r) for r in tx.fetchall(
                "SELECT id, ruleset, username, name, role, tasks, start_day, end_day, training_day, training_ref, "
                "signed_by, signed_at, updated_by, updated_at FROM delegation WHERE ruleset = ? ORDER BY id",
                (ruleset,))]  # fmt: skip
            pi = _pi_on(entries, today)
            if pi is None or not pi.username or pi.username != by:
                raise TeamError("only the PI the study's log names enters a cover")
            sub = next((x for x in reversed(entries) if x.username == who and x.role == COVER_ROLE
                        and x.start <= s and (x.end is None or x.end >= e)), None)  # fmt: skip
            if sub is None:
                raise TeamError(
                    "the person who covers is a sub-investigator on this study's log for every day of the cover",
                    fields=(("username", "fe.cover.username.sub"),),
                )
            rows = tx.fetchall(self._COVERS_SQL, (ruleset,))
            for c in (self._cover(r) for r in rows):
                last = c.last_day()
                if last and c.start <= e and s <= last:
                    raise TeamError("another cover of this study holds some of these days")
            row = tx.fetchone(
                "INSERT INTO pi_cover (ruleset, pi, pi_name, username, name, start_day, end_day, entered_on, by, at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (ruleset, pi.username, pi.name, who, sub.name, s, e, today.isoformat(), by, at),
            )
            assert row is not None
            out = self._cover_in(tx, ruleset, int(row[0]))
            if before_commit is not None:  # the audit event first: no cover takes effect without its ``add`` event
                before_commit(out)
        return out

    def _cover_in(self, tx: Any, ruleset: str, cid: int) -> Cover:
        row = tx.fetchone(self._COVER_SQL, (ruleset, cid))
        assert row is not None
        return self._cover(row)

    def end_cover(self, ruleset: str, cid: int, *, today: date, by: str, at: str, before_commit: Any = None) -> Cover:
        """End a cover early: from ``today`` (a cover that has not begun never begins). Refused when it is over.
        ``before_commit`` (the ``end_early`` event, given the cover as ended) runs in the same transaction."""
        with self.db.transaction() as tx:
            row = tx.fetchone(self._COVER_LOCK_SQL, (ruleset, cid))
            if row is None:
                raise TeamError("no such cover in this study")
            c = self._cover(row)
            if c.over_on(today):
                raise TeamError("this cover is already over")
            on = max(today.isoformat(), c.start)
            tx.execute("UPDATE pi_cover SET ended_on = ?, ended_by = ? WHERE ruleset = ? AND id = ? AND ended_on IS "
                       "NULL", (on, by, ruleset, cid))  # fmt: skip
            out = self._cover_in(tx, ruleset, cid)
            if before_commit is not None:
                before_commit(out)
        return out

    def irb_told(self, ruleset: str, cid: int, *, today: date, by: str, before_commit: Any = None) -> Cover:
        """The task "tell the IRB of the cover" is done (once). ``before_commit`` (the ``irb_told`` event) runs in the
        same transaction."""
        with self.db.transaction() as tx:
            row = tx.fetchone(self._COVER_LOCK_SQL, (ruleset, cid))
            if row is None:
                raise TeamError("no such cover in this study")
            if self._cover(row).irb_told_on:
                raise TeamError("the IRB was already told of this cover")
            tx.execute("UPDATE pi_cover SET irb_told_on = ?, irb_told_by = ? WHERE ruleset = ? AND id = ?",
                       (today.isoformat(), by, ruleset, cid))  # fmt: skip
            out = self._cover_in(tx, ruleset, cid)
            if before_commit is not None:
                before_commit(out)
        return out

    def lapse_cover(self, ruleset: str, cid: int, *, reason: str, last: str | None, at: str,
                    before_commit: Any = None) -> bool:  # fmt: skip
        """9f-3 (D-1383): store a cover's lapse, first observed, for good: ``ended_on`` the day after its last day in
        effect (its first day when it never took effect), ``lapse_reason``, its end marked logged (the ``lapsed`` event
        is its end); ``before_commit`` (that event) runs in the same transaction. True when this call stored it."""
        if reason not in LAPSE_REASONS:
            raise TeamError("no such lapse")
        with self.db.transaction() as tx:
            row = tx.fetchone("SELECT start_day FROM pi_cover WHERE ruleset = ? AND id = ? AND lapse_reason IS NULL "
                              "FOR UPDATE", (ruleset, cid))  # fmt: skip
            if row is None:
                return False
            on = (date.fromisoformat(last) + timedelta(days=1)).isoformat() if last else str(row[0])
            tx.execute("UPDATE pi_cover SET lapse_reason = ?, ended_on = CASE WHEN ended_on IS NULL OR ended_on > ? "
                       "THEN ? ELSE ended_on END, ended_by = COALESCE(ended_by, 'system:cover'), "
                       "end_logged_at = COALESCE(end_logged_at, ?) WHERE ruleset = ? AND id = ?",
                       (reason, on, on, at, ruleset, cid))  # fmt: skip
            if before_commit is not None:
                before_commit()
        return True

    def mark_cover_edge(self, ruleset: str, cid: int, edge: str, at: str, before_commit: Any = None) -> bool:
        """Record once that a cover's ``start`` or ``end`` was written to the audit trail; ``before_commit`` (the
        audit event) runs inside the same transaction, so the mark is never kept without its event. True when this
        call made the mark."""
        sql = {
            "start": "UPDATE pi_cover SET start_logged_at = ? WHERE ruleset = ? AND id = ? AND start_logged_at IS NULL "
                     "RETURNING id",
            "end": "UPDATE pi_cover SET end_logged_at = ? WHERE ruleset = ? AND id = ? AND end_logged_at IS NULL "
                   "RETURNING id",
        }[edge]  # fmt: skip
        with self.db.transaction() as tx:
            row = tx.fetchone(sql, (at, ruleset, cid))
            if row is None:
                return False
            if before_commit is not None:
                before_commit()
        return True

    def cover_rulesets(self) -> list[str]:
        """The studies that have a cover row (for the daily round of start and end events)."""
        return [str(r[0]) for r in self.db.fetchall("SELECT DISTINCT ruleset FROM pi_cover ORDER BY ruleset")]

    # ------------------------------------------------------------------ 9f-5: a task's owner (D-1383)
    def task_owners(self, ruleset: str) -> dict[tuple[str, str], TaskOwner]:
        """The current owner of each task of the study that has one (the newest row of each task; '' = none)."""
        rows = self.db.fetchall(
            "SELECT kind, ref, owner, owner_name, by, at FROM task_owner WHERE ruleset = ? ORDER BY at, id", (ruleset,)
        )
        out: dict[tuple[str, str], TaskOwner] = {}
        for r in rows:
            out[(str(r[0]), str(r[1]))] = TaskOwner(*(str(x) for x in r))
        return {k: v for k, v in out.items() if v.owner}

    def set_task_owner(self, ruleset: str, *, kind: str, ref: str, owner: str, day: date, by: str, at: str,
                       current: set[tuple[str, str]] | None = None) -> tuple[TaskOwner | None, TaskOwner]:  # fmt: skip
        """Name ``owner`` (an account with an active entry on this study's log on ``day``, not a monitor grant) as the
        owner of one task, or clear it (``owner`` ''). ``current``: the study's tasks today as the opening page has
        them, (kind, ref) pairs; a task not among them is refused (None: the caller checked). Returns (the owner
        before, the owner now)."""
        if kind not in TASK_KINDS:
            raise TeamError("no such task")
        ref = (ref or "").strip()
        if not _TASK_REF.match(ref) or (current is not None and (kind, ref) not in current):
            raise TeamError("no such task")
        who = (owner or "").strip().lower()
        name = ""
        if who:
            e = next((x for x in reversed(self.entries(ruleset)) if x.username == who and x.role in OWNER_ROLES
                      and x.active_on(day)), None)  # fmt: skip
            if e is None:
                raise TeamError(
                    "a task's owner is a person on this study's delegation log", fields=(("owner", "fe.owner.owner"),)
                )
            name = e.name
        with self.db.transaction() as tx:
            # the owner before and the new row under one lock per study: two changes at once each name the true before
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"task_owner:{ruleset}",))
            row = tx.fetchone(
                "SELECT kind, ref, owner, owner_name, by, at FROM task_owner WHERE ruleset = ? AND kind = ? "
                "AND ref = ? ORDER BY at DESC, id DESC",  # the newest first: its owner is the owner before
                (ruleset, kind, ref),
            )
            before = TaskOwner(*(str(x) for x in row)) if row is not None and row[2] else None
            tx.execute("INSERT INTO task_owner (ruleset, kind, ref, owner, owner_name, by, at) VALUES (?,?,?,?,?,?,?)",
                       (ruleset, kind, ref, who, name, by, at))  # fmt: skip
        return before, TaskOwner(kind, ref, who, name, by, at)
