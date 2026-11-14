"""D-191 (independent plan review PR-17): the SAE register's worklist and case pages.

* ``/sae``: every serious AE of the studies the account sees, overdue reports first, with an alert at the top
  (role="alert") counting the overdue reports, the reports sent late, the SAEs whose dates need checking and the cases
  no longer serious that still have open reports. Each row: the study, the participant's screening number and
  pseudonym, onset and the day the site learned of it, every report (first report and follow-ups) with its due day,
  sent day, the receiver's acknowledgement and its state, and the investigator's acknowledgement. Never the AE term:
  the participant page has it.
* ``/studies/{rs}/sae/{record}/{event}``: one case, the forms that record a report sent (written to the AE form; kept
  in the register for a case no longer serious, whose form hides the field), a receipt, a requested follow-up, a
  follow-up sent, closing an open report of a case no longer serious, and the trail.

A page view never writes (CR-012, D-277): the register is brought up to date with the AE forms
(``console.saerecord.SaeStore.sync``) on the write path, by :func:`register`'s ``h.sae_sync``: when an AE form is
saved through the console, after each entry on the case page, after the investigator's acknowledgement (here or on
the banner), on ``POST /studies/{rs}/sae/sync`` and by the daily notice job. What it reads from the forms is written
as ``system:sync`` with the form's author and time from the data core, never as the person viewing; a person's own
entries on the case page are written as that person. A new case is copied to the trial office's mailbox
(``TB_SAE_OFFICE_MAILBOX``), without the AE term.

The worklist and the case page name each study's rule set, its regulator (from the set's country, the same word in
every language: UX-005) and who confirmed it (D-277); the case page has the investigator's acknowledgement (UX-028)
and the trail in the reader's language. Every row is also a
``console.sae`` audit event with dates and parties only. Access: the role table ``tb_common.authz.ROLE_SAE_ACTIONS``
(deny by default) on top of the study scope of the lifecycle pages (a study the account does not see, or a CRO
account: 404); recording also needs the study's ``enter_data`` task (D-147).
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

from datacore import lifecycle as lc
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from tb_common.authz import sae_allowed

from console import actor, i18n_sae, s28
from console.auth import Session
from console.backend import Problem, Unavailable
from console.entry_pages import record_key
from console.home import Helpers
from console.i18n import CATALOGUES, translate
from console.saerecord import (
    PARTIES,
    SYNC,
    SaeError,
    SaeStore,
    case_view,
    check_ref,
    day_of,
    downgraded_view,
    followup_rules,
    office_notice,
    sort_key,
)
from console.studies import known_study
from console.timefmt import local_today, site_zone

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_EV = re.compile(r"^ae\d{1,3}$")
_ID = re.compile(r"[0-9]{1,18}")
AE_FORM = "tb_adverse_event"
DATE_ALERTS = ("nostart", "aware_before_onset", "future_date", "bad_sent", "serious_mismatch", "noclock")
RULE_ALERTS = set(lc.RULE_ALERTS)

for _lang, _cat in (("en", i18n_sae.EN), ("ja", i18n_sae.JA), ("zh-TW", i18n_sae.ZH)):
    CATALOGUES[_lang].update(_cat)


def register(app: FastAPI, h: Helpers, store: SaeStore | None = None) -> None:
    bk, au = h.bk, h.au
    tz = site_zone(bk)
    reg = store if store is not None else SaeStore()

    def today() -> date:
        return local_today(h.clock(), tz)

    def now() -> datetime:
        n = h.clock()
        return (n if n.tzinfo else n.replace(tzinfo=UTC)).astimezone(tz)

    def stamp() -> str:
        now = h.clock()
        return (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC).isoformat(timespec="seconds")

    def lang_of(sess: Session) -> str:
        return sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def delegated(sess: Session, rid: str) -> bool:
        """D-147: once a study's delegation log names a PI, an investigator sees its patients only as the PI or a
        sub-investigator ticked for "screen" (as on the week and candidate pages)."""
        return h.delegated_ok(sess.user, rid)

    def scope(sess: Session, rs: str, action: str, path: str) -> str:
        """The study, after the study scope (404) and the role table (403); recording also needs ``enter_data``."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.sponsor_form or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not sae_allowed(sess.user.role, action):
            raise deny(sess, path)
        if action == "record" and not h.permit(sess.user, "task.enter_data", rid):
            raise deny(sess, path)
        if not delegated(sess, rid):
            raise deny(sess, path)
        return rid

    def audit(rid: str, by: str, record: str, event: str, rows: list[dict[str, Any]]) -> None:
        for w in rows:  # dates, parties and staff only: the AE term never reaches the log
            au.append("console.sae", ruleset=rid, actor=by,
                      detail={"action": w["action"], "record": record, "event": event, **w["body"]})  # fmt: skip

    def form_author(rid: str, rec: str, ev: str) -> Callable[[], dict[str, str]]:
        """Who last changed the AE form and when (the data core's values), for a row the register writes as
        ``system:sync``: the person and time behind the change, not the person whose page view noticed it."""

        def get() -> dict[str, str]:
            try:
                vals = (s28.call(bk, "GET", f"/studies/{rid}/records/{quote(rec)}").get("values") or {}).get(ev) or {}
            except (Problem, Unavailable):
                return {}
            last = max((v for k, v in vals.items() if k.startswith("ae_") and isinstance(v, dict)),
                       key=lambda v: str(v.get("at") or ""), default=None)  # fmt: skip
            return {"form_by": str(last.get("by") or ""), "form_at": str(last.get("at") or "")} if last else {}

        return get

    def fetch(rid: str, day: date) -> dict[str, Any]:
        """The study's AEs with their clocks at the site's ``now`` and the study's rules. Raises Problem/Unavailable
        when the orchestrator does not answer."""
        q = f"today={day.isoformat()}&now={quote(now().isoformat(timespec='seconds'))}"
        return dict(s28.call(bk, "GET", f"/studies/{rid}/aes?{q}"))

    def views_of(rid: str, day: date, out: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read only: the worklist rows (serious, and no longer serious with open reports) and the cases no longer
        serious with nothing open."""
        fu, rules, at = followup_rules(os.environ.get("TB_SAE_FOLLOWUP_DAYS", "")), out.get("rules") or {}, now()
        seen: set[tuple[str, str]] = set()
        views: list[dict[str, Any]] = []
        lost: list[dict[str, Any]] = []
        for a in out.get("aes") or []:
            key = (str(a["record"]), str(a["event"]))
            if not a.get("serious"):
                continue
            seen.add(key)
            v = case_view(a, reg.case(rid, *key), reg.reports(rid, *key), day, fu, at, rules)
            v.update(rs=rid, term=str(a.get("ae_term") or ""))
            views.append(v)
        for c in reg.cases(rid):
            key = (str(c["record"]), str(c["event"]))
            if key in seen:
                continue
            v = downgraded_view(c, reg.reports(rid, *key), day)
            v["rs"] = rid
            (views if v["open"] else lost).append(v)
        return views, lost

    def load(rid: str, day: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        out = fetch(rid, day)
        views, lost = views_of(rid, day, out)
        return views, lost, dict(out.get("rules") or {})

    def sync_study(rid: str) -> list[dict[str, Any]]:
        """The write path (CR-012): bring the study's cases up to date with the AE forms as ``system:sync``, mark the
        cases no longer serious, and copy each new case to the trial office's mailbox. Returns the rows written."""
        day = today()
        out = fetch(rid, day)
        at, rules = stamp(), dict(out.get("rules") or {})
        fu = followup_rules(os.environ.get("TB_SAE_FOLLOWUP_DAYS", ""))
        seen: set[tuple[str, str]] = set()
        written: list[dict[str, Any]] = []
        for a in out.get("aes") or []:
            key = (str(a["record"]), str(a["event"]))
            if not a.get("serious"):
                continue
            seen.add(key)
            rows = reg.sync(rid, a, SYNC, at, form_author(rid, *key))
            audit(rid, SYNC, *key, rows)
            written += rows
            if any(w["action"] == "create" for w in rows):
                office_copy(
                    rid, case_view(a, reg.case(rid, *key), reg.reports(rid, *key), day, fu, now(), rules), rules
                )
        for c in reg.cases(rid):
            key = (str(c["record"]), str(c["event"]))
            if key not in seen:
                rows = reg.no_longer_serious(rid, *key, SYNC, at, form_author(rid, *key))
                audit(rid, SYNC, *key, rows)
                written += rows
        return written

    def office_copy(rid: str, v: dict[str, Any], rules: dict[str, Any]) -> None:
        """FIT-025: a new case goes to the trial office's mailbox (an internal address), without the AE term. A mail
        that fails is in the audit; the register and the pages do not depend on it."""
        to = os.environ.get("TB_SAE_OFFICE_MAILBOX", "").strip()
        if not to:
            return
        subject, body = office_notice(rid, v, rules)
        try:
            bk.send_notice("N2", [to], subject, body, SYNC)
            detail = {"action": "office_copy", "record": v["record"], "event": v["event"], "to": to}
            au.append("console.sae", ruleset=rid, actor=SYNC, detail=detail)
        except Exception as exc:
            au.append("console.sae", ruleset=rid, actor=SYNC,
                      detail={"action": "office_copy_failed", "record": v["record"], "event": v["event"],
                              "error": type(exc).__name__})  # fmt: skip

    def hook(rid: str) -> None:
        """``h.sae_sync``: called after an AE form is saved, an acknowledgement and by the notice job. Never fails
        the caller's write: what it cannot write now, the next write or the daily job writes."""
        try:
            sync_study(rid)
        except Exception as exc:
            au.append("console.sae", ruleset=rid, actor=SYNC,
                      detail={"action": "sync_failed", "error": type(exc).__name__})  # fmt: skip

    h.sae_sync = hook
    prev_reports = h.life_reports

    def life_reports(rid: str) -> list[dict[str, Any]]:
        """The overdue SAE reports of the home pages, the week page and N2: the first reports (the orchestrator's
        clock) and, from the register, every overdue follow-up (CR-010: rule follow-ups used to reach no mail)."""
        rows = list(prev_reports(rid)) if prev_reports is not None else []
        try:
            views, _lost, _rules = load(rid, today())
        except (Problem, Unavailable):
            return rows
        for v in views:
            rows += [{"record": v["record"], "event": v["event"], "pid": v["pid"], "party": r["party"],
                      "due": r["due"], "kind": "followup"}
                     for r in v["reports"] if r["kind"] == "followup" and r["state"] == "overdue"]  # fmt: skip
        return rows

    h.life_reports = life_reports

    def sae_open(rid: str) -> int:
        """NEW-LIFE-6 (D-763): the study's SAE reports still to send (``saerecord.OPEN``), for the close check.
        Raises ``Problem`` or ``Unavailable`` when the register cannot be read: the caller refuses the close."""
        views, _lost, _rules = load(rid, today())
        return sum(int(v.get("open") or 0) for v in views)

    h.sae_open = sae_open

    def context(rules_by: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {"study_rules": rules_by, "fu_rules": followup_rules(os.environ.get("TB_SAE_FOLLOWUP_DAYS", "")),
                "tz": str(getattr(tz, "key", "UTC")), "parties": PARTIES}  # fmt: skip

    @app.get("/sae")
    def worklist(request: Request) -> Response:
        sess = h.need(request)
        if not sae_allowed(sess.user.role, "view"):
            raise deny(sess, "/sae")
        day = today()
        rows: list[dict[str, Any]] = []
        lost: list[dict[str, Any]] = []
        failed: list[str] = []
        rules_by: dict[str, dict[str, Any]] = {}
        for r in h.trials(sess) if h.trials is not None else []:
            if sess.user.sponsor_form or not known_study(bk, r.id) or not delegated(sess, r.id):
                continue
            try:
                got, gone, rules_by[r.id] = load(r.id, day)
            except (Problem, Unavailable):
                failed.append(r.id)  # never a silent empty list: the page says which studies are missing
                continue
            rows += got
            lost += gone
        rows.sort(key=sort_key)
        live = [v for v in rows if not v["downgraded"]]
        return h.page(request, "sae_worklist.html", sess, rows=rows, lost=lost, failed=failed,
                      overdue=sum(v["overdue"] for v in rows), late=sum(v["late"] for v in rows),
                      dates=sum(1 for v in live if set(DATE_ALERTS) & set(v["flags"])),
                      downgraded=sum(1 for v in rows if v["downgraded"]),
                      rule_alerts=sorted(k for k, x in rules_by.items() if set(x.get("problems") or []) & RULE_ALERTS),
                      today=day.isoformat(), **context(rules_by))  # fmt: skip

    def find(views: list[dict[str, Any]], rec: str, ev: str) -> dict[str, Any] | None:
        return next((v for v in views if (str(v["record"]), str(v["event"])) == (rec, ev)), None)

    def case_page(request: Request, sess: Session, rid: str, rec: str, ev: str, status: int = 200,
                  refused: str = "", done: str = "") -> Response:  # fmt: skip
        day = today()
        rules: dict[str, Any] = {}
        try:
            views, lost, rules = load(rid, day)
            one = find(views + lost, rec, ev)
        except (Problem, Unavailable):  # the orchestrator did not answer: say so, never an empty case
            one = None
            status, refused = 503, translate(lang_of(sess), "sae.unavailable")
        case = reg.case(rid, rec, ev)
        if one is None and case is None and status != 503:
            raise h.problem(404, "notfound")
        editable = sae_allowed(sess.user.role, "record") and h.permit(sess.user, "task.enter_data", rid).allowed
        may_ack = h.permit(sess.user, "sae.ack").allowed and status != 503
        return h.page(request, "sae_case.html", sess, status=status, rs=rid, record=rec, event=ev, one=one,
                      case=case, trail=reg.trail(rid, rec, ev), today=day.isoformat(), rules=rules,
                      editable=editable and status != 503, may_ack=may_ack, refused=refused, done=done,
                      **context({rid: rules}))  # fmt: skip

    def keys(record: str, event: str) -> tuple[str, str]:
        rec, ev = record_key(record[:64]), event.strip().lower()
        if not _REC.match(rec) or not _EV.match(ev):
            raise h.problem(404, "notfound")
        return rec, ev

    @app.get("/studies/{rs}/sae/{record}/{event}")
    def case(request: Request, rs: str, record: str, event: str, done: str = "") -> Response:
        sess = h.need(request)
        rid = scope(sess, rs, "view", request.url.path)
        rec, ev = keys(record, event)
        return case_page(request, sess, rid, rec, ev, done=done if done in ("saved", "acked") else "")

    def current(rid: str, rec: str, ev: str, day: date) -> dict[str, Any]:
        views, lost, _rules = load(rid, day)
        one = find(views + lost, rec, ev)
        if one is None:
            raise SaeError("case")
        return one

    def start_of(one: dict[str, Any]) -> str:
        return str(one.get("aware") or one.get("onset") or "")

    def write_sent(rid: str, rec: str, ev: str, party: str, on: str, by: str) -> None:
        """The day sent goes to the AE form: the one field the clock, the home pages and the mail read. Only that
        field is sent (the data core keeps every other value); a field the form hides is refused, not dropped."""
        field = lc.REPORT_FIELDS[party]
        out = s28.call(bk, "POST", f"/studies/{rid}/entry/{quote(rec)}",
                       {"form": AE_FORM, "event": ev, "values": {field: on}, "by": by})  # fmt: skip
        if field in (out.get("hidden") or []) or field not in (out.get("written") or [field]):
            raise SaeError("form")
        au.append("console.data_entry", ruleset=rid, actor=by,
                  detail={"form": AE_FORM, "event": ev, "fields": [field]})  # fmt: skip

    def open_report(one: dict[str, Any], kind: str, party: str, rid_n: int | None) -> dict[str, Any] | None:
        if kind == "followup":
            return next((r for r in one["reports"] if r["kind"] == "followup" and r["id"] == rid_n), None)
        return next((r for r in one["reports"] if r["kind"] == "initial" and r["party"] == party), None)

    @app.post("/studies/{rs}/sae/{record}/{event}/ack")
    async def ack(request: Request, rs: str, record: str, event: str) -> Response:
        """UX-028: the investigator acknowledges on the case page too (one tap, as on the banner), audited; the
        register's trail takes it at once (the write path)."""
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = scope(sess, rs, "view", request.url.path)
        rec, ev = keys(record, event)
        if not h.permit(sess.user, "sae.ack"):
            raise deny(sess, request.url.path)
        try:
            out = dict(actor.call(h, sess, "sae.ack", rid, "POST", f"/studies/{rid}/aes/{quote(rec)}/{ev}/ack", {}))
        except Problem as exc:
            if exc.status == 404:
                raise h.problem(404, "notfound") from exc
            return case_page(request, sess, rid, rec, ev, status=409, refused=translate(lang_of(sess), "sae.why.case"))
        except Unavailable:
            return case_page(request, sess, rid, rec, ev, status=503,
                             refused=translate(lang_of(sess), "sae.unavailable"))  # fmt: skip
        au.append("console.sae_ack", ruleset=rid, actor=h.actor(sess),
                  detail={"record": rec, "event": ev, "at": out.get("ack_at")})  # fmt: skip
        hook(rid)
        return RedirectResponse(f"/studies/{rid}/sae/{quote(rec)}/{ev}?done=acked", status_code=303)

    @app.post("/studies/{rs}/sae/sync")
    async def sync_now(request: Request, rs: str) -> Response:
        """Bring the study's register up to date now (the coordinator), e.g. after answers came from REDCap."""
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        rid = scope(sess, rs, "record", request.url.path)
        try:
            sync_study(rid)
        except (Problem, Unavailable):
            raise h.problem(503, "unavailable", detail="orchestrator") from None
        return RedirectResponse("/sae", status_code=303)

    @app.post("/studies/{rs}/sae/{record}/{event}/{what}")
    async def record_it(request: Request, rs: str, record: str, event: str, what: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        if what not in ("sent", "receipt", "followup", "followup_sent", "close"):
            raise h.problem(404, "notfound")
        rid = scope(sess, rs, "record", request.url.path)
        rec, ev = keys(record, event)
        by, day = h.actor(sess), today()
        f = {k: str(data.get(k) or "").strip()[:80] for k in ("party", "on", "ref", "due", "kind", "id")}
        if f["id"] and not _ID.fullmatch(f["id"]):
            raise h.problem(404, "notfound")
        rid_n = int(f["id"]) if f["id"] else None
        try:
            one = current(rid, rec, ev, day)
            if what == "sent":
                if f["party"] not in PARTIES:
                    raise SaeError("party")
                row = open_report(one, "initial", f["party"], None)
                if row is None:
                    raise SaeError("party_off")
                if row["sent_on"] or row["closed_on"]:
                    raise SaeError("already")  # a correction is made on the AE form, where its history is kept
                d, s = day_of(f["on"]), day_of(start_of(one))
                if d is None or d.isoformat() != f["on"]:
                    raise SaeError("day")
                if d > day or (s is not None and d < s):
                    raise SaeError("sent_day")
                ref = check_ref(f["ref"])  # refused before anything is written
                if one["downgraded"]:  # the form hides the report fields of an AE no longer serious
                    body = reg.register_sent(rid, rec, ev, f["party"], f["on"], ref, by, stamp())
                    audit(rid, by, rec, ev, [{"action": "report", "body": body}])
                else:
                    try:
                        write_sent(rid, rec, ev, f["party"], f["on"], by)
                    except Problem as exc:
                        raise SaeError("form") from exc
                    if ref:
                        body = reg.initial_ref(rid, rec, ev, f["party"], ref, by, stamp())
                        audit(rid, by, rec, ev, [{"action": "report_ref", "body": body}])
                    sync_study(rid)  # the AE form's new date enters the trail now (system:sync, form_by = this person)
            elif what == "receipt":
                kind = "followup" if f["kind"] == "followup" else "initial"
                row = open_report(one, kind, f["party"], rid_n)
                if row is None and kind == "initial" and f["party"] in PARTIES:
                    raise SaeError("party_off")
                sent = str((row or {}).get("sent_on") or "") if (row or {}).get("state") != "bad_sent" else ""
                body = reg.receipt(rid, rec, ev, f["party"], kind, rid_n, f["on"], f["ref"], sent, day, by, stamp())
                audit(rid, by, rec, ev, [{"action": "receipt", "body": body}])
            elif what == "followup":
                body = reg.add_followup(rid, rec, ev, f["party"], f["due"], start_of(one), by, stamp())
                audit(rid, by, rec, ev, [{"action": "followup_add", "body": body}])
            elif what == "close":
                if not one["downgraded"]:
                    raise SaeError("not_downgraded")  # a serious AE's report is sent, never closed
                d = day_of(f["on"])
                if d is None or d.isoformat() != f["on"] or d > day:
                    raise SaeError("day")
                kind = "followup" if f["kind"] == "followup" else "initial"
                body = reg.close_report(rid, rec, ev, f["party"], kind, rid_n, f["on"], by, stamp())
                audit(rid, by, rec, ev, [{"action": "closed", "body": body}])
            else:
                due = ""
                if not rid_n:
                    rule = next((r for r in one["reports"] if r["kind"] == "followup" and r["origin"] == "rule"
                                 and r["party"] == f["party"] and not r["id"]), None)  # fmt: skip
                    if rule is None:
                        raise SaeError("party_off")
                    due = str(rule["due"])
                body = reg.followup_sent(rid, rec, ev, f["party"], rid_n, due, f["on"], f["ref"], start_of(one), day,
                                         by, stamp())  # fmt: skip
                audit(rid, by, rec, ev, [{"action": "followup_sent", "body": body}])
        except SaeError as exc:
            return case_page(request, sess, rid, rec, ev, status=409,
                             refused=translate(lang_of(sess), f"sae.why.{exc.why}"))  # fmt: skip
        except (Unavailable, Problem):  # the orchestrator did not answer the read: nothing was recorded
            return case_page(request, sess, rid, rec, ev, status=503,
                             refused=translate(lang_of(sess), "sae.unavailable"))  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/sae/{quote(rec)}/{ev}?done=saved", status_code=303)
