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
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import sys
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
EXTRA_EXCLUSION = "Participation in another interventional drug trial within the last 30 days."


class Clock:
    """The console's clock, set to 07:00 (site time, UTC+9) on the demo day so marks and mail agree with the box."""

    def __init__(self, day: date) -> None:
        self.set(day)

    def set(self, day: date, at: time = time(7, 0)) -> None:
        self.now = datetime.combine(day, at, tzinfo=UTC) - timedelta(hours=9)

    def __call__(self) -> datetime:
        return self.now


def criteria_text(ruleset: str) -> str:
    text = fd.pasted_criteria(ruleset)
    if ruleset == COHORT:  # one criterion reworded
        return text.replace("1. ", "1. 年齢18歳以上で、", 1)
    return text.rstrip("\n") + f"\n15. {EXTRA_EXCLUSION}\n"  # one exclusion added to the trial


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

    shutil.rmtree(work / "console", ignore_errors=True)
    (work / "console").mkdir(parents=True)
    users = UserStore(fd.fresh_console_db(work), clock=clock)  # accounts, sessions and marks start fresh too
    for name, role, mailbox, scope in fd.ACCOUNTS:
        users.create(name, role, password, mailbox)  # type: ignore[arg-type]
        if scope:
            users.set_scope(name, **scope)
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


def sign_in(app: Any, user: str, password: str, lang: str) -> Any:
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
            "practitioner_id": PI_PRACTITIONER if user == "pi" else "",
            "digest_time": "07:30",
        },
    )
    return c


def ok(r: Any, what: str) -> Any:
    assert r.status_code == 200, (what, r.status_code, re.sub(r"<[^>]+>", " ", r.text)[-800:])
    return r


