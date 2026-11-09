"""The SAE register (D-191, independent plan review PR-17): TrialBox's one record of each serious adverse event.

**One place per fact.** A serious AE is entered once, on the AE form of the data core (D-134, D-143): onset
(``ae_onset``), the day the site learned of it (``ae_aware``), seriousness and outcome, and the day each initial report
was sent (``ae_rep_sponsor``, ``ae_rep_irb``, ``ae_rep_reg``). The register never keeps a second copy of those: it
reads them, and "report sent" on the worklist writes the date to the AE form. The deadlines come from the one clock,
:func:`datacore.lifecycle.report_clock` with the rules ``TB_SAE_RULES`` / ``TB_SAE_REPORT_DAYS`` (the orchestrator
computes them for the site's local date). The register adds what the AE form does not hold:

* the case itself: when TrialBox first saw it, who, and the deadlines it last saw (so a changed date that moves a
  deadline is visible);
* the receiver's acknowledgement of each report (the sponsor's, the IRB's or the regulator's receipt, its day and
  reference);
* follow-up reports: the rule's follow-up (ICH E2A: a fatal or life-threatening case's complete report 8 days after
  the first report to the regulator; ``TB_SAE_FOLLOWUP_DAYS``, same form as ``TB_SAE_REPORT_DAYS``) and any
  follow-up a receiver asks for by a date;
* the trail: every create and change, with old and new dates, who and when (``sae_trail``), and the same in the audit
  log (``console.sae``).

**No patient text.** The register and the trail keep the study, the screening number (``record``), the AE event
(``ae1`` ...), the pseudonym, dates, parties and short references. Never the AE term, a chart number or a name.

**Time.** Dates are the site's calendar dates (``site.tz``: Asia/Tokyo, Asia/Taipei; neither has daylight saving).
"Today" is the site's date at the server's clock, so a server on UTC never counts a Tokyo deadline a day late.
Deadlines are calendar days: a weekend or a public holiday neither extends nor shortens one (J-GCP's 直ちに and the
Taiwanese IRB SOPs count calendar days); the worklist says so.

Stored in the trial database (PostgreSQL ``trialbox_wf``, schema ``sae``; D-126).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from datacore import lifecycle as lc

from console.storedb import open_db

PARTIES = lc.REPORT_PARTIES  # sponsor, irb, regulator
KINDS = ("initial", "followup")
ORIGINS = ("rule", "request")
# ICH E2A: a fatal or life-threatening case is reported within 7 days and completed within 8 more. Only the regulator
# by default; 0 = no follow-up clock for that party. ``TB_SAE_FOLLOWUP_DAYS`` overrides (``regulator=8,sponsor=0``).
FOLLOWUP_RULES: dict[str, tuple[int, int]] = {"sponsor": (0, 0), "irb": (0, 0), "regulator": (8, 0)}
REF_MAX = 60  # a receiver's reference number, never free text about the patient

SCHEMA_V1 = """
CREATE TABLE sae_case (
  ruleset TEXT NOT NULL,
  record TEXT NOT NULL,
  event TEXT NOT NULL,
  pid TEXT NOT NULL DEFAULT '',
  onset TEXT,
  aware TEXT,
  grave INTEGER NOT NULL,
  serious INTEGER NOT NULL,
  clock TEXT NOT NULL DEFAULT '{}',
  pi_ack_by TEXT,
  pi_ack_at TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  updated_at TEXT COLLATE "C" NOT NULL,
  PRIMARY KEY (ruleset, record, event)
);
CREATE TABLE sae_report (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  record TEXT NOT NULL,
  event TEXT NOT NULL,
  party TEXT NOT NULL,
  kind TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT 'rule',
  due TEXT,
  sent_on TEXT,
  ref TEXT,
  receipt_on TEXT,
  receipt_ref TEXT,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX sae_report_case ON sae_report (ruleset, record, event);
CREATE TABLE sae_trail (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  record TEXT NOT NULL,
  event TEXT NOT NULL,
  action TEXT NOT NULL,
  body TEXT NOT NULL,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX sae_trail_case ON sae_trail (ruleset, record, event, at)
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1,)


class SaeError(ValueError):
    """A refused register entry. ``why`` is a key under ``sae.why.`` in the console's catalogues."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


# ---------------------------------------------------------------------------------------------- the clock, reused
def day_of(text: object) -> date | None:
    try:
        return date.fromisoformat(str(text or "")[:10])
    except ValueError:
        return None


def followup_rules(override: str = "") -> dict[str, tuple[int, int]]:
    """The follow-up days per party (fatal or life-threatening / other) after the first report to that party was
    sent: :data:`FOLLOWUP_RULES`, then ``override`` in ``TB_SAE_REPORT_DAYS``'s form."""
    out = dict(FOLLOWUP_RULES)
    for part in (override or "").split(","):
        key, _, val = part.partition("=")
        key, val = key.strip().lower(), val.strip()
        if key not in PARTIES or not val:
            continue
        a, _, b = val.partition("/")
        try:
            out[key] = (max(0, int(a)), max(0, int(b or a)))
        except ValueError:
            continue
    return out


def rule_followups(ae: dict[str, Any], today: date, rules: dict[str, tuple[int, int]],
                   sent: dict[str, str]) -> list[dict[str, Any]]:  # fmt: skip
    """The rule's follow-up per party, on the same clock as the first report (:func:`lc.report_clock`): it starts the
    day the first report to that party was sent (the AE form's date) and is done when ``sent[party]`` holds a day."""
    out: list[dict[str, Any]] = []
    for c in ae.get("clock") or []:
        party, first = str(c.get("party")), str(c.get("done") or "")
        if party not in PARTIES or not day_of(first):
            continue
        e = {"ae_serious": "1", "ae_outcome": ae.get("ae_outcome", ""), "ae_serious_why": ae.get("ae_serious_why", ""),
             "ae_aware": first, lc.REPORT_FIELDS[party]: sent.get(party, "")}  # fmt: skip
        out += [{**f, "origin": "rule"} for f in lc.report_clock(e, today, {party: rules.get(party, (0, 0))})]
    return out


def state_of(due: str, done: str, today: date) -> str:
    """One report's state on the site's ``today``: sent, overdue, due_today, open, or nostart (no start date)."""
    if done:
        return "sent"
    d = day_of(due)
    if d is None:
        return "nostart"
    if today > d:
        return "overdue"
    return "due_today" if today == d else "open"


def flags_of(ae: dict[str, Any]) -> list[str]:
    """Checks on the dates the clock starts from (shown on the worklist, never silently fixed):

    * ``nostart``: neither the onset nor the day learned: no deadline can be counted; an alert, not a quiet row.
    * ``aware_missing``: no day learned: the clock counts from the onset (the earlier day, so never later than due).
    * ``aware_before_onset``: the site cannot learn of an event before it happens; the clock counts from the day
      learned, the earlier and stricter day, until someone corrects the form.
    * ``late_aware``: learned after a deadline counted from the onset would have passed; the clock counts from the
      day learned (ICH E2A day 0), and the report may need the reason for the delay.
    """
    onset, aware = day_of(ae.get("ae_onset")), day_of(ae.get("ae_aware"))
    out: list[str] = []
    if onset is None and aware is None:
        return ["nostart"]
    if aware is None:
        out.append("aware_missing")
    elif onset is not None and aware < onset:
        out.append("aware_before_onset")
    elif onset is not None:
        days = [int(c.get("days") or 0) for c in ae.get("clock") or [] if int(c.get("days") or 0) > 0]
        if days and aware > onset + timedelta(days=min(days)):
            out.append("late_aware")
    return out


def due_map(ae: dict[str, Any]) -> dict[str, str]:
    return {str(c["party"]): str(c.get("due") or "") for c in ae.get("clock") or []}


def sent_map(ae: dict[str, Any]) -> dict[str, str]:
    return {str(c["party"]): str(c.get("done") or "") for c in ae.get("clock") or []}


# ---------------------------------------------------------------------------------------------- the store
class SaeStore:
    """Schema ``sae`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = open_db(url, "sae", MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ reads
    def case(self, rs: str, record: str, event: str) -> dict[str, Any] | None:
        rows = self.db.fetchdicts("SELECT * FROM sae_case WHERE ruleset = ? AND record = ? AND event = ?",
                                  (rs, record, event))  # fmt: skip
        return _case(rows[0]) if rows else None

    def cases(self, rs: str) -> list[dict[str, Any]]:
        rows = self.db.fetchdicts("SELECT * FROM sae_case WHERE ruleset = ? ORDER BY record, event", (rs,))
        return [_case(r) for r in rows]

    def reports(self, rs: str, record: str, event: str) -> list[dict[str, Any]]:
        return self.db.fetchdicts(
            "SELECT * FROM sae_report WHERE ruleset = ? AND record = ? AND event = ? ORDER BY id", (rs, record, event)
        )

    def report(self, rs: str, rid: int) -> dict[str, Any] | None:
        rows = self.db.fetchdicts("SELECT * FROM sae_report WHERE ruleset = ? AND id = ?", (rs, rid))
        return rows[0] if rows else None

    def trail(self, rs: str, record: str, event: str) -> list[dict[str, Any]]:
        rows = self.db.fetchdicts(
            "SELECT action, body, by, at FROM sae_trail WHERE ruleset = ? AND record = ? AND event = ? ORDER BY id",
            (rs, record, event),
        )
        return [{**r, "body": json.loads(r["body"])} for r in rows]

    # ------------------------------------------------------------------ writes (each one also a trail row)
    def _trail(self, tx: Any, rs: str, record: str, event: str, action: str, body: dict[str, Any], by: str,
               at: str) -> None:  # fmt: skip
        tx.execute("INSERT INTO sae_trail (ruleset, record, event, action, body, by, at) VALUES (?,?,?,?,?,?,?)",
                   (rs, record, event, action, json.dumps(body, sort_keys=True), by, at))  # fmt: skip

    def sync(self, rs: str, ae: dict[str, Any], by: str, at: str) -> list[dict[str, Any]]:
        """Bring the case of one AE (as the orchestrator's ``/aes`` gives it, with its clock) up to date. Returns the
        trail rows written (``create``, ``change``, ``report``, ``ack``), empty when nothing changed."""
        record, event = str(ae["record"]), str(ae["event"])
        serious = 1 if ae.get("serious") or ae.get("ae_serious") == "1" else 0
        new: dict[str, Any] = {"onset": str(ae.get("ae_onset") or ""), "aware": str(ae.get("ae_aware") or ""),
               "grave": 1 if lc.grave(ae) else 0, "serious": serious, "due": due_map(ae)}  # fmt: skip
        sent = sent_map(ae)
        ack_by, ack_at = str(ae.get("ack_by") or ""), str(ae.get("ack_at") or "")
        old = self.case(rs, record, event)
        written: list[dict[str, Any]] = []
        if old is None and not serious:
            return written
        with self.db.transaction() as tx:
            if old is None:
                rc = tx.execute(
                    "INSERT INTO sae_case (ruleset, record, event, pid, onset, aware, grave, serious, clock, pi_ack_by,"
                    " pi_ack_at, created_by, created_at, updated_by, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (ruleset, record, event) DO NOTHING",
                    (rs, record, event, str(ae.get("pid") or ""), new["onset"] or None, new["aware"] or None,
                     new["grave"], serious, json.dumps({"due": new["due"], "sent": sent}), ack_by or None,
                     ack_at or None, by, at, by, at),
                )  # fmt: skip
                if rc:  # else another page view created it a moment ago and wrote its trail
                    body = {k: new[k] for k in ("onset", "aware", "grave", "due")}
                    written.append({"action": "create", "body": body})
                    if ack_by:
                        written.append({"action": "ack", "body": {"by": ack_by, "at": ack_at}})
                    written += [
                        {"action": "report", "body": {"party": p, "kind": "initial", "sent_on": d, "source": "ae_form"}}
                        for p, d in sent.items()
                        if d
                    ]
            else:
                was = old["clock"]
                diff: dict[str, Any] = {}
                for k in ("onset", "aware", "grave", "serious"):
                    if str(old[k] or "") != str(new[k] or ""):
                        diff[k] = {"old": old[k], "new": new[k]}
                for p in sorted(set(was.get("due", {})) | set(new["due"])):
                    o, n = str(was.get("due", {}).get(p, "")), str(new["due"].get(p, ""))
                    if o != n:
                        diff[f"due_{p}"] = {"old": o, "new": n}
                if diff:
                    written.append({"action": "change", "body": diff})
                for p in sorted(set(was.get("sent", {})) | set(sent)):
                    o, n = str(was.get("sent", {}).get(p, "")), str(sent.get(p, ""))
                    if o != n:
                        written.append({"action": "report", "body": {"party": p, "kind": "initial", "old": o,
                                                                     "sent_on": n, "source": "ae_form"}})  # fmt: skip
                if ack_by and not old["pi_ack_by"]:
                    written.append({"action": "ack", "body": {"by": ack_by, "at": ack_at}})
                if written:  # compare and set: two page views at once write one trail, not two
                    rc = tx.execute(
                        "UPDATE sae_case SET onset = ?, aware = ?, grave = ?, serious = ?, clock = ?, pi_ack_by = ?,"
                        " pi_ack_at = ?, updated_by = ?, updated_at = ? WHERE ruleset = ? AND record = ? AND event = ?"
                        " AND updated_at = ?",
                        (new["onset"] or None, new["aware"] or None, new["grave"], serious,
                         json.dumps({"due": new["due"], "sent": sent}), old["pi_ack_by"] or ack_by or None,
                         old["pi_ack_at"] or ack_at or None, by, at, rs, record, event, old["updated_at"]),
                    )  # fmt: skip
                    if not rc:
                        written = []
            for w in written:
                self._trail(tx, rs, record, event, w["action"], w["body"], by, at)
        return written

    def no_longer_serious(self, rs: str, record: str, event: str, by: str, at: str) -> list[dict[str, Any]]:
        """The AE form no longer says serious (or the AE is gone): the case stays, marked, and the trail says so."""
        old = self.case(rs, record, event)
        if old is None or not old["serious"]:
            return []
        body = {"serious": {"old": 1, "new": 0}}
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE sae_case SET serious = 0, updated_by = ?, updated_at = ? WHERE ruleset = ? AND record = ? AND"
                " event = ?",
                (by, at, rs, record, event),
            )
            self._trail(tx, rs, record, event, "change", body, by, at)
        return [{"action": "change", "body": body}]

    def initial_ref(self, rs: str, record: str, event: str, party: str, ref: str, by: str, at: str) -> dict[str, Any]:
        """The reference of an initial report (the date itself is on the AE form)."""
        if party not in PARTIES:
            raise SaeError("party")
        ref = check_ref(ref)
        row = self._initial(rs, record, event, party)
        with self.db.transaction() as tx:
            if row is None:
                tx.execute("INSERT INTO sae_report (ruleset, record, event, party, kind, ref, by, at) VALUES "
                           "(?,?,?,?,?,?,?,?)", (rs, record, event, party, "initial", ref or None, by, at))  # fmt: skip
            elif ref:
                tx.execute("UPDATE sae_report SET ref = ?, by = ?, at = ? WHERE id = ?", (ref, by, at, row["id"]))
            body = {"party": party, "kind": "initial", "ref": bool(ref)}
            self._trail(tx, rs, record, event, "report_ref", body, by, at)
        return body

    def _initial(self, rs: str, record: str, event: str, party: str) -> dict[str, Any] | None:
        return next((r for r in self.reports(rs, record, event) if r["kind"] == "initial" and r["party"] == party),
                    None)  # fmt: skip

    def receipt(self, rs: str, record: str, event: str, party: str, kind: str, report_id: int | None, on: str,
                ref: str, sent_on: str, today: date, by: str, at: str) -> dict[str, Any]:  # fmt: skip
        """The receiver acknowledged a report: the day (not before the report was sent, not after today) and its
        reference. ``kind`` initial names the party; followup names the follow-up row."""
        d, sent = day_of(on), day_of(sent_on)
        if d is None or d.isoformat() != on.strip():
            raise SaeError("day")
        if sent is None:
            raise SaeError("not_sent")
        if d < sent or d > today:
            raise SaeError("receipt_day")
        ref = check_ref(ref)
        if kind == "initial":
            if party not in PARTIES:
                raise SaeError("party")
            row = self._initial(rs, record, event, party)
        else:
            row = self.report(rs, int(report_id or 0))
            if row is None or row["kind"] != "followup" or (row["record"], row["event"]) != (record, event):
                raise SaeError("report")
            party = str(row["party"])
        if row is not None and row.get("receipt_on"):
            raise SaeError("already")
        with self.db.transaction() as tx:
            if row is None:
                tx.execute("INSERT INTO sae_report (ruleset, record, event, party, kind, receipt_on, receipt_ref,"
                           " by, at) VALUES (?,?,?,?,?,?,?,?,?)",
                           (rs, record, event, party, "initial", on, ref or None, by, at))  # fmt: skip
            else:
                tx.execute("UPDATE sae_report SET receipt_on = ?, receipt_ref = ?, by = ?, at = ? WHERE id = ?",
                           (on, ref or None, by, at, row["id"]))  # fmt: skip
            body = {"party": party, "kind": kind, "receipt_on": on, "ref": bool(ref)}
            self._trail(tx, rs, record, event, "receipt", body, by, at)
        return body

    def add_followup(self, rs: str, record: str, event: str, party: str, due: str, start: str, by: str,
                     at: str) -> dict[str, Any]:  # fmt: skip
        """A follow-up a receiver asked for, due on ``due`` (not before the case's start day)."""
        if party not in PARTIES:
            raise SaeError("party")
        d, s = day_of(due), day_of(start)
        if d is None or d.isoformat() != due.strip():
            raise SaeError("day")
        if s is not None and d < s:
            raise SaeError("due_before_start")
        with self.db.transaction() as tx:
            rid = tx.fetchval(
                "INSERT INTO sae_report (ruleset, record, event, party, kind, origin, due, by, at) VALUES "
                "(?,?,?,?,?,?,?,?,?) RETURNING id",
                (rs, record, event, party, "followup", "request", due, by, at),
            )
            body = {"party": party, "kind": "followup", "origin": "request", "due": due, "id": int(rid)}
            self._trail(tx, rs, record, event, "followup_add", body, by, at)
        return body

    def followup_sent(self, rs: str, record: str, event: str, party: str, report_id: int | None, due: str, on: str,
                      ref: str, start: str, today: date, by: str, at: str) -> dict[str, Any]:  # fmt: skip
        """A follow-up was sent on ``on``: a requested one (``report_id``), or the rule's one for ``party`` (stored
        now with the due day the clock gave it)."""
        d, s = day_of(on), day_of(start)
        if d is None or d.isoformat() != on.strip():
            raise SaeError("day")
        if d > today or (s is not None and d < s):
            raise SaeError("sent_day")
        ref = check_ref(ref)
        if report_id:
            row = self.report(rs, int(report_id))
            if row is None or row["kind"] != "followup" or (row["record"], row["event"]) != (record, event):
                raise SaeError("report")
            if row["sent_on"]:
                raise SaeError("already")
            party, origin = str(row["party"]), "request"
        else:
            if party not in PARTIES:
                raise SaeError("party")
            if any(r["kind"] == "followup" and r["origin"] == "rule" and r["party"] == party
                   for r in self.reports(rs, record, event)):  # fmt: skip
                raise SaeError("already")
            row, origin = None, "rule"
        with self.db.transaction() as tx:
            if row is not None:
                tx.execute("UPDATE sae_report SET sent_on = ?, ref = ?, by = ?, at = ? WHERE id = ?",
                           (on, ref or None, by, at, row["id"]))  # fmt: skip
            else:
                tx.execute(
                    "INSERT INTO sae_report (ruleset, record, event, party, kind, origin, due, sent_on, ref, by, at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (rs, record, event, party, "followup", "rule", due or None, on, ref or None, by, at),
                )
            body = {"party": party, "kind": "followup", "origin": origin, "sent_on": on, "ref": bool(ref)}
            self._trail(tx, rs, record, event, "followup_sent", body, by, at)
        return body


def check_ref(ref: str) -> str:
    """A receiver's reference: letters, digits and - / _ . # only, at most :data:`REF_MAX` characters; anything else
    (a sentence, a name) is refused, so no patient text reaches the register."""
    ref = (ref or "").strip()
    if len(ref) > REF_MAX or any(not (ch.isascii() and (ch.isalnum() or ch in "-/_.#")) for ch in ref):
        raise SaeError("ref")
    return ref


def _case(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["clock"] = json.loads(row.get("clock") or "{}")
    out["onset"], out["aware"] = row.get("onset") or "", row.get("aware") or ""
    return out


# ---------------------------------------------------------------------------------------------- the worklist
def case_view(ae: dict[str, Any], case: dict[str, Any] | None, reports: list[dict[str, Any]], today: date,
              fu_rules: dict[str, tuple[int, int]]) -> dict[str, Any]:  # fmt: skip
    """One SAE as the worklist shows it: every report (initial and follow-up) with its due day, sent day, receipt and
    state on the site's ``today``, the date checks, and how many reports are overdue. No AE term."""
    initial = {r["party"]: r for r in reports if r["kind"] == "initial"}
    rows: list[dict[str, Any]] = []
    for c in ae.get("clock") or []:
        rec = initial.get(c["party"], {})
        rows.append({"party": c["party"], "kind": "initial", "origin": "rule", "days": c.get("days"),
                     "due": c.get("due") or "", "sent_on": c.get("done") or "", "ref": rec.get("ref") or "",
                     "receipt_on": rec.get("receipt_on") or "", "id": None,
                     "state": state_of(str(c.get("due") or ""), str(c.get("done") or ""), today)})  # fmt: skip
    rule_rows = {r["party"]: r for r in reports if r["kind"] == "followup" and r["origin"] == "rule"}
    for f in rule_followups(ae, today, fu_rules, {p: str(r.get("sent_on") or "") for p, r in rule_rows.items()}):
        rec = rule_rows.get(f["party"], {})
        rows.append({"party": f["party"], "kind": "followup", "origin": "rule", "days": f["days"], "due": f["due"],
                     "sent_on": f["done"], "ref": rec.get("ref") or "", "receipt_on": rec.get("receipt_on") or "",
                     "id": rec.get("id"), "state": state_of(f["due"], f["done"], today)})  # fmt: skip
    for r in reports:
        if r["kind"] == "followup" and r["origin"] == "request":
            rows.append({"party": r["party"], "kind": "followup", "origin": "request", "days": None,
                         "due": r.get("due") or "", "sent_on": r.get("sent_on") or "", "ref": r.get("ref") or "",
                         "receipt_on": r.get("receipt_on") or "", "id": r["id"],
                         "state": state_of(str(r.get("due") or ""), str(r.get("sent_on") or ""), today)})  # fmt: skip
    flags = flags_of(ae)
    if ae.get("ae_serious") == "1" and not ae.get("clock"):
        flags = [*flags, "noclock"] if "nostart" not in flags else flags
    overdue = sum(1 for r in rows if r["state"] == "overdue")
    open_due = sorted(r["due"] for r in rows if r["state"] in ("open", "due_today") and r["due"])
    return {
        "record": ae["record"], "event": ae["event"], "pid": str(ae.get("pid") or ""),
        "short": str(ae.get("pid") or "")[:8], "onset": ae.get("ae_onset") or "", "aware": ae.get("ae_aware") or "",
        "grave": lc.grave(ae), "fatal": ae.get("ae_outcome") == "5", "serious": ae.get("ae_serious") == "1",
        "ack_by": ae.get("ack_by") or "", "ack_at": ae.get("ack_at") or "", "needs_ack": bool(ae.get("needs_ack")),
        "reports": rows, "flags": flags, "overdue": overdue,
        "alert": overdue > 0 or "nostart" in flags or "aware_before_onset" in flags,
        "next_due": open_due[0] if open_due else "",
        "first_seen": (case or {}).get("created_at") or "",
    }  # fmt: skip


def sort_key(v: dict[str, Any]) -> tuple[Any, ...]:
    """Overdue first (most overdue reports), then the other alerts, then the nearest due day; no due day last."""
    return (-v["overdue"], not v["alert"], v["next_due"] or "9999-12-31", str(v["record"]), str(v["event"]))
