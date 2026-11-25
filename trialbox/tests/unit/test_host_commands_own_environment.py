"""H-88: every ``trialbox`` host command brings its own environment (``tools/trialbox/launch.py``).

The bench's install walk, step 8: the scheduled backup stopped on "No module named 'tb_common'" and the restore drill
on the same, then on "TB_DB_URL is not set": cron and ``sudo`` give a command a bare environment, and the host's
``python3`` has the standard library and PyYAML only (install.sh HOST-PYTHON). Here each command runs as cron and
``sudo`` run it: ``env -i`` with ``PATH=/usr/sbin:/usr/bin:/bin``, no ``PYTHONPATH``, no ``HOME``, and a stand-in
"system" ``python3`` (a venv of the base interpreter without site packages, PyYAML linked in, so psycopg, zstandard,
cryptography and tb_common cannot come from anywhere but the tool itself) first on that ``PATH``, in a copy of the
install folder. The stand-in ``docker`` records every call and runs the box image's part with the test's
interpreter, as the image would (its ``PYTHONPATH``), so what needs the libraries really runs.

THE INVARIANT (H-88): ``test_every_host_command_runs_from_a_bare_environment``: every ``trialbox`` host command runs
from a bare environment with the system interpreter; none reads its import path, its settings or its DSN from the
caller's environment (``test_the_callers_path_and_settings_never_win``)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests import pg_client
from tests.unit.test_doctor_serving import KEY, _inputs, _pins, servers  # noqa: F401 (the fixture)
from tools.trialbox import backup_schedule as bs
from tools.trialbox import launch

ROOT = Path(__file__).resolve().parents[2]
PY_IMAGE = "trialbox-py:h88-test"
BARE_PATH = "/usr/sbin:/usr/bin:/bin"
DSN = "postgresql://trialbox@db:5432/trialbox_wf"
HAPI = "postgresql://hapi@db:5432/hapi"

STANDIN = r"""
import json, os, subprocess, sys
argv = sys.argv[1:]
with open(os.environ["STANDIN_LOG"], "a") as log:
    log.write(json.dumps({"argv": argv, "env_db_url": os.environ.get("TB_DB_URL")}) + "\n")
img = os.environ["STANDIN_PY_IMAGE"]
box = os.environ["STANDIN_BOX"]
def mapped(x, maps):
    for dst, src in maps:
        if x == dst or x.startswith(dst + "/"):
            return src + x[len(dst):]
        if "=" + dst in x:
            return x.replace("=" + dst, "=" + src, 1)
    return x


if argv[:1] == ["run"] and img in argv:  # the box image: its python, its PYTHONPATH, each mount where it is here
    i = argv.index(img)
    opts, rest = argv[1:i], argv[i + 1 :]
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": f"{box}/libs:{os.environ['STANDIN_SERVICES']}:{box}"}
    maps = []
    for k, v in zip(opts, opts[1:]):
        if k == "-v":
            src, dst = v.split(":")[:2]
            if not src.startswith("/"):  # a named volume: the folder docker keeps it in
                src = os.path.join(os.environ["STANDIN_VOLUMES"], src, "_data")
                os.makedirs(src, exist_ok=True)
            if src != dst:
                maps.append((dst, src))
    maps.sort(key=lambda m: -len(m[0]))
    rest = [mapped(x, maps) for x in rest]
    for k, v in zip(opts, opts[1:]):
        if k == "--env-file":
            for line in open(v, encoding="utf-8").read().splitlines():
                if "=" in line and not line.startswith("#"):
                    a, _, b = line.partition("=")
                    env[a.strip()] = b.strip()
        if k == "-e":
            name, eq, val = v.partition("=")
            if eq:
                env[name] = mapped(val, maps)
            elif name in os.environ:
                env[name] = os.environ[name]
    assert rest[0] == "python", rest
    if "tools.trialbox.box_drill" in rest:  # the drill's image step: its /work is the mounted folder here
        if "TB_DB_URL" in env:
            env["TB_DB_URL"] = os.environ["STANDIN_DB_URL"]  # the box's URL, as the db container's network resolves it
        i = rest.index("tools.trialbox.box_drill")
        code = ("import json, sys; from pathlib import Path; from tools.trialbox import box_drill; "
                "print(json.dumps(box_drill.image_step(sys.argv[2:], Path(sys.argv[1]))))")
        rest = ["python", "-c", code, mapped("/work", maps), *rest[i + 1 :]]
    sys.exit(subprocess.run([os.environ["STANDIN_PY"], *rest[1:]], cwd=box, env=env).returncode)
if "compose" in argv and "ps" in argv and "-q" in argv:  # the db container's id
    print("synthetic-db")
    sys.exit(0)
if argv[:1] == ["inspect"]:  # its mounts: the database's data folder
    print(json.dumps([{"Destination": "/var/lib/postgresql/data", "Source": os.environ["STANDIN_VOLUMES"]}]))
    sys.exit(0)
