"""One-command demo (step 5, D-111): the whole step 1-4 flow on the synthetic hospital, seeded and checked, then the
console stays up for clicking through.

On start it runs exactly what ``e2e_simple`` runs (criteria pasted, FEAS report with funnel, investigator approval on
S20, SCREEN list and GOUT-COH cohort list, three investigator marks and one changed, the N1/N2 morning mail, the
REDCap simulator link with a consented and enrolled patient, the screening log), prints the check list, and serves
the console: role homes (S2/S3/S13), the header command field and the three languages (step 4).

    python -m tools.demo [--lang ja|zh-TW|en] [--port 8080] [--host 0.0.0.0]
    python -m tools.demo --keep --dir /data/demo --accounts /run/secrets/demo-accounts.json   # the PoC (T-505b)
    make demo                                               # same, on 127.0.0.1:8080
    docker build -f demo/Dockerfile -t trialbox-demo . && docker run -p 8080:8080 -e TB_DEMO_PASSWORD=... trialbox-demo

Built-in accounts: admin, crc (coordinator), pi (investigator), subpi (sub-investigator), cra (CRO, aggregate only),
viewer; one password from ``TB_DEMO_PASSWORD`` (else a random one is printed). Stub model, no network, no secrets,
data class D0. Never load real patient data into it.

T-505b, the PoC accounts (ROLE-004, OPS-002, UX-040, FIT-027, LIFE-006):

* ``--accounts FILE`` (or ``TB_DEMO_ACCOUNTS``): a JSON file kept outside the image that names one account per tester
  and role, each with its role, default language, end date and delegation-log entries (``demo/README.md``). Each
  account gets its own password: from the environment variable the entry names (``password_env``), else a random one.
  Both are passwords someone else set, so the first sign-in asks for a new one (D-279). With TOTP on (the default
  with an accounts file; ``TB_CONSOLE_MFA``) each account also gets a one-time enrolment code for its authenticator.
  New passwords and codes go to ``issued-credentials.txt`` in ``--dir`` (owner-only file mode), never to the log. The
  file's accounts are seeded once: a restart never resets a password or adds a log entry twice. The built-in
  accounts, which share one password, are switched off.
* The delegation log of each named study gets the file's entries (PI, sub-investigator with only the tasks ticked in
  the file, CRC), so the sub-investigator is refused Approach (403) and criteria approval (403) where the log has no
  tick or names another PI.
* Each account lands in its own language after sign-in (``language``: ja, zh-TW or en); ``/lang`` changes it.
* ``--keep`` (or ``TB_DEMO_KEEP=1``): the first start seeds and records it in ``demo-state.json``; every later start
  reopens the same data (accounts, marks, delegation log, jobs, audit) instead of rebuilding it. The trial database
  then lives in ``--dir`` too (``TB_PG_DIR`` = ``<dir>/pg``), so a volume mounted there survives the container. Without
  ``--keep`` every start rebuilds the data (the old behaviour; ``--fresh`` is accepted and changes nothing), which is
  also how the owner resets a site: one start without ``--keep``.
* ``TB_CONSOLE_MFA``, ``TB_CONSOLE_IDLE_MINUTES``, ``TB_CONSOLE_SESSION_HOURS``, ``TB_CONSOLE_TOTP_KEY_FILE``,
  ``TB_CONSOLE_TOTP_ISSUER`` and ``TB_CONSOLE_SECURE_COOKIE`` reach the served console from the environment.

T-513, one demo clock (UX-003, D-329): ``--day`` (or ``TB_DEMO_DAY``) is ``today`` by default. The demo day is then
the real day in the site's time zone (on a Saturday or Sunday, the Friday before, the last morning with a digest): the
synthetic hospital's dates are moved so that its data is as of the day before, the seed plays that morning, and then
the console's clock and the box's day follow the real time, also after a ``--keep`` restart. ``--day data`` keeps the
synthetic data's own day (2026-11-02) and a frozen clock, as the tests and drills use it.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import e2e_simple  # noqa: E402
from tools import feas_demo as fd  # noqa: E402

SEEDED = [*(x[0] for x in fd.ACCOUNTS), "subpi", "stw"]  # e2e_simple adds the sub-investigator and steward (15)
STATE = "demo-state.json"  # --keep: written once the seed is done; its presence means "reopen, do not rebuild"
ISSUED = "issued-credentials.txt"  # new passwords and enrolment codes for the owner to hand out (mode 0600)
RC_SIM = "rc-sim.json"  # the REDCap simulator's projects, kept across a --keep restart
OPINIONS = ROOT / "demo" / "fixtures" / "opinions"  # T-515: recorded first and second checks (the G1 slot is here)
LANGS = ("ja", "zh-TW", "en")
ROLES = ("admin", "coordinator", "investigator", "viewer", "cro", "steward", "privacy")  # console.auth.ROLES
SITE_ROLES = ("steward", "privacy")  # DEMO-JA: site-wide (the audit browser, the opt-out register); never on a log
LOG_ROLES = ("pi", "sub_pi", "crc", "other")  # console.teamstore.LOG_ROLES
TASKS = ("screen", "approach", "refer", "enter_data")  # tb_common.authz.STUDY_TASKS
PASSTHROUGH = (
    "TB_CONSOLE_MFA",
    "TB_CONSOLE_IDLE_MINUTES",
    "TB_CONSOLE_SESSION_HOURS",
    "TB_CONSOLE_TOTP_KEY_FILE",
    "TB_CONSOLE_TOTP_ISSUER",
)
SEED_ACTOR = "demo:seed"
_NAME_OK = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
_STUDY_OK = re.compile(r"[A-Z0-9][A-Z0-9_-]{0,31}")


class AccountsError(ValueError):
    """The accounts file is not usable; the message names the entry (never a password)."""


@dataclass(frozen=True)
class LogEntry:
    study: str
    role: str
    tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Account:
    username: str
    role: str
    language: str = "en"
    name: str = ""
    mailbox: str = ""
    affiliation: str = "hospital"
    studies: tuple[str, ...] = ()
    expires: str | None = None
    password_env: str = ""
    delegation: tuple[LogEntry, ...] = field(default_factory=tuple)

    @property
    def scope(self) -> str:
        """The account's study scope (D-104): the file's ``studies``, else the studies its log entries name."""
        return ",".join(self.studies or tuple(dict.fromkeys(e.study for e in self.delegation)))


def parse_accounts(data: Any) -> list[Account]:
    """Check and read the accounts file's JSON (``{"accounts": [...]}`` or the list itself)."""
    rows = data.get("accounts") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise AccountsError('the accounts file needs a non-empty list "accounts"')
    out: list[Account] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise AccountsError(f"entry {i} is not an object")
        if "password" in row:
            raise AccountsError(f"entry {i}: no passwords in the file; name an environment variable in password_env")
        user = str(row.get("username") or "").strip().lower()
        where = f"entry {i} ({user or 'no username'})"
        if not _NAME_OK.fullmatch(user):
            raise AccountsError(f"{where}: username must be 2 to 64 of a-z 0-9 . _ -")
        if user in seen:
            raise AccountsError(f"{where}: the username is listed twice")
        seen.add(user)
        role = str(row.get("role") or "")
        if role not in ROLES:
            raise AccountsError(f"{where}: role must be one of {', '.join(ROLES)}")
        lang = str(row.get("language") or "en")
        if lang not in LANGS:
            raise AccountsError(f"{where}: language must be one of {', '.join(LANGS)}")
        expires = str(row.get("expires") or "").strip() or None
        if expires is not None:
            try:
                date.fromisoformat(expires)
            except ValueError as exc:
                raise AccountsError(f"{where}: expires must be YYYY-MM-DD") from exc
        env_name = str(row.get("password_env") or "").strip()
        if env_name and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", env_name):
            raise AccountsError(f"{where}: password_env must be an environment variable name")
        log: list[LogEntry] = []
        for e in row.get("delegation") or []:
            study = str(e.get("study") or "").strip().upper()
            lrole = str(e.get("role") or "")
            tasks = tuple(str(t) for t in e.get("tasks") or [])
            if not _STUDY_OK.fullmatch(study):
                raise AccountsError(f"{where}: a delegation entry needs a study id")
            if lrole not in LOG_ROLES:
                raise AccountsError(f"{where}: delegation role must be one of {', '.join(LOG_ROLES)}")
            if lrole in ("pi", "sub_pi") and role != "investigator":
                raise AccountsError(f"{where}: only an investigator account is a PI or sub-investigator on the log")
            if lrole == "pi" and tasks:
                raise AccountsError(f"{where}: the PI holds every task; list tasks only for the others")
            bad = [t for t in tasks if t not in TASKS]
            if bad:
                raise AccountsError(f"{where}: unknown task {bad[0]!r} (one of {', '.join(TASKS)})")
            log.append(LogEntry(study, lrole, tasks))
        studies = tuple(str(s).strip().upper() for s in row.get("studies") or [])
        if any(not _STUDY_OK.fullmatch(s) for s in studies):
            raise AccountsError(f"{where}: studies are study ids")
        if role in SITE_ROLES and (log or studies):
            raise AccountsError(f"{where}: a {role} account is site-wide: no delegation entries or studies")
        affiliation = str(row.get("affiliation") or "hospital")
        if (role == "cro" or affiliation in ("smo", "cro")) and not studies and not log:
            raise AccountsError(f"{where}: a CRO or SMO account names its studies (D-380)")
        out.append(
            Account(
                username=user,
                role=role,
                language=lang,
                name=str(row.get("name") or user)[:120],
                mailbox=str(row.get("mailbox") or f"{user}@hospa.test"),
                affiliation=affiliation,
                studies=studies,
                expires=expires,
                password_env=env_name,
                delegation=tuple(log),
            )
        )
    pis: dict[str, str] = {}
    for a in out:
        for e in a.delegation:
            if e.role == "pi" and pis.setdefault(e.study, a.username) != a.username:
                raise AccountsError(f"study {e.study} has two PIs in the file ({pis[e.study]}, {a.username})")
    return out


