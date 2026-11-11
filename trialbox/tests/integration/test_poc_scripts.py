"""T-508: the English PoC scripts of ``docs/poc/scripts/`` walked task by task in process, on the current master.

The acceptance of card T-508 is "an internal dry run completes every task on tag ``poc-1``". The tag does not exist
yet, so this test is the dry run's stand-in: it reads every task id from the English script of each site
(``jp.en.md``, ``tw.en.md``), walks that task through the console as the tester would (the same pages, the same
forms, the tester's own accounts), and checks the expected result the script states. A task in the script without a
step here, or a step here without a task in the script, fails the test.

The two sites are built as the PoC host builds them, from the synthetic hospitals of T-503 (``jp-ad``, Asia/Tokyo:
AD-MAB and NEUR-COH) and T-504 (``tw-ra``, Asia/Taipei: RA-JAK, the GZQO amendment and the GOUT-COH registry
prefill). The owner's seeding runs first, with the built-in accounts and demo mode still off; then demo mode
(``demo.mode``, D-328) is switched on and each tester's three accounts (PI, sub-investigator, CRC; T-505b) sign in
for the first time with the second factor on. Stub model, synthetic data only, no network.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tools import cgmh_demo as cd
from tools import demo
from tools import feas_demo as fd
from tools import list_demo as ld

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "docs" / "poc" / "scripts"
TASK_ROW = re.compile(r"^\| ((JP|TW)-(PI|SI|CRC)-(\d{2})) \|", re.M)
ROLES = ("PI", "SI", "CRC")
NATIVE = {"jp": "ja", "tw": "zh-TW"}
SEED_PW = "seed-" + "s" * 16  # the built-in accounts the owner's seeding uses (switched off for the testers)
OWN_PW = "tester-own-password-01"  # what each tester types at the forced password change


def task_ids(site: str, lang: str) -> list[str]:
    return [m.group(1) for m in TASK_ROW.finditer((SCRIPTS / f"{site}.{lang}.md").read_text(encoding="utf-8"))]


def text(html: str) -> str:
    """A page's main text, tags removed (what a reader sees)."""
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    m = re.search(r"<main.*?</main>", body, re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", m.group(0) if m else body).replace("&#39;", "'").split())


def csrf(html: str) -> str:
    return fd._csrf(html)


# ---------------------------------------------------------------------------------------------------- the scripts
@pytest.mark.parametrize("site", ["jp", "tw"])
def test_each_script_has_ten_tasks_per_role_in_both_languages(site: str) -> None:
    en = task_ids(site, "en")
    native = task_ids(site, NATIVE[site])
    assert en == native, "the English and the native script must list the same tasks in the same order"
    for role in ROLES:
        mine = [t for t in en if t.split("-")[1] == role]
        assert mine == [f"{site.upper()}-{role}-{i:02d}" for i in range(1, 11)], (role, mine)


# ---------------------------------------------------------------------------------------------------- one site
@dataclass
class Site:
    key: str
    work: Path
    box: Any
    app: Any
    served: Any  # the app as the PoC host serves it: each account lands in its own language (T-505b)
    clock: Any
    issued: dict[str, dict[str, str]]
    seconds: list[float] = field(default_factory=lambda: [1_800_000_000.0])
    secrets_: dict[str, str] = field(default_factory=dict)
    c: dict[str, TestClient] = field(default_factory=dict)  # the signed-in browsers, by account
    state: dict[str, Any] = field(default_factory=dict)  # what one task leaves for a later one
    walked: list[str] = field(default_factory=list)

    @property
    def h(self) -> Any:
        return self.app.state.helpers

    def tick(self) -> None:
        """The authenticator's clock moves one 30-second step: a code is never replayed."""
        self.seconds[0] += 30

    def code(self, user: str) -> str:
        from console import totp

        self.tick()
        return totp.totp(self.secrets_[user], self.seconds[0])

    def sign_in(self, user: str, password: str, enrol: str = "") -> TestClient:
        """Sign in through the page with the second factor; the first time, set up the authenticator with the
        enrolment code the owner handed out (the key is read from the page, as a phone would scan it)."""
        c = TestClient(self.served)
        tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
        assert tok
        page = c.post("/login", data={"username": user, "password": password, "login_csrf": tok.group(1)})
        assert page.url.path == "/login/totp", (user, page.status_code, text(page.text)[:300])
        key = re.search(r'data-testid="totp-key"[^>]*value="([^"]+)"|value="([^"]+)"[^>]*data-testid="totp-key"',
                        page.text)  # fmt: skip
        data = {"mfa_csrf": re.search(r'name="mfa_csrf" value="([^"]+)"', page.text).group(1)}  # type: ignore[union-attr]
        if key:
            self.secrets_[user] = (key.group(1) or key.group(2)).replace(" ", "")
            data["enrol_code"] = enrol
        data["code"] = self.code(user)
        r = c.post("/login/totp", data=data, follow_redirects=False)
        assert r.status_code == 303, (user, r.status_code, text(r.text)[:300])
        self.c[user] = c
        return c

    def get(self, user: str, path: str, status: int = 200) -> Any:
        r = self.c[user].get(path)
        assert r.status_code == status, (user, path, r.status_code, text(r.text)[-500:])
        return r

    def post(self, user: str, path: str, data: dict[str, Any], page: str, **kw: Any) -> Any:
        """A form post as the browser sends it: the page it was on gives the form's token."""
        return self.c[user].post(path, data={"csrf": csrf(page), **data}, **kw)


def _accounts(site: str) -> dict[str, Any]:
    """The tester accounts file of the PoC host (T-505b), English accounts for the English dry run. Placeholder
    names only; the real file lives outside the image and outside the repository."""
    if site == "jp":
        pi_log = [{"study": "AD-MAB", "role": "pi"}, {"study": "NEUR-COH", "role": "pi"}]
        si_log = [{"study": "AD-MAB", "role": "sub_pi", "tasks": ["screen", "refer"]}]
        crc_log = [{"study": "AD-MAB", "role": "crc"}, {"study": "NEUR-COH", "role": "crc"}]
    else:
        pi_log = [{"study": "RA-JAK", "role": "pi"}, {"study": "GZQO", "role": "pi"}]
        si_log = [{"study": "RA-JAK", "role": "sub_pi", "tasks": ["screen", "refer"]}]
        crc_log = [{"study": s, "role": "crc"} for s in ("RA-JAK", "GZQO", "GOUT-COH")]
    return {"accounts": [
        {"username": f"{site}.pi", "name": "Tester (PI)", "role": "investigator", "language": "en",
         "expires": "2027-01-31", "delegation": pi_log},
        {"username": f"{site}.subpi", "name": "Tester (sub-I)", "role": "investigator", "language": "en",
         "expires": "2027-01-31", "delegation": si_log},
        {"username": f"{site}.crc", "name": "Tester (CRC)", "role": "coordinator", "language": "en",
         "expires": "2027-01-31", "delegation": crc_log},
    ]}  # fmt: skip


def build(site: str, work: Path, monkeypatch: pytest.MonkeyPatch) -> Site:
    """The site as the owner leaves it before the first session: lists run, demo mode on, tester accounts issued."""
    from console.app import COOKIE
    from tb_common import flags as fl
    from tb_common.audit import AuditLog

    profile, settings = ("jp-ad", fd.SITE_JP) if site == "jp" else (cd.PROFILE, cd.SITE_TW)
    monkeypatch.setenv("TB_TZ", settings["site"]["tz"])  # one synthetic site in one process: its site.tz (D-315)
    box, client, repo, _ = fd.build_site(work, profile, settings)
    clock = ld.Clock(box.today[0])
    app = ld.console(work, box, client, repo, SEED_PW, clock, extra_env={"TB_CONSOLE_MFA": "totp"})
    served = demo.DefaultLanguage(app, app.state.helpers.users, {}, COOKIE)
    s = Site(site, work, box, app, served, clock, {})
    app.state.identity.now = lambda: s.seconds[0]
    users = app.state.helpers.users
    for name in ("admin", "crc", "pi"):
        s.sign_in(name, SEED_PW, users.issue_enrol_code(name))
    seed(s)
    # the owner switches demo mode on (as on /ops/flags: audited, with a reason)
    fl.Flags(audit=AuditLog(box.audit_dir)).set("demo.mode", "on", actor="console:admin", reason="PoC sessions")
    fl.clear_cache()
    # the tester accounts (T-505b): own passwords, enrolment codes, the delegation log; built-ins switched off
    from console.teamstore import TeamStore

    accounts = demo.parse_accounts(_accounts(site))
    issued = work / demo.ISSUED
    demo.seed_accounts(users, TeamStore(), accounts, today=users.today(), now=clock().isoformat(), totp=True,
                       issued=issued, known_studies={r.id.upper() for r in s.h.bk.rulesets()},
                       audit=AuditLog(box.audit_dir))  # fmt: skip
    for line in issued.read_text(encoding="utf-8").splitlines():
        _, user, kind, value = line.split("\t")
        s.issued.setdefault(user, {})[kind] = value
    s.served.langs.update({a.username: a.language for a in accounts})
    demo.switch_off_builtin(users, {a.username for a in accounts})  # the shared-password accounts are off
    return s


def seed(s: Site) -> None:
    """The owner's seeding of the site (demo mode still off): the lists the testers open."""
    ctx = {"crc": s.c["crc"], "box": s.box, "h": s.h}
    if s.key == "jp":
        cd.screen(ctx, "AD-MAB")
        cd.screen(ctx, "NEUR-COH", "P90001,P90002,P90003")
        return
    cd.screen(ctx, "RA-JAK")
    cd.screen(ctx, "GZQO")
    # T1: the sponsor's amendment arrives; the coordinator pastes it and it waits on S20 for the PI (task TW-PI-08)
    form = s.c["crc"].get("/pilot/protocol")
    criteria = cd.criteria_text("GZQO", {cd.BMI_FROM: cd.BMI_TO}, (cd.ADDED,))
    r = s.c["crc"].post("/pilot/protocol", data={"csrf": csrf(form.text), "ruleset": "GZQO", "criteria": criteria})
    assert r.status_code == 200, text(r.text)[-400:]
    s.state["amend_job"] = r.url.path.rsplit("/", 1)[-1]
    # T3: the GOUT-COH registry is linked to REDCap (the built-in simulator) and one member is taken on
    seed_registry(s)


def seed_registry(s: Site) -> None:
    from rc_bridge.client import RedcapClient
    from rc_sim.app import create_app, register_inproc

    crc, pi, admin, h = s.c["crc"], s.c["pi"], s.c["admin"], s.h
    res = cd.screen({"crc": crc, "box": s.box, "h": h}, cd.REGISTRY, cd.CLINICS)
    pid = sorted(res["rows"])[0]
    visit = h.today()
    for who, role in (("pi", "pi"), ("crc", "crc")):
        r = pi.post(f"/studies/{cd.REGISTRY}/team", data={"csrf": csrf(pi.get("/home").text), "username": who,
                    "role": role, "start": visit.isoformat(), "training_day": visit.isoformat()},
                    follow_redirects=False)  # fmt: skip
        assert r.status_code == 303, (who, text(r.text)[-300:])
    r = pi.post(f"/studies/{cd.REGISTRY}/patients/{pid}/mark", data={"csrf": csrf(pi.get(f"/studies/{cd.REGISTRY}/patients/{pid}").text),
                "mark": "approach", "back": "patient"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    no = h.store.screening_no(cd.REGISTRY, pid)
    sim = create_app()
    register_inproc(sim)
    made = TestClient(sim).post("/sim/projects", json={"title": "GOUT-COH CRF", "metadata": cd.COH_CRF}).json()
    rc = RedcapClient(cd.SIM_URL, made["token"])
    rc.import_records([{"record_id": "1", "tb_screening_no": no}])
    page = admin.get("/admin/redcap")
    r = admin.post("/admin/redcap", data={"csrf": csrf(page.text), "token_ref": "edc", "url": cd.SIM_URL,
                                           "token": made["token"]})  # fmt: skip
    assert r.status_code == 200
    sw = {"csrf": csrf(pi.get(f"/studies/{cd.REGISTRY}/edc").text), "on": "1", "kind": "sponsor_letter",
          "reference": "IIT-GOUTCOH-001", "ack_date": visit.isoformat(), "reentry_pages": "30",
          "reentry_accuracy": "98.6"}  # fmt: skip
    assert pi.post(f"/studies/{cd.REGISTRY}/edc/switch", data=sw, follow_redirects=False).status_code == 303
    mp = crc.get(f"/studies/{cd.REGISTRY}/edc/map")
    r = crc.post(f"/studies/{cd.REGISTRY}/edc/dictionary", data={"csrf": csrf(mp.text), "token_ref": "edc",
                 "record_field": "record_id"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    tok = TestClient(s.app).post(
        "/api/v1/session", json={"username": "crc", "password": SEED_PW, "code": s.code("crc")}
    )
    assert tok.status_code == 200, tok.text[:300]
    hd = {"authorization": f"Bearer {tok.json()['token']}"}
    r = TestClient(s.app).put(f"/api/v1/studies/{cd.REGISTRY}/edc/map", json={"items": cd.COH_MAP, "target": cd.TARGET},
                      headers=hd)  # fmt: skip
    assert r.status_code == 200, r.text[:300]
    s.state.update(reg_pid=pid, reg_no=no, rc=rc)


def first_sign_in(s: Site, role: str) -> TestClient:
    """Task 01 of every script: the first sign-in with the issued password and enrolment code, the authenticator
    set up, the forced password change, the acknowledgement; then the account's landing page."""
    from console import demo_guard as dg

    user = f"{s.key}.{role}"
    got = s.issued[user]
    c = s.sign_in(user, got["password"], got["enrolment code"])
    acct = c.get("/home")
    assert acct.url.path == "/account", acct.url  # D-279: a password someone else set is replaced first
    r = c.post("/account/password", data={"csrf": csrf(acct.text), "current": got["password"], "new": OWN_PW,
                                          "again": OWN_PW})  # fmt: skip
    assert r.url.path == "/login"  # the change signs the account out everywhere: sign in again
    c = s.sign_in(user, OWN_PW)
    page = c.get("/home")
    assert page.url.path == "/demo/ack", page.url
    ack = text(page.text)
    assert "synthetic" in ack.lower() and 'lang="en"' in page.text
    r = c.post("/demo/ack", data={"csrf": csrf(page.text), "back": "/home", **{k: "yes" for k in dg.REQUIRED}})
    assert r.status_code == 200 and r.url.path != "/demo/ack", r.url
    assert 'data-testid="demo-banner"' in r.text or "not a medical device" in r.text.lower()
    s.state[f"landing.{role}"] = r
    return c


# ---------------------------------------------------------------------------------------------------- shared steps
Step = Callable[["Site"], None]
STEPS: dict[str, Step] = {}


def step(*ids: str) -> Callable[[Step], Step]:
    def put(fn: Step) -> Step:
        for i in ids:
            STEPS[i] = fn
        return fn

    return put


def rows(s: Site, rs: str) -> list[dict[str, Any]]:
    wk = s.h.week_bundle(None, rs)
    return list((wk["cl"] or {}).get("rows") or [])


def pick(s: Site, rs: str, n: int) -> str:
    """The n-th patient of the PI's first worklist ("Clinic, next 2 weeks": earliest booked visit first), as the
    list showed it before the first mark."""
    key = f"order.{rs}"
    if key not in s.state:
        page = s.get(f"{s.key}.pi", f"/studies/{rs}/week?list=clinic").text
        short = list(dict.fromkeys(re.findall(r'data-testid="row-([0-9a-f]{8})"', page)))
        full = {str(r["pid"])[:8]: str(r["pid"]) for r in rows(s, rs)}
        s.state[key] = [full[x] for x in short if x in full]
    return str(s.state[key][n])


def sheet(s: Site, user: str, rs: str, pid: str, query: str = "") -> Any:
    return s.get(user, f"/studies/{rs}/patients/{pid}{query}")


def mark(s: Site, user: str, rs: str, pid: str, value: str, **extra: str) -> Any:
    page = sheet(s, user, rs, pid).text
    return s.post(user, f"/studies/{rs}/patients/{pid}/mark", {"mark": value, "back": "patient", **extra}, page)


def row_text(html: str, cid: str) -> str:
    """One row of the criteria table (the row that names the criterion id), as the reader sees it."""
    for tr in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
        if cid in tr:
            return text(tr)
    return ""


def landing(s: Site, role: str) -> Any:
    return s.state[f"landing.{role}"]


@step("JP-PI-01", "TW-PI-01")
def _pi_first(s: Site) -> None:
    first_sign_in(s, "pi")
    study = "AD-MAB" if s.key == "jp" else "RA-JAK"
    page = landing(s, "pi")
    if s.key == "tw":  # two studies with a list (RA-JAK, GZQO): the week page asks which one first
        assert page.url.path == "/week" and "RA-JAK" in text(page.text) and "GZQO" in text(page.text)
        page = s.get(f"{s.key}.pi", f"/studies/{study}/week")
    assert page.url.path == f"/studies/{study}/week", page.url
    assert f"This week's patients · {study}" in text(page.text)


@step("JP-SI-01", "TW-SI-01")
def _si_first(s: Site) -> None:
    first_sign_in(s, "subpi")
    study = "AD-MAB" if s.key == "jp" else "RA-JAK"
    page = landing(s, "subpi")
    assert page.url.path == f"/studies/{study}/week" and f"This week's patients · {study}" in text(page.text)


@step("JP-CRC-01", "TW-CRC-01")
def _crc_first(s: Site) -> None:
    first_sign_in(s, "crc")
    page = landing(s, "crc")
    assert page.url.path == "/home" and "My tasks" in text(page.text)


@step("JP-PI-02", "TW-PI-02")
def _pi_sheet(s: Site) -> None:
    rs = s.state["trial"]
    pid = pick(s, rs, 0)
    t = text(sheet(s, f"{s.key}.pi", rs, pid).text)
    for part in ("Why this patient fits", "Still open", "Needs you", "To do", "Ask treating doctor", "Approach",
                 "Need info", "Not suitable now", "Every criterion with its evidence"):  # fmt: skip
        assert part in t, part


@step("JP-PI-05", "TW-PI-05")
def _pi_need_info(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.pi"
    pid = pick(s, rs, 1)
    r = mark(s, user, rs, pid, "need_info", note="Please check the latest record (PoC test note)")
    assert r.status_code == 200 and 'data-testid="undo"' in r.text
    assert "Sent to the coordinator's task list." in text(r.text)
    s.state["need_info"] = pid


@step("JP-PI-06", "TW-PI-06")
def _pi_not_suitable(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.pi"
    pid = pick(s, rs, 2)
    r = mark(s, user, rs, pid, "not_suitable")
    assert r.status_code == 400 and "Choose a reason first." in text(r.text)  # no reason, no mark (D-133)
    reason = re.search(r'<option value="([a-z_]+)">', sheet(s, user, rs, pid).text.split('name="reason"', 1)[1])
    assert reason
    r = mark(s, user, rs, pid, "not_suitable", reason=reason.group(1))
    assert r.status_code == 200 and 'data-testid="undo"' in r.text
    assert s.h.store.latest_marks(rs)[pid].mark == "not_suitable"
    r = s.post(user, f"/studies/{rs}/patients/{pid}/mark", {"mark": "undo", "back": "patient"}, r.text)
    assert r.status_code == 200
    assert pid not in s.h.store.latest_marks(rs) or s.h.store.latest_marks(rs)[pid].mark != "not_suitable"


@step("JP-PI-07", "TW-PI-07")
def _pi_approach(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.pi"
    pid = pick(s, rs, 0)
    page = sheet(s, user, rs, pid)
    assert 'data-testid="irb-warning"' in page.text  # no IRB approval date, no consent-form version
    r = mark(s, user, rs, pid, "approach")
    assert r.status_code == 200 and "Approved. The coordinator has a task to contact this patient." in text(r.text)
    no = s.h.store.screening_no(rs, pid)
    assert no and no.startswith(f"{rs}-")
    log = text(s.get(user, f"/studies/{rs}/screening-log").text)
    assert no in log and "Approach despite IRB warning" in log, log[:400]
    s.state.update(approached=pid, screening_no=no)


@step("JP-PI-08", "TW-PI-04")
def _pi_referral(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.pi"
    pid = pick(s, rs, 3)
    page = s.get(user, f"/studies/{rs}/candidates/{pid}?purpose=referral")
    assert 'data-testid="referral-form"' in page.text, text(page.text)[:400]
    r = s.post(user, f"/studies/{rs}/candidates/{pid}/referral", {"route": "suggested", "note": "PoC test"},
               page.text)  # fmt: skip
    assert r.status_code == 200 and r.url.path == f"/studies/{rs}/referrals", r.url
    assert "Referral requested. It is on the screening log." in text(r.text)
    assert "Waiting for the doctor 1" in text(r.text)
    after = sheet(s, user, rs, pid).text
    assert "Approach waits for the treating doctor" in text(after)
    assert 'data-testid="ref-wait"' in after and f'data-testid="approach-{pid[:8]}"' not in after
    s.state["referred"] = pid


@step("JP-PI-09", "TW-PI-09")
def _pi_not_matched(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.pi"
    page = s.get(user, f"/studies/{rs}/not-matched")
    assert "Criteria not matched" in text(page.text)
    m = re.search(r'action="(/studies/[^/]+/not-matched/([0-9a-f]+)/review)"', page.text)
    assert m
    form = page.text[m.start() :].split("</form>", 1)[0]
    crit = re.search(r'name="crit" value="([^"]*)"', form)
    r = s.post(user, m.group(1), {"crit": crit.group(1) if crit else "", "note": "PoC test: looks wrong"}, page.text)
    assert r.status_code == 200 and "Sent to review. It is recorded with your name" in text(r.text)
    s.state["reviewed"] = m.group(2)


@step("JP-PI-10", "TW-PI-10")
def _pi_reveal(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.pi"
    pid = s.state["approached"]
    page = sheet(s, user, rs, pid)
    r = s.post(user, f"/studies/{rs}/patients/{pid}/reveal", {"reason": "contact"}, page.text)
    assert r.status_code == 200 and 'data-testid="mrn"' in r.text, text(r.text)[-300:]
    again = sheet(s, user, rs, pid).text
    assert 'data-testid="mrn"' not in again  # shown once
    events = [e for e in s.h.bk.audit(None, 5000) if e.event.endswith("reveal") and e.actor == f"console:{user}"]
    assert events


# ---------------------------------------------------------------------------------------------------- Japan site
@step("JP-PI-03")
def _jp_criteria(s: Site) -> None:
    pid = pick(s, "AD-MAB", 0)
    html = sheet(s, "jp.pi", "AD-MAB", pid).text
    mmse, anticoag, egfr, amyloid = (row_text(html, f"AD-MAB-{c}") for c in ("INC-03", "EXC-01", "EXC-04", "INC-05"))
    assert "test model" in mmse and "unknown" in mmse and "the notes" in mmse, mmse
    assert "coded records" in anticoag and "present" in anticoag, anticoag  # "not present" or "present"
    assert "coded records" in egfr and re.search(r"present|unknown the score cannot be computed", egfr), egfr
    assert "unknown" in amyloid, amyloid
    assert pid in {str(r["pid"]) for r in rows(s, "AD-MAB")}  # unknown keeps the patient on the list
    excluded = s.get("jp.pi", "/studies/AD-MAB/not-matched?show=all").text
    assert f"patient {pid[:8]}" not in text(excluded)


@step("JP-PI-04")
def _jp_cohort(s: Site) -> None:
    page = s.get("jp.pi", "/studies/NEUR-COH/cohort")
    t = text(page.text)
    assert "NEUR-COH · Cohort list" in t and "There is no contact step" in t
    assert 'data-testid="markbar"' not in page.text


@step("JP-SI-02", "TW-SI-02")
def _si_log(s: Site) -> None:
    rs = s.state["trial"]
    t = text(s.get(f"{s.key}.subpi", f"/studies/{rs}/team").text)
    assert "Sub-investigator" in t and "Only the study's PI keeps the delegation log." in t
    entry = next(e for e in s.h.team.entries(rs) if e.username == f"{s.key}.subpi")
    assert set(entry.tasks) == {"screen", "refer"}


@step("JP-SI-03", "TW-SI-03")
def _si_no_approach(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.subpi"
    pid = pick(s, rs, 4)
    html = sheet(s, user, rs, pid).text
    assert f'data-testid="approach-{pid[:8]}"' not in html and f'data-testid="need_info-{pid[:8]}"' in html
    r = mark(s, user, rs, pid, "approach")  # typed by hand: refused all the same
    assert r.status_code == 403


@step("JP-SI-04", "TW-SI-04")
def _si_need_info(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.subpi"
    pid = pick(s, rs, 4)
    r = mark(s, user, rs, pid, "need_info", note="Sub-investigator note (PoC test)")
    assert r.status_code == 200
    assert f"· {user} · Need info" in text(sheet(s, user, rs, pid).text)


@step("JP-SI-05", "TW-SI-05")
def _si_referral(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.subpi"
    pid = pick(s, rs, 5)
    page = s.get(user, f"/studies/{rs}/candidates/{pid}?purpose=referral")
    r = s.post(user, f"/studies/{rs}/candidates/{pid}/referral", {"route": "suggested"}, page.text)
    assert r.status_code == 200 and "Waiting for the doctor" in text(r.text)


@step("JP-SI-06", "TW-SI-06")
def _si_not_matched(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.subpi"
    t = text(s.get(user, f"/studies/{rs}/not-matched").text)
    assert "Criteria not matched" in t and "This is wrong, send to review" in t


@step("JP-SI-07", "TW-SI-07")
def _si_not_delegated(s: Site) -> None:
    other = "NEUR-COH" if s.key == "jp" else "GZQO"
    r = s.get(f"{s.key}.subpi", f"/studies/{other}/week", status=404)
    t = text(r.text)
    assert "Page not found" in t and "not one of yours" in t and "My home page" in t


@step("JP-SI-08", "TW-SI-08")
def _si_reveal(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.subpi"
    pid = pick(s, rs, 4)
    r = s.post(user, f"/studies/{rs}/patients/{pid}/reveal", {"reason": "eligibility"}, sheet(s, user, rs, pid).text)
    assert r.status_code == 200 and 'data-testid="mrn"' in r.text


@step("JP-SI-09", "TW-SI-09")
def _si_irb(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.subpi"
    page = s.get(user, f"/studies/{rs}/irb")
    assert "IRB and consent form" in text(page.text) and 'name="approval_no"' not in page.text


@step("JP-SI-10", "TW-SI-10", "JP-CRC-10", "TW-CRC-10")
def _sign_out(s: Site) -> None:
    c = s.c[f"{s.key}.{s.state['_role']}"]
    r = c.post("/logout", data={"csrf": csrf(c.get("/help").text)})
    assert r.url.path == "/login"
    assert c.get("/home").url.path == "/login"


@step("JP-CRC-02", "TW-CRC-02")
def _crc_tasks(s: Site) -> None:
    pid = s.state["need_info"]
    t = text(s.get(f"{s.key}.crc", "/home").text)
    assert f"patient {pid[:8]}" in t and "PoC test note" in t, t[:600]


@step("JP-CRC-03", "TW-CRC-03")
def _crc_outcome(s: Site) -> None:
    rs, user, pid = s.state["trial"], f"{s.key}.crc", s.state["approached"]
    page = sheet(s, user, rs, pid)
    assert s.state["screening_no"] in text(page.text)
    r = s.post(user, f"/studies/{rs}/patients/{pid}/outcome", {"outcome": "reached_booked", "back": "patient"},
               page.text)  # fmt: skip
    assert r.status_code == 200 and 'data-testid="done"' in r.text
    log = text(s.get(user, f"/studies/{rs}/screening-log").text)
    assert "Reached, visit booked" in log, log[:500]


@step("JP-CRC-04", "TW-CRC-04")
def _crc_answer(s: Site) -> None:
    rs, user, pid = s.state["trial"], f"{s.key}.crc", s.state["referred"]
    page = s.get(user, f"/studies/{rs}/referrals")
    ref = next(r for r in s.h.team.referrals(rs) if r.pid == pid)
    r = s.post(user, f"/studies/{rs}/referrals/{ref.id}/answer", {"answer": "agree", "channel": "phone"}, page.text)
    assert r.status_code == 200 and "Doctor agreed 1" in text(r.text), text(r.text)[:400]
    assert "The PI may now approach the patient." in text(r.text)
    pi = sheet(s, f"{s.key}.pi", rs, pid).text
    assert f'data-testid="approach-{pid[:8]}"' in pi and 'data-testid="ref-wait"' not in pi


@step("JP-CRC-05", "TW-CRC-05")
def _crc_irb(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.crc"
    page = s.get(user, f"/studies/{rs}/irb")
    day = s.h.today()
    form = {"approval_no": "IRB-DEMO-0001", "approved_on": (day - timedelta(days=60)).isoformat(),
            "expires_on": (day + timedelta(days=300)).isoformat(), "icf_version": "3.0",
            "icf_date": (day - timedelta(days=30)).isoformat()}  # fmt: skip
    r = s.post(user, f"/studies/{rs}/irb", form, page.text)
    assert r.status_code == 200 and "IRB-DEMO-0001" in text(r.text)
    pi = sheet(s, f"{s.key}.pi", rs, pick(s, rs, 6)).text
    assert 'data-testid="irb-warning"' not in pi


@step("JP-CRC-06", "TW-CRC-06")
def _crc_log(s: Site) -> None:
    rs, user = s.state["trial"], f"{s.key}.crc"
    t = text(s.get(user, f"/studies/{rs}/screening-log").text)
    assert s.state["screening_no"] in t
    r = s.c[user].get(f"/studies/{rs}/screening-log.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml = " ".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
    assert s.state["screening_no"] in xml
    s.state["xlsx_synthetic"] = "synthetic" in xml.lower()


@step("JP-CRC-07")
def _crc_consent(s: Site) -> None:
    rs, user, no = s.state["trial"], f"{s.key}.crc", s.state["screening_no"]
    page = s.get(user, f"/studies/{rs}/subjects/{no}")
    r = s.post(user, f"/studies/{rs}/subjects/{no}/step", {"to": "consented", "on_day": s.h.today().isoformat()},
               page.text)  # fmt: skip
    assert r.status_code == 200, text(r.text)[:400]
    t = text(s.get(user, f"/studies/{rs}/subjects").text)
    assert "Consented 1" in t, t[:400]


@step("JP-CRC-08", "TW-CRC-08")
def _crc_paste_refused(s: Site) -> None:
    user = f"{s.key}.crc"
    page = s.get(user, "/pilot/protocol")
    r = s.post(user, "/pilot/protocol", {"ruleset": s.state["trial"], "criteria": "1. Age 18 or over."}, page.text)
    assert r.status_code == 403 and "Not accepted in the demonstration" in text(r.text), text(r.text)[:300]


@step("JP-CRC-09", "TW-CRC-09")
def _crc_idle(s: Site) -> None:
    user = f"{s.key}.crc"
    s.clock.now += timedelta(minutes=11)  # past the 10-minute idle lock
    assert s.c[user].get("/home").url.path == "/login"
    s.sign_in(user, OWN_PW)
    assert s.c[user].get("/home").url.path == "/home"


# ---------------------------------------------------------------------------------------------------- Taiwan site
@step("TW-PI-03")
def _tw_criteria(s: Site) -> None:
    pid = pick(s, "RA-JAK", 0)
    html = sheet(s, "tw.pi", "RA-JAK", pid).text
    das, hbs, zoster = (row_text(html, f"RA-JAK-{c}") for c in ("INC-04", "EXC-02", "EXC-06"))
    result = re.compile(r"\b(met|not met|present|not present|unknown|a person decides)\b")
    assert result.search(das) and "coded records" in das, das
    assert result.search(hbs) and "coded records" in hbs, hbs
    assert "test model" in zoster and "notes" in zoster and result.search(zoster), zoster
    for row in (das, hbs, zoster):
        if "unknown" in row:  # an unknown says why, and the patient stays on the list
            assert re.search(r"unknown \S", row), row
    assert pid in {str(r["pid"]) for r in rows(s, "RA-JAK")}


@step("TW-PI-08")
def _tw_amend(s: Site) -> None:
    job = s.state["amend_job"]
    assert "Criteria waiting for your approval: GZQO v1.1.0" in text(s.get("tw.pi", "/week").text)
    page = s.get("tw.pi", f"/pilot/jobs/{job}/approval")
    changes = re.search(r'data-testid="changes">(.*?)</section>', page.text, re.S)
    assert changes, text(page.text)[:300]
    box = text(changes.group(1))
    assert "GZQO-INC-03 · new wording" in box and "new criterion" in box, box
    for cid in re.findall(r'data-testid="open-([A-Z0-9-]+)"', page.text):  # every amber line opened
        page = s.get("tw.pi", f"/pilot/jobs/{job}/approval?open={cid}")
    for cid in re.findall(r'data-testid="label-missing-([A-Z0-9-]+)"', page.text):  # the site's label (D-309)
        r = s.post("tw.pi", f"/pilot/jobs/{job}/approval/label", {"crit": cid, "text": f"{cid} label"}, page.text)
        assert r.status_code == 200, text(r.text)[-300:]
        page = s.get("tw.pi", f"/pilot/jobs/{job}/approval")
    r = s.post("tw.pi", f"/pilot/jobs/{job}/approve", {"confirm": "yes"}, page.text)
    assert r.status_code == 200 and "APPROVE GZQO v1.1.0 done" in text(r.text), text(r.text)[:300]
    assert {x.id: x for x in s.h.bk.rulesets()}["GZQO"].version == "1.1.0"
    assert "Criteria waiting for your approval" not in text(s.get("tw.pi", "/week").text)


@step("TW-CRC-07")
def _tw_edc(s: Site) -> None:
    rs, user, no = cd.REGISTRY, "tw.crc", s.state["reg_no"]
    home = s.get(user, f"/studies/{rs}/edc")
    r = s.post(user, f"/studies/{rs}/edc/drafts", {"record": no, "visit_date": s.h.today().isoformat()}, home.text)
    assert r.status_code == 200, text(r.text)[-400:]
    d = {x["item"]: x for x in s.h.bk.study_api("GET", f"/studies/{rs}/edc/drafts?record={no}")}
    drafted = {k: v["value"] for k, v in d.items() if v["state"] == "drafted"}
    assert {"brthdat", "sex"} <= set(drafted)
    rev = s.get(user, f"/studies/{rs}/edc/review/{no}")
    t = text(rev.text)
    assert "Check each value against its source" in t and "hospital record" in t
    assert "Comments comments unknown · not drafted" in t  # no source, no draft: entered by hand (D-398: label first)
    for k in drafted:
        s.post(user, f"/studies/{rs}/edc/decide/{d[k]['id']}", {"action": "confirm", "record": no}, rev.text)
    shown = s.get(user, f"/studies/{rs}/edc/review/{no}").text
    seen = re.search(r'name="seen" value="([^"]*)"', shown)
    form = {"record": no, "password": OWN_PW, "meaning_ack": "1", "seen": seen.group(1) if seen else ""}
    refused = s.post(user, f"/studies/{rs}/edc/sign", form, shown)  # no authenticator code: nothing is signed
    assert refused.status_code == 401 and "Nothing was signed" in text(refused.text), refused.status_code
    signed = s.post(user, f"/studies/{rs}/edc/sign", {**form, "otp": s.code(user)}, shown)
    assert signed.status_code == 200, text(signed.text)[-400:]
    sent = s.post(user, f"/studies/{rs}/edc/send", {"record": no}, signed.text)
    assert sent.status_code == 200 and re.search(r"Sent [1-9]\d*\..*Read-back differences 0", text(sent.text)), text(
        sent.text
    )[:400]
    rb = s.state["rc"].records()[0]
    assert all(rb.get(k) == v for k, v in drafted.items()), (drafted, rb)


# ---------------------------------------------------------------------------------------------------- the walk
ORDER = ("PI", "SI", "CRC")  # session A (PI, then the sub-investigator), session B (the CRC)


def walk(s: Site) -> None:
    ids = task_ids(s.key, "en")
    missing = [i for i in ids if i not in STEPS]
    assert not missing, f"tasks in the script without a step in this test: {missing}"
    extra = sorted(i for i in STEPS if i.startswith(s.key.upper()) and i not in ids)
    assert not extra, f"steps without a task in the script: {extra}"
    for role in ORDER:
        for i in (x for x in ids if x.split("-")[1] == role):
            s.state["_role"] = {"PI": "pi", "SI": "subpi", "CRC": "crc"}[role]
            STEPS[i](s)
            s.walked.append(i)
    assert s.walked == [i for r in ORDER for i in ids if i.split("-")[1] == r]


def test_the_japan_scripts_walk_on_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = build("jp", tmp_path, monkeypatch)
    s.state["trial"] = "AD-MAB"
    walk(s)


def test_the_taiwan_scripts_walk_on_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = build("tw", tmp_path, monkeypatch)
    s.state["trial"] = "RA-JAK"
    walk(s)
