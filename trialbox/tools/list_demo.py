"""Step-2 list-and-mail demo (20-build-map §2 step 2): approve the criteria on S20, open the patient list, mark three
patients and receive the investigator's pre-clinic mail (N1) and the coordinator's digest (N2) in the mail sink. Stub
model only, no network, no API key.

    python -m tools.list_demo --dir /tmp/tb-list            # run once, print what happened, exit 0 on success
    python -m tools.list_demo --dir /tmp/tb-list --serve    # then keep the console up (accounts as tools.feas_demo)

What it does, on the 5,000-patient synthetic hospital of ``tools.feas_demo``:

1. the coordinator pastes the GOUT-COH registry criteria with one criterion reworded, and the GZQO trial criteria
   with one exclusion added: both compile to a new draft (v1.1.0) that waits for approval;
2. the coordinator ticks one criterion's codes as checked on S20 (its own audit event);
3. the investigator opens S20 for each study, opens every amber line (the "Changes since v1.0.0" box lists them) and
   presses **Approve all**; the waiting feasibility runs resume on the new version;
4. the coordinator asks for the GZQO patient list (SCREEN) and the GOUT-COH cohort list (SCREEN for two clinics);
5. the investigator opens the GZQO list and marks three patients: Approach, Need info and Not now (re-check in four
   weeks); the coordinator records "Not reached" for the approached patient;
6. N1 goes to the investigator on their first clinic day (practitioner P12345), N2 to the coordinator the same
   morning; both are printed from the box's mail sink. Neither carries a chart number or a screening number.

Everything is synthetic; pages and mail are Japanese (``--lang``).

``--trial AD-MAB`` runs the same steps on scenario J1 of the clinician PoC (T-503): the Japanese memory-clinic site
(``tools.synth_hospital --profile jp-ad``, Asia/Tokyo, notes in Japanese and English), the early Alzheimer's
disease trial AD-MAB (protocol in Japanese, investigator P90001 of neurology) and the registry NEUR-COH.

    python -m tools.list_demo --dir /tmp/tb-ad --lang ja --trial AD-MAB
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import feas_demo as fd  # noqa: E402

TRIAL, COHORT = "GZQO", "GOUT-COH"
PI_PRACTITIONER = "P12345"
COHORT_CLINICS = "P12345,P23456,P34567,P45678"
# D-758: within the 40 characters a draft's short label takes in English, a whole phrase ("Participation in another
# interventional" was cut); the same meaning as GZQO-EXC-14, which it rewords
EXTRA_EXCLUSION = "Any other drug trial within 30 days."
# the scenarios: trial -> (registry, investigator, registry clinics, added exclusion, "need info" note, site)
SCENARIOS: dict[str, dict[str, Any]] = {
    "GZQO": {
        "cohort": COHORT,
        "pi": PI_PRACTITIONER,
        "clinics": COHORT_CLINICS,
        "extra": None,
        # DEMO-SEED (D-757): the note in the seed's language (a Japanese note showed in an English session)
        "need_info": {"ja": "HbA1c の最新値を確認", "en": "Check the latest HbA1c", "zh-TW": "確認最新的 HbA1c 數值"},
        # D-757: GZQO-EXC-14 (another interventional study within 30 days) reworded, not added again beside itself
        "reword": ("Participation in another interventional study within 30 days before screening.", EXTRA_EXCLUSION),
        "profile": "ci",
        "settings": None,
    },
    "AD-MAB": {  # scenario J1 (T-503)
        "cohort": "NEUR-COH",
        "pi": "P90001",
        "clinics": "P90001,P90002,P90003",
        "extra": "スクリーニング前30日以内に他の治験に参加した者。",
        "need_info": {
            "ja": "アミロイドPETまたは脳脊髄液検査の結果を確認",
            "en": "Check the amyloid PET or cerebrospinal fluid result",
            "zh-TW": "確認類澱粉蛋白PET或腦脊髓液檢查結果",
        },
        "profile": "jp-ad",
        "settings": fd.SITE_JP,
    },
}


# D-309: the label the investigator gives, on the approval page, a criterion that has no shipped label in the page
# language. It is the shipped rulesets' own label (``rulesets/<id>/labels.yaml``, or the IR's ``label`` in the
# protocol's language) of the criterion it stands for: a reworded criterion stands for itself, the exclusion added
# to each trial (``extra``, another trial within 30 days) for GZQO-EXC-14, which says the same. Never a placeholder.
ADDED_LIKE = ("GZQO", "GZQO-EXC-14")


def shipped_label(ruleset: str, cid: str, lang: str) -> str:
    """The short label the shipped ruleset ``ruleset`` gives criterion ``cid`` in ``lang``; empty when it has none."""
    import json

    import yaml
    from console import ruleset_labels

    tr = (ruleset_labels.shipped(ruleset).get(cid) or {}).get(lang)
    if isinstance(tr, dict) and str(tr.get("label") or "").strip():
        return " ".join(str(tr["label"]).split())
    base = ROOT / "rulesets" / ruleset
    ir, manifest = base / "ir" / f"{cid}.json", base / "manifest.yaml"
    protocol = (yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}) if manifest.is_file() else {}
    if ir.is_file() and protocol.get("language") == lang:  # the IR's own label is in the protocol's language
        return " ".join(str(json.loads(ir.read_text(encoding="utf-8")).get("label") or "").split())
    return ""


def given_label(ruleset: str, cid: str, lang: str) -> str:
    """What the demo's investigator types as the site's label of ``cid`` (D-120, D-309); see :data:`ADDED_LIKE`."""
    own = shipped_label(ruleset, cid, lang)
    if own or (ROOT / "rulesets" / ruleset / "ir" / f"{cid}.json").is_file():
        return own or cid  # a shipped criterion: only its own label
    return shipped_label(*ADDED_LIKE, lang) or cid


# T-513 (UX-003): which day the demo plays. Unset or "data": the synthetic data's own day (tests, drills, the complete
# run). "today": the real day in the site's time zone; the hospital's dates are moved to it, and once the seed is done
# the console and the box follow the real clock (tools.demo sets it). YYYY-MM-DD: that day, with the dates moved.
DAY_ENV = "TB_DEMO_DAY"


def seed_day(today: date) -> date:
    """The day the seed plays for a demo started on ``today``: the last working day (Monday to Friday) before
    ``today`` (DEMO-SEED, D-757; D-496 played the Tuesday before the last Wednesday, so the data was up to a week old
    and every study page said "more than two days old" on the demo day). The seed ends with the screening cadence
    (e2e stage 17), which ingests the seed day's data in the night after it (:func:`cadence_night`): the data date,
    that night's run and every mark stay on or before ``today``, never after it; a working day, so the coordinator's
    morning digest still goes out. On a Tuesday to a Saturday the data is as of yesterday."""
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def cadence_night(day: date) -> date:
    """The night the screening cadence (e2e stage 17) plays after a seed on ``day``: the next day (its ingest takes
    the seed day's data, its run is that night); on or before the demo day (:func:`seed_day`)."""
    return day + timedelta(days=1)


def demo_day(
    tz: str | None = None, environ: Mapping[str, str] | None = None, now: datetime | None = None
) -> date | None:
    """The demo day ``TB_DEMO_DAY`` asks for (see :data:`DAY_ENV`); None for the data's own day. ``tz``: the site's
    zone (else ``TB_TZ``), which decides what "today" is."""
    from console.timefmt import local_today
    from tb_common.config import site_zone

    value = str((os.environ if environ is None else environ).get(DAY_ENV) or "").strip().lower()
    if value in ("", "data"):
        return None
    if value == "today":
        return seed_day(local_today(now or datetime.now(UTC), site_zone(tz)))
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"{DAY_ENV}={value!r}: use today, data or a date YYYY-MM-DD") from exc


