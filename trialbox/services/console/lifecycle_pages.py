"""TB-PLAN-04 step 5 (D-134): the trial lifecycle in the console, and its ``/api/v1`` routes (D-125, D-127).

* **Participants** (``/studies/{rs}/subjects``): every screening number of the study and its state; one participant
  (``/studies/{rs}/subjects/{record}``) with the next legal steps, Undo, every step so far, the visits with their
  windows, the AEs (several, on events ``ae1``, ``ae2`` ...) and deviations (``dv1`` ...). An illegal step is refused
  with a plain reason, on the page and in ``/api/v1``.
* **Visits** (``/studies/{rs}/visits``): the coordinator's list, today, this week and overdue; "Done today" opens the
  visit form filled in for today (two taps: the button, Save), "Open the visit form" opens it as it is. The same
  list is on the coordinator's home page; serious AEs are on the investigator's (and the coordinator's) home page.
* **Visit schedule** (``/studies/{rs}/schedule``): typed in, or read from REDCap's arms and events.
* **Enrolment report** (``/studies/{rs}/enrolment``, ``.csv``, ``.xlsx``).
* **Possible deviations** (``/studies/{rs}/deviations``, D-407, LIFE-025): proposals from the box's own facts, each
  confirmed by the coordinator (a deviation entry is written) or dismissed with a reason.

Everything goes through the orchestrator's lifecycle API (``orchestrator.lifecycle_api``); each page first asks it
to bring the participants up to date with the site store's screening numbers. "Today" is the site's local date
(``site.tz``: Asia/Tokyo, Asia/Taipei). Roles as on the Entry page: the study's coordinator records steps and the
schedule; the investigator and the admin read; viewer and CRA accounts get 403; CRO and other-study accounts 404.
"""

from __future__ import annotations

import base64
import contextlib
import logging
import re
from datetime import date
from typing import Any
from urllib.parse import quote, urlencode

from datacore import proxy_consent
from datacore.lifecycle import ON_STUDY
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from tb_common.csvfile import for_spreadsheet
from tb_common.erased import is_erased

from console import actor, people_lists, s28
from console import person_state as ps
from console.api_first import before_body, page_twin
from console.auth import Session
from console.backend import Problem, Unavailable, service_and_status
from console.data_pages import err_of
from console.entry_pages import can_enter, record_key
from console.home import Helpers
from console.i18n import lookup, translate
from console.screening_log import criteria_choices
from console.studies import known_study
from console.timefmt import local_today, site_zone

ENTER = "study.setup"  # the matrix row of who records the participants (T-715, D-483: signed with every call)

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VISIT = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATES = ("candidate", "approached", "consented", "enrolled", "on_study", "completed", "withdrawn", "screen_fail")
FINAL_STEPS = ("withdrawn", "screen_fail")  # WALK-1 (F-11): the final steps that take a reason, confirmed first
SF_REASONS = ("not_eligible", "declined", "lost_contact", "other")
WD_REASONS = ("1", "2", "3", "4", "5", "6")
SCHEDULE_ROWS = 4  # empty rows on the schedule page for new visits


class ApiStep(BaseModel):
    to: str = Field(max_length=20)
    on_day: str = Field(default="", max_length=10)
    reason: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=300)
    criterion: str = Field(default="", max_length=48)  # D-387: the criterion not met, on a "not_eligible" failure


class ApiVisit(BaseModel):
    visit: str = Field(max_length=41)
    day: int
    before: int = 0
    after: int = 0
    anchor: str = "enrolment"
    labels: dict[str, str] = Field(default_factory=dict)


class ApiSchedule(BaseModel):
    visits: list[ApiVisit]


def why_text(lang: str, exc: Problem) -> str:
    """A lifecycle refusal in the reader's language: the reason, with the states named in that language."""
    d = exc.detail
    key = f"life.why.{d.get('why') or 'other'}"

    def st(s: str) -> str:
        return translate(lang, f"life.state.{s}") if s in STATES else s

    if lookup(lang, key) is None:  # a reason with no sentence of its own
        return translate(lang, "life.why.other")
    allowed = ", ".join(st(x.strip()) for x in str(d.get("allowed") or "").split(",") if x.strip()) or "–"
    return translate(lang, key, state=st(str(d.get("state") or "")), to=st(str(d.get("to") or "")), allowed=allowed)


log = logging.getLogger("console.lifecycle")


def printable_report(data: bytes, lang: str) -> bytes:
    """NEW-UX-3b (D-699, UX-003): the enrolment workbook with a sheet for people, which it opens on: the study and
    when the file was made, then the states, the months, the screen-failure reasons and the withdrawals in the page's
    words, dates as dates, laid out to print (portrait, one page wide). The machine sheets stay as they are, ``states``
    first, for the systems that read them; the file stays byte-reproducible. A file that is not the report, or not
    of its shape, is handed over as it came."""
    try:
        return _printable_report(data, lang)
    except Exception as exc:  # another file or another shape: the machine file, never a half-made one
        log.warning("enrolment workbook handed over without its sheet for people (%s)", type(exc).__name__)
        return data


