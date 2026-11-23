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

``--last``: the newest backup ``backup-nightly`` recorded good (``deploy/site/backup-last.json``) and found on a
target with the same size and sha256.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
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
WAIT_S = 600  # the services' health wait after the restore (as an update's start waits, update.ComposeBox)


#: D-724 (DATA-011): the services a restore leaves running: the database it restores into, nothing that writes
#: a volume the restore renames aside
RESTORE_MAY_RUN = frozenset({"db"})
#: backup.VOLUME_ROOT: where the box's compose volumes are, inside the restore's container as on a host
VOLUME_ROOT = "/var/lib/docker/volumes/trialbox_{}/_data"


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
                 call: Callable[[list[str], dict[str, str]], tuple[int, str]] | None = None) -> None:  # fmt: skip
        from tools.trialbox import update
        from tools.trialbox.backup_schedule import absolute

        self.deploy = absolute(deploy)
        self.box = update.ComposeBox(self.deploy, run or update.run_cmd)
        self.env = self.box.env  # deploy/.env, read by the box (launch.box_file checked it first)
        # the runtime and compose are the box file's or the defaults, never the caller's (launch.run_in_image)
        self.box.docker = shlex.split(self.env.get("TB_DOCKER") or "docker")
        self.box.compose = shlex.split(self.env.get("TB_COMPOSE") or "") or [
            *self.box.docker, "compose", "--project-directory", str(self.deploy)]  # fmt: skip
        self.call = call or _call

    # ------------------------------------------------------------------------------------------- the services
    def running(self) -> list[str] | None:
        return self.box.running_services()

    def stop_all_but_db(self) -> list[str]:
        names = self.running()
        if names is None:
            raise RestoreStopped("compose cannot say which services run: --restart stops nothing it cannot see. "
                                 "Nothing was changed")  # fmt: skip
        others = sorted(set(names) - RESTORE_MAY_RUN)
        if others:
            self.box.run(self.box._c("stop", *others), timeout=900)
        return others

    def start_and_wait(self) -> list[str]:
        """Every service up, waited for until healthy (``up --wait``); the services that run after it."""
        self.box.run(self.box._c("up", "-d", "--wait", "--wait-timeout", str(WAIT_S)), timeout=WAIT_S + 120)
        return self.running() or []

    # ------------------------------------------------------------------------------------------- the container
    def volumes_root(self) -> Path:
        return Path(self.env.get("TB_DOCKER_VOLUMES") or "/var/lib/docker/volumes")

    def container(self, a: Any, file: Path) -> tuple[list[str], dict[str, str]]:
        """The restore's one container and the values its ``-e NAME`` options take (never on its command line)."""
        from tools.trialbox.backup_schedule import absolute
        from tools.trialbox.update import BACKUP_VOLUMES

        image = self.env.get("TB_BACKUP_IMAGE") or "trialbox-backup:1.0.0"
        file, key = absolute(file), absolute(a.key)
        pub, keep_to, refdata = absolute(a.public), absolute(a.keep_to), absolute(a.refdata)
        values = {**job_db_env(self.env), **role_env(self.env), "TB_DB_ROLES_CMD": ROLES_CMD}
        for k in ("TB_SITE_ID", "TB_ENV", "TB_TZ", "TB_REHEARSAL", "TB_KEK_FILE", "TB_KEK_PASSPHRASE"):
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
        root = self.volumes_root()
        for name, vol in BACKUP_VOLUMES.items():  # each volume's own folder: its _data is moved aside within it
            folder = root / f"trialbox_{vol}"
            if folder.is_dir():
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
                "--services-stopped", "--public", str(pub), "--keep-to", str(keep_to), "--refdata", str(refdata),
                *dirs]  # fmt: skip
        flags = (("--no-copy", a.no_copy), ("--other-site", a.other_site), ("--older-ok", a.older_ok),
                 ("--restic-from-box", a.restic_from_box))  # fmt: skip
        argv += [x for x, on in flags if on]
        for s in shares:
            argv += ["--restic-share", str(s)]
        return argv, values

    # ------------------------------------------------------------------------------------------- the command
    def restore(self, a: Any) -> int:
        file = last_good(self.deploy, self.env) if a.last else Path(a.file)
        if a.restart:
            stopped = self.stop_all_but_db()
            if stopped:
                print(f"restore: stopped {', '.join(stopped)} (--restart); db keeps running", file=sys.stderr)
        try:  # D-724: asked of compose here, on the host, before anything is read or changed
            only_the_database_runs(["db"] if a.services_stopped else self.running())
        except Exception as e:  # the refusal, as the restore says it: nothing was changed
            raise RestoreStopped(str(e)) from None
        argv, values = self.container(a, file)
        code, out = self.call(argv, values)
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
        if code in (0, 3, 4):  # restored: H-48's marker goes, as the in-process restore removes it
            from tools.tls_policy import OLD_CLIENTS_AUDITED

            (self.deploy / "site" / OLD_CLIENTS_AUDITED).unlink(missing_ok=True)
        if not a.restart:
            return code
        hold = _hold_of(out)
        if code == 0 or (code == 4 and hold == "held"):
            try:
                up = self.start_and_wait()
            except Exception as e:  # named, never a setting in it
                print(f"restore: the restore is done, but the services did not all come back healthy: "
                      f"{str(e)[-400:]} (docker compose ps; RUNBOOK §5)", file=sys.stderr)  # fmt: skip
                return 1
            print(f"restore: the services run again and are healthy: {len(up)} ({', '.join(sorted(up))})",
                  file=sys.stderr)  # fmt: skip
            return code
        why = {3: "a reference pack is missing (put it in --refdata and run the restore again)",
               4: f"the restore is not complete and the hold on the list jobs is {hold or 'unknown'}"}  # fmt: skip
        print(f"restore: the services stay stopped: {why.get(code, f'the restore failed (exit {code})')}; "
              "start them with docker compose up -d once the lines above are dealt with (RUNBOOK §5)",
              file=sys.stderr)  # fmt: skip
        return code


def _hold_of(out: str) -> str:
    try:
        return str(json.loads(out).get("hold") or "")
    except (ValueError, AttributeError):
        return ""


def _call(argv: list[str], values: dict[str, str]) -> tuple[int, str]:
    """The restore container: its stdout (the JSON) captured and passed on, its stderr straight to the person."""
    try:
        r = subprocess.run(argv, env={**os.environ, **values}, stdout=subprocess.PIPE, text=True, check=False)
    except OSError as e:
        raise RestoreStopped(
            f"the container runtime cannot be started here ({e.strerror}): nothing was changed"
        ) from None
    return r.returncode, r.stdout or ""


def main(a: Any) -> int:
    """``trialbox restore`` on the host (the installed form, or a host python without the libraries)."""
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