if "compose" in argv and "exec" in argv:  # into the db container: its shell and its clients, here on the test cluster
    rest = argv[argv.index("exec") + 1 :]
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in ("-u", "--user", "-e") else rest[1:]
    pg = {"PGHOST": os.environ["STANDIN_PGHOST"], "PGPORT": os.environ["STANDIN_PGPORT"],
          "POSTGRES_USER": os.environ["STANDIN_PGUSER"], "POSTGRES_DB": os.environ["STANDIN_PGDB"]}
    path = os.environ["STANDIN_PGWRAP"] + ":" + os.environ["STANDIN_PG_BIN"] + ":" + os.environ["PATH"]
    if rest[:1] == ["db"] and rest[1:2] in (["sh"], ["rm"], ["pg_restore"]):
        # the db container's own /tmp spool is this test's folder here: a fixed host path may be another user's
        spool = os.environ["STANDIN_SPOOL"]
        fixed = os.environ["STANDIN_CONTAINER_SPOOL"]
        rest = [x.replace(fixed, spool) for x in rest]
        data = None if sys.stdin.isatty() else sys.stdin.buffer.read()
        if rest[1] != "pg_restore" and data is not None:
            data = data.replace(fixed.encode(), spool.encode())
        sys.exit(subprocess.run(rest[1:], input=data, env={**os.environ, **pg, "PATH": path}).returncode)
    if rest[:1] == ["orchestrator"] and os.environ.get("STANDIN_AUDIT"):  # the audit event, on stdin
        with open(os.environ["STANDIN_AUDIT"], "a") as fh:
            fh.write(sys.stdin.read().strip() + "\n")
        sys.exit(0)
    if "count(*)" in " ".join(rest):  # no job runs or waits on this box
        print("0")
    sys.exit(0)  # another query of the db (sizes) or the orchestrator: no answer
if argv[:1] == ["version"]:
    print("27.0.0")
elif argv[:2] == ["image", "inspect"]:
    print("sha256:0")
sys.exit(0)  # compose ps, exec, ...: nothing runs, nothing is listed
"""


PGWRAP = r"""
import os, sys
name, a, out, i = os.path.basename(sys.argv[0]), sys.argv[1:], [], 0
while i < len(a):  # the box's names (-U trialbox -d trialbox_wf) are the test cluster's
    if a[i] in ("-U", "-d") and i + 1 < len(a):
        out += ["-U", os.environ["STANDIN_PGUSER"]] if a[i] == "-U" else ["-d", os.environ.get("STANDIN_DB_" + a[i + 1],
                                                                                            a[i + 1])]
        i += 2
        continue
    out.append(a[i])
    i += 1
env = {**os.environ, "PGHOST": os.environ["STANDIN_PGHOST"], "PGPORT": os.environ["STANDIN_PGPORT"]}
os.execve(os.path.join(os.environ["STANDIN_PG_BIN"], name), [name, *out], env)
"""


@pytest.fixture(autouse=True)
def _a_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """In this process the launcher sees a host, whatever marks the test host itself carries (review F2)."""
    monkeypatch.setattr(launch, "CONTAINER_MARKS", ())


@pytest.fixture(scope="module")
def system_python(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ``python3`` with the standard library and PyYAML only: the host's, as install.sh requires it."""
    d = tmp_path_factory.mktemp("system-python")
    base = getattr(sys, "_base_executable", None) or sys.executable
    subprocess.run([base, "-m", "venv", "--without-pip", str(d / "venv")], check=True, capture_output=True)
    site = next((d / "venv" / "lib").glob("python3*/site-packages"))
    have = Path(yaml.__file__).resolve().parent.parent
    for name in ("yaml", "_yaml"):
        if (have / name).exists():
            (site / name).symlink_to(have / name)
    py = d / "venv" / "bin" / "python3"
    for mod in ("psycopg", "zstandard", "cryptography", "httpx", "tb_common"):
        r = subprocess.run(
            [str(py), "-c", f"import {mod}"], cwd="/", env={"PATH": BARE_PATH}, capture_output=True, check=False
        )
        assert r.returncode != 0, f"the stand-in system python has {mod}"
    return py


def _explicit_modes(top: Path, root: Path) -> None:
    """H-139 (item 5, the integrator's 7151749260: ruled b): the folders a fixture makes get explicit modes, never the
    run's umask. ``top``, the folders from it down to the install folder ``root`` and the install's own folders are
    0755, as root makes them on the box; ``deploy/.env`` is 0600, as install.sh writes it (``deploy/.env:`` in the
    Makefile). The copied tree below keeps the modes of the files it was copied from."""
    for folder in (top, *[p for p in root.parents if top in p.parents], root, root / "deploy"):
        folder.chmod(0o755)
    (root / "deploy" / ".env").chmod(0o600)