def run(work: Path, password: str, lang: str = "ja") -> dict[str, Any]:
    from console import notify

    box, client, repo, summary = fd.build(work)
    clock = Clock(box.today[0])
    app = console(work, box, client, repo, password, clock)
    h = app.state.helpers
    crc = sign_in(app, "crc", password, lang)
    pi = sign_in(app, "pi", password, lang)
    out: dict[str, Any] = {"summary": summary, "box": box, "app": app, "approvals": {}}

    # 1-2 the coordinator pastes both studies and prepares S20
    jobs = {}
    for rs in (COHORT, TRIAL):
        form = crc.get("/pilot/protocol")
        r = ok(
            crc.post(
                "/pilot/protocol", data={"csrf": fd._csrf(form.text), "ruleset": rs, "criteria": criteria_text(rs)}
            ),
            f"paste {rs}",
        )
        job_id = r.url.path.rsplit("/", 1)[-1]
        job = box.orch.db.get(job_id)
        assert job is not None and job.state == "awaiting_approval", (rs, job and job.state)
        jobs[rs] = job
    s20 = ok(crc.get(f"/pilot/jobs/{jobs[TRIAL].job_id}/approval"), "S20 as coordinator")
    first = re.search(r'data-testid="tick-btn-([A-Z0-9-]+)"', s20.text)
    assert first
    ok(
        crc.post(
            f"/pilot/jobs/{jobs[TRIAL].job_id}/approval/tick", data={"csrf": fd._csrf(s20.text), "crit": first.group(1)}
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
        out["approvals"][rs] = {"amber": ambers, "html": page.text}
        r = pi.post(f"/pilot/jobs/{job.job_id}/approve", data={"csrf": fd._csrf(page.text)}, follow_redirects=False)
        assert r.status_code == 303, (rs, r.status_code, re.sub(r"<[^>]+>", " ", r.text)[-600:])
        after = box.orch.db.get(job.job_id)
        out["approvals"][rs]["feas_state"] = after.state if after else None
    infos = {r.id: r for r in h.bk.rulesets()}
    out["versions"] = {rs: infos[rs].version for rs in jobs}

    # 4 the lists
    for rs, pract in ((TRIAL, ""), (COHORT, COHORT_CLINICS)):
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
    cohort = ok(pi.get(f"/studies/{COHORT}/cohort"), "cohort list")
    out["cohort_html"] = cohort.text
    out["cohort_new"] = len(re.findall(r'data-testid="member-', cohort.text))

    # 5 marks: the PI's first clinic day decides the demo day
    week = h.week_bundle(None, TRIAL)
    rows = week["rows"]
    days = sorted(notify.clinic_days(rows, PI_PRACTITIONER))
    assert days, "no listed candidate is booked with the investigator"
    day = days[0] if days[0].weekday() < 5 else next(d for d in days if d.weekday() < 5)
    clock.set(day)
    mine = [r for r in rows if r.get("practitioner_id") == PI_PRACTITIONER and r.get("visit")]
    mine.sort(key=lambda r: r["visit"])
    picks = (mine + [r for r in rows if r not in mine])[:3]
    assert len(picks) == 3, "fewer than three patients on the list"
    marks = [
        ("approach", {}),
        ("need_info", {"note": "HbA1c の最新値を確認"}),
        ("not_now", {"recheck": (day + timedelta(days=28)).isoformat()}),
    ]
    lst = ok(pi.get(f"/studies/{TRIAL}/week?list=all"), "list")
    out["list_html"] = lst.text
    for row, (mark, extra) in zip(picks, marks, strict=True):
        page = pi.get(f"/studies/{TRIAL}/week?list=all&pid={row['pid']}")
        r = pi.post(
            f"/studies/{TRIAL}/patients/{row['pid']}/mark",
            data={"csrf": fd._csrf(page.text), "mark": mark, "back": "list:all", **extra},
            follow_redirects=False,
        )
        assert r.status_code == 303, (mark, r.status_code, r.text[-300:])
    approached = picks[0]["pid"]
    page = crc.get(f"/studies/{TRIAL}/patients/{approached}")
    r = crc.post(
        f"/studies/{TRIAL}/patients/{approached}/outcome",
        data={"csrf": fd._csrf(page.text), "outcome": "not_reached", "back": "patient"},
        follow_redirects=False,
    )
    assert r.status_code == 303, (r.status_code, r.text[-300:])
    out["picks"] = picks
    out["day"] = day
    out["screening_no"] = h.store.screening_no(TRIAL, approached)
    out["patient_html"] = ok(pi.get(f"/studies/{TRIAL}/patients/{picks[1]['pid']}"), "S5").text

    # 6 the morning mail
    before = len(box.sent)
    sent = notify.send_all(h, day)
    mails = box.sent[before:]
    out["notices"] = sent
    out["mails"] = mails
    out["crc"], out["pi"] = crc, pi
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR", "/tmp/tb-list-demo")))
    ap.add_argument("--lang", default="ja", choices=["ja", "zh-TW", "en"])
    ap.add_argument("--serve", action="store_true", help="keep the console up after the run")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--fresh", action="store_true", help="delete --dir first")
    a = ap.parse_args(argv)
    if a.fresh and a.dir.exists():
        shutil.rmtree(a.dir)
    a.dir.mkdir(parents=True, exist_ok=True)
    password = os.environ.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    res = run(a.dir, password, a.lang)
    for rs, v in res["approvals"].items():
        print(
            f"S20 {rs}: amber {', '.join(v['amber']) or '-'} -> approved v{res['versions'][rs]} "
            f"(feasibility job {v['feas_state']})"
        )
    print(f"cohort list {COHORT}: {res['cohort_new']} new members")
    print(f"demo day {res['day']} · marks: " + ", ".join(f"{p['short']}" for p in res["picks"]))
    print(f"screening number given on Approach: {res['screening_no']}")
    for m in res["mails"]:
        print(f"\n=== mail to {', '.join(m.to)}: {m.subject}\n{m.text()}")
    good = len(res["mails"]) == 2 and all(res["screening_no"] not in m.text() for m in res["mails"])
    if a.serve:
        import uvicorn

        print(f"\nconsole on http://{a.host}:{a.port}/home  accounts: {', '.join(x[0] for x in fd.ACCOUNTS)}")
        if not os.environ.get("TB_DEMO_PASSWORD"):
            print(f"password (all accounts): {password}")
        uvicorn.run(res["app"], host=a.host, port=a.port, log_level="warning")
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
