"""The live half of the failure drill (card H-31, D-1109): the compose test stack, the night's work on it, the kills
and the readers of the product's records. The logic, the checks and the report are in :mod:`tools.failure_drill`;
read its opening text first. Needs Docker, ``make images`` and the host ports of ``tests/stack.py``.

Each target: a fresh stack (``down -v``, ``up --wait``), yesterday's ingest (``tests.stack.ensure_ingested``), then
the night: the mailed FEAS and SCREEN per study, the timer's INGEST (``schedule.ingest`` set two minutes ahead and the
orchestrator restarted to read it, before the night starts) and its chain, the morning notices. The kill happens in
the target's stage, when its condition holds (``Target.when``). The control night is the same night with no kill
(``<out>/control.json``), made once per run directory.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import smtplib
import subprocess
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from tools.failure_drill import (
    FINISH_S,
    FULL_FOR_S,
    RECOVER_S,
    STUDIES,
    TERMINAL,
    WAITS,
    Record,
    Target,
    check_audit,
    check_jobs,
    check_mail,
    render,
)

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / ".cache" / "drill-settings.yaml"
DISK_OVERRIDE = ROOT / ".cache" / "drill-disk.yml"
AUTH = "mx.hospa.test; spf=pass smtp.mailfrom=hospa.test; dkim=pass header.d=hospa.test; dmarc=pass"
SENDER = "crc1@hospa.test"
RUNNING = ("parsing", "compiling", "running", "reporting")


def log(msg: str) -> None:
    print(f"[drill {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd: Sequence[str], timeout: float = 900, check: bool = False, env: dict[str, str] | None = None) -> str:
    res = subprocess.run(
        list(cmd), cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False,
        env={**os.environ, **(env or {})},
    )  # fmt: skip
    if check and res.returncode != 0:
        raise RuntimeError(f"{shlex.join(cmd)} exited {res.returncode}: {(res.stderr or res.stdout).strip()[-800:]}")
    return res.stdout


#: H-139: the Makefile's TEST_PROJECT, the test stack's own compose project
TEST_PROJECT = "trialbox-test"


def compose(*args: str, disk: bool = False) -> list[str]:
    """The test stack's compose command as the Makefile's ``COMPOSE_TEST`` builds it, with the drill's settings."""
    files = ["-f", "deploy/docker-compose.yml", "-f", "deploy/docker-compose.test.yml"]
    if disk and DISK_OVERRIDE.exists():
        files += ["-f", str(DISK_OVERRIDE)]
    return ["docker", "compose", "--project-directory", "deploy", "-p", TEST_PROJECT, *files, "--profile", "stub",
            "--profile", "test", *args]  # fmt: skip


def compose_env() -> dict[str, str]:
    # the test file's object folder defaults to ${PWD}/deploy/.objects, as `make up-test` binds it
    return {"PWD": str(ROOT), "TB_SETTINGS_FILE": str(SETTINGS)}


def dc(*args: str, disk: bool = False, timeout: float = 900, check: bool = False) -> str:
    return sh(compose(*args, disk=disk), timeout=timeout, check=check, env=compose_env())


# ------------------------------------------------------------------------------------------------ the settings
def write_settings(ingest_at: str = "02:00") -> None:
    """The test stack's settings (``make`` ``$(TEST_SETTINGS)``) with the ingest's clock time set: written in place
    so the read-only bind mount sees it."""
    base = (ROOT / "deploy" / "settings.example.yaml").read_text(encoding="utf-8")
    out = []
    for line in base.splitlines():
        if line.startswith("rate_limit_per_sender_per_day:"):
            line = "rate_limit_per_sender_per_day: 1000"
        if line.startswith("schedule:"):
            line = line.replace('ingest: "02:00"', f'ingest: "{ingest_at}"')
        out.append(line)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out) + "\n"
    if SETTINGS.exists():
        with SETTINGS.open("r+", encoding="utf-8") as f:  # the same inode: the container's bind mount sees it
            f.seek(0)
            f.write(text)
            f.truncate()
    else:
        SETTINGS.write_text(text, encoding="utf-8")


DISK_IMAGE = Path.home() / ".cache" / "tb-drill-disk.img"
DISK_MOUNT = Path.home() / ".cache" / "tb-drill-pg"