def load_accounts(path: Path) -> list[Account]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AccountsError(f"cannot read the accounts file {path}: {exc.__class__.__name__}") from exc
    return parse_accounts(data)


def _issue(path: Path, lines: list[str]) -> None:
    """Append to the owner's hand-out file, created owner-read-only."""
    fd_ = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd_, "a", encoding="utf-8") as fh:
        fh.write("".join(f"{ln}\n" for ln in lines))
    os.chmod(path, 0o600)


def seed_accounts(
    users: Any,
    team: Any,
    accounts: list[Account],
    *,
    today: date,
    now: str,
    totp: bool,
    issued: Path,
    environ: Mapping[str, str] | None = None,
    known_studies: set[str] | None = None,
    audit: Any = None,
) -> dict[str, list[str]]:
    """Create the file's accounts that do not exist yet, add their delegation-log entries that are not there yet,
    and give each account still without an authenticator a live enrolment code. Idempotent: an existing account's
    password, scope and log entries are never touched again. Returns what was done, by kind (user names only)."""
    env = os.environ if environ is None else environ
    if known_studies is not None:
        unknown = sorted({e.study for a in accounts for e in a.delegation} - known_studies)
        if unknown:
            have = ", ".join(sorted(known_studies))
            raise AccountsError(f"the demo has no study {', '.join(unknown)} (it has {have})")
    existing = {u.username for u in users.users()} | {u.username for u in users.disabled_users()}
    done: dict[str, list[str]] = {"created": [], "logged": [], "enrol": []}
    lines: list[str] = []
    for a in accounts:
        if a.username not in existing:
            password = env.get(a.password_env, "") if a.password_env else ""
            given = bool(password)
            if not given:
                from console.auth import random_password

                password = random_password()
            users.create(a.username, a.role, password, a.mailbox, must_change=True)  # D-279: changed at first sign-in
            users.set_scope(a.username, a.affiliation, a.scope, a.expires)
            done["created"].append(a.username)
            shown = f"from ${a.password_env}" if given else password
            lines.append(f"{now}\t{a.username}\tpassword\t{shown}")
            if audit is not None:
                audit.append("console.user", actor=SEED_ACTOR, detail={"action": "create", "user": a.username,
                                                                       "role": a.role})  # fmt: skip
        for e in a.delegation:
            if any(x.username == a.username and x.role == e.role for x in team.entries(e.study)):
                continue
            team.add_entry(e.study, username=a.username, name=a.name, role=e.role, tasks=list(e.tasks),
                           start=today.isoformat(), end=a.expires, training_day=today.isoformat(),
                           training_ref="demo seed (synthetic)", by=SEED_ACTOR, at=now)  # fmt: skip
            done["logged"].append(f"{a.username}@{e.study}")
            if audit is not None:
                detail = {"action": "add", "user": a.username, "role": e.role, "tasks": list(e.tasks)}
                audit.append("console.delegation", actor=SEED_ACTOR, ruleset=e.study, detail=detail)
        if totp and users.get(a.username) is not None and users.totp_state(a.username)[0] is None:
            live, _why = users.enrol_state(a.username)
            if not live:
                code = users.issue_enrol_code(a.username)
                done["enrol"].append(a.username)
                lines.append(f"{now}\t{a.username}\tenrolment code\t{code}")
    if lines:
        _issue(issued, lines)
    return done


