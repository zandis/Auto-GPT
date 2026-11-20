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
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from datacore import lifecycle as lc
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from tb_common.authz import permit, sae_allowed

from console import actor, i18n_sae, s28
from console.auth import Session
from console.backend import Problem, Unavailable
from console.entry_pages import record_key
from console.home import Helpers
from console.i18n import CATALOGUES, translate
from console.notify import base_url
from console.saerecord import (
    PARTIES,
    SYNC,
    SaeError,
    SaeStore,
    case_view,
    check_ref,
    day_of,
    downgraded_view,
    escalate_once,
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
#: 9f-4 (b), D-1383: the log roles told of a serious AE the PI has not acknowledged after ``TB_SAE_ESCALATE_HOURS``
ESCALATE_ROLES = ("sub_pi", "crc")
ESCALATE_ENV = "TB_SAE_ESCALATE_HOURS"
DATE_ALERTS = ("nostart", "aware_before_onset", "future_date", "bad_sent", "serious_mismatch", "noclock")
RULE_ALERTS = set(lc.RULE_ALERTS)

for _lang, _cat in (("en", i18n_sae.EN), ("ja", i18n_sae.JA), ("zh-TW", i18n_sae.ZH)):
    CATALOGUES[_lang].update(_cat)


def escalate_hours(env: Any) -> int:
    """9f-4 (b): the hours an unacknowledged serious AE waits before the escalation (``TB_SAE_ESCALATE_HOURS``,
    default 24, a whole number from 1 to 720). Anything else is refused (ValueError): no preference silences it."""
    raw = str(env.get(ESCALATE_ENV) or "24").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= 720:
        raise ValueError(f"{ESCALATE_ENV} must be a whole number of hours from 1 to 720, got {raw!r}")
    return int(raw)


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

    def sae_scope(user: Any, rid: str, action: str) -> str | None:
        """Why this account may not take ``action`` on study ``rid``'s serious AEs, or None when it may: the one rule
        of the SAE pages, which :func:`scope` turns into a 404 or a 403, the worklist into the studies it lists and
        the opening page into the studies whose serious AEs it reads (J-6, D-1225). "notfound": not a study the
        account sees (or a sponsor copy); "role": the matrix's ``sae.*`` row; "enter_data": recording needs the study
        task; "delegation": the delegation log (D-147, the week and candidate pages' rule)."""
        if not _RS.match(rid) or not user.sees_study(rid) or user.sponsor_form or not known_study(bk, rid):
            return "notfound"
        if not sae_allowed(user.role, action):
            return "role"
        if action == "record" and not h.permit(user, "task.enter_data", rid):
            return "enter_data"
        return None if h.delegated_ok(user, rid) else "delegation"

    def reads_saes(user: Any, rid: str) -> bool:
        """:func:`sae_scope` for viewing, as a yes or no, with nothing audited."""
        return sae_scope(user, rid, "view") is None

    def scope(sess: Session, rs: str, action: str, path: str) -> str:
        """The study, after the study scope (404) and the role table (403); recording also needs ``enter_data``."""
        rid = rs.strip().upper()
        why = sae_scope(sess.user, rid, action)
        if why == "notfound":
            raise h.problem(404, "notfound")
        if why is not None:
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
            # D-764: a new case, or one serious again after it was not (its review), is told at once
            again = any(w["action"] == "change" and not (w["body"].get("serious") or {}).get("old")
                        and (w["body"].get("serious") or {}).get("new") for w in rows)  # fmt: skip
            if again or any(w["action"] == "create" for w in rows):
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

    def told_at_once(rid: str) -> list[str]:
        """NEW-LIFE-7 (D-764): who hears of a new case at once: the trial office's mailbox (FIT-025) and the study's
        PI on the delegation log today, by the mailbox of their account (``get`` gives only an enabled account that
        has not expired)."""
        out: list[str] = []
        office = os.environ.get("TB_SAE_OFFICE_MAILBOX", "").strip()
        if office:
            out.append(office)
        pi = h.team.pi_of(rid, today()) if h.team is not None else None
        u = h.users.get(pi.username) if pi is not None and pi.username else None
        if u is not None and u.mailbox:
            out.append(u.mailbox)
        else:  # the review of D-764: a PI who cannot be mailed is said, also when the office is told
            au.append("console.sae", ruleset=rid, actor=SYNC,
                      detail={"action": "pi_unreachable", "why": "no_pi" if pi is None else "no_mailbox"})  # fmt: skip
        return list(dict.fromkeys(out))

    def office_copy(rid: str, v: dict[str, Any], rules: dict[str, Any]) -> None:
        """FIT-025, NEW-LIFE-7 (D-764): a new case goes at once to the trial office's mailbox and the study's PI,
        without the AE term. Nobody to tell is audited (``notice_nobody``); a mail that fails is in the audit; the
        register and the pages do not depend on it."""
        to = told_at_once(rid)
        if not to:
            au.append("console.sae", ruleset=rid, actor=SYNC,
                      detail={"action": "notice_nobody", "record": v["record"], "event": v["event"]})  # fmt: skip
            return
        subject, body = office_notice(rid, v, rules)
        try:
            bk.send_notice("N2", to, subject, body, actor.SAE_SYNC)  # T-715: the sync's own name
            detail = {"action": "office_copy", "record": v["record"], "event": v["event"], "to": ", ".join(to)}
            au.append("console.sae", ruleset=rid, actor=SYNC, detail=detail)
        except Exception as exc:
            au.append("console.sae", ruleset=rid, actor=SYNC,
                      detail={"action": "office_copy_failed", "record": v["record"], "event": v["event"],
                              "error": type(exc).__name__})  # fmt: skip

    def hook(rid: str) -> None:
        """``h.sae_sync``: called after an AE form is saved, an acknowledgement and by the notice job. Never fails
        the caller's write: what it cannot write now, the next write or the daily job writes. 9f-4 (b): then the
        escalation of the study's unacknowledged cases (:func:`escalate`)."""
        try:
            sync_study(rid)
        except Exception as exc:
            au.append("console.sae", ruleset=rid, actor=SYNC,
                      detail={"action": "sync_failed", "error": type(exc).__name__})  # fmt: skip
        escalate_safe(rid)

    def escalate_safe(rid: str) -> None:
        """:func:`escalate`, never failing its caller: a failure is a ``console.sae`` event; the next round tries."""
        try:
            escalate(rid)
        except Exception as exc:
            au.append("console.sae", ruleset=rid, actor=SYNC,
                      detail={"action": "escalate_failed", "error": type(exc).__name__})  # fmt: skip

    # ------------------------------------------------------------------ 9f-4 (b), D-1383: the escalation
    escalate_hours(os.environ)  # a broken TB_SAE_ESCALATE_HOURS stops the console at start, never a quiet default

    def told_later(rid: str, day: date) -> list[tuple[str, str]]:
        """Who hears of a case the PI has not acknowledged after the threshold: each account with an entry active on
        ``day`` on the study's delegation log as sub-investigator or coordinator (``crc``), once, as (account, log
        role; a person on the log as both is told as sub-investigator). Nobody else; no notice setting applies."""
        if h.team is None:
            return []
        out: dict[str, str] = {}
        for e in h.team.entries(rid):
            if e.username and e.role in ESCALATE_ROLES and e.active_on(day) and out.get(e.username) != "sub_pi":
                out[e.username] = e.role
        return sorted(out.items())

    def escalation_mail(rid: str, v: dict[str, Any], rules: dict[str, Any], n: int, day: date) -> dict[str, Any]:
        """Mail each person :func:`told_later` names, one mail each (an address the orchestrator refuses loses only
        its own). The mail is the PI's own notice of the case (``office_notice``: study, screening number, event,
        dates, fatal or not, rule set, deadlines; never the AE term, a chart number or a name) after one line saying
        why; a person whose own rights do not read this study's serious AEs gets the line and the link only, without
        the screening number, the event or the dates. Returns the trail body and the audit's names."""
        _subject, notice = office_notice(rid, v, rules)
        url = f"{base_url()}/studies/{rid}/subjects"
        sent: list[str] = []
        full: list[str] = []
        short: list[str] = []
        failed: list[str] = []
        unreachable: list[str] = []
        for name, role in told_later(rid, day):
            u = h.users.get(name)  # an enabled account that has not expired, else None
            if u is None or not u.mailbox:
                unreachable.append(name)
                continue
            try:
                lang = h.store.notify_person(name).lang
            except Exception:  # the site store cannot say: the mail still goes, in English
                lang = "en"
            lang = lang if lang in ("en", "ja", "zh-TW") else "en"
            lead = translate(lang, "sae.escalate.sub_pi" if role == "sub_pi" else "sae.escalate.crc", rs=rid, n=n)
            sees = reads_saes(u, rid)
            body = "\n".join([lead, "", notice] if sees else [lead, "", translate(lang, "sae.escalate.open", url=url)])
            try:
                bk.send_notice("N2", [u.mailbox], translate(lang, "sae.escalate.subject", rs=rid, n=n), body,
                               actor.SAE_SYNC)  # fmt: skip
            except Exception:  # one refused address does not stop the others; the audit names it
                failed.append(name)
                continue
            sent.append(name)
            (full if sees else short).append(name)
        return {"to": ", ".join(sent), "sent": len(sent), "full": full, "short": short, "failed": failed,
                "unreachable": unreachable}  # fmt: skip

    def escalate(rid: str) -> list[str]:
        """9f-4 (b): each serious AE of the study the PI has not acknowledged ``TB_SAE_ESCALATE_HOURS`` hours (default
        24) after the register first had it (``sae_case.created_at``, the moment it became one waiting for the PI) is
        mailed to the study's sub-investigators and coordinators, once per case and threshold (a trail row
        ``escalated`` and a ``console.sae`` event naming who was told, in one transaction). Returns the cases told."""
        n = escalate_hours(os.environ)
        day, at = today(), now()
        out = fetch(rid, day)
        rules = dict(out.get("rules") or {})
        fu = followup_rules(os.environ.get("TB_SAE_FOLLOWUP_DAYS", ""))
        done: list[str] = []
        for a in out.get("aes") or []:
            if not a.get("serious") or not a.get("needs_ack"):
                continue
            key = (str(a["record"]), str(a["event"]))
            case = reg.case(rid, *key)
            if case is None or case.get("pi_ack_by"):
                continue
            try:
                since = datetime.fromisoformat(str(case.get("created_at") or ""))
            except ValueError:
                continue
            since = since if since.tzinfo else since.replace(tzinfo=UTC)
            if at - since < timedelta(hours=n):
                continue
            v = case_view(a, case, reg.reports(rid, *key), day, fu, at, rules)
            names: dict[str, Any] = {}

            def send(v: dict[str, Any] = v, names: dict[str, Any] = names) -> dict[str, Any]:
                got = escalation_mail(rid, v, rules, n, day)
                names.update(got)
                return {"to": got["to"], "sent": got["sent"]}

            def audit_it(body: dict[str, Any], key: tuple[str, str] = key, names: dict[str, Any] = names,
                         since: str = str(case.get("created_at") or "")) -> None:  # fmt: skip
                au.append("console.sae", ruleset=rid, actor=SYNC,
                          detail={"action": "escalated", "record": key[0], "event": key[1], "hours": n,
                                  "since": since, **names})  # fmt: skip

            if escalate_once(reg, rid, *key, n, send, SYNC, stamp(), audit_it) is not None:
                done.append(f"{key[0]}/{key[1]}")
        return done

    def escalate_all() -> list[str]:
        """The hourly round (``console.timers``): every study's register brought up to date and escalated, its
        patient reads signed as the morning mail's principal (NEW-SEC-1)."""
        told: list[str] = []
        for r in bk.rulesets():
            if not _RS.match(r.id):
                continue
            with actor.reading_as(actor.NOTIFY):
                try:
                    sync_study(r.id)
                except Exception as exc:
                    au.append("console.sae", ruleset=r.id, actor=SYNC,
                              detail={"action": "sync_failed", "error": type(exc).__name__})  # fmt: skip
                try:
                    told += [f"{r.id}:{x}" for x in escalate(r.id)]
                except Exception as exc:
                    au.append("console.sae", ruleset=r.id, actor=SYNC,
                              detail={"action": "escalate_failed", "error": type(exc).__name__})  # fmt: skip
        return told

    h.sae_sync = hook
    h.sae_escalate = escalate_all
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
        """NEW-LIFE-6 (D-763): the study's serious AEs not done with, for the close check: every report still to send
        (``saerecord.OPEN``), and every serious AE with no reporting clock (an unset or unknown rule set: no report
        row to count) or not acknowledged by the investigator. Raises when the register cannot be read: the caller
        refuses the close."""
        day = today()
        out = fetch(rid, day)
        views, _lost = views_of(rid, day, out)
        loose = sum(1 for a in out.get("aes") or [] if a.get("serious") and (a.get("noclock") or a.get("needs_ack")))
        return sum(int(v.get("open") or 0) for v in views) + loose

    h.sae_open = sae_open

    def home_saes(rid: str) -> dict[str, Any]:
        """J-6 (D-1225): one study's serious AEs for the opening page, from the SAE pages' own answer, read once: the
        ones not acknowledged, and the overdue reports (the first reports as the life-cycle pages count them, and the
        register's follow-ups, as :func:`life_reports`). ``failed`` when the orchestrator did not answer (CR-010)."""
        day = today()
        try:
            out = fetch(rid, day)
        except (Problem, Unavailable):
            return {"unacked": [], "reports": [], "failed": True}
        views, _lost = views_of(rid, day, out)
        first = list(h.life_reports_of(out)) if h.life_reports_of is not None else []
        follow = [{"record": v["record"], "event": v["event"], "pid": v["pid"], "party": r["party"], "due": r["due"],
                   "kind": "followup"}
                  for v in views for r in v["reports"]
                  if r["kind"] == "followup" and r["state"] == "overdue"]  # fmt: skip
        return {"unacked": list(out.get("unacked") or []), "reports": first + follow, "failed": False}

    h.reads_saes = reads_saes
    h.home_saes = home_saes

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
            if not reads_saes(sess.user, r.id):  # the same rule as a study's own SAE pages
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
        # D-797 (lane G's walk, finding 7): the set-up warnings go to who can act on them: the reporting rules to the
        # study's set-up (the coordinator), the trial office mailbox also to the site's set-up (the administrator)
        study_setup = permit(sess.user.role, "study.setup").allowed
        site_setup = study_setup or permit(sess.user.role, "site.setup").allowed
        return h.page(request, "sae_worklist.html", sess, rows=rows, lost=lost, failed=failed,
                      overdue=sum(v["overdue"] for v in rows), late=sum(v["late"] for v in rows),
                      dates=sum(1 for v in live if set(DATE_ALERTS) & set(v["flags"])),
                      downgraded=sum(1 for v in rows if v["downgraded"]),
                      rule_alerts=sorted(k for k, x in rules_by.items()
                                         if study_setup and set(x.get("problems") or []) & RULE_ALERTS),
                      today=day.isoformat(),
                      no_mailbox=site_setup and not os.environ.get("TB_SAE_OFFICE_MAILBOX", "").strip(),
                      **context(rules_by))  # fmt: skip

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

    def write_sent(sess: Session, rid: str, rec: str, ev: str, party: str, on: str, by: str) -> None:
        """The day sent goes to the AE form: the one field the clock, the home pages and the mail read. Only that
        field is sent (the data core keeps every other value); a field the form hides is refused, not dropped."""
        field = lc.REPORT_FIELDS[party]
        # T-715f (D-799): an entry on the AE form, signed as one (the page asked sae.record, a narrower row)
        out = actor.call(h, sess, "task.enter_data", rid, "POST", f"/studies/{rid}/entry/{quote(rec)}",
                         {"form": AE_FORM, "event": ev, "values": {field: on}})  # fmt: skip
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
        escalate_safe(rid)  # 9f-4 (b): the write path escalates too
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
                        write_sent(sess, rid, rec, ev, f["party"], f["on"], by)
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
