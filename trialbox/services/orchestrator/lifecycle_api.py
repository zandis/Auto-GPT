"""Orchestrator API of the trial lifecycle (TB-PLAN-04 step 5, D-134), on the data core (``datacore.lifecycle``).

* ``POST /studies/{rs}/subjects/refresh`` (``screening``: screening number -> pseudonym, from the console's site store
  that issues them): each number becomes a subject (a candidate) and is moved forward to what the data core's answers
  and the screening log say. The REDCap read-back (``study_api``) and every saved form (``datacore_api``) do the same
  for the records they touch.
* ``GET /studies/{rs}/subjects``; ``GET /studies/{rs}/subjects/{record}`` (state, every step, the visits with their
  windows, AEs and deviations, the next legal steps); ``POST .../step`` (``to``, ``on_day``, ``reason``, ``note``) and
  ``POST .../undo``: an illegal step is 409 ``LIFE-STEP`` with ``why`` (a plain-reason key) and the allowed steps.
* ``GET/PUT /studies/{rs}/schedule`` (the schedule of events), ``POST /studies/{rs}/schedule/redcap`` (read from a
  REDCap project's arms and events: ``day_offset``, ``offset_min``, ``offset_max``).
* ``GET /studies/{rs}/visits?today=`` (every visit of every subject on that day: due, open, overdue, done, missed,
  and the coordinator's list: today, this week, overdue); ``GET /studies/{rs}/aes`` (every AE, serious ones apart,
  those an investigator has not acknowledged yet, and the reports that are overdue); ``POST
  /studies/{rs}/aes/{record}/{event}/ack`` (the investigator's one-tap acknowledgement, audited ``life.sae_ack``).
* ``GET /studies/{rs}/report`` and ``/report/{csv|xlsx}``: the investigator's enrolment report.
* ``GET/PUT /studies/{rs}/contact-rule`` (D-407, LIFE-017): the study's contact-attempt limit; ``GET/POST
  /studies/{rs}/deviations/possible`` (LIFE-025): the possible deviations from the box's facts, confirmed (a
  deviation entry) or dismissed with a reason.

``today`` is the site's local date (``now()`` is in the site's zone) unless a caller gives one, so tests step through
the windows. A step is mirrored into the screening log (the candidate registry), so the log, this report and the
REDCap write-back's ``tb_status`` say the same; the mirror runs only after a step, so a REDCap value that differs is
never fought over (it stays listed as ``held``). Every change is audited (``life.step``, ``life.schedule``).
"""

from __future__ import annotations

import base64
import csv
import io
import logging
import os
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Protocol

from datacore import lifecycle as lc
from datacore.lifecycle import AE_EVENT, DV_EVENT, Lifecycle, LifeError, Visit
from datacore.store import DataCore
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from rc_bridge.client import RedcapClient
from tb_common import sheets
from tb_common.actor_v3 import Claim
from tb_common.audit import AuditLog
from tb_common.deterministic import normalize_ooxml
from tb_common.erased import is_erased
from tb_common.patient_reads import MONITOR as _MONITOR
from tb_common.patient_reads import PHI as _PHI

from orchestrator.actor import require_actor
from orchestrator.candidates import RegistryError

# T-715 (D-483): the matrix rows the console asks before it calls these routes; the dependency asks them again
ENTER = "study.setup"  # who records the participants' steps, the schedule and the study's rules (the coordinator)
ACK = "sae.ack"  # the investigator has seen a serious adverse event
READ = "phi.view"  # the enrolment report as a file (it is audited with the person who took it)
AS_ENTER = require_actor(ENTER)
AS_ENTER_OR_TIMER = require_actor(ENTER, service=True)  # the participants' refresh: also the console's notice timer
AS_ACK = require_actor(ACK)
AS_READ = require_actor(READ)

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIFE_FORMS = ("tb_screening_log", "tb_consent", "tb_enrolment", "tb_visit", "tb_withdrawal")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

log = logging.getLogger("orchestrator")

#: NEW-SEC-1 (D-717): a route that returns a patient's row takes the verified person, allowed to see
#: patient-level data on the route's study (tb_common.patient_reads)
PATIENT_READ = require_actor(_PHI)  # D-717 review: no service principal
NOTIFY_READ = require_actor(_PHI, service=True)  # the morning mail's visits and AEs, signed as its principal
#: D-389: the four reads of the monitor's page (a sponsor's CRA under a monitor grant) take its row too
MONITOR_READ = require_actor(_MONITOR, service=True)


class Host(Protocol):
    """What the lifecycle needs from its service (``DataService``, or ``LifeHost`` for the REDCap read-back)."""

    @property
    def dc(self) -> DataCore: ...

    @property
    def registry(self) -> Any: ...

    @property
    def audit(self) -> AuditLog: ...

    def now(self) -> datetime: ...

    def stamp(self) -> str: ...