def write_disk_override(size_mb: int) -> str:
    """The database's data volume, small, for the disk target only. A loop-mounted ext4 file of ``size_mb`` bound as
    the volume (needs root on the host: ``mount``); else a size-capped tmpfs, which does not survive a restart of
    its container (a database that restarts after the disk filled comes back empty: the drill's medium, not the
    product). Returns what was used."""
    release_disk()
    DISK_MOUNT.mkdir(parents=True, exist_ok=True)
    img, pg = str(DISK_IMAGE), str(DISK_MOUNT / "pg")  # a subfolder: initdb refuses ext4's lost+found
    steps = (
        ["truncate", "-s", f"{size_mb}M", img],
        ["mkfs.ext4", "-q", "-F", img],
        ["mount", "-o", "loop", img, str(DISK_MOUNT)],
        ["mkdir", pg],
        ["chown", "999:999", pg],
        ["chmod", "700", pg],
    )
    made = subprocess.CompletedProcess([], 0, "", "")
    for step in steps:
        made = subprocess.run(step, capture_output=True, text=True, check=False)
        if made.returncode != 0:
            break
    if made.returncode == 0:
        opts = f'{{type: none, o: bind, device: "{DISK_MOUNT / "pg"}"}}'
        used = f"a {size_mb} MB ext4 file, loop-mounted on the host and bound as the volume"
    else:
        opts = f'{{type: tmpfs, device: tmpfs, o: "size={size_mb}m,uid=999,gid=999,mode=0700"}}'
        used = f"a {size_mb} MB tmpfs (no loop mount here: {made.stderr.strip()[-120:]})"
    DISK_OVERRIDE.write_text(f"volumes:\n  db-pg:\n    driver: local\n    driver_opts: {opts}\n", encoding="utf-8")
    return used


def release_disk() -> None:
    """Unmount and remove the disk target's loop file (nothing when there is none)."""
    if DISK_MOUNT.is_mount():
        subprocess.run(["umount", str(DISK_MOUNT)], capture_output=True, check=False)
    DISK_IMAGE.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------------ the stack
def site_tz() -> ZoneInfo:
    from tb_common.config import _read_dotenv

    zone = os.environ.get("TB_TZ") or _read_dotenv(ROOT / "deploy" / ".env").get("TB_TZ")
    if not zone:  # the site's zone is a setting (D-315), never a default in code
        raise RuntimeError("TB_TZ is not set (the environment or deploy/.env): the timer's clock time needs it")
    return ZoneInfo(zone)


def fresh_stack(disk: bool) -> None:
    dc("down", "-v", "--remove-orphans", disk=True, timeout=600)
    if not disk:
        release_disk()
        DISK_OVERRIDE.unlink(missing_ok=True)
    shutil.rmtree(ROOT / "deploy" / ".objects", ignore_errors=True)  # the test stack's bind-mounted object folder
    write_settings((datetime.now(site_tz()) + timedelta(seconds=INGEST_AFTER_S)).strftime("%H:%M"))
    sh(["make", "--no-print-directory", "deploy/.env", ".cache/test-secrets/site_hmac.key", "objects-dir",
        f"OBJECTS_DIR={ROOT / 'deploy' / '.objects'}"], check=True)  # fmt: skip
    dc("up", "-d", "--wait", disk=disk, timeout=1500, check=True)


def container(service: str) -> str:
    return dc("ps", "-q", service).strip()


def health(service: str) -> str:
    cid = container(service)
    if not cid:
        return "absent"
    fmt = "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}}"
    return sh(["docker", "inspect", "-f", fmt, cid]).strip()


def kill9(service: str) -> str:
    """``kill -9`` of the container's first process from the host: the container exits as on a crash, and Docker's
    restart policy applies (``docker kill`` would count as a person's stop)."""
    cid = container(service)
    pid = sh(["docker", "inspect", "-f", "{{.State.Pid}}", cid], check=True).strip()
    sh(["kill", "-9", pid], check=True)
    return f"kill -9 of pid {pid} on the host: the first process (init) of container {service} ({cid[:12]})"


def wait_healthy(services: Sequence[str], since: float, limit: float) -> float | None:
    """Seconds from ``since`` until every service is running and healthy (or has no health check), else None."""
    time.sleep(3)
    while time.monotonic() - since < limit:
        states = [health(s).split() for s in services]
        if all(len(st) >= 2 and st[0] == "running" and st[1] in ("healthy", "none") for st in states):
            return time.monotonic() - since
        time.sleep(3)
    return None


