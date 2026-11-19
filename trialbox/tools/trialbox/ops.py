"""``trialbox ops`` (D-178, review J-09): the host side of the console's operations screens.

The console runs in a container without Docker, the backup key's tools or the install folder, so it never runs an
operation itself. It writes a request (``requests/<id>.json``) into the operations folder it shares with the host
(``TB_OPS_DIR``; on a box ``deploy/ops``, mounted in the console at ``/data/ops``). This runner, started by a host
timer every minute (``sudo python3 -m tools.trialbox ops run``, RUNBOOK "Operations screens"), takes each request,
runs the command the runbook already names for it and writes the result (``results/<id>.json``). After each round it
writes ``status.json``, which is what the console's screens show. No operation is re-implemented here:

==================  ==========================================================================================
``backup``          ``trialbox backup`` (on a box: the update path's one-off backup container, ``ComposeBox``)
``backup_check``    ``trialbox backup-check`` of the newest backup in every target (no key) and the copies compared
``update_check``    ``tools/apply_update.sh <bundle> --dry-run``: signature and hashes verified, nothing changes;
                    with ``from: stick`` (10K-7, D-1363) the bundle is first copied from the update stick
                    (``TB_UPDATE_STICK``, read only) into the incoming folder, and the verified bundle's Japanese
                    release note and change-impact sheet are kept in ``<ops>/notes/`` for the console
``update_apply``    ``tools/apply_update.sh <bundle>``: backup first, rollback point, automatic rollback; with
                    ``when: quiet`` (T-730b, D-731) it waits for the quiet hour and for no job running
``logs_collect``    ``trialbox logs collect`` (yesterday's service logs)
``network_sheet``   ``tools/network_sheet.py`` into ``<ops>/network/`` (en, ja, zh-TW)
==================  ==========================================================================================

The status and the results never hold a secret: secrets are listed by name, presence and age
(``svc_secrets.status``), backups by file name, size and time, logs by day. Standard library at import; the backup,
log, update and network-sheet modules are imported when an action needs them.

A *local* box (``--local``; the console's ``TB_OPS_RUNNER=inline``: the in-process box of e2e_simple, the demo and
the tests) runs the same actions in the console's process at once: the backup through ``backup.backup`` with the
process's database URL and ``TB_BACKUP_DIRS``. Updates and log collection need the compose box and are refused there.
"""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
ACTIONS: tuple[str, ...] = (
    "backup",
    "backup_check",
    "update_check",
    "update_apply",
    "logs_collect",
    "network_sheet",
)
COMPOSE_ONLY = frozenset({"update_apply", "logs_collect"})
REQ_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")
BUNDLE = re.compile(r"^[A-Za-z0-9][\w.\-]{0,120}\.tar$")
BACKUP_FILE = re.compile(r"^trialbox-[\w\-]+-(\d{8}T\d{6}Z)\.tbbak$")
SERVICE_UID = 10001  # the ``tb`` user of the trialbox-py image (svc_secrets.SERVICE_UID)
STALE_HOURS = 36  # WS-08.5: the backup tile turns red 36 hours after the last backup
MAX_AGE_MIN = 60  # a request older than this when the runner reaches it is not run: the person asks again
# T-730b (D-731): an update asked for "in the quiet hour" waits for it, up to this long (the next quiet hour always
# comes within a day; two hours more for a night that ran long), then it expires as any old request does
QUIET_WAIT_H = 26
QUIET_DEFAULT_AT, QUIET_DEFAULT_HOURS = "05:00", "2"  # the box's quiet hour unless the site sets one (D-731)
# 10K-7 (D-1363): where the host mounts an update stick inserted at the box, read only, unless TB_UPDATE_STICK says
STICK_DEFAULT = "/media/trialbox-update"
STICK_MARGIN = 1.05  # the copy into the incoming folder needs the bundle's size and 5 % more free
Runner = Callable[[Sequence[str], int | None], str]  # (argv, timeout seconds) -> combined output; raises OpsFailed


