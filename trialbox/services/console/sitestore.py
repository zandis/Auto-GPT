"""What the site types into TrialBox and the PI's weekly marks (D-104), kept in the console's own SQLite file.

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

Nothing here holds a chart number or a name.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_profile (
  ruleset TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  entered_by TEXT NOT NULL,
  entered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pi_marks (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  mark TEXT NOT NULL,
  reason TEXT,
  note TEXT,
  by TEXT NOT NULL,
  at TEXT NOT NULL,
  job_id TEXT
);
CREATE INDEX IF NOT EXISTS pi_marks_rs ON pi_marks (ruleset, pid, at);
CREATE TABLE IF NOT EXISTS weekly_seen (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  first_job TEXT NOT NULL,
  first_at TEXT NOT NULL,
  PRIMARY KEY (ruleset, pid)
);
CREATE TABLE IF NOT EXISTS study_settings (
  ruleset TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS screening_no (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  seq INTEGER NOT NULL,
  no TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (ruleset, pid),
  UNIQUE (ruleset, seq)
);
CREATE TABLE IF NOT EXISTS contact_outcomes (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  outcome TEXT NOT NULL,
  retry TEXT,
  note TEXT,
  by TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS contact_outcomes_rs ON contact_outcomes (ruleset, pid, at);
CREATE TABLE IF NOT EXISTS approval_opened (
  job_id TEXT NOT NULL,
  crit TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (job_id, crit, by)
);
CREATE TABLE IF NOT EXISTS criterion_labels (
  ruleset TEXT NOT NULL,
  crit TEXT NOT NULL,
  lang TEXT NOT NULL,
  label TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (ruleset, crit, lang)
);
CREATE TABLE IF NOT EXISTS code_ticks (
  job_id TEXT NOT NULL,
  crit TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (job_id, crit)
);
CREATE TABLE IF NOT EXISTS notify_people (
  username TEXT PRIMARY KEY,
  practitioner_id TEXT,
  digest_time TEXT NOT NULL DEFAULT '07:30',
  enabled INTEGER NOT NULL DEFAULT 1,
  lang TEXT NOT NULL DEFAULT 'en'
);
CREATE TABLE IF NOT EXISTS notify_log (
  kind TEXT NOT NULL,
  username TEXT NOT NULL,
  day TEXT NOT NULL,
  at TEXT NOT NULL,
  subject TEXT NOT NULL,
  PRIMARY KEY (kind, username, day)
);
"""


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


class SiteStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(SCHEMA)

    # ------------------------------------------------------------------ site profile
    def profile(self, ruleset: str) -> SiteProfile:
        with self._lock:
            row = self._con.execute(
                "SELECT body, entered_by, entered_at FROM site_profile WHERE ruleset = ?", (ruleset,)
            ).fetchone()
        if row is None:
            return SiteProfile()
        body = json.loads(row[0])
        return SiteProfile(**body, entered_by=row[1], entered_at=row[2])

    def save_profile(self, ruleset: str, prof: SiteProfile, by: str, at: str) -> SiteProfile:
        body = json.dumps(prof.as_dict(), ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._con.execute(
                "INSERT INTO site_profile (ruleset, body, entered_by, entered_at) VALUES (?,?,?,?) "
                "ON CONFLICT(ruleset) DO UPDATE SET body = excluded.body, entered_by = excluded.entered_by, "
                "entered_at = excluded.entered_at",
                (ruleset, body, by, at),
            )
        prof.entered_by, prof.entered_at = by, at
        return prof

    # ------------------------------------------------------------------ PI marks
    def mark(self, ruleset: str, m: Mark) -> None:
        if m.mark not in (*MARKS, WITHDRAWN):
            raise ValueError(f"mark must be one of {', '.join(MARKS)}")
        with self._lock:
            self._con.execute(
                "INSERT INTO pi_marks (ruleset, pid, mark, reason, note, by, at, job_id) VALUES (?,?,?,?,?,?,?,?)",
                (ruleset, m.pid, m.mark, m.reason, m.note, m.by, m.at, m.job_id),
            )

    def latest_marks(self, ruleset: str) -> dict[str, Mark]:
        with self._lock:
            rows = self._con.execute(
                "SELECT pid, mark, reason, note, by, at, job_id FROM pi_marks WHERE ruleset = ? ORDER BY at, rowid",
                (ruleset,),
            ).fetchall()
        out: dict[str, Mark] = {}
        for r in rows:
            if r[1] == WITHDRAWN:  # the PI took the mark back: no current mark, the history keeps both events
                out.pop(str(r[0]), None)
            else:
                out[str(r[0])] = Mark(*r)
        return out

    def mark_history(self, ruleset: str, pid: str) -> list[Mark]:
        with self._lock:
            rows = self._con.execute(
                "SELECT pid, mark, reason, note, by, at, job_id FROM pi_marks WHERE ruleset = ? AND pid = ? "
                "ORDER BY at, rowid",
                (ruleset, pid),
            ).fetchall()
        return [Mark(*r) for r in rows]

    # ------------------------------------------------------------------ weekly appearances
    def seen(self, ruleset: str, pids: list[str], job_id: str, at: str) -> dict[str, str]:
        """Record first appearances of ``pids`` on a list for ``ruleset``; return pid -> job id of first listing."""
        with self._lock:
            for pid in pids:
                self._con.execute(
                    "INSERT OR IGNORE INTO weekly_seen (ruleset, pid, first_job, first_at) VALUES (?,?,?,?)",
                    (ruleset, pid, job_id, at),
                )
            rows = self._con.execute("SELECT pid, first_job FROM weekly_seen WHERE ruleset = ?", (ruleset,)).fetchall()
        return {str(p): str(j) for p, j in rows}

    def first_seen(self, ruleset: str) -> dict[str, tuple[str, str]]:
        """pid -> (first job, first time) a pseudonym was listed for ``ruleset``."""
        with self._lock:
            rows = self._con.execute(
                "SELECT pid, first_job, first_at FROM weekly_seen WHERE ruleset = ?", (ruleset,)
            ).fetchall()
        return {str(p): (str(j), str(a)) for p, j, a in rows}

    def screening_rows(self, ruleset: str) -> list[tuple[str, str, str]]:
        """(pid, screening number, assigned at), in number order."""
        with self._lock:
            rows = self._con.execute(
                "SELECT pid, no, at FROM screening_no WHERE ruleset = ? ORDER BY seq", (ruleset,)
            ).fetchall()
        return [(str(p), str(n), str(a)) for p, n, a in rows]

    def all_marks(self, ruleset: str) -> list[Mark]:
        with self._lock:
            rows = self._con.execute(
                "SELECT pid, mark, reason, note, by, at, job_id FROM pi_marks WHERE ruleset = ? ORDER BY at, rowid",
                (ruleset,),
            ).fetchall()
        return [Mark(*r) for r in rows]

    # ------------------------------------------------------------------ study settings (D-108)
    def study_settings(self, ruleset: str, default: StudySettings | None = None) -> StudySettings:
        with self._lock:
            row = self._con.execute("SELECT body FROM study_settings WHERE ruleset = ?", (ruleset,)).fetchone()
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
        with self._lock:
            self._con.execute(
                "INSERT INTO study_settings (ruleset, body, by, at) VALUES (?,?,?,?) ON CONFLICT(ruleset) DO UPDATE "
                "SET body = excluded.body, by = excluded.by, at = excluded.at",
                (ruleset, body, by, at),
            )

    # ------------------------------------------------------------------ screening numbers (FR-STUDY-08, BD-18)
    def screening_no(self, ruleset: str, pid: str) -> str | None:
        with self._lock:
            row = self._con.execute(
                "SELECT no FROM screening_no WHERE ruleset = ? AND pid = ?", (ruleset, pid)
            ).fetchone()
        return str(row[0]) if row else None

    def screening_nos(self, ruleset: str) -> dict[str, str]:
        with self._lock:
            rows = self._con.execute("SELECT pid, no FROM screening_no WHERE ruleset = ?", (ruleset,)).fetchall()
        return {str(p): str(n) for p, n in rows}

    def assign_screening_no(self, ruleset: str, pid: str, settings: StudySettings, at: str) -> str:
        """The study's next screening number for ``pid``; an existing number is kept (never re-used, never moved)."""
        with self._lock:
            row = self._con.execute(
                "SELECT no FROM screening_no WHERE ruleset = ? AND pid = ?", (ruleset, pid)
            ).fetchone()
            if row is not None:
                return str(row[0])
            top = self._con.execute("SELECT MAX(seq) FROM screening_no WHERE ruleset = ?", (ruleset,)).fetchone()[0]
            seq = max(int(top or 0) + 1, settings.first_no)
            prefix = settings.screening_prefix or f"{ruleset}-"
            no = f"{prefix}{seq:04d}"
            self._con.execute(
                "INSERT INTO screening_no (ruleset, pid, seq, no, at) VALUES (?,?,?,?,?)", (ruleset, pid, seq, no, at)
            )
        return no

    # ------------------------------------------------------------------ contact outcomes (FR-SCR-10c)
    def add_outcome(self, ruleset: str, o: Outcome) -> None:
        if o.outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
        with self._lock:
            self._con.execute(
                "INSERT INTO contact_outcomes (ruleset, pid, outcome, retry, note, by, at) VALUES (?,?,?,?,?,?,?)",
                (ruleset, o.pid, o.outcome, o.retry, o.note, o.by, o.at),
            )

    def outcomes(self, ruleset: str, pid: str | None = None) -> list[Outcome]:
        q = "SELECT pid, outcome, retry, note, by, at FROM contact_outcomes WHERE ruleset = ?"
        args: tuple[str, ...] = (ruleset,)
        if pid is not None:
            q, args = q + " AND pid = ?", (ruleset, pid)
        with self._lock:
            rows = self._con.execute(q + " ORDER BY at, rowid", args).fetchall()
        return [Outcome(*r) for r in rows]

    # ------------------------------------------------------------------ approval page (FR-FEAS-12a/d)
    def open_row(self, job_id: str, crit: str, by: str, at: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR IGNORE INTO approval_opened (job_id, crit, by, at) VALUES (?,?,?,?)", (job_id, crit, by, at)
            )

    def opened_rows(self, job_id: str, by: str) -> set[str]:
        with self._lock:
            rows = self._con.execute(
                "SELECT crit FROM approval_opened WHERE job_id = ? AND by = ?", (job_id, by)
            ).fetchall()
        return {str(r[0]) for r in rows}

    def tick_codes(self, job_id: str, crit: str, by: str, at: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO code_ticks (job_id, crit, by, at) VALUES (?,?,?,?)", (job_id, crit, by, at)
            )

    # ------------------------------------------------------------------ criterion labels in the site language (D-120)
    def save_label(self, ruleset: str, crit: str, lang: str, label: str, by: str, at: str) -> None:
        with self._lock:
            if label:
                self._con.execute(
                    "INSERT OR REPLACE INTO criterion_labels (ruleset, crit, lang, label, by, at) VALUES (?,?,?,?,?,?)",
                    (ruleset.upper(), crit, lang, label, by, at),
                )
            else:
                self._con.execute(
                    "DELETE FROM criterion_labels WHERE ruleset = ? AND crit = ? AND lang = ?",
                    (ruleset.upper(), crit, lang),
                )

    def labels(self, ruleset: str, lang: str) -> dict[str, str]:
        with self._lock:
            rows = self._con.execute(
                "SELECT crit, label FROM criterion_labels WHERE ruleset = ? AND lang = ?", (ruleset.upper(), lang)
            ).fetchall()
        return {str(c): str(v) for c, v in rows}

    def code_ticks(self, job_id: str) -> dict[str, tuple[str, str]]:
        with self._lock:
            rows = self._con.execute("SELECT crit, by, at FROM code_ticks WHERE job_id = ?", (job_id,)).fetchall()
        return {str(c): (str(b), str(a)) for c, b, a in rows}

    # ------------------------------------------------------------------ notices (FR-NOTIF-01/02)
    def notify_person(self, username: str) -> NotifyPerson:
        with self._lock:
            row = self._con.execute(
                "SELECT username, practitioner_id, digest_time, enabled, lang FROM notify_people WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return NotifyPerson(username, None)
        return NotifyPerson(str(row[0]), row[1], str(row[2]), bool(row[3]), str(row[4]))

    def save_notify_person(self, p: NotifyPerson) -> None:
        with self._lock:
            self._con.execute(
                "INSERT INTO notify_people (username, practitioner_id, digest_time, enabled, lang) VALUES (?,?,?,?,?) "
                "ON CONFLICT(username) DO UPDATE SET practitioner_id = excluded.practitioner_id, "
                "digest_time = excluded.digest_time, enabled = excluded.enabled, lang = excluded.lang",
                (p.username, p.practitioner_id, p.digest_time, int(p.enabled), p.lang),
            )

    def notice_sent(self, kind: str, username: str, day: str) -> bool:
        with self._lock:
            row = self._con.execute(
                "SELECT 1 FROM notify_log WHERE kind = ? AND username = ? AND day = ?", (kind, username, day)
            ).fetchone()
        return row is not None

    def last_notice(self, kind: str, username: str) -> str | None:
        with self._lock:
            row = self._con.execute(
                "SELECT MAX(at) FROM notify_log WHERE kind = ? AND username = ?", (kind, username)
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def log_notice(self, kind: str, username: str, day: str, at: str, subject: str) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO notify_log (kind, username, day, at, subject) VALUES (?,?,?,?,?)",
                (kind, username, day, at, subject),
            )

    def notices_for(self, username: str, limit: int = 50) -> list[tuple[str, str, str, str]]:
        """S37 Notices received (step 4, FR-PLAT-17): (kind, day, at, subject) of one person, newest first."""
        with self._lock:
            rows = self._con.execute(
                "SELECT kind, day, at, subject FROM notify_log WHERE username = ? ORDER BY at DESC LIMIT ?",
                (username, limit),
            ).fetchall()
        return [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]
