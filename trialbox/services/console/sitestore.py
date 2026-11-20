"""What the site types into TrialBox and the PI's weekly marks (D-104), kept in the trial database (schema ``site``).

* **Site profile** per study: the parts of a sponsor feasibility questionnaire the EMR cannot answer — site
  capability checklist, competing trials, sponsor target, screen-failure rate, a comment for the barriers table —
  plus who entered them and when. Printed on the report as "entered by site".
* **PI marks**: Approach / Not suitable (reason) / Need info (what) per patient pseudonym and study. A mark is an
  event, never a registry status: a PI's "not suitable" must not become "screen fail" in the screening log (a CRA
  reads that word literally). The latest mark per patient counts; the history stays.
* **Weekly appearances**: the first week a pseudonym was listed for a study, so the list can say "new this week".
* **Build step 2 (D-108)**: study settings (type, cohort kind, the "Not suitable" reasons, screening-number format),
  screening numbers, contact outcomes, which amber approval rows an investigator opened, the coordinator's code
  pre-ticks, who receives which notice (investigator -> practitioner id for clinic days, digest time) and the notice
  log.
* **Study state and identifiers (D-386, LIFE-008, LIFE-013)**: the study's state (start-up, open, paused, closed) as
  an event log with who, when and why, and the study's sponsor, protocol number, site initiation visit (SIV) date
  and registry ids (ClinicalTrials.gov, jRCT, UMIN-CTR, the Taiwan registry). Lists run and N1/N2 mails go out only
  for an open study; a study with no recorded state counts as open, as before D-386.
* **The IRB text's coverage (D-395, RSK-42)**: whether the study's approved IRB text covers "identified pre-screening
  across departments by the investigator before referral", with the approval number, the text's version and date, as
  an event log recorded by the study's PI. The whole-hospital candidate view (D-147) opens only while it does.

Stored in the trial database (PostgreSQL ``trialbox_wf``, schema ``site``; D-126). Nothing here holds a chart number
or a name.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from console.storedb import open_db

MARKS = ("approach", "need_info", "not_suitable", "not_now")  # one vocabulary on every screen, mail, export
WITHDRAWN = "withdrawn"  # a withdrawn mark: stored as an event, so the history keeps the earlier mark (FR-SCR-07e/j)
NOT_SUITABLE_REASONS = ("stage", "partner", "comorbidity", "unlikely", "other")  # every reason any study type uses
STUDY_TYPES = ("trial", "registry", "observational")
COHORT_KINDS = ("enrolled", "dynamic")
# FR-STUDY-09: default "Not suitable" reasons per study type; a study may set its own list (S21, step 3)
DEFAULT_REASONS: dict[str, tuple[str, ...]] = {
    "ad": ("stage", "partner", "comorbidity", "unlikely", "other"),
    "ra": ("activity", "biologic", "comorbidity", "unlikely", "other"),
    "other": ("comorbidity", "unlikely", "other"),
}
ALL_REASONS = ("stage", "partner", "activity", "biologic", "comorbidity", "unlikely", "other")
# FR-SCR-10c: contact outcomes a coordinator records in two taps; status change per TB-DS-07 §4.1
OUTCOMES: dict[str, tuple[str | None, str | None]] = {  # outcome -> (registry status after, reason category)
    "reached_booked": ("contacted", None),
    "reached_declined": ("declined", "declined"),
    "not_reached": (None, None),  # status unchanged; a retry date is kept
    "not_approached": (None, "not approached (physician decision)"),
    "lost_contact": ("screen_fail", "lost contact"),
}
CAPABILITIES_AD: tuple[str, ...] = (
    "amyloid_pet",
    "tau_pet",
    "csf",
    "plasma_ptau217",
    "mri_3t_aria",
    "aria_radiologist",
    "infusion",
    "raters",
    "partner_room",
    "ip_storage",
    "apoe",
)
CAPABILITIES_GENERAL: tuple[str, ...] = ("imaging", "lab", "pharmacy", "infusion", "raters_general", "ip_storage")
CAP_VALUES = ("yes", "partner", "no", "na")

# Version 1 is the schema the SQLite file had (D-126). Append new versions; never edit an applied one. ``at`` columns
# hold ISO-8601 text and sort with the "C" collation, byte by byte, as SQLite compared them.
SCHEMA_V1 = """
CREATE TABLE site_profile (
  ruleset TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  entered_by TEXT NOT NULL,
  entered_at TEXT NOT NULL
);
CREATE TABLE pi_marks (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  mark TEXT NOT NULL,
  reason TEXT,
  note TEXT,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL,
  job_id TEXT
);
CREATE INDEX pi_marks_rs ON pi_marks (ruleset, pid, at);
CREATE TABLE weekly_seen (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  first_job TEXT NOT NULL,
  first_at TEXT NOT NULL,
  PRIMARY KEY (ruleset, pid)
);
CREATE TABLE study_settings (
  ruleset TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE screening_no (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  seq INTEGER NOT NULL,
  no TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (ruleset, pid),
  UNIQUE (ruleset, seq)
);
CREATE TABLE contact_outcomes (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  outcome TEXT NOT NULL,
  retry TEXT,
  note TEXT,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX contact_outcomes_rs ON contact_outcomes (ruleset, pid, at);
CREATE TABLE approval_opened (
  job_id TEXT NOT NULL,
  crit TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (job_id, crit, by)
);
CREATE TABLE criterion_labels (
  ruleset TEXT NOT NULL,
  crit TEXT NOT NULL,
  lang TEXT NOT NULL,
  label TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (ruleset, crit, lang)
);
CREATE TABLE code_ticks (
  job_id TEXT NOT NULL,
  crit TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (job_id, crit)
);
CREATE TABLE notify_people (
  username TEXT PRIMARY KEY,
  practitioner_id TEXT,
  digest_time TEXT NOT NULL DEFAULT '07:30',
  enabled INTEGER NOT NULL DEFAULT 1,
  lang TEXT NOT NULL DEFAULT 'en'
);
CREATE TABLE notify_log (
  kind TEXT NOT NULL,
  username TEXT NOT NULL,
  day TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL,
  subject TEXT NOT NULL,
  PRIMARY KEY (kind, username, day)
)
"""
# review 2026-11-09 P-04 (D-143): an excluded patient a person thinks was excluded wrongly, sent to review
SCHEMA_V2 = """
CREATE TABLE excluded_review (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  job_id TEXT NOT NULL,
  crit TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL,
  PRIMARY KEY (ruleset, pid, job_id)
)
"""
# D-178 (review J-14): a contact outcome can be undone; the row stays (the trail), marked undone, with the registry
# status it replaced so the undo can put it back
SCHEMA_V3 = """
ALTER TABLE contact_outcomes ADD COLUMN prev_status TEXT;
ALTER TABLE contact_outcomes ADD COLUMN undone_by TEXT;
ALTER TABLE contact_outcomes ADD COLUMN undone_at TEXT
"""
# D-364 (LIFE-010): the criteria version the list showed when the mark was made, so an amendment can re-open marks
# made under an older version (additive; marks made before have none and count as older than any version)
SCHEMA_V4 = """
ALTER TABLE pi_marks ADD COLUMN version TEXT
"""
# D-386 (T-622, LIFE-008, LIFE-013): the study's state as an event log (the latest row is the state) and the study's
# identifiers (one row per study; every change is a ``console.study_identity`` audit event)
SCHEMA_V5 = """
CREATE TABLE study_state (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  state TEXT NOT NULL,
  prev TEXT,
  reason TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX study_state_rs ON study_state (ruleset, at);
CREATE TABLE study_identity (
  ruleset TEXT PRIMARY KEY,
  sponsor TEXT NOT NULL DEFAULT '',
  protocol_no TEXT NOT NULL DEFAULT '',
  siv_date TEXT,
  registry_ids TEXT NOT NULL DEFAULT '{}',
  by TEXT NOT NULL,
  at TEXT NOT NULL
)
"""
# D-395 (T-310b, RSK-42): the IRB approval text's coverage of the cross-department identified view, per study, as an
# event log (the latest row is the record). The candidate view of D-147 opens only while it says "covers".
SCHEMA_V6 = """
CREATE TABLE study_irb_text (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  covers BOOLEAN NOT NULL,
  sentence TEXT NOT NULL,
  approval_ref TEXT NOT NULL DEFAULT '',
  text_version TEXT NOT NULL DEFAULT '',
  approved_on TEXT,
  note TEXT NOT NULL DEFAULT '',
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX study_irb_text_rs ON study_irb_text (ruleset, at)
"""
# D-779 (T-305c): a close names how many years the study's files are kept after it (RETENTION reads it); other rows
# and closes recorded before have none (the default period)
SCHEMA_V7 = """
ALTER TABLE study_state ADD COLUMN keep_years INTEGER
"""
# 9k-7 (D-1388): an Undo row names the mark row it takes back, so an Undo is done once (a second click, a second tab or
# the back button finds it done and writes nothing) and the trail keeps both rows. Idempotent: run again, it changes
# nothing; rows before it have none (no Undo of theirs is known)
SCHEMA_V8 = """
ALTER TABLE pi_marks ADD COLUMN IF NOT EXISTS undoes BIGINT;
CREATE UNIQUE INDEX IF NOT EXISTS pi_marks_undoes ON pi_marks (undoes) WHERE undoes IS NOT NULL
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6, SCHEMA_V7, SCHEMA_V8)

# ---------------------------------------------------------------------------------------------- D-386 study state
STUDY_STATES = ("startup", "open", "paused", "closed")
# the moves a person may make; "closed" is final (a study that recruits again is a new study set-up)
STATE_MOVES: dict[str, tuple[str, ...]] = {
    "startup": ("open", "closed"),
    "open": ("paused", "closed"),
    "paused": ("open", "closed"),
    "closed": (),
}
LIST_STATES = ("open",)  # screening lists run and N1/N2 mails go out only in these states
DEFAULT_STATE = "open"  # a study with no recorded state, as before D-386 (the pilot studies keep running)
# Registry ids, by the registries' public formats (synthetic examples only in tests and docs):
# ClinicalTrials.gov "NCT" + 8 digits; jRCT "jRCT" + 10 digits, or a category letter + 9 digits ("jRCTs..."); UMIN-CTR
# "UMIN" + 9 digits. The Taiwan registry publishes no single pattern we could confirm: its id is checked for shape
# only (4 to 40 letters, digits and ". / _ -", starting with a letter or digit) and may not look like another
# registry's id (a jRCT or NCT id typed into the Taiwan field is refused).
REGISTRIES = ("nct", "jrct", "umin", "tw")
REGISTRY_PATTERNS: dict[str, re.Pattern[str]] = {
    "nct": re.compile(r"^NCT\d{8}$"),
    "jrct": re.compile(r"^jRCT[a-z]?\d{9,10}$"),
    "umin": re.compile(r"^UMIN\d{9}$"),
    "tw": re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_-]{3,39}$"),
}
_PROTOCOL_NO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()-]{0,39}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPONSOR_MAX = 120


def registry_id_ok(registry: str, value: str) -> bool:
    """True when ``value`` is a well-formed id of ``registry`` (one of :data:`REGISTRIES`)."""
    pat = REGISTRY_PATTERNS.get(registry)
    if pat is None or not pat.match(value):
        return False
    if registry == "tw":  # another registry's id in the Taiwan field is a slip, not a Taiwan id
        return not any(REGISTRY_PATTERNS[r].match(value) for r in ("nct", "jrct", "umin"))
    return True


def state_move_ok(prev: str, new: str) -> bool:
    return new in STATE_MOVES.get(prev, ())


# ---------------------------------------------------------------------------------------------- D-395 IRB text
# The sentence the study's IRB approval text must cover for the cross-department identified candidate view (WS-06.5,
# RSK-42; item 4 of the site amendments). Its id is stored with each record, so a later wording is a new id and an
# older record never counts for it.
IRB_SENTENCE_ID = "cross_dept_identified_v1"
IRB_SENTENCE_EN = "Identified pre-screening across departments by the investigator before referral"
_IRB_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()#-]{0,59}$")
_TEXT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()-]{0,39}$")
NOTE_MAX = 200