class OpsFailed(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_cmd(argv: Sequence[str], timeout: int | None) -> str:
    """Run a command from the install folder; its output (stdout and stderr) is the result's text."""
    from tools.trialbox import procgroup

    # T-695 (D-752): the whole process group is killed on the limit, never the shell alone with the updater left
    r = procgroup.run(list(argv), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise OpsFailed(f"exit {r.returncode}: {out.strip()[-600:]}")
    return out


def _env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


MAX_JSON = 64 * 1024  # a request, a result or the status is a few kilobytes


def _read_json(path: Path) -> dict[str, Any] | None:
    """A small JSON object from a regular file. The runner reads ``requests/`` as root and the console's user can
    write there, so a link (to a file it may not read), a pipe (the timer would wait for ever) or a huge file is
    skipped, never followed."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_JSON:
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = json.loads(f.read(MAX_JSON + 1).decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)
    return data if isinstance(data, dict) else None


def _quiet_setting(env: Mapping[str, str]) -> tuple[Any, int, int, float] | str:
    """The quiet hour's zone, start and length, or the name of the setting that does not read (D-731)."""
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo((env.get("TB_TZ") or "").strip())
    except (ValueError, KeyError, OSError):
        return "TB_TZ"
    try:
        hh, mm = (int(x) for x in (env.get("TB_UPDATE_QUIET_AT") or QUIET_DEFAULT_AT).strip().split(":"))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except ValueError:
        return "TB_UPDATE_QUIET_AT"
    try:
        hours = float((env.get("TB_UPDATE_QUIET_HOURS") or QUIET_DEFAULT_HOURS).strip())
        if not 0 < hours <= 12:
            raise ValueError
    except ValueError:
        return "TB_UPDATE_QUIET_HOURS"
    return zone, hh, mm, hours


def in_quiet_hour(env: Mapping[str, str], now: datetime) -> bool:
    """T-730b (D-731): ``now`` is inside the quiet hour: from ``TB_UPDATE_QUIET_AT`` (``HH:MM``, the site's clock,
    ``TB_TZ``) for ``TB_UPDATE_QUIET_HOURS`` real hours (0 to 12); a window may run over midnight, and on a day the
    clocks change it still lasts its hours. A setting that does not read, or a box with no zone, has no quiet hour
    (an update then waits and expires, never runs at an unknown time)."""
    from datetime import timedelta

    got = _quiet_setting(env)
    if isinstance(got, str):
        return False
    zone, hh, mm, hours = got
    at = now.astimezone(UTC)
    local = now.astimezone(zone)
    for day in (local.date() - timedelta(days=1), local.date()):  # a window that began yesterday evening
        start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone).astimezone(UTC)
        if start <= at < start + timedelta(hours=hours):
            return True
    return False


def _args(req: Mapping[str, Any]) -> dict[str, Any]:
    """A request's ``args`` when it is an object; else nothing (the console's user writes the file, D-731)."""
    a = req.get("args")
    return a if isinstance(a, dict) else {}


# ------------------------------------------------------------------------------------------------ the shared folder
class OpsDir:
    """The folder the console and the host share: requests, results, the status and the network sheet."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def network(self) -> Path:
        return self.root / "network"

    @property
    def notes(self) -> Path:
        """10K-7 (D-1363): the verified bundles' release notes and change-impact sheets (root's, the runner's)."""
        return self.root / "notes"

    def submit(self, action: str, by: str, args: Mapping[str, str] | None = None) -> str:
        if action not in ACTIONS:
            raise OpsFailed(f"unknown action {action!r}")
        rid = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        req = {"id": rid, "action": action, "by": by, "at": datetime.now(UTC).isoformat(), "args": dict(args or {})}
        _write_json(self.root / "requests" / f"{rid}.json", req)
        return rid

    def requests(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted((self.root / "requests").glob("*.json")):
            # the id is the file's name, never a field the console wrote: the runner (root on the host) writes
            # ``results/<id>.json``, so an id taken from the content could point outside the folder
            if REQ_ID.match(p.stem) and (r := _read_json(p)) is not None:
                with contextlib.suppress(OSError):  # the file's own time, not a field: how long it has waited
                    out.append({**r, "id": p.stem, "queued": p.lstat().st_mtime})
        return sorted(out, key=lambda r: (str(r.get("at")), str(r.get("id"))))  # first in, first out

    def result(self, rid: str) -> dict[str, Any] | None:
        return _read_json(self.root / "results" / f"{rid}.json") if REQ_ID.match(rid) else None

    def pending(self) -> list[dict[str, Any]]:
        return [r for r in self.requests() if self.result(str(r.get("id"))) is None]

    def marker(self, rid: str) -> Path:
        """``running/<id>.json``: written just before a request runs. A request with a marker and no result was cut
        off (a reboot, an OOM kill, ``systemctl stop``) and is never run again."""
        if not REQ_ID.match(rid):
            raise OpsFailed(f"bad request id {rid[:40]!r}")
        return self.root / "running" / f"{rid}.json"

    def running(self) -> list[dict[str, Any]]:
        """The pending requests that have started (one, while the runner works on it)."""
        return [r for r in self.pending() if self.marker(str(r.get("id"))).is_file()]

    def history(self, limit: int = 30) -> list[dict[str, Any]]:
        """Requests, newest first, each with its result when there is one."""
        rows = []
        for r in reversed(self.requests()[-limit:]):
            rows.append({**r, "result": self.result(str(r.get("id")))})
        return rows

    def last(self, action: str) -> dict[str, Any] | None:
        """The newest finished result of ``action``."""
        for r in reversed(self.requests()):
            if r.get("action") == action and (res := self.result(str(r.get("id")))) is not None:
                return res
        return None

    def status(self) -> dict[str, Any] | None:
        return _read_json(self.root / "status.json")

    def write_result(
        self, req: Mapping[str, Any], ok: bool, summary: str, lines: Sequence[str], started: str, state: str = ""
    ) -> None:
        """``state``: ``done``, ``failed``, ``interrupted`` (it started and was cut off), ``expired`` (it waited
        longer than :data:`MAX_AGE_MIN`, or a quiet update :data:`QUIET_WAIT_H`) or ``superseded`` (a quiet update
        another update overtook, D-731); the last three never ran to the end and are not run again."""
        if not REQ_ID.match(str(req.get("id"))):
            raise OpsFailed(f"bad request id {str(req.get('id'))[:40]!r}")
        _write_json(
            self.root / "results" / f"{req['id']}.json",
            {
                "id": req["id"],
                "action": req["action"],
                "by": req.get("by", ""),
                "ok": ok,
                "state": state or ("done" if ok else "failed"),
                "summary": summary[:300],
                "lines": [str(x)[:300] for x in list(lines)[-40:]],
                "started": started,
                "finished": _now(),
            },
        )


# ------------------------------------------------------------------------------------------------ the box
@dataclass
class Box:
    """Where the runner works: ``compose`` (a site box, as root on the host) or ``local`` (in one process)."""

    kind: str
    deploy: Path
    env: dict[str, str] = field(default_factory=dict)
    run: Runner = run_cmd

    @classmethod
    def compose(cls, deploy: Path) -> Box:
        return cls("compose", deploy, {**_env_file(deploy / ".env"), **_env_only(os.environ)})

    @classmethod
    def local(cls, deploy: Path, env: Mapping[str, str]) -> Box:
        return cls("local", deploy, dict(env))

    def targets(self) -> list[Path]:
        raw = self.env.get("TB_BACKUP_TARGETS") or ""
        return [Path(t) for t in raw.replace(",", " ").split() if t]

    def public_key(self) -> Path:
        return Path(self.env.get("TB_BACKUP_PUBKEY") or self.deploy / "secrets" / "backup.pub")

    def incoming(self) -> Path:
        return Path(self.env.get("TB_UPDATE_INCOMING") or self.deploy / "updates" / "incoming")

    def stick(self) -> Path:
        """10K-7 (D-1363): the update stick's mount point (a read-only mount; the runner never writes there)."""
        return Path(self.env.get("TB_UPDATE_STICK") or STICK_DEFAULT)

    def log_dir(self) -> Path:
        return Path(self.env.get("TB_LOG_DIR") or self.deploy / "logs")


def _env_only(env: Mapping[str, str]) -> dict[str, str]:
    """The few variables an operator may set for the runner (never a password)."""
    keep = (
        "TB_BACKUP_TARGETS",
        "TB_BACKUP_PUBKEY",
        "TB_UPDATE_INCOMING",
        "TB_UPDATE_STICK",
        "TB_LOG_DIR",
        "TB_OPS_DIR",
    )
    return {k: v for k, v in env.items() if k in keep and v}


# ------------------------------------------------------------------------------------------------ the runner
class OpsRunner:
    """Takes the requests of an :class:`OpsDir` one by one and runs the command behind each."""

    def __init__(self, box: Box, ops: OpsDir) -> None:
        self.box = box
        self.ops = ops

    def now(self) -> datetime:
        return datetime.now(UTC)

    def jobs_running(self) -> int | None:
        """How many jobs the orchestrator runs now; None when it cannot be asked. A local box runs none."""
        if self.box.kind != "compose":
            return 0
        from tools.trialbox.update import ComposeBox

        return ComposeBox(self.box.deploy).running_jobs()

    def _job_count(self) -> int | None:
        try:
            return self.jobs_running()
        except Exception:  # not known: not quiet
            return None

    def _seen(self, req: Mapping[str, Any]) -> dict[str, Any]:
        """D-731: the runner's own record of a quiet update (``seen/<id>.json``, root's): when the runner first saw
        it and the staged bundle's sha256 then. The wait is counted from it, not from the request file's time, which
        the console's user can move; and the file applied is the one the person confirmed."""
        rid = str(req.get("id"))
        if not REQ_ID.match(rid):
            raise OpsFailed(f"bad request id {rid[:40]!r}")
        path = self.ops.root / "seen" / f"{rid}.json"
        got = _read_json(path)
        if got is None:
            got = {"first_seen": self.now().timestamp(), "sha256": self._bundle_sha(req)}
            _write_json(path, got)
        return got

    def _bundle_sha(self, req: Mapping[str, Any]) -> str | None:
        import hashlib

        p = self.box.incoming() / str(_args(req).get("bundle") or "")
        if not BUNDLE.match(p.name) or not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()

    def quiet_reason(self, req: Mapping[str, Any]) -> str | None:
        """T-730b (D-731): why a ``when: quiet`` update does not run now; None when it may."""
        bad = _quiet_setting(self.box.env)
        if isinstance(bad, str):
            return f"the quiet-hour setting does not read ({bad}): it waits, and expires unless the setting is mended"
        if not in_quiet_hour(self.box.env, self.now()):
            at = self.box.env.get("TB_UPDATE_QUIET_AT") or QUIET_DEFAULT_AT
            return (
                f"waits for the quiet hour ({at}, {self.box.env.get('TB_UPDATE_QUIET_HOURS') or QUIET_DEFAULT_HOURS} h)"
            )
        jobs = self._job_count()
        if jobs is None:
            return "in the quiet hour, but the box cannot say whether a job runs: it waits"
        if jobs:
            what = "1 job still runs" if jobs == 1 else f"{jobs} jobs still run"
            return f"in the quiet hour, but {what}: it waits"
        return None

    def take_quiet(self, req: Mapping[str, Any]) -> dict[str, Any] | None:
        """A ``when: quiet`` request: a result when it is refused or expired, else None (it waits, or may run)."""
        rid = str(req.get("id"))
        if req.get("action") != "update_apply":
            msg = "refused: only an update waits for the quiet hour; ask for this one without it"
            self.ops.write_result(req, False, msg, [], _now())
        else:
            seen = self._seen(req)
            queued = req.get("queued")
            first = min(float(seen.get("first_seen") or 0), float(queued) if isinstance(queued, int | float) else 1e18)
            if self.now().timestamp() - first <= QUIET_WAIT_H * 3600:
                return None
            msg = f"not run: no quiet hour with no job running came within {QUIET_WAIT_H} hours; ask again"
            self.ops.write_result(req, False, msg, [], _now(), state="expired")
        out = self.ops.result(rid)
        assert out is not None
        return out

    def run_pending(self) -> list[dict[str, Any]]:
        """Every pending request, in order, then the status. One runner at a time: a request is pending until its
        result is written, so a second runner (the timer while ``ops run --watch`` or a hand-run ``ops run`` is busy)
        would run the same backup or update again; it finds the lock taken and leaves the requests to the first."""
        self.ops.root.mkdir(parents=True, exist_ok=True)
        with open(self.ops.root / ".runner.lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return []
            try:
                done = []
                for req in self.ops.pending():
                    res = self._one(req)
                    if res is None:
                        continue  # T-730b (D-731): it waits for the quiet hour; the status says why
                    self.audit(res)
                    done.append(res)
                if any(r.get("action") == "update_apply" and r.get("state") in ("done", "failed") for r in done):
                    for res in self._supersede():
                        self.audit(res)
                        done.append(res)
                self.write_status()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        return done

    def _one(self, req: Mapping[str, Any]) -> dict[str, Any] | None:
        """One pending request: its result, or None while a quiet update waits (D-731)."""
        args = _args(req)
        if "when" not in args or self.ops.marker(str(req.get("id"))).is_file():
            return self.close_stale(req) or self.run_one(req)
        if args.get("when") != "quiet":
            # an update asked for "later" in any other words never runs at once (the plain path checks no job)
            msg = f"refused: when is {str(args.get('when'))[:20]!r}; it is 'quiet' or left out. Ask again"
            self.ops.write_result(req, False, msg, [], _now())
            return self.ops.result(str(req.get("id")))
        res = self.take_quiet(req)
        if res is not None:
            return res
        if self.quiet_reason(req) is not None:
            return None
        seen = self._seen(req)
        if seen.get("sha256") != self._bundle_sha(req):
            msg = "refused: the staged bundle changed since the update was asked for; check it and ask again"
            self.ops.write_result(req, False, msg, [], _now())
            return self.ops.result(str(req.get("id")))
        return self.run_one(req)

    def _supersede(self) -> list[dict[str, Any]]:
        """D-731: an update that ran (now, or in a quiet hour) closes the quiet updates still waiting: none is
        applied again on its own. The person asks again for one they still want."""
        out = []
        for req in self.ops.pending():
            if req.get("action") == "update_apply" and _args(req).get("when") == "quiet":
                if self.ops.marker(str(req.get("id"))).is_file():
                    continue
                msg = "superseded: another update ran on this box; ask again if this one is still wanted"
                self.ops.write_result(req, False, msg, [], _now(), state="superseded")
                if (res := self.ops.result(str(req.get("id")))) is not None:
                    out.append(res)
        return out

    def close_stale(self, req: Mapping[str, Any]) -> dict[str, Any] | None:
        """A request that started and was cut off, or that waited too long, gets a result without running: an
        update or a backup is never started again without the person asking again (and confirming again)."""
        rid = str(req.get("id"))
        if self.ops.marker(rid).is_file():
            begun = (_read_json(self.ops.marker(rid)) or {}).get("started") or ""
            msg = "interrupted: the runner stopped while this ran (a restart or a stop); it is not run again"
            self.ops.write_result(req, False, msg, [], str(begun), state="interrupted")
        else:
            queued = req.get("queued")
            if not isinstance(queued, int | float) or time.time() - queued <= MAX_AGE_MIN * 60:
                return None
            msg = f"not run: asked more than {MAX_AGE_MIN} minutes before the runner reached it; ask again"
            self.ops.write_result(req, False, msg, [], _now(), state="expired")
        out = self.ops.result(rid)
        assert out is not None
        return out

    def audit(self, res: Mapping[str, Any]) -> None:
        """On a site box, each finished request is a ``console.ops`` event in the box's audit chain, written inside
        the orchestrator as ``update.py`` does (the console writes the request's event; inline, also the result's).
        Best effort: the result file stays either way."""
        if self.box.kind != "compose":
            return
        from tools.trialbox.update import ComposeBox

        detail = {"action": f"{res.get('action')}.done", "request": res.get("id"), "ok": bool(res.get("ok")),
                  "state": res.get("state"), "by": res.get("by")}  # fmt: skip
        code = (
            "import json, sys\nfrom tb_common.audit_writer import open_audit\n"
            "open_audit().append('console.ops', actor='trialbox-ops', detail=json.loads(sys.argv[1]))\n"
        )
        argv = [*ComposeBox(self.box.deploy).compose, "exec", "-T", "orchestrator", "python", "-c", code,
                json.dumps(detail)]  # fmt: skip
        with contextlib.suppress(Exception):
            self.box.run(argv, 120)

    def run_one(self, req: Mapping[str, Any]) -> dict[str, Any]:
        started = _now()
        action = str(req.get("action"))
        _write_json(self.ops.marker(str(req.get("id"))), {"id": req.get("id"), "action": action, "started": started})
        try:
            if action not in ACTIONS:
                raise OpsFailed(f"unknown action {action!r}")
            if action in COMPOSE_ONLY and self.box.kind != "compose":
                raise OpsFailed("this runs on a site box only (the host's docker compose)")
            fn = cast(Callable[[Mapping[str, str]], tuple[str, list[str]]], getattr(self, f"do_{action}"))
            summary, lines = fn(dict(req.get("args") or {}))
            ok = True
        except Exception as exc:  # every failure is a result the console shows, never a crash of the timer
            summary, lines, ok = f"{type(exc).__name__}: {exc}"[:300], [], False
        self.ops.write_result(req, ok, summary, lines, started)
        with contextlib.suppress(OSError):
            self.ops.marker(str(req["id"])).unlink()
        out = self.ops.result(str(req["id"]))
        assert out is not None
        return out

    # -------------------------------------------------------------------------------------------- actions
    def do_backup(self, args: Mapping[str, str]) -> tuple[str, list[str]]:
        targets = self.box.targets()
        if not targets:
            raise OpsFailed("no TB_BACKUP_TARGETS (the NAS share, a USB disk ...): RUNBOOK §5")
        pub = self.box.public_key()
        if not pub.is_file():
            raise OpsFailed("no backup key yet: trialbox backup-keygen with hospital IT (RUNBOOK §5)")
        if self.box.kind == "compose" and args.get("mode") == "running":
            return self._backup_running()
        if self.box.kind == "compose":
            from tools.trialbox.update import ComposeBox

            # a request without ``mode`` was queued by an older console, which confirmed a stop: it keeps the quiet
            # box, but never stops the services under a running job (D-455, F-03): the person asks again
            jobs = ComposeBox(self.box.deploy).running_jobs()
            if jobs != 0:  # D-455 (M2): a count that could not be taken is a refusal too, never a stop
                what = "the jobs could not be counted" if jobs is None else f"{jobs} job(s) running or queued"
                raise OpsFailed(f"not run: {what}, and this backup would stop the services under them; ask again on "
                                "the console (its Back up now keeps the services running)")  # fmt: skip
            work = self.box.deploy / "updates"
            work.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="ops-backup-", dir=work) as tmp:
                os.chmod(tmp, 0o700)
                cb = ComposeBox(self.box.deploy)
                where = cb.backup(cast(Any, None), Path(tmp))
                # ``backup`` leaves the services stopped on success (the update path starts them in its restart
                # step, and starts them itself when it fails); here nothing follows, so they start now
                cb.resume(cast(Any, None))
            files = [newest.name for t in targets if (newest := _newest_backup(t)) is not None]
            return f"backup written to {where}", files
        from tools.trialbox import backup as bkp

        keep = int(self.box.env.get("TB_BACKUP_KEEP") or 14)
        written = bkp.backup(targets, pub, env=self.box.env, dirs=bkp.layout(self.box.env), keep=keep)
        return f"backup written: {written[0].name} to {len(written)} targets", [str(p) for p in written]

    def _backup_running(self) -> tuple[str, list[str]]:
        """The console's "Back up now" on a site box (D-455): the nightly's snapshot backup, under its lock and
        recorded like it (``backup-last.json``, ``backup.done``), with nothing paused or stopped and no pgBackRest."""
        from tools.trialbox import backup_schedule as bsch

        try:
            _cfg, _ops, res = bsch.run_backup(self.box.deploy, quiesce="off", with_pgbackrest=False, wait=False)
        except bsch.BackupBusy as exc:
            raise OpsFailed(f"not run: {exc} (the nightly backup is running)") from exc
        if not res["ok"]:
            raise OpsFailed("; ".join(res["errors"])[:280])
        f = res["file"]
        lim = (res.get("point_in_time") or {}).get("limits") or {}
        lines = [c["path"] for c in f["copies"]]
        lines += [f"step limit {k}: {'none (size unknown)' if v is None else f'{v:.0f} s'}" for k, v in lim.items()]
        return f"backup written: {f['name']} to {len(f['copies'])} targets; no service was stopped", lines

    def _image(self) -> str:
        return self.box.env.get("TB_IMAGE") or "trialbox-py:1.0.0"

    def _check(self, f: Path) -> dict[str, Any]:
        """``backup.check`` of one file: in this process on a local box; on a site box in a one-off trialbox-py
        container without network (the host's python3 has no zstandard or cryptography), the file read-only."""
        if self.box.kind != "compose":
            from tools.trialbox import backup as bkp

            try:
                return bkp.check(f)
            except bkp.BackupError as exc:
                raise OpsFailed(str(exc)) from exc
        argv = ["docker", "run", "--rm", "--network", "none", "-v", f"{f.parent}:/b:ro", self._image(),
                "python", "-m", "tools.trialbox", "backup-check", f"/b/{f.name}"]  # fmt: skip
        out = self.box.run(argv, 3600)
        try:
            return dict(json.loads(out[out.index("{") :]))
        except ValueError as exc:
            raise OpsFailed(out.strip()[-300:]) from exc

    def do_backup_check(self, args: Mapping[str, str]) -> tuple[str, list[str]]:
        lines: list[str] = []
        bad: list[str] = []
        shas: set[tuple[str, str]] = set()
        newest_name = ""
        targets = self.box.targets()
        if not targets:
            raise OpsFailed("no TB_BACKUP_TARGETS (the NAS share, a USB disk ...): RUNBOOK §5")
        for t in targets:
            f = _newest_backup(t)
            if f is None:
                bad.append(f"{t}: no backup")
                continue
            newest_name = max(newest_name, f.name)
            try:
                c = self._check(f)
            except (OSError, OpsFailed) as exc:
                bad.append(f"{t.name}/{f.name}: {exc}")
                continue
            shas.add((f.name, c["sha256"]))
            lines.append(f"{t}: {f.name}: complete, {c['chunks']} chunks, {c['bytes']} bytes, made {c['created_at']}")
        names = {n for n, _ in shas}
        if len(names) == 1 and len(shas) > 1:
            bad.append("the copies of the newest backup differ between targets")
        elif len(names) > 1:  # a target that missed the newest backup is stale: the check fails
            bad.append("the targets' newest backups are not the same file (one target missed a backup)")
        if bad:
            raise OpsFailed("; ".join(bad))
        return f"newest backup {newest_name} complete in every target (content needs the key: backup-verify)", lines

    def _bundle(self, args: Mapping[str, str]) -> Path:
        name = str(args.get("bundle") or "")
        p = self.box.incoming() / name
        if not BUNDLE.match(name) or not p.is_file():
            raise OpsFailed(f"no staged bundle {name!r} in {self.box.incoming()}")
        return p

    def do_update_check(self, args: Mapping[str, str]) -> tuple[str, list[str]]:
        source = args.get("from")
        if source not in (None, "", "stick"):
            raise OpsFailed(f"refused: from is {str(source)[:20]!r}; it is 'stick' or left out. Ask again")
        copied, fresh = self._take_from_stick(str(args.get("bundle") or "")) if source == "stick" else ("", False)
        p = self._bundle(args)
        try:
            out = self.box.run(["sh", str(ROOT / "tools" / "apply_update.sh"), str(p), "--dry-run"], 1800)
        except Exception:
            if fresh:  # a bundle this check copied from the stick and the verifier refused does not stay on the box
                with contextlib.suppress(OSError):
                    p.unlink()
            raise
        lines = ([copied] if copied else []) + out.strip().splitlines() + self._keep_note(p)
        return f"{p.name}: signature and every file verified; nothing was changed", lines

    def _take_from_stick(self, name: str) -> tuple[str, bool]:
        """10K-7 (D-1363): the bundle ``name`` copied from the update stick into the incoming folder, where verify and
        apply read it. Only a regular file of a bundle's name directly on the stick (never a link: the stick is
        anyone's), copied under a temporary name and renamed when whole; a different file of that name already on
        the box is refused, the same one is kept. The stick is only read. Returns the line to show and whether this
        call made the copy."""
        if not BUNDLE.match(name):
            raise OpsFailed(f"refused: {name[:60]!r} is not a bundle's name (a .tar)")
        src = self.box.stick() / name
        try:
            fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        except OSError as exc:
            raise OpsFailed(f"no bundle {name!r} on the update stick ({self.box.stick()}): is it inserted?") from exc
        inc = self.box.incoming()
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise OpsFailed(f"refused: {name!r} on the stick is not a regular file")
            inc.mkdir(parents=True, exist_ok=True)
            dest, tmp = inc / name, inc / f".{name}.part"
            if dest.exists() or dest.is_symlink():
                if dest.is_symlink() or not dest.is_file():
                    raise OpsFailed(f"refused: {dest} is not a regular file")
                if dest.stat().st_size == st.st_size and _sha_file(dest) == _sha_stream(fh):
                    return f"{name}: the same bundle is already on the box ({inc}); not copied again", False
                raise OpsFailed(f"refused: a different bundle named {name} is already on the box ({inc}); "
                                "remove it there or rename the one on the stick, then ask again")  # fmt: skip
            free = shutil.disk_usage(inc).free
            if free < st.st_size * STICK_MARGIN:
                raise OpsFailed(f"not copied: the bundle needs {st.st_size * STICK_MARGIN / 1e9:.2f} GB free in {inc}, "
                                f"free {free / 1e9:.2f} GB")  # fmt: skip
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()
            with open(tmp, "xb") as out:
                shutil.copyfileobj(fh, out, 1 << 20)
                out.flush()
                os.fsync(out.fileno())
        tmp.replace(dest)
        return f"{name}: copied from the update stick ({self.box.stick()}) into {inc}", True

    def _keep_note(self, p: Path) -> list[str]:
        """10K-7 (D-1363): the verified bundle's Japanese release note and change-impact sheet, kept for the console
        (``<ops>/notes/<bundle>.json``, with the file's size and time: a bundle replaced since shows no note)."""
        from tools import release_note

        got = release_note.read_from_bundle(p)
        st = p.stat()
        _write_json(self.ops.notes / f"{p.name}.json", {"bundle": p.name, "bytes": st.st_size, "mtime": st.st_mtime,
                                                         "verified_at": _now(), **got})  # fmt: skip
        return [f"warning: {w}" for w in got["warnings"]]

    def apply_limit(self) -> int | None:
        """T-695 (D-752, F-09): the update's limit from the databases' size (``ComposeBox.apply_limit_s``); a local
        box keeps the 3 h of before."""
        from tools.trialbox.update import APPLY_FIXED_S, ComposeBox

        return ComposeBox(self.box.deploy).apply_limit_s() if self.box.kind == "compose" else APPLY_FIXED_S

    def do_update_apply(self, args: Mapping[str, str]) -> tuple[str, list[str]]:
        p = self._bundle(args)
        out = self.box.run(["sh", str(ROOT / "tools" / "apply_update.sh"), str(p)], self.apply_limit())
        return f"{p.name}: applied", out.strip().splitlines()

    def do_logs_collect(self, args: Mapping[str, str]) -> tuple[str, list[str]]:
        from tools.trialbox import logs as tb_logs

        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = tb_logs.main_action("collect", self.box.deploy, None)
        lines = (buf.getvalue() + err.getvalue()).strip().splitlines()
        if code != 0:
            raise OpsFailed("; ".join(lines)[-300:] or f"exit {code}")
        return lines[-1] if lines else "collected", lines

    def do_network_sheet(self, args: Mapping[str, str]) -> tuple[str, list[str]]:
        if self.box.kind == "compose":  # the sheet's tool needs PyYAML: the trialbox-py image, no network
            out_dir = self.ops.network
            out_dir.mkdir(parents=True, exist_ok=True)
            argv = ["docker", "run", "--rm", "--network", "none", "--user", "0", "-v",
                    f"{self.box.deploy}:/app/deploy:ro", "-v", f"{out_dir}:/out", self._image(), "python", "-m",
                    "tools.network_sheet", "--env", "/app/deploy/.env", "--out", "/out/network-sheet"]  # fmt: skip
            lines = self.box.run(argv, 600).strip().splitlines()
            return "network sheet written in 3 languages", lines
        from tools import network_sheet as ns

        env_path = self.box.deploy / ".env"
        env = ns.read_env(env_path) if env_path.is_file() else None
        written = ns.write(self.ops.network / "network-sheet", list(ns.FILES), env, root=ROOT)
        return f"network sheet written in {len(ns.LANGS)} languages", [p.name for p in written]

    # -------------------------------------------------------------------------------------------- status
    def write_status(self) -> dict[str, Any]:
        st = snapshot(self.box)
        st["notes"] = self._notes(st.get("incoming") or [])  # 10K-7 (D-1363)
        st["quiet"] = quiet_facts(self.box.env)
        st["waiting"] = [  # T-730b (D-731): the updates that wait for the quiet hour, and why
            {"id": r.get("id"), "action": r.get("action"), "by": r.get("by", ""), "at": r.get("at"),
             "bundle": _args(r).get("bundle"), "why": self.quiet_reason(r) or "runs in the next round"}
            for r in self.ops.pending()
            if _args(r).get("when") == "quiet" and r.get("action") == "update_apply"
        ]  # fmt: skip
        _write_json(self.ops.root / "status.json", st)
        return st

    def _notes(self, incoming: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """The kept notes of the bundles in the incoming folder now, each only while the file is the one verified."""
        out: dict[str, Any] = {}
        for b in incoming:
            name = str(b.get("name") or "")
            rec = _read_json(self.ops.notes / f"{name}.json") if BUNDLE.match(name) else None
            with contextlib.suppress(OSError):
                now = (self.box.incoming() / name).stat()
                if rec and rec.get("bytes") == now.st_size and rec.get("mtime") == now.st_mtime:
                    out[name] = {k: rec.get(k) for k in ("bundle_id", "release_seq", "note_ja", "impact", "warnings",
                                                          "verified_at")}  # fmt: skip
        return out


def _sha_stream(fh: Any) -> str:
    """The sha256 of an open file from its start; the file is put back at its start."""
    import hashlib

    h = hashlib.sha256()
    fh.seek(0)
    while block := fh.read(1 << 20):
        h.update(block)
    fh.seek(0)
    return h.hexdigest()


def _sha_file(p: Path) -> str:
    with p.open("rb") as fh:
        return _sha_stream(fh)


def quiet_facts(env: Mapping[str, str]) -> dict[str, Any]:
    """10K-7: the quiet hour as the console shows it (D-731's settings), and the setting that does not read."""
    got = _quiet_setting(env)
    return {"at": (env.get("TB_UPDATE_QUIET_AT") or QUIET_DEFAULT_AT).strip(),
            "hours": (env.get("TB_UPDATE_QUIET_HOURS") or QUIET_DEFAULT_HOURS).strip(),
            "zone": (env.get("TB_TZ") or "").strip(), "wait_h": QUIET_WAIT_H,
            "bad": got if isinstance(got, str) else ""}  # fmt: skip


def stick_listing(box: Box) -> dict[str, Any]:
    """10K-7 (D-1363): the bundles directly on the update stick (regular files of a bundle's name; a link is not
    listed), and whether the vendor's ``.sha256`` sidecar is beside each. No file on the stick is opened here."""
    root = box.stick()
    out: dict[str, Any] = {"path": str(root), "mounted": root.is_dir(), "bundles": []}
    if not out["mounted"]:
        return out
    with contextlib.suppress(OSError):
        for p in sorted(root.iterdir())[:50]:
            with contextlib.suppress(OSError):
                st = p.lstat()
                if BUNDLE.match(p.name) and stat.S_ISREG(st.st_mode):
                    out["bundles"].append({"name": p.name, "bytes": st.st_size, "at": _mtime(p),
                                           "sidecar": (root / f"{p.name}.sha256").is_file()})  # fmt: skip
    return out


def _newest_backup(target: Path) -> Path | None:
    files = sorted((p for p in target.glob("trialbox-*.tbbak") if BACKUP_FILE.match(p.name)),
                   key=lambda p: BACKUP_FILE.match(p.name).group(1))  # type: ignore[union-attr]  # fmt: skip
    return files[-1] if files else None


def _stamp_iso(name: str) -> str:
    m = BACKUP_FILE.match(name)
    if not m:
        return ""
    return datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat(timespec="seconds")


def _version() -> str:
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return m.group(1) if m else "-"


def _history(updates: Path) -> list[dict[str, Any]]:
    f = updates / "history.jsonl"
    rows: list[dict[str, Any]] = []
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines()[-400:]:
            with contextlib.suppress(ValueError):
                d = json.loads(line)
                if isinstance(d, dict):
                    rows.append(d)
    return rows


def _mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(timespec="seconds")


def _disk(path: Path) -> dict[str, Any] | None:
    try:
        u = shutil.disk_usage(path)
    except OSError:
        return None
    return {"path": str(path), "total": u.total, "used": u.used, "free": u.free}


def snapshot(box: Box) -> dict[str, Any]:
    """What the console's operations screens show; no value of any secret."""
    updates = box.deploy / "updates"
    hist = _history(updates)
    applied = [h for h in hist if h.get("step") == "audited update.applied" and h.get("ok")]
    previous = applied[-2].get("bundle") if len(applied) > 1 else ""  # 10K-7: the release before the current one
    bundles: dict[str, dict[str, Any]] = {}
    for h in hist:  # one line per bundle: its last step and whether the update ended applied or rolled back
        b = str(h.get("bundle") or "")
        row = bundles.setdefault(b, {"bundle": b, "first": h.get("at"), "steps": 0})
        row.update(last=h.get("at"), step=h.get("step"), ok=bool(h.get("ok")))
        row["detail"] = str(h.get("detail") or "")[:200]
        row["steps"] += 1
        if h.get("step") == "audited update.applied":
            row["outcome"] = "applied"
        elif h.get("step") == "rollback":
            row["outcome"] = "rolled_back" if h.get("ok") else "rollback_failed"
        elif not h.get("ok") and row.get("outcome") is None:  # a step failed and no rollback line followed
            row["outcome"] = "failed"
        elif h.get("ok") and row.get("outcome") == "failed":  # the bundle was tried again
            row.pop("outcome")
    points = []
    for pj in sorted(updates.glob("*/rollback/point.json")):
        d = _read_json(pj) or {}
        dumps = d.get("dumps") or {}
        points.append(
            {
                "bundle": pj.parent.parent.name,
                "images": len(d.get("images") or {}),
                "dumps_kept": sum(1 for v in dumps.values() if Path(str(v)).is_file()),
                "at": _mtime(pj),
            }
        )
    incoming = []
    inc = box.incoming()
    if inc.is_dir():
        for p in sorted(inc.glob("*.tar")):
            if BUNDLE.match(p.name):
                incoming.append({"name": p.name, "bytes": p.stat().st_size, "at": _mtime(p)})
    targets = []
    newest = ""
    for t in box.targets():
        files = []
        if t.is_dir():
            for p in sorted(t.glob("trialbox-*.tbbak"), key=lambda p: p.name, reverse=True)[:30]:
                if BACKUP_FILE.match(p.name):
                    files.append({"name": p.name, "bytes": p.stat().st_size, "at": _stamp_iso(p.name)})
                    newest = max(newest, _stamp_iso(p.name))
        disk = _disk(t) if t.is_dir() else None
        targets.append({"path": str(t), "files": files, "reachable": t.is_dir(), "disk": disk})
    try:
        from tools.trialbox import svc_secrets

        secret_rows = [{k: v for k, v in r.items() if k in ("name", "present", "age_days", "registered", "mode")}
                       for r in svc_secrets.status(box.deploy)]  # fmt: skip
    except Exception:  # a box without the secrets folder yet
        secret_rows = []
    log_days = []
    base = box.log_dir() / "services"
    if base.is_dir():
        for day in sorted(base.iterdir(), reverse=True)[:14]:
            if day.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", day.name):
                fs = [f for f in day.iterdir() if f.is_file()]
                log_days.append({"day": day.name, "files": len(fs), "bytes": sum(f.stat().st_size for f in fs)})
    disks = [x for x in (_disk(box.deploy), _disk(Path("/var/lib/docker"))) if x is not None]
    return {
        "at": _now(),
        "box": box.kind,
        "version": {
            "trialbox": _version(),
            "bundle": applied[-1].get("bundle") if applied else "",
            "applied_at": applied[-1].get("at") if applied else "",
            "previous": previous,
        },
        "stick": stick_listing(box),
        "updates": sorted(bundles.values(), key=lambda r: str(r.get("last")), reverse=True)[:10],
        "rollback_points": points[-10:],
        "incoming": incoming,
        "backups": {
            "targets": targets,
            "newest": newest,
            "key": box.public_key().is_file(),
            "stale_hours": STALE_HOURS,
        },
        "secrets": secret_rows,
        "logs": {"days": log_days},
        "disk": disks,
        "health": health_facts(box),
    }


def health_facts(box: Box) -> dict[str, Any]:
    """T-209a (D-379): the host half of the box's health (backup age as ``backup-status`` sees it, the last key
    check, the disks, the certificate's end), for the console's health line, health mail and ``/metrics``."""
    import sys

    try:
        from tools.trialbox import backup_schedule as bsch

        cfg = bsch.config(box.deploy, box.env)
        # D-735 (review): WAL archiving's problems reach the health tile too, as the hourly backup-status sees them;
        # on a box whose only alert route is the page nobody would hear of them otherwise
        archiver = bsch._try(bsch.ComposeOps(box.deploy).archiver) if box.kind == "compose" and cfg.archive_on else None
        backup: dict[str, Any] | None = bsch.status(cfg, archiver=archiver)
    except Exception:  # a box without a backup set-up yet: the check says unknown
        backup = None
    if str(ROOT / "libs") not in sys.path:
        sys.path.insert(0, str(ROOT / "libs"))  # the host's python3 (logs.py does the same); standard library only
    from tb_common import metrics

    try:
        return metrics.host_facts(box.deploy, box.env, backup)
    except Exception as exc:  # health must report, not stop the runner's status
        return {"error": type(exc).__name__}


def prepare(ops: OpsDir, uid: int | None = SERVICE_UID) -> None:
    """The folders; ``requests/`` is writable by the console's user (uid 10001 in the image), the rest only by root.
    As a non-root user (a test, the in-process box) the folders are only made."""
    for sub, mode in (
        ("requests", 0o770),
        ("results", 0o755),
        ("running", 0o755),
        ("network", 0o755),
        ("seen", 0o755),
        ("notes", 0o755),
    ):
        d = ops.root / sub
        d.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.chmod(d, mode)
            if sub == "requests" and uid is not None:
                os.chown(d, uid, uid)


def metrics_token(deploy: Path) -> Path:
    """T-209a (D-379): ``deploy/secrets/metrics.token``, the token the monitoring overlay's scraper sends to the
    console's ``/metrics``. Made once and never printed. The folder stays 0700 (root); the file is 0444 so the two
    containers that mount it (the console, the scraper) read it under their own users."""
    d = deploy / "secrets"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    f = d / "metrics.token"
    if not f.is_file():
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(32) + "\n")
    return f


def main(action: str, deploy: Path, ops_dir: Path | None, local: bool, watch: int) -> int:
    """``trialbox ops run``: the pending requests, then the status (``--watch N``: again every N seconds);
    ``trialbox ops metrics-token``: the scraper's token for ``/metrics`` (T-209a)."""
    if action == "metrics-token":
        print(f"metrics token in {metrics_token(deploy)} (not printed)")
        return 0
    box = Box.local(deploy, os.environ) if local else Box.compose(deploy)
    ops = OpsDir(ops_dir or Path(box.env.get("TB_OPS_DIR") or deploy / "ops"))
    prepare(ops)
    runner = OpsRunner(box, ops)
    if action == "status":
        print(json.dumps(runner.write_status(), indent=1, ensure_ascii=False))
        return 0
    while True:
        for res in runner.run_pending():
            print(f"{res['id']} {res['action']}: {'ok' if res['ok'] else 'FAILED'}: {res['summary']}")
        if watch <= 0:
            return 0
        time.sleep(watch)