@pytest.fixture(scope="module")
def box(tmp_path_factory: pytest.TempPathFactory, system_python: Path, pg_cluster_url: str) -> Iterator[dict[str, Any]]:
    """A copy of the install folder (tools, libs, deploy) with a box's deploy/.env and backup key, the stand-in bin
    first on PATH, and the box's two databases as two scratch databases of the test cluster (synthetic rows)."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from tb_common.db import split_url

    from tools import pglocal
    from tools.trialbox import backup as bk

    d = tmp_path_factory.mktemp("h88")
    admin, _ = split_url(pg_cluster_url)
    info = conninfo_to_dict(admin)
    dbs = {"trialbox_wf": f"h88_{os.getpid()}_wf", "hapi": f"h88_{os.getpid()}_hapi"}
    with psycopg.connect(admin, autocommit=True) as con:
        for n in dbs.values():
            con.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')
            con.execute(f'CREATE DATABASE "{n}"')
    from psycopg.conninfo import make_conninfo

    with psycopg.connect(make_conninfo(admin, dbname=dbs["trialbox_wf"]), autocommit=True) as con:
        con.execute("CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL)")
        con.execute("INSERT INTO marks VALUES ('SYN-1', 'approach'), ('SYN-2', 'not_now')")
    root = d / "opt" / "trialbox"
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "site", ".env")
    for sub in ("tools", "libs", "deploy"):
        shutil.copytree(ROOT / sub, root / sub, ignore=skip, symlinks=True)
    (root / "services").symlink_to(ROOT / "services")  # the image's /app/services (read only here)
    nas = d / "nas"
    nas.mkdir()
    (d / "volumes").mkdir()  # where docker keeps the volumes (the db's data folder among them)
    (nas / bs.OFFBOX_MARKER).write_text("")
    settings = {"TB_ENV": "TEST", "TB_DB_URL": DSN, "TB_HAPI_DB_URL": HAPI, "TB_IMAGE": PY_IMAGE, "TB_BACKUP_TARGETS": str(nas),
                "TB_BACKUP_OFFBOX": str(nas), "TB_DOCKER_VOLUMES": str(d / "volumes")}  # fmt: skip
    (root / "deploy" / ".env").write_text("".join(f"{k}={v}\n" for k, v in settings.items()), encoding="utf-8")
    _explicit_modes(d, root)  # H-139 (item 5, ruled b): the folders this fixture makes, whatever the run's umask
    (root / "deploy" / "secrets").mkdir(exist_ok=True)
    bk.keygen(d / "usb" / "backup.key", root / "deploy" / "secrets" / "backup.pub")  # this test's own key pair
    pgwrap = d / "pgwrap"
    pgwrap.mkdir()
    for name in ("psql", "pg_dump"):
        (pgwrap / name).write_text(f"#!{sys.executable}\n{PGWRAP}", encoding="utf-8")
        (pgwrap / name).chmod(0o755)
    bindir = d / "bin"
    bindir.mkdir()
    (bindir / "python3").write_text(f'#!/bin/sh\nexec {system_python} "$@"\n', encoding="utf-8")
    (bindir / "python3").chmod(0o755)
    (bindir / "docker").write_text(f"#!{sys.executable}\n{STANDIN}", encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    log = d / "docker-calls.jsonl"
    env = {"PATH": f"{bindir}:{BARE_PATH}", "STANDIN_LOG": str(log), "STANDIN_PY_IMAGE": PY_IMAGE,
           "STANDIN_BOX": str(root), "STANDIN_PY": sys.executable, "STANDIN_SERVICES": str(root / "services"),
           "STANDIN_VOLUMES": str(d / "volumes"), "STANDIN_PGWRAP": str(pgwrap), "STANDIN_PG_BIN": str(pglocal.bindir()),
           "STANDIN_PGHOST": str(info.get("host") or ""), "STANDIN_PGPORT": str(info.get("port") or "5432"),
           "STANDIN_PGUSER": str(info.get("user") or "postgres"), "STANDIN_PGDB": str(info.get("dbname") or "postgres"),
           "STANDIN_DB_URL": f"postgresql://{info.get('user') or 'postgres'}@/{dbs['trialbox_wf']}"
                             f"?host={info.get('host')}&port={info.get('port') or '5432'}",
           "STANDIN_AUDIT": str(d / "audit-events.jsonl"), "STANDIN_SPOOL": str(d / "db-container-tmp" / "tb-backup"),
           "STANDIN_CONTAINER_SPOOL": bs.CONTAINER_SPOOL,
           "TB_SYSTEMD": "0",  # H-92: a root run on a systemd host never enables the host's own backup timers
           **{f"STANDIN_DB_{k}": v for k, v in dbs.items()}}  # fmt: skip
    yield {"root": root, "deploy": root / "deploy", "nas": nas, "env": env, "log": log, "dir": d,
           "key": d / "usb" / "backup.key", "dbs": dbs, "admin": admin, "user": str(info.get("user") or "postgres"),
           "bin": bindir, "python": system_python}  # fmt: skip
    with psycopg.connect(admin, autocommit=True) as con:
        for n in dbs.values():
            con.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')


def bare(box: dict[str, Any], cmd: str, cwd: str | Path = "/", **extra: str) -> subprocess.CompletedProcess[str]:
    """``cmd`` through /bin/sh in cron's and sudo's environment: PATH only (with the stand-ins), no HOME."""
    return subprocess.run(["/bin/sh", "-c", cmd], cwd=cwd, env={**box["env"], **extra}, capture_output=True,
                          text=True, timeout=300, check=False)  # fmt: skip


def calls(box: dict[str, Any]) -> list[dict[str, Any]]:
    if not box["log"].is_file():
        return []
    return [json.loads(x) for x in box["log"].read_text(encoding="utf-8").splitlines() if x.strip()]


def _no_import_fault(r: subprocess.CompletedProcess[str]) -> None:
    """No module the host lacks, and no setting the caller had to bring (what a bare environment breaks)."""
    text = r.stdout + r.stderr
    assert "No module named" not in text and "ModuleNotFoundError" not in text, text[-3000:]
    assert "TB_DB_URL is not set" not in text, text[-3000:]


# ---------------------------------------------------------------------------------------- the scheduled backup
def test_the_installed_cron_line_runs_the_nightly_backup_from_crons_bare_environment(box: dict[str, Any]) -> None:
    """THE TEST the integrator asked for: the line ``backup-install`` writes (rendered by the product, the log path
    only moved into the test's folder), its command run as cron runs it: cwd /, PATH only, the system python."""
    cron = box["dir"] / "cron.d"
    cfg = bs.config(box["deploy"], launch.env_file(box["deploy"] / ".env"))
    bs.install_cron(cfg, cron, box["root"], has_mta=False)
    text = (cron / bs.CRON_NAME).read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("45 4 "))
    user, command = line.split(None, 6)[5:]
    assert user == "root"
    log = box["dir"] / "trialbox-backup.log"
    command = command.replace("/var/log/trialbox-backup.log", str(log))
    r = bare(box, command)
    out = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "No module named" not in out + r.stdout + r.stderr, out[-2000:]
    assert "Traceback" not in out, out[-3000:]
    last = json.loads((box["deploy"] / "site" / "backup-last.json").read_text(encoding="utf-8"))
    assert last["ok"] and last["file"], (last, out[-2000:])  # the backup really happened
    made = box["nas"] / last["file"]["name"]
    from tools.trialbox import backup as bk

    res = bk.verify(made, box["key"])  # decrypted with the test's own key: every hash checks
    assert res, res
    runs = [c["argv"] for c in calls(box) if c["argv"][:1] == ["run"] and PY_IMAGE in c["argv"]]
    assert runs and all(DSN not in json.dumps(a) for a in runs), runs  # the box's DSN by name only
    hour = next(x for x in text.splitlines() if x.startswith("17 * "))
    r = bare(box, hour.split(None, 6)[6])
    _no_import_fault(r)
    assert "PYTHONPATH" not in "".join(x for x in text.splitlines() if not x.startswith("#"))
    assert bs.cron_old_form(text) == ""


