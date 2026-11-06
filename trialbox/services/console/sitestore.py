"""What the site types into TrialBox and the PI's weekly marks (D-104), kept in the console's own SQLite file.

* **Site profile** per study: the parts of a sponsor feasibility questionnaire the EMR cannot answer — site
  capability checklist, competing trials, sponsor target, screen-failure rate, a comment for the barriers table —
  plus who entered them and when. Printed on the report as "entered by site".
* **PI marks**: Approach / Not suitable (reason) / Need info (what) per patient pseudonym and study. A mark is an
  event, never a registry status: a PI's "not suitable" must not become "screen fail" in the screening log (a CRA
  reads that word literally). The latest mark per patient counts; the history stays.
* **Weekly appearances**: the first week a pseudonym was listed for a study, so the list can say "new this week".

Nothing here holds a chart number or a name.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKS = ("approach", "not_suitable", "need_info")
NOT_SUITABLE_REASONS = ("stage", "partner", "comorbidity", "unlikely", "other")
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
"""


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
        if m.mark not in MARKS:
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