@dataclass(frozen=True)
class IrbText:
    """Whether the study's approved IRB text covers :data:`IRB_SENTENCE_ID` (D-395), as the PI recorded it: the
    approval number of that text, its version and approval date. ``by`` empty: nothing recorded (the view is off)."""

    covers: bool = False
    approval_ref: str = ""
    text_version: str = ""
    approved_on: str = ""
    note: str = ""
    sentence: str = IRB_SENTENCE_ID
    by: str = ""
    at: str = ""

    @property
    def enables(self) -> bool:
        """The candidate view may open: the latest record says the approved text covers the current sentence."""
        return self.covers and self.sentence == IRB_SENTENCE_ID and bool(self.approval_ref)

    def problems(self, today: date) -> list[str]:
        """The fields that are wrong, by name. Covering needs the approval number; withdrawing needs a note."""
        out: list[str] = []
        if (self.covers and not self.approval_ref) or (self.approval_ref and not _IRB_REF.match(self.approval_ref)):
            out.append("approval_ref")
        if self.text_version and not _TEXT_VERSION.match(self.text_version):
            out.append("text_version")
        if self.approved_on:
            try:
                ok = bool(_DATE.match(self.approved_on)) and date.fromisoformat(self.approved_on) <= today
            except ValueError:
                ok = False
            if not ok:
                out.append("approved_on")
        bad_note = len(self.note) > NOTE_MAX or any(ord(c) < 32 for c in self.note)
        if bad_note or (not self.covers and not self.note):  # taking the record back needs a note
            out.append("note")
        return out