IRB_STUDY = "GZQO"  # T-516 (UX-014): the trial whose IRB approval and consent-form version the demo seeds


def seed_irb(team: Any, study: str, today: date, now: str) -> bool:
    """T-516 (UX-014, D-385): two values for the demo trial: the IRB approval date (60 days ago) and the current
    consent-form version, so a tester's Approach is not an override every time. Only when the study has neither (a
    record a tester saved is never touched); the cohort study keeps none, so the warning can still be shown on purpose.
    Synthetic values. Returns True when it seeded."""
    from console.teamstore import Irb

    have = team.irb(study)
    if have.approved_on or have.icf_version:
        return False
    team.save_irb(study, Irb(approved_on=(today - timedelta(days=60)).isoformat(), icf_version="1.0"), SEED_ACTOR, now)
    return True


def switch_off_builtin(users: Any, keep: set[str]) -> list[str]:
    """With an accounts file, the built-in accounts (one shared password) are switched off after the seed."""
    off = [u.username for u in users.users() if u.username in SEEDED and u.username not in keep]
    for name in off:
        users.disable(name)
    return off


class DefaultLanguage:
    """ASGI wrapper (T-505b, UX-040): a session opened for an account with a default language starts in it. It reads
    the new session cookie of a sign-in response and sets that session's language; ``/lang`` still changes it."""

    def __init__(self, app: Any, users: Any, langs: Mapping[str, str], cookie: str = "tb_console") -> None:
        self.app, self.users, self.langs = app, users, dict(langs)
        self.cookie = cookie.encode() + b"="

    @property
    def state(self) -> Any:
        return self.app.state

    def apply(self, token: str) -> None:
        sess = self.users.session(token, touch=False)
        if sess is None:
            return
        lang = self.langs.get(sess.user.username)
        if lang in LANGS and sess.lang != lang:
            self.users.set_lang(sess, lang)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_lang(msg: Any) -> None:
            if msg.get("type") == "http.response.start":
                for k, v in msg.get("headers") or []:
                    if k.lower() == b"set-cookie" and v.startswith(self.cookie):
                        token = v[len(self.cookie) :].split(b";", 1)[0].decode("latin-1").strip('"')
                        if token:
                            import anyio.to_thread

                            await anyio.to_thread.run_sync(self.apply, token)
            await send(msg)

        await self.app(scope, receive, send_with_lang)