class ApiHost(Host, Protocol):
    def client(self, token_ref: str) -> RedcapClient: ...


@dataclass
class LifeHost:
    dc: DataCore
    registry: Any
    audit: AuditLog
    now: Callable[[], datetime]

    def stamp(self) -> str:
        return self.now().isoformat(timespec="seconds")


class RefreshBody(BaseModel):
    screening: dict[str, str] = Field(default_factory=dict)  # screening number -> pseudonym


class StepBody(BaseModel):
    to: str
    on_day: str = ""
    reason: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=300)
    today: str = ""
    criterion: str = Field(default="", max_length=48)  # D-387: the criterion not met, on a "not_eligible" failure
    criteria_version: str = Field(default="", max_length=24)


class UndoBody(BaseModel):
    note: str = Field(default="", max_length=300)


class VisitBody(BaseModel):
    visit: str
    day: int
    before: int = 0
    after: int = 0
    anchor: str = "enrolment"
    labels: dict[str, str] = Field(default_factory=dict)


class ScheduleBody(BaseModel):
    visits: list[VisitBody]
    effective_from: str = ""  # D-364: the first visit day this version applies to; empty = from the start


class AckBody(BaseModel):
    """Nothing: the person who acknowledges is the verified one (T-715, D-483)."""


class SaeRuleBody(BaseModel):
    rule_set: str


class ContactRuleBody(BaseModel):
    max_attempts: int
    min_days: int


class ConsentAgesBody(BaseModel):
    majority: int
    assent_from: int
    assent_to: int


class DeviationCallBody(BaseModel):
    record: str
    key: str = Field(max_length=80)
    decision: str
    reason: str = ""
    today: str = ""
    icf: str = Field("", max_length=40)


class ScheduleRedcapBody(BaseModel):
    token_ref: str
    anchor: str = "enrolment"


def _rs(rs: str) -> str:
    rid = rs.strip().upper()
    if not _RS.match(rid):
        raise HTTPException(status_code=400, detail={"code": "BAD-STUDY", "message": "not a study id"})
    return rid


def _rec(record: str) -> str:
    if not _REC.match(record):
        raise HTTPException(status_code=400, detail={"code": "DATA-RECORD", "message": "not a record key"})
    return record.lower() if re.fullmatch(r"[0-9a-fA-F]{32}", record) else record.upper()


def _refused(exc: LifeError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": exc.code, "why": exc.why, "message": exc.message,
                                                  "fields": exc.fields, **exc.detail})  # fmt: skip


def _today(svc: Host, given: str = "") -> date:
    if given:
        if not _DAY.match(given):
            raise HTTPException(status_code=400, detail={"code": "BAD-DAY", "message": "today is YYYY-MM-DD"})
        return date.fromisoformat(given)
    return svc.now().date()


# ---------------------------------------------------------------------------------------------- the screening log
def registry_path(cur: str | None, want: str) -> list[str] | None:
    """The registry's own recorded transitions from ``cur`` to ``want`` (shortest), or None."""
    from orchestrator.candidates import FORWARD

    start = cur or "candidate"
    if start == want:
        return [] if cur else [want]
    seen = {start: [] if cur else ["candidate"]}
    q: deque[str] = deque([start])
    while q:
        s = q.popleft()
        for n in FORWARD.get(s, ()):
            if n in seen:
                continue
            seen[n] = [*seen[s], n]
            if n == want:
                return seen[n]
            q.append(n)
    return None


def mirror(registry: Any, rs: str, pid: str, state: str, by: str, now: Any) -> str | None:
    """Put the subject's state on the screening log (the candidate registry); None, or why it could not."""
    from tb_contracts import RegistryUpdate

    if registry is None or not pid:
        return None
    if is_erased(pid):  # D-875: an erased subject is never put back on the log; the step says so (the review)
        return "an erased row: the screening log is not updated"
    want = lc.REGISTRY_OF[state]
    try:
        cur = next((e.status for e in registry.rows(rs) if e.pid == pid), None)
    except RegistryError as exc:
        return str(exc)[:120]  # the registry's own words (D-555)
    except Exception as exc:  # any other error's text can hold what was sent: its type, and the log
        log.warning("the screening log could not be read for a lifecycle step", extra={"error": type(exc).__name__})
        return f"the screening log could not be read ({type(exc).__name__})"
    if cur is not None and lc.REGISTRY_OF.get(lc.FROM_REGISTRY.get(cur, ""), "") == want:
        return None  # the log already says so in its own words (declined is a screen failure)
    path = registry_path(cur, want)
    if path is None:
        return f"{cur} -> {want} is not a screening-log transition"
    for st in path:
        try:
            registry.update(rs, RegistryUpdate.model_validate({"pid": pid, "status": st, "by": by,
                                                               "source": "manual"}), now)  # fmt: skip
        except RegistryError as exc:
            return str(exc)[:120]
        except Exception as exc:
            log.warning("the screening log was not updated by a lifecycle step", extra={"error": type(exc).__name__})
            return f"the screening log was not updated ({type(exc).__name__})"
    return None