@dataclass(frozen=True)
class StudyState:
    """The study's state now: the latest event of the log, or the default for a study with none (``by`` empty)."""

    state: str = DEFAULT_STATE
    reason: str = ""
    by: str = ""
    at: str = ""
    prev: str | None = None
    keep_years: int | None = None  # D-779: on a close, the years the study's files are kept after it

    @property
    def runs(self) -> bool:
        """Lists run and N1/N2 mails go out (D-386): only an open study."""
        return self.state in LIST_STATES


@dataclass
class StudyIdentity:
    """Who runs the study and where it is registered (D-386, LIFE-013). Every field is optional; what is filled in
    must have its format. Printed on the study state page and the screening log's "about" sheet."""

    sponsor: str = ""
    protocol_no: str = ""
    siv_date: str = ""  # the site initiation visit, YYYY-MM-DD
    registry_ids: dict[str, str] = field(default_factory=dict)  # registry -> id, registry in REGISTRIES
    by: str = ""
    at: str = ""

    def problems(self) -> list[str]:
        """The fields that are filled in and wrong, by name (``registry.<r>`` for a registry id)."""
        out: list[str] = []
        if len(self.sponsor) > SPONSOR_MAX or any(ord(c) < 32 for c in self.sponsor):
            out.append("sponsor")
        if self.protocol_no and not _PROTOCOL_NO.match(self.protocol_no):
            out.append("protocol_no")
        if self.siv_date:
            try:
                ok = bool(_DATE.match(self.siv_date)) and date.fromisoformat(self.siv_date).isoformat() == self.siv_date
            except ValueError:
                ok = False
            if not ok:
                out.append("siv_date")
        for reg, value in self.registry_ids.items():
            if reg not in REGISTRIES or (value and not registry_id_ok(reg, value)):
                out.append(f"registry.{reg}")
        return out

    def lines(self) -> list[tuple[str, str]]:
        """(field, value) of what is filled in, in a fixed order: the log's "about" sheet prints these."""
        out = [(k, v) for k, v in (("sponsor", self.sponsor), ("protocol_no", self.protocol_no),
                                   ("siv_date", self.siv_date)) if v]  # fmt: skip
        out += [(f"registry.{r}", self.registry_ids[r]) for r in REGISTRIES if self.registry_ids.get(r)]
        return out


@dataclass
class StudySettings:
    """Per-study settings the build reads (FR-STUDY-01/02/08/09). Edited on S21 from step 3; until then the defaults
    below apply, derived from the ruleset."""

    study_type: str = "trial"
    cohort_kind: str = "enrolled"
    reasons: tuple[str, ...] = DEFAULT_REASONS["other"]
    screening_prefix: str = ""  # empty = "<STUDY>-"
    first_no: int = 1  # continue the site's own sequence

    def as_dict(self) -> dict[str, Any]:
        return {
            "study_type": self.study_type,
            "cohort_kind": self.cohort_kind,
            "reasons": list(self.reasons),
            "screening_prefix": self.screening_prefix,
            "first_no": self.first_no,
        }