@contextlib.contextmanager
def https_seeding() -> Iterator[None]:
    """T-501 (ROLE-002, OPS-007): seed over ``https://testserver``. The image sets ``TB_CONSOLE_SECURE_COOKIE=1``; the
    seeding clients of e2e_simple are in-process ``TestClient``s, which send a Secure cookie back only over https."""
    from fastapi.testclient import TestClient

    init = TestClient.__init__

    def https_init(self: TestClient, app: Any, base_url: str = "https://testserver", *args: Any, **kw: Any) -> None:
        init(self, app, base_url, *args, **kw)

    TestClient.__init__ = https_init  # type: ignore[method-assign]
    try:
        yield
    finally:
        TestClient.__init__ = init  # type: ignore[method-assign]


def mark_temp_root() -> None:
    """T-501 (OPS-077): the cluster for_work starts lives under ``TB_TEST_ROOT`` when one is set; mark that root, so
    the next run with the same root is not refused as a folder of other files."""
    if os.environ.get("TB_TEST_ROOT") and not os.environ.get("TB_DB_URL") and not os.environ.get("TB_PG_DIR"):
        from tools import pglocal

        pglocal.mark_test_root(Path(os.environ["TB_TEST_ROOT"]))


def prepare_dir(work: Path, keep: bool) -> bool:
    """Make ``work`` ready; True when ``--keep`` finds a finished seed there to reopen. A fresh start (or a keep
    start that finds no finished seed) deletes the folder, after stopping a trial database that runs inside it."""
    if keep:
        os.environ.setdefault("TB_PG_DIR", str(work / "pg"))  # the trial database survives with the folder
        if (work / STATE).exists():
            return True
    if work.exists():
        from tools import pglocal

        pglocal.stop(work / "pg")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    return False