def is_live(environ: Mapping[str, str] | None = None) -> bool:
    """True when the demo follows the real clock after its seed (``TB_DEMO_DAY=today``)."""
    return str((os.environ if environ is None else environ).get(DAY_ENV) or "").strip().lower() == "today"


def site_tz_of(box: Any) -> str:
    """The box's site zone (settings ``site.tz``)."""
    return str(box.orch.cfg.settings.site.tz)


class Clock:
    """The console's clock. While the demo seeds it stands at 07:00 site time on the demo day, so marks and mail agree
    with the box; :meth:`go_live` then lets it follow the real time (T-513: one clock for the served demo)."""

    def __init__(self, day: date, tz: str | None = None) -> None:
        from tb_common.config import site_zone

        self.zone = site_zone(tz)  # D-315: the site's zone (else TB_TZ), never a zone of the code's own
        self.live = False
        self.set(day)

    def set(self, day: date, at: time = time(7, 0)) -> None:
        self.now = datetime.combine(day, at, tzinfo=self.zone).astimezone(UTC)

    def go_live(self) -> None:
        self.live = True

    def __call__(self) -> datetime:
        return datetime.now(UTC) if self.live else self.now


def go_live(box: Any, clock: Clock) -> None:
    """T-513: after the seed, the console's clock and the box's day follow the real time in the site's zone, so a demo
    left running (or reopened with --keep) on a later day shows that day everywhere."""
    from console.timefmt import local_today

    zone = clock.zone
    clock.go_live()
    box.today[0] = local_today(datetime.now(UTC), zone)
    box.orch._today = lambda: local_today(datetime.now(UTC), zone)  # the in-process box's day, read on every call


