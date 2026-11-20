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
* follow-up reports: the rule's follow-up (ICH E2A: a fatal or life-threatening case is completed 8 days after the
  7-day report, so day 15 from the day learned; ``TB_SAE_FOLLOWUP_DAYS``, same form as ``TB_SAE_REPORT_DAYS``) and
  any follow-up a receiver asks for by a date;
* the trail: every create and change, with old and new dates, who and when (``sae_trail``), and the same in the audit
  log (``console.sae``). What the register reads from the AE form is written as ``system:sync`` with the form's
  author and time in the body, never as the person whose page view noticed it;
* a case no longer serious keeps its last clock: its open reports stay on the worklist until sent or closed.

**No patient text.** The register and the trail keep the study, the screening number (``record``), the AE event
(``ae1`` ...), the pseudonym, dates, parties and short references. Never the AE term, a chart number or a name.

**Time.** Dates are the site's calendar dates (``site.tz``: Asia/Tokyo, Asia/Taipei; neither has daylight saving).
"Today" is the site's date at the server's clock, so a server on UTC never counts a Tokyo deadline a day late. The
24-hour report (a one-day rule: J-GCP's 直ちに, the Taiwanese 立即) is counted in hours from the time the site learned
of the event (``ae_aware_time``; without it from the start of that day, the strictest reading), so it is overdue at
+24 h, not two days later (LIFE-022, D-277). Longer deadlines are calendar days: a weekend or a public holiday neither
extends nor shortens one; the worklist says so.

**Rules per study (D-277).** Each study names its rule set on the set-up page (``datacore.lifecycle.RULE_SETS``);
the worklist and the case page name the set, the regulator (from the set's country, the same word in every
language) and who confirmed it. An unknown set, a site zone of no known country, an unreadable override or a clock
with no party left is an alert (CR-009, S-16), never a quiet fallback.

**Written on the write path (CR-012).** A page view never writes: the register is brought up to date when an AE form
is saved through the console, when a person records something on the case page, when the investigator acknowledges,
and by the daily notice job (for answers that reached the data core another way). A new case is copied to the trial
office's mailbox (``TB_SAE_OFFICE_MAILBOX``) without the AE term.

Stored in the trial database (PostgreSQL ``trialbox_wf``, schema ``sae``; D-126).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
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
# version 2 (review of PR #60, H4): an open report of a case no longer serious can be closed
SCHEMA_V2 = "ALTER TABLE sae_report ADD COLUMN closed_on TEXT"
# version 3 (CR-011, PR #60 M7): one initial report and one rule follow-up per party and case
SCHEMA_V3 = """
CREATE UNIQUE INDEX sae_report_initial ON sae_report (ruleset, record, event, party) WHERE kind = 'initial';
CREATE UNIQUE INDEX sae_report_rule_fu ON sae_report (ruleset, record, event, party)
  WHERE kind = 'followup' AND origin = 'rule'
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3)
SYNC = "system:sync"  # the actor of every row the register writes from the AE form (never the person viewing)


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
    lc.apply_override(out, override)
    return out


def start_of(ae: dict[str, Any]) -> date | None:
    """Day 0 of the clock, as :func:`lc.report_clock` takes it: the day learned, else the onset."""
    return day_of(ae.get("ae_aware")) or day_of(ae.get("ae_onset"))


def rule_followups(ae: dict[str, Any], today: date, rules: dict[str, tuple[int, int]],
                   sent: dict[str, str]) -> list[dict[str, Any]]:  # fmt: skip
    """The rule's follow-up per party, on the same clock as the first report (:func:`lc.report_clock`), counted from
    the same day 0: the first report's days plus the follow-up days (ICH E2A: 7 + 8 = day 15 for a fatal or
    life-threatening case to the regulator). It shows as soon as the case qualifies, whether or not the first report
    has gone, and does not move when the first report is sent late or early: a late first report must not buy a later
    follow-up, and an early one must not raise a false alarm. Done when ``sent[party]`` holds a day."""
    out: list[dict[str, Any]] = []
    grave = lc.grave(ae)
    for c in ae.get("clock") or []:
        party = str(c.get("party"))
        if party not in PARTIES:
            continue
        if party == "regulator" and ae.get("ae_expected") == "1":
            continue  # D-766: the 7 + 8 = day 15 follow-up is for an unexpected reaction, not the expected row
        extra = rules.get(party, (0, 0))[0 if grave else 1]
        if extra <= 0:
            continue
        total = int(c.get("days") or 0) + extra
        e = {"ae_serious": "1", "ae_outcome": ae.get("ae_outcome", ""), "ae_serious_why": ae.get("ae_serious_why", ""),
             "ae_aware": ae.get("ae_aware", ""), "ae_onset": ae.get("ae_onset", ""),
             lc.REPORT_FIELDS[party]: sent.get(party, "")}  # fmt: skip
        out += [{**f, "origin": "rule"} for f in lc.report_clock(e, today, {party: (total, total)})]
    return out


def state_of(due: str, done: str, today: date, start: date | None = None, due_at: str = "",
             now: datetime | None = None) -> str:  # fmt: skip
    """One report's state on the site's ``today``:

    * ``sent``: sent on or before its due day;
    * ``sent_late``: sent after its due day (counts as sent, stays in the alert);
    * ``bad_sent``: the day sent is unreadable, after today, or before the clock's day 0 (the AE form takes any
      date): it does **not** count as sent and stays in the alert until the form is corrected;
    * ``overdue``, ``due_today``, ``open``; ``nostart`` when there is no due day (no start date). The 24-hour report
      (``due_at``, a site-local moment) is overdue once ``now`` is past it (LIFE-022), not at the next midnight.
    """
    if done:
        d = day_of(done)
        if d is None or d > today or (start is not None and d < start):
            return "bad_sent"
        due_d = day_of(due)
        return "sent_late" if due_d is not None and d > due_d else "sent"
    d = day_of(due)
    if d is None:
        return "nostart"
    at = _moment(due_at)
    if (now is not None and at is not None and now > at) or today > d:
        return "overdue"
    return "due_today" if today == d else "open"


def _moment(text: str) -> datetime | None:
    try:
        out = datetime.fromisoformat(text) if text else None
    except ValueError:
        return None
    return out if out is not None and out.tzinfo is not None else None


def flags_of(ae: dict[str, Any], today: date | None = None) -> list[str]:
    """Checks on the dates the clock starts from (shown on the worklist, never silently fixed):

    * ``nostart``: neither the onset nor the day learned: no deadline can be counted; an alert, not a quiet row.
    * ``future_date``: the onset or the day learned is after today: a typing error; an alert.
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
    if today is not None and any(d is not None and d > today for d in (onset, aware)):
        out.append("future_date")
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

    def sync(self, rs: str, ae: dict[str, Any], by: str, at: str,
             source: Callable[[], dict[str, str]] | None = None) -> list[dict[str, Any]]:  # fmt: skip
        """Bring the case of one AE (as the orchestrator's ``/aes`` gives it, with its clock) up to date. Returns the
        trail rows written (``create``, ``change``, ``report``, ``ack``), empty when nothing changed.

        ``by`` is the register's own actor (:data:`SYNC`), never the person whose page view ran the sync; ``source``
        is asked only when something changed and gives the AE form's author and time (``form_by``, ``form_at``,
        from the data core), which go into each trail row's body."""
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
            extra = source() if written and source is not None else {}
            for w in written:
                w["body"].update(extra)
                self._trail(tx, rs, record, event, w["action"], w["body"], by, at)
        return written

    def no_longer_serious(self, rs: str, record: str, event: str, by: str, at: str,
                          source: Callable[[], dict[str, str]] | None = None) -> list[dict[str, Any]]:  # fmt: skip
        """The AE form no longer says serious (or the AE is gone): the case stays, marked, with its last clock (its
        open reports stay on the worklist), and the trail says so."""
        old = self.case(rs, record, event)
        if old is None or not old["serious"]:
            return []
        body: dict[str, Any] = {"serious": {"old": 1, "new": 0}, **(source() if source is not None else {})}
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE sae_case SET serious = 0, updated_by = ?, updated_at = ? WHERE ruleset = ? AND record = ? AND"
                " event = ?",
                (by, at, rs, record, event),
            )
            self._trail(tx, rs, record, event, "change", body, by, at)
        return [{"action": "change", "body": body}]

    def register_sent(self, rs: str, record: str, event: str, party: str, on: str, ref: str, by: str,
                      at: str) -> dict[str, Any]:  # fmt: skip
        """The first report of a case no longer serious was sent: the AE form hides its report fields once the AE is
        not serious, so the day is kept here (``source`` register). Only for a downgraded case."""
        if party not in PARTIES:
            raise SaeError("party")
        ref = check_ref(ref)
        row = self._initial(rs, record, event, party)
        if row is not None and (row.get("sent_on") or row.get("closed_on")):
            raise SaeError("already")
        with self.db.transaction() as tx:
            if row is None:
                tx.execute(
                    "INSERT INTO sae_report (ruleset, record, event, party, kind, sent_on, ref, by, at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (rs, record, event, party, "initial", on, ref or None, by, at),
                )
            else:
                tx.execute("UPDATE sae_report SET sent_on = ?, ref = COALESCE(?, ref), by = ?, at = ? WHERE id = ?",
                           (on, ref or None, by, at, row["id"]))  # fmt: skip
            body = {"party": party, "kind": "initial", "sent_on": on, "source": "register", "ref": bool(ref)}
            self._trail(tx, rs, record, event, "report", body, by, at)
        return body

    def close_report(self, rs: str, record: str, event: str, party: str, kind: str, report_id: int | None, on: str,
                     by: str, at: str) -> dict[str, Any]:  # fmt: skip
        """Close an open report of a case no longer serious (not needed any more), on ``on``; the trail keeps it."""
        if kind == "initial":
            if party not in PARTIES:
                raise SaeError("party")
            row = self._initial(rs, record, event, party)
        else:
            row = self.report(rs, int(report_id or 0))
            if row is None or row["kind"] != "followup" or (row["record"], row["event"]) != (record, event):
                raise SaeError("report")
            party = str(row["party"])
        if row is not None and (row.get("sent_on") or row.get("closed_on")):
            raise SaeError("already")
        with self.db.transaction() as tx:
            if row is None:
                tx.execute("INSERT INTO sae_report (ruleset, record, event, party, kind, closed_on, by, at) VALUES "
                           "(?,?,?,?,?,?,?,?)", (rs, record, event, party, "initial", on, by, at))  # fmt: skip
            else:
                tx.execute("UPDATE sae_report SET closed_on = ?, by = ?, at = ? WHERE id = ?", (on, by, at, row["id"]))
            body = {"party": party, "kind": kind, "closed_on": on}
            self._trail(tx, rs, record, event, "closed", body, by, at)
        return body

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
            if row["sent_on"] or row.get("closed_on"):
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