def console_env(work: Path, environ: Mapping[str, str], accounts: bool) -> dict[str, str]:
    """The served console's settings: the demo's own, plus the identity settings from the environment (ROLE-004).
    TOTP is on by default when the testers have their own accounts."""
    env = {
        "TB_ENV": "DEV",
        "TB_CONSOLE_PILOT": "1",
        "TB_DATA_CLASS": "D0",
        "TB_CONSOLE_DIR": str(work / "console"),
        "TB_CONSOLE_ADMIN_EMAIL": "admin@hospa.test",
        "TB_CONSOLE_SECURE_COOKIE": environ.get("TB_CONSOLE_SECURE_COOKIE", "0"),
        # T-515 (D-323): first and second checks on the demo pages, each marked synthetic or recorded
        "TB_DEMO_OPINIONS": environ.get("TB_DEMO_OPINIONS") or str(OPINIONS),
    }
    env.update({k: environ[k] for k in PASSTHROUGH if environ.get(k)})
    if accounts:
        env.setdefault("TB_CONSOLE_MFA", "totp")
    return env


def _save_sim(work: Path, sim: Any) -> None:
    with contextlib.suppress(Exception):
        (work / RC_SIM).write_text(json.dumps(sim.state.sim.projects, ensure_ascii=False), encoding="utf-8")


def _reopen(work: Path) -> tuple[Any, Any, Callable[[], datetime]]:
    """A kept demo: the box, its backend and the console clock as the seed left them."""
    from rc_sim.app import create_app as sim_app
    from rc_sim.app import register_inproc

    from tools import list_demo as ld
    from tools import pglocal
    from tools.role_demo import InprocBackend

    st = json.loads((work / STATE).read_text(encoding="utf-8"))
    pglocal.for_work(work)  # the seed's schemas: named after --dir (its first for_work), not after the box folder
    box, client, repo = fd.reopen_site(work)
    box.today[0] = date.fromisoformat(st["box_today"])
    clock = ld.Clock(box.today[0], ld.site_tz_of(box))
    clock.now = datetime.fromisoformat(st["clock"])
    if st.get("live"):  # T-513: a demo seeded on the real day goes on with the real day after a restart
        ld.go_live(box, clock)
    sim = sim_app()  # the REDCap simulator of the seed, with the projects it held at the last clean stop
    if (work / RC_SIM).exists():
        sim.state.sim.projects = json.loads((work / RC_SIM).read_text(encoding="utf-8"))
    register_inproc(sim)
    atexit.register(_save_sim, work, sim)
    return box, InprocBackend(box, client, repo), clock