def criteria_text(ruleset: str, trial: str = TRIAL) -> str:
    sc = SCENARIOS[trial]
    text = fd.pasted_criteria(ruleset)
    if ruleset == sc["cohort"]:  # one criterion reworded
        return text.replace("1. ", "1. 年齢18歳以上で、", 1)
    if sc.get("reword"):  # D-757: an exclusion reworded (the trial's own, so its labels are its own in every language)
        old, new = sc["reword"]
        if old not in text:
            raise ValueError(f"{ruleset}: no criterion reads {old!r} to reword")
        return text.replace(old, new, 1)
    n = len(re.findall(r"^\d+\. ", text.split("除外基準", 1)[-1], re.M)) + 1
    return text.rstrip("\n") + f"\n{n}. {sc['extra']}\n"  # one exclusion added to the trial


def console(
    work: Path,
    box: Any,
    client: Any,
    repo: Path,
    password: str,
    clock: Clock,
    extra_env: dict[str, str] | None = None,
) -> Any:
    from console.app import create_app
    from console.auth import UserStore
    from tb_common.audit import AuditLog

    from tools.role_demo import InprocBackend

    # J-4 (D-1224, walk F-10): one day for the box: every stamp of the in-process orchestrator takes the console's
    # clock (list_demo, cgmh_demo, scenarios and public_e2e all build their console here)
    box.orch.clock = clock
    shutil.rmtree(work / "console", ignore_errors=True)
    (work / "console").mkdir(parents=True)
    url = fd.fresh_console_db(work)
    users = UserStore(url, clock=clock)  # accounts, sessions and marks start fresh too
    for name, role, mailbox, scope in fd.ACCOUNTS:
        users.create(name, role, password, mailbox)  # type: ignore[arg-type]
        if scope:
            users.set_scope(name, **scope)
    fd.seed_pi(url)
    env = {
        "TB_ENV": "DEV",
        "TB_CONSOLE_PILOT": "1",
        "TB_DATA_CLASS": "D0",
        "TB_CONSOLE_DIR": str(work / "console"),
        "TB_CONSOLE_ADMIN_EMAIL": "admin@hospa.test",
        "TB_CONSOLE_SECURE_COOKIE": os.environ.get("TB_CONSOLE_SECURE_COOKIE", "0"),  # 1 behind https (demo image)
        **(extra_env or {}),
    }
    return create_app(env, backend=InprocBackend(box, client, repo), audit=AuditLog(box.audit_dir), users=users)