def test_an_old_form_schedule_is_reported_and_replaced(box: dict[str, Any], tmp_path: Path) -> None:
    old = (
        'SHELL=/bin/sh\nPYTHONPATH=/opt/trialbox/libs\nMAILTO=""\n'
        "45 4 * * * root cd /opt/trialbox && { python3 -m tools.trialbox backup-nightly >> /var/log/x 2>&1 || :; }\n"
    )
    assert bs.cron_old_form(old) == "it sets PYTHONPATH"
    cron = tmp_path / "cron.d"
    cron.mkdir()
    (cron / bs.CRON_NAME).write_text(old, encoding="utf-8")
    cfg = bs.config(box["deploy"], launch.env_file(box["deploy"] / ".env"))
    bs.install_cron(cfg, cron, box["root"], has_mta=False)
    assert bs.cron_old_form((cron / bs.CRON_NAME).read_text(encoding="utf-8")) == ""
    (cron / bs.CRON_NAME).write_text(old, encoding="utf-8")
    from tools.trialbox import doctor

    inp = doctor.inputs_from(env_file=box["deploy"] / ".env", settings=None, routing=None, lake=None)
    inp.cron_dir = cron
    check = doctor.check_backup(inp)
    assert check.status != "PASS" and "old form" in check.detail and "backup-install" in check.detail, check


# ------------------------------------------------------------------------------- every host command, bare
PROBES: dict[str, list[str] | None] = {
    "doctor": ["doctor", "--preflight", "--env-file", "{deploy}/.env"],  # as RUNBOOK 01 types it on the host
    "platform-images": ["platform-images"],
    "platform-egress": ["platform-egress", "--env-file", "{deploy}/.env"],
    "eval": ["eval", "no-such-suite"],
    "backup-keygen": ["backup-keygen", "--private", "{tmp}/usb/backup.key", "--public", "{tmp}/box/backup.pub"],
    "backup": ["backup", "--to", "{tmp}/nas", "--public", "{tmp}/no.pub"],
    "backup-check": ["backup-check", "{tmp}/none.tbbak"],
    "backup-verify": ["backup-verify", "{tmp}/none.tbbak", "--key", "{tmp}/none.key"],
    "restore": ["restore", "{tmp}/none.tbbak", "--key", "{tmp}/none.key"],
    "restore-drill": ["restore-drill", "{tmp}/none.tbbak", "--key", "{tmp}/none.key", "--work", "{tmp}"],
    "backup-nightly": None,  # the cron test above runs it from the installed line
    "backup-status": ["backup-status", "--json"],
    "backup-install": ["backup-install", "--cron-dir", "{tmp}/cron.d", "--no-first-run"],
    "migrate": ["migrate"],
    "secrets": ["secrets", "status"],
    "audit-sign": ["audit-sign"],
    "anchors-compose": ["anchors-compose"],
    "finish-check": ["finish-check", "--print-anchors"],
    "omop-store": ["omop-store", "--lake", "{tmp}/lake"],
    "logs": ["logs", "prune"],
    "update": ["update", "--stage", "{tmp}/no-stage", "--summary", "{tmp}/no-summary.json"],
    "pre-start": ["pre-start", "--deploy", "{tmp}/deploy"],
    "db-up": ["db-up", "--deploy", "{tmp}/deploy"],
    "ops": ["ops", "status"],
    "watchdog": ["watchdog", "--help"],
    "support-bundle": ["support-bundle", "--help"],
    "exports": ["exports", "--audit", "{tmp}/audit", "--json"],
    "selftest": ["selftest", "--dry-run"],
    "decommission-plan": ["decommission-plan", "--json"],
    "mail": ["mail", "status", "--json"],
    "platform-day2": ["platform-day2", "--help"],
    "model": ["model", "status"],
    "provenance": ["provenance", "check"],
}


