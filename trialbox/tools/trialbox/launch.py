"""Every ``trialbox`` host command brings its own environment (H-88). Standard library only.

A command typed on a box (``sudo python3 -m tools.trialbox ...`` from the install folder, or the backup schedule's
cron line) runs with the host's ``python3``, which has the standard library and PyYAML (install.sh HOST-PYTHON) and
nothing else, under ``sudo`` or cron, which drop the caller's environment. So every entry goes through here:

1. **The import path** is set from this file's own location: the install folder and its ``libs/`` go first
   (:func:`own_path`); what the caller's ``PYTHONPATH`` added comes after and never decides where a command runs.
2. **The settings** are the box's own ``deploy/.env`` (beside this file's install folder), read by the tool itself
   (:func:`box_settings`): a key in that file wins over the caller's environment, a ``TB_ENV`` it does not set is
   never the caller's, and a file that is there but cannot be trusted (not a readable regular file, another user's,
   writable by group or others) stops the command (:func:`box_file`, exit 2). So ``sudo`` dropping ``TB_DB_URL`` no
   longer matters, and a caller's ``TB_DB_URL``, ``TB_ENV``, ``TB_DOCKER`` or ``TB_IMAGE`` never wins over the box.
3. **The libraries** the host does not have (``zstandard``, ``cryptography``, ``psycopg``, ``httpx``): a command
   that needs them runs in a one-off container of the box's own Python image (``TB_IMAGE``, as ``ops.py`` and
   ``audit_heads.py`` run theirs; ``--pull never``), on the compose network only when it needs the database, with
   only the mounts its arguments name (inputs read-only), ``--cap-drop ALL``, the invoking user's uid and gid,
   the settings by ``--env-file`` only to a command with a network (no value on a command line), the runtime and the
   image the box file's or the defaults, and its exit code and output passed through
   (:func:`container_argv`). Where the libraries are there (the image itself, a developer's interpreter), the
   command runs here.

``restore-drill`` runs on the host: the installed form's own steps already run the library parts in the box image
(``box_drill.py``, #1305).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import shlex
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
OWN_PATH = (str(ROOT / "libs"), str(ROOT))
DEFAULT_IMAGE = "trialbox-py:1.0.0"
DB_NETWORK = "trialbox-net"
MODEL_NETWORK = "trialbox-model-net"

HOST = "host"  # the standard library, PyYAML and the product's own path: runs here
IMAGE = "image"  # the box image's libraries, no network


@dataclass(frozen=True)
class Need:
    """What a command needs beyond the host's python3: its libraries, a network, the files its arguments name."""

    where: str = HOST
    libs: tuple[str, ...] = ()
    network: str = "none"
    read: tuple[str, ...] = ()  # options (or "0" for the first positional) whose file is read: mounted read-only
    write: tuple[str, ...] = ()  # options whose file or folder is written: its folder mounted read-write
    pairs: tuple[str, ...] = ()  # options of name=path (``--dir``): the path mounted read-write
    site: bool = False  # writes deploy/site (a record): that folder mounted read-write, --deploy passed
    extra: tuple[str, ...] = field(default=())


CRYPTO = ("zstandard", "cryptography")
#: every command of ``tools/trialbox/__main__.py`` and what it needs (a new command must be added here: the test
#: ``test_every_host_command_runs_from_a_bare_environment`` holds the table to the parser)
COMMANDS: dict[str, Need] = {
    "doctor": Need(),
    "platform-images": Need(),
    "platform-egress": Need(),
    "eval": Need(IMAGE, ("httpx",), MODEL_NETWORK, write=("--archive",)),
    "backup-keygen": Need(IMAGE, CRYPTO, write=("--private", "--public")),
    "backup": Need(IMAGE, (*CRYPTO, "psycopg"), DB_NETWORK, read=("--public",), write=("--to",), pairs=("--dir",)),
    "backup-check": Need(IMAGE, CRYPTO, read=("0",)),
    "backup-verify": Need(IMAGE, CRYPTO, read=("0", "--key", "--restic-share"), site=True),
    "restore": Need(
        IMAGE,
        (*CRYPTO, "psycopg"),
        DB_NETWORK,
        read=("0", "--key", "--public", "--refdata", "--restic-share"),
        write=("--keep-to",),
        pairs=("--dir",),
        site=True,
    ),
    "restore-drill": Need(),  # installed: its image steps are box_drill.py's own (#1305)
    "backup-nightly": Need(),
    "backup-status": Need(),
    "backup-install": Need(),
    "migrate": Need(),
    "secrets": Need(),
    "audit-sign": Need(),
    "anchors-compose": Need(),
    "finish-check": Need(),
    "omop-store": Need(IMAGE, ("psycopg",), DB_NETWORK, write=("--lake",)),
    "logs": Need(),
    "update": Need(),
    "pre-start": Need(),
    "db-up": Need(),
    "ops": Need(),
    "watchdog": Need(),
    "support-bundle": Need(),
    "exports": Need(IMAGE, ("cryptography",), read=("--audit",)),
    "selftest": Need(),
    "decommission-plan": Need(),
    "mail": Need(
        IMAGE, ("mail_gateway", "pydantic"), DB_NETWORK
    ),  # the gateway's own code (services/), as the runbook runs it
    "platform-day2": Need(),
    "model": Need(IMAGE, ("psycopg",), DB_NETWORK, write=("--out",)),
    "provenance": Need(),
}