def services() -> list[str]:
    return [s for s in dc("ps", "--services", "--status", "running").split() if s]


# ------------------------------------------------------------------------------------------------ the readers
def _stack() -> Any:
    import tests.stack as stack

    return stack


def jobs() -> list[dict[str, Any]]:
    from tb_common.service_auth import auth_headers

    r = httpx.get(_stack().url("ORCH", "/jobs"), params={"limit": 1000}, headers=auth_headers(), timeout=30)
    r.raise_for_status()
    out: list[dict[str, Any]] = r.json()
    return out


def jobs_or_none() -> list[dict[str, Any]] | None:
    try:
        return jobs()
    except (httpx.HTTPError, ValueError):
        return None


def mails() -> list[dict[str, Any]]:
    try:
        msgs = _stack().outbound_mail(limit=1000)
    except (httpx.HTTPError, ValueError):
        return []
    return [
        {"to": sorted(a for _, a in getaddresses(m.get_all("To", []) + m.get_all("Cc", []))),
         "subject": str(m["Subject"] or ""), "message_id": str(m["Message-ID"] or "")}
        for m in msgs
    ]  # fmt: skip


def psql(sql: str) -> str:
    cmd = f'psql -U "$POSTGRES_USER" -d trialbox_wf -Atc {shlex.quote(sql)}'
    return dc("exec", "-T", "db", "sh", "-c", cmd, timeout=60)


def outbox() -> list[dict[str, Any]]:
    rows = psql("SELECT key, state, coalesce(job_id, '') FROM mail.send_keys ORDER BY at").splitlines()
    return [dict(zip(("key", "state", "job_id"), r.split("|"), strict=False)) for r in rows if r]


CHAIN_READER = r"""
import glob, json, sys
seqs, n = [], 0
for p in sorted(glob.glob('/data/audit/*.jsonl')):
    for line in open(p, 'rb'):
        n += 1
        try:
            j = json.loads(line).get('journal')
        except ValueError:
            continue
        if isinstance(j, dict) and 'seq' in j:
            seqs.append(int(j['seq']))
print(json.dumps({'lines': n, 'seqs': seqs}))
"""


def chain() -> dict[str, Any]:
    out = dc("exec", "-T", "orchestrator", "python", "-c", CHAIN_READER, timeout=120)
    try:
        body: dict[str, Any] = json.loads(out.strip().splitlines()[-1])
        return body
    except (ValueError, IndexError):
        return {"lines": 0, "seqs": []}


def journal_seqs() -> list[int]:
    return [int(x) for x in psql("SELECT seq FROM audit.journal ORDER BY seq").split() if x.strip().isdigit()]


def verify() -> tuple[int, str]:
    res = subprocess.run(
        compose("exec", "-T", "orchestrator", "python", "tools/audit_verify.py", "/data/audit"),
        cwd=ROOT, capture_output=True, text=True, timeout=300, env={**os.environ, **compose_env()}, check=False,
    )  # fmt: skip
    return res.returncode, (res.stdout + res.stderr)


# ------------------------------------------------------------------------------------------------ the night
def mail_command(subject: str) -> str:
    m = EmailMessage()
    m["From"] = SENDER
    m["To"] = "trialbox@hospa.test"
    m["Subject"] = subject
    m["Message-ID"] = mid = make_msgid(domain="hospa.test")
    m["Authentication-Results"] = AUTH
    m.set_content("TrialBox failure drill (synthetic)")
    with smtplib.SMTP("127.0.0.1", _stack().host_port("SMTP"), timeout=30) as s:
        s.send_message(m)
    return mid


def until(pred: Callable[[], bool], limit: float, step: float = 2.0) -> bool:
    end = time.monotonic() + limit
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except Exception:  # a reader that fails while a part is down is "not yet"
            pass
        time.sleep(step)
    return False


def _any(pred: Callable[[dict[str, Any]], bool]) -> bool:
    return any(pred(j) for j in jobs_or_none() or [])