def test_the_command_table_is_the_parsers() -> None:
    """A command added to tools/trialbox/__main__.py without its line in launch.COMMANDS and a probe here fails."""
    r = subprocess.run([sys.executable, "-m", "tools.trialbox", "--help"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": f"{ROOT / 'libs'}:{ROOT}"}, check=False)  # fmt: skip
    listed = r.stdout[r.stdout.index("{") + 1 : r.stdout.index("}")].split(",")
    text = (ROOT / "tools" / "trialbox" / "__main__.py").read_text(encoding="utf-8")
    prefixed = {x.split('"')[1] for x in text.split("if args[:")[1:] if '"' in x.split("\n")[0]}
    assert set(launch.COMMANDS) == set(listed) | prefixed - {"eval"} | {"eval"}
    assert set(PROBES) == set(launch.COMMANDS)


@pytest.mark.parametrize("cmd", sorted(launch.COMMANDS))
def test_every_host_command_runs_from_a_bare_environment(box: dict[str, Any], tmp_path: Path, cmd: str) -> None:
    """THE INVARIANT (H-88, D-1089): ``--help`` of each command in both forms (``python3 -m tools.trialbox`` from
    the install folder; ``trialbox`` on PATH, install.sh's link to ``__main__.py``, run as its shebang runs it:
    ``python3 -I``, from /) and one read-only call of the installed form, in sudo's and cron's bare environment with
    the system python: no import fault; a command that needs the box image's libraries goes to its container."""
    link = tmp_path / "usr-local-bin" / "trialbox"  # install.sh's link: the install folder is found through it
    link.parent.mkdir()
    link.symlink_to(box["root"] / "tools" / "trialbox" / "__main__.py")
    trialbox = f"python3 -I {link}"
    for line, cwd in ((f"python3 -m tools.trialbox {cmd} --help", box["root"]), (f"{trialbox} {cmd} --help", "/")):
        r = bare(box, line, cwd=cwd)
        _no_import_fault(r)
        assert r.returncode == 0 and "usage" in (r.stdout + r.stderr).lower(), (line, r.stdout, r.stderr)
    probe = PROBES[cmd]
    if probe is None:
        return
    before = len(calls(box))
    args = [a.format(tmp=tmp_path, deploy=box["deploy"]) for a in probe]
    r = bare(box, f"{trialbox} {shlex.join(args)}", cwd=tmp_path)
    _no_import_fault(r)
    runs = [c["argv"] for c in calls(box)[before:] if c["argv"][:1] == ["run"] and PY_IMAGE in c["argv"]]
    need = launch.COMMANDS[cmd]
    if need.where == launch.IMAGE and "--help" not in args:
        assert runs, f"{cmd} needs {need.libs} and did not go to the box image"
        a = runs[0]
        assert a[a.index("--network") + 1] == need.network and a[a.index("--pull") + 1] == "never", a
        assert a[a.index("--cap-drop") + 1] == "ALL" and "--privileged" not in a, a
        assert not any("docker.sock" in x for x in a), a
        assert DSN not in json.dumps(a), a
        # the box's settings (its database password among them) only to a command that has a network
        assert ("--env-file" in a) == (need.network != "none"), a
    elif cmd != "restore-drill":
        assert not runs, f"{cmd} needs nothing of the image and went to it: {runs}"


# ----------------------------------------------------------------- the caller's path and settings never win
PLANTED = "raise SystemExit('PLANTED tb_common from the caller')\n"


def test_the_callers_path_and_settings_never_win(box: dict[str, Any], tmp_path: Path) -> None:
    """A caller's PYTHONPATH with a planted tb_common, and a caller's TB_DB_URL and TB_IMAGE: the tool takes its
    libs from its own folder and its settings from the box's deploy/.env."""
    planted = tmp_path / "planted"
    (planted / "tb_common").mkdir(parents=True)
    (planted / "tb_common" / "__init__.py").write_text(PLANTED, encoding="utf-8")
    for lib in ("zstandard", "cryptography"):  # all a command needs: only the box image's may count
        (planted / f"{lib}.py").write_text(f"raise SystemExit('PLANTED {lib}')\n", encoding="utf-8")
    caller = {"PYTHONPATH": str(planted), "TB_DB_URL": "postgresql://x:caller-secret@caller:5432/x",
              "TB_IMAGE": "caller/image:evil"}  # fmt: skip
    r = bare(box, "python3 -m tools.trialbox backup-status --json", cwd=box["root"], **caller)
    _no_import_fault(r)
    assert "PLANTED" not in r.stdout + r.stderr, r.stderr
    before = len(calls(box))
    r = bare(box, f"python3 -m tools.trialbox backup-check {tmp_path}/none.tbbak", cwd=box["root"], **caller)
    assert "PLANTED" not in r.stdout + r.stderr, r.stderr
    runs = [c for c in calls(box)[before:] if c["argv"][:1] == ["run"]]
    assert runs and PY_IMAGE in runs[0]["argv"] and "caller/image:evil" not in runs[0]["argv"], runs
    assert all(c["env_db_url"] != caller["TB_DB_URL"] for c in calls(box)[before:]), "the caller's DSN reached docker"
    env = dict(caller)
    launch.box_settings(env, box["deploy"])
    assert env["TB_DB_URL"] == DSN and env["TB_IMAGE"] == PY_IMAGE
    path = launch.own_path([str(planted), "", "/usr/lib/python3"], {"PYTHONPATH": str(planted)})
    assert path[:2] == list(launch.OWN_PATH) and "" not in path
    assert launch.caller_entries({"PYTHONPATH": f"{planted}:{launch.ROOT / 'services'}"}) == {str(planted)}


def test_the_container_keeps_the_exit_code_and_puts_no_secret_on_the_command_line(
    box: dict[str, Any], tmp_path: Path
) -> None:
    argv = launch.container_argv(["backup-verify", "f.tbbak", "--key", "/media/usb/k.key"],
                                 launch.COMMANDS["backup-verify"], {"TB_IMAGE": PY_IMAGE, "TB_DB_URL": DSN},
                                 tmp_path, 1000, 1000)  # fmt: skip
    assert argv[argv.index("--network") + 1] == "none" and argv[argv.index("--pull") + 1] == "never"
    assert argv[argv.index("--user") + 1] == "1000:1000" and DSN not in " ".join(argv) and "--env-file" not in argv
    assert f"{tmp_path}/f.tbbak:{tmp_path}/f.tbbak:ro" in argv and "/media/usb/k.key:/media/usb/k.key:ro" in argv
    assert argv[-4:] == ["--key", "/media/usb/k.key", "--deploy", str(launch.DEPLOY)]
    db = launch.container_argv(["backup", "--to", str(tmp_path / "nas")], launch.COMMANDS["backup"], {}, tmp_path,
                               0, 0)  # fmt: skip
    assert db[db.index("--network") + 1] == launch.DB_NETWORK and f"{tmp_path}/nas:{tmp_path}/nas" in db
    (tmp_path / "not-a-backup.tbbak").write_bytes(b"not a backup")
    r = bare(box, f"python3 -m tools.trialbox backup-check {tmp_path}/not-a-backup.tbbak", cwd=box["root"])
    assert r.returncode == 1 and "backup-check" in r.stderr, (r.returncode, r.stderr)  # the container's own exit


# ------------------------------------------------------------------------------- the restore drill, sudo typed
SUDO = """#!/bin/sh
# sudo: the caller's environment is dropped (env_reset); secure_path, HOME, the user's names and TERM are set
exec env -i PATH="{path}" HOME=/root USER=root LOGNAME=root SHELL=/bin/sh TERM=dumb SUDO_USER=hospital-it "$@"
"""


def test_the_drill_typed_with_sudo_as_the_runbook_writes_it_runs_from_a_bare_environment(
    box: dict[str, Any], tmp_path: Path
) -> None:
    """The bench's step 8 ("No module named 'tb_common'", then "TB_DB_URL is not set"): ``sudo trialbox
    restore-drill <file> --key <key>`` (RUNBOOK 5; ``trialbox`` is install.sh's link to ``__main__.py``, run by its
    own shebang), with sudo dropping the caller's environment and a caller's ``TB_DB_URL`` and ``PYTHONPATH``
    planted: the drill takes the box's settings, its image steps run in the box image, and it passes."""
    from psycopg.conninfo import make_conninfo

    from tools.trialbox import backup as bk

    url = box["env"]["STANDIN_DB_URL"]
    hapi = make_conninfo(box["admin"], dbname=box["dbs"]["hapi"])
    made = bk.backup([tmp_path / "nas"], box["deploy"] / "secrets" / "backup.pub",
                     env={"TB_DB_URL": url, "TB_HAPI_DB_URL": hapi, **pg_client.env()}, dirs={})[0]  # fmt: skip
    root = tmp_path / "opt" / "trialbox"  # an install folder of its own: the box's URL names this server's owner
    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "site", ".env")
    for sub in ("tools", "libs", "deploy"):
        shutil.copytree(box["root"] / sub, root / sub, ignore=skip, symlinks=True)
    (root / "services").symlink_to(ROOT / "services")
    env_text = (
        f"TB_ENV=TEST\nTB_IMAGE={PY_IMAGE}\nTB_DB_URL=postgresql://{box['user']}@db:5432/{box['dbs']['trialbox_wf']}\n"
    )
    (root / "deploy" / ".env").write_text(env_text, encoding="utf-8")
    _explicit_modes(tmp_path, root)  # H-139 (item 5, ruled b)
    bindir = tmp_path / "sudo-bin"
    bindir.mkdir()
    bindir.chmod(0o755)
    secure = f"{bindir}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    exports = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in box["env"].items() if k.startswith("STANDIN_"))
    (bindir / "sudo").write_text(SUDO.format(path=secure), encoding="utf-8")
    (bindir / "docker").write_text(f'#!/bin/sh\n{exports}exec {box["bin"] / "docker"} "$@"\n', encoding="utf-8")
    for name in ("sudo", "docker"):
        (bindir / name).chmod(0o755)
    link = tmp_path / "usr-local-bin" / "trialbox"  # install.sh's link
    link.parent.mkdir()
    link.parent.chmod(0o755)  # H-139 (item 5, ruled b)
    link.symlink_to(root / "tools" / "trialbox" / "__main__.py")
    # its shebang's interpreter (`python3 -I`), the stand-in system python, not the test host's /usr/bin/python3
    (bindir / "trialbox").write_text(f'#!/bin/sh\nexec {box["python"]} -I {link} "$@"\n', encoding="utf-8")
    (bindir / "trialbox").chmod(0o755)
    audit = Path(box["env"]["STANDIN_AUDIT"])
    audit.unlink(missing_ok=True)
    before = len(calls(box))
    caller = {"PATH": secure, "TB_DB_URL": "postgresql://x@caller-host:5432/x", "PYTHONPATH": str(tmp_path)}
    cmd = shlex.join(["sudo", "trialbox", "restore-drill", str(made), "--key", str(box["key"]), "--work",
                      str(tmp_path)])  # fmt: skip
    r = subprocess.run(["/bin/sh", "-c", cmd], cwd=tmp_path, env=caller, capture_output=True, text=True, timeout=600,
                       check=False)  # fmt: skip
    _no_import_fault(r)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    res = json.loads(r.stdout)
    assert res["ok"] and res["scratch_dropped"] and res["unpacked_removed"], res
    assert set(res["databases"]) == {"trialbox_wf", "hapi"}
    assert (root / "deploy" / "site" / "backup-verified.json").is_file()
    assert [json.loads(x)["event"] for x in audit.read_text(encoding="utf-8").splitlines()] == ["backup.restore_drill"]
    argvs = [c["argv"] for c in calls(box)[before:]]
    assert "caller-host" not in json.dumps(argvs) and str(box["key"]) not in json.dumps(audit.read_text())
    images = [a for a in argvs if a[:1] == ["run"]]
    assert images and all(a[a.index("--pull=never")] and PY_IMAGE in a for a in images), images


def test_the_box_file_wins_except_for_the_module_forms_drill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-1089 (3): the box's deploy/.env wins over the caller in every form, but ``python -m tools.trialbox
    restore-drill`` keeps the caller's connection (#1305, review item 12); the installed ``trialbox restore-drill``
    takes the box's."""
    (tmp_path / ".env").write_text(f"TB_DB_URL={DSN}\nTB_IMAGE={PY_IMAGE}\n", encoding="utf-8")
    (tmp_path / ".env").chmod(0o600)  # H-139 (item 5, ruled b): as install.sh makes it, whatever the umask
    monkeypatch.setattr(launch, "DEPLOY", tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    caller = "postgresql://x@caller-host:5432/x"
    for args, installed, want in ((["restore-drill", "f", "--key", "k"], False, caller),
                                  (["restore-drill", "f", "--key", "k"], True, DSN),
                                  (["backup-status"], False, DSN), (["backup-nightly"], True, DSN)):  # fmt: skip
        env = {"TB_DB_URL": caller}
        assert launch.enter(args, env, installed=installed) is None
        assert env["TB_DB_URL"] == want, (args, installed, env)
    env = {"TB_ENV": "DEV"}  # a TB_ENV the box's file does not set is never the caller's (PRODUCTION applies)
    (tmp_path / ".env").write_text(f"TB_DB_URL={DSN}\n", encoding="utf-8")
    (tmp_path / ".env").chmod(0o600)
    assert launch.enter(["backup-status"], env) is None and "TB_ENV" not in env
    (tmp_path / ".env").unlink()
    env = {"TB_ENV": "DEV"}
    assert launch.enter(["backup-status"], env) is None and "TB_ENV" not in env  # no file: no caller TB_ENV either


def test_the_runtime_and_the_image_are_never_the_callers(box: dict[str, Any], tmp_path: Path) -> None:
    """Review M1: install.sh writes neither TB_DOCKER nor TB_IMAGE to deploy/.env. With a box file that has neither
    and a caller (``sudo -E``, an ``env_keep`` rule) that sets both, the caller's program never runs as the runtime
    and the caller's image is never given the box's settings: the defaults are used."""
    env_file = box["deploy"] / ".env"
    kept = env_file.read_text(encoding="utf-8")
    marker = tmp_path / "caller-runtime-ran"
    evil = tmp_path / "evil-docker"
    evil.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    evil.chmod(0o755)
    try:
        env_file.write_text("".join(x + "\n" for x in kept.splitlines() if not x.startswith(("TB_IMAGE=", "TB_DOCKER="))),
                            encoding="utf-8")  # fmt: skip
        before = len(calls(box))
        (tmp_path / "f.tbbak").write_bytes(b"not a backup")
        caller = {"TB_DOCKER": str(evil), "TB_IMAGE": "caller/evil:1"}
        r = bare(box, f"python3 -I {box['root'] / 'tools' / 'trialbox' / '__main__.py'} backup-check {tmp_path}/f.tbbak",
                 cwd=tmp_path, **caller)  # fmt: skip
        _no_import_fault(r)
        assert not marker.exists(), "the caller's TB_DOCKER ran"
        runs = [c["argv"] for c in calls(box)[before:] if c["argv"][:1] == ["run"]]
        assert runs and launch.DEFAULT_IMAGE in runs[0] and "caller/evil:1" not in json.dumps(runs), runs
    finally:
        env_file.write_text(kept, encoding="utf-8")


def test_a_box_file_that_cannot_be_trusted_stops_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review L1, L2: a deploy/.env that is there but is a folder, a dangling link, unreadable, owned by another user
    or writable by group or others stops the command (exit 2, nothing run, no value said); none there is no setting.
    (Lane R's #1371 keeps PRODUCTION in these cases instead and goes on: here the review's rule, exit 2.)"""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(launch, "DEPLOY", tmp_path)
    assert launch.box_file(tmp_path) == {}
    f = tmp_path / ".env"

    def refused(why: str) -> None:
        with pytest.raises(launch.BoxFileError, match=why):
            launch.box_file(tmp_path)
        assert launch.enter(["backup-status"], {"TB_ENV": "DEV"}) == 2

    f.mkdir()
    refused("not a file")
    f.rmdir()
    f.symlink_to(tmp_path / "nowhere")
    refused("cannot be read")
    f.unlink()
    f.write_text(f"TB_DB_URL={DSN}\n", encoding="utf-8")
    f.chmod(0o664)
    refused("group or others")
    f.chmod(0o600)
    assert launch.box_file(tmp_path) == {"TB_DB_URL": DSN}
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    refused("cannot be read")
    monkeypatch.undo()
    monkeypatch.setattr(launch, "DEPLOY", tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    if os.geteuid() == 0:
        os.chown(f, 4242, 4242)
    else:
        monkeypatch.setattr(os, "geteuid", lambda: 4242)
    refused("neither root nor this user")


def test_the_doctor_in_the_image_still_sees_the_gateways_missing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    servers: dict[str, str],  # noqa: F811
) -> None:
    """Train 129, rehearsal step 26 (``missing-key``): the doctor runs in the box image with ``--env-file
    deploy/.env -e TB_LLM_API_KEY= -e TB_LLM_API_KEY_FILE=<the gateway's key file>`` and the box's deploy folder
    mounted. With the key file emptied, its serving check must FAIL with "refused the key (HTTP 401)", whatever
    deploy/.env holds: inside a container the launcher leaves the environment as it was given (D-450, D-1089)."""
    from tools.trialbox import doctor

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_LLM_API_KEY={KEY}\n", encoding="utf-8")  # the box's working copy
    (deploy / ".env").chmod(0o600)
    key_file = tmp_path / "llm.key"
    key_file.write_text("", encoding="utf-8")  # the drill: the gateway's key file emptied
    mark = tmp_path / "dockerenv"
    mark.write_text("", encoding="utf-8")
    monkeypatch.setattr(launch, "DEPLOY", deploy)
    monkeypatch.setattr(launch, "CONTAINER_MARKS", (str(mark),), raising=False)
    monkeypatch.setattr(launch, "IMAGE_ROOT", str(launch.ROOT), raising=False)  # the image's /app
    monkeypatch.setattr(sys, "path", list(sys.path))
    env = {**_inputs(_pins(tmp_path), servers, key=None).env, "TB_LLM_API_KEY": "",
           "TB_LLM_API_KEY_FILE": str(key_file)}  # fmt: skip
    assert launch.enter(["doctor", "--serving"], env) is None
    c = doctor.check_serving(doctor.DoctorInputs(env=env))
    assert c.status == "FAIL" and "refused the key (HTTP 401)" in c.detail, c


def test_a_container_that_is_not_the_box_image_keeps_the_host_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review F1: the rehearsal's box host is itself a container; its `trialbox` calls must still take the box's
    file over the caller, drop a caller's TB_ENV and stop on an untrusted file, as a site's host does. Only the box's
    own image (a container, from /app) leaves its environment as given."""
    mark = tmp_path / "dockerenv"
    mark.write_text("", encoding="utf-8")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_DB_URL={DSN}\n", encoding="utf-8")
    (deploy / ".env").chmod(0o600)
    monkeypatch.setattr(launch, "CONTAINER_MARKS", (str(mark),))
    monkeypatch.setattr(launch, "DEPLOY", deploy)
    monkeypatch.setattr(sys, "path", list(sys.path))
    env = {"TB_DB_URL": "postgresql://x@caller-host:5432/x", "TB_ENV": "DEV"}
    assert launch.enter(["backup-status"], env) is None
    assert env["TB_DB_URL"] == DSN and "TB_ENV" not in env, env
    assert str(launch.ROOT) != launch.IMAGE_ROOT and not launch.in_box_image()
    (deploy / ".env").chmod(0o666)
    assert launch.enter(["backup-status"], {}) == 2  # the untrusted-file stop holds there too
    monkeypatch.setattr(launch, "IMAGE_ROOT", str(launch.ROOT))  # the same container from the image's folder
    assert launch.in_box_image() and launch.enter(["backup-status"], env := {"TB_ENV": "DEV"}) is None
    assert env == {"TB_ENV": "DEV"}
