"""The sponsor's own words (T-302d, D-435): the screening log in the sponsor's columns, and the sponsor's weekly
subject-status sheet read into lifecycle step proposals.

**The layout** is one JSON document per study, kept in ``sponsor_layout`` (datacore version 8): a new row per save,
the newest in force, every earlier one kept. It is checked whole when saved (:func:`check_layout`)::

    {"sponsor": "...",
     "log": [{"from": "screening_no", "heading": "Subject ID"},
             {"from": "status", "heading": "Status", "values": {"screen_fail": "Screen Failed"}},
             {"from": "consent_date", "heading": "ICF Date", "date": "%d-%b-%Y"}],
     "weekly": {"subject": "Subject ID", "status": "Status", "date": "Status Date", "date_format": "%d-%b-%Y",
                "reason": "Reason", "statuses": {"Screen Failed": "screen_fail", "Enrolled": "enrolled"},
                "reasons": {"Not eligible": "not_eligible"}}}

``log`` names TrialBox's screening-log columns (:data:`LOG_COLUMNS`, the site's XLSX header) under the sponsor's
headings, in the sponsor's order; ``weekly`` says how to read the sponsor's sheet. Nothing here writes to a
sponsor's system.

**The weekly sheet** (CSV, at most ``TB_SPONSOR_WEEKLY_MAX_BYTES``, decoded by ``tb_common.encoding.decode``) is
refused whole on any problem: a missing column, a subject that is not a record key, a status or reason word the
layout does not name, a date that does not parse, one subject listed twice with two answers. :func:`proposals`
compares each subject's sponsor status with its lifecycle state: ``same``, ``step`` (a legal next step, taken only
when a person confirms it), ``held`` (with the lifecycle's plain reason) or ``unknown``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from tb_common.encoding import EncodingRefused, decode

from datacore import lifecycle as lc
from datacore.store import DataCore

SCHEMA = """
CREATE TABLE IF NOT EXISTS sponsor_layout (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, study TEXT NOT NULL,
  body TEXT NOT NULL, by_user TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sponsor_layout_study ON sponsor_layout (study, id)
"""
#: the site's screening log columns (the XLSX header, D-387, D-407), in its order
LOG_COLUMNS = (
    "screening_no", "pseudonym", "first_listed", "number_given", "pi_mark", "pi_mark_reason", "pi_mark_date",
    "last_contact_outcome", "contact_attempts", "status", "reason", "status_date", "redcap_record_id", "subject_no",
    "referral_route", "referral_outcome", "referral_reason", "referral_requested", "referral_answered",
    "approach_irb_override", "criteria_version", "criterion_not_met", "consent_date", "consent_form_version",
    "enrolment_date", "randomisation_date",
)  # fmt: skip
DATE_COLUMNS = frozenset({"first_listed", "number_given", "pi_mark_date", "status_date", "referral_requested",
                          "referral_answered", "consent_date", "enrolment_date", "randomisation_date"})  # fmt: skip
#: the date formats a layout may name (never a free strftime text)
DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%d.%m.%Y")
MAX_BYTES_ENV = "TB_SPONSOR_WEEKLY_MAX_BYTES"
MAX_BYTES = 2_000_000
MAX_ROWS = 20_000
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_TEXT = 80  # longest heading or word


class SponsorError(ValueError):
    def __init__(self, code: str, message: str, where: str = "") -> None:
        super().__init__(f"{code}: {message}" + (f" ({where})" if where else ""))
        self.code = code
        self.message = message
        self.where = where


def _words(x: Any, where: str) -> str:
    if not isinstance(x, str) or not x.strip() or len(x) > _TEXT:
        raise SponsorError("sponsor.layout", f"a non-empty text of at most {_TEXT} characters is needed", where)
    return x.strip()


def check_layout(body: Any) -> dict[str, Any]:
    """The layout, checked and normalised, or :class:`SponsorError` naming the first problem."""
    if not isinstance(body, dict):
        raise SponsorError("sponsor.layout", "the layout is a JSON object")
    out: dict[str, Any] = {"sponsor": _words(body.get("sponsor") or "sponsor", "sponsor")}
    log = body.get("log") or []
    if not isinstance(log, list) or len(log) > len(LOG_COLUMNS) * 2:
        raise SponsorError("sponsor.layout", "log is a list of columns", "log")
    cols, heads = [], set()
    for i, c in enumerate(log):
        where = f"log[{i}]"
        if not isinstance(c, dict):
            raise SponsorError("sponsor.layout", "a column is an object", where)
        src = c.get("from")
        if src not in LOG_COLUMNS:
            raise SponsorError("sponsor.column", f"{str(src)[:40]!r} is not a screening-log column", where)
        head = _words(c.get("heading"), where)
        if head in heads:
            raise SponsorError("sponsor.layout", f"the heading {head!r} is named twice", where)
        heads.add(head)
        col: dict[str, Any] = {"from": src, "heading": head}
        vals = c.get("values") or {}
        if not isinstance(vals, dict):
            raise SponsorError("sponsor.layout", "values maps TrialBox words to the sponsor's", where)
        if vals:
            col["values"] = {_words(k, where): _words(v, where) for k, v in vals.items()}
        if c.get("date"):
            if src not in DATE_COLUMNS or c["date"] not in DATE_FORMATS:
                raise SponsorError("sponsor.date_format", f"a date format of {', '.join(DATE_FORMATS)} on a date "
                                   "column", where)  # fmt: skip
            col["date"] = c["date"]
        cols.append(col)
    out["log"] = cols
    wk = body.get("weekly")
    if wk is not None:
        if not isinstance(wk, dict):
            raise SponsorError("sponsor.layout", "weekly is an object", "weekly")
        w: dict[str, Any] = {k: _words(wk.get(k), f"weekly.{k}") for k in ("subject", "status", "date")}
        if wk.get("reason"):
            w["reason"] = _words(wk["reason"], "weekly.reason")
        fmt = wk.get("date_format") or "%Y-%m-%d"
        if fmt not in DATE_FORMATS:
            raise SponsorError("sponsor.date_format", f"a date format of {', '.join(DATE_FORMATS)}", "weekly")
        w["date_format"] = fmt
        st = wk.get("statuses") or {}
        if not isinstance(st, dict) or not st:
            raise SponsorError("sponsor.layout", "statuses maps the sponsor's words to lifecycle states", "weekly")
        for k, v in st.items():
            if v not in lc.STATES:
                raise SponsorError("sponsor.state", f"{str(v)[:40]!r} is not a lifecycle state", f"weekly.{k}"[:80])
        w["statuses"] = {_words(k, "weekly.statuses"): str(v) for k, v in st.items()}
        rs = wk.get("reasons") or {}
        if not isinstance(rs, dict):
            raise SponsorError("sponsor.layout", "reasons maps the sponsor's words to TrialBox's codes", "weekly")
        for k, v in rs.items():
            if v not in (*lc.SCREEN_FAIL_REASONS, *lc.WITHDRAW_REASONS):
                raise SponsorError("sponsor.reason", f"{str(v)[:40]!r} is not a screen-failure or withdrawal "
                                   "reason", f"weekly.{k}"[:80])  # fmt: skip
        w["reasons"] = {_words(k, "weekly.reasons"): str(v) for k, v in rs.items()}
        out["weekly"] = w
    return out


class Layouts:
    """The study's sponsor layouts in the data core (version 8): append-only by this code."""

    def __init__(self, dc: DataCore) -> None:
        self.db = dc.db

    def put(self, study: str, body: Any, by: str, at: str) -> dict[str, Any]:
        lay = check_layout(body)
        self.db.execute("INSERT INTO sponsor_layout (study, body, by_user, at) VALUES (?,?,?,?)",
                        (study, json.dumps(lay, ensure_ascii=False, sort_keys=True), by, at))  # fmt: skip
        cur = self.get(study)
        assert cur is not None
        return cur

    def get(self, study: str) -> dict[str, Any] | None:
        rows = self.db.fetchdicts("SELECT * FROM sponsor_layout WHERE study = ? ORDER BY id DESC LIMIT 1", (study,))
        if not rows:
            return None
        r = rows[0]
        return {"id": int(r["id"]), "layout": json.loads(r["body"]), "by": r["by_user"], "at": r["at"]}

    def history(self, study: str) -> list[dict[str, Any]]:
        return self.db.fetchdicts("SELECT id, by_user, at FROM sponsor_layout WHERE study = ? ORDER BY id", (study,))


# ------------------------------------------------------------------ the screening log in the sponsor's columns
def _date_in(value: str, fmt: str) -> str:
    try:
        return date.fromisoformat(value[:10]).strftime(fmt)
    except ValueError:
        return value


def log_table(layout: Mapping[str, Any], rows: Sequence[Sequence[Any]]) -> tuple[list[str], list[list[Any]]]:
    """``rows`` in :data:`LOG_COLUMNS` order -> the sponsor's headings and its rows (only the columns it names)."""
    cols = list(layout.get("log") or [])
    if not cols:
        raise SponsorError("sponsor.no_log", "the sponsor layout names no screening-log column")
    at = {c: i for i, c in enumerate(LOG_COLUMNS)}
    out: list[list[Any]] = []
    for r in rows:
        line: list[Any] = []
        for c in cols:
            v = r[at[c["from"]]]
            if isinstance(v, str) and v in (c.get("values") or {}):
                v = c["values"][v]
            elif isinstance(v, str) and v and c.get("date"):
                v = _date_in(v, c["date"])
            line.append(v)
        out.append(line)
    return [str(c["heading"]) for c in cols], out


# ------------------------------------------------------------------ the weekly sheet
@dataclass(frozen=True)
class WeeklyRow:
    record: str
    state: str
    day: str  # ISO date
    reason: str  # TrialBox's code, or ""
    line: int


def max_bytes(env: Mapping[str, str] | None = None) -> int:
    raw = str((os.environ if env is None else env).get(MAX_BYTES_ENV) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else MAX_BYTES


def read_weekly(data: bytes, layout: Mapping[str, Any],
                env: Mapping[str, str] | None = None) -> tuple[str, list[WeeklyRow]]:  # fmt: skip
    """``(sha256, rows)`` of the sponsor's weekly sheet, or :class:`SponsorError` (the sheet refused whole)."""
    wk = layout.get("weekly")
    if not wk:
        raise SponsorError("sponsor.no_weekly", "the sponsor layout does not say how to read the weekly sheet")
    limit = max_bytes(env)
    if len(data) > limit:
        raise SponsorError("sponsor.size", f"the sheet is larger than {limit} bytes")
    try:
        text, _ = decode(data)
    except EncodingRefused as exc:
        raise SponsorError("sponsor.encoding", exc.message, f"line {exc.line}" if exc.line else "") from exc
    sample = text[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    heads = [h.strip() for h in reader.fieldnames or []]
    reader.fieldnames = heads
    need = [wk["subject"], wk["status"], wk["date"], *([wk["reason"]] if wk.get("reason") else [])]
    missing = [h for h in need if h not in heads]
    if missing:
        raise SponsorError("sponsor.columns", "the sheet has no column " + ", ".join(repr(m) for m in missing))
    seen: dict[str, WeeklyRow] = {}
    out: list[WeeklyRow] = []
    for n, r in enumerate(reader, start=2):
        if n > MAX_ROWS + 1:
            raise SponsorError("sponsor.size", f"more than {MAX_ROWS} rows")
        rec = str(r.get(wk["subject"]) or "").strip().upper()
        if not rec and not any(str(v or "").strip() for v in r.values()):
            continue  # a blank line
        if not _REC.match(rec):
            raise SponsorError("sponsor.subject", f"{rec[:40]!r} is not a screening number", f"line {n}")
        word = str(r.get(wk["status"]) or "").strip()
        if word not in wk["statuses"]:
            raise SponsorError("sponsor.status", f"the status {word[:40]!r} is not in the layout", f"line {n}")
        raw = str(r.get(wk["date"]) or "").strip()
        try:
            day = datetime.strptime(raw, wk["date_format"]).date().isoformat()
        except ValueError:
            raise SponsorError("sponsor.date", f"{raw[:20]!r} is not a date in {wk['date_format']}",
                               f"line {n}") from None  # fmt: skip
        why = str(r.get(wk["reason"]) or "").strip() if wk.get("reason") else ""
        if why and why not in wk["reasons"]:
            raise SponsorError("sponsor.reason", f"the reason {why[:40]!r} is not in the layout", f"line {n}")
        row = WeeklyRow(rec, wk["statuses"][word], day, wk["reasons"].get(why, ""), n)
        prev = seen.get(rec)
        if prev is not None:
            if (prev.state, prev.day, prev.reason) != (row.state, row.day, row.reason):
                raise SponsorError("sponsor.duplicate", f"{rec} is listed twice with two answers", f"line {n}")
            continue
        seen[rec] = row
        out.append(row)
    return hashlib.sha256(data).hexdigest(), out


def proposals(dc: DataCore, study: str, rows: Sequence[WeeklyRow], today: date) -> list[dict[str, Any]]:
    """Per subject of the sheet: ``same``, ``step`` (a legal next step), ``held`` (``why``: the lifecycle's plain
    reason) or ``unknown``. Nothing is written."""
    life = lc.Lifecycle(dc)
    out: list[dict[str, Any]] = []
    for r in rows:
        p: dict[str, Any] = {"record": r.record, "to": r.state, "on_day": r.day, "reason": r.reason, "line": r.line}
        sub = life.subject(study, r.record)
        if sub is None:
            out.append({**p, "kind": "unknown", "why": "none"})
            continue
        state = str(sub["state"])
        p["state"] = state
        if state == r.state:
            out.append({**p, "kind": "same"})
            continue
        why = lc.can_step(state, r.state)
        if why is None and r.state == "screen_fail" and r.reason not in lc.SCREEN_FAIL_REASONS:
            why = "reason"
        if why is None and r.state == "withdrawn" and r.reason not in lc.WITHDRAW_REASONS:
            why = "reason"
        if why is None and date.fromisoformat(r.day) > today:
            why = "future"
        out.append({**p, "kind": "held" if why else "step", **({"why": why} if why else {})})
    return out


def confirm(dc: DataCore, study: str, sha: str, rows: Sequence[WeeklyRow], record: str, *, by: str, at: str,
            today: date) -> dict[str, Any]:  # fmt: skip
    """A person confirms one ``step`` proposal of the sheet: the lifecycle step, its source ``sponsor_weekly`` and
    the sheet's sha256 in its note. Anything but a ``step`` proposal is refused (``LifeError``)."""
    p = next((x for x in proposals(dc, study, rows, today) if x["record"] == record), None)
    if p is None:
        raise lc.LifeError("none", "this subject is not on the sponsor's sheet")
    if p["kind"] != "step":
        raise lc.LifeError(str(p.get("why") or p["kind"]), f"the sheet proposes no step for {record} ({p['kind']})")
    return lc.Lifecycle(dc).step(study, record, p["to"], by=by, at=at, on_day=p["on_day"], reason=p["reason"],
                                 note=f"sponsor weekly sheet {sha[:16]}", source="sponsor_weekly",
                                 today=today)  # fmt: skip
