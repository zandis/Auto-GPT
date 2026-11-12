"""``python3 -m tools.trialbox watchdog``: restart a service whose health check fails, and audit it (T-108a, D-360).

Docker's ``restart: unless-stopped`` acts when a process exits, not when its health check fails: a hung vLLM stays
"up" and a screening run waits on it (OPS-029). This watchdog runs on the host, beside the stack, with the host's
``python3`` and the standard library only (like ``ops`` and ``secrets``). Each pass:

1. lists the compose project's containers that carry the label ``tb.watchdog`` (the compose files set it: ``restart``
   on every long-running service, ``report`` on the database, where a restart is no cure and a person looks);
2. a container Docker calls ``unhealthy`` (its health check failed ``retries`` times in a row) for at least
   ``--after-minutes`` is restarted (``docker restart``) and an ``ops.watchdog.restart`` event goes into the box's
   hash-chained audit log; a ``report`` container gets one ``ops.watchdog.unhealthy`` event per episode;
3. at most ``--max-restarts`` restarts per service in ``--window-hours``: after that the watchdog stops restarting
   it, audits ``ops.watchdog.gave_up`` once and leaves it to a person (a restart loop hides the fault and can keep
   the card busy). The episode ends when the service is healthy again.

The audit line is written inside the orchestrator, as ``update.py`` and ``ops.py`` write theirs
(``docker compose exec -T orchestrator python -c ...``). When that fails (the orchestrator is the one restarting, or
the stack is down) the event waits in ``deploy/watchdog/pending_audit.jsonl`` and the next pass writes it first, so no
restart goes unaudited. The detail holds the service, the container name, how long it was unhealthy and the health
check's failing streak and exit code, never the check's output.

Two cases are left alone (D-455). A container Docker reports as **paused** (``docker compose pause``, e.g. a backup
with ``TB_BACKUP_QUIESCE=pause``) is never restarted, whatever its health says: a paused service's probe times out, so
Docker calls it unhealthy, but it is held on purpose; its unhealthy clock does not run while it is paused. While the
**maintenance flag** ``deploy/watchdog/maintenance`` exists, nothing is restarted and each service the watchdog would
have acted on is listed as ``maintenance``. The flag is JSON (who, why, since, and the pid of the process holding it,
:func:`maintenance`); a flag whose process is gone is stale and ignored (removed outside a dry run), so a killed
backup never leaves the watchdog off. A flag a person wrote (no pid) stays until the person removes it.

Run it every minute: ``python3 -m tools.trialbox watchdog`` (one pass, for a systemd timer; T-108b installs the unit)
or ``--interval 60`` (a loop). ``--dry-run`` lists what it would do and changes nothing.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LABEL = "tb.watchdog"
MODES = ("restart", "report")
SERVICE_LABEL = "com.docker.compose.service"
PROJECT_LABEL = "com.docker.compose.project"
ACTOR = "trialbox-watchdog"
AUDIT_CODE = (
    "import json, sys\nfrom tb_common.audit_writer import open_audit\ne = json.loads(sys.argv[1])\n"
    "open_audit().append(e['event'], actor=e['actor'], detail=e['detail'])\n"
)


class WatchdogError(RuntimeError):
    """A docker command failed."""


Runner = Callable[[Sequence[str], float], str]  # (argv, timeout) -> stdout; raises WatchdogError
AuditWriter = Callable[[dict[str, Any]], None]  # raises on failure; the event is then kept as pending


def run_cmd(argv: Sequence[str], timeout: float) -> str:
    try:
        r = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WatchdogError(f"{shlex.join(list(argv)[:6])} ...: {exc}") from exc
    if r.returncode != 0:
        raise WatchdogError(f"{shlex.join(list(argv)[:6])} ... exit {r.returncode}: {(r.stderr or '').strip()[-300:]}")
    return r.stdout


@dataclass(frozen=True)
class Container:
    id: str
    name: str
    service: str
    mode: str  # restart | report
    health: str  # healthy | unhealthy | starting | none
    failing_streak: int
    last_exit: int | None
    paused: bool = False  # D-455: held on purpose (docker compose pause); never restarted

    @classmethod
    def from_inspect(cls, doc: dict[str, Any]) -> Container:
        labels = (doc.get("Config") or {}).get("Labels") or {}
        st = doc.get("State") or {}
        health = st.get("Health") or {}
        log = health.get("Log") or []
        last = log[-1].get("ExitCode") if log and isinstance(log[-1], dict) else None
        return cls(
            id=str(doc.get("Id", "")),
            name=str(doc.get("Name", "")).lstrip("/"),
            service=str(labels.get(SERVICE_LABEL) or str(doc.get("Name", "")).lstrip("/")),
            mode=str(labels.get(LABEL, "")),
            health=str(health.get("Status") or "none"),
            failing_streak=int(health.get("FailingStreak") or 0),
            last_exit=last if isinstance(last, int) else None,
            paused=bool(st.get("Paused")) or st.get("Status") == "paused",
        )


MAINTENANCE = "maintenance"  # the flag's file name in deploy/watchdog/ (D-455)


def _start_time(pid: int) -> str | None:
    """The process's start time in clock ticks since boot (``/proc/<pid>/stat`` field 22), or None where there is
    no ``/proc``: with the pid it names one process, so a pid reused by another process is not the flag's holder."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    fields = stat.rsplit(")", 1)[-1].split()  # the name in () may hold spaces
    return fields[19] if len(fields) > 19 else None


