"""D-191 (independent plan review PR-17): the SAE register's worklist and case pages.

* ``/sae``: every serious AE of the studies the account sees, overdue reports first, with an alert at the top
  (role="alert") counting the overdue reports and the SAEs whose dates need checking. Each row: the study, the
  participant's screening number and pseudonym, onset and the day the site learned of it, every report (first report
  and follow-ups) with its due day, sent day, the receiver's acknowledgement and its state, and the investigator's
  acknowledgement. Never the AE term: the participant page has it.
* ``/studies/{rs}/sae/{record}/{event}``: one case, the forms that record a report sent (written to the AE form), a
  receipt, a requested follow-up and a follow-up sent, and the trail.

Every page first brings the register up to date with the AE forms (``console.saerecord.SaeStore.sync``); every create
or change is a trail row and a ``console.sae`` audit event with dates and parties only. Access: the role table
``tb_common.authz.ROLE_SAE_ACTIONS`` (deny by default) on top of the study scope of the lifecycle pages (a study the
account does not see, or a CRO account: 404); recording also needs the study's ``enter_data`` task (D-147).
"""

from __future__ import annotations

import os
import re
from datetime import UTC, date
from typing import Any
from urllib.parse import quote

from datacore import lifecycle as lc
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from tb_common.authz import sae_allowed

from console import i18n_sae, s28
from console.auth import Session
from console.backend import Problem, Unavailable
from console.entry_pages import record_key
from console.home import Helpers
from console.i18n import CATALOGUES, translate
from console.saerecord import PARTIES, SaeError, SaeStore, case_view, check_ref, day_of, followup_rules, sort_key
from console.studies import known_study
from console.timefmt import local_today, site_zone

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_EV = re.compile(r"^ae\d{1,3}$")
AE_FORM = "tb_adverse_event"

for _lang, _cat in (("en", i18n_sae.EN), ("ja", i18n_sae.JA), ("zh-TW", i18n_sae.ZH)):
    CATALOGUES[_lang].update(_cat)