def case_chart(lang: str, today: date) -> str:
    """DEMO-SEED (D-757, D-758): the synthetic chart of the seed's one "Check one patient" (CASE) job, made up (no
    person's record), dated from the demo day, in the seed's language, written the way the box's readers read a
    chart: a visit with BMI 31.4 and HbA1c 7.6 % ten days ago, and two dated gout flares within the year (zh-TW and
    ja; the stub reads no English flare). Demo mode refuses an upload by design (D-328): it is made before."""
    from tools.synth.notes import roc

    visit, flare1, flare2 = today - timedelta(days=10), today - timedelta(days=60), today - timedelta(days=200)
    if lang == "zh-TW":
        return (
            f"{roc(visit)}門診紀錄。BMI 31.4 kg/m2。HbA1c 7.6%。第二型糖尿病，服用metformin。\n"
            f"病人於{roc(flare1)}右側第一蹠趾關節紅腫熱痛，臨床診斷為急性痛風發作，給予秋水仙素治療後緩解。\n"
            f"病人於{roc(flare2)}左膝紅腫熱痛，臨床診斷為急性痛風發作，給予秋水仙素治療後緩解。\n"
            f"{roc(visit)}目前無急性痛風發作，關節檢查無紅腫或壓痛。血壓 138/84 mmHg。未懷孕。\n"
        )
    if lang == "ja":
        return (
            f"{roc(visit)}外来。BMI 31.4 kg/m2。HbA1c 7.6%。2型糖尿病でメトホルミン内服中。\n"
            f"{roc(flare1)}に右第一中足趾節関節の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。\n"
            f"{roc(flare2)}に左膝の発赤・腫脹・熱感・疼痛あり、急性痛風発作と診断しコルヒチンで改善した。\n"
            f"{roc(visit)}現在、急性痛風発作はなく、関節の発赤・圧痛は認めない。血圧 138/84 mmHg。妊娠なし。\n"
        )
    return (
        f"Clinic visit {visit.isoformat()}. BMI 31.4 kg/m2. HbA1c 7.6%. Type 2 diabetes on metformin.\n"
        f"Acute gout flare of the right first toe on {flare1.isoformat()}, treated with colchicine.\n"
        f"Acute gout flare of the left knee on {flare2.isoformat()}, treated with colchicine.\n"
        f"Visit {visit.isoformat()}: no current flare. Blood pressure 138/84 mmHg. Not pregnant.\n"
    )


def seed_case(pi: Any, box: Any, lang: str, ruleset: str = "GZQO") -> str | None:
    """DEMO-SEED (D-757): one CASE job on a synthetic chart, asked by the investigator through the console's own
    route as a user would, before demo mode is switched on; run to its end, so "Check one patient" has a sheet to
    show. The job's id, or None when the console refused it."""
    from tools import feas_demo as fd

    page = pi.get("/pilot/case")
    if page.status_code != 200:
        return None
    chart = case_chart(lang, box.orch.today())
    r = pi.post(
        "/pilot/case",
        data={"csrf": fd._csrf(page.text), "ruleset": ruleset, "lang": lang},
        files=[("charts", ("synthetic-chart.txt", chart.encode("utf-8"), "text/plain"))],
        follow_redirects=False,
    )
    if r.status_code != 303:
        return None
    job_id = str(r.headers["location"]).rstrip("/").rsplit("/", 1)[-1]
    box.orch.drain()
    job = box.orch.db.get(job_id)
    return job_id if job is not None and job.state == "done" else None