# ---------------------------------------------------------------------------------------------- 9f-4 (b), D-1383
def escalated_hours(trail: list[dict[str, Any]]) -> set[int]:
    """The thresholds (hours) at which a case was already escalated, from its trail."""
    return {int(t["body"].get("hours") or 0) for t in trail if t["action"] == "escalated"}


def escalate_once(store: SaeStore, rs: str, record: str, event: str, hours: int, send: Callable[[], dict[str, Any]],
                  by: str, at: str, before_commit: Callable[[dict[str, Any]], None] | None = None,
                  ) -> dict[str, Any] | None:  # fmt: skip
    """Escalate one unacknowledged case once per threshold: under a lock per case, when its trail has no
    ``escalated`` row for ``hours``, ``send`` mails the recipients and gives the row's body; the row and
    ``before_commit`` (the audit event) are written in the same transaction. None when it was escalated already."""
    with store.db.transaction() as tx:
        tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"sae-escalate:{rs}:{record}:{event}",))
        rows = tx.fetchall(
            "SELECT body FROM sae_trail WHERE ruleset = ? AND record = ? AND event = ? AND action = 'escalated'",
            (rs, record, event),
        )
        if hours in {int(json.loads(str(r[0])).get("hours") or 0) for r in rows}:
            return None
        body = {**send(), "hours": hours}
        store._trail(tx, rs, record, event, "escalated", body, by, at)
        if before_commit is not None:
            before_commit(body)
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
OPEN = ("overdue", "due_today", "open", "nostart", "bad_sent")  # a report still to send (or whose day is wrong)
ALERT_FLAGS = ("nostart", "aware_before_onset", "future_date", "noclock", "serious_mismatch", *lc.RULE_ALERTS)