def _alive(pid: int, start: str | None = None) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # another user's process: it is there
        pass
    if start is not None:  # D-455: the same pid, another process (the holder died, the pid was given out again)
        now = _start_time(pid)
        return now is None or now == start
    return True


def maintenance_state(deploy: Path, clean: bool = False) -> dict[str, Any] | None:
    """The maintenance flag when it is in force, else None. A flag whose holder process is gone is stale: None, and
    removed when ``clean``. A flag without a pid (written by a person) is in force until it is removed."""
    f = deploy / "watchdog" / MAINTENANCE
    try:
        doc = json.loads(f.read_text(encoding="utf-8") or "{}")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        doc = {"by": "unknown", "why": "an unreadable flag file"}  # a person's flag in another form: honoured
    doc = doc if isinstance(doc, dict) else {}
    pid = doc.get("pid")
    start = doc.get("pid_start")
    if isinstance(pid, int) and not _alive(pid, start if isinstance(start, str) else None):
        if clean:
            f.unlink(missing_ok=True)
        return None
    return doc


@contextmanager
def maintenance(deploy: Path, by: str, why: str) -> Iterator[Path]:
    """Hold the maintenance flag while the block runs (removed after it, whatever happens; a killed holder leaves a
    stale flag the watchdog ignores)."""
    d = deploy / "watchdog"
    d.mkdir(parents=True, exist_ok=True)
    f = d / MAINTENANCE
    tmp = d / f".{MAINTENANCE}.tmp"
    me = os.getpid()
    tmp.write_text(json.dumps({"by": by, "why": why, "since": int(time.time()), "pid": me,
                               "pid_start": _start_time(me)}), encoding="utf-8")  # fmt: skip
    os.replace(tmp, f)
    try:
        yield f
    finally:
        f.unlink(missing_ok=True)


def compose_audit(deploy: Path, run: Runner = run_cmd) -> AuditWriter:
    """The writer of a site box: the event goes into the audit chain from inside the orchestrator."""
    compose = shlex.split(
        os.environ.get("TB_COMPOSE") or f"docker compose --project-directory {shlex.quote(str(deploy))}"
    )

    def write(event: dict[str, Any]) -> None:
        run([*compose, "exec", "-T", "orchestrator", "python", "-c", AUDIT_CODE, json.dumps(event)], 60)

    return write