def behind(status: str | None, state: str) -> bool:
    """T-516 (UX-011): the screening log's status is behind the participant's state on the main line (or the log has
    no row yet while the participant moved on). An end state on the log, or a log ahead, is never pulled back."""
    if state not in lc.LINE or state == "candidate":
        return False
    if status is None:
        return True
    have = lc.FROM_REGISTRY.get(status, "")
    return have in lc.LINE and lc.LINE.index(have) < lc.LINE.index(state)


def registry_status(svc: Host, rs: str) -> dict[str, str]:
    if svc.registry is None:
        return {}
    try:
        return {e.pid: e.status for e in svc.registry.rows(rs)}
    except Exception:
        return {}


def refresh(svc: Host, rs: str, screening: dict[str, str], by: str,
            records: list[str] | None = None) -> dict[str, Any]:  # fmt: skip
    """Make each screening number a subject and move every subject (or ``records``) forward to its evidence."""
    life = Lifecycle(svc.dc)
    at = svc.stamp()
    made: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for no, pid in sorted(screening.items()):
        _sub, new = life.ensure(rs, no.strip().upper(), pid, by, at)
        if new:
            made.append({"record": no.strip().upper(), "from": None, "to": "candidate"})
    reg = registry_status(svc, rs)
    sched = life.schedule(rs)
    subjects = {s["record"]: s for s in life.subjects(rs)}
    for rec in records if records is not None else sorted(subjects):
        sub = subjects.get(rec)
        if sub is None:
            continue
        out = life.derive(rs, rec, by=by, at=at, registry=reg.get(str(sub["pid"])), schedule=sched)
        for st in out["steps"]:
            made.append({"record": rec, **st})
        held += [{"record": rec, **h} for h in out["held"]]
        now = life.subject(rs, rec)
        assert now is not None
        # T-516 (UX-011): the log follows the participant also when a step was taken before the screening number
        # was known (a consent form saved first): a log behind the participant's state is brought up to it
        pid, state = str(now["pid"]), str(now["state"])
        if out["steps"] or (pid and svc.registry is not None and behind(reg.get(pid), state)):
            why = mirror(svc.registry, rs, pid, state, by, svc.now())
            if why:
                held.append({"record": rec, "state": state, "why": "screening_log", "detail": why})
            if out["steps"]:
                svc.audit.append("life.step", ruleset=rs, actor=by,
                                 detail={"record": rec, "steps": [[s["from"], s["to"]] for s in out["steps"]],
                                         "source": "derived"})  # fmt: skip
            else:
                svc.audit.append("life.log_sync", ruleset=rs, actor=by,
                                 detail={"record": rec, "to": lc.REGISTRY_OF[state], "from": reg.get(pid) or "",
                                         "ok": not why})  # fmt: skip
    return {"made": made, "held": held}


def derive_record(svc: Host, rs: str, record: str, by: str) -> dict[str, Any]:
    """After a form is saved: the record becomes a subject if it is not one, and follows its answers."""
    Lifecycle(svc.dc).ensure(rs, record, "", by, svc.stamp())
    return refresh(svc, rs, {}, by, [record])


# ---------------------------------------------------------------------------------------------- views
def subject_view(life: Lifecycle, rs: str, sub: dict[str, Any], today: date,
                 sched: list[Visit]) -> dict[str, Any]:  # fmt: skip
    visits = life.visits(rs, str(sub["record"]), today, sched, sub)
    n = {k: sum(1 for v in visits if v["status"] == k) for k in lc.VISIT_STATES}
    # T-516 (LIFE-019): an enrolment or a visit recorded without a consent form; the subject is held before consent
    missing = life.consent_missing(rs, str(sub["record"]), str(sub["state"]))
    # D-399 (T-302a): every consent recorded, the last one, and what is out of order (LIFE-018, LIFE-019)
    consent = life.consent_record(rs, str(sub["record"]), str(sub["state"]), today=today)
    return {**sub, "visits": n, "next": list(lc.NEXT.get(str(sub["state"]), ())), "consent_missing": missing,
            "consent": consent}  # fmt: skip


def visit_rows(life: Lifecycle, rs: str, today: date) -> list[dict[str, Any]]:
    sched = life.schedule_on(rs, today)
    rows = []
    for sub in life.subjects(rs):
        for v in life.visits(rs, str(sub["record"]), today, sched, sub):
            if v["status"] == "unplanned":
                continue
            rows.append({**v, "record": sub["record"], "pid": sub["pid"], "state": sub["state"]})
    return rows