def sign_in(app: Any, user: str, password: str, lang: str, practitioner: str = PI_PRACTITIONER) -> Any:
    from fastapi.testclient import TestClient

    c = TestClient(app)
    tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert tok
    r = c.post("/login", data={"username": user, "password": password, "login_csrf": tok.group(1)})
    assert r.status_code == 200, (user, r.status_code)
    c.post("/lang", data={"csrf": fd._csrf(c.get("/home").text), "lang": lang, "back": "/home"})
    c.post(
        "/settings/notices",
        data={
            "csrf": fd._csrf(c.get("/settings/notices").text),
            "enabled": "1",
            "lang": lang,
            "practitioner_id": practitioner if user == "pi" else "",
            "digest_time": "07:30",
        },
    )
    return c


def ok(r: Any, what: str) -> Any:
    assert r.status_code == 200, (what, r.status_code, re.sub(r"<[^>]+>", " ", r.text)[-800:])
    return r


def run(work: Path, password: str, lang: str = "ja", trial: str = TRIAL, day: date | None = None) -> dict[str, Any]:
    """``day`` (T-513): the demo day, with the hospital's dates moved to it; None reads ``TB_DEMO_DAY`` (unset: the
    data's own day, the PI's first clinic day)."""
    from console import notify
    from console.timefmt import local_today

    sc = SCENARIOS[trial]
    cohort_rs, pi_pr = str(sc["cohort"]), str(sc["pi"])
    tz = ((sc["settings"] or {}).get("site") or {}).get("tz")
    target = day or demo_day(tz)
    if target is not None:
        box, client, repo, summary = fd.build_site(work, str(sc["profile"]), sc["settings"], day=target)
    elif sc["profile"] == "ci" and not sc["settings"]:
        box, client, repo, summary = fd.build(work)  # the form tools.complete_run wraps
    else:
        box, client, repo, summary = fd.build_site(work, sc["profile"], sc["settings"])
    clock = Clock(box.today[0], site_tz_of(box))
    live = day is None and is_live()
    if live and target == local_today(datetime.now(UTC), clock.zone):
        # T-513: seeding on the real day, the console's clock is the real one from the start, as the box's job times
        # are: a 07:00 clock ahead of the real time dated an opt-out after the screening run that should honour it
        clock.go_live()
    app = console(work, box, client, repo, password, clock)
    h = app.state.helpers
    crc = sign_in(app, "crc", password, lang, pi_pr)
    pi = sign_in(app, "pi", password, lang, pi_pr)
    out: dict[str, Any] = {"summary": summary, "box": box, "app": app, "approvals": {}, "clock": clock, "live": live}

    # 1-2 the coordinator pastes both studies and prepares S20
    jobs = {}
    for rs in (cohort_rs, trial):
        form = crc.get("/pilot/protocol")
        r = ok(
            crc.post(
                "/pilot/protocol",
                data={"csrf": fd._csrf(form.text), "ruleset": rs, "criteria": criteria_text(rs, trial)},
            ),
            f"paste {rs}",
        )
        job_id = r.url.path.rsplit("/", 1)[-1]
        job = box.orch.db.get(job_id)
        assert job is not None and job.state == "awaiting_approval", (rs, job and job.state)
        jobs[rs] = job
    ok(crc.get(f"/pilot/jobs/{jobs[trial].job_id}/approval"), "S20 as coordinator")
    # D-146 (review J-27): the investigator ticks a criterion's codes, as only the investigator approves
    s20 = ok(pi.get(f"/pilot/jobs/{jobs[trial].job_id}/approval"), "S20 as investigator")
    first = re.search(r'data-testid="tick-btn-([A-Z0-9-]+)"', s20.text)
    assert first
    ok(
        pi.post(
            f"/pilot/jobs/{jobs[trial].job_id}/approval/tick", data={"csrf": fd._csrf(s20.text), "crit": first.group(1)}
        ),
        "tick",
    )

    # 3 the investigator approves both on S20
    ok(pi.get("/week"), "PI week")
    for rs, job in jobs.items():
        page = ok(pi.get(f"/pilot/jobs/{job.job_id}/approval"), f"S20 {rs}")
        ambers = re.findall(r'data-testid="open-([A-Z0-9-]+)"', page.text)
        for cid in ambers:
            page = ok(pi.get(f"/pilot/jobs/{job.job_id}/approval?open={cid}"), f"open {cid}")
        # D-309: a criterion the coordinator reworded has no shipped label in the page language; the PI gives one
        missing = re.findall(r'data-testid="label-missing-([A-Z0-9-]+)"', page.text)
        for cid in missing:
            ok(
                pi.post(
                    f"/pilot/jobs/{job.job_id}/approval/label",
                    data={"csrf": fd._csrf(page.text), "crit": cid, "text": given_label(rs, cid, lang)},
                ),
                f"label {cid}",
            )
        if missing:
            page = ok(pi.get(f"/pilot/jobs/{job.job_id}/approval"), f"S20 {rs} labelled")
        out["approvals"][rs] = {"amber": ambers, "labelled": missing, "html": page.text}
        r = pi.post(
            f"/pilot/jobs/{job.job_id}/approve",
            data={"csrf": fd._csrf(page.text), "confirm": "yes"},
            follow_redirects=False,
        )
        assert r.status_code == 303, (rs, r.status_code, re.sub(r"<[^>]+>", " ", r.text)[-600:])
        after = box.orch.db.get(job.job_id)
        out["approvals"][rs]["feas_state"] = after.state if after else None
    infos = {r.id: r for r in h.bk.rulesets()}
    out["versions"] = {rs: infos[rs].version for rs in jobs}

    # 4 the lists
    for rs, pract in ((trial, ""), (cohort_rs, str(sc["clinics"]))):
        form = crc.get(f"/pilot/request?ruleset={rs}")
        r = crc.post(
            "/pilot/request",
            data={"csrf": fd._csrf(form.text), "kind": "SCREEN", "ruleset": rs, "pract": pract},
            follow_redirects=False,
        )
        assert r.status_code == 303, (rs, r.status_code, r.text[-400:])
        jid = r.headers["location"].rsplit("/", 1)[-1]
        sj = box.orch.db.get(jid)
        assert sj is not None and sj.state == "done", (rs, sj and sj.state, sj and sj.error)
    cohort = ok(pi.get(f"/studies/{cohort_rs}/cohort"), "cohort list")
    out["cohort_html"] = cohort.text
    out["cohort_new"] = len(re.findall(r'data-testid="member-', cohort.text))

    # 5 marks: the PI's first clinic day decides the demo day
    week = h.mail_week(trial)  # NEW-SEC-1 (D-717): the weekly list as the mail reads it
    rows = week["rows"]
    days = sorted(notify.clinic_days(rows, pi_pr))
    assert days, "no listed candidate is booked with the investigator"
    if target is not None:  # T-513: the demo day is the day asked for (its dates were moved to it), never a later one
        day = target
    else:
        day = days[0] if days[0].weekday() < 5 else next(d for d in days if d.weekday() < 5)
    if day != box.today[0]:  # a later clinic day (another hospital size): sessions end after 8 h, so sign in again
        box.today[0] = day  # the box moves with the console: one site has one date (an EDC acknowledgement or visit
        clock.set(day)  # dated "today" by the console is otherwise "in the future" for the box, finding EDC-16)
        crc = sign_in(app, "crc", password, lang, pi_pr)
        pi = sign_in(app, "pi", password, lang, pi_pr)
    clock.set(day)
    mine = [r for r in rows if r.get("practitioner_id") == pi_pr and r.get("visit")]
    mine.sort(key=lambda r: r["visit"])
    picks = (mine + [r for r in rows if r not in mine])[:3]
    assert len(picks) == 3, "fewer than three patients on the list"
    marks = [
        ("approach", {}),
        ("need_info", {"note": str(sc["need_info"].get(lang) or sc["need_info"]["en"])}),
        ("not_now", {"recheck": (day + timedelta(days=28)).isoformat()}),
    ]
    lst = ok(pi.get(f"/studies/{trial}/week?list=all"), "list")
    out["list_html"] = lst.text
    for row, (mark, extra) in zip(picks, marks, strict=True):
        page = pi.get(f"/studies/{trial}/week?list=all&pid={row['pid']}")
        r = pi.post(
            f"/studies/{trial}/patients/{row['pid']}/mark",
            data={"csrf": fd._csrf(page.text), "mark": mark, "back": "list:all", **extra},
            follow_redirects=False,
        )
        assert r.status_code == 303, (mark, r.status_code, r.text[-300:])
    approached = picks[0]["pid"]
    page = crc.get(f"/studies/{trial}/patients/{approached}")
    r = crc.post(
        f"/studies/{trial}/patients/{approached}/outcome",
        data={"csrf": fd._csrf(page.text), "outcome": "not_reached", "back": "patient"},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[-300:])
    out["picks"] = picks
    out["day"] = day
    out["screening_no"] = h.store.screening_no(trial, approached)
    out["patient_html"] = ok(pi.get(f"/studies/{trial}/patients/{picks[1]['pid']}"), "S5").text

    # 6 the morning mail
    before = len(box.sent)
    sent = notify.send_all(h, day)
    mails = box.sent[before:]
    out["notices"] = sent
    out["mails"] = mails
    out["crc"], out["pi"] = crc, pi
    out["trial"], out["cohort"] = trial, cohort_rs
    return out