class Watchdog:
    def __init__(
        self,
        deploy: Path,
        *,
        run: Runner = run_cmd,
        audit: AuditWriter | None = None,
        clock: Callable[[], float] = time.time,
        project: str | None = None,
        after_minutes: float = 2.0,
        max_restarts: int = 3,
        window_hours: float = 6.0,
        dry_run: bool = False,
        out: Callable[[str], None] = print,
    ) -> None:
        self.deploy = deploy
        self.run = run
        self.audit_writer = audit if audit is not None else compose_audit(deploy, run)
        self.clock = clock
        self.project = project or os.environ.get("COMPOSE_PROJECT_NAME") or "trialbox"
        self.after_s = after_minutes * 60
        self.max_restarts = max_restarts
        self.window_s = window_hours * 3600
        self.dry_run = dry_run
        self.out = out
        self.docker = shlex.split(os.environ.get("TB_DOCKER") or "docker")
        self.dir = deploy / "watchdog"
        self.state_file = self.dir / "state.json"
        self.pending_file = self.dir / "pending_audit.jsonl"

    # ------------------------------------------------------------------ docker
    def containers(self) -> list[Container]:
        ids = self.run(
            [*self.docker, "ps", "-q", "--no-trunc", "--filter", f"label={PROJECT_LABEL}={self.project}",
             "--filter", f"label={LABEL}"], 60,
        ).split()  # fmt: skip
        if not ids:
            return []
        docs = json.loads(self.run([*self.docker, "inspect", *ids], 60) or "[]")
        found = [Container.from_inspect(d) for d in docs if isinstance(d, dict)]
        return [c for c in found if c.mode in MODES]

    def restart(self, c: Container) -> None:
        self.run([*self.docker, "restart", "--time", "60", c.id], 300)

    # ------------------------------------------------------------------ state
    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            doc = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return doc if isinstance(doc, dict) else {}

    def _save(self, state: dict[str, dict[str, Any]]) -> None:
        if self.dry_run:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, sort_keys=True, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_file)

    # ------------------------------------------------------------------ audit
    def _pending(self) -> list[dict[str, Any]]:
        try:
            lines = self.pending_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue  # a torn line of a crash: nothing to replay
        return out

    def _write_pending(self, events: list[dict[str, Any]]) -> None:
        if not events:
            self.pending_file.unlink(missing_ok=True)
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.pending_file.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in events), encoding="utf-8")
        os.replace(tmp, self.pending_file)

    def flush(self) -> int:
        """Write the events kept from an earlier pass, oldest first; stop at the first failure (order kept)."""
        pending = self._pending()
        done = 0
        for e in pending:
            try:
                self.audit_writer(e)
            except Exception:  # still no orchestrator: keep the rest for the next pass
                break
            done += 1
        if done:
            self._write_pending(pending[done:])
        return done

    def audit(self, event: str, detail: dict[str, Any]) -> bool:
        """True when the event is in the chain now; False when it waits in the pending file."""
        e = {"event": event, "actor": ACTOR, "detail": {**detail, "at": int(self.clock())}}
        if self.dry_run:
            return False
        if not self._pending():
            try:
                self.audit_writer(e)
                return True
            except Exception as exc:
                self.out(f"watchdog: audit of {event} is pending ({type(exc).__name__})")
        self._write_pending([*self._pending(), e])
        return False

    # ------------------------------------------------------------------ one pass
    def tick(self) -> list[dict[str, Any]]:
        """One pass. Returns the actions taken (also printed, for the journal)."""
        if not self.dry_run:
            self.flush()
        now = self.clock()
        state = self._load()
        actions: list[dict[str, Any]] = []
        seen: set[str] = set()
        flag = maintenance_state(self.deploy, clean=not self.dry_run)
        if flag is not None:
            self.out(f"watchdog: maintenance on ({flag.get('by', '?')}: {flag.get('why', '')}): nothing is restarted")
        for c in self.containers():
            seen.add(c.service)
            s = state.setdefault(c.service, {})
            s["restarts"] = [t for t in s.get("restarts", []) if now - float(t) < self.window_s]
            if c.paused:  # D-455: held on purpose; its probe times out, it is not hung. The clock starts afresh after
                s.pop("unhealthy_since", None)
                actions.append({"service": c.service, "action": "paused", "unhealthy_minutes": 0.0})
                continue
            if c.health != "unhealthy":
                for k in ("unhealthy_since", "reported", "gave_up"):
                    s.pop(k, None)  # healthy (or starting, or no check): the episode is over
                continue
            since = float(s.setdefault("unhealthy_since", now))
            minutes = round((now - since) / 60, 1)
            if now - since < self.after_s:
                actions.append({"service": c.service, "action": "waiting", "unhealthy_minutes": minutes})
                continue
            detail = {"service": c.service, "container": c.name, "unhealthy_minutes": minutes,
                      "failing_streak": c.failing_streak, "last_exit": c.last_exit}  # fmt: skip
            if c.mode == "report":
                if not s.get("reported"):
                    s["reported"] = True
                    self.audit("ops.watchdog.unhealthy", {**detail, "mode": "report"})
                    actions.append({**detail, "action": "reported"})
                continue
            if (
                flag is not None
            ):  # D-455: a person or a backup holds the box still: no restart (a report still goes out)
                actions.append({**detail, "action": "maintenance"})
                continue
            if len(s["restarts"]) >= self.max_restarts:
                if not s.get("gave_up"):
                    s["gave_up"] = True
                    self.audit("ops.watchdog.gave_up", {**detail, "restarts_in_window": len(s["restarts"]),
                                                        "window_hours": self.window_s / 3600})  # fmt: skip
                    actions.append({**detail, "action": "gave_up"})
                continue
            if self.dry_run:
                actions.append({**detail, "action": "would_restart"})
                continue
            try:
                self.restart(c)
            except WatchdogError as exc:
                s["restarts"].append(now)  # a failed try counts: the cap stops a loop of failing restarts too
                self.audit("ops.watchdog.restart_failed", {**detail, "error": str(exc)[:300]})
                actions.append({**detail, "action": "restart_failed"})
                continue
            s["restarts"].append(now)
            s.pop("unhealthy_since", None)
            self.audit("ops.watchdog.restart", {**detail, "restarts_in_window": len(s["restarts"])})
            actions.append({**detail, "action": "restarted"})
        for gone in set(state) - seen:  # a service removed from the stack (or scaled to 0)
            if not state[gone].get("restarts"):
                state.pop(gone)
        self._save(state)
        for a in actions:
            if a["action"] == "paused":  # D-455: visible, so a service paused by mistake is seen
                self.out(f"watchdog: paused {a['service']} (held on purpose: not restarted)")
            elif a["action"] != "waiting":
                self.out(f"watchdog: {a['action']} {a['service']} (unhealthy {a['unhealthy_minutes']} min)")
        return actions


def main(
    deploy: Path,
    *,
    interval: int = 0,
    after_minutes: float = 2.0,
    max_restarts: int = 3,
    window_hours: float = 6.0,
    dry_run: bool = False,
    as_json: bool = False,
) -> int:
    wd = Watchdog(deploy, after_minutes=after_minutes, max_restarts=max_restarts, window_hours=window_hours,
                  dry_run=dry_run)  # fmt: skip
    while True:
        try:
            actions = wd.tick()
            rc = 0
        except (WatchdogError, ValueError) as exc:  # no docker, or a daemon that does not answer: say so, go on
            print(f"watchdog: {exc}", file=sys.stderr)
            actions, rc = [], 1
        if as_json:
            print(json.dumps(actions, sort_keys=True))
        if interval <= 0:
            return rc
        time.sleep(interval)