def sae_rules(svc: Host, rid: str = "", life: Lifecycle | None = None) -> dict[str, Any]:
    """The reporting clock in force for one study (D-277): the study's named set from its set-up page, else
    ``TB_SAE_RULES``, else the default of the site's country; then ``TB_SAE_REPORT_DAYS``. With who confirmed the
    study's set and when, and the problems the pages show as an alert (CR-009)."""
    tz = str(getattr(svc.now().tzinfo, "key", "") or os.environ.get("TB_TZ", ""))
    row = (life or Lifecycle(svc.dc)).sae_rule(rid) if rid else None
    out = lc.clock_rules(str((row or {}).get("rule_set") or ""), tz, os.environ.get("TB_SAE_REPORT_DAYS", ""),
                         os.environ.get("TB_SAE_RULES", ""))  # fmt: skip
    out["confirmed_by"] = str((row or {}).get("confirmed_by") or "")
    out["confirmed_at"] = str((row or {}).get("confirmed_at") or "")
    return out


AE_KEEP = ("record", "event", "n", "ae_term", "ae_onset", "ae_aware", "ae_aware_time", "ae_serious", "ae_serious_why",
           "ae_severity", "ae_outcome", "ae_death_date", "ae_end", "ae_related", "ae_sponsor_related", "ae_expected",
           "ae_unblinded", "ae_unblind_date", "ae_unblind_reason", *lc.REPORT_FIELDS.values())  # fmt: skip