def main(argv: list[str] | None = None) -> int:
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR") or scratch_root() / "tb-list-demo"))
    ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--serve", action="store_true", help="keep the console up after the run")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--fresh", action="store_true", help="delete --dir first")
    ap.add_argument("--trial", default=TRIAL, choices=sorted(SCENARIOS), help="AD-MAB: scenario J1 (T-503)")
    ap.add_argument("--day", default=os.environ.get(DAY_ENV) or "data",
                    help="today, data (the synthetic data's own day) or YYYY-MM-DD (T-513; TB_DEMO_DAY)")  # fmt: skip
    a = ap.parse_args(argv)
    os.environ[DAY_ENV] = a.day
    if a.fresh and a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    res = run(a.dir, password, a.lang, a.trial)
    for rs, v in res["approvals"].items():
        print(
            f"S20 {rs}: amber {', '.join(v['amber']) or '-'} -> approved v{res['versions'][rs]} "
            f"(feasibility job {v['feas_state']})"
        )
    print(f"cohort list {res['cohort']}: {res['cohort_new']} new members")
    print(f"demo day {res['day']} · marks: " + ", ".join(f"{p['short']}" for p in res["picks"]))
    print(f"screening number given on Approach: {res['screening_no']}")
    for m in res["mails"]:
        print(f"\n=== mail to {', '.join(m.to)}: {m.subject}\n{m.text()}")
    good = len(res["mails"]) == 2
    if a.serve:
        import uvicorn

        if res["live"]:
            go_live(res["box"], res["clock"])

        print(f"\nconsole on http://{a.host}:{a.port}/home  accounts: {', '.join(x[0] for x in fd.ACCOUNTS)}")
        if not os.environ.get("TB_DEMO_PASSWORD"):
            print(f"password (all accounts): {password}")
        uvicorn.run(res["app"], host=a.host, port=a.port, log_level="warning")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
