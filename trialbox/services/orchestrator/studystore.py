"""Study settings store S-28 (TB-DS-07 §4.11), built in step 3: ``<data_dir>/studies.db``.

Holds the per-study settings S21 edits (moved here from the console's site store, D-109), the REDCap connections
S36 sets (base URL and the *name* of each token; the token itself is a 0600 file in the secret store), the project
link per study (``rc_project_link``), what the last read-back found per REDCap record (record id, sponsor subject
number, consent date) and a log of every read. The console edits it only through the orchestrator API.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS study_settings (
  ruleset TEXT PRIMARY KEY,
  study_type TEXT NOT NULL,
  cohort_kind TEXT NOT NULL,
  consent_scope TEXT,
  screening_no_format TEXT NOT NULL DEFAULT '',
  screening_no_next INTEGER NOT NULL DEFAULT 1,
  not_suitable_reasons TEXT NOT NULL,
  introduce_rule TEXT,
  explainer_on INTEGER NOT NULL DEFAULT 0,
  entered_by TEXT NOT NULL,
  entered_at TEXT NOT NULL,
  confirmed_by TEXT,
  confirmed_at TEXT
);
CREATE TABLE IF NOT EXISTS rc_connection (
  token_ref TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  version TEXT,
  project_id INTEGER,
  project_title TEXT,
  checked_at TEXT,
  check_result TEXT,
  set_by TEXT NOT NULL,
  set_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rc_project_link (
  ruleset TEXT PRIMARY KEY,
  body TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  problem TEXT,
  last_read TEXT,
  set_by TEXT NOT NULL,
  set_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rc_record (
  ruleset TEXT NOT NULL,
  record_id TEXT NOT NULL,
  link_value TEXT NOT NULL,
  pid TEXT,
  status TEXT,
  consent_date TEXT,
  subject_no TEXT,
  read_at TEXT NOT NULL,
  PRIMARY KEY (ruleset, record_id)
);
CREATE TABLE IF NOT EXISTS rc_read_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ruleset TEXT NOT NULL,
  at TEXT NOT NULL,
  by TEXT NOT NULL,
  ok INTEGER NOT NULL,
  result TEXT NOT NULL
);
"""
_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class StudyStore:
    def __init__(self, path: Path, secrets_dir: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.secrets_dir = secrets_dir
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(SCHEMA)

    def close(self) -> None:
        self._con.close()

    def _one(self, sql: str, args: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._lock:
            row = self._con.execute(sql, args).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._con.execute(sql, args).fetchall()]

    def _run(self, sql: str, args: tuple[Any, ...]) -> None:
        with self._lock:
            self._con.execute(sql, args)

    # ------------------------------------------------------------------ study_settings (FR-STUDY-07)
    def settings(self, ruleset: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM study_settings WHERE ruleset = ?", (ruleset,))
        if row is None:
            return None
        row["not_suitable_reasons"] = json.loads(row["not_suitable_reasons"])
        row["explainer_on"] = bool(row["explainer_on"])
        return row

    def save_settings(self, ruleset: str, body: dict[str, Any], by: str, at: str) -> dict[str, Any]:
        self._run(
            "INSERT INTO study_settings (ruleset, study_type, cohort_kind, consent_scope, screening_no_format, "
            "screening_no_next, not_suitable_reasons, introduce_rule, explainer_on, entered_by, entered_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ruleset) DO UPDATE SET study_type = excluded.study_type, "
            "cohort_kind = excluded.cohort_kind, consent_scope = excluded.consent_scope, "
            "screening_no_format = excluded.screening_no_format, screening_no_next = excluded.screening_no_next, "
            "not_suitable_reasons = excluded.not_suitable_reasons, introduce_rule = excluded.introduce_rule, "
            "explainer_on = excluded.explainer_on, entered_by = excluded.entered_by, entered_at = excluded.entered_at, "
            "confirmed_by = NULL, confirmed_at = NULL",
            (
                ruleset,
                body["study_type"],
                body["cohort_kind"],
                body.get("consent_scope"),
                body.get("screening_no_format") or "",
                int(body.get("screening_no_next") or 1),
                json.dumps(list(body["not_suitable_reasons"]), ensure_ascii=False),
                body.get("introduce_rule"),
                1 if body.get("explainer_on") else 0,
                by,
                at,
            ),
        )
        out = self.settings(ruleset)
        assert out is not None
        return out

    # ------------------------------------------------------------------ REDCap connections (FR-PLAT-10, S36)
    def token_path(self, token_ref: str) -> Path:
        if not _REF.match(token_ref):
            raise ValueError("a token name is lower-case letters, digits, - and _")
        return self.secrets_dir / "redcap" / token_ref

    def put_token(self, token_ref: str, token: str) -> None:
        p = self.token_path(token_ref)
        p.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(p.parent, 0o700)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(token)
        os.chmod(p, 0o600)

    def token(self, token_ref: str) -> str | None:
        p = self.token_path(token_ref)
        return p.read_text(encoding="ascii").strip() if p.exists() else None

    def connections(self) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM rc_connection ORDER BY token_ref")
        links = self._all("SELECT ruleset, body FROM rc_project_link ORDER BY ruleset")
        for r in rows:
            r["token_set"] = self.token(r["token_ref"]) is not None
            r["token_hint"] = _mask(self.token(r["token_ref"]))
            r["studies"] = [lk["ruleset"] for lk in links if json.loads(lk["body"]).get("token_ref") == r["token_ref"]]
        return rows

    def connection(self, token_ref: str) -> dict[str, Any] | None:
        return next((c for c in self.connections() if c["token_ref"] == token_ref), None)

    def save_connection(self, token_ref: str, url: str, by: str, at: str) -> None:
        self._run(
            "INSERT INTO rc_connection (token_ref, url, set_by, set_at) VALUES (?,?,?,?) ON CONFLICT(token_ref) DO "
            "UPDATE SET url = excluded.url, set_by = excluded.set_by, set_at = excluded.set_at, version = NULL, "
            "project_id = NULL, project_title = NULL, checked_at = NULL, check_result = NULL",
            (token_ref, url, by, at),
        )

    def record_check(self, token_ref: str, at: str, result: str, version: str | None = None,
                     project: dict[str, Any] | None = None) -> None:  # fmt: skip
        self._run(
            "UPDATE rc_connection SET checked_at = ?, check_result = ?, version = COALESCE(?, version), "
            "project_id = COALESCE(?, project_id), project_title = COALESCE(?, project_title) WHERE token_ref = ?",
            (
                at,
                result,
                version,
                int(project["project_id"]) if project else None,
                str(project.get("project_title") or "") if project else None,
                token_ref,
            ),
        )

    # ------------------------------------------------------------------ rc_project_link (FR-RC-16)
    def link(self, ruleset: str) -> dict[str, Any] | None:
        row = self._one("SELECT * FROM rc_project_link WHERE ruleset = ?", (ruleset,))
        if row is None:
            return None
        row["link"] = json.loads(row.pop("body"))
        row["enabled"] = bool(row["enabled"])
        return row

    def links(self) -> list[dict[str, Any]]:
        out = []
        for r in self._all("SELECT ruleset FROM rc_project_link ORDER BY ruleset"):
            lk = self.link(r["ruleset"])
            if lk is not None:
                out.append(lk)
        return out

    def save_link(self, ruleset: str, body: dict[str, Any], enabled: bool, problem: str | None, by: str,
                  at: str) -> None:  # fmt: skip
        self._run(
            "INSERT INTO rc_project_link (ruleset, body, enabled, problem, set_by, set_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(ruleset) DO UPDATE SET body = excluded.body, enabled = excluded.enabled, "
            "problem = excluded.problem, set_by = excluded.set_by, set_at = excluded.set_at, "
            "last_read = CASE WHEN json_extract(rc_project_link.body, '$.project_id') = "
            "json_extract(excluded.body, '$.project_id') THEN rc_project_link.last_read ELSE NULL END",
            (ruleset, json.dumps(body, ensure_ascii=False, sort_keys=True), 1 if enabled else 0, problem, by, at),
        )

    def disable_link(self, ruleset: str, problem: str) -> None:
        self._run("UPDATE rc_project_link SET enabled = 0, problem = ? WHERE ruleset = ?", (problem, ruleset))

    def mark_read(self, ruleset: str, at: str) -> None:
        self._run("UPDATE rc_project_link SET last_read = ?, enabled = 1, problem = NULL WHERE ruleset = ?",
                  (at, ruleset))  # fmt: skip

    # ------------------------------------------------------------------ rc_record and the read log
    def records(self, ruleset: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM rc_record WHERE ruleset = ? ORDER BY record_id", (ruleset,))

    def put_record(self, ruleset: str, rec: dict[str, Any], at: str) -> None:
        self._run(
            "INSERT INTO rc_record (ruleset, record_id, link_value, pid, status, consent_date, subject_no, read_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(ruleset, record_id) DO UPDATE SET link_value = excluded.link_value,"
            " pid = excluded.pid, status = excluded.status, consent_date = excluded.consent_date, "
            "subject_no = excluded.subject_no, read_at = excluded.read_at",
            (
                ruleset,
                rec["record_id"],
                rec["link_value"],
                rec.get("pid"),
                rec.get("status"),
                rec.get("consent_date") or None,
                rec.get("subject_no") or None,
                at,
            ),
        )

    def log_read(self, ruleset: str, at: str, by: str, ok: bool, result: dict[str, Any]) -> None:
        self._run(
            "INSERT INTO rc_read_log (ruleset, at, by, ok, result) VALUES (?,?,?,?,?)",
            (ruleset, at, by, 1 if ok else 0, json.dumps(result, ensure_ascii=False, sort_keys=True)),
        )

    def last_reads(self, ruleset: str, n: int = 5) -> list[dict[str, Any]]:
        rows = self._all("SELECT * FROM rc_read_log WHERE ruleset = ? ORDER BY id DESC LIMIT ?", (ruleset, n))
        for r in rows:
            r["result"] = json.loads(r["result"])
            r["ok"] = bool(r["ok"])
        return rows


def _mask(token: str | None) -> str:
    return f"••••{token[-4:]}" if token else ""