def register(app: FastAPI, h: Helpers, store: SaeStore | None = None) -> None:
    bk, au = h.bk, h.au
    tz = site_zone(bk)
    reg = store if store is not None else SaeStore()

    def today() -> date:
        return local_today(h.clock(), tz)

    def stamp() -> str:
        now = h.clock()
        return (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC).isoformat(timespec="seconds")

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def scope(sess: Session, rs: str, action: str, path: str) -> str:
        """The study, after the study scope (404) and the role table (403); recording also needs ``enter_data``."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or sess.user.role == "cro" or not known_study(bk, rid):
            raise h.problem(404, "notfound")
        if not sae_allowed(sess.user.role, action):
            raise deny(sess, path)
        if action == "record" and h.may is not None and not h.may(sess.user, rid, "enter_data"):
            raise deny(sess, path)
        if not delegated(sess, rid):
            raise deny(sess, path)
        return rid

    def delegated(sess: Session, rid: str) -> bool:
        """D-147: once a study's delegation log names a PI, an investigator sees its patients only as the PI or a
        sub-investigator ticked for "screen" (as on the week and candidate pages)."""
        return sess.user.role != "investigator" or h.may is None or h.may(sess.user, rid, "screen")

    def audit(rid: str, by: str, record: str, event: str, rows: list[dict[str, Any]]) -> None:
        for w in rows:  # dates, parties and staff only: the AE term never reaches the log
            au.append("console.sae", ruleset=rid, actor=by,
                      detail={"action": w["action"], "record": record, "event": event, **w["body"]})  # fmt: skip

    def load(rid: str, by: str, day: date) -> list[dict[str, Any]]:
        """The study's serious AEs, the register brought up to date, as worklist rows (raises Problem/Unavailable)."""
        aes = list(s28.call(bk, "GET", f"/studies/{rid}/aes?today={day.isoformat()}").get("aes") or [])
        at, fu = stamp(), followup_rules(os.environ.get("TB_SAE_FOLLOWUP_DAYS", ""))
        seen: set[tuple[str, str]] = set()
        views = []
        for a in aes:
            key = (str(a["record"]), str(a["event"]))
            if not a.get("serious"):
                continue
            seen.add(key)
            audit(rid, by, *key, reg.sync(rid, a, by, at))
            v = case_view(a, reg.case(rid, *key), reg.reports(rid, *key), day, fu)
            v["rs"] = rid
            views.append(v)
        for c in reg.cases(rid):
            key = (str(c["record"]), str(c["event"]))
            if key not in seen:
                audit(rid, by, *key, reg.no_longer_serious(rid, *key, by, at))
        return views

    def gone(rid: str) -> list[dict[str, Any]]:
        return [{"rs": rid, "record": c["record"], "event": c["event"]} for c in reg.cases(rid) if not c["serious"]]

    def context() -> dict[str, Any]:
        rules = lc.report_rules(str(getattr(tz, "key", "")), os.environ.get("TB_SAE_REPORT_DAYS", ""),
                                os.environ.get("TB_SAE_RULES", ""))  # fmt: skip
        return {"rules": rules, "fu_rules": followup_rules(os.environ.get("TB_SAE_FOLLOWUP_DAYS", "")),
                "confirmed": os.environ.get("TB_SAE_RULES_CONFIRMED", "").strip()[:120],
                "tz": str(getattr(tz, "key", "UTC")), "parties": PARTIES}  # fmt: skip

    @app.get("/sae")
    def worklist(request: Request) -> Response:
        sess = h.need(request)
        if not sae_allowed(sess.user.role, "view"):
            raise deny(sess, "/sae")
        day, by = today(), h.actor(sess)
        rows: list[dict[str, Any]] = []
        lost: list[dict[str, Any]] = []
        failed: list[str] = []
        for r in h.trials(sess) if h.trials is not None else []:
            if sess.user.role == "cro" or not known_study(bk, r.id) or not delegated(sess, r.id):
                continue
            try:
                rows += load(r.id, by, day)
            except (Problem, Unavailable):
                failed.append(r.id)  # never a silent empty list: the page says which studies are missing
            lost += gone(r.id)
        rows.sort(key=sort_key)
        overdue = sum(v["overdue"] for v in rows)
        dates = sum(1 for v in rows if {"nostart", "aware_before_onset"} & set(v["flags"]))
        return h.page(request, "sae_worklist.html", sess, rows=rows, lost=lost, failed=failed, overdue=overdue,
                      dates=dates, today=day.isoformat(), **context())  # fmt: skip

    def case_page(request: Request, sess: Session, rid: str, rec: str, ev: str, status: int = 200,
                  refused: str = "", done: str = "") -> Response:  # fmt: skip
        day = today()
        try:
            views = load(rid, h.actor(sess), day)
        except (Problem, Unavailable):
            views = []
        one = next((v for v in views if (str(v["record"]), str(v["event"])) == (rec, ev)), None)
        if one is None and reg.case(rid, rec, ev) is None:
            raise h.problem(404, "notfound")
        editable = sae_allowed(sess.user.role, "record") and (h.may is None or h.may(sess.user, rid, "enter_data"))
        return h.page(request, "sae_case.html", sess, status=status, rs=rid, record=rec, event=ev, one=one,
                      case=reg.case(rid, rec, ev), trail=reg.trail(rid, rec, ev), today=day.isoformat(),
                      editable=editable, refused=refused, done=done, **context())  # fmt: skip

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
        return case_page(request, sess, rid, rec, ev, done="saved" if done == "saved" else "")

    def current(rid: str, rec: str, ev: str, by: str, day: date) -> dict[str, Any]:
        one = next((v for v in load(rid, by, day) if (str(v["record"]), str(v["event"])) == (rec, ev)), None)
        if one is None:
            raise SaeError("case")
        return one

    def start_of(one: dict[str, Any]) -> str:
        return str(one.get("aware") or one.get("onset") or "")

    def write_sent(rid: str, rec: str, ev: str, party: str, on: str, by: str) -> None:
        """The day sent goes to the AE form: the one field the clock, the home pages and the mail read."""
        got = s28.call(bk, "GET", f"/studies/{rid}/records/{quote(rec)}")
        vals = {k: str((v or {}).get("value") or "") for k, v in ((got.get("values") or {}).get(ev) or {}).items()
                if k.startswith("ae_")}  # fmt: skip
        vals[lc.REPORT_FIELDS[party]] = on
        s28.call(bk, "POST", f"/studies/{rid}/entry/{quote(rec)}",
                 {"form": AE_FORM, "event": ev, "values": vals, "by": by})  # fmt: skip
        au.append("console.data_entry", ruleset=rid, actor=by,
                  detail={"form": AE_FORM, "event": ev, "fields": [lc.REPORT_FIELDS[party]]})  # fmt: skip

    @app.post("/studies/{rs}/sae/{record}/{event}/{what}")
    async def record_it(request: Request, rs: str, record: str, event: str, what: str) -> Response:
        sess = h.need(request)
        data = await request.form()
        if not h.csrf_ok(sess, str(data.get("csrf") or "")):
            raise h.problem(400, "csrf")
        if what not in ("sent", "receipt", "followup", "followup_sent"):
            raise h.problem(404, "notfound")
        rid = scope(sess, rs, "record", request.url.path)
        rec, ev = keys(record, event)
        by, day = h.actor(sess), today()
        f = {k: str(data.get(k) or "").strip()[:80] for k in ("party", "on", "ref", "due", "kind", "id")}
        rid_n = int(f["id"]) if f["id"].isdigit() else None
        try:
            one = current(rid, rec, ev, by, day)
            parties = {r["party"] for r in one["reports"] if r["kind"] == "initial"}
            if what == "sent":
                if f["party"] not in PARTIES:
                    raise SaeError("party")
                if f["party"] not in parties:
                    raise SaeError("party_off")
                if any(r["kind"] == "initial" and r["party"] == f["party"] and r["sent_on"] for r in one["reports"]):
                    raise SaeError("already")  # a correction is made on the AE form, where its history is kept
                d, s = day_of(f["on"]), day_of(start_of(one))
                if d is None or d.isoformat() != f["on"]:
                    raise SaeError("day")
                if d > day or (s is not None and d < s):
                    raise SaeError("sent_day")
                ref = check_ref(f["ref"])  # refused before anything is written
                try:
                    write_sent(rid, rec, ev, f["party"], f["on"], by)
                except Problem as exc:
                    raise SaeError("form") from exc
                if ref:
                    body = reg.initial_ref(rid, rec, ev, f["party"], ref, by, stamp())
                    audit(rid, by, rec, ev, [{"action": "report_ref", "body": body}])
                load(rid, by, day)  # the AE form's new date enters the trail now, as this person's
            elif what == "receipt":
                if f["kind"] == "followup":
                    row = next((r for r in one["reports"] if r["kind"] == "followup" and r["id"] == rid_n), None)
                    sent = str((row or {}).get("sent_on") or "")
                else:
                    row = next((r for r in one["reports"] if r["kind"] == "initial" and r["party"] == f["party"]), None)
                    sent = str((row or {}).get("sent_on") or "")
                    if f["party"] in PARTIES and row is None:
                        raise SaeError("party_off")
                body = reg.receipt(rid, rec, ev, f["party"], "followup" if f["kind"] == "followup" else "initial",
                                   rid_n, f["on"], f["ref"], sent, day, by, stamp())  # fmt: skip
                audit(rid, by, rec, ev, [{"action": "receipt", "body": body}])
            elif what == "followup":
                body = reg.add_followup(rid, rec, ev, f["party"], f["due"], start_of(one), by, stamp())
                audit(rid, by, rec, ev, [{"action": "followup_add", "body": body}])
            else:
                due = ""
                if not rid_n:
                    rule = next((r for r in one["reports"] if r["kind"] == "followup" and r["origin"] == "rule"
                                 and r["party"] == f["party"]), None)  # fmt: skip
                    if rule is None:
                        raise SaeError("party_off")
                    due = str(rule["due"])
                body = reg.followup_sent(rid, rec, ev, f["party"], rid_n, due, f["on"], f["ref"], start_of(one), day,
                                         by, stamp())  # fmt: skip
                audit(rid, by, rec, ev, [{"action": "followup_sent", "body": body}])
        except SaeError as exc:
            lang = sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"
            return case_page(request, sess, rid, rec, ev, status=409, refused=translate(lang, f"sae.why.{exc.why}"))
        except (Unavailable, Problem):  # the orchestrator did not answer the read: nothing was recorded
            lang = sess.lang if sess.lang in ("ja", "zh-TW", "en") else "en"
            return case_page(request, sess, rid, rec, ev, status=503, refused=translate(lang, "sae.unavailable"))
        return RedirectResponse(f"/studies/{rid}/sae/{quote(rec)}/{ev}?done=saved", status_code=303)