def start(a: argparse.Namespace, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Seed (or reopen with ``--keep``), seed the accounts file, and build the console to serve."""
    from console.app import COOKIE, create_app
    from console.auth import UserStore
    from console.teamstore import TeamStore
    from tb_common.audit import AuditLog

    from tools import pglocal

    env = os.environ if environ is None else environ
    accounts = load_accounts(Path(a.accounts)) if a.accounts else []
    kept = prepare_dir(a.dir, a.keep)
    password = env.get("TB_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    mark_temp_root()
    out: dict[str, Any] = {"kept": kept, "ok": True, "report": ""}
    if kept:
        box, backend, clock = _reopen(a.dir)
    else:
        with https_seeding():
            seeded = e2e_simple.run(a.dir, password, a.lang)
        out["ok"], out["report"] = seeded["ok"], e2e_simple.report(seeded)
        res = seeded["result"]
        out["case"] = seed_case(res["list"]["pi"], res["list"]["box"], a.lang)
        if out["case"] is None:  # the seed is not whole without the sheet "Check one patient" shows
            out["ok"] = False
            out["report"] += "\nFAIL the seeded CASE job (Check one patient) did not end done"
        box, h = res["list"]["box"], res["app"].state.helpers
        backend, clock = h.bk, h.users.clock
        live = bool(res["list"].get("live"))
        out["day"] = res["list"]["day"]
        if a.keep:
            _save_sim(a.dir, res["sim"])
            atexit.register(_save_sim, a.dir, res["sim"])
            state = {"version": 1, "box_today": box.today[0].isoformat(), "clock": clock().isoformat(),
                     "lang": a.lang, "seeded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                     "live": live}  # fmt: skip
            (a.dir / STATE).write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
        if live:  # T-513: the seed played this morning; from now on the console and the box follow the real clock
            from tools import list_demo as ld

            ld.go_live(box, clock)
    url = pglocal.for_work(a.dir)
    users = UserStore(url, clock=clock)
    app = create_app(console_env(a.dir, env, bool(accounts)), backend=backend, audit=AuditLog(box.audit_dir),
                     users=users)  # fmt: skip
    langs = {name: a.lang for name in SEEDED}
    done: dict[str, list[str]] = {"created": [], "logged": [], "enrol": [], "off": [], "irb": []}
    team = TeamStore(url)
    studies = {r.id.upper() for r in backend.rulesets()}
    if not kept and IRB_STUDY in studies and seed_irb(team, IRB_STUDY, users.today(), clock().isoformat()):
        done["irb"].append(IRB_STUDY)  # after the seed's own checks, which show the warning
        AuditLog(box.audit_dir).append("console.irb", actor=SEED_ACTOR, ruleset=IRB_STUDY,
                                       detail={"action": "seed", "fields": "approved_on,icf_version"})  # fmt: skip
    if accounts:
        totp_on = app.state.identity.settings.totp_required
        known = {r.id.upper() for r in backend.rulesets()}
        done.update(seed_accounts(users, team, accounts, today=users.today(), now=clock().isoformat(), totp=totp_on,
                                  issued=a.dir / ISSUED, environ=env, known_studies=known,
                                  audit=AuditLog(box.audit_dir)))  # fmt: skip
        done["off"] = switch_off_builtin(users, {x.username for x in accounts})
        langs = {x.username: x.language for x in accounts}
    elif kept:  # the built-in accounts take this start's password (the one printed, or TB_DEMO_PASSWORD)
        for name in SEEDED:
            if users.get(name) is not None:
                users.set_password(name, password)
    out.update(app=DefaultLanguage(app, users, langs, COOKIE), users=users, box=box, password=password,
               accounts=accounts, done=done, names=[x.username for x in accounts] or SEEDED)  # fmt: skip
    return out


#: H-25 (D-1124): the parts of the orchestrator's start-up (``services/orchestrator/app.py``, ``lifespan``) and what a
#: demo or steps-mode box does with each. Only the opt-out worker runs here: a tester sees an erase complete, and the
#: health check ``optout_worker`` is green. The others stay off by name: the job workers (the box runs its jobs in
#: process), the model pair canary (off on a demo box), the night's clocks and the site-publish batch tick (they would
#: ingest again and move the synthetic data at night). A test holds this table against the lifespan's own code.
START_UP = {
    "workers": "off",
    "canary": "off",
    "scheduler": "off",
    "site_publish_batch": "off",
    "optout_worker": "on",
}
#: the worker's interval on a demo box unless one is set: a minute, so an opt-out is erased while the tester waits
OPTOUT_MINUTES = "1"


def start_up(orch: Any, environ: Any = None) -> Callable[[], None]:
    """H-25 (D-1124): run the parts of the orchestrator's start-up that :data:`START_UP` turns on, for the box the
    console serves; returns the stop. The worker is the orchestrator's own (``datacore.optout_worker.start``, D-441):
    its first tick at once, then every ``TB_OPTOUT_WORKER_MINUTES`` (here a minute unless set)."""
    from datacore import optout_worker

    env = os.environ if environ is None else environ
    env.setdefault(optout_worker.MINUTES_ENV, OPTOUT_MINUTES)
    sched = optout_worker.start(orch, production=False) if START_UP["optout_worker"] == "on" else None

    def stop() -> None:
        if sched is not None:
            sched.shutdown(wait=False)

    atexit.register(stop)
    return stop


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import adopt_site_tz

    adopt_site_tz()  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    from tools.pglocal import scratch_root  # D-201: never a fixed /tmp path

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR") or scratch_root() / "tb-demo"))
    ap.add_argument("--lang", default=os.environ.get("TB_DEMO_LANG", "ja"), choices=list(LANGS))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--no-serve", action="store_true", help="seed and check, then exit")
    ap.add_argument("--fresh", action="store_true", help="accepted for compatibility; a start without --keep is fresh")
    ap.add_argument("--keep", action="store_true", default=os.environ.get("TB_DEMO_KEEP", "") in ("1", "true", "yes"),
                    help="reopen the data of an earlier --keep start (TB_DEMO_KEEP=1); wins over --fresh")  # fmt: skip
    ap.add_argument("--accounts", default=os.environ.get("TB_DEMO_ACCOUNTS") or None,
                    help="the per-tester accounts file (TB_DEMO_ACCOUNTS; JSON, kept outside the image)")  # fmt: skip
    ap.add_argument("--day", default=os.environ.get("TB_DEMO_DAY") or "today",
                    help="the demo day (T-513, TB_DEMO_DAY): today (the default: the real day in the site's zone, "
                         "the synthetic dates moved to it), data (the data's own day) or YYYY-MM-DD")  # fmt: skip
    a = ap.parse_args(argv)
    os.environ["TB_DEMO_DAY"] = a.day
    os.environ.setdefault("TB_ENV", "DEV")
    logging.disable(logging.INFO)
    try:
        out = start(a)
    except AccountsError as exc:
        print(f"demo accounts: {exc}", file=sys.stderr)
        return 2
    if out["kept"]:
        print(f"kept demo reopened from {a.dir} (no rebuild)")
    else:
        print(out["report"])
        print(f"demo day {out['day']} (TB_DEMO_DAY={a.day})")
    done = out["done"]
    if out["accounts"]:
        off = ", ".join(done["off"]) or "-"
        print(f"accounts file: {len(done['created'])} new, {len(done['logged'])} new log entries, "
              f"{len(done['enrol'])} enrolment codes; built-in accounts switched off: {off}")  # fmt: skip
        if done["created"] or done["enrol"]:
            print(f"new passwords and enrolment codes: {a.dir / ISSUED} (owner only; hand out, then delete)")
    if a.no_serve:
        return 0 if out["ok"] else 1
    import uvicorn

    start_up(out["box"].orch)  # H-25 (D-1124): after the seed and its checks, before the console serves
    logging.disable(logging.NOTSET)
    print(f"\nconsole on http://{a.host}:{a.port}/home  accounts: {', '.join(out['names'])}")
    if not out["accounts"] and not os.environ.get("TB_DEMO_PASSWORD"):
        print(f"password (all accounts): {out['password']}")
    uvicorn.run(out["app"], host=a.host, port=a.port, log_level="warning")
    if a.keep and os.environ.get("TB_PG_DIR") == str(a.dir / "pg"):
        from tools import pglocal

        pglocal.stop(a.dir / "pg")  # a clean stop of the kept trial database
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