def own_path(path: list[str], caller: Mapping[str, str]) -> list[str]:
    """``sys.path`` with the install folder's ``libs/`` and the install folder first, so the product is found from
    this file, never from the caller: what the caller's ``PYTHONPATH`` put there comes after (a site's own PyYAML
    folder still imports) and never decides where a command runs (:func:`has_libs`). An empty entry (the cwd) goes."""
    kept = [p for p in path if p and p not in OWN_PATH]
    return [*OWN_PATH, *kept]


def caller_entries(caller: Mapping[str, str]) -> set[str]:
    """The caller's ``PYTHONPATH`` entries from outside the install folder."""
    return {os.path.abspath(p) for p in (caller.get("PYTHONPATH") or "").split(os.pathsep) if p and not _inside(p)}


def _inside(p: str) -> bool:
    a = os.path.abspath(p)
    return a == str(ROOT) or a.startswith(str(ROOT) + os.sep)


def env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines of a ``deploy/.env`` (as ``update._env_file`` reads it; comments and blank lines skipped)."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


class BoxFileError(RuntimeError):
    """The box's ``deploy/.env`` is there but cannot be trusted or read: nothing is run."""


def box_file(deploy: Path = DEPLOY) -> dict[str, str]:
    """The box's own ``deploy/.env``, checked before it is used (as root): none there is no setting (``{}``); one that
    is there but is not a readable regular file (a folder, a dangling link, unreadable), is owned by neither root nor
    this user, or is writable by group or others raises :class:`BoxFileError` (named, never with a value)."""
    path = deploy / ".env"
    if not os.path.lexists(path):
        return {}
    try:
        st = os.stat(path)
    except OSError as e:
        raise BoxFileError(f"{path} cannot be read ({e.strerror}): nothing was run") from None
    if not stat.S_ISREG(st.st_mode):
        raise BoxFileError(f"{path} is not a file: nothing was run")
    if st.st_uid not in (0, os.geteuid()):
        raise BoxFileError(f"{path} belongs to uid {st.st_uid}, neither root nor this user: nothing was run")
    if st.st_mode & 0o022:
        raise BoxFileError(f"{path} can be written by group or others (chmod 600 it): nothing was run")
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise BoxFileError(f"{path} cannot be read ({type(e).__name__}): nothing was run") from None
    return env_file(path)


def box_settings(environ: dict[str, str] | os._Environ[str], deploy: Path = DEPLOY) -> dict[str, str]:
    """Put the box's own ``deploy/.env`` into ``environ``: each key of the file wins over the caller's value, and a
    ``TB_ENV`` the file does not set is never taken from the caller (the default, PRODUCTION, applies). Returns the
    file's settings; :class:`BoxFileError` when it cannot be trusted."""
    box = box_file(deploy)
    environ.update(box)
    if "TB_ENV" not in box:
        environ.pop("TB_ENV", None)
    return box


_CALLER: set[str] = set()  # set by enter(): what the caller's PYTHONPATH added


def has_libs(names: Sequence[str]) -> bool:
    """Whether this interpreter has ``names`` of its own: a module on the caller's ``PYTHONPATH`` does not count."""
    own = [p for p in sys.path if os.path.abspath(p or ".") not in _CALLER]
    return all(importlib.machinery.PathFinder.find_spec(n, own) is not None for n in names)


def command_of(args: Sequence[str]) -> str:
    return next((a for a in args if not a.startswith("-")), "")


#: options that take no value (the first positional is found past them)
SWITCHES = ("--yes", "--json", "--no-copy", "--other-site", "--older-ok", "--services-stopped", "--restic-from-box",
            "--help", "-h")  # fmt: skip


def _values(args: Sequence[str], flag: str) -> list[str]:
    """The values of ``flag`` (``--x v`` and ``--x=v``); ``"0"``: the first positional after the command."""
    if flag == "0":
        rest = list(args[1:])
        out: list[str] = []
        skip = False
        for a in rest:
            if skip:
                skip = False
                continue
            if a.startswith("-"):
                skip = "=" not in a and a not in SWITCHES
                continue
            out.append(a)
            break
        return out
    vals = []
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            vals.append(args[i + 1])
        elif a.startswith(flag + "="):
            vals.append(a.split("=", 1)[1])
    return vals