@dataclass(frozen=True)
class Outcome:
    pid: str
    outcome: str
    retry: str | None
    note: str | None
    by: str
    at: str


@dataclass(frozen=True)
class NotifyPerson:
    username: str
    practitioner_id: str | None
    digest_time: str = "07:30"
    enabled: bool = True
    lang: str = "en"


@dataclass
class SiteProfile:
    capabilities: dict[str, dict[str, str]] = field(default_factory=dict)  # key -> {value, note}
    competing: list[dict[str, str]] = field(default_factory=list)  # {id, title, overlap, status, target}
    target_n: int | None = None
    target_months: int | None = None
    screen_fail: float | None = None  # 0..1; None = the report's default (or none)
    comment: str = ""
    comment_to_sponsor: bool = False
    entered_by: str = ""
    entered_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "capabilities": self.capabilities,
            "competing": self.competing,
            "target_n": self.target_n,
            "target_months": self.target_months,
            "screen_fail": self.screen_fail,
            "comment": self.comment,
            "comment_to_sponsor": self.comment_to_sponsor,
        }

    @property
    def missing(self) -> list[str]:
        """Which of the three site inputs are still empty (drives the CRC's next action)."""
        out = []
        if not any(v.get("value") for v in self.capabilities.values()):
            out.append("capability")
        if not self.competing:
            out.append("competing")
        if not self.target_n:
            out.append("target")
        return out


@dataclass(frozen=True)
class Mark:
    pid: str
    mark: str
    reason: str | None
    note: str | None
    by: str
    at: str
    job_id: str | None
    version: str | None = None  # the criteria version of the list the mark was made on (D-364)
    id: int | None = None  # the row's id (9k-7, D-1388: an Undo names the row it takes back)
    undoes: int | None = None  # this row is the Undo of that row (9k-7, D-1388)