#: what the drill waits for before it kills (``Target.when``)
CONDITIONS: dict[str, Callable[[], bool]] = {
    "the adapter's ingest run is running": lambda: _any(lambda j: j["type"] == "INGEST" and j["state"] in RUNNING),
    "the ingest has ended and the lake is rebuilding": lambda: _lake_state() == "running",
    "a mailed FEAS is running": lambda: _any(lambda j: j["type"] == "FEAS" and j["state"] in RUNNING),
    "a mailed job is running": lambda: _any(lambda j: bool(j.get("message_id")) and j["state"] in RUNNING),
    "a mailed SCREEN is running (it asks the model)": lambda: _any(
        lambda j: j["type"] == "SCREEN" and j["state"] in ("running", "reporting")
    ),
    "a mailed SCREEN is running": lambda: _any(lambda j: j["type"] == "SCREEN" and j["state"] in RUNNING),
    "the first result mail is in the outbox": lambda: len(mails()) >= 1,
    "the morning notices are being sent": lambda: True,
}


def _lake_state() -> str:
    """The state of today's rebuild (``GET /rebuild/<snapshot>`` on the lake; the snapshot is the site's day)."""
    day = datetime.now(site_tz()).date().isoformat()
    body = httpx.get(_stack().url("LAKE", f"/rebuild/{day}"), timeout=10).json()
    return str(body.get("state") or "")


def settled(js: Sequence[dict[str, Any]]) -> bool:
    return all(j["state"] in (*TERMINAL, *WAITS) for j in js)


def stage_mailed() -> None:
    for rs in STUDIES:
        mail_command(f"FEAS {rs} -- drill")
        mail_command(f"SCREEN {rs} -- drill")


#: the timer's ingest is set this far ahead when the stack starts (up, yesterday's ingest and the mailed stage fit)
INGEST_AFTER_S = 420


def stage_ingest() -> None:
    """The timer's INGEST: nothing to do but wait; its clock time was set when the stack started (no restart of the
    orchestrator during the night: a restart is itself a recovery, and would hide a stuck job)."""
    until(lambda: _any(lambda j: j["type"] == "INGEST"), INGEST_AFTER_S + 120, 5)


def stage_notices() -> subprocess.Popen[str]:
    return subprocess.Popen(
        compose("exec", "-T", "console", "python", "-m", "console.notify"),
        cwd=ROOT, env={**os.environ, **compose_env()}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )  # fmt: skip


def night_done(after_ingest: bool) -> bool:
    js = jobs()
    mailed = [j for j in js if j.get("message_id")]
    if len(mailed) < 2 * len(STUDIES) or not settled(mailed):
        return False
    if not after_ingest:
        return True
    timer = [j for j in js if j["requested_by"] in ("scheduler", "system")]
    ingests = [j for j in timer if j["type"] == "INGEST"]
    if ingests and settled(timer) and not any(j["state"] == "done" for j in ingests):
        return True  # the night's ingest failed: the chain does not follow it (orchestrator/night.py)
    return any(j["type"] == "INGEST" for j in timer) and settled(timer) and any(j["type"] == "RETENTION" for j in timer)


def run_night(t: Target | None, rec: Record) -> None:
    """The night, with the kill of ``t`` in its stage (None: the control night)."""
    t0 = time.monotonic()
    killed_at: list[float] = []
    chain_at_kill: dict[str, Any] = {}

    def maybe_kill(stage: str) -> None:
        if t is None or t.stage != stage or killed_at:
            return
        if not until(CONDITIONS[t.when], 900, 0.25):
            rec.notes.append(f"the kill point ({t.when}) was not seen within 900 s: killed at the end of the wait")
        chain_at_kill.update(_safe(chain, {"lines": 0, "seqs": []}))
        chain_at_kill["ended"] = sum(j["state"] in TERMINAL for j in jobs_or_none() or [])
        if t.kind == "disk":
            rec.killed = fill_disk(t.service)
        else:
            rec.killed = kill9(t.service)
        killed_at.append(time.monotonic())
        rec.killed_at_s = killed_at[0] - t0
        log(f"killed {t.name} at {rec.killed_at_s:.0f} s ({t.stage})")
        recover(t, rec, killed_at[0])

    stage_mailed()
    maybe_kill("mailed")
    if not until(lambda: night_done(False) or _any(lambda j: j["type"] == "INGEST"), FINISH_S, 5):
        rec.notes.append("the mailed jobs had not settled and the timer's ingest had not started")
    elif not _safe(lambda: night_done(False), False):
        rec.notes.append("the mailed jobs had not settled when the timer's ingest started")
    stage_ingest()
    maybe_kill("ingest")
    if not until(lambda: night_done(True), FINISH_S, 5):
        rec.notes.append(f"the night's jobs had not settled within {FINISH_S} s of the ingest stage")
    proc = stage_notices()
    if t is not None and t.stage == "notices":
        time.sleep(1.0)
        maybe_kill("notices")
    try:
        out, _ = proc.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        out = "the notice run did not end in 600 s"
    rec.notes.append(f"console.notify: exit {proc.returncode}: {(out or '').strip()[-200:]}")
    if t is not None and t.stage == "notices":  # the box's timer runs the notices again the next minute it fires
        wait_healthy(["console"], time.monotonic(), RECOVER_S)
        p2 = stage_notices()
        p2.communicate(timeout=600)
        rec.notes.append(f"console.notify (second run, as the timer's next firing): exit {p2.returncode}")
    rec.finished = _safe(lambda: night_done(True), False)
    rec.notes.append(f"the night took {time.monotonic() - t0:.0f} s")
    rec.audit_at_kill = chain_at_kill  # type: ignore[attr-defined]


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default