def ae_view(e: dict[str, Any], today: date | None = None, rules: dict[str, tuple[int, int]] | None = None,
            ack: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    """One AE as the pages show it. A serious AE needs the investigator's acknowledgement whatever its outcome
    (review 2026-11-09 P-02: a fatal SAE used to count as "not ongoing" and left the banner and N1 at once), and
    carries its reporting clock (P-03). Serious means the form's answer or a fatal outcome or a "why serious"
    reason (CR-008); ``serious_mismatch`` says the Serious radio disagrees, so the pages ask to correct it."""
    out = {k: e.get(k, "") for k in AE_KEEP}
    out["serious"] = lc.is_serious(e)
    out["serious_mismatch"] = out["serious"] and e.get("ae_serious") != "1"
    out["fatal"] = e.get("ae_outcome") == "5"
    out["ongoing"] = e.get("ae_outcome", "") in ("", "2", "3", "6")
    out["ack_by"] = str((ack or {}).get("who") or "")
    out["ack_at"] = str((ack or {}).get("at") or "")
    out["needs_ack"] = out["serious"] and not out["ack_by"]
    out["clock"] = lc.report_clock(e, today, rules, now) if today is not None and rules is not None else []
    out["overdue"] = [c["party"] for c in out["clock"] if c["overdue"]]
    out["noclock"] = bool(out["serious"] and rules is not None and not out["clock"])  # S-16: never a quiet SAE
    return out


def aes_of(svc: Host, rid: str, record: str | None, today: date, now: datetime | None = None,
           rules: dict[str, Any] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    life = Lifecycle(svc.dc)
    acks = life.acks(rid)
    parties = (rules or sae_rules(svc, rid, life))["parties"]
    return [ae_view(e, today, parties, acks.get((str(e["record"]), str(e["event"]))), now or _now(svc, today))
            for e in life.entries(rid, record, AE_EVENT)]  # fmt: skip


def _now(svc: Host, day: date, given: str = "") -> datetime:
    """The moment the 24-hour report is judged at (LIFE-022): ``given`` (ISO with its offset), else the service's
    clock when ``day`` is its date, else the start of ``day`` in the site's zone (a test stepping through days)."""
    if given:
        try:
            out = datetime.fromisoformat(given.replace(" ", "+").replace("Z", "+00:00"))
        except ValueError:
            out = None
        if out is None or out.tzinfo is None:
            raise HTTPException(
                status_code=400, detail={"code": "BAD-DAY", "message": "now is an ISO time with offset"}
            )
        return out
    n = svc.now()
    return n if n.date() == day else datetime.combine(day, time(0, 0), tzinfo=n.tzinfo)


def report_files(rep: dict[str, Any], rs: str, at: str) -> dict[str, Any]:
    """The enrolment report as CSV (one table, long form) and XLSX (a sheet per table)."""
    rows: list[list[Any]] = [["table", "key", "state", "count"]]
    rows += [["state", "now", s, rep["counts"][s]] for s in lc.STATES]
    rows += [["state", "ever", s, rep["ever"][s]] for s in lc.STATES]
    for m in rep["months"]:
        rows += [["month", m["month"], s, m[s]] for s in lc.STATES if s != "candidate"]
    rows += [["screen_fail_reason", k, "screen_fail", v] for k, v in rep["screen_fail_reasons"].items()]
    rows += [["withdrawal", w["record"], w["day"], w["reason"]] for w in rep["withdrawals"]]
    buf = io.StringIO()
    # NEW-CSV-1 (D-549): a withdrawal's reason is typed; no text cell runs as a formula in a spreadsheet
    csv.writer(buf, lineterminator="\n").writerows(
        [sheets.csv_cell(c) if isinstance(c, str) else c for c in row] for row in rows
    )
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws: Any = wb.active
    ws.title = "states"
    ws.append(["state", "now", "ever"])
    for s in lc.STATES:
        ws.append([s, rep["counts"][s], rep["ever"][s]])
    mo = wb.create_sheet("months")
    mo.append(["month", *[s for s in lc.STATES if s != "candidate"]])
    for m in rep["months"]:
        mo.append([m["month"], *[m[s] for s in lc.STATES if s != "candidate"]])
    sf = wb.create_sheet("screen_fail")
    sf.append(["reason", "count"])
    for k, v in rep["screen_fail_reasons"].items():
        sf.append([k, v])
    wd = wb.create_sheet("withdrawals")
    wd.append(["record", "day", "reason"])
    for w in rep["withdrawals"]:
        wd.append([w["record"], w["day"], w["reason"]])
    ab = wb.create_sheet("about")
    ab.append(["study", rs])
    ab.append(["made", at])
    ab.append(["note", "Records are screening numbers or patient codes, never chart numbers."])
    for sheet in (ws, mo, sf, wd):
        for c in sheet[1]:
            c.font = Font(bold=True)
    sheets.no_formulas(wb)  # NEW-CSV-1 (D-549)
    out = io.BytesIO()
    wb.save(out)
    return {"csv": buf.getvalue(), "xlsx": normalize_ooxml(out.getvalue())}


# ---------------------------------------------------------------------------------------------- routes
def router(get: Callable[[], ApiHost]) -> APIRouter:
    r = APIRouter()

    @r.post("/studies/{rs}/subjects/refresh")
    def post_refresh(rs: str, body: RefreshBody, who: Claim = AS_ENTER_OR_TIMER) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        nos = {k.strip().upper(): v.strip().lower() for k, v in body.screening.items() if _REC.match(k.strip())}
        return refresh(svc, rid, nos, who.name)

    @r.get("/studies/{rs}/subjects", dependencies=[MONITOR_READ])
    def get_subjects(rs: str, today: str = "", slim: bool = False) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        if slim:  # D-1221: the state only (the console's lists read each person's one state; no visit or consent view)
            life = Lifecycle(svc.dc)
            keep = ("record", "pid", "state", "since", "reason", "changed_by", "changed_at")
            by_rec: dict[str, list[dict[str, Any]]] = {}
            for st in life.steps(rid):  # one read: the steps that still stand ("ever reached", not undone)
                by_rec.setdefault(str(st["record"]), []).append(st)
            return {"study": rid, "subjects": [
                {**{k: s.get(k, "") for k in keep},
                 "ever": sorted({str(x["new"]) for x in lc.live_steps(by_rec.get(str(s["record"]), []))})}
                for s in life.subjects(rid)]}  # fmt: skip
        life, day = Lifecycle(svc.dc), _today(svc, today)
        sched = life.schedule_on(rid, day)
        detail = life.screen_detail(rid)  # D-387: consent, enrolment and the criterion not met, for the screening log
        subs = [{**subject_view(life, rid, s, day, sched), **detail.get(str(s["record"]), {})}
                for s in life.subjects(rid)]  # fmt: skip
        return {"study": rid, "today": day.isoformat(), "subjects": subs,
                "counts": {s: sum(1 for x in subs if x["state"] == s) for s in lc.STATES}}  # fmt: skip

    @r.get("/studies/{rs}/subjects/{record}", dependencies=[MONITOR_READ])
    def get_subject(rs: str, record: str, today: str = "") -> dict[str, Any]:
        svc, rid, rec = get(), _rs(rs), _rec(record)
        life, day = Lifecycle(svc.dc), _today(svc, today)
        sub = life.subject(rid, rec)
        if sub is None:
            raise HTTPException(status_code=404, detail={"code": "LIFE-NONE", "message": "no such subject"})
        sched = life.schedule_on(rid, day)
        return {
            "study": rid,
            "today": day.isoformat(),
            "subject": subject_view(life, rid, sub, day, sched),
            "steps": life.steps(rid, rec),
            "visits": life.visits(rid, rec, day, sched, sub),
            "aes": aes_of(svc, rid, rec, day),
            "deviations": life.entries(rid, rec, DV_EVENT),
            "next_ae": life.next_event(rid, rec, "ae"),
            "next_dv": life.next_event(rid, rec, "dv"),
        }

    @r.post("/studies/{rs}/subjects/{record}/step")
    def post_step(rs: str, record: str, body: StepBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        svc, rid, rec = get(), _rs(rs), _rec(record)
        life = Lifecycle(svc.dc)
        before = life.subject(rid, rec)
        if body.to == "consented" and not body.note.strip() and life.assent_declined(rid, rec):
            # 10C-19 (D-1232): consent to proceed after a declined assent is a person's deliberate step, with a reason
            exc = LifeError("assent_reason", "the participant declined assent: give the reason to proceed in the note")
            svc.audit.append("life.refused", ruleset=rid, actor=who.name,
                             detail={"record": rec, "to": body.to, "why": exc.why})  # fmt: skip
            raise _refused(exc)
        try:
            sub = life.step(rid, rec, body.to, by=who.name, at=svc.stamp(), on_day=body.on_day, reason=body.reason,
                            note=body.note, today=_today(svc, body.today), criterion=body.criterion,
                            criteria_version=body.criteria_version)  # fmt: skip
        except LifeError as exc:
            svc.audit.append("life.refused", ruleset=rid, actor=who.name,
                             detail={"record": rec, "to": body.to, "why": exc.why})  # fmt: skip
            raise _refused(exc) from exc
        why = mirror(svc.registry, rid, str(sub["pid"]), str(sub["state"]), who.name, svc.now())
        crit = {"criterion": body.criterion.strip(), "criteria_version": body.criteria_version.strip()}
        svc.audit.append("life.step", ruleset=rid, actor=who.name,
                         detail={"record": rec, "steps": [[before["state"] if before else None, sub["state"]]],
                                 "reason": body.reason, "source": "manual",
                                 **(crit if crit["criterion"] else {})})  # fmt: skip
        return {"subject": sub, "screening_log": why or "ok"}

    @r.post("/studies/{rs}/subjects/{record}/undo")
    def post_undo(rs: str, record: str, body: UndoBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        svc, rid, rec = get(), _rs(rs), _rec(record)
        life = Lifecycle(svc.dc)
        before = life.subject(rid, rec)
        try:
            sub = life.undo(rid, rec, by=who.name, at=svc.stamp(), note=body.note)
        except LifeError as exc:
            raise _refused(exc) from exc
        why = mirror(svc.registry, rid, str(sub["pid"]), str(sub["state"]), who.name, svc.now())
        svc.audit.append("life.step", ruleset=rid, actor=who.name,
                         detail={"record": rec, "steps": [[before["state"] if before else None, sub["state"]]],
                                 "source": "undo", "reason": " ".join(body.note.split())})  # fmt: skip
        return {"subject": sub, "screening_log": why or "ok"}

    @r.get("/studies/{rs}/schedule")
    def get_schedule(rs: str) -> dict[str, Any]:
        rid = _rs(rs)
        life = Lifecycle(get().dc)
        vers = [{"version": v["version"], "effective_from": v["effective_from"], "origin": v["origin"], "at": v["at"]}
                for v in life.schedule_versions(rid)]  # fmt: skip
        return {"study": rid, "visits": [v.as_dict() for v in life.schedule(rid)], "versions": vers}

    def put(rid: str, visits: list[Visit], origin: str, by: str, effective_from: str = "") -> dict[str, Any]:
        svc = get()
        try:
            version = Lifecycle(svc.dc).set_schedule(rid, visits, origin, svc.stamp(), effective_from.strip())
        except LifeError as exc:
            raise _refused(exc) from exc
        svc.audit.append("life.schedule", ruleset=rid, actor=by,
                         detail={"visits": [v.name for v in visits], "origin": origin, "version": version,
                                 "effective_from": effective_from.strip()})  # fmt: skip
        return {"study": rid, "visits": [v.as_dict() for v in visits], "origin": origin, "version": version,
                "effective_from": effective_from.strip()}  # fmt: skip

    @r.put("/studies/{rs}/schedule")
    def put_schedule(rs: str, body: ScheduleBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        visits = [Visit(v.visit.strip().lower(), v.day, v.before, v.after, v.anchor, dict(v.labels))
                  for v in body.visits]  # fmt: skip
        return put(_rs(rs), visits, "trialbox", who.name, body.effective_from)

    @r.post("/studies/{rs}/schedule/redcap")
    def schedule_from_redcap(rs: str, body: ScheduleRedcapBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        """REDCap's arms and events become the schedule: the event's unique name is the visit, ``day_offset`` the
        day, ``offset_min`` and ``offset_max`` the window. Arm 1 only (one schedule per study in v1)."""
        from rc_bridge.client import RcError

        svc, rid = get(), _rs(rs)
        try:
            with svc.client(body.token_ref) as rc:
                events = rc.events()
        except RcError as exc:
            if "classic" in exc.message:  # REDCap: a classic project has no arms or events
                events = []
            else:
                raise HTTPException(status_code=502 if exc.code == "RC-UPSTREAM" else 409,
                                    detail={"code": exc.code, "message": exc.message}) from exc  # fmt: skip
        if not events:
            raise HTTPException(status_code=409, detail={"code": "LIFE-STEP", "why": "no_events",
                                                         "message": "the REDCap project has no events"})  # fmt: skip
        arm = min(int(e.get("arm_num") or 1) for e in events)
        visits = []
        for e in sorted((e for e in events if int(e.get("arm_num") or 1) == arm),
                        key=lambda e: float(e.get("day_offset") or 0)):  # fmt: skip
            name = str(e["unique_event_name"])
            visits.append(Visit(name, round(float(e.get("day_offset") or 0)), round(float(e.get("offset_min") or 0)),
                                round(float(e.get("offset_max") or 0)), body.anchor,
                                {"en": str(e.get("event_name") or name)}))  # fmt: skip
        return put(rid, visits, "redcap", who.name)

    @r.get("/studies/{rs}/visits", dependencies=[NOTIFY_READ])
    def get_visits(rs: str, today: str = "") -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        day = _today(svc, today)
        rows = visit_rows(Lifecycle(svc.dc), rid, day)
        return {"study": rid, "today": day.isoformat(), "rows": rows, "list": lc.worklist(rows, day)}

    @r.get("/studies/{rs}/aes", dependencies=[NOTIFY_READ])
    def get_aes(rs: str, today: str = "", now: str = "") -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        day = _today(svc, today)
        rules = sae_rules(svc, rid)
        aes = aes_of(svc, rid, None, day, _now(svc, day, now), rules)
        pids = {str(s["record"]): str(s["pid"]) for s in Lifecycle(svc.dc).subjects(rid)}
        for a in aes:
            a["pid"] = pids.get(str(a["record"]), "")
        alert = bool(set(rules["problems"]) & set(lc.RULE_ALERTS))
        return {"study": rid, "today": day.isoformat(), "aes": aes, "serious": [a for a in aes if a["serious"]],
                "unacked": [a for a in aes if a["needs_ack"]],
                "overdue": [a for a in aes if a["overdue"]],
                "alerts": [a for a in aes if a["serious"] and (a["noclock"] or alert)], "rules": rules}  # fmt: skip

    @r.get("/studies/{rs}/sae-rule")
    def get_sae_rule(rs: str) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        sets = {
            k: {"country": v.country, "regulator": v.regulator, "parties": v.parties} for k, v in lc.RULE_SETS.items()
        }
        row = Lifecycle(svc.dc).sae_rule(rid) or {}
        return {"study": rid, "rule_set": str(row.get("rule_set") or ""), "rules": sae_rules(svc, rid), "sets": sets}

    @r.put("/studies/{rs}/sae-rule")
    def put_sae_rule(rs: str, body: SaeRuleBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        """The study's SAE rule set (D-277); the person who saves it confirms it. Audited ``life.sae_rule``."""
        svc, rid = get(), _rs(rs)
        life = Lifecycle(svc.dc)
        old = str((life.sae_rule(rid) or {}).get("rule_set") or "")
        try:
            row = life.set_sae_rule(rid, body.rule_set, who.name, svc.stamp())
        except LifeError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "why": exc.why,
                                                         "message": exc.message}) from exc  # fmt: skip
        svc.audit.append("life.sae_rule", ruleset=rid, actor=who.name,
                         detail={"old": old, "new": body.rule_set, "at": row["confirmed_at"]})  # fmt: skip
        return {"study": rid, "rule_set": row["rule_set"], "rules": sae_rules(svc, rid, life)}

    @r.get("/studies/{rs}/contact-rule")
    def get_contact_rule(rs: str) -> dict[str, Any]:
        """D-407 (LIFE-017): the study's contact-attempt limit and the days between two attempts."""
        rid = _rs(rs)
        return {"study": rid, **Lifecycle(get().dc).contact_rule(rid)}

    @r.put("/studies/{rs}/contact-rule")
    def put_contact_rule(rs: str, body: ContactRuleBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        life = Lifecycle(svc.dc)
        old = life.contact_rule(rid)
        try:
            row = life.set_contact_rule(rid, body.max_attempts, body.min_days, who.name, svc.stamp())
        except LifeError as exc:
            raise _refused(exc) from exc
        svc.audit.append("life.contact_rule", ruleset=rid, actor=who.name,
                         detail={"old": [old["max_attempts"], old["min_days"]],
                                 "new": [row["max_attempts"], row["min_days"]]})  # fmt: skip
        return {"study": rid, **row}

    @r.get("/studies/{rs}/consent-ages")
    def get_consent_ages(rs: str) -> dict[str, Any]:
        """10C-19 (D-1232): whether consent by a representative and assent are recorded here (the setting), and the
        study's age of majority and assent ages, as the contact rule (who may read the set-up page)."""
        from datacore import proxy_consent

        rid = _rs(rs)
        return {"study": rid, "on": proxy_consent.is_on(), **Lifecycle(get().dc).consent_age_rule(rid)}

    @r.put("/studies/{rs}/consent-ages")
    def put_consent_ages(rs: str, body: ConsentAgesBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        life = Lifecycle(svc.dc)
        old = life.consent_age_rule(rid)
        try:
            row = life.set_consent_age_rule(rid, body.majority, body.assent_from, body.assent_to, who.name,
                                            svc.stamp())  # fmt: skip
        except LifeError as exc:
            raise _refused(exc) from exc
        keys = ("majority", "assent_from", "assent_to")
        svc.audit.append("life.consent_ages", ruleset=rid, actor=who.name,
                         detail={"old": [old[k] for k in keys], "new": [row[k] for k in keys]})  # fmt: skip
        return {"study": rid, **row}

    @r.get("/studies/{rs}/deviations/possible", dependencies=[PATIENT_READ])
    def get_possible_deviations(rs: str, today: str = "", icf: str = "") -> dict[str, Any]:
        """D-407 (LIFE-025): the possible deviations the box's facts show, each open, confirmed or dismissed."""
        svc, rid = get(), _rs(rs)
        day = _today(svc, today)
        rows = Lifecycle(svc.dc).possible_deviations(rid, day, icf[:40])
        return {"study": rid, "today": day.isoformat(), "rows": rows,
                "open": sum(1 for x in rows if x["state"] == "open")}  # fmt: skip

    @r.post("/studies/{rs}/deviations/possible")
    def post_deviation_call(rs: str, body: DeviationCallBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        """Confirm (a deviation entry is written) or dismiss (with a reason) one possible deviation; audited
        ``life.deviation_call``."""
        svc, rid, rec = get(), _rs(rs), _rec(body.record)
        try:
            out = Lifecycle(svc.dc).decide_deviation(rid, rec, body.key, body.decision, reason=body.reason,
                                                     by=who.name, at=svc.stamp(), today=_today(svc, body.today),
                                                     icf_version=body.icf)  # fmt: skip
        except LifeError as exc:
            svc.audit.append("life.refused", ruleset=rid, actor=who.name,
                             detail={"record": rec, "deviation": body.key[:80], "why": exc.why})  # fmt: skip
            raise _refused(exc) from exc
        svc.audit.append("life.deviation_call", ruleset=rid, actor=who.name,
                         detail={"record": rec, "key": out["key"], "decision": body.decision,
                                 "event": out["event"]})  # fmt: skip
        return {"study": rid, "row": out}

    @r.post("/studies/{rs}/aes/{record}/{event}/ack")
    def post_ack(rs: str, record: str, event: str, body: AckBody, who: Claim = AS_ACK) -> dict[str, Any]:
        """The investigator has seen this serious AE (P-02, D-143): one tap, who and when, audited."""
        svc, rid, rec = get(), _rs(rs), _rec(record)
        life = Lifecycle(svc.dc)
        one = next((e for e in life.entries(rid, rec, AE_EVENT) if e["event"] == event), None)
        if one is None or not lc.is_serious(one):
            raise HTTPException(status_code=404, detail={"code": "LIFE-SAE", "message": "no such serious AE"})
        ack = life.ack(rid, rec, event, who.name, svc.stamp())
        svc.audit.append("life.sae_ack", ruleset=rid, actor=who.name,
                         detail={"record": rec, "event": event, "at": ack["at"], "by": ack["who"],
                                 "outcome": one.get("ae_outcome", "")})  # fmt: skip
        return {"study": rid, "record": rec, "event": event, "ack_by": ack["who"], "ack_at": ack["at"]}

    @r.get("/studies/{rs}/report", dependencies=[PATIENT_READ])
    def get_report(rs: str) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        life = Lifecycle(svc.dc)
        return {"study": rid, **lc.report(life.subjects(rid), life.steps(rid))}

    @r.get("/studies/{rs}/report/{fmt}")
    def get_report_file(rs: str, fmt: str, who: Claim = AS_READ) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        if fmt not in ("csv", "xlsx"):
            raise HTTPException(status_code=404, detail={"code": "LIFE-REPORT", "message": "csv or xlsx"})
        life = Lifecycle(svc.dc)
        files = report_files(lc.report(life.subjects(rid), life.steps(rid)), rid, svc.stamp())
        name = f"enrolment_{rid}_{svc.now().strftime('%Y%m%d')}.{fmt}"
        svc.audit.append("life.report", ruleset=rid, actor=who.name, detail={"format": fmt})
        if fmt == "xlsx":
            return {"name": name, "media_type": XLSX, "b64": base64.b64encode(files["xlsx"]).decode()}
        return {"name": name, "media_type": "text/csv", "text": files["csv"]}

    return r
