"""H-100: the live restore starts from the host (the MVP walk's step 8 on the bench host).

Three gaps, each held here on the real entry point with the repo's stand-in for the container engine:

1. ``backup-nightly --deploy deploy`` (a relative folder) bound ``deploy/secrets/backup.pub`` and the dump folder by
   relative path, which the container engine reads as a volume name: every bind source is absolute now.
2. ``trialbox restore`` from the host ran in a plain one-off container with no hapi URL, no volume and no database
   client: it now runs in the backup image the way the nightly's job does, with the database URLs taken from the
   box's own ``deploy/.env`` (a caller's exported variable changes nothing; no password on a command line).
3. The backup image carries the database client tools (pinned, held, checked) and the superuser URL comes from the
   box, never from the caller.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_host_commands_own_environment as h88
from tests.unit.test_backup_schedule import FakeBox
from tools.trialbox import backup as bk
from tools.trialbox import update

# the h88 bare box (a copy of the install folder, the system python, the stand-in runtime, the test cluster's two
# databases) and its host marks, as fixtures of this module too
box = h88.box
system_python = h88.system_python
_a_host = h88._a_host


def url(user: str, pw: str, rest: str) -> str:
    """A database URL with a made-up password, built so no scan reads a credential in this file."""
    return "postgresql://" + user + ":" + pw + "@" + rest


def _mounts(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]


# ------------------------------------------------------------------------------------------------ gap 1
def test_nightly_with_a_relative_deploy_binds_only_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup_schedule as bs

    deploy = tmp_path / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    bk.keygen(tmp_path / "it.key", deploy / "secrets" / "backup.pub")
    nas = tmp_path / "nas"
    (deploy / ".env").write_text(
        f"TB_DB_URL={url('trialbox', 'zq~7!Kd~pw', 'db:5432/trialbox_wf')}\nTB_SITE_ID=CGMH\nTB_ENV=TEST\n"
        f"TB_BACKUP_TARGETS={nas}\nTB_BACKUP_RESTIC=off\nTB_BACKUP_JOB_WAIT_S=0\nTB_DOCKER_VOLUMES={tmp_path / 'volumes'}\n",
        encoding="utf-8",
    )
    for k in [k for k in os.environ if k.startswith("TB_")]:
        monkeypatch.delenv(k)
    fake = FakeBox()
    monkeypatch.setattr(update, "run_cmd", fake)  # the real ComposeOps and ComposeBox, the engine stood in for
    monkeypatch.chdir(tmp_path)
    bs.main_nightly(Path("deploy"))  # as typed from the install folder: `trialbox backup-nightly --deploy deploy`
    runs = [c for c in fake.calls if c[:2] == ["docker", "run"]]
    assert runs, fake.calls
    sources = [m.split(":", 1)[0] for m in _mounts(runs[0])]
    binds = [s for s in sources if not s.startswith("trialbox_")]  # named volumes are names
    assert binds and all(os.path.isabs(s) for s in binds), sources
    assert f"{deploy / 'secrets' / 'backup.pub'}:/in/backup.pub:ro" in _mounts(runs[0])
    assert any(s.startswith(str(deploy / ".backup-")) for s in binds), binds


# ------------------------------------------------------------------------------------------------ gap 2
PW = "zq~7!Kd@/pw"  # synthetic; a "@" and "/" that must stay the password inside a URL
CALLER = {"TB_DB_URL": url("x", "caller-secret", "caller:5432/x"), "TB_HAPI_DB_URL": "postgresql://x@caller/x",
          "TB_DB_ROLES_CMD": "touch /tmp/caller-ran", "TB_DOCKER": "caller-docker", "TB_COMPOSE": "caller-compose",
          "TB_BACKUP_IMAGE": "caller/evil:1", "TB_BACKUP_PUBKEY": "/caller/pub", "TB_RESTORE_KEEP_DIR": "/caller/keep",
          "POSTGRES_PASSWORD": "caller-pw"}  # fmt: skip


class Recorder:
    """The box's commands (compose ps, stop, up): records them; ``running`` is what compose says runs."""

    def __init__(self, running: list[str] | None = None, up_fails: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.running = ["db"] if running is None else running
        self.up_fails = up_fails

    def __call__(self, argv: list[str], **kw: object) -> str:
        self.calls.append(list(argv))
        if "ps" in argv:
            return "\n".join(self.running)
        if "stop" in argv:
            self.running = ["db"]
        if "up" in argv:
            if self.up_fails:
                raise update.UpdateFailed("compose up --wait: service console is unhealthy")
            self.running = ["db", "console", "orchestrator"]
        return ""


def _box(tmp_path: Path, extra: str = "TB_KEK_PASSPHRASE=synthetic-kek\n") -> Path:
    deploy = tmp_path / "opt" / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    (deploy / "secrets" / "backup.pub").write_text("synthetic public key", encoding="utf-8")
    (deploy / "docker" / "db-init").mkdir(parents=True)
    (deploy / "docker" / "db-init" / "30-service-roles.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    vols = tmp_path / "volumes"
    for v in ("audit-data", "lake-data", "tb-secrets"):
        (vols / f"trialbox_{v}" / "_data").mkdir(parents=True)
    (deploy / ".env").write_text(
        f"TB_ENV=TEST\nTB_SITE_ID=CGMH\nTB_DB_URL={url('trialbox', 'wf-pw', 'db:5432/trialbox_wf')}\n"
        f"POSTGRES_PASSWORD={PW}\nPOSTGRES_WF_PASSWORD=wf-pw\nTB_DB_PW_LAKE=lake-pw\nTB_DOCKER_VOLUMES={vols}\n{extra}",
        encoding="utf-8",
    )
    (tmp_path / "nas").mkdir()
    (tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak").write_bytes(b"synthetic")
    (tmp_path / "usb").mkdir()
    (tmp_path / "usb" / "backup.key").write_text("synthetic private key", encoding="utf-8")
    return deploy


def _restore(
    deploy: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rec: Recorder,
    out: str = "{}",
    code: int = 0,
    *more: str,
    file: bool = True,
) -> tuple[int, list[tuple[list[str], dict[str, str]]]]:
    """``trialbox restore`` as installed (``main(..., installed=True)``), with a caller who exported ``CALLER``; the
    box's commands and the restore container stood in for. Returns the exit code and each container call."""
    from tools.trialbox import __main__ as cli
    from tools.trialbox import box_restore

    seen: list[tuple[list[str], dict[str, str]]] = []

    def call(argv: list[str], values: dict[str, str]) -> tuple[int, str]:
        seen.append((argv, values))
        return code, out

    monkeypatch.setattr(update, "run_cmd", rec)
    monkeypatch.setattr(box_restore, "_call", call)
    for k, v in CALLER.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    given = [str(tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak")] if file else []
    argv = ["restore", *given, "--key", "usb/backup.key", "--yes", "--deploy", str(deploy), *more]
    return cli.main(argv, installed=True), seen


def _value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_the_host_restore_takes_every_url_from_the_box_and_none_from_the_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE INVARIANT (H-100): the restore typed on the host runs in the backup image with the database URLs the
    nightly's job gets from the same deploy/.env; the caller's exported URLs, role command, runtime, compose,
    image, key and copy folder change nothing; no password is on any command line."""
    from tools.trialbox import box_restore

    deploy = _box(tmp_path)
    rec = Recorder()
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--dir", "host=hostpart/deploy")
    assert code == 0 and len(seen) == 1, seen
    argv, values = seen[0]
    assert argv[0] == "docker" and "trialbox-backup:1.0.0" in argv and "caller/evil:1" not in argv
    assert all(c[0] == "docker" and c[1] == "compose" for c in rec.calls), (
        rec.calls
    )  # the box's runtime, not the caller's
    # the job's own URLs (update.ComposeBox._backup_container, from the same file): the same server, user and database
    job: dict[str, str] = {}
    box = update.ComposeBox(deploy, lambda argv, env=None, **kw: job.update(env or {}) or "")
    box._backup_container(tmp_path, deploy / "secrets" / "backup.pub", [str(tmp_path / "nas")])
    from urllib.parse import quote

    from psycopg.conninfo import conninfo_to_dict

    for k in ("TB_DB_URL", "TB_HAPI_DB_URL"):
        assert conninfo_to_dict(values[k]) == conninfo_to_dict(job[k].replace(PW, quote(PW, safe=""))), k
    assert conninfo_to_dict(values["TB_HAPI_DB_URL"])["password"] == PW  # quoted in the URL, whole again when read
    assert values["TB_DB_ROLES_CMD"] == box_restore.ROLES_CMD
    assert values["TB_DB_PW_LAKE"] == "lake-pw" and values["TB_DB_PW_CONSOLE"] == "wf-pw"  # compose's own fallbacks
    assert values["TB_DB_PW_FHIR_STORE"] == ""  # D-541: no fallback
    assert "TB_KEK_PASSPHRASE" not in values  # the KEK only with --restic-from-box
    for name in values:
        assert ["-e", name] == argv[argv.index(name) - 1 : argv.index(name) + 1], name  # by name only
    text = " ".join(argv)
    for secret in (PW, "wf-pw", "lake-pw", "caller-secret", "caller-pw", "/caller/"):
        assert secret not in text, secret
    assert _value(argv, "--public") == str(deploy / "secrets" / "backup.pub")
    assert _value(argv, "--keep-to") == str(deploy / "pre-restore")
    assert "--services-stopped" in argv and "--yes" in argv
    mounts = _mounts(argv)
    vols = tmp_path / "volumes"
    for v in ("audit-data", "lake-data", "tb-secrets"):  # each volume's folder read-write: its _data moves within it
        assert f"{vols / f'trialbox_{v}'}:/var/lib/docker/volumes/trialbox_{v}" in mounts
    assert "audit=/var/lib/docker/volumes/trialbox_audit-data/_data" in argv
    assert f"host={tmp_path / 'hostpart' / 'deploy'}" in argv  # --dir, made absolute, its parent bound
    assert f"{tmp_path / 'hostpart'}:{tmp_path / 'hostpart'}" in mounts
    assert f"{tmp_path / 'usb' / 'backup.key'}:{tmp_path / 'usb' / 'backup.key'}:ro" in mounts
    assert f"{deploy / 'docker/db-init/30-service-roles.sh'}:{box_restore.ROLES_IN}:ro" in mounts
    assert all(os.path.isabs(m.split(":", 1)[0]) for m in mounts), mounts
    assert _value(argv, "--network") == "trialbox-net" and _value(argv, "--pull") == "never"


def test_the_running_services_refusal_stays_without_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    deploy = _box(tmp_path)
    rec = Recorder(running=["db", "console", "orchestrator"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec)
    assert code == 2 and not seen
    assert "these services are running: console, orchestrator" in capsys.readouterr().err
    assert not any("stop" in c for c in rec.calls)  # nothing was stopped or changed
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    assert (
        code == 0 and seen and ["docker", "compose", "--project-directory", str(deploy), "stop", "console"] in rec.calls
    )
    assert rec.calls.index(next(c for c in rec.calls if "stop" in c)) < len(rec.calls)
    rec = Recorder(running=None)
    rec.running = []  # compose answers nothing runs: the restore goes on
    assert _restore(deploy, tmp_path, monkeypatch, rec)[0] == 0
    assert _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0)[0] == 0
    from tools.trialbox import __main__ as cli

    assert cli.main(["restore", "f.tbbak", "--key", "k", "--deploy", str(deploy)], installed=True) == 2


@pytest.mark.parametrize(
    ("code", "hold", "starts"),
    [
        (0, "released", True),
        (4, "held", True),
        (4, "NOT set: OperationalError", False),
        (3, "held", False),
        (1, "", False),
    ],
)
def test_restart_starts_the_services_only_after_a_complete_or_held_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], code: int, hold: str,
    starts: bool,
) -> None:  # fmt: skip
    import json

    deploy = _box(tmp_path)
    rec = Recorder(running=["db", "console"])
    got, seen = _restore(deploy, tmp_path, monkeypatch, rec, json.dumps({"hold": hold}), code, "--restart")
    assert len(seen) == 1  # the restore ran once, whatever it then says
    ups = [c for c in rec.calls if "up" in c]
    assert bool(ups) is starts, rec.calls
    if starts:
        assert got == code and ups[0][-4:] == ["-d", "--wait", "--wait-timeout", "600"]
        assert "healthy" in capsys.readouterr().err
    else:
        assert got == code and "the services stay stopped" in capsys.readouterr().err


def test_a_service_that_does_not_come_back_healthy_fails_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = _box(tmp_path)
    got, _ = _restore(deploy, tmp_path, monkeypatch, Recorder(up_fails=True), "{}", 0, "--restart")
    assert got == 1 and "did not all come back healthy" in capsys.readouterr().err


def test_last_is_the_backup_the_nightly_recorded_good_on_a_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    import json

    from tools.trialbox import backup_schedule as bs

    deploy = _box(tmp_path, f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\n")
    f = tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    got, seen = _restore(deploy, tmp_path, monkeypatch, Recorder(), "{}", 0, "--last", file=False)
    assert got == 2 and not seen and "--last: no good backup" in capsys.readouterr().err
    bs.sidecar(f).write_text(f"{sha}  {f.name}\n", encoding="utf-8")
    (deploy / "site").mkdir()
    (deploy / "site" / "backup-last.json").write_text(json.dumps(
        {"good_file": {"name": f.name, "bytes": f.stat().st_size, "sha256": sha}}), encoding="utf-8")  # fmt: skip
    got, seen = _restore(deploy, tmp_path, monkeypatch, Recorder(), "{}", 0, "--last", file=False)
    assert got == 0 and str(f) in seen[0][0], seen
    from tools.trialbox import __main__ as cli

    assert cli.main(["restore", str(f), "--last", "--key", "k", "--yes", "--deploy", str(deploy)], installed=True) == 2


def test_the_roles_step_signs_in_as_the_superuser_of_the_url_with_its_password_in_the_environment_only() -> None:
    from tools.trialbox import box_restore

    ran: list[tuple[list[str], dict[str, str]]] = []

    class Done:
        returncode = 0

    def run(argv: list[str], env: dict[str, str], check: bool) -> Done:
        ran.append((argv, env))
        return Done()

    url = box_restore.job_db_env({"POSTGRES_PASSWORD": PW})["TB_HAPI_DB_URL"]
    assert box_restore.roles({"TB_HAPI_DB_URL": url, "TB_DB_PW_LAKE": "lake-pw"}, run) == 0
    argv, env = ran[0]
    assert argv == ["sh", box_restore.ROLES_IN] and PW not in " ".join(argv)
    assert env["PGHOST"] == "db" and env["PGPORT"] == "5432" and env["POSTGRES_USER"] == "hapi"
    assert env["PGPASSWORD"] == PW and env["TB_DB_PW_LAKE"] == "lake-pw"
    assert box_restore.roles({"TB_HAPI_DB_URL": ""}, run) == 2 and len(ran) == 1


# ------------------------------------------------------------------------------------------------ gap 3
ROOT = Path(__file__).resolve().parents[2]
BACKUP_IMAGE = ROOT / "deploy" / "docker" / "backup.Dockerfile"


def _final_stage(text: str) -> str:
    return text[text.rindex("\nFROM ") :]


def test_the_backup_image_carries_the_database_client_tools_pinned_held_and_checked() -> None:
    """The restore's container (and its copy of the box before it) restores and dumps with the client tools of the
    server's own major: each package at an exact version from the db image's own base and package source, held,
    its installed version and each tool's major checked when the image builds; the image still runs as its user."""
    import json
    import re

    text = BACKUP_IMAGE.read_text(encoding="utf-8")
    lock = json.loads((ROOT / "deploy" / "images.lock").read_text(encoding="utf-8"))["images"]["db"]
    base = re.search(r"^FROM (\S+)@(sha256:[0-9a-f]{64}) AS pgdg$", text, re.M)
    assert base and base.group(1) == lock["base"]["ref"] and base.group(2) == lock["base"]["digest"], base
    final = _final_stage(text)
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", final, re.M))
    assert args["PG_CLIENT_MAJOR"] == str(lock["postgres_major"])
    pins = {"postgresql-client-${PG_CLIENT_MAJOR}": "PG_CLIENT_VERSION", "libpq5": "LIBPQ_VERSION",
            "postgresql-client-common": "PG_CLIENT_COMMON_VERSION"}  # fmt: skip
    for pkg, var in pins.items():
        assert re.fullmatch(r"[0-9.]+(-\d+)?\.pgdg13\+\d+", args[var]), (var, args[var])  # PGDG's Debian 13 build
        var_ref = "${" + var + "}"
        assert '"' + pkg + "=" + var_ref + '"' in final, pkg  # installed at that version
        named = '"' + pkg + '"' if "$" in pkg else pkg
        check = "test \"$(dpkg-query -W -f '${Version}' " + named + ')" = "' + var_ref + '"'
        assert check in final, (pkg, check)  # checked after the install
    assert args["PG_CLIENT_VERSION"].startswith(args["PG_CLIENT_MAJOR"] + ".")
    assert 'apt-mark hold "postgresql-client-${PG_CLIENT_MAJOR}" libpq5 postgresql-client-common;' in final
    assert "for tool in pg_restore pg_dump psql; do" in final and '"$tool (PostgreSQL) ${PG_CLIENT_MAJOR}."*' in final
    assert 'test "$VERSION_CODENAME" = trixie' in final  # the package source's suite
    assert "COPY --from=pgdg /usr/local/share/keyrings/postgres.gpg.asc" in final  # the db base's own signing key
    assert re.findall(r"^USER (\S+)$", final, re.M)[-1] == "tb"  # never left running as root
    assert "apt-get install" not in final.replace("--no-install-recommends", "")  # every install is the pinned one


def test_the_restore_runs_in_the_box_files_backup_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    deploy = _box(tmp_path, "TB_BACKUP_IMAGE=trialbox-backup:1.0.1\nTB_IMAGE=trialbox-py:1.0.1\n")
    code, seen = _restore(deploy, tmp_path, monkeypatch, Recorder())
    argv = seen[0][0]
    assert code == 0 and "trialbox-backup:1.0.1" in argv and "trialbox-py:1.0.1" not in argv
    assert "caller/evil:1" not in argv  # the caller exported TB_BACKUP_IMAGE too


# ------------------------------------------------------------------------------------------------ the real path
#: The restore container on this test host: the release's backup image is this interpreter with the product's path;
#: each bind (``-v src:dst``) maps ``dst`` back to ``src`` in the arguments and the values; the URLs the host passed
#: by name are recorded (to prove they are the box's), then pointed at the test cluster's two databases, as the
#: database network resolves ``db`` on a box. Anything else goes to the h88 stand-in (compose ps, stop, up ...).
RESTORE_STANDIN = r"""
import json, os, subprocess, sys
argv = sys.argv[1:]
if not (argv[:1] == ["run"] and "restore" in argv and os.environ["STANDIN_PY_IMAGE"] in argv):
    os.execv(os.environ["STANDIN_DOCKER"], [os.environ["STANDIN_DOCKER"], *argv])
img = argv.index(os.environ["STANDIN_PY_IMAGE"])
opts, rest = argv[1:img], argv[img + 1:]
maps, names = [], []
for k, v in zip(opts, opts[1:]):
    if k == "-v":
        src, dst = v.split(":")[:2]
        assert src.startswith("/"), v  # never a relative bind: the engine would read it as a volume name
        maps.append((dst, src))
    if k == "-e" and "=" not in v:
        names.append(v)
maps.sort(key=lambda m: -len(m[0]))
def mapped(x):
    for dst, src in maps:
        if dst in x:
            return x.replace(dst, src)
    return x
with open(os.environ["STANDIN_RECEIVED"], "w") as fh:  # the test's synthetic settings only
    json.dump({n: os.environ.get(n) for n in names} | {"argv": argv}, fh)
env = {"PATH": os.environ["STANDIN_RESTORE_PATH"], "PYTHONPATH": os.environ["STANDIN_RESTORE_PYTHONPATH"]}
env.update({n: mapped(os.environ[n]) for n in names if n in os.environ})
env["TB_DB_URL"], env["TB_HAPI_DB_URL"] = os.environ["STANDIN_WF_URL"], os.environ["STANDIN_HAPI_URL"]
assert rest[:3] == ["python", "-m", "tools.trialbox"], rest
code = "import sys; from tools.trialbox.__main__ import main; sys.exit(main(sys.argv[1:]))"
sys.exit(subprocess.run([os.environ["STANDIN_PY"], "-c", code, *[mapped(x) for x in rest[3:]]],
                        cwd=os.environ["STANDIN_BOX"], env=env).returncode)
"""

ROLES_STUB = """#!/bin/sh
# the service-role script's stand-in: what it was given (names and whether set; never a value)
printf 'user=%s host_set=%s lake_set=%s fhir=%s\\n' "$POSTGRES_USER" "${PGHOST:+yes}" "${TB_DB_PW_LAKE:+yes}" \\
  "${TB_DB_PW_FHIR_STORE:+set}" >> "$(dirname "$0")/roles-ran.txt"
"""


def test_the_one_documented_command_restores_the_last_backup_from_a_bare_sudo(
    tmp_path: Path, box: dict[str, Any]
) -> None:
    """THE CARD (H-100): ``sudo trialbox restore --last --key <key> --yes --restart`` typed as RUNBOOK §5 writes it,
    from sudo's bare environment with the system python: the backup the nightly recorded good is restored over the
    box's databases in the backup image's container, the URLs it got are the box's, the service-role step ran inside
    it, the restored rows equal ``backup-verify``'s, and the services start again only as the result allows."""
    import hashlib
    import json
    import shlex
    import subprocess
    import sys

    import psycopg

    from tools import pglocal
    from tools.trialbox import backup_schedule as bs

    wf = box["env"]["STANDIN_DB_URL"]  # the test cluster's two databases, as URLs (the box's form)
    hapi = wf.replace(f"/{box['dbs']['trialbox_wf']}?", f"/{box['dbs']['hapi']}?")
    nas = tmp_path / "nas"
    nas.mkdir()
    root = tmp_path / "opt" / "trialbox"  # an install folder of its own
    import shutil

    skip = shutil.ignore_patterns("__pycache__", "*.pyc", "site", ".env")
    for sub in ("tools", "libs", "deploy"):
        shutil.copytree(box["root"] / sub, root / sub, ignore=skip, symlinks=True)
    (root / "services").symlink_to(ROOT / "services")
    deploy = root / "deploy"
    (deploy / "docker" / "db-init" / "30-service-roles.sh").write_text(ROLES_STUB, encoding="utf-8")
    vols = tmp_path / "volumes"
    for v in ("audit-data", "lake-data"):
        (vols / f"trialbox_{v}" / "_data").mkdir(parents=True)
    (deploy / ".env").write_text(
        f"TB_ENV=TEST\nTB_IMAGE={h88.PY_IMAGE}\nTB_BACKUP_IMAGE={h88.PY_IMAGE}\nTB_BACKUP_TARGETS={nas}\n"
        f"TB_DB_URL={url('trialbox', 'wf-synthetic', 'db:5432/trialbox_wf')}\nPOSTGRES_PASSWORD=pg@synthetic/1\n"
        f"TB_DB_PW_LAKE=lake-synthetic\nTB_DOCKER_VOLUMES={vols}\n",
        encoding="utf-8",
    )
    (deploy / ".env").chmod(0o600)
    made = bk.backup([nas], deploy / "secrets" / "backup.pub", env={"TB_DB_URL": wf, "TB_HAPI_DB_URL": hapi},
                     dirs={})[0]  # fmt: skip
    sha = hashlib.sha256(made.read_bytes()).hexdigest()
    (deploy / "site").mkdir(exist_ok=True)
    (deploy / "site" / "backup-last.json").write_text(json.dumps(
        {"good_file": {"name": made.name, "bytes": made.stat().st_size, "sha256": sha}}), encoding="utf-8")  # fmt: skip
    with psycopg.connect(wf, autocommit=True) as con:  # what the box lost after the backup
        con.execute("DELETE FROM marks")
    # sudo, the runtime stand-ins, the installed link: as the drill's own test builds them
    bindir = tmp_path / "sudo-bin"
    bindir.mkdir()
    secure = f"{bindir}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    pybin = tmp_path / "py-bin"
    pybin.mkdir()
    (pybin / "python").write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n', encoding="utf-8")
    (pybin / "python").chmod(0o755)  # the image's python, with the libraries
    received = tmp_path / "received.json"
    standin = {**{k: v for k, v in box["env"].items() if k.startswith("STANDIN_")},
               "STANDIN_DOCKER": str(box["bin"] / "docker"), "STANDIN_RECEIVED": str(received),
               "STANDIN_WF_URL": wf, "STANDIN_HAPI_URL": hapi,
               "STANDIN_RESTORE_PATH": f"{pybin}:{pglocal.bindir()}:/usr/bin:/bin",
               "STANDIN_RESTORE_PYTHONPATH": f"{box['root'] / 'libs'}:{ROOT / 'services'}:{box['root']}"}  # fmt: skip
    exports = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in standin.items())
    (bindir / "restore-standin").write_text(f"#!{sys.executable}\n{RESTORE_STANDIN}", encoding="utf-8")
    (bindir / "docker").write_text(f'#!/bin/sh\n{exports}exec {bindir / "restore-standin"} "$@"\n', encoding="utf-8")
    (bindir / "sudo").write_text(h88.SUDO.format(path=secure), encoding="utf-8")
    link = tmp_path / "usr-local-bin" / "trialbox"
    link.parent.mkdir()
    link.symlink_to(root / "tools" / "trialbox" / "__main__.py")
    (bindir / "trialbox").write_text(f'#!/bin/sh\nexec {box["python"]} -I {link} "$@"\n', encoding="utf-8")
    for name in ("sudo", "docker", "trialbox", "restore-standin"):
        (bindir / name).chmod(0o755)
    caller = {"PATH": secure, "TB_DB_URL": url("x", "caller", "caller-host:5432/x"), "TB_HAPI_DB_URL": "caller",
              "TB_DB_ROLES_CMD": f"touch {tmp_path / 'caller-ran'}", "PYTHONPATH": str(tmp_path)}  # fmt: skip

    def sudo(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["/bin/sh", "-c", shlex.join(["sudo", "trialbox", *args])], cwd=root, env=caller,
                              capture_output=True, text=True, timeout=600, check=False)  # fmt: skip

    vr = sudo("backup-verify", str(made), "--key", str(box["key"]))
    h88._no_import_fault(vr)
    assert vr.returncode == 0, (vr.stdout + vr.stderr)[-3000:]
    verified = json.loads(vr.stdout)["databases"]
    assert verified["trialbox_wf"] == 2  # the synthetic rows the backup holds
    r = sudo("restore", "--last", "--key", str(box["key"]), "--yes", "--restart")
    h88._no_import_fault(r)
    assert r.stdout.startswith("{"), r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["rows"] == verified, (out["rows"], verified)  # the restored rows equal backup-verify's
    with psycopg.connect(wf) as con:
        assert con.execute("SELECT count(*) FROM marks").fetchone() == (2,)
    got = json.loads(received.read_text(encoding="utf-8"))
    argv = got.pop("argv")
    assert got["TB_DB_URL"] == url("trialbox", "wf-synthetic", "db:5432/trialbox_wf")  # the box's, not the caller's
    assert got["TB_HAPI_DB_URL"] == url("hapi", "pg%40synthetic%2F1", "db:5432/hapi")
    assert got["TB_DB_ROLES_CMD"].startswith("python -m tools.trialbox.box_restore roles")
    assert not (tmp_path / "caller-ran").exists()
    assert "synthetic" not in " ".join(argv) and str(made) in argv  # --last: the recorded file; no password
    ran = (deploy / "docker" / "db-init" / "roles-ran.txt").read_text(encoding="utf-8")
    assert "host_set=yes lake_set=yes fhir=" in ran, ran  # the role step ran inside, with the roles' passwords
    events = [json.loads(ln)["event"] for day in (vols / "trialbox_audit-data" / "_data").rglob("*.jsonl")
              for ln in day.read_text(encoding="utf-8").splitlines() if ln.strip()]  # fmt: skip
    assert "backup.restored" in events, events
    assert out["kept_copy"] and Path(out["kept_copy"]).is_file()  # the box held data: kept first, as before
    # a box with no opt-out register to read (a new machine): the restore is not complete (D-493) and holds the
    # list jobs (D-522), so the services start again, held, and are waited for until healthy
    assert r.returncode == 4 and out["optouts_after_backup"]["state"] == "unknown", (r.returncode, r.stderr[-2000:])
    assert out["hold"] == "held" and "NOT complete" in r.stderr, r.stderr[-2000:]
    assert "the services run again and are healthy" in r.stderr, r.stderr[-2000:]
    ups = [c["argv"] for c in h88.calls(box) if "compose" in c["argv"] and "up" in c["argv"]]
    assert ups and ups[-1][-4:] == ["-d", "--wait", "--wait-timeout", "600"], ups
    assert bs.recorded_good([nas], {"name": made.name, "bytes": made.stat().st_size, "sha256": sha})


# ------------------------------------------------------------------------------------------------ the rehearsal
def test_the_rehearsal_restores_over_the_live_stack_by_the_documented_command() -> None:
    """The box rehearsal's ``live-restore`` (the real box, every service, in CI): the nightly with a relative
    ``--deploy``, ``backup-verify``, then RUNBOOK §5's one command; the rows equal backup-verify's, every service
    that ran before runs again healthy, and the box's own key, targets and records are put back. It is the last
    step on the box, so no later step runs on a box a restore left held."""
    import re

    box_sh = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    rehearse = (ROOT / "tools" / "rehearse_box" / "rehearse.sh").read_text(encoding="utf-8")
    body = box_sh[box_sh.index("\nlive-restore)") : box_sh.index("\n  ;;", box_sh.index("\nlive-restore)"))]
    page = (ROOT / "docs" / "runbook" / "05-updates-backup-restore-secrets.md").read_text(encoding="utf-8")
    documented = re.search(r"^    sudo (trialbox restore --last --key \S+ --yes --restart)$", page, re.M)
    assert documented, "RUNBOOK §5 names no one command"
    assert 'trialbox restore --last --key "$rr/backup.key" --yes --restart' in body
    assert "python3 -m tools.trialbox backup-nightly --deploy deploy " in body  # gap 1: the relative folder
    assert "backup-verify" in body and 'out["rows"] == verify["databases"]' in body
    assert "wait_healthy" in body and '[ "$before" = "$after" ]' in body
    assert "trap put_back EXIT" in body and "env.before" in body
    assert "backup-keygen" in body and "never the box's" in body  # a throwaway key pair
    steps = re.findall(r"^step ([a-z0-9-]+) [01] (\S+)", rehearse, re.M)
    in_box = [name for name, how in steps if how == "in_box"]
    assert in_box[-1] == "live-restore", in_box