def _printable_report(data: bytes, lang: str) -> bytes:
    import io
    from datetime import date as day_

    from openpyxl import load_workbook
    from openpyxl.styles import Font
    from tb_common import sheets
    from tb_common.deterministic import normalize_ooxml

    wb = load_workbook(io.BytesIO(data))
    tables = {n: [list(r) for r in wb[n].iter_rows(values_only=True)]
              for n in ("states", "months", "screen_fail", "withdrawals")}  # fmt: skip
    about = {str(r[0]): r[1] for r in wb["about"].iter_rows(values_only=True) if r and len(r) > 1} if (
        "about" in wb.sheetnames) else {}  # fmt: skip

    def t(key: str) -> str:
        return translate(lang, key)

    def word(prefix: str, code: Any) -> Any:
        text = lookup(lang, prefix + str(code))
        return text if text is not None else code

    def as_day(v: Any) -> Any:
        try:
            return day_.fromisoformat(str(v)[:10]) if isinstance(v, str) and len(v) >= 10 else v
        except ValueError:
            return v

    ws = wb.create_sheet(t("enrol.xlsx.sheet")[:31], 1)
    ws.append([t("enrol.xlsx.sheet"), str(about.get("study") or ""), str(about.get("made") or "")])
    ws.cell(1, 1).font = Font(bold=True, size=13)
    heads: list[int] = []

    def section(title: str, head: list[str], rows: list[list[Any]]) -> None:
        ws.append([])
        ws.append([title])
        ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
        ws.append(head)
        heads.append(ws.max_row)
        for r in rows:
            ws.append(r)

    section(t("enrol.xlsx.states"), [t("registry.status"), t("enrol.xlsx.now"), t("enrol.xlsx.ever")],
            [[word("life.state.", r[0]), r[1], r[2]] for r in tables["states"][1:]])  # fmt: skip
    mo = tables["months"]
    section(t("enrol.xlsx.months"), [t("enrol.xlsx.month"), *[word("life.state.", c) for c in mo[0][1:]]],
            [list(r) for r in mo[1:]])  # fmt: skip
    section(t("enrol.xlsx.screen_fail"), [t("enrol.xlsx.reason"), t("enrol.xlsx.count")],
            [[word("life.reason.sf.", r[0]), r[1]] for r in tables["screen_fail"][1:]])  # fmt: skip
    section(t("enrol.xlsx.withdrawals"), [t("enrol.xlsx.record"), t("enrol.xlsx.day"), t("enrol.xlsx.reason")],
            [[r[0], as_day(r[1]), word("life.reason.wd.", r[2])] for r in tables["withdrawals"][1:]])  # fmt: skip
    for n in heads:
        for c in ws[n]:
            c.font = Font(bold=True)
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, day_):
                c.number_format = "yyyy-mm-dd"
    for letter in ("A", "B", "C", "D", "E", "F", "G", "H"):
        ws.column_dimensions[letter].width = 30 if letter == "A" else 18
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    wb.active = wb.index(ws)
    sheets.no_formulas(wb)  # NEW-CSV-1 (D-549): a typed reason stays text
    out = io.BytesIO()
    wb.save(out)
    return normalize_ooxml(out.getvalue())  # byte-reproducible, as the orchestrator's file (SPEC 11.2)


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store
    tz = site_zone(bk)

    def today() -> date:
        return local_today(h.clock(), tz)

    def lang_of(sess: Session) -> str:
        return sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.sponsor_form or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not sess.user.can_view_phi:
            au.append("console.denied", actor=h.actor(sess), detail={"action": f"participants {rid}"})
            raise h.problem(403, "forbidden")
        # D-273 (PV-3): an investigator reads a study's participants only as its PI or as a sub-investigator ticked
        # for screening or data entry, once the delegation log names a PI
        h.delegated(sess, rid, f"participants {rid}", ("screen", "enter_data"))
        return rid

    def need_enter(sess: Session, path: str) -> None:
        if not can_enter(sess.user):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")

    def screening(rid: str) -> dict[str, str]:
        try:
            return {no: pid for pid, no in store.screening_nos(rid).items()}
        except Exception:  # a store without the table answers no numbers
            return {}

    def refresh(rid: str, by: str, sess: Session | None = None) -> None:
        """Bring the participants up to date with the screening numbers and the screening log (idempotent). On a
        page this is the coordinator's (who records); an investigator, an administrator or a reader only reads."""
        if sess is not None and not can_enter(sess.user):
            return
        path, body = f"/studies/{rid}/subjects/refresh", {"screening": screening(rid)}
        with contextlib.suppress(Problem, Unavailable):
            if sess is not None:  # T-715 (D-483): the person signed; the notice timer as its own principal
                actor.call(h, sess, ENTER, rid, "POST", path, body)
            else:
                s28.call(bk, "POST", path, body, headers=actor.assert_service(by, ENTER, rid, "POST", path, body))

    def get(path: str) -> Any:
        return s28.call(bk, "GET", path)

    def short_of(sub: dict[str, Any]) -> str:
        pid = str(sub.get("pid") or "")
        return pid[:8] if pid and not is_erased(pid) else ""  # D-875: a token is never shown

    # ------------------------------------------------------------------ actions (one per page and /api/v1)
    def apply_step(sess: Session, path: str, rs: str, record: str, to: str, on_day: str, reason: str,
                   note: str, criterion: str = "") -> dict[str, Any]:  # fmt: skip
        rid, rec, body, criterion = check_step(sess, path, rs, record, to, on_day, reason, note, criterion)
        out = dict(actor.call(h, sess, ENTER, rid, "POST", f"/studies/{rid}/subjects/{quote(rec)}/step", body))
        au.append("console.life_step", ruleset=rid, actor=h.actor(sess),
                  detail={"record": rec, "to": to, **({"criterion": criterion} if criterion else {})})  # fmt: skip
        return out

    def check_step(sess: Session, path: str, rs: str, record: str, to: str, on_day: str, reason: str,
                   note: str, criterion: str = "") -> tuple[str, str, dict[str, Any], str]:  # fmt: skip
        """Every check of a step before it is sent (who, the closed study, the record, the day, the criterion): the
        page runs them before its confirmation sheet too (WALK-1, the review of D-1153), so a sheet is never shown for
        a step that would be refused. Returns (study, record, body, criterion)."""
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        rec = record_key(record)
        if to in ON_STUDY and store.study_state(rid).state == "closed":  # NEW-LIFE-6 (D-763)
            raise Problem(409, "LIFE-STEP", "the study is closed", [], detail={"why": "closed", "to": to})
        if not _REC.match(rec) or (on_day and not _DAY.match(on_day)):
            raise Problem(400, "LIFE-STEP", "bad record or day", ["day"], detail={"why": "day"})
        body = {"to": to, "on_day": on_day, "reason": reason, "note": note[:300], "today": today().isoformat()}
        # D-387 (LIFE-016): "not eligible" names the criterion not met, from the latest list's approved criteria;
        # the criteria version is the list's, never typed
        criterion = criterion.strip()
        if criterion and (to != "screen_fail" or reason != "not_eligible"):
            raise Problem(400, "LIFE-STEP", "only not_eligible names a criterion", ["criterion"],
                          detail={"why": "criterion_only"})  # fmt: skip
        if to == "screen_fail" and reason == "not_eligible":
            version, ids = criteria_choices(bk, rid)
            if (ids and criterion not in ids) or (criterion and not ids):
                raise Problem(400, "LIFE-STEP", "choose the criterion not met", ["criterion"],
                              detail={"why": "criterion"})  # fmt: skip
            if criterion:
                body.update({"criterion": criterion, "criteria_version": version})
        return rid, rec, body, criterion

    def apply_undo(sess: Session, path: str, rs: str, record: str, note: str = "") -> dict[str, Any]:
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        rec = record_key(record)
        if store.study_state(rid).state == "closed":  # NEW-LIFE-6 (D-763): an undo could put a subject back on study
            raise Problem(409, "LIFE-STEP", "the study is closed", [], detail={"why": "closed"})
        body = {"note": " ".join(note.split())[:300]}  # D-778: the reason
        out = dict(actor.call(h, sess, ENTER, rid, "POST", f"/studies/{rid}/subjects/{quote(rec)}/undo", body))
        au.append("console.life_step", ruleset=rid, actor=h.actor(sess), detail={"record": rec, "to": "undo"})
        return out

    def apply_schedule(sess: Session, path: str, rs: str, visits: list[dict[str, Any]]) -> dict[str, Any]:
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        out = dict(actor.call(h, sess, ENTER, rid, "PUT", f"/studies/{rid}/schedule", {"visits": visits}))
        au.append("console.life_schedule", ruleset=rid, actor=h.actor(sess), detail={"visits": len(visits)})
        return out

    def apply_schedule_redcap(sess: Session, path: str, rs: str, token_ref: str) -> dict[str, Any]:
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        out = dict(actor.call(h, sess, ENTER, rid, "POST", f"/studies/{rid}/schedule/redcap",
                              {"token_ref": token_ref}))  # fmt: skip
        au.append("console.life_schedule", ruleset=rid, actor=h.actor(sess), detail={"origin": "redcap"})
        return out

    def read_report_file(sess: Session, rs: str, fmt: str) -> tuple[str, str, bytes]:
        rid = study_or_404(sess, rs)
        if fmt not in ("csv", "xlsx"):
            raise h.problem(404, "notfound")
        out = actor.call(h, sess, "phi.view", rid, "GET", f"/studies/{rid}/report/{fmt}")
        data = base64.b64decode(out["b64"]) if "b64" in out else str(out.get("text") or "").encode("utf-8")
        au.append("console.export", ruleset=rid, actor=h.actor(sess), detail={"filename": str(out["name"])})
        return str(out["name"]), str(out["media_type"]), data

    # ------------------------------------------------------------------ what other pages show (home, mail)
    def visits_of(rid: str, day: date) -> dict[str, Any] | None:
        try:
            out = get(f"/studies/{rid}/visits?today={day.isoformat()}")
            subs = {s["record"]: s for s in get(f"/studies/{rid}/subjects?today={day.isoformat()}")["subjects"]}
        except (Problem, Unavailable):
            return None
        for r in [*out["rows"], *(x for rows in out["list"].values() for x in rows)]:
            r["short"] = short_of(subs.get(r["record"], {}))
            r["pid"] = str(subs.get(r["record"], {}).get("pid") or "")
        return dict(out)

    def aes(rid: str) -> dict[str, Any]:
        try:
            return dict(get(f"/studies/{rid}/aes?today={today().isoformat()}"))
        except (Problem, Unavailable):  # CR-010: never "no SAE" when the answer is unknown; the pages say so
            return {"unacked": [], "overdue": [], "failed": True}

    def serious(rid: str) -> list[dict[str, Any]]:
        """Serious AEs the investigator has not acknowledged, whatever their outcome (review 2026-11-09 P-02: a fatal
        SAE used to leave the banner and N1 the moment it was saved, as "not ongoing")."""
        return list(aes(rid).get("unacked") or [])

    def reports_due(rid: str) -> list[dict[str, Any]]:
        """One row per overdue report of a serious AE (P-03): participant, party, due date. The review of D-766: a
        serious AE with no clock at all (no rule set chosen) is listed too, as "no deadline", never left out."""
        got = aes(rid)
        rows = [{**a, "party": c["party"], "due": c["due"]} for a in got.get("overdue") or []
                for c in a["clock"] if c["overdue"]]  # fmt: skip
        return rows + [{**a, "party": "no_clock", "due": ""} for a in got.get("aes") or []
                       if a.get("serious") and a.get("noclock")]  # fmt: skip

    def life_home(sess: Session) -> dict[str, Any]:
        """The home page's visit block and serious-AE alert, across the studies this account sees."""
        if not sess.user.can_view_phi or h.trials is None:
            return {"studies": [], "sae": [], "reports": []}
        day = today()
        studies, sae, reports, failed = [], [], [], []
        for r in h.trials(sess):  # read only: the lifecycle pages and the mail bring the participants up to date
            v = visits_of(r.id, day)
            if v is not None and v["rows"]:
                lst = v["list"]
                studies.append({"rs": r.id, "today": lst["today"], "week": lst["week"], "overdue": lst["overdue"]})
            got = aes(r.id)
            sae += [{**a, "rs": r.id} for a in got.get("unacked") or []]
            reports += [{**a, "rs": r.id} for a in (h.life_reports or reports_due)(r.id)]
            if got.get("failed"):
                failed.append(r.id)
        return {"studies": studies, "sae": sae, "reports": reports, "today": day.isoformat(), "sae_failed": failed}

    def life_mail(rid: str, day: date) -> dict[str, Any]:
        """N1/N2 (D-134): the study's visits on ``day`` and its serious AEs, by pseudonym (the mail adds the screening
        number beside it, D-136; never a chart number in mail)."""
        refresh(rid, actor.NOTIFY)
        with actor.reading_as(actor.NOTIFY):  # NEW-SEC-1 (D-717): the morning mail's patient reads, signed as it
            return mail_rows(rid, day)

    def mail_rows(rid: str, day: date) -> dict[str, Any]:
        if h.sae_sync is not None:
            h.sae_sync(rid)  # D-277: the daily job writes what reached the data core another way (REDCap, the API)
        v = visits_of(rid, day)
        nos = store.screening_nos(rid)

        def short(pid: str) -> str:  # the screening number beside the pseudonym (D-136); never a chart number
            if is_erased(pid):  # D-875: a token is never shown
                return f"– ({nos[pid]})" if pid in nos else "–"
            return f"{pid[:8]} ({nos[pid]})" if pid in nos else pid[:8] or "–"

        reports = [{"short": short(str(a.get("pid") or "")), "party": a["party"], "due": a["due"]}
                   for a in (h.life_reports or reports_due)(rid)]  # fmt: skip
        if v is None:
            return {"today": [], "week": [], "overdue": [], "sae": len(serious(rid)), "reports": reports}
        lst = v["list"]
        keep = ("short", "visit", "due", "start", "end")

        def row(r: dict[str, Any]) -> dict[str, Any]:
            return {x: r[x] for x in keep} | {"short": short(str(r.get("pid") or ""))}

        return {k: [row(r) for r in lst[k]] for k in ("today", "week", "overdue")} | {
            "sae": len(serious(rid)), "reports": reports}  # fmt: skip

    h.life_home = life_home
    h.life_mail = life_mail
    h.life_sae = serious
    h.life_reports = reports_due

    def apply_ack(sess: Session, path: str, rs: str, record: str, event: str) -> dict[str, Any]:
        """The investigator acknowledges a serious AE (P-02, D-143): one tap, the study's investigator only."""
        rid = study_or_404(sess, rs)
        if not h.permit(sess.user, "sae.ack"):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        rec, ev = record_key(record[:64]), event.strip().lower()
        if not _REC.match(rec) or not re.fullmatch(r"ae\d{1,3}", ev):
            raise h.problem(404, "notfound")
        out = dict(actor.call(h, sess, "sae.ack", rid, "POST", f"/studies/{rid}/aes/{quote(rec)}/{ev}/ack", {}))
        au.append("console.sae_ack", ruleset=rid, actor=h.actor(sess),
                  detail={"record": rec, "event": ev, "at": out.get("ack_at")})  # fmt: skip
        if h.sae_sync is not None:
            h.sae_sync(rid)  # D-277: the register's trail takes the acknowledgement on the write path
        return out

    # ------------------------------------------------------------------ pages
    @app.get("/studies/{rs}/subjects")
    def subjects_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        err = None
        subs: list[dict[str, Any]] = []
        try:
            out = get(f"/studies/{rid}/subjects?today={today().isoformat()}")
            subs = out["subjects"]
        except (Problem, Unavailable) as exc:
            err = err_of(exc)
        # D-1221 (review R10): each participant's one state, from the same function as every other list
        people = ps.read(h, rid, subjects=subs if err is None else None)
        for s in subs:
            s["person"] = people.of(str(s.get("pid") or "") or f"#{s.get('record')}")
        counts = ps.counts(s["person"] for s in subs)  # one per row: a kept record of an opted-out person too
        # J-5 (D-1223, flag layout.people_lists), only when the page is served as a view of Participants (off: as
        # before). The default view divides at consent by the one state: the people who have consented, none opted out
        # or erased, and (for whom the log's page admits) a participant the log names first; the working view "every
        # record" is the page as it was. Either filters by the one state (``?state=``), never by the record's own step
        lst = people_lists.default_of(request)
        view = getattr(request.state, "people", None)
        readable = people.readable or not subs
        keep: tuple[str, ...] = ps.STATES
        if lst == "participants":
            on_side = people_lists.side(people, "participants")
            keys = {str(s.get("pid") or "") or f"#{s.get('record')}" for s in subs}
            subs = [s for s in subs if (str(s.get("pid") or "") or f"#{s.get('record')}") in on_side]
            # a participant the screening log names before a record exists: only for whom the log's own page admits
            # (``Helpers.rows_ok``, the screening log's question); anyone else sees the participant records only
            if h.rows_ok(sess.user, rid):
                subs += [{"record": "", "pid": pid, "since": st.since[:10], "visits": {}, "person": st,
                          "log_only": True} for pid, st in sorted(on_side.items()) if pid not in keys]  # fmt: skip
            counts = ps.counts(s["person"] for s in subs)
            keep = ps.PARTICIPANT
        only = request.query_params.get("state", "") if view else ""
        only = only if only in keep else ""
        if only:
            subs = [s for s in subs if s["person"].name == only]
        return h.page(request, "life_subjects.html", sess, rs=rid, subjects=subs, err=err, only=only,
                      shown=ps.shown_counts(counts, keep), readable=readable)  # fmt: skip

    def subject_page(request: Request, sess: Session, rid: str, rec: str, status: int = 200,
                     refused: str = "", done: str = "") -> Response:  # fmt: skip
        err = None
        one: dict[str, Any] = {}
        try:
            one = dict(get(f"/studies/{rid}/subjects/{quote(rec)}?today={today().isoformat()}"))
        except (Problem, Unavailable) as exc:
            if isinstance(exc, Problem) and exc.status == 404:
                raise h.problem(404, "notfound") from exc
            err = err_of(exc)
        sf_version, sf_criteria = criteria_choices(bk, rid)  # D-387: the pick list for "not eligible"
        sub = one.get("subject") if isinstance(one.get("subject"), dict) else None
        person = None  # D-1221: the participant's one state, as every list names it
        if sub is not None:
            person = ps.read(h, rid, subjects=[sub]).of(str(sub.get("pid") or "") or f"#{sub.get('record')}")
        # J-4 (D-1224, walk F-18): the way back to the patient sheet, only for a reader the sheet admits by its own
        # rights (``h.reads``, the sheet's check) and never for an erased pseudonym (D-875: a token is never shown)
        pid = str((one.get("subject") or {}).get("pid") or "")
        sheet_pid = pid if pid and short_of({"pid": pid}) and h.reads(sess.user, rid) else ""
        return h.page(request, "life_subject.html", sess, status=status, rs=rid, record=rec, one=one, err=err,
                      sheet_pid=sheet_pid,
                      editable=can_enter(sess.user), refused=refused, done=done, sf_reasons=SF_REASONS,
                      proceed_reasons=proxy_consent.PROCEED_REASONS,
                      wd_reasons=WD_REASONS, today=today().isoformat(), sf_criteria=sf_criteria,
                      sf_version=sf_version, person=person)  # fmt: skip

    @app.get("/studies/{rs}/subjects/{record}")
    def subject(request: Request, rs: str, record: str, done: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        rec = record_key(record[:64])
        if not _REC.match(rec):
            raise h.problem(404, "notfound")
        refresh(rid, h.actor(sess), sess)
        return subject_page(request, sess, rid, rec, done=done if done in ("step", "undo", "entry", "ack") else "")

    @app.post("/studies/{rs}/subjects/{record}/step")
    async def subject_step(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        rec = record_key(record[:64])
        to, on_day, reason, note = (str(data.get(k) or "").strip()[:300] for k in ("to", "on_day", "reason", "note"))
        proceed = str(data.get("proceed") or "").strip()[:40]
        if proceed and to in proxy_consent.FORWARD:  # D-1232: why a person goes on after a declined assent
            reason = proceed
        criterion = str(data.get("criterion") or "").strip()[:48] if reason == "not_eligible" else ""
        reasons = WD_REASONS if to == "withdrawn" else SF_REASONS
        if (to in FINAL_STEPS and reason in reasons and str(data.get("confirm") or "") != "yes"
                and h.confirm is not None):  # fmt: skip
            try:  # the review of D-1153: every check first, so no sheet is shown for a step that would be refused
                check_step(sess, request.url.path, rid, rec, to, on_day, reason, note, criterion)
            except Problem as exc:
                return subject_page(request, sess, rid, rec, status=409, refused=why_text(lang_of(sess), exc))
            # WALK-1 (F-11, D-178): a final step is named before it is recorded (no reason: refused as before)
            lang = lang_of(sess)
            key = f"life.reason.{'wd' if to == 'withdrawn' else 'sf'}.{reason}"
            words = translate(lang, key)
            text = translate(lang, "life.confirm.final", step=translate(lang, f"life.state.{to}"), record=rec,
                             reason=reason if words == key else words)  # fmt: skip
            fields = {k: v for k, v in (("to", to), ("on_day", on_day), ("reason", reason), ("note", note),
                                        ("criterion", criterion)) if v}  # fmt: skip
            return h.confirm(request, sess, text, request.url.path, fields, f"/studies/{rid}/subjects/{quote(rec)}")
        try:
            apply_step(sess, request.url.path, rid, rec, to, on_day, reason, note, criterion)
        except Problem as exc:
            return subject_page(request, sess, rid, rec, status=409, refused=why_text(lang_of(sess), exc))
        except Unavailable as exc:
            return subject_page(request, sess, rid, rec, status=503, refused=str(exc)[:120])
        return RedirectResponse(f"/studies/{rid}/subjects/{quote(rec)}?done=step", status_code=303)

    @app.post("/studies/{rs}/subjects/{record}/undo")
    async def subject_undo(request: Request, rs: str, record: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        rec = record_key(record[:64])
        try:
            apply_undo(sess, request.url.path, rid, rec, str(data.get("note") or ""))
        except Problem as exc:
            return subject_page(request, sess, rid, rec, status=409, refused=why_text(lang_of(sess), exc))
        return RedirectResponse(f"/studies/{rid}/subjects/{quote(rec)}?done=undo", status_code=303)

    @app.post("/studies/{rs}/subjects/{record}/aes/{event}/ack")
    async def sae_ack(request: Request, rs: str, record: str, event: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        try:
            apply_ack(sess, request.url.path, rs, record, event)
        except Problem as exc:
            raise h.problem(404 if exc.status == 404 else 409, "notfound" if exc.status == 404 else "request.refused",
                            reason=exc.message) from exc  # fmt: skip
        rid, rec = rs.strip().upper(), record_key(record[:64])
        back = str(data.get("back") or "")
        if back == "home":
            return RedirectResponse("/home?sae=acked", status_code=303)
        if back == "week":
            return RedirectResponse(f"/studies/{rid}/week?sae=acked", status_code=303)
        return RedirectResponse(f"/studies/{rid}/subjects/{quote(rec)}?done=ack", status_code=303)

    @app.get("/studies/{rs}/visits")
    def visits_page(request: Request, rs: str, saved: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        day = today()
        v = visits_of(rid, day)
        sched: list[Any] = []
        with contextlib.suppress(Problem, Unavailable):
            sched = list(get(f"/studies/{rid}/schedule")["visits"])
        return h.page(request, "life_visits.html", sess, rs=rid, v=v, schedule=sched, today=day.isoformat(),
                      editable=can_enter(sess.user), saved=saved[:80],
                      err=None if v is not None else {"code": "unavailable", "fields": ""})  # fmt: skip

    @app.get("/studies/{rs}/schedule")
    def schedule_page(request: Request, rs: str, saved: str = "", err: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        sched: list[Any] = []
        conns: list[str] = []
        try:
            sched = list(get(f"/studies/{rid}/schedule")["visits"])
            conns = [c["token_ref"] for c in (get("/redcap/connections") or {}).get("connections", [])]
        except (Problem, Unavailable):
            pass
        return h.page(request, "life_schedule.html", sess, rs=rid, schedule=sched, blank=SCHEDULE_ROWS, conns=conns,
                      editable=can_enter(sess.user), saved=saved[:10], refused=err[:300])  # fmt: skip

    @app.post("/studies/{rs}/schedule")
    async def schedule_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        try:
            if str(data.get("action") or "") == "redcap":
                out = apply_schedule_redcap(sess, request.url.path, rid, str(data.get("token_ref") or "")[:40])
            else:
                visits = []
                names, labels = data.getlist("visit"), data.getlist("label")
                days, before, after = data.getlist("day"), data.getlist("before"), data.getlist("after")
                anchors = data.getlist("anchor")
                lang = lang_of(sess)
                for i, raw in enumerate(names):
                    name = str(raw).strip().lower()
                    if not name:
                        continue

                    def num(xs: list[Any], i: int = i) -> int:
                        try:
                            return int(str(xs[i]).strip() or 0)
                        except (ValueError, IndexError):
                            return 99999  # refused by the orchestrator with the window's plain reason

                    label = str(labels[i]).strip()[:80] if i < len(labels) else ""
                    visits.append({"visit": name[:41], "day": num(days), "before": num(before), "after": num(after),
                                   "anchor": str(anchors[i]) if i < len(anchors) else "enrolment",
                                   "labels": {lang: label} if label else {}})  # fmt: skip
                out = apply_schedule(sess, request.url.path, rid, visits)
        except Problem as exc:
            q = urlencode({"err": why_text(lang_of(sess), exc) if exc.code == "LIFE-STEP" else exc.code})
            return RedirectResponse(f"/studies/{rid}/schedule?{q}", status_code=303)
        except Unavailable:
            return RedirectResponse(f"/studies/{rid}/schedule?err=unavailable", status_code=303)
        return RedirectResponse(f"/studies/{rid}/schedule?saved={len(out.get('visits') or [])}", status_code=303)

    @app.get("/studies/{rs}/enrolment")
    def enrolment(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        rep: dict[str, Any] | None = None
        err = None
        try:
            rep = dict(get(f"/studies/{rid}/report"))
        except (Problem, Unavailable) as exc:
            err = err_of(exc)
        return h.page(request, "life_report.html", sess, rs=rid, rep=rep, states=STATES, err=err)

    # ------------------------------------------------------------------ possible deviations (D-407, LIFE-025)
    def icf_in_force(rid: str) -> str:
        """The consent form version of the study's IRB record (the console's team store), "" when none is kept."""
        try:
            return str(h.team.irb(rid).icf_version or "") if h.team is not None else ""
        except Exception:  # a store without the IRB table answers no version
            return ""

    def possible(rid: str) -> dict[str, Any]:
        q = urlencode({"today": today().isoformat(), "icf": icf_in_force(rid)})
        return dict(get(f"/studies/{rid}/deviations/possible?{q}"))

    def apply_deviation(sess: Session, path: str, rs: str, record: str, key: str, decision: str,
                        reason: str) -> dict[str, Any]:  # fmt: skip
        rid = study_or_404(sess, rs)
        need_enter(sess, path)
        rec = record_key(record[:64])
        if not _REC.match(rec):
            raise h.problem(404, "notfound")
        body = {"record": rec, "key": key[:80], "decision": decision, "reason": reason.strip()[:300],
                "today": today().isoformat(), "icf": icf_in_force(rid)}  # fmt: skip
        out = dict(actor.call(h, sess, ENTER, rid, "POST", f"/studies/{rid}/deviations/possible", body))
        au.append("console.deviation_call", ruleset=rid, actor=h.actor(sess),
                  detail={"record": rec, "key": key[:80], "decision": decision,
                          "event": str((out.get("row") or {}).get("event") or "")})  # fmt: skip
        return out

    def deviations_page(request: Request, sess: Session, rid: str, status: int = 200, refused: str = "",
                        done: str = "") -> Response:  # fmt: skip
        err = None
        out: dict[str, Any] = {"rows": [], "open": 0}
        try:
            out = possible(rid)
        except (Problem, Unavailable) as exc:
            err = err_of(exc)
        rows = list(out.get("rows") or [])
        order = {"open": 0, "confirmed": 1, "dismissed": 2}
        rows.sort(key=lambda r: (order.get(str(r.get("state")), 3), str(r.get("day") or ""), str(r.get("record"))))
        return h.page(request, "life_deviations.html", sess, status=status, rs=rid, rows=rows,
                      n_open=int(out.get("open") or 0), editable=can_enter(sess.user), err=err, refused=refused,
                      done=done)  # fmt: skip

    @app.get("/studies/{rs}/deviations")
    def deviations(request: Request, rs: str, done: str = "") -> Response:
        """The possible deviations the box's facts show (a visit outside its window, a consent form version not in
        force, enrolment before consent or while the screening log says not eligible). The coordinator confirms
        each (a deviation entry is written, then completed on the form) or dismisses it with a reason."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        return deviations_page(request, sess, rid, done=done if done in ("confirm", "dismiss") else "")

    @app.post("/studies/{rs}/deviations")
    async def deviation_call(request: Request, rs: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = study_or_404(sess, rs)
        decision = str(data.get("decision") or "")
        try:
            apply_deviation(sess, request.url.path, rid, str(data.get("record") or ""), str(data.get("key") or ""),
                            decision, str(data.get("reason") or ""))  # fmt: skip
        except Problem as exc:
            return deviations_page(request, sess, rid, status=409, refused=why_text(lang_of(sess), exc))
        except Unavailable as exc:
            return deviations_page(request, sess, rid, status=503, refused=str(exc)[:120])
        return RedirectResponse(f"/studies/{rid}/deviations?done={decision}", status_code=303)

    @app.get("/studies/{rs}/enrolment.{fmt}")
    def enrolment_file(request: Request, rs: str, fmt: str) -> Response:
        sess = h.need(request)
        try:
            name, media, data = read_report_file(sess, rs, fmt)
        except (Problem, Unavailable) as exc:
            raise h.problem(503, "unavailable", detail=service_and_status(exc)) from exc
        if media.startswith("text/csv"):
            data = for_spreadsheet(data)  # a file a person opens: Excel reads it as UTF-8 only with the mark
        elif fmt == "xlsx":
            data = printable_report(data, sess.lang)  # NEW-UX-3b (D-699): it opens on the report for people
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------------ /api/v1 (D-125, D-127)
    def api_session(request: Request) -> Session:
        assert h.api_session is not None, "console.home.register runs first"
        return h.api_session(request)

    def refused(sess: Session, exc: Exception) -> Response:
        if isinstance(exc, Unavailable):
            return JSONResponse({"error": "unavailable", "detail": {"detail": str(exc)[:200]}}, status_code=503)
        assert isinstance(exc, Problem)
        status = exc.status if 400 <= exc.status < 500 else 502
        detail = {"code": exc.code, "reason": exc.message, "fields": ", ".join(exc.fields)}
        if exc.code == "LIFE-STEP":
            detail.update({"why": str(exc.detail.get("why") or ""), "message": why_text(lang_of(sess), exc),
                           "allowed": str(exc.detail.get("allowed") or "")})  # fmt: skip
        return JSONResponse({"error": "request.refused", "detail": detail}, status_code=status)

    def masked(sess: Session, rid: str, sub: dict[str, Any]) -> dict[str, Any]:
        """J-4 (D-1224): the twin hides what the page hides: no erased token (D-875), and no pseudonym for a reader
        the patient sheet does not admit (``h.reads``)."""
        pid = str(sub.get("pid") or "")
        return {**sub, "pid": pid if pid and short_of({"pid": pid}) and h.reads(sess.user, rid) else ""}

    @app.get("/api/v1/studies/{rs}/subjects", response_model=None)
    def api_subjects(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        try:
            out = dict(get(f"/studies/{rid}/subjects?today={today().isoformat()}"))
            out["subjects"] = [masked(sess, rid, s) for s in out.get("subjects") or []]
            return {**out, "may_step": can_enter(sess.user)}
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/subjects/{record}", response_model=None)
    def api_subject(request: Request, rs: str, record: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        try:
            one = dict(get(f"/studies/{rid}/subjects/{quote(record_key(record[:64]))}?today={today().isoformat()}"))
            if isinstance(one.get("subject"), dict):
                one["subject"] = masked(sess, rid, one["subject"])
            return one
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    def first_enter(sess: Session, request: Request) -> None:
        """T-657 (D-444): the actions' own first checks, run before the body is read (console.api_first)."""
        study_or_404(sess, request.path_params["rs"])
        need_enter(sess, request.url.path)

    @app.post("/api/v1/studies/{rs}/subjects/{record}/step", response_model=None)
    @before_body(first_enter)
    def api_step(request: Request, rs: str, record: str, body: ApiStep) -> Any:
        sess = api_session(request)
        try:
            return {"study": rs.upper(), **apply_step(sess, request.url.path, rs, record, body.to, body.on_day,
                                                      body.reason, body.note, body.criterion)}  # fmt: skip
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.post("/api/v1/studies/{rs}/aes/{record}/{event}/ack", response_model=None)
    @page_twin("/studies/{rs}/subjects/{record}/aes/{event}/ack")
    def api_sae_ack(request: Request, rs: str, record: str, event: str) -> Any:
        sess = api_session(request)
        try:
            return apply_ack(sess, request.url.path, rs, record, event)
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/visits", response_model=None)
    def api_visits(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        v = visits_of(rid, today())
        if v is None:
            return refused(sess, Unavailable("the lifecycle does not answer"))
        return v

    @app.get("/api/v1/studies/{rs}/schedule", response_model=None)
    def api_schedule(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        try:
            return get(f"/studies/{rid}/schedule")
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.put("/api/v1/studies/{rs}/schedule", response_model=None)
    @before_body(first_enter)
    def api_schedule_put(request: Request, rs: str, body: ApiSchedule) -> Any:
        sess = api_session(request)
        try:
            return apply_schedule(sess, request.url.path, rs, [v.model_dump() for v in body.visits])
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/enrolment", response_model=None)
    def api_enrolment(request: Request, rs: str) -> Any:
        sess = api_session(request)
        rid = study_or_404(sess, rs)
        refresh(rid, h.actor(sess), sess)
        try:
            return get(f"/studies/{rid}/report")
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)

    @app.get("/api/v1/studies/{rs}/enrolment/{fmt}", response_model=None)
    def api_enrolment_file(request: Request, rs: str, fmt: str) -> Any:
        sess = api_session(request)
        try:
            name, media, data = read_report_file(sess, rs, fmt)
        except (Problem, Unavailable) as exc:
            return refused(sess, exc)
        return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
