"""Mail notices of build step 2 (D-108).

* **N1, the investigator's list before clinic** (FR-NOTIF-01): one mail per investigator across their studies. When
  the console knows the investigator's practitioner id, the mail goes on the morning of each day that investigator
  has a listed candidate booked (the appointment source the SCREEN run read), with today's patients first and the
  rest of the week folded below. Without a practitioner id the clinic days are unknown: the mail goes every Monday
  with the next seven days.
* **N2, the coordinator's daily digest** (FR-NOTIF-02): on working days, one mail per coordinator: today's visits
  with what to prepare, the next steps (call, find information, retry a call), new pre-screens and the PI's marks
  since the last digest.

TB-PLAN-04 step 5 (D-134): N2 also lists the study visits of the day and the overdue ones (from the visit schedule
and the windows), N1 the investigator's participants' visits of the week and the count of serious AEs to review.
Visits are named by the patient's pseudonym and the visit's name. Review 2026-11-09 P-02/P-03 (D-143): the SAE count
is every serious AE the investigator has not acknowledged, whatever its outcome, and N1 goes out on any working day
while one waits; N2 lists the SAE reports past their due day (pseudonym, party, due day).

Both carry pseudonyms (eight characters), with the study's screening number beside the pseudonym once the patient has
one (owner, 2026-11-08, D-136), times and counts: never a chart number or a name. D-143 (owner, 2026-11-09): the
investigator may see chart numbers on the pages after sign-in, but N1 still carries none, since mail leaves TrialBox
(a point for the owner to confirm). Each says why it was sent and
links to the person's notice settings (FR-NOTIF-09). Mail leaves through the orchestrator's ``POST /notices`` and
the mail gateway, tagged ``aggregate`` and internal addresses only.

T-209a (D-379, review OPS-027 and OPS-032): N2 begins with one line on the box's health (``tb_common.metrics``), and
a red line sends N2 even on a morning with nothing else in it, so the coordinator sees that note reading was off
last night. ``HEALTH``, the administrators' daily health mail, gives one line per check every day (weekends too).

D-386 (T-622, LIFE-008): the mails follow the study's state. A study in start-up or closed is left out; a paused
study gives no list rows, marks, calls or new pre-screens, so a paused study with no participant visit or serious AE
due gives no mail. Its participants' visits and unacknowledged serious AEs are still mailed (:data:`CARE_STATES`).

Run on a schedule with ``python -m console.notify --at 07:00`` (N1) and ``--at 07:30`` (N2), or from the admin home
("Send notices now"). A notice is sent at most once per person and day.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse

from console.auth import Session, User
from console.home import Helpers
from console.i18n import LANGS, translate
from console.sitestore import NotifyPerson

MAX_ROWS = 10  # per digest section; the rest is one line and the link
# D-386 (LIFE-008): the states whose enrolled participants' visits and serious AEs are still mailed. Screening rows
# (the list, marks, calls, new pre-screens) go out only for an open study (``StudyState.runs``); a paused study keeps
# its participants' visit and SAE lines, because a pause stops recruitment, not the care of those already enrolled.
CARE_STATES = ("open", "paused")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class Notice:
    kind: str  # N1 | N2
    username: str
    to: str
    subject: str
    body: str
    day: str
    counts: dict[str, int] = field(default_factory=dict)


def base_url() -> str:
    return (os.environ.get("TB_CONSOLE_PUBLIC_URL") or "https://trialbox.hospa.test").rstrip("/")


def _line(lang: str, r: dict[str, Any], rs: str) -> str:
    met = r["fit"].inc_met + r["fit"].exc_clear
    total = r["fit"].inc_total + r["fit"].exc_total
    open_n = len(r["fit"].open) + len(r["fit"].person) + len(r["fit"].not_met)
    when = r["visit"].strftime("%H:%M") if r.get("visit") else "--:--"
    return translate(
        lang,
        "n1.row",
        time=when,
        p=r["short"],
        rs=rs,
        met=met,
        total=total,
        open=open_n,
        status=translate(lang, "wstatus." + str(r["status"])),
    )


def with_no(pid: str, no: str | None) -> str:
    """The pseudonym (eight characters), with the screening number beside it once the patient has one (D-136)."""
    return f"{pid[:8]} ({no})" if no else pid[:8]


def clinic_days(rows: Iterable[dict[str, Any]], practitioner: str | None) -> set[date]:
    """Days the investigator sees a listed candidate, from the appointment source (the candidate's next visit)."""
    return {
        r["visit"].date() for r in rows if r.get("visit") and practitioner and r.get("practitioner_id") == practitioner
    }


def _life_row(lang: str, key: str, rs: str, r: dict[str, Any]) -> str:
    return translate(lang, key, p=r.get("short") or "–", rs=rs, visit=r["visit"], start=r["start"], end=r["end"],
                     day=r["due"])  # fmt: skip


def build_n1(
    user: User,
    person: NotifyPerson,
    today: date,
    studies: Sequence[tuple[str, list[dict[str, Any]]]],
    life: dict[str, dict[str, Any]] | None = None,
) -> Notice | None:
    """The investigator's pre-clinic mail for ``today``, or None when today is not a mail day for them."""
    lang = person.lang
    all_rows = [(rs, r) for rs, rows in studies for r in rows]
    known = bool(person.practitioner_id)
    sae = sum(int(lf.get("sae") or 0) for lf in (life or {}).values())
    alert = sae > 0 and today.weekday() < 5  # P-02: an unacknowledged SAE is mailed every working day
    if known:
        mine = [(rs, r) for rs, r in all_rows if r.get("practitioner_id") == person.practitioner_id]
        if today not in clinic_days((r for _rs, r in mine), person.practitioner_id):
            if not alert:
                return None
            mine = []
        why = translate(lang, "n1.why.clinic", day=today.isoformat()) if mine else translate(lang, "n1.why.sae")
    else:
        if today.weekday() != 0 and not alert:
            return None
        mine = all_rows if today.weekday() == 0 else []
        why = translate(lang, "n1.why.monday") if mine else translate(lang, "n1.why.sae")
    end = today + timedelta(days=7)
    today_rows = [(rs, r) for rs, r in mine if r.get("visit") and r["visit"].date() == today]
    week_rows = [(rs, r) for rs, r in mine if r.get("visit") and today < r["visit"].date() < end]
    if known is False:  # the Monday mail is the whole week, in one list
        week_rows = today_rows + week_rows
        today_rows = []
    if not today_rows and not week_rows and not alert:
        return None
    today_rows.sort(key=lambda x: x[1]["visit"])
    week_rows.sort(key=lambda x: x[1]["visit"])
    url = base_url()
    parts = [translate(lang, "n1.hello"), ""]
    if today_rows:
        parts += [f"## {translate(lang, 'n1.today', day=today.isoformat(), n=len(today_rows))}", ""]
        parts += [f"- {_line(lang, r, rs)}" for rs, r in today_rows]
        parts.append("")
    if week_rows:
        head = "n1.week" if known else "n1.week.monday"
        parts += [f"## {translate(lang, head, n=len(week_rows))}", ""]
        days: dict[date, list[tuple[str, dict[str, Any]]]] = {}
        for rs, r in week_rows:
            days.setdefault(r["visit"].date(), []).append((rs, r))
        for d, items in days.items():
            parts.append(f"**{d.isoformat()} ({translate(lang, 'day.' + WEEKDAYS[d.weekday()])})**")
            parts += [f"- {_line(lang, r, rs)}" for rs, r in items]
            parts.append("")
    visits = [(rs, r) for rs, lf in sorted((life or {}).items()) for r in lf.get("today", []) + lf.get("week", [])]
    if visits:
        parts += [f"## {translate(lang, 'n1.life.week', n=len(visits))}", ""]
        parts += [f"- {_life_row(lang, 'n1.life.row', rs, r)}" for rs, r in sorted(visits, key=lambda x: x[1]["due"])]
        parts.append("")
    if sae:
        parts += [f"## {translate(lang, 'n1.life.sae', n=sae)}", ""]
        parts += [translate(lang, "n1.link", rs=rs, url=f"{url}/studies/{rs}/subjects") for rs, lf in
                  sorted((life or {}).items()) if lf.get("sae")] + [""]  # fmt: skip
    for rs in sorted({rs for rs, _r in today_rows + week_rows}):
        parts.append(translate(lang, "n1.link", rs=rs, url=f"{url}/studies/{rs}/week?list=clinic"))
    parts += ["", "---", why, translate(lang, "notice.settings", url=f"{url}/settings/notices")]
    n_today, n_week = len(today_rows), len(week_rows)
    counts = {"today": n_today, "week": n_week, **({"visits": len(visits)} if visits else {})}
    if sae:
        counts["sae"] = sae
    subject = translate(lang, "n1.subject", day=today.isoformat(), n=n_today or n_week or sae)
    return Notice(
        "N1",
        user.username,
        user.mailbox or "",
        subject,
        "\n".join(parts),
        today.isoformat(),
        counts,
    )


def build_n2(
    user: User,
    person: NotifyPerson,
    today: date,
    studies: Sequence[tuple[str, list[dict[str, Any]], dict[str, Any]]],
    since: str | None,
    life: dict[str, dict[str, Any]] | None = None,
    health: Any = None,
) -> Notice | None:
    """The coordinator's digest. ``studies``: (study, weekly rows, extra) with extra = {marks: [Mark], retry: {pid:
    date}, registry: {pid: status}}; ``since``: the time of the last digest (None = the last 24 hours); ``health``:
    the box's health now (``tb_common.metrics.Health``, T-209a), one line at the top."""
    if today.weekday() >= 5:
        return None
    lang = person.lang
    url = base_url()
    cut = since or (datetime.combine(today, datetime.min.time()) - timedelta(days=1)).isoformat()
    visits: list[str] = []
    steps: list[str] = []
    new: list[str] = []
    marks: list[str] = []
    for rs, rows, extra in studies:
        reg = extra.get("registry") or {}
        retry = extra.get("retry") or {}
        for r in rows:
            mk = r.get("mark")
            if r.get("visit") and r["visit"].date() == today:
                visits.append(_line(lang, r, rs))
            if mk is not None and mk.mark == "approach" and reg.get(r["pid"]) in (None, "candidate"):
                if r["pid"] in retry and retry[r["pid"]] > today.isoformat():
                    continue
                key = "n2.step.retry" if r["pid"] in retry else "n2.step.call"
                steps.append(translate(lang, key, p=r["short"], rs=rs))
            elif mk is not None and mk.mark == "need_info":
                steps.append(translate(lang, "n2.step.info", p=r["short"], rs=rs))
            if r.get("status") == "new" and (r.get("first_at") or "") > cut:
                new.append(translate(lang, "n2.new.row", p=r["short"], rs=rs))
        for ref in extra.get("referrals") or []:  # D-147: ask the treating doctor, record the answer
            p = with_no(ref.pid, (extra.get("nos") or {}).get(ref.pid))
            steps.append(translate(lang, "n2.step.refer", p=p, rs=rs))
        for m in extra.get("marks") or []:
            if m.at > cut:
                p = with_no(m.pid, (extra.get("nos") or {}).get(m.pid))
                marks.append(translate(lang, "n2.mark.row", p=p, rs=rs, mark=translate(lang, "mark." + m.mark)))
    by_study = sorted((life or {}).items())
    due = [_life_row(lang, "n2.life.row", rs, r) for rs, lf in by_study for r in lf.get("today", [])]
    late = [_life_row(lang, "n2.life.row", rs, r) for rs, lf in by_study for r in lf.get("overdue", [])]
    reports = [translate(lang, "n2.life.report.row", p=r["short"], rs=rs, day=r["due"],
                         party=translate(lang, "life.clock.party." + r["party"]))
               for rs, lf in by_study for r in lf.get("reports", [])]  # fmt: skip
    red = health is not None and health.level == "red"
    if not (visits or steps or new or marks or due or late or reports or red):
        return None
    parts = [translate(lang, "n2.hello"), ""]
    if health is not None:  # T-209a: a missing line means the box could not say; a red one is never left out
        parts += [translate(lang, f"health.line.{health.level}", what=health.details()), ""]
    sections = [("n2.visits", visits), ("n2.steps", steps), ("n2.new", new), ("n2.marks", marks)]
    if due or late:  # D-134: the participants' study visits (only when the study has a visit schedule)
        sections = [("n2.life.today", due), ("n2.life.overdue", late), *sections]
    if reports:  # P-03: an SAE report past its due day comes first
        sections = [("n2.life.reports", reports), *sections]
    for key, items in sections:
        parts += [f"## {translate(lang, key, n=len(items))}", ""]
        shown = [f"- {x}" for x in items[:MAX_ROWS]]
        if len(items) > MAX_ROWS:
            shown.append(translate(lang, "n2.more", n=len(items) - MAX_ROWS))
        parts += shown or [translate(lang, "n2.none")]
        parts.append("")
    for rs in sorted({s[0] for s in studies}):
        parts.append(translate(lang, "n2.link", rs=rs, url=f"{url}/home"))
    parts += [
        "",
        "---",
        translate(lang, "n2.why", time=person.digest_time),
        translate(lang, "notice.settings", url=f"{url}/settings/notices"),
    ]
    counts = {"visits": len(visits), "steps": len(steps), "new": len(new), "marks": len(marks)}
    subject = translate(lang, "n2.subject", day=today.isoformat(), **counts)
    if due or late:
        counts |= {"study_visits": len(due), "overdue": len(late)}
    if reports:
        counts["sae_reports"] = len(reports)
    if health is not None:
        counts["health_red"] = int(red)
    return Notice("N2", user.username, user.mailbox or "", subject, "\n".join(parts), today.isoformat(), counts)


def build_health(user: User, person: NotifyPerson, today: date, health: Any) -> Notice:
    """The administrators' daily health mail (T-209a, D-379): the level, then one line per check. Ages, counts and
    percentages only."""
    lang = person.lang
    marks = {"ok": "ok", "warn": "WARN", "red": "RED"}
    parts = [translate(lang, f"health.line.{health.level}", what=health.details()), ""]
    parts += [f"- [{marks[c.level]}] {c.text}" for c in health.checks]
    parts += ["", "---", translate(lang, "health.why"), translate(lang, "notice.settings",
                                                                    url=f"{base_url()}/settings/notices")]  # fmt: skip
    subject = translate(lang, "health.subject", day=today.isoformat(), level=marks[health.level])
    red = sum(c.level == "red" for c in health.checks)
    return Notice("HEALTH", user.username, user.mailbox or "", subject, "\n".join(parts), today.isoformat(),
                  {"red": red, "warn": sum(c.level == "warn" for c in health.checks)})  # fmt: skip


# ---------------------------------------------------------------------------------------------- collecting and sending
def collect(h: Any, today: date, kinds: Sequence[str] = ("N1", "N2")) -> list[Notice]:
    store = h.store
    out: list[Notice] = []
    got: list[Any] = []

    def health_now() -> Any:  # once per round; None when the console has no health (a bare test app)
        if not got:
            fn = getattr(h, "health", None)
            try:
                got.append(fn() if fn is not None else None)
            except Exception:  # a failed health must not stop the digests: the line is then missing
                got.append(None)
        return got[0]

    for u in h.users.users():
        if not u.mailbox or (u.expires and u.expires < today.isoformat()):
            continue
        person = store.notify_person(u.username)
        if not person.enabled:
            continue
        if u.is_admin:  # T-209a: the daily health mail
            if "HEALTH" in kinds and not store.notice_sent("HEALTH", u.username, today.isoformat()):
                hl = health_now()
                if hl is not None:
                    out.append(build_health(u, person, today, hl))
            continue
        sess = Session(u, "", person.lang, "")
        kind = "N1" if u.role == "investigator" else "N2" if u.role == "coordinator" else None
        if kind is None or kind not in kinds or store.notice_sent(kind, u.username, today.isoformat()):
            continue
        studies: list[Any] = []
        life: dict[str, dict[str, Any]] = {}
        for r in h.trials(sess):
            # D-273 (PV-3): N1 carries the study's patient rows; an investigator gets them only as delegated
            may = getattr(h, "may", None)
            if kind == "N1" and may is not None and not may(u, r.id, "screen"):
                continue
            state = store.study_state(r.id)  # D-386 (LIFE-008): the mails follow the study's state
            if state.state not in CARE_STATES:
                continue  # start-up or closed: nothing of this study is mailed
            nos = store.screening_nos(r.id)
            lf = h.life_mail(r.id, today) if getattr(h, "life_mail", None) else None
            if lf and any(lf.get(k) for k in ("today", "week", "overdue", "sae", "reports")):
                life[r.id] = lf  # its rows already carry the screening number beside the pseudonym (D-136)
            if not state.runs:
                continue  # paused: no list rows, marks, calls or new pre-screens; enrolled participants' care stays
            wk = h.week_bundle(sess, r.id)
            if wk is None:
                continue
            seen = store.first_seen(r.id)
            for row in wk["rows"]:
                row["first_at"] = (seen.get(row["pid"]) or ("", ""))[1]
            wk_rows = [row | {"short": with_no(row["pid"], nos.get(row["pid"]))} for row in wk["rows"]]
            if kind == "N1":
                studies.append((r.id, wk_rows))
            else:
                retry = {o.pid: o.retry for o in store.outcomes(r.id) if o.outcome == "not_reached" and o.retry}
                try:
                    reg = {e.pid: e.status for e in h.bk.registry_rows(r.id)}
                except Exception:
                    reg = {}
                listed = {row["pid"] for row in wk["cl"].get("rows") or []} if wk.get("cl") else set()
                team = getattr(h, "team", None)
                refs = [x for x in team.latest_referrals(r.id).values() if x.open and x.pid in listed] if team else []
                studies.append((r.id, wk_rows, {"marks": store.all_marks(r.id), "retry": retry, "registry": reg,
                                                "nos": nos, "referrals": refs}))  # fmt: skip
        n = (
            build_n1(u, person, today, studies, life)
            if kind == "N1"
            else build_n2(u, person, today, studies, store.last_notice("N2", u.username), life, health_now())
        )
        if n is not None:
            out.append(n)
    return out


def send_all(h: Any, today: date, kinds: Sequence[str] = ("N1", "N2"), by: str = "console:notify") -> list[Notice]:
    sent = []
    for n in collect(h, today, kinds):
        h.bk.send_notice(n.kind, [n.to], n.subject, n.body, by)
        h.store.log_notice(n.kind, n.username, n.day, h.clock().isoformat(), n.subject)
        h.au.append("console.notice", actor=by, detail={"action": n.kind, "to": n.to, "subject": n.subject})
        sent.append(n)
    return sent


def register(app: FastAPI, h: Helpers) -> None:
    store = h.store

    @app.get("/settings/notices")
    def settings_page(request: Request, saved: str = "") -> Response:
        sess = h.need(request)
        p = store.notify_person(sess.user.username)
        return h.page(request, "notices.html", sess, person=p, saved=saved == "1", sent=None)

    @app.post("/settings/notices")
    def settings_save(
        request: Request,
        csrf: str = Form(""),
        practitioner_id: str = Form(""),
        digest_time: str = Form("07:30"),
        enabled: str = Form(""),
        lang: str = Form("en"),
    ) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        pid = practitioner_id.strip().upper()[:32] or None
        if pid is not None and not pid.replace("-", "").isalnum():
            raise h.problem(400, "request.refused", reason="the practitioner id is letters and digits")
        if len(digest_time) != 5 or digest_time[2] != ":":
            digest_time = "07:30"
        store.save_notify_person(
            NotifyPerson(sess.user.username, pid, digest_time, enabled == "1", lang if lang in LANGS else "en")
        )
        h.au.append("console.notice_settings", actor=h.actor(sess), detail={"action": "save"})
        return RedirectResponse("/settings/notices?saved=1", status_code=303)

    @app.post("/ops/notices")
    def send_now(request: Request, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        sent = send_all(h, h.today(), by=h.actor(sess))
        p = store.notify_person(sess.user.username)
        return h.page(request, "notices.html", sess, person=p, saved=False, sent=sent)


def main(argv: list[str] | None = None) -> int:
    """``python -m console.notify [--kind N1|N2] [--day YYYY-MM-DD]``: build and send today's notices with the
    console's own settings (TB_CONSOLE_* environment), as the production timer does."""
    ap = argparse.ArgumentParser(prog="console.notify")
    ap.add_argument("--kind", choices=("N1", "N2", "HEALTH"), action="append")
    ap.add_argument("--day", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    from console.app import create_app

    app = create_app()
    h = getattr(app.state, "helpers", None)
    if h is None:
        raise SystemExit("the console pilot workspace is off (TB_CONSOLE_PILOT=1)")
    day = date.fromisoformat(args.day) if args.day else h.today()
    kinds = tuple(args.kind or ("N1", "N2"))
    notices = collect(h, day, kinds) if args.dry_run else send_all(h, day, kinds)
    for n in notices:
        print(f"{n.kind} {n.username} {n.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