class SiteStore:
    """Schema ``site`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = open_db(url, "site", MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ site profile
    def profile(self, ruleset: str) -> SiteProfile:
        row = self.db.fetchone("SELECT body, entered_by, entered_at FROM site_profile WHERE ruleset = ?", (ruleset,))
        if row is None:
            return SiteProfile()
        body = json.loads(row[0])
        return SiteProfile(**body, entered_by=row[1], entered_at=row[2])

    def save_profile(self, ruleset: str, prof: SiteProfile, by: str, at: str) -> SiteProfile:
        body = json.dumps(prof.as_dict(), ensure_ascii=False, sort_keys=True)
        self.db.execute(
            "INSERT INTO site_profile (ruleset, body, entered_by, entered_at) VALUES (?,?,?,?) "
            "ON CONFLICT (ruleset) DO UPDATE SET body = excluded.body, entered_by = excluded.entered_by, "
            "entered_at = excluded.entered_at",
            (ruleset, body, by, at),
        )
        prof.entered_by, prof.entered_at = by, at
        return prof

    # ------------------------------------------------------------------ PI marks
    def mark(
        self,
        ruleset: str,
        m: Mark,
        number: StudySettings | None = None,
        before_commit: Callable[[str | None], None] | None = None,
    ) -> str | None:
        """Store one mark; with ``number`` also give the patient the study's screening number (FR-STUDY-08), in the
        same transaction. D-273 (CR-055, DI-5): ``before_commit`` (the audit append) runs inside that transaction with
        the number, so a failed append rolls the mark and the number back: no change is ever kept without its audit
        event. Returns the screening number, or None."""
        if m.mark not in (*MARKS, WITHDRAWN):
            raise ValueError(f"mark must be one of {', '.join(MARKS)}")
        with self.db.transaction() as tx:
            # 9k-7 (D-1388): one writer per patient's marks at a time, so an Undo sees the latest row as it is
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"pi_marks:{ruleset}:{m.pid}",))
            tx.execute(
                "INSERT INTO pi_marks (ruleset, pid, mark, reason, note, by, at, job_id, version) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ruleset, m.pid, m.mark, m.reason, m.note, m.by, m.at, m.job_id, m.version),
            )
            no = self._number(tx, ruleset, m.pid, number, m.at) if number is not None else None
            if before_commit is not None:
                before_commit(no)
        return no

    def latest_marks(self, ruleset: str) -> dict[str, Mark]:
        out: dict[str, Mark] = {}
        for m in self.all_marks(ruleset):
            if m.mark == WITHDRAWN:  # the PI took the mark back: no current mark, the history keeps both events
                out.pop(m.pid, None)
            else:
                out[m.pid] = m
        return out

    def mark_history(self, ruleset: str, pid: str) -> list[Mark]:
        rows = self.db.fetchall(
            "SELECT pid, mark, reason, note, by, at, job_id, version, id, undoes FROM pi_marks WHERE ruleset = ? "
            "AND pid = ? ORDER BY at, id",
            (ruleset, pid),
        )
        return [Mark(*r) for r in rows]

    def undo_mark(
        self,
        ruleset: str,
        done_id: int,
        m: Mark,
        number: StudySettings | None = None,
        before_commit: Callable[[str | None], None] | None = None,
    ) -> str:
        """9k-7 (D-1388): store ``m``, the state before row ``done_id``, as the Undo of that row, in one transaction
        under the patient's lock: ``"undone"`` when written; ``"already"`` when an Undo of that row exists (nothing is
        written: a second click, a second tab); ``"changed"`` when a later row exists (nothing is written). The audit
        event (``before_commit``) runs inside the transaction, so the Undo is never kept without it."""
        if m.mark not in (*MARKS, WITHDRAWN):
            raise ValueError(f"mark must be one of {', '.join(MARKS)}")
        with self.db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"pi_marks:{ruleset}:{m.pid}",))
            if tx.fetchone("SELECT 1 FROM pi_marks WHERE undoes = ?", (done_id,)) is not None:
                return "already"
            last = tx.fetchone(
                "SELECT id FROM pi_marks WHERE ruleset = ? AND pid = ? ORDER BY at DESC, id DESC LIMIT 1",
                (ruleset, m.pid),
            )
            if last is None or int(last[0]) != done_id:
                return "changed"
            tx.execute(
                "INSERT INTO pi_marks (ruleset, pid, mark, reason, note, by, at, job_id, version, undoes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ruleset, m.pid, m.mark, m.reason, m.note, m.by, m.at, m.job_id, m.version, done_id),
            )
            no = self._number(tx, ruleset, m.pid, number, m.at) if number is not None else None
            if before_commit is not None:
                before_commit(no)
        return "undone"

    # ------------------------------------------------------------------ weekly appearances
    def seen(self, ruleset: str, pids: list[str], job_id: str, at: str) -> dict[str, str]:
        """Record first appearances of ``pids`` on a list for ``ruleset``; return pid -> job id of first listing."""
        with self.db.transaction() as tx:
            tx.executemany(
                "INSERT INTO weekly_seen (ruleset, pid, first_job, first_at) VALUES (?,?,?,?) "
                "ON CONFLICT (ruleset, pid) DO NOTHING",
                [(ruleset, pid, job_id, at) for pid in pids],
            )
            rows = tx.fetchall("SELECT pid, first_job FROM weekly_seen WHERE ruleset = ?", (ruleset,))
        return {str(p): str(j) for p, j in rows}

    def first_seen(self, ruleset: str) -> dict[str, tuple[str, str]]:
        """pid -> (first job, first time) a pseudonym was listed for ``ruleset``."""
        rows = self.db.fetchall("SELECT pid, first_job, first_at FROM weekly_seen WHERE ruleset = ?", (ruleset,))
        return {str(p): (str(j), str(a)) for p, j, a in rows}

    def screening_rows(self, ruleset: str) -> list[tuple[str, str, str]]:
        """(pid, screening number, assigned at), in number order."""
        rows = self.db.fetchall("SELECT pid, no, at FROM screening_no WHERE ruleset = ? ORDER BY seq", (ruleset,))
        return [(str(p), str(n), str(a)) for p, n, a in rows]

    def all_marks(self, ruleset: str) -> list[Mark]:
        rows = self.db.fetchall(
            "SELECT pid, mark, reason, note, by, at, job_id, version FROM pi_marks WHERE ruleset = ? ORDER BY at, id",
            (ruleset,),
        )
        return [Mark(*r) for r in rows]

    # ------------------------------------------------------------------ study settings (D-108)
    def study_settings(self, ruleset: str, default: StudySettings | None = None) -> StudySettings:
        row = self.db.fetchone("SELECT body FROM study_settings WHERE ruleset = ?", (ruleset,))
        base = default or StudySettings()
        if row is None:
            return base
        body = json.loads(row[0])
        body["reasons"] = tuple(body.get("reasons") or base.reasons)
        return StudySettings(**{**base.as_dict(), **body})

    def save_study_settings(self, ruleset: str, s: StudySettings, by: str, at: str) -> None:
        if s.study_type not in STUDY_TYPES or s.cohort_kind not in COHORT_KINDS:
            raise ValueError("unknown study type or cohort kind")
        if not s.reasons or any(r not in ALL_REASONS for r in s.reasons):
            raise ValueError(f"reasons must be among {', '.join(ALL_REASONS)}")
        body = json.dumps(s.as_dict(), ensure_ascii=False, sort_keys=True)
        self.db.execute(
            "INSERT INTO study_settings (ruleset, body, by, at) VALUES (?,?,?,?) ON CONFLICT (ruleset) DO UPDATE "
            "SET body = excluded.body, by = excluded.by, at = excluded.at",
            (ruleset, body, by, at),
        )

    # ------------------------------------------------------------------ screening numbers (FR-STUDY-08, BD-18)
    def screening_no(self, ruleset: str, pid: str) -> str | None:
        row = self.db.fetchone("SELECT no FROM screening_no WHERE ruleset = ? AND pid = ?", (ruleset, pid))
        return str(row[0]) if row else None

    def screening_nos(self, ruleset: str) -> dict[str, str]:
        rows = self.db.fetchall("SELECT pid, no FROM screening_no WHERE ruleset = ?", (ruleset,))
        return {str(p): str(n) for p, n in rows}

    def assign_screening_no(self, ruleset: str, pid: str, settings: StudySettings, at: str) -> str:
        """The study's next screening number for ``pid``; an existing number is kept (never re-used, never moved)."""
        with self.db.transaction() as tx:
            return self._number(tx, ruleset, pid, settings, at)

    @staticmethod
    def _number(tx: Any, ruleset: str, pid: str, settings: StudySettings, at: str) -> str:
        # one numberer per study at a time, across console processes too
        tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"screening_no:{ruleset}",))
        row = tx.fetchone("SELECT no FROM screening_no WHERE ruleset = ? AND pid = ?", (ruleset, pid))
        if row is not None:
            return str(row[0])
        top = tx.fetchval("SELECT MAX(seq) FROM screening_no WHERE ruleset = ?", (ruleset,))
        seq = max(int(top or 0) + 1, settings.first_no)
        prefix = settings.screening_prefix or f"{ruleset}-"
        no = f"{prefix}{seq:04d}"
        tx.execute(
            "INSERT INTO screening_no (ruleset, pid, seq, no, at) VALUES (?,?,?,?,?)", (ruleset, pid, seq, no, at)
        )
        return no

    # ------------------------------------------------------------------ contact outcomes (FR-SCR-10c)
    def add_outcome(self, ruleset: str, o: Outcome, prev_status: str | None = None) -> None:
        if o.outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
        self.db.execute(
            "INSERT INTO contact_outcomes (ruleset, pid, outcome, retry, note, by, at, prev_status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ruleset, o.pid, o.outcome, o.retry, o.note, o.by, o.at, prev_status),
        )

    def undo_outcome(self, ruleset: str, pid: str, by: str, at: str) -> tuple[Outcome, str | None] | None:
        """D-178 (review J-14): mark ``by``'s latest contact outcome of ``pid`` undone, if it is the patient's latest
        one. Returns that outcome and the registry status it replaced, or None (nothing of this person's to undo)."""
        with self.db.transaction() as tx:
            row = tx.fetchone(
                "SELECT id, pid, outcome, retry, note, by, at, prev_status FROM contact_outcomes WHERE ruleset = ? "
                "AND pid = ? AND undone_at IS NULL ORDER BY at DESC, id DESC LIMIT 1 FOR UPDATE",
                (ruleset, pid),
            )
            if row is None or row[5] != by:
                return None
            tx.execute("UPDATE contact_outcomes SET undone_by = ?, undone_at = ? WHERE id = ?", (by, at, row[0]))
        return Outcome(*row[1:7]), (str(row[7]) if row[7] is not None else None)

    def restore_outcome(self, ruleset: str, o: Outcome, undone_at: str) -> None:
        """Put back an outcome :meth:`undo_outcome` marked undone at ``undone_at`` (the registry refused the undo)."""
        self.db.execute(
            "UPDATE contact_outcomes SET undone_by = NULL, undone_at = NULL WHERE ruleset = ? AND pid = ? AND by = ? "
            "AND at = ? AND undone_at = ?",
            (ruleset, o.pid, o.by, o.at, undone_at),
        )

    def outcomes(self, ruleset: str, pid: str | None = None) -> list[Outcome]:
        """The contact outcomes in force (an undone one is left out; it stays in the table and the audit)."""
        q = "SELECT pid, outcome, retry, note, by, at FROM contact_outcomes WHERE ruleset = ? AND undone_at IS NULL"
        args: tuple[str, ...] = (ruleset,)
        if pid is not None:
            q, args = q + " AND pid = ?", (ruleset, pid)
        rows = self.db.fetchall(q + " ORDER BY at, id", args)
        return [Outcome(*r) for r in rows]

    # ------------------------------------------------------------------ approval page (FR-FEAS-12a/d)
    def open_row(self, job_id: str, crit: str, by: str, at: str) -> None:
        self.db.execute(
            "INSERT INTO approval_opened (job_id, crit, by, at) VALUES (?,?,?,?) "
            "ON CONFLICT (job_id, crit, by) DO NOTHING",
            (job_id, crit, by, at),
        )

    def opened_rows(self, job_id: str, by: str) -> set[str]:
        rows = self.db.fetchall("SELECT crit FROM approval_opened WHERE job_id = ? AND by = ?", (job_id, by))
        return {str(r[0]) for r in rows}

    def tick_codes(self, job_id: str, crit: str, by: str, at: str) -> None:
        self.db.execute(
            "INSERT INTO code_ticks (job_id, crit, by, at) VALUES (?,?,?,?) "
            "ON CONFLICT (job_id, crit) DO UPDATE SET by = excluded.by, at = excluded.at",
            (job_id, crit, by, at),
        )

    # ------------------------------------------------------------------ criterion labels in the site language (D-120)
    def save_label(self, ruleset: str, crit: str, lang: str, label: str, by: str, at: str) -> None:
        if label:
            self.db.execute(
                "INSERT INTO criterion_labels (ruleset, crit, lang, label, by, at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT (ruleset, crit, lang) DO UPDATE SET label = excluded.label, by = excluded.by, "
                "at = excluded.at",
                (ruleset.upper(), crit, lang, label, by, at),
            )
        else:
            self.db.execute(
                "DELETE FROM criterion_labels WHERE ruleset = ? AND crit = ? AND lang = ?",
                (ruleset.upper(), crit, lang),
            )

    def labels(self, ruleset: str, lang: str) -> dict[str, str]:
        rows = self.db.fetchall(
            "SELECT crit, label FROM criterion_labels WHERE ruleset = ? AND lang = ?", (ruleset.upper(), lang)
        )
        return {str(c): str(v) for c, v in rows}

    def code_ticks(self, job_id: str) -> dict[str, tuple[str, str]]:
        rows = self.db.fetchall("SELECT crit, by, at FROM code_ticks WHERE job_id = ?", (job_id,))
        return {str(c): (str(b), str(a)) for c, b, a in rows}

    # ------------------------------------------------------------------ excluded patients sent to review (P-04)
    def send_excluded_review(self, ruleset: str, pid: str, job_id: str, crit: str, note: str, by: str, at: str,
                             before_commit: Callable[[], None] | None = None) -> bool:  # fmt: skip
        """Record the first "send to review" of a patient on a run (a later one is not kept). True when this one was
        recorded; ``before_commit`` (D-989's events, the review of D-1152) runs inside the transaction then only, so
        a review the store does not keep writes no decision, and a failed append keeps no review."""
        with self.db.transaction() as tx:
            n = tx.execute(
                "INSERT INTO excluded_review (ruleset, pid, job_id, crit, note, by, at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT (ruleset, pid, job_id) DO NOTHING",
                (ruleset.upper(), pid, job_id, crit, note, by, at),
            )
            if n and before_commit is not None:
                before_commit()
        return bool(n)

    def excluded_reviews(self, ruleset: str) -> dict[str, dict[str, str]]:
        """pid -> the first "send to review" of this patient (who, when, the criterion, the note)."""
        rows = self.db.fetchall(
            "SELECT pid, job_id, crit, note, by, at FROM excluded_review WHERE ruleset = ? ORDER BY at",
            (ruleset.upper(),),
        )
        out: dict[str, dict[str, str]] = {}
        for pid, job, crit, note, by, at in rows:
            out.setdefault(str(pid), {"job_id": str(job), "crit": str(crit), "note": str(note), "by": str(by),
                                      "at": str(at)})  # fmt: skip
        return out

    # ------------------------------------------------------------------ notices (FR-NOTIF-01/02)
    def notify_person(self, username: str) -> NotifyPerson:
        row = self.db.fetchone(
            "SELECT username, practitioner_id, digest_time, enabled, lang FROM notify_people WHERE username = ?",
            (username,),
        )
        if row is None:
            return NotifyPerson(username, None)
        return NotifyPerson(str(row[0]), row[1], str(row[2]), bool(row[3]), str(row[4]))

    def save_notify_person(self, p: NotifyPerson) -> None:
        self.db.execute(
            "INSERT INTO notify_people (username, practitioner_id, digest_time, enabled, lang) VALUES (?,?,?,?,?) "
            "ON CONFLICT (username) DO UPDATE SET practitioner_id = excluded.practitioner_id, "
            "digest_time = excluded.digest_time, enabled = excluded.enabled, lang = excluded.lang",
            (p.username, p.practitioner_id, p.digest_time, int(p.enabled), p.lang),
        )

    def notice_sent(self, kind: str, username: str, day: str) -> bool:
        row = self.db.fetchone(
            "SELECT 1 FROM notify_log WHERE kind = ? AND username = ? AND day = ?", (kind, username, day)
        )
        return row is not None

    def last_notice(self, kind: str, username: str) -> str | None:
        at = self.db.fetchval("SELECT MAX(at) FROM notify_log WHERE kind = ? AND username = ?", (kind, username))
        return str(at) if at else None

    def log_notice(self, kind: str, username: str, day: str, at: str, subject: str) -> None:
        self.db.execute(
            "INSERT INTO notify_log (kind, username, day, at, subject) VALUES (?,?,?,?,?) "
            "ON CONFLICT (kind, username, day) DO UPDATE SET at = excluded.at, subject = excluded.subject",
            (kind, username, day, at, subject),
        )

    def notices_for(self, username: str, limit: int = 50) -> list[tuple[str, str, str, str]]:
        """S37 Notices received (step 4, FR-PLAT-17): (kind, day, at, subject) of one person, newest first."""
        rows = self.db.fetchall(
            "SELECT kind, day, at, subject FROM notify_log WHERE username = ? ORDER BY at DESC LIMIT ?",
            (username, limit),
        )
        return [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]

    # ------------------------------------------------------------------ study state and identifiers (D-386)
    def study_state(self, ruleset: str) -> StudyState:
        row = self.db.fetchone(
            "SELECT state, reason, by, at, prev, keep_years FROM study_state WHERE ruleset = ?"
            " ORDER BY at DESC, id DESC LIMIT 1",
            (ruleset.upper(),),
        )
        if row is None:
            return StudyState()
        return StudyState(str(row[0]), str(row[1]), str(row[2]), str(row[3]), row[4], row[5])

    def state_history(self, ruleset: str) -> list[StudyState]:
        """Every state change of the study, oldest first (the log prints the dates)."""
        rows = self.db.fetchall(
            "SELECT state, reason, by, at, prev, keep_years FROM study_state WHERE ruleset = ? ORDER BY at, id",
            (ruleset.upper(),),
        )
        return [StudyState(str(r[0]), str(r[1]), str(r[2]), str(r[3]), r[4], r[5]) for r in rows]

    def set_study_state(
        self, ruleset: str, state: str, reason: str, by: str, at: str,
        before_commit: Callable[[StudyState], None] | None = None, take_back: bool = False,
        keep_years: int | None = None,
    ) -> StudyState:  # fmt: skip
        """Move the study to ``state``. Refuses a state not in :data:`STUDY_STATES` or a move not in
        :data:`STATE_MOVES` (ValueError). ``before_commit`` (the audit append) runs inside the transaction, so a
        failed append keeps the old state (as D-273 does for marks).

        ``take_back`` (NEW-LIFE-6, D-763): the one way out of ``closed``: back to the state the close left, read
        under the same lock (the caller checks who and that the close was made the same site day).

        ``keep_years`` (D-779, T-305c): on a close only, the years the study's files are kept after it (1 to
        :data:`tb_common.retention.STUDY_YEARS_MAX`); None on a close keeps the default period."""
        from tb_common.retention import STUDY_YEARS_MAX

        if state not in STUDY_STATES:
            raise ValueError(f"state must be one of {', '.join(STUDY_STATES)}")
        if keep_years is not None and (state != "closed" or not 1 <= keep_years <= STUDY_YEARS_MAX):
            raise ValueError(f"only a close keeps the files, for 1 to {STUDY_YEARS_MAX} years")
        rid = ruleset.upper()
        with self.db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"study_state:{rid}",))
            row = tx.fetchone(
                "SELECT state, prev FROM study_state WHERE ruleset = ? ORDER BY at DESC, id DESC LIMIT 1", (rid,)
            )
            prev = str(row[0]) if row is not None else DEFAULT_STATE
            if take_back:
                if prev != "closed" or row is None or str(row[1] or "") != state:
                    raise ValueError(f"a close can only be taken back to the state it left, not to {state}")
            elif not state_move_ok(prev, state):
                raise ValueError(f"a study cannot move from {prev} to {state}")
            tx.execute(
                "INSERT INTO study_state (ruleset, state, prev, reason, by, at, keep_years) VALUES (?,?,?,?,?,?,?)",
                (rid, state, prev, reason, by, at, keep_years),
            )
            new = StudyState(state, reason, by, at, prev, keep_years)
            if before_commit is not None:
                before_commit(new)
        return new

    def begin_study(self, ruleset: str, by: str, at: str,
                    before_commit: Callable[[StudyState], None] | None = None) -> StudyState | None:  # fmt: skip
        """D-386 point 3 (WALK-1, F-14): a new study starts in start-up, so it opens only through the move to open and
        its checks (D-415: the type for SAE reporting). Recorded only when the study has no state yet (under the same
        lock as :meth:`set_study_state`); None when it has one. ``before_commit``: the audit append."""
        rid = ruleset.upper()
        with self.db.transaction() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"study_state:{rid}",))
            if tx.fetchval("SELECT EXISTS (SELECT 1 FROM study_state WHERE ruleset = ?)", (rid,)):
                return None
            reason = "a new study: set up, then opened"
            tx.execute("INSERT INTO study_state (ruleset, state, prev, reason, by, at) VALUES (?,?,?,?,?,?)",
                       (rid, "startup", None, reason, by, at))  # fmt: skip
            new = StudyState("startup", reason, by, at, None, None)
            if before_commit is not None:
                before_commit(new)
        return new

    # ------------------------------------------------------------------ the IRB text's coverage (D-395)
    _IRB_COLS = "covers, approval_ref, text_version, approved_on, note, sentence, by, at"

    @staticmethod
    def _irb_text(row: Any) -> IrbText:
        return IrbText(bool(row[0]), str(row[1]), str(row[2]), str(row[3] or ""), str(row[4]), str(row[5]),
                       str(row[6]), str(row[7]))  # fmt: skip

    def irb_text(self, ruleset: str) -> IrbText:
        """The latest record of the study's IRB-text coverage, or an empty one (nothing recorded: the view is off)."""
        row = self.db.fetchone(
            f"SELECT {self._IRB_COLS} FROM study_irb_text WHERE ruleset = ? ORDER BY at DESC, id DESC LIMIT 1",
            (ruleset.upper(),),
        )
        return IrbText() if row is None else self._irb_text(row)

    def irb_text_history(self, ruleset: str) -> list[IrbText]:
        """Every record, oldest first."""
        rows = self.db.fetchall(
            f"SELECT {self._IRB_COLS} FROM study_irb_text WHERE ruleset = ? ORDER BY at, id", (ruleset.upper(),)
        )
        return [self._irb_text(r) for r in rows]

    def record_irb_text(
        self, ruleset: str, rec: IrbText, by: str, at: str, today: date,
        before_commit: Callable[[IrbText], None] | None = None,
    ) -> IrbText:  # fmt: skip
        """Add a record (the approved text covers the sentence, or no longer does). ValueError naming the wrong
        fields. ``before_commit`` (the audit append) runs inside the transaction, so a failed append keeps nothing."""
        bad = rec.problems(today)
        if bad:
            raise ValueError(", ".join(bad))
        new = IrbText(rec.covers, rec.approval_ref, rec.text_version, rec.approved_on, rec.note, IRB_SENTENCE_ID, by,
                      at)  # fmt: skip
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO study_irb_text (ruleset, covers, sentence, approval_ref, text_version, approved_on, note, "
                "by, at) VALUES (?,?,?,?,?,?,?,?,?)",
                (ruleset.upper(), new.covers, new.sentence, new.approval_ref, new.text_version,
                 new.approved_on or None, new.note, by, at),
            )  # fmt: skip
            if before_commit is not None:
                before_commit(new)
        return new

    def study_identity(self, ruleset: str) -> StudyIdentity:
        row = self.db.fetchone(
            "SELECT sponsor, protocol_no, siv_date, registry_ids, by, at FROM study_identity WHERE ruleset = ?",
            (ruleset.upper(),),
        )
        if row is None:
            return StudyIdentity()
        ids = {str(k): str(v) for k, v in (json.loads(row[3]) or {}).items()}
        return StudyIdentity(str(row[0]), str(row[1]), str(row[2] or ""), ids, str(row[4]), str(row[5]))

    def save_study_identity(self, ruleset: str, ident: StudyIdentity, by: str, at: str) -> StudyIdentity:
        """Store the study's identifiers; ValueError naming the wrong fields when one is malformed."""
        bad = ident.problems()
        if bad:
            raise ValueError(", ".join(bad))
        ids = {r: ident.registry_ids[r] for r in REGISTRIES if ident.registry_ids.get(r)}
        self.db.execute(
            "INSERT INTO study_identity (ruleset, sponsor, protocol_no, siv_date, registry_ids, by, at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT (ruleset) DO UPDATE SET sponsor = excluded.sponsor, "
            "protocol_no = excluded.protocol_no, siv_date = excluded.siv_date, registry_ids = excluded.registry_ids, "
            "by = excluded.by, at = excluded.at",
            (ruleset.upper(), ident.sponsor, ident.protocol_no, ident.siv_date or None,
             json.dumps(ids, sort_keys=True), by, at),
        )  # fmt: skip
        return StudyIdentity(ident.sponsor, ident.protocol_no, ident.siv_date, ids, by, at)