def recover(t: Target, rec: Record, at: float) -> None:
    """Let the box's own recovery act; say what did it and how long it took. A person's step is taken only when
    the box did not recover by itself within :data:`RECOVER_S`, and is said."""
    every = [s for s in services() if s not in ("greenmail", "mailpit")] or [t.service]
    if t.kind == "disk":
        time.sleep(FULL_FOR_S)
        free_disk(t.service)
        rec.notes.append(f"the disk was freed {FULL_FOR_S} s after it filled (the drill's own step, as a person would)")
    took = wait_healthy([t.service], at, RECOVER_S)
    restarts = health(t.service).split()[-1:] or ["?"]
    if took is not None:
        rec.recovered_by = (
            f"Docker's restart policy (restarts: {restarts[0]})"
            if t.kind != "disk"
            else f"a person's step (the drill freed the space); the database's restarts: {restarts[0]}"
        )
        all_took = wait_healthy(every, at, RECOVER_S)
        rec.recover_s = all_took if all_took is not None else took
        if all_took is None:
            rec.notes.append("the killed service came back but not every service was healthy within the window: "
                             + ", ".join(f"{s} {health(s)}" for s in every))  # fmt: skip
        return
    sh(["python3", "-m", "tools.trialbox", "watchdog", "--after-minutes", "0"], timeout=300)
    took = wait_healthy([t.service], at, RECOVER_S * 2)
    if took is not None:
        rec.recovered_by, rec.recover_s = "the watchdog (tools.trialbox watchdog)", took
        return
    dc("up", "-d", "--wait", disk=t.kind == "disk", timeout=900)
    took = wait_healthy([t.service], at, RECOVER_S * 3)
    rec.recovered_by = "a person: docker compose up -d" if took is not None else "not recovered"
    rec.recover_s = took


DATA = "/var/lib/postgresql/data"
FILL = f"dd if=/dev/zero of={DATA}/drill-fill bs=1M 2>&1 | tail -1; df -h {DATA} | tail -1"


def fill_disk(service: str) -> str:
    """Fill the disk that holds the database's volume. On the loop-mounted ext4: a file beside the database's
    folder, written from the host (something else on the same disk grew, as on a site; the runbook forbids deleting
    from the database volume). On the tmpfs fallback: a file inside the volume, from inside the container."""
    if DISK_MOUNT.is_mount():
        out = sh(["sh", "-c", f"dd if=/dev/zero of={shlex.quote(str(DISK_MOUNT / 'fill'))} bs=1M 2>&1 | tail -1; "
                  f"df -h {shlex.quote(str(DISK_MOUNT))} | tail -1"], timeout=300)  # fmt: skip
        where = "the disk that holds the database's volume, filled from the host by a file beside the database's folder"
    else:
        out = dc("exec", "-T", "-u", "postgres", service, "sh", "-c", FILL, timeout=300, disk=True)
        where = "the database's data volume (tmpfs), filled from inside the container"
    said = "; ".join(" ".join(x.split()) for x in out.strip().splitlines())
    return f"{where} until no space was left: {said}"


def free_disk(service: str) -> None:
    if DISK_MOUNT.is_mount():
        (DISK_MOUNT / "fill").unlink(missing_ok=True)
    else:
        dc("exec", "-T", "-u", "postgres", service, "rm", "-f", f"{DATA}/drill-fill", disk=True)


