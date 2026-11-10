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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "libs", ROOT / "services"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools import e2e_simple  # noqa: E402
from tools import feas_demo as fd  # noqa: E402

SEEDED = [*(x[0] for x in fd.ACCOUNTS), "subpi"]  # e2e_simple adds the sub-investigator (stage 15)
STATE = "demo-state.json"  # --keep: written once the seed is done; its presence means "reopen, do not rebuild"
ISSUED = "issued-credentials.txt"  # new passwords and enrolment codes for the owner to hand out (mode 0600)
RC_SIM = "rc-sim.json"  # the REDCap simulator's projects, kept across a --keep restart
LANGS = ("ja", "zh-TW", "en")
ROLES = ("admin", "coordinator", "investigator", "viewer", "cro")
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
        out.append(
            Account(
                username=user,
                role=role,
                language=lang,
                name=str(row.get("name") or user)[:120],
                mailbox=str(row.get("mailbox") or f"{user}@hospa.test"),
                affiliation=str(row.get("affiliation") or "hospital"),
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
    clock = ld.Clock(box.today[0])
    clock.now = datetime.fromisoformat(st["clock"])
    sim = sim_app()  # the REDCap simulator of the seed, with the projects it held at the last clean stop
    if (work / RC_SIM).exists():
        sim.state.sim.projects = json.loads((work / RC_SIM).read_text(encoding="utf-8"))
    register_inproc(sim)
    atexit.register(_save_sim, work, sim)
    return box, InprocBackend(box, client, repo), clock


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
        box, h = res["list"]["box"], res["app"].state.helpers
        backend, clock = h.bk, h.users.clock
        if a.keep:
            _save_sim(a.dir, res["sim"])
            atexit.register(_save_sim, a.dir, res["sim"])
            state = {"version": 1, "box_today": box.today[0].isoformat(), "clock": clock().isoformat(),
                     "lang": a.lang, "seeded_at": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
            (a.dir / STATE).write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    url = pglocal.for_work(a.dir)
    users = UserStore(url, clock=clock)
    app = create_app(console_env(a.dir, env, bool(accounts)), backend=backend, audit=AuditLog(box.audit_dir),
                     users=users)  # fmt: skip
    langs = {name: a.lang for name in SEEDED}
    done: dict[str, list[str]] = {"created": [], "logged": [], "enrol": [], "off": []}
    if accounts:
        team = TeamStore(url)
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


def main(argv: list[str] | None = None) -> int:
    from tb_common.config import adopt_site_tz

    adopt_site_tz()  # a synthetic site in one process: its site.tz as TB_TZ (D-315)
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, default=Path(os.environ.get("TB_DEMO_DIR", "/tmp/tb-demo")))
    ap.add_argument("--lang", default=os.environ.get("TB_DEMO_LANG", "ja"), choices=list(LANGS))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--host", default=os.environ.get("TB_DEMO_HOST", "127.0.0.1"))
    ap.add_argument("--no-serve", action="store_true", help="seed and check, then exit")
    ap.add_argument("--fresh", action="store_true", help="accepted for compatibility; a start without --keep is fresh")
    ap.add_argument("--keep", action="store_true", default=os.environ.get("TB_DEMO_KEEP", "") in ("1", "true", "yes"),
                    help="reopen the data of an earlier --keep start (TB_DEMO_KEEP=1); wins over --fresh")  # fmt: skip
    ap.add_argument("--accounts", default=os.environ.get("TB_DEMO_ACCOUNTS") or None,
                    help="the per-tester accounts file (TB_DEMO_ACCOUNTS; JSON, kept outside the image)")  # fmt: skip
    a = ap.parse_args(argv)
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