def _row(party: str, kind: str, origin: str, days: Any, due: str, sent: str, rec: dict[str, Any],
         start: date | None, today: date, rid: Any = None, due_at: str = "",
         now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    closed = str(rec.get("closed_on") or "")
    return {"party": party, "kind": kind, "origin": origin, "days": days, "due": due or "", "sent_on": sent or "",
            "due_at": due_at, "hours": 24 if due_at else None,
            "ref": rec.get("ref") or "", "receipt_on": rec.get("receipt_on") or "", "closed_on": closed,
            "id": None if kind == "initial" else (rid if rid is not None else rec.get("id")),  # initial: by party
            "state": "closed" if closed and not sent else state_of(due, sent, today, start, due_at, now)}  # fmt: skip


def _summary(rows: list[dict[str, Any]], flags: list[str]) -> dict[str, Any]:
    overdue = sum(1 for r in rows if r["state"] == "overdue")
    late = sum(1 for r in rows if r["state"] == "sent_late")
    bad = sum(1 for r in rows if r["state"] == "bad_sent")
    open_due = sorted(r["due"] for r in rows if r["state"] in ("open", "due_today") and r["due"])
    return {"overdue": overdue, "late": late, "bad": bad, "open": sum(1 for r in rows if r["state"] in OPEN),
            "alert": bool(overdue or late or bad or set(ALERT_FLAGS) & set(flags)),
            "next_due": open_due[0] if open_due else ""}  # fmt: skip


def case_view(ae: dict[str, Any], case: dict[str, Any] | None, reports: list[dict[str, Any]], today: date,
              fu_rules: dict[str, tuple[int, int]], now: datetime | None = None,
              rules: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """One serious AE as the worklist shows it: every report (initial and follow-up) with its due day (and the
    24-hour report's due moment), sent day, receipt and state at the site's ``now`` / ``today``, the date checks,
    the rule problems (``rules``, :func:`lc.clock_rules`), and the counts the alert needs. No AE term."""
    start = start_of(ae)
    initial = {r["party"]: r for r in reports if r["kind"] == "initial"}
    rows = [_row(c["party"], "initial", "rule", c.get("days"), str(c.get("due") or ""), str(c.get("done") or ""),
                 initial.get(c["party"], {}), start, today, rid=None, due_at=str(c.get("due_at") or ""), now=now)
            for c in ae.get("clock") or []]  # fmt: skip
    stored = {r["party"]: r for r in reports if r["kind"] == "followup" and r["origin"] == "rule"}
    shown: set[str] = set()
    for f in rule_followups(ae, today, fu_rules, {p: str(r.get("sent_on") or "") for p, r in stored.items()}):
        shown.add(f["party"])
        rows.append(_row(f["party"], "followup", "rule", f["days"], f["due"], f["done"], stored.get(f["party"], {}),
                         start, today))  # fmt: skip
    for p, r in stored.items():  # a recorded rule follow-up never disappears (a downgrade, a cleared date)
        if p not in shown:
            rows.append(_row(p, "followup", "rule", None, str(r.get("due") or ""), str(r.get("sent_on") or ""), r,
                             start, today))  # fmt: skip
    rows += [_row(r["party"], "followup", "request", None, str(r.get("due") or ""), str(r.get("sent_on") or ""), r,
                  start, today)
             for r in reports if r["kind"] == "followup" and r["origin"] == "request"]  # fmt: skip
    flags = flags_of(ae, today)
    if lc.is_serious(ae) and not ae.get("clock") and "nostart" not in flags:
        flags.append("noclock")  # S-16: a serious AE with no clock at all is an alert, never a quiet row
    if lc.is_serious(ae) and ae.get("ae_serious") != "1":
        flags.append("serious_mismatch")  # CR-008: fatal (or a "why serious" reason) with Serious = No
    if any(r["state"] == "bad_sent" for r in rows):
        flags.append("bad_sent")
    flags += [p for p in (rules or {}).get("problems") or [] if p != "noclock" or "noclock" not in flags]
    if any(r.get("due_at") for r in rows) and ae.get("ae_aware") and lc.aware_time(ae) is None:
        flags.append("aware_time_missing")  # the 24-hour report counts from 00:00 of the day learned
    has_reg = any(r.get("party") == "regulator" for r in ae.get("clock") or [])  # D-766: jp_gcp_ii keeps one
    if (
        ae.get("ae_expected") == "1"
        and not has_reg
        and ((rules or {}).get("parties") or {}).get("regulator", (0, 0)) != (0, 0)
    ):
        flags.append("expected_noreg")  # expected per the reference safety information: no regulator clock
    return {
        "record": ae["record"], "event": ae["event"], "pid": str(ae.get("pid") or ""),
        "short": str(ae.get("pid") or "")[:8], "onset": ae.get("ae_onset") or "", "aware": ae.get("ae_aware") or "",
        "grave": lc.grave(ae), "fatal": ae.get("ae_outcome") == "5", "serious": True, "downgraded": False,
        "ack_by": ae.get("ack_by") or "", "ack_at": ae.get("ack_at") or "", "needs_ack": bool(ae.get("needs_ack")),
        "expected": str(ae.get("ae_expected") or ""), "unblinded": str(ae.get("ae_unblinded") or ""),
        "unblind_date": str(ae.get("ae_unblind_date") or ""), "aware_time": str(ae.get("ae_aware_time") or ""),
        "reports": rows, "flags": flags, "first_seen": (case or {}).get("created_at") or "",
        **_summary(rows, flags),
    }  # fmt: skip


def downgraded_view(case: dict[str, Any], reports: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """A case the AE form no longer calls serious, drawn from the last clock the register saw (``sae_case.clock``)
    and the register's own rows: its open reports stay visible until each is sent or closed."""
    start = day_of(case.get("aware")) or day_of(case.get("onset"))
    clock = case.get("clock") or {}
    initial = {r["party"]: r for r in reports if r["kind"] == "initial"}
    rows = []
    for p, due in (clock.get("due") or {}).items():
        rec = initial.get(p, {})
        sent = str((clock.get("sent") or {}).get(p) or rec.get("sent_on") or "")
        rows.append(_row(p, "initial", "rule", None, str(due or ""), sent, rec, start, today))
    rows += [_row(r["party"], "followup", r["origin"], None, str(r.get("due") or ""), str(r.get("sent_on") or ""), r,
                  start, today)
             for r in reports if r["kind"] == "followup"]  # fmt: skip
    flags = ["downgraded"]
    summary = _summary(rows, flags)
    summary["alert"] = summary["alert"] or summary["open"] > 0
    return {
        "record": case["record"], "event": case["event"], "pid": str(case.get("pid") or ""),
        "short": str(case.get("pid") or "")[:8], "onset": case.get("onset") or "", "aware": case.get("aware") or "",
        "grave": bool(case.get("grave")), "fatal": False, "serious": False, "downgraded": True,
        "ack_by": case.get("pi_ack_by") or "", "ack_at": case.get("pi_ack_at") or "", "needs_ack": False,
        "reports": rows, "flags": flags, "first_seen": case.get("created_at") or "", **summary,
    }  # fmt: skip


def office_notice(rs: str, v: dict[str, Any], rules: dict[str, Any]) -> tuple[str, str]:
    """The copy of a new SAE case to the trial office's mailbox (FIT-025): the study, the screening number, the
    event, the dates, the rule set and each deadline. Never the AE term, a chart number or a name."""
    subject = f"[TrialBox] SAE {rs} {v['record']} {v['event']}"
    lines = [f"New serious adverse event in the TrialBox SAE register: study {rs}, screening number {v['record']}, "
             f"event {v['event']}.", "",
             f"- Onset: {v.get('onset') or '-'}; the site learned of it: {v.get('aware') or '-'} "
             f"{v.get('aware_time') or ''}".rstrip(),
             f"- Fatal or life-threatening: {'yes' if v.get('grave') else 'no'}",
             f"- Rule set: {rules.get('name') or '-'} (regulator {rules.get('regulator') or '-'}; confirmed by "
             f"{rules.get('confirmed_by') or 'nobody yet'})"]  # fmt: skip
    for r in v.get("reports") or []:
        due = r.get("due_at") or r.get("due") or "-"
        lines.append(f"- {r['kind']} report to the {r['party']}: due {due}")
    lines += ["", "The office log stays the record (D-191). Open the case in TrialBox for the details."]
    return subject, "\n".join(lines)


def sort_key(v: dict[str, Any]) -> tuple[Any, ...]:
    """Overdue first (most overdue reports), then the other alerts, then the nearest due day; no due day last."""
    return (-v["overdue"], not v["alert"], v["next_due"] or "9999-12-31", str(v["record"]), str(v["event"]))
