"""``trialbox restore`` typed on the box's host (H-100): it runs in the backup image, as the nightly's job does.

The host's ``python3`` has neither the libraries nor the database client a restore needs, and a plain one-off
container of the box image has no hapi URL, no volume and no client either (the MVP walk's step 8). So on the host
the restore is orchestrated here, standard library only, and its work runs in one container of the release's backup
image (``TB_BACKUP_IMAGE``: the box image, restic and the database client tools), on the database network:

1. **What it reads, all from the box's own files.** ``deploy/.env`` (``launch.box_file``'s checks already passed):
   the trial database's URL (``TB_DB_URL``), the database superuser's password (``POSTGRES_PASSWORD``: the hapi
   database's owner, ``POSTGRES_USER: hapi`` in compose), the service roles' passwords as compose gives them to the
   ``db`` container, the images, the runtime and the volume folder. A caller's exported ``TB_DB_URL``,
   ``TB_HAPI_DB_URL``, ``TB_DB_ROLES_CMD``, ``TB_COMPOSE`` or ``TB_DOCKER`` changes nothing.
2. **The guards stay.** ``--yes`` (the caller's), the running services asked of compose (only ``db`` may run, D-724),
   the site, the age and the copy of a box that holds data (``backup.restore``, inside the container, unchanged).
   ``--restart`` is the person's own word to stop every service but ``db`` first; the running services are asked
   of compose again after the stop, and the restore runs only when ``db`` alone runs.
3. **The container.** The backup file's folder, the key and the box's public key read-only; the folder for the copy
   and each data volume's folder read-write (the volume's ``_data`` is moved aside within it); the service-role
   script of the box read-only. The URLs and passwords travel as ``-e NAME`` without a value (never on a command
   line); the restore runs the role script itself (``python -m tools.trialbox.box_restore roles``) over the database
   network as the superuser, with each role's password as compose gives it to the ``db`` container.
4. **After it.** Its JSON and its lines are the command's own, and so is its exit code. With ``--restart`` the
   services start again and are waited for until healthy only when the restore ended complete (exit 0) or held
   (exit 4 with ``hold: held``, D-522: the box screens nobody until a person releases it); otherwise they stay
   stopped and the command says why.
5. **Every service the box defines (H-126).** ``--restart`` starts the whole of the box's compose project, not
   only what this run stopped: a run interrupted earlier may have left services stopped that this run never saw
   running. Afterwards the full expected set (``compose config --services``, less the one-shot services) is checked
   to run and be healthy; the line names both counts (``16 of 16``) and a shortfall is exit 1, never "healthy".
   The hold on the list jobs is said either way: released by the restore, or held until a person releases it.

``--last``: the newest backup ``backup-nightly`` recorded good (``deploy/site/backup-last.json``) and found on a
target with the same size and sha256.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

DB_HOST = "db:5432"  # the database service on trialbox-net, as the nightly's job reaches it
SUPERUSER = "hapi"  # deploy/docker-compose.yml, service db: POSTGRES_USER and POSTGRES_DB
ROLES_SCRIPT = "docker/db-init/30-service-roles.sh"  # under deploy/: what compose mounts into the db container
ROLES_IN = "/in/30-service-roles.sh"
ROLES_CMD = f"python -m tools.trialbox.box_restore roles {ROLES_IN}"
#: D-378: the service roles' passwords, each as compose gives it to the db container (the workflow password, then
#: the database's, when the box file names none); the FHIR store's own role has no fallback (D-541)
ROLE_PASSWORDS = ("LAKE", "CRITERIA_COMPILER", "ADAPTER", "ORCHESTRATOR", "MAIL_GATEWAY", "GATEWAY", "CONSOLE",
                  "AUDIT_WRITER")  # fmt: skip
FHIR_PASSWORD = "TB_DB_PW_FHIR_STORE"
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
#: H-100 (F1): the engine variables taken from the box file when it names them; never from the caller
ENGINE_KEYS = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
UNPACK_FACTOR = 4  # restore_drill.UNPACK_FACTOR: the unpacked backup, about this many times the file
WAIT_S = 600  # the services' health wait after the restore (as an update's start waits, update.ComposeBox)


#: D-724 (DATA-011): the services a restore leaves running: the database it restores into, nothing that writes
#: a volume the restore renames aside
RESTORE_MAY_RUN = frozenset({"db"})
#: backup.VOLUME_ROOT: where the box's compose volumes are, inside the restore's container as on a host
VOLUME_ROOT = "/var/lib/docker/volumes/trialbox_{}/_data"
HOLD_FLAG = "screening.after_restore"  # backup.HOLD_FLAG (D-522): the hold on the list jobs a restore leaves


def _backup_error() -> type[Exception]:
    """``backup.BackupError`` where the libraries are (the restore's own refusal, as before); on the host,
    :class:`RestoreStopped` (backup.py cannot be imported by the host's python)."""
    try:
        from tools.trialbox.backup import BackupError
    except ImportError:
        return RestoreStopped
    return BackupError


def only_the_database_runs(names: list[str] | None) -> None:
    if names is None:
        raise _backup_error()(
            "the restore cannot tell which services run (docker compose did not answer): stop every service but db "
            "(docker compose stop), then run the restore again with --services-stopped"
        )
    others = sorted(set(names) - RESTORE_MAY_RUN)
    if others:
        raise _backup_error()(
            f"these services are running: {', '.join(others)}. A restore moves their folders aside, and what they "
            f"write meanwhile is lost: stop them first (docker compose stop {' '.join(others)}; keep db running), "
            "run the restore, then start them. Nothing was changed"
        )


class RestoreStopped(RuntimeError):
    """The restore did not start (or the services were not started again): said, nothing more was changed."""


def _unset(v: str | None) -> bool:
    return not (v or "").strip()


def _compose_value(env: Mapping[str, str], *names: str) -> str:
    """``${A:-${B:-${C}}}`` as compose reads it: the first of ``names`` the box file sets to a non-empty value."""
    return next((env[n] for n in names if not _unset(env.get(n))), "")


def job_db_env(env: Mapping[str, str]) -> dict[str, str]:
    """The database URLs of the box's backup job (``update.ComposeBox._backup_container``), from the box file
    ``env``: the trial database's own URL and the hapi database as its owner, the cluster's superuser. The password
    is quoted for the URL (a ``@`` or ``/`` in it stays the password)."""
    pw = env.get("POSTGRES_PASSWORD", "")
    return {
        "TB_DB_URL": env.get("TB_DB_URL", ""),
        "TB_HAPI_DB_URL": f"postgresql://{SUPERUSER}:{quote(pw, safe='')}@{DB_HOST}/{SUPERUSER}",
    }


def role_env(env: Mapping[str, str]) -> dict[str, str]:
    """Each service role's password as compose gives it to the ``db`` container (deploy/docker-compose.yml): the
    role script run without them would clear the roles' passwords (RUNBOOK §5)."""
    out = {
        f"TB_DB_PW_{n}": _compose_value(env, f"TB_DB_PW_{n}", "POSTGRES_WF_PASSWORD", "POSTGRES_PASSWORD")
        for n in ROLE_PASSWORDS
    }
    out[FHIR_PASSWORD] = env.get(FHIR_PASSWORD, "")
    return out


def last_good(deploy: Path, env: Mapping[str, str]) -> Path:
    """``--last``: the backup ``backup-nightly`` recorded good, on a target of the box, with its size and sha256."""
    from tools.trialbox import backup_schedule as bs

    cfg = bs.config(deploy, env, process_env=False)
    try:
        rec = json.loads(cfg.last_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {}
    good = bs.recorded_good(cfg.targets, rec.get("good_file"))
    if good is None:
        raise RestoreStopped(f"--last: no good backup recorded in {cfg.last_file} is on a target of this box "
                             "(TB_BACKUP_TARGETS): name the backup file instead. Nothing was changed")  # fmt: skip
    return Path(good["path"])


class BoxRestore:
    """The restore of a box, typed on its host. ``run`` (the box's commands) and ``call`` (the restore container,
    its output passed through) are the tests' seams; the box's settings are its ``deploy/.env`` alone."""

    def __init__(self, deploy: Path, run: Callable[..., str] | None = None,
                 call: Callable[..., tuple[int, str]] | None = None) -> None:  # fmt: skip
        from tools.trialbox import backup_schedule as bs
        from tools.trialbox.backup_schedule import absolute

        self.deploy = absolute(deploy)
        # the box's own commands run with a clean environment (F1): the box file's settings, never the caller's
        self.ops = bs.ComposeOps(self.deploy, run or self._run)
        self.box = self.ops.box
        self.env = self.box.env  # deploy/.env, read by the box (launch.box_file checked it first)
        # the runtime and compose are the box file's or the defaults, never the caller's (launch.run_in_image)
        self.box.docker = shlex.split(self.env.get("TB_DOCKER") or "docker")
        self.box.compose = shlex.split(self.env.get("TB_COMPOSE") or "") or [
            *self.box.docker, "compose", "--project-directory", str(self.deploy)]  # fmt: skip
        self.call = call or (lambda argv, values: _call(argv, values, self.engine_env()))

    # ------------------------------------------------------------------------------------------- the engine
    def engine_env(self) -> dict[str, str]:
        """H-100 (F1): the whole environment of compose and of the container engine. The engine's own needs: PATH
        (this process's: sudo's secure_path for the documented command) and HOME (the user's own folder, where the
        engine keeps its client settings); then only the engine variables the box file names. A caller's exported
        ``COMPOSE_PROJECT_NAME``, ``COMPOSE_FILE``, ``COMPOSE_PROFILES``, ``DOCKER_HOST``, ``DOCKER_CONTEXT`` ... never
        reach them: compose reads the project's name and files from ``deploy/.env`` itself (``--project-directory``)."""
        import pwd

        try:
            home = pwd.getpwuid(os.geteuid()).pw_dir
        except KeyError:
            home = "/root"
        env = {"PATH": os.environ.get("PATH") or SAFE_PATH, "HOME": home}
        env.update({k: self.env[k] for k in ENGINE_KEYS if self.env.get(k)})
        return env

    def _run(self, argv: Sequence[str], stdin_file: Path | None = None, stdout_file: Path | None = None,
             env: dict[str, str] | None = None, timeout: float | None = None) -> str:  # fmt: skip
        """``update.run_cmd`` with the clean environment of :meth:`engine_env` in place of the caller's."""
        from tools.trialbox import procgroup
        from tools.trialbox.update import UpdateFailed

        fin = stdin_file.open("rb") if stdin_file else None
        fout = (
            os.fdopen(os.open(stdout_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") if stdout_file else None
        )
        try:
            r = procgroup.run(list(argv), stdin=fin, stdout=fout or subprocess.PIPE, stderr=subprocess.PIPE,
                              env={**self.engine_env(), **(env or {})}, timeout=timeout)  # fmt: skip
        finally:
            for f in (fin, fout):
                if f:
                    f.close()
        if r.returncode != 0:
            err = (r.stderr or b"").decode(errors="replace").strip()[-600:]
            raise UpdateFailed(f"{shlex.join(list(argv)[:8])} ... exit {r.returncode}: {err}")
        return "" if fout else (r.stdout or b"").decode(errors="replace")

    # ------------------------------------------------------------------------------------------- the services
    def running(self) -> list[str] | None:
        return self.box.running_services()

    def stop_all_but_db(self, stopped: list[str]) -> None:
        """``--restart``: every service but db stopped; ``stopped`` holds them as they go (for the state line)."""
        names = self.running()
        if names is None:
            raise RestoreStopped("compose cannot say which services run: --restart stops nothing it cannot see. "
                                 "Nothing was changed")  # fmt: skip
        others = sorted(set(names) - RESTORE_MAY_RUN)
        if others:
            stopped.extend(others)  # before the stop: a stop that fails part-way may have stopped any of them
            self.box.run(self.box._c("stop", *others), timeout=900)
            print(f"restore: stopped {', '.join(others)} (--restart); db keeps running", file=sys.stderr)

    def expected(self, stopped: Sequence[str]) -> set[str]:
        """H-126: the services the box's compose defines (its files and profiles, ``config --services``), less the
        one-shot ones (``restart: "no"``: they run to the end and exit); with ``db`` and whatever this run stopped,
        whatever compose says. Never the set that happened to run before (an interrupted run may have stopped some)."""
        names = set(self.box.run(self.box._c("config", "--services"), timeout=120).split())
        try:  # the files as written: no value of deploy/.env is put into this output
            spec = json.loads(self.box.run(self.box._c("config", "--no-interpolate", "--format", "json"), timeout=120))
        except ValueError:
            spec = {}
        services = spec.get("services") if isinstance(spec, dict) else None
        for name, svc in (services if isinstance(services, dict) else {}).items():
            if isinstance(svc, dict) and str(svc.get("restart", "")).strip().strip("\"'") == "no":
                names.discard(name)
        return names | RESTORE_MAY_RUN | set(stopped)

    def healthy(self, expected: set[str]) -> tuple[set[str], set[str]]:
        """H-126: of ``expected``, the services that run (``running``, not restarting or paused) and are healthy
        (no health check, or ``healthy``), asked of compose; and the rest."""
        runs = set(self.box.run(self.box._c("ps", "--status", "running", "--services"), timeout=120).split())
        fmt = "{{.Service}} {{.Health}}"
        out = self.box.run(self.box._c("ps", "--status", "running", "--format", fmt), timeout=120)
        sick = {f[0] for f in (ln.split() for ln in out.splitlines()) if len(f) > 1 and f[1] != "healthy"}
        ok = (expected & runs) - sick
        return ok, expected - ok

    def start_and_wait(self, stopped: Sequence[str], whole: bool = True) -> tuple[set[str], set[str], str]:
        """H-126 (in place of H-100's F6): after a restore that ran (``whole``), every service the box defines,
        started and waited for until healthy, as an update starts the box (``up -d --wait``); then the full expected
        set checked, whatever the wait said: (healthy, not healthy, the wait's error). LR-14: after a restore refused
        before any change, only what this run stopped (and db): an earlier run may have left the rest stopped on
        data that is not as it was. An interrupt is raised to the caller."""
        if not whole:
            want: set[str] | None = set(stopped) | RESTORE_MAY_RUN
        else:
            try:
                want = self.expected(stopped)
            except Exception as e:  # started all the same; never said healthy
                want, why = None, str(e)[-300:] or type(e).__name__
        err = ""
        try:
            if whole or stopped:
                self.box.run(self._up(stopped, whole), timeout=WAIT_S + 120)
        except Exception as e:  # a service that did not come up: counted below, and said
            err = str(e)[-400:] or type(e).__name__
        if want is None:
            raise RestoreStopped(f"compose cannot say which services the box defines ({why}): they were started, "
                                 "whether each runs and is healthy is not known")  # fmt: skip
        ok, short = self.healthy(want)
        return ok, short, err

    def _up(self, stopped: Sequence[str], whole: bool) -> list[str]:
        """The start: the whole project, or (LR-14) only the services named, without their dependencies."""
        names = [] if whole else ["--no-deps", *stopped]
        return self.box._c("up", "-d", "--pull", self.pull(), "--wait", "--wait-timeout", str(WAIT_S), *names)

    def pull(self) -> str:
        """OCR 1470-2 (D-176): the start pulls as the update's start does (``update.ComposeBox._pull``): every image
        from the bundle (``never``) unless the box file says ``TB_INSTALL_PULL=missing``. The box file's word, never
        the caller's; any other value is ``never``."""
        return "missing" if (self.env.get("TB_INSTALL_PULL") or "").strip() == "missing" else "never"

    def state(self) -> str:
        """What compose says runs now (asked, never assumed)."""
        try:
            names = self.running()
        except Exception:
            names = None
        return "compose cannot say which services run" if names is None else (
            "running: " + (", ".join(sorted(names)) or "none"))  # fmt: skip

    def audit(self, detail: dict[str, Any]) -> None:
        """The host's own event of a restore it could not finish (F3): through the orchestrator, else kept in
        deploy/site/backup-audit-pending.jsonl for the next run (``ComposeOps.audit``)."""
        try:
            self.ops.audit("backup.restore_failed", {"where": "host", **detail})
        except Exception as e:
            print(f"restore: the audit event could not be written or kept ({type(e).__name__})", file=sys.stderr)

    # ------------------------------------------------------------------------------------------- the container
    def volumes_root(self) -> Path:
        return Path(self.env.get("TB_DOCKER_VOLUMES") or "/var/lib/docker/volumes")

    def container(self, a: Any, file: Path, work: Path, sha: str) -> tuple[list[str], dict[str, str]]:
        """The restore's one container and the values its ``-e NAME`` options take (never on its command line)."""
        from tools.trialbox.backup_schedule import absolute
        from tools.trialbox.update import BACKUP_VOLUMES

        image = self.env.get("TB_BACKUP_IMAGE") or "trialbox-backup:1.0.0"
        file, key = absolute(file), absolute(a.key)
        pub, keep_to, refdata = absolute(a.public), absolute(a.keep_to), absolute(a.refdata)
        values = {**job_db_env(self.env), **role_env(self.env), "TB_DB_ROLES_CMD": ROLES_CMD, "TMPDIR": str(work)}
        kek = ("TB_KEK_FILE", "TB_KEK_PASSPHRASE") if a.restic_from_box else ()  # only where the KEK is opened
        for k in ("TB_SITE_ID", "TB_ENV", "TB_TZ", "TB_REHEARSAL", *kek):
            if k in self.env:
                values[k] = self.env[k]
        mounts: list[str] = []
        seen: set[str] = set()

        def bind(src: Path, dst: Path | str, ro: bool) -> None:
            if str(dst) not in seen:
                seen.add(str(dst))
                mounts.extend(["-v", f"{src}:{dst}" + (":ro" if ro else "")])

        bind(file.parent, file.parent, True)  # the file, its sha256 sidecar and a restic repository beside it
        bind(key, key, True)
        bind(work, work, False)  # the restore's scratch on the host (TMPDIR), its space checked first
        if pub.is_file():
            bind(pub, pub, True)
        keep_to.mkdir(parents=True, exist_ok=True)
        bind(keep_to, keep_to, False)
        if refdata.is_dir():
            bind(refdata, refdata, True)
        shares = [absolute(s) for s in a.restic_share]
        for s in shares:
            bind(s, s, True)
        roles = self.deploy / ROLES_SCRIPT
        if roles.is_file():
            bind(roles, ROLES_IN, True)
        dirs: list[str] = []
        given: dict[str, Path] = {}
        for pair in a.dir:  # --dir name=path (the host part among them): its folder, moved aside within its parent
            name, _, path = str(pair).partition("=")
            if not name or not path:
                raise RestoreStopped(f"bad directory {pair!r}: use name=path. Nothing was changed")
            given[name] = absolute(Path(path))
            given[name].parent.mkdir(parents=True, exist_ok=True)
            bind(given[name].parent, given[name].parent, False)
            dirs += ["--dir", f"{name}={given[name]}"]
        root = self.volumes_root()
        for name, vol in BACKUP_VOLUMES.items():  # each volume's own folder: its _data is moved aside within it
            folder = root / f"trialbox_{vol}"
            if name not in given and folder.is_dir():
                inside = Path(VOLUME_ROOT.format(vol)).parent
                bind(folder, inside, False)
                dirs += ["--dir", f"{name}={inside / '_data'}"]
        if a.restic_from_box:  # D-968: the box's restic.key under its unsealed KEK, read-only
            kek_dir = self.env.get("TB_KEK_HOST_DIR") or "/run/trialbox"
            bind(Path(kek_dir), "/run/trialbox", True)
            values["TB_SECRETS_DIR"] = str(Path(VOLUME_ROOT.format("tb-secrets")))
        names = sorted(values)
        argv = [*self.box.docker, "run", "--rm", "-i", "--pull", "never", "--network", "trialbox-net", "--user", "0",
                "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "FOWNER", "--cap-add", "DAC_OVERRIDE",
                "--security-opt", "no-new-privileges:true", "-e", "PYTHONDONTWRITEBYTECODE=1",
                *[x for n in names for x in ("-e", n)], *mounts, image,
                "python", "-m", "tools.trialbox", "restore", str(file), "--key", str(key), "--yes",
                "--services-stopped", "--expect-sha256", sha, "--public", str(pub), "--keep-to", str(keep_to),
                "--refdata", str(refdata), *dirs]  # fmt: skip
        flags = (("--no-copy", a.no_copy), ("--other-site", a.other_site), ("--older-ok", a.older_ok),
                 ("--restic-from-box", a.restic_from_box))  # fmt: skip
        argv += [x for x, on in flags if on]
        for s in shares:
            argv += ["--restic-share", str(s)]
        return argv, values

    # ------------------------------------------------------------------------------------------- the command
    def _state_line(self, stopped: Sequence[str], data: str, nxt: str) -> None:
        """H-100 (F2, F3): one line, never a box left stopped without it: what runs (asked of compose), what the
        restore left in the data, and the next command."""
        stop = f"; stopped by --restart: {', '.join(stopped)}" if stopped else ""
        print(f"restore: the box now: {self.state()}{stop}; the data: {data}; next: {nxt} (RUNBOOK §5)",
              file=sys.stderr)  # fmt: skip

    def _say(self, stopped: Sequence[str], data: str, nxt: str, detail: dict[str, Any] | None = None) -> bool:
        """The audit event (``detail``) and the state line, said whatever signal comes next (OCR 1470-1, the walk's
        double Ctrl-C): a second signal while compose is asked ends the asking, never the line. False: not asked."""
        try:
            if detail is not None:
                self.audit(detail)
            self._state_line(stopped, data, nxt)
            return True
        except (KeyboardInterrupt, HostInterrupted):
            old = _ignore_signals()
            try:
                stop = f"; stopped by --restart: {', '.join(stopped)}" if stopped else ""
                kept = "" if detail is None else " (interrupted again: the audit event may not be kept)"
                print(f"restore: the box now: not asked (interrupted again){stop}; the data: {data}; next: {nxt} "
                      f"(RUNBOOK §5){kept}", file=sys.stderr)  # fmt: skip
            finally:
                _put_back_signals(old)
            return False

    def _start_line(self, stopped: Sequence[str]) -> str:
        return shlex.join(self.box._c("up", "-d", "--no-deps", *stopped)) if stopped else "nothing to start"

    def restore(self, a: Any) -> int:
        with self.lock():  # review R7: one restore at a time; what a killed one left is swept first
            return self._restore(a)

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """``deploy/site/restore.lock`` held for the whole run; a second restore is refused. Under it, a scratch
        folder another run left (``deploy/.restore-*``: a killed host step's decrypted backup and copies) is removed.
        H-114 (1421-3): ``deploy/site/backup.lock`` too, the lock every backup run takes
        (``backup_schedule.run_backup``): no backup writes over the folders while they are restored, and a restore
        never starts under a running one."""
        import fcntl

        site = self.deploy / "site"
        site.mkdir(parents=True, exist_ok=True)
        fd = os.open(site / "restore.lock", os.O_RDWR | os.O_CREAT, 0o600)
        bfd = -1
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RestoreStopped("another restore of this box is running (deploy/site/restore.lock): nothing "
                                     "was changed") from None  # fmt: skip
            bfd = os.open(site / "backup.lock", os.O_RDWR | os.O_CREAT, 0o644)  # the backup's own file (an empty lock)
            try:
                fcntl.flock(bfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RestoreStopped("a backup of this box is running (deploy/site/backup.lock): run the restore again "
                                     "when it has ended; nothing was changed") from None  # fmt: skip
            for old in self.deploy.glob(".restore-*"):
                if old.is_dir() and not old.is_symlink():
                    shutil.rmtree(old, ignore_errors=True)
                    print(f"restore: removed {old.name}, left by a restore that did not finish", file=sys.stderr)
            yield
        finally:
            if bfd >= 0:
                os.close(bfd)
            os.close(fd)

    def _restore(self, a: Any) -> int:
        file = absolute_path(last_good(self.deploy, self.env) if a.last else Path(a.file))
        if a.last:  # said before anything is stopped or changed
            print(f"restore: --last: {file} (the newest backup backup-nightly recorded good)", file=sys.stderr)
        check_key(Path(a.key))  # F5, before anything stops
        sha = self.checked_sha(file, a.last)  # F4: the file itself, before anything stops
        again = shlex.join(["trialbox", "restore", *(["--last"] if a.last else [str(file)]), "--key", str(a.key),
                            "--yes", *(["--restart"] if a.restart else [])])  # fmt: skip
        work = self.work_dir(file)  # the space the restore needs, before anything stops
        stopped: list[str] = []
        started = keep_work = False
        stop_signals = _host_signals()
        try:
            try:
                if a.restart:
                    self.stop_all_but_db(stopped)
                try:  # D-724: asked of compose here, on the host, before anything is read or changed
                    only_the_database_runs(["db"] if a.services_stopped else self.running())
                except Exception as e:  # the refusal, as the restore says it: nothing was changed
                    raise RestoreStopped(str(e)) from None
                argv, values = self.container(a, file, work, sha)
                started = True  # review R2: from here on, never "did not start"
                code, out = self.call(argv, values)
            except BaseException as e:  # F3: a stop that failed, an interrupt, anything: said, audited
                why = str(e) or type(e).__name__
                if started and not isinstance(e, RestoreStopped):
                    keep_work = True  # the container may still be putting the box back from it
                    self._say(stopped, f"unknown: the restore's container was started and this step stopped "
                              f"({type(e).__name__}); its work folder {work} is kept",
                              "docker ps: wait until no restore container runs, then trialbox doctor; do not start "
                              "the services before",
                              {"error": why[-300:], "stopped": stopped, "file": file.name,
                               "state": "unknown"})  # fmt: skip
                    return 130 if isinstance(e, (KeyboardInterrupt, HostInterrupted)) else 1
                if stopped or not isinstance(e, RestoreStopped):
                    self._say(stopped, "not changed by this command (the restore did not start)",
                              f"start them as they were: {self._start_line(stopped)}; or try again: {again}",
                              {"error": why[-300:], "stopped": stopped, "file": file.name})  # fmt: skip
                if isinstance(e, RestoreStopped):
                    raise
                if isinstance(e, (KeyboardInterrupt, HostInterrupted)):
                    return 130
                print(f"restore: {type(e).__name__}: {why[-400:]}", file=sys.stderr)
                return 1
            finally:
                if not keep_work:
                    shutil.rmtree(work, ignore_errors=True)
            try:
                return self._after(a, code, out, stopped, again)
            except (KeyboardInterrupt, HostInterrupted) as e:  # H-126: between the container's end and the start
                self._say(stopped, f"the restore's container ended {code} (its lines above say the data); this step "
                          f"was interrupted after it ({type(e).__name__})",
                          f"look at docker compose ps; run this command again: {again}")  # fmt: skip
                return 130
        finally:
            stop_signals()

    def _after(self, a: Any, code: int, out: str, stopped: list[str], again: str) -> int:
        """What the restore's container ended with: said, and with ``--restart`` the services started or not."""
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
        if code in (0, 3, 4):  # restored: H-48's marker goes, as the in-process restore removes it
            from tools.tls_policy import OLD_CLIENTS_AUDITED

            (self.deploy / "site" / OLD_CLIENTS_AUDITED).unlink(missing_ok=True)
        said = _said(out)
        if not a.restart:
            return code
        hold = str(said.get("hold") or "")
        state = str(said.get("state") or ("restored" if code in (0, 3, 4) else "unknown"))
        if code == 0 or (code == 4 and hold == "held") or (code != 0 and state == "unchanged"):
            # complete, or held (D-522): H-126, every service the box defines is started and the full expected set
            # checked. Refused before any change (the data is as this run found it): LR-14, only what this run
            # stopped, never what an earlier run left stopped
            data = "restored" if code in (0, 4) else "not changed"
            whole = state != "unchanged"
            start = shlex.join(self._up(stopped, whole))
            try:
                ok, short, err = self.start_and_wait(stopped, whole)
            except BaseException as e:  # review R7: an interrupt here is said too, never a silent end
                rc = 130 if isinstance(e, (KeyboardInterrupt, HostInterrupted)) else 1
                if not self._say(stopped, data, f"look at docker compose ps; then {start}, or run this command "
                                 f"again: {again}"):  # fmt: skip
                    rc = 130
                old = _ignore_signals()  # OCR 1470-1: lines only from here; no further signal cuts them short
                try:
                    print(f"restore: the services did not all come back healthy: {str(e)[-400:] or type(e).__name__}",
                          file=sys.stderr)  # fmt: skip
                    self._hold_line(hold, state)
                finally:
                    _put_back_signals(old)
                return rc
            n = f"{len(ok)} of {len(ok) + len(short)}"
            if short:  # H-126: a shortfall is never "healthy"; OCR 1470-3: a restore's own non-zero code (4: NOT
                # complete, held) stays the exit code, a complete one ends 1
                self._say(stopped, data, f"look at docker compose ps and the services' logs; then {start}")
                print(f"restore: the services did not all come back healthy: {n}; not running or not healthy: "
                      f"{', '.join(sorted(short))}" + (f" ({err})" if err else ""), file=sys.stderr)  # fmt: skip
                self._hold_line(hold, state)
                return code or 1
            what = "not changed (the restore was refused before any change)" if state == "unchanged" else "restored"
            if not whole:  # LR-14: what this run stopped, and only that
                print(f"restore: the data {what}; the services this run stopped run again and are healthy: {n} "
                      f"({', '.join(sorted(ok))})", file=sys.stderr)  # fmt: skip
                self._left_stopped(ok)
            else:
                print(f"restore: the data {what}; the services run again and are healthy: {n} "
                      f"({', '.join(sorted(ok))})", file=sys.stderr)  # fmt: skip
            self._hold_line(hold, state)
            return code
        if code == 3:
            self._say(stopped, "the databases and folders are restored; a reference pack is missing",
                      f"put the pack named above in --refdata and run {again}")  # fmt: skip
        elif code == 4:
            self._say(stopped, f"restored, NOT complete; the hold on the list jobs is {hold or 'unknown'}",
                      "keep the services stopped until the lines above are dealt with")  # fmt: skip
        elif state == "rolled_back":  # F2: the restore put the box back as it was and holds its list jobs
            self._say(stopped, "put back as it was before the restore (the restore failed); list jobs held",
                      f"read the error above; start them as they were: {self._start_line(stopped)}; "
                      f"or try again: {again}")  # fmt: skip
        else:  # F2: half restored or unknown: never a start line
            self._say(stopped, "NOT as it was: the restore failed and could not put everything back "
                      "(the lines above say what, and where the copy of the databases taken first is kept)",
                      "do not start the services; put the databases back from that copy, or restore the "
                      "kept copy of the box (trialbox restore <kept copy> --key <key> --yes)")  # fmt: skip
        return code

    def _left_stopped(self, ok: set[str]) -> None:
        """LR-14: after a refused restore, the services the box defines that this run did not start, named: an
        earlier run may have left them stopped on data that is not as it was. Never started here."""
        try:
            rest = sorted(self.expected([]) - ok)
        except Exception:
            print("restore: compose cannot say which other services the box defines: trialbox doctor says what "
                  "runs", file=sys.stderr)  # fmt: skip
            return
        if rest:
            print(f"restore: not started by this run, as it found them stopped: {', '.join(rest)}. An earlier run may "
                  "have left them stopped on purpose: read what it said (or the audit's backup.restore_failed) and "
                  "trialbox doctor before starting them (RUNBOOK §5)", file=sys.stderr)  # fmt: skip

    @staticmethod
    def _hold_line(hold: str, state: str) -> None:
        """H-126: the hold on the list jobs (``screening.after_restore``, D-522) after the services' start, as RUNBOOK
        §5 step 4 says it is released: by the restore itself, or by a person."""
        if hold == "released":
            print(f"restore: the hold {HOLD_FLAG}: released by the restore (it ended complete)", file=sys.stderr)
        elif hold == "held":
            print(f"restore: the hold {HOLD_FLAG} stays held: this restore did not end complete, or a hold or an "
                  "earlier restore's set-aside audit chain stood before it. No patient list is made until the data "
                  "steward or the administrator re-applies the events the restores listed and sets it to released on "
                  "/ops/flags with the reason (RUNBOOK §5, step 4)", file=sys.stderr)  # fmt: skip
        elif state != "unchanged":
            print(f"restore: the hold {HOLD_FLAG}: the restore said {hold or 'nothing'}; trialbox doctor shows it "
                  "(restore_hold)", file=sys.stderr)  # fmt: skip

    def checked_sha(self, file: Path, last: bool) -> str:
        """H-100 (F4): the backup file's own sha256, read here before anything stops, equal to what the nightly
        recorded for it (``--last``; a named file: its sidecar, and the record when it names the same file). The
        restore's container is given this hash and refuses a file that is not it."""
        from tools.trialbox import backup_schedule as bs

        h = hashlib.sha256()
        try:
            with file.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        except OSError as e:
            raise RestoreStopped(f"{file} cannot be read ({e.strerror}): nothing was changed") from None
        got = h.hexdigest()
        want = {"its .sha256 sidecar": bs.read_sidecar(file)}
        cfg = bs.config(self.deploy, self.env, process_env=False)
        try:
            good = json.loads(cfg.last_file.read_text(encoding="utf-8")).get("good_file") or {}
        except (OSError, ValueError):
            good = {}
        if last or good.get("name") == file.name:
            want["the nightly's record"] = str(good.get("sha256") or "") or None
        for where, sha in want.items():
            if sha is not None and sha != got:
                raise RestoreStopped(f"{file.name} is not the file {where} names: its sha256 differs. Nothing was "
                                     "changed")  # fmt: skip
        return got

    def work_dir(self, file: Path) -> Path:
        """The restore's scratch folder on the host (the unpacked backup, the copy of the databases taken first, the
        kept copy's work), checked for space before anything stops: the databases' size (``pg_database_size``,
        asked through the db container) plus four times the backup file (``restore_drill.UNPACK_FACTOR``)."""
        work = Path(tempfile.mkdtemp(prefix=".restore-", dir=self.deploy))  # 0700
        dbs = [self.box.db_bytes(db, user) for db, user in (("trialbox_wf", "trialbox"), ("hapi", "hapi"))]
        need = sum(n or 0 for n in dbs) + UNPACK_FACTOR * file.stat().st_size
        free = shutil.disk_usage(work).free
        if free < need:
            shutil.rmtree(work, ignore_errors=True)
            raise RestoreStopped(f"the restore needs about {need / 1e9:.1f} GB in {self.deploy} (the backup unpacked "
                                 f"and the databases copied aside first, to be put back if it fails), "
                                 f"{free / 1e9:.1f} GB is free. Nothing was changed")  # fmt: skip
        if None in dbs:
            print("restore: the databases' size could not be asked: their copy is checked inside the restore",
                  file=sys.stderr)  # fmt: skip
        return work


class HostInterrupted(BaseException):
    """SIGTERM or SIGHUP to the host's restore step (a closed session): its state is said and audited (F3)."""


def _host_signals() -> Callable[[], None]:
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def stop(signum: int, _frame: Any) -> None:
        raise HostInterrupted(f"signal {signal.Signals(signum).name}")

    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGHUP)}

    def back() -> None:
        for sig, h in old.items():
            signal.signal(sig, h)

    return back


def absolute_path(p: Path) -> Path:
    return Path(os.path.abspath(p))


def check_key(path: Path) -> None:
    """H-100 (F5): the private key, opened without following a link and checked on the open file: a regular file,
    owned by root (or by the user running the command, as launch.box_file reads the box file), readable by its
    owner alone. A key on a removable stick that cannot carry such a mode is copied to a root-only file first
    (RUNBOOK §5). Its content is never read here: the restore's container reads it, bound read-only."""
    import stat

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        why = "a link" if os.path.islink(path) else (e.strerror or "cannot be opened")
        raise RestoreStopped(f"--key {path}: {why}: nothing was changed") from None
    try:
        st = os.fstat(fd)
    finally:
        os.close(fd)
    if not stat.S_ISREG(st.st_mode):
        raise RestoreStopped(f"--key {path} is not a file: nothing was changed")
    if st.st_uid not in (0, os.geteuid()) or st.st_mode & 0o077:
        raise RestoreStopped(
            f"--key {path} must be owned by root and readable by root alone (mode 0600): copy it to such a file "
            f"first (install -m 0600 -o root -g root {path} /root/trialbox-backup.key) and name that one. Nothing "
            "was changed"
        )


def _said(out: str) -> dict[str, Any]:
    try:
        d = json.loads(out)
    except (ValueError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def _ignore_signals() -> dict[int, Any]:
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return {}
    return {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}


def _put_back_signals(old: Mapping[int, Any]) -> None:
    import signal

    for sig, h in old.items():
        signal.signal(sig, h)


def _call(argv: list[str], values: dict[str, str], base: Mapping[str, str] | None = None) -> tuple[int, str]:
    """The restore container: its stdout (the JSON) captured and passed on, its stderr straight to the person. Its
    environment is the engine's own (``base``, F1) and the values its ``-e NAME`` options name. The first interrupt
    or signal while it runs is passed to it once; from then on further ones are ignored and the container is waited
    for to the end, whatever arrives (review R2): the restore puts the box back itself and says its state."""
    import signal

    try:
        proc = subprocess.Popen(argv, env={**(base or {}), **values}, stdout=subprocess.PIPE, text=True)
    except OSError as e:
        raise RestoreStopped(
            f"the container runtime cannot be started here ({e.strerror}): nothing was changed"
        ) from None
    old: dict[int, Any] | None = None
    try:
        while True:
            try:
                out, _ = proc.communicate()
                return proc.returncode, out or ""
            except (KeyboardInterrupt, HostInterrupted):
                if old is None:
                    old = _ignore_signals()  # first: nothing more stops this wait
                    print("restore: stopping: the restore is told and puts the box back; waiting for it",
                          file=sys.stderr)  # fmt: skip
                    proc.send_signal(signal.SIGTERM)
    finally:
        if old is not None:
            for sig, h in old.items():
                signal.signal(sig, h)


def main(a: Any) -> int:
    """trialbox restore on the host (the installed form, or a host python without the libraries)."""
    try:
        return BoxRestore(a.deploy).restore(a)
    except RestoreStopped as e:
        print(f"restore: {e}", file=sys.stderr)
        return 2


# ------------------------------------------------------------------------------------------------ in the container
def roles(environ: Mapping[str, str] | None = None, run: Callable[..., Any] = subprocess.run,
          script: str = ROLES_IN) -> int:  # fmt: skip
    """``TB_DB_ROLES_CMD`` of the box's restore container (D-573): the service-role script of the box, over the
    database network as the superuser of ``TB_HAPI_DB_URL``, its password in the environment of psql only."""
    from psycopg.conninfo import conninfo_to_dict

    env = dict(os.environ if environ is None else environ)
    try:
        info = conninfo_to_dict(env.get("TB_HAPI_DB_URL", ""))
    except Exception:  # never the URL itself in the message: it holds the password
        info = {}
    if not info.get("host") or not info.get("user"):
        print("roles: TB_HAPI_DB_URL names no database server and user", file=sys.stderr)
        return 2
    env.update(PGHOST=str(info["host"]), PGPORT=str(info.get("port") or 5432),
               PGPASSWORD=str(info.get("password") or ""),
               POSTGRES_USER=str(info["user"]))  # fmt: skip
    return int(run(["sh", script], env=env, check=False).returncode)


def _main(args: Sequence[str]) -> int:
    if list(args[:1]) == ["roles"] and len(args) <= 2:
        return roles(script=args[1] if len(args) == 2 else ROLES_IN)
    print("usage: python -m tools.trialbox.box_restore roles [script]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