def _abs(p: str, cwd: Path) -> Path:
    return Path(os.path.normpath(cwd / p))


def container_argv(args: Sequence[str], need: Need, box: Mapping[str, str], cwd: Path,
                   uid: int, gid: int, docker: Sequence[str] = ("docker",)) -> list[str]:  # fmt: skip
    """The one-off container that runs ``python -m tools.trialbox ARGS`` for a command that needs the box image's
    libraries: the box's own image, never pulled; the compose network only when the command needs the database;
    each file its arguments name mounted at its own path (inputs read-only); the settings by ``--env-file``."""
    mounts: list[str] = []
    out_args = list(args)
    seen: set[str] = set()

    def mount(src: Path, ro: bool) -> None:
        key = f"{src}:{src}" + (":ro" if ro else "")
        if str(src) not in seen:
            seen.add(str(src))
            mounts.extend(["-v", key])

    def rewrite(old: str, new: str) -> None:
        for i, a in enumerate(out_args):
            if a == old:
                out_args[i] = new
            elif a.endswith("=" + old) and a.startswith("--"):
                out_args[i] = a[: -len(old)] + new

    for flag in need.read:
        for v in _values(args, flag):
            p = _abs(v, cwd)
            mount(p, True)
            rewrite(v, str(p))
    for flag in need.write:
        for v in _values(args, flag):
            p = _abs(v, cwd)
            folder = p if p.is_dir() or flag == "--to" else p.parent
            folder.mkdir(parents=True, exist_ok=True)
            mount(folder, False)
            rewrite(v, str(p))
    for flag in need.pairs:
        for v in _values(args, flag):
            name, _, path = v.partition("=")
            if path:
                p = _abs(path, cwd)
                mount(p, False)
                rewrite(v, f"{name}={p}")
    if need.site:
        site = DEPLOY / "site"
        site.mkdir(parents=True, exist_ok=True)
        mount(site, False)
        if "--deploy" not in args and not any(a.startswith("--deploy=") for a in args):
            out_args += ["--deploy", str(DEPLOY)]
    # the settings only to a command with a network (the database's password among them); never on a command line
    envf = ["--env-file", str(DEPLOY / ".env")] if need.network != "none" and (DEPLOY / ".env").is_file() else []
    image = box.get("TB_IMAGE") or DEFAULT_IMAGE
    return [*docker, "run", "--rm", "-i", "--pull", "never", "--network", need.network, "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--user", f"{uid}:{gid}", "-e", "PYTHONDONTWRITEBYTECODE=1",
            *envf, *mounts, "-w", "/app", image, "python", "-m", "tools.trialbox", *out_args]  # fmt: skip


def run_in_image(args: Sequence[str], need: Need, box: Mapping[str, str]) -> int:
    """Run the command in the box image; its output and exit code are the command's own. The runtime and the image
    are the box file's or the defaults, never the caller's (a caller's TB_DOCKER would run as this user)."""
    docker = shlex.split(box.get("TB_DOCKER") or "docker")
    argv = container_argv(args, need, box, Path.cwd(), os.getuid(), os.getgid(), docker)
    try:
        return subprocess.run(argv, check=False).returncode
    except OSError as e:
        print(f"trialbox: {command_of(args)} needs the box image's libraries ({', '.join(need.libs)}) and runs in "
              f"a one-off container, but Docker cannot be started here: {e}", file=sys.stderr)  # fmt: skip
        return 2


def enter(args: Sequence[str], environ: dict[str, str] | os._Environ[str] | None = None, *,
          installed: bool = False) -> int | None:  # fmt: skip
    """The entry of ``trialbox`` (installed on PATH) and ``python3 -m tools.trialbox``: its own import path and the
    box's settings; then either the exit code of the command run in the box image, or None: run it here.

    The one form that keeps the caller's environment is ``python -m tools.trialbox restore-drill`` (#1305, review
    12: the module form drills against the caller's connection and ``--dir``; the installed ``trialbox
    restore-drill`` reads the box's own settings itself, ``box_drill.BoxDrill``)."""
    environ = os.environ if environ is None else environ
    _CALLER.update(caller_entries(environ))
    sys.path[:] = own_path(sys.path, environ)
    cmd = command_of(args)
    try:
        box = box_file(DEPLOY)
        if installed or cmd != "restore-drill":
            box_settings(environ, DEPLOY)
    except BoxFileError as e:
        print(f"trialbox: {e}", file=sys.stderr)
        return 2
    need = COMMANDS.get(cmd)
    if need is None or need.where == HOST or "-h" in args or "--help" in args or has_libs(need.libs):
        return None
    return run_in_image(args, need, box)