# ------------------------------------------------------------------------------------------------ one target
def snapshot() -> dict[str, Any]:
    c = _safe(chain, {"lines": 0, "seqs": []})
    rc, out = _safe(verify, (-1, "verify could not run"))
    return {"jobs": _safe(jobs, []), "mails": mails(), "outbox": _safe(outbox, []), "chain": c,
            "journal": _safe(journal_seqs, []), "verify_rc": rc, "verify_out": out[-2000:]}  # fmt: skip


def one(t: Target | None, out: Path, run: int) -> dict[str, Any]:
    name = t.name if t else "control"
    log(f"{name}: fresh stack")
    disk = bool(t and t.kind == "disk")
    medium = ""
    if disk:
        dc("down", "-v", "--remove-orphans", disk=True, timeout=600)
        medium = write_disk_override(1024)
    fresh_stack(disk)
    _stack().ensure_ingested(force=True)
    rec = Record(name, t.kind if t else "none", t.service if t else "", t.stage if t else "", t.when if t else "",
                 run=run)  # fmt: skip
    if medium:
        rec.notes.append(f"the data volume: {medium}")
    run_night(t, rec)
    snap = snapshot()
    snap["chain_at_kill"] = getattr(rec, "audit_at_kill", {})
    snap["record"] = rec.to_json()
    (out / "raw").mkdir(parents=True, exist_ok=True)
    (out / "raw" / f"{name}-{run}.json").write_text(json.dumps(snap, indent=1, default=str), encoding="utf-8")
    if t is None:
        return snap
    control = json.loads((out / "raw" / "control-1.json").read_text(encoding="utf-8"))
    rec.jobs = check_jobs(control["jobs"], snap["jobs"])
    rec.mail = check_mail(control["mails"], snap["mails"], snap["outbox"])
    missing = sorted(set(snap["journal"]) - set(snap["chain"]["seqs"]))
    rec.audit = check_audit(
        snap["verify_rc"], snap["verify_out"], int(snap["chain_at_kill"].get("lines", 0)),
        int(snap["chain"]["lines"]), len(missing),
        sum(j["state"] in TERMINAL for j in snap["jobs"]) > int(snap["chain_at_kill"].get("ended", 0)),
    )  # fmt: skip
    if missing:
        rec.audit.lines.append(f"journal rows not in the chain: {missing[:20]}")
    stuck = [j["job_id"] for j in snap["jobs"] if j["state"] not in (*TERMINAL, *WAITS)]
    if stuck:  # the checks above are on the box as it was left; then a person's step, and what it did
        t1 = time.monotonic()
        dc("restart", "orchestrator", timeout=300)
        ok = until(lambda: all(j["state"] in (*TERMINAL, *WAITS) for j in jobs() if j["job_id"] in stuck), 600, 5)
        after = {j["job_id"]: j["state"] for j in _safe(jobs, []) if j["job_id"] in stuck}
        rec.notes.append(
            f"after the check, a person's step (docker compose restart orchestrator): the stuck jobs "
            f"{'ended' if ok else 'did not end'} within {time.monotonic() - t1:.0f} s: {after}"
        )
    path = out / (f"{name}.json" if run == 1 else f"{name}-run{run}.json")
    path.write_text(json.dumps(rec.to_json(), indent=1), encoding="utf-8")
    return snap


def drill(out: Path, targets: Sequence[Target], run: int = 1) -> int:
    out.mkdir(parents=True, exist_ok=True)
    if not (out / "raw" / "control-1.json").exists():
        one(None, out, 1)
    for t in targets:
        try:
            one(t, out, run)
        except Exception as exc:  # a target that cannot be run is said, and the drill goes on
            rec = Record(t.name, t.kind, t.service, t.stage, t.when, run=run, recovered_by="not run")
            rec.notes.append(f"could not be run here: {type(exc).__name__}: {str(exc)[-600:]}")
            path = out / (f"{t.name}.json" if run == 1 else f"{t.name}-run{run}.json")
            path.write_text(json.dumps(rec.to_json(), indent=1), encoding="utf-8")
            log(f"{t.name}: not run: {exc}")
    dc("down", "-v", "--remove-orphans", disk=True, timeout=600)
    release_disk()
    from tools.failure_drill import load

    print(render(load(out)))
    return 0
