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

from tests import pg_client
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
    (tmp_path / "usb" / "backup.key").chmod(0o600)
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

    def call(argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
        seen.append((argv, values))
        return code, out

    _stand_in(monkeypatch, rec)
    monkeypatch.setattr(box_restore, "_call", call)
    for k, v in CALLER.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    given = [str(tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak")] if file else []
    argv = ["restore", *given, "--key", "usb/backup.key", "--yes", "--deploy", str(deploy), *more]
    return cli.main(argv, installed=True), seen


def _stand_in(monkeypatch: pytest.MonkeyPatch, rec: Recorder) -> None:
    """The box's commands (compose and the engine) stood in for, at the host restore's own runner."""
    from tools.trialbox import box_restore

    monkeypatch.setattr(box_restore.BoxRestore, "_run", lambda self, argv, **kw: rec(argv, **kw))


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
    assert all(c[0] == "docker" for c in rec.calls), rec.calls  # the box's runtime, not the caller's
    for c in rec.calls:  # H-132 (LR-13, LR-15; ruling 7136897074): compose, or the engine's two read-only questions
        if c[1] != "compose":
            assert len(c) == 6 and c[3] == "-f", c
            assert (c[1:3], c[4]) in ((["volume", "inspect"], "{{.Mountpoint}}"),
                                      (["container", "inspect"], "{{.State.Status}}")), c  # fmt: skip
    assert not [c for c in rec.calls if c[1] in ("volume", "container") and c[2] in ("rm", "prune", "create")]
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
        # H-126: every service the box defines, waited for until healthy; both counts said
        whole = ["docker", "compose", "--project-directory", str(deploy), "up", "-d", "--pull", "never", "--wait",
                 "--wait-timeout", "600"]  # fmt: skip
        assert got == code and ups == [whole], ups  # exactly one start, the whole command pinned
        assert "healthy: 2 of 2" in capsys.readouterr().err
    else:
        err = capsys.readouterr().err
        assert got == code and "restore: the box now: running: db; stopped by --restart: console" in err, err


def test_h126_a_service_the_start_leaves_stopped_is_a_shortfall_with_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """H-126: a complete restore whose start leaves an expected service stopped ends 1, never "healthy"."""

    class LeavesConsole(Recorder):
        def __call__(self, argv: list[str], **kw: object) -> str:
            out = super().__call__(argv, **kw)
            if "up" in argv:
                self.running = ["db", "orchestrator"]  # console stays stopped
            return out

    deploy = _box(tmp_path)
    rec = LeavesConsole(running=["db", "console"])
    got, _ = _restore(deploy, tmp_path, monkeypatch, rec, '{"hold": "released"}', 0, "--restart")
    err = capsys.readouterr().err
    assert got == 1 and len([c for c in rec.calls if "up" in c]) == 1, (got, rec.calls)
    assert "did not all come back healthy: 1 of 2; not running or not healthy: console" in err, err
    assert "are healthy" not in err


def test_a_service_that_does_not_come_back_healthy_fails_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = _box(tmp_path)
    got, _ = _restore(deploy, tmp_path, monkeypatch, Recorder(["db", "console"], up_fails=True), "{}", 0, "--restart")
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
    (deploy / "site").mkdir(exist_ok=True)
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
if "compose" in argv and ("config" in argv and "--services" in argv or "ps" in argv and "running" in argv):
    print("db")  # H-126: the box defines db, and db runs
    sys.exit(0)
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
    made = bk.backup([nas], deploy / "secrets" / "backup.pub", env={"TB_DB_URL": wf, "TB_HAPI_DB_URL": hapi, **pg_client.env()},
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
    # H-126: the stand-in's compose says only db runs, so nothing was stopped; the whole project is started and
    # the full expected set (db) is checked
    ups = [c["argv"] for c in h88.calls(box) if "compose" in c["argv"] and "up" in c["argv"]]
    whole = [
        "compose",
        "--project-directory",
        str(deploy),
        "up",
        "-d",
        "--pull",
        "never",
        "--wait",
        "--wait-timeout",
        "600",
    ]
    assert ups == [whole], ups  # exactly one, pinned whole; every image from the bundle (OCR 1470-2)
    assert "the services run again and are healthy: 1 of 1" in r.stderr, r.stderr[-1500:]
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
    assert "trap put_back_all EXIT" in body and "env.before" in body and "roles.before" in body
    # review F2: a restore made to fail after it replaced the databases leaves every table as it was
    assert body.index("rows.before") < body.index('--yes > "$rr/failed.json"') < body.index("rows.after")
    assert '"rolled_back"' in body and 'diff "$rr/rows.before" "$rr/rows.after"' in body
    assert body.index("kill -INT 1") < body.index("kill -TERM 1")  # review R1: two signals, the second in the put-back
    assert body.index("rows.after") < body.index("--yes --restart >")  # the good restore after it
    assert "backup-keygen" in body and "never the box's" in body  # a throwaway key pair
    steps = re.findall(r"^step ([a-z0-9-]+) [01] (\S+)", rehearse, re.M)
    in_box = [name for name, how in steps if how == "in_box"]
    assert in_box[-1] == "live-restore", in_box


# ------------------------------------------------------------------------------------------------ the lead's holds
REFUSED_RUNNING = "these services are running: console. A restore moves their folders aside"
NO_YES = "restore replaces the box's databases and data folders (the old folders are kept aside): add --yes"


@pytest.mark.parametrize("env", ["TEST", "PRODUCTION"])
def test_restart_and_yes_never_imply_each_other_and_the_refusals_stay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: str
) -> None:
    """Twin (a PRODUCTION box and a PoC one): --restart without --yes is no longer a stop (T-U007: a notice with the
    way back); --yes without --restart meets the running-services refusal word for word; nothing was stopped or run
    in it."""
    from tools.trialbox import __main__ as cli

    deploy = _box(tmp_path, f"TB_ENV={env}\n")
    rec = Recorder(running=["db", "console"])
    _stand_in(monkeypatch, rec)
    key = tmp_path / "usb" / "backup.key"
    f = tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"
    from tools.trialbox import box_restore

    def container(argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
        rec.calls.append(["restore-container", *argv])  # the one step that takes the encrypted copy, then swaps
        return 0, "{}"

    monkeypatch.setattr(box_restore, "_call", container)
    code = cli.main(["restore", str(f), "--key", str(key), "--restart", "--deploy", str(deploy)], installed=True)
    said = capsys.readouterr()  # T-U007: was `== 2` and `NO_YES in out and rec.calls == []`
    assert NO_YES not in said.out and "trialbox restore <" in said.err
    assert code == 0  # not a refusal any more: the restore went through
    names = [
        c[0] if c[0] == "restore-container" else next((w for w in ("stop", "up") if w in c), "other") for c in rec.calls
    ]
    at = names.index("restore-container")
    assert "--keep-to" in rec.calls[at] and "--no-copy" not in rec.calls[at]  # the encrypted copy is asked for
    assert names.index("stop") < at < names.index("up")  # taken in the container: after the stop, before the swap
    rec = Recorder(running=["db", "console"])
    _stand_in(monkeypatch, rec)
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec)
    assert code == 2 and not seen and REFUSED_RUNNING in capsys.readouterr().err
    assert not any("stop" in c for c in rec.calls)


def test_a_restore_that_fails_after_the_stop_says_the_state_and_the_way_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = _box(tmp_path)
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "", 1, "--restart")
    err = capsys.readouterr().err
    assert code == 1 and seen and not any("up" in c for c in rec.calls)
    assert "restore: the box now: running: db; stopped by --restart: console; the data: NOT as it was" in err, err
    assert "up -d --no-deps console" not in err and "do not start the services" in err, err  # F2: never a start

    from tools.trialbox import box_restore

    def no_runtime(argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
        raise box_restore.RestoreStopped("the container runtime cannot be started here: nothing was changed")

    rec = Recorder(running=["db", "console"])
    _stand_in(monkeypatch, rec)
    monkeypatch.setattr(box_restore, "_call", no_runtime)
    from tools.trialbox import __main__ as cli

    f = tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"
    argv = ["restore", str(f), "--key", str(tmp_path / "usb" / "backup.key"), "--yes", "--restart", "--deploy",
            str(deploy)]  # fmt: skip
    assert cli.main(argv, installed=True) == 2
    err = capsys.readouterr().err
    assert "the data: not changed by this command (the restore did not start)" in err, err
    assert f"docker compose --project-directory {deploy} up -d --no-deps console" in err, err


def test_the_key_must_be_a_file_and_last_names_its_pick_before_anything_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    import json

    from tools.trialbox import __main__ as cli
    from tools.trialbox import backup_schedule as bs

    deploy = _box(tmp_path, f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\n")
    rec = Recorder(running=["db", "console"])
    _stand_in(monkeypatch, rec)
    f = tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"
    argv = ["restore", str(f), "--key", str(tmp_path / "usb"), "--yes", "--restart", "--deploy", str(deploy)]
    assert cli.main(argv, installed=True) == 2  # a folder, not a key file
    assert "is not a file: nothing was changed" in capsys.readouterr().err and rec.calls == []
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    bs.sidecar(f).write_text(f"{sha}  {f.name}\n", encoding="utf-8")
    (deploy / "site").mkdir(exist_ok=True)
    (deploy / "site" / "backup-last.json").write_text(
        json.dumps({"good_file": {"name": f.name, "bytes": f.stat().st_size, "sha256": sha}}), encoding="utf-8"
    )
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--last", "--restart", file=False)
    err = capsys.readouterr().err
    assert code == 0 and str(f) in seen[0][0] and err.index(f"--last: {f}") < err.index("stopped console"), err


# ------------------------------------------------------------------------------------------------ the review (F1-F7)
# Each test below fails on 1455734f (the head the independent review read) and holds what its finding asks.
def _t728() -> Any:
    from tests.unit import test_t728_asof_restore_optouts as t

    return t


def _counts(src: Any) -> dict[str, list[Any]]:
    """Every table's rows and hash but the flags store's (the hold a failed restore takes is a flag row in it)."""
    return {k: v for k, v in bk.row_counts(src).items() if not k.split(".")[0].endswith("app")}


def _box_db(tmp_path: Path, db_url: str) -> tuple[Any, dict[str, Path], Path, Path, Path, dict[str, str], Path]:
    t = _t728()
    reg, _jobs, dirs = t._box(db_url, tmp_path)
    priv, pub, keep = t._keys(tmp_path)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH", "TB_ENV": "TEST", **pg_client.env()}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    reg.add("P-LATER-2", "office", "", "office:a", "2026-11-23T10:00:00+00:00")  # the box moved on after the backup
    (dirs["audit"] / "after-the-backup.txt").write_text("synthetic", encoding="utf-8")
    return reg, dirs, priv, pub, keep, env, f


def _boom(*a: object, **kw: object) -> Any:
    raise bk.BackupError("synthetic failure after the first change")


@pytest.mark.parametrize("where", ["roles", "after-the-folders", "interrupt", "sigterm"])
def test_f2_a_restore_that_fails_after_its_first_change_puts_the_box_back_holds_and_audits(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """F2, F3 (inside): all or nothing. A failure, an interrupt or a signal after the databases were replaced (and,
    for one case, after the folders moved) puts the databases and the folders back as they were, takes the hold on
    the box's list jobs and audits ``backup.restore_failed`` with ``state: rolled_back``."""
    import os
    import signal

    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    src = bk.db_sources(env)[0]
    before = _counts(src)

    def interrupt(*a: object, **kw: object) -> Any:
        raise KeyboardInterrupt

    def sigterm(*a: object, **kw: object) -> Any:
        os.kill(os.getpid(), signal.SIGTERM)
        return []

    if where == "roles":
        monkeypatch.setattr(bk, "reapply_service_roles", _boom)
    elif where == "after-the-folders":
        monkeypatch.setattr(bk, "events_to_reapply", _boom)
    else:
        monkeypatch.setattr(bk, "fail_running_jobs", interrupt if where == "interrupt" else sigterm)
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert getattr(err.value, "state", None) == "rolled_back", err.value
    assert "put back as it was before the restore" in str(err.value) and "list jobs: held" in str(err.value)
    assert _counts(src) == before  # the databases as they were, P-LATER-2 among them
    assert (dirs["audit"] / "after-the-backup.txt").is_file()  # the folders as they were
    assert not list(dirs["audit"].parent.glob(f"{dirs['audit'].name}.pre-restore-*"))
    from tb_common.flags import Flags

    assert Flags(url=db_url).row(bk.HOLD_FLAG) == "held"
    (ev,) = _t728()._audit_events(dirs["audit"], "backup.restore_failed")
    assert ev["detail"]["state"] == "rolled_back" and ev["detail"]["hold"] == "held"
    assert signal.getsignal(signal.SIGTERM) is not None  # the handlers are put back after


def test_f2_a_put_back_that_fails_says_so_and_never_claims_the_box_is_whole(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    real = bk.restore_db

    def restore_db(src: Any, dump_file: Path, e: Any, keep_owners: bool = False) -> None:
        if dump_file.parent.name == "pre-restore":
            raise RuntimeError("synthetic: the put-back fails")
        real(src, dump_file, e, keep_owners)

    monkeypatch.setattr(bk, "restore_db", restore_db)
    monkeypatch.setattr(bk, "reapply_service_roles", _boom)
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert getattr(err.value, "state", None) == "not_rolled_back"
    assert "NOT put back as it was" in str(err.value) and "do not start the services" in str(err.value)
    assert "trialbox restore" in str(err.value) and "kept in" in str(err.value)  # the kept copy is the way back


def test_f2_no_space_for_the_copy_of_the_databases_refuses_before_any_change(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import collections

    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    src = bk.db_sources(env)[0]
    before = _counts(src)
    usage = collections.namedtuple("usage", "total used free")
    import shutil

    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(1, 1, 0))
    with pytest.raises(bk.BackupError, match="copied aside.*Nothing was changed") as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep, no_copy=False)
    assert getattr(err.value, "state", "unchanged") == "unchanged"
    assert _counts(src) == before and not _t728()._audit_events(dirs["audit"], "backup.restore_failed")


def test_f4_the_container_refuses_a_file_that_is_not_the_one_the_host_checked(tmp_path: Path, db_url: str) -> None:
    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    src = bk.db_sources(env)[0]
    before = _counts(src)
    with pytest.raises(bk.BackupError, match="not the backup that was named.*Nothing was changed"):
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep, expect_sha256="0" * 64)
    assert _counts(src) == before


def test_f4_the_host_hashes_the_file_before_anything_stops_and_passes_the_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib
    import json

    from tools.trialbox import backup_schedule as bs

    deploy = _box(tmp_path, f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\n")
    f = tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    assert code == 0 and _value(seen[0][0], "--expect-sha256") == sha  # the hash the host read, to the container
    bs.sidecar(f).write_text(f"{'1' * 64}  {f.name}\n", encoding="utf-8")  # the sidecar names another file
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    assert code == 2 and not seen and rec.calls == []  # nothing asked, nothing stopped
    assert "its sha256 differs. Nothing was changed" in capsys.readouterr().err
    bs.sidecar(f).write_text(f"{sha}  {f.name}\n", encoding="utf-8")
    (deploy / "site").mkdir(exist_ok=True)
    (deploy / "site" / "backup-last.json").write_text(json.dumps(  # the record says another content (sidecar too)
        {"good_file": {"name": f.name, "bytes": f.stat().st_size, "sha256": "2" * 64}}), encoding="utf-8")  # fmt: skip
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    assert code == 2 and not seen and rec.calls == []
    assert "the nightly's record" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["mode", "link", "owner", "folder"])
def test_f5_the_key_is_a_root_only_regular_file_and_not_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bad: str
) -> None:
    import os

    deploy = _box(tmp_path)
    key = tmp_path / "usb" / "backup.key"
    if bad == "mode":
        key.chmod(0o640)
    elif bad == "link":
        real = tmp_path / "usb" / "real.key"
        key.rename(real)
        key.symlink_to(real)
    elif bad == "owner":  # owned by neither root nor the user running it
        if os.geteuid() == 0:
            os.chown(key, 65534, 65534)
        else:
            monkeypatch.setattr(os, "geteuid", lambda: 99999)
    else:
        key.unlink()
        key.mkdir()
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    err = capsys.readouterr().err
    assert code == 2 and not seen and rec.calls == [] and "Nothing was changed" in err.replace("nothing", "Nothing")


COMPOSE_AND_ENGINE = ("COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES", "DOCKER_HOST", "DOCKER_CONTEXT",
                      "DOCKER_CONFIG")  # fmt: skip


@pytest.mark.parametrize("var", COMPOSE_AND_ENGINE)
def test_f1_a_callers_compose_or_engine_variable_reaches_neither_compose_nor_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, var: str
) -> None:
    """F1 (probe P10): with the variable exported, compose still asks the box's own project, so the running
    services are seen and the restore is refused; the container's engine gets the clean environment too."""
    from tools.trialbox import box_restore, procgroup

    deploy = _box(tmp_path)
    monkeypatch.setenv(var, "caller-value")
    envs: list[dict[str, str]] = []

    class Done:
        def __init__(self, out: bytes) -> None:
            self.returncode, self.stdout, self.stderr = 0, out, b""

    def run(argv: list[str], env: dict[str, str], **kw: object) -> Done:
        envs.append(dict(env))
        steered = env.get("COMPOSE_PROJECT_NAME") == "caller-value" or env.get(var) == "caller-value"
        return Done(b"" if steered else (b"db\nconsole\n" if "ps" in argv else b""))

    monkeypatch.setattr(procgroup, "run", run)
    calls: list[dict[str, str]] = []

    def container(argv: list[str], values: dict[str, str], base: Any = None) -> tuple[int, str]:
        calls.append(dict(base or {}))
        return 0, "{}"

    monkeypatch.setattr(box_restore, "_call", container)
    from tools.trialbox import __main__ as cli

    argv = ["restore", str(tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"), "--key",
            str(tmp_path / "usb" / "backup.key"), "--yes", "--deploy", str(deploy)]  # fmt: skip
    assert cli.main(argv, installed=True) == 2 and not calls  # the box's services run: refused, as on the box
    assert envs and all(var not in e for e in envs), envs
    assert all(set(e) <= {"PATH", "HOME"} for e in envs), envs  # the engine's own needs, nothing of the caller's
    rec = Recorder()
    _stand_in(monkeypatch, rec)
    monkeypatch.setattr(box_restore, "_call", container)
    assert cli.main(argv, installed=True) == 0 and calls and var not in calls[0] and set(calls[0]) <= {"PATH", "HOME"}


def test_f1_the_box_file_names_the_engine_and_that_reaches_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import box_restore

    deploy = _box(tmp_path, "DOCKER_HOST=unix:///run/box-engine.sock\n")
    monkeypatch.setenv("DOCKER_HOST", "tcp://caller:2375")
    assert box_restore.BoxRestore(deploy).engine_env()["DOCKER_HOST"] == "unix:///run/box-engine.sock"


def test_f3_a_stop_that_fails_says_the_state_and_keeps_the_audit_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    deploy = _box(tmp_path)

    class StopFails(Recorder):
        def __call__(self, argv: list[str], **kw: object) -> str:
            if "stop" in argv:
                self.calls.append(list(argv))
                raise update.UpdateFailed("compose stop ... exit 1: synthetic")
            if "exec" in argv and "orchestrator" in argv:  # the orchestrator is down: the event is kept
                raise update.UpdateFailed("synthetic: no orchestrator")
            return super().__call__(argv, **kw)

    rec = StopFails(running=["db", "console", "orchestrator"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    err = capsys.readouterr().err
    assert code == 1 and not seen
    assert "restore: the box now: running: console, db, orchestrator; stopped by --restart: console, orchestrator" \
           in err, err  # fmt: skip
    assert "next: start them as they were: docker compose" in err and "up -d --no-deps console orchestrator" in err
    (ev,) = [json.loads(x) for x in (deploy / "site" / "backup-audit-pending.jsonl").read_text().splitlines()]
    assert ev["event"] == "backup.restore_failed" and ev["detail"]["where"] == "host"
    assert ev["detail"]["stopped"] == ["console", "orchestrator"]


def test_f3_an_interrupt_while_the_container_runs_is_passed_on_and_waited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    import signal
    import subprocess

    from tools.trialbox import box_restore

    sent: list[int] = []

    class Proc:
        returncode = 1
        n = 0

        def __init__(self, *a: object, **kw: object) -> None:
            pass

        def communicate(self) -> tuple[str, str]:
            Proc.n += 1
            if Proc.n == 1:
                raise KeyboardInterrupt
            return '{"ok": false, "state": "rolled_back"}', ""

        def send_signal(self, sig: int) -> None:
            sent.append(sig)

    monkeypatch.setattr(subprocess, "Popen", Proc)
    code, out = box_restore._call(["docker", "run"], {}, {"PATH": "/usr/bin"})
    assert code == 1 and sent == [signal.SIGTERM] and '"rolled_back"' in out


@pytest.mark.parametrize(
    ("state", "starts", "says"),
    [
        ("unchanged", True, "the data not changed (the restore was refused before any change)"),
        ("rolled_back", False, "the data: put back as it was before the restore"),
        ("not_rolled_back", False, "do not start the services"),
    ],
)
def test_f2_after_a_failed_restore_the_host_starts_only_what_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], state: str, starts: bool,
    says: str,
) -> None:  # fmt: skip
    import json

    deploy = _box(tmp_path)
    rec = Recorder(running=["db", "console"])
    code, _ = _restore(deploy, tmp_path, monkeypatch, rec, json.dumps({"ok": False, "state": state}), 1, "--restart")
    err = capsys.readouterr().err
    assert code == 1 and bool([c for c in rec.calls if "up" in c]) is starts and says in err, err
    if state == "not_rolled_back":
        assert "up -d" not in err  # never a start line for a box that is not as it was


@pytest.mark.parametrize(("code", "gone"), [(0, True), (3, True), (4, True), (1, False), (2, False)])
def test_f7_the_tls_marker_goes_after_every_exit_that_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, gone: bool
) -> None:
    from tools.tls_policy import OLD_CLIENTS_AUDITED

    deploy = _box(tmp_path)
    (deploy / "site").mkdir(exist_ok=True)
    marker = deploy / "site" / OLD_CLIENTS_AUDITED
    marker.write_text("synthetic", encoding="utf-8")
    assert _restore(deploy, tmp_path, monkeypatch, Recorder(), '{"hold": "held"}', code)[0] == code
    assert marker.exists() is not gone


def test_f2_the_copy_and_its_put_back_keep_the_owners_and_grants(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rehearsal's find: a put-back restored without owners left the services' schemas owned by the restoring
    role, and three services came back unhealthy. The copy is dumped and put back with its owners and grants; the
    backup's own restore stays ``--no-owner`` (D-573: the role script gives them back)."""
    import subprocess

    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    src = bk.db_sources(env)[0]
    before = _counts(src)
    seen: list[list[str]] = []
    real = subprocess.run

    def run(cmd: Any, *a: Any, **kw: Any) -> Any:
        if isinstance(cmd, list) and cmd and str(cmd[0]).endswith(("pg_dump", "pg_restore")):
            io = [str(getattr(kw.get(k), "name", "")) for k in ("stdin", "stdout")]  # the dump file, by its name
            seen.append([str(x) for x in cmd] + io)
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(bk, "reapply_service_roles", _boom)
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert getattr(err.value, "state", None) == "rolled_back" and _counts(src) == before
    pre = [c for c in seen if any("pre-restore" in x for x in c)]
    assert {c[0].rsplit("/", 1)[-1] for c in pre} == {"pg_dump", "pg_restore"}, seen
    assert all("--no-owner" not in c and "--no-privileges" not in c for c in pre), pre
    restores = [c for c in seen if c[0].endswith("pg_restore") and c not in pre]
    assert restores and all("--no-owner" in c for c in restores), restores


# ------------------------------------------------------------------------------------------------ the re-review (R1-R7)
# Each fails on da6d1b7a (the head the re-review read).
@pytest.mark.parametrize(("first", "second"), [("SIGINT", "SIGTERM"), ("SIGTERM", "SIGINT"), ("SIGHUP", "SIGTERM"),
                                               ("SIGTERM", "SIGHUP")])  # fmt: skip
def test_r1_a_second_signal_during_the_put_back_never_abandons_it(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, first: str, second: str
) -> None:
    """R1, R6: one Ctrl-C under ``docker run`` can arrive twice. The first signal stops the restore after its first
    change; the second arrives while the databases are being put back: it is ignored, the put-back finishes, the hold
    is taken and the event written."""
    import os
    import signal

    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    src = bk.db_sources(env)[0]
    before = _counts(src)
    real = bk.restore_db
    sent: list[str] = []

    def stop_once(*a: object, **kw: object) -> Any:
        os.kill(os.getpid(), getattr(signal, first))
        return []

    def restore_db(s: Any, dump_file: Path, e: Any, keep_owners: bool = False) -> None:
        if dump_file.parent.name == "pre-restore" and not sent:
            sent.append(second)
            os.kill(os.getpid(), getattr(signal, second))  # the second signal, as the put-back starts
        real(s, dump_file, e, keep_owners)

    monkeypatch.setattr(bk, "fail_running_jobs", stop_once)
    monkeypatch.setattr(bk, "restore_db", restore_db)
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert sent == [second] and getattr(err.value, "state", None) == "rolled_back", err.value
    assert _counts(src) == before
    from tb_common.flags import Flags

    assert Flags(url=db_url).row(bk.HOLD_FLAG) == "held"
    (ev,) = _t728()._audit_events(dirs["audit"], "backup.restore_failed")
    assert ev["detail"]["state"] == "rolled_back"
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL or callable(signal.getsignal(signal.SIGTERM))
    assert signal.getsignal(signal.SIGINT) is not signal.SIG_IGN  # the handlers are put back after


def test_r3_r5_a_put_back_that_fails_keeps_its_copy_and_says_the_hold_is_unknown(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stat

    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    real = bk.restore_db

    def restore_db(s: Any, dump_file: Path, e: Any, keep_owners: bool = False) -> None:
        if dump_file.parent.name == "pre-restore":
            raise RuntimeError("synthetic: the put-back fails")
        real(s, dump_file, e, keep_owners)

    monkeypatch.setattr(bk, "restore_db", restore_db)
    monkeypatch.setattr(bk, "reapply_service_roles", _boom)
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert getattr(err.value, "state", None) == "not_rolled_back"
    (kept,) = keep.glob("pre-restore-dumps-*")
    assert {p.name for p in kept.iterdir()} == {"trialbox_wf.dump"} and str(kept) in str(err.value)
    assert stat.S_IMODE(kept.stat().st_mode) == 0o700
    assert "list jobs: unknown (the trial database is not whole)" in str(err.value)
    (ev,) = _t728()._audit_events(dirs["audit"], "backup.restore_failed")
    assert ev["detail"]["hold"].startswith("unknown")


def test_r3_no_copy_on_the_host_needs_yes_really(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy = _box(tmp_path)
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--no-copy", "--restart")
    assert code == 2 and not seen and rec.calls == [] and "--yes-really" in capsys.readouterr().err
    code, seen = _restore(deploy, tmp_path, monkeypatch, Recorder(), "{}", 0, "--no-copy", "--yes-really")
    assert code == 0 and "--no-copy" in seen[0][0]


def test_r4_an_empty_folder_comes_back_with_its_own_owner_and_mode(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import stat

    t = _t728()
    (tmp_path / "b").mkdir()
    _reg, _j, dirs = t._box(db_url, tmp_path / "b")
    priv, pub, keep = t._keys(tmp_path / "b")
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH", "TB_ENV": "TEST", **pg_client.env()}
    objects = tmp_path / "b" / "objects"
    objects.mkdir()
    (objects / "a.bin").write_bytes(b"synthetic")
    dirs = {**dirs, "objects": objects}
    f = bk.backup([tmp_path / "b" / "nas"], pub, env=env, dirs=dirs)[0]
    (objects / "a.bin").unlink()  # the box's folder is empty now: no aside, it is made again on a put-back
    objects.chmod(0o750)
    owner = (os.getuid(), os.getgid())
    if os.geteuid() == 0:
        os.chown(objects, 1234, 1234)
        owner = (1234, 1234)
    monkeypatch.setattr(bk, "events_to_reapply", _boom)  # after the folders were placed
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert getattr(err.value, "state", None) == "rolled_back"
    st = objects.stat()
    assert stat.S_IMODE(st.st_mode) == 0o750 and (st.st_uid, st.st_gid) == owner and not any(objects.iterdir())


def test_r6_the_hosts_step_raises_on_sighup_and_sigterm() -> None:
    import os
    import signal

    from tools.trialbox import box_restore

    back = box_restore._host_signals()
    try:
        for sig in (signal.SIGHUP, signal.SIGTERM):
            with pytest.raises(box_restore.HostInterrupted):
                os.kill(os.getpid(), sig)
    finally:
        back()


def test_r6_the_hosts_space_check_refuses_before_anything_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import collections
    import shutil

    deploy = _box(tmp_path)
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(1, 1, 0))
    rec = Recorder(running=["db", "console"])
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
    assert code == 2 and not seen and not any("stop" in c for c in rec.calls)
    assert "GB is free. Nothing was changed" in capsys.readouterr().err
    assert not list(deploy.glob(".restore-*"))


CHILD = r"""
import json, signal, sys, time
got = []
signal.signal(signal.SIGTERM, lambda s, f: got.append(s))
open(sys.argv[1], "w").write("started")
t = time.time()
while time.time() - t < 3 and not got:
    time.sleep(0.02)
time.sleep(0.5)  # the restore's put-back, while the host's further signals arrive
open(sys.argv[1], "w").write(f"sigterm={len(got)}")
print(json.dumps({"ok": False, "state": "rolled_back"}))
sys.exit(1)
"""


@pytest.mark.parametrize(("first", "second"), [("SIGINT", "SIGTERM"), ("SIGTERM", "SIGINT"), ("SIGHUP", "SIGINT")])
def test_r2_two_signals_on_the_host_pass_one_on_and_wait_for_the_container(
    tmp_path: Path, first: str, second: str
) -> None:
    """R2: the first signal goes to the container once; the second is ignored; the host waits for the container's
    own end and returns its state (never a "did not start")."""
    import os
    import signal
    import sys
    import threading
    import time

    from tools.trialbox import box_restore

    mark = tmp_path / "child"
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")

    def fire() -> None:
        while not mark.exists():
            time.sleep(0.01)
        os.kill(os.getpid(), getattr(signal, first))
        time.sleep(0.15)
        os.kill(os.getpid(), getattr(signal, second))

    back = box_restore._host_signals()
    try:
        threading.Thread(target=fire, daemon=True).start()
        code, out = box_restore._call([sys.executable, str(script), str(mark)], {}, dict(os.environ))
    finally:
        back()
    assert code == 1 and '"rolled_back"' in out
    assert mark.read_text() == "sigterm=1"  # passed on once
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_r2_an_escape_after_the_container_started_never_says_it_did_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools.trialbox import box_restore

    deploy = _box(tmp_path)

    def escapes(argv: list[str], values: dict[str, str], base: Any = None) -> tuple[int, str]:
        raise KeyboardInterrupt

    _stand_in(monkeypatch, Recorder(running=["db", "console"]))
    monkeypatch.setattr(box_restore, "_call", escapes)
    from tools.trialbox import __main__ as cli

    argv = ["restore", str(tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"), "--key",
            str(tmp_path / "usb" / "backup.key"), "--yes", "--restart", "--deploy", str(deploy)]  # fmt: skip
    assert cli.main(argv, installed=True) == 130
    err = capsys.readouterr().err
    assert "did not start" not in err and "the data: unknown: the restore's container was started" in err, err
    assert "do not start the services" in err and list(deploy.glob(".restore-*"))  # its work folder is kept


def test_r7_one_restore_at_a_time_and_a_killed_ones_folder_is_swept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import fcntl
    import os

    deploy = _box(tmp_path)
    left = deploy / ".restore-killed"
    left.mkdir(mode=0o700)
    (left / "plain.dump").write_bytes(b"synthetic")
    assert _restore(deploy, tmp_path, monkeypatch, Recorder(), "{}", 0)[0] == 0
    assert not left.exists() and "left by a restore that did not finish" in capsys.readouterr().err
    fd = os.open(deploy / "site" / "restore.lock", os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        code, seen = _restore(deploy, tmp_path, monkeypatch, Recorder(running=["db", "console"]), "{}", 0, "--restart")
        assert code == 2 and not seen and "another restore of this box is running" in capsys.readouterr().err
    finally:
        os.close(fd)


def test_r7_an_interrupt_while_the_services_start_says_the_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class UpInterrupted(Recorder):
        def __call__(self, argv: list[str], **kw: object) -> str:
            if "up" in argv:
                raise KeyboardInterrupt
            return super().__call__(argv, **kw)

    deploy = _box(tmp_path)
    code, _ = _restore(deploy, tmp_path, monkeypatch, UpInterrupted(running=["db", "console"]), "{}", 0, "--restart")
    err = capsys.readouterr().err
    assert code == 130 and "restore: the box now:" in err and "the data: restored" in err, err


def test_r1_whatever_stops_one_put_back_step_the_rest_still_go_back_and_it_is_audited(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1: a BaseException in one step of the put-back (an interrupt that came before the signals were ignored)
    leaves the other steps to run, the state said (not_rolled_back) and the event written; nothing escapes."""
    _reg, dirs, priv, pub, keep, env, f = _box_db(tmp_path, db_url)
    real = bk.restore_db

    def restore_db(s: Any, dump_file: Path, e: Any, keep_owners: bool = False) -> None:
        if dump_file.parent.name == "pre-restore":
            raise KeyboardInterrupt
        real(s, dump_file, e, keep_owners)

    monkeypatch.setattr(bk, "restore_db", restore_db)
    monkeypatch.setattr(bk, "events_to_reapply", _boom)  # after the folders moved: they go back as well
    with pytest.raises(bk.BackupError) as err:
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert getattr(err.value, "state", None) == "not_rolled_back" and "database trialbox_wf (KeyboardInterrupt)" in str(
        err.value
    )
    assert (dirs["audit"] / "after-the-backup.txt").is_file()  # the folders went back all the same
    (ev,) = _t728()._audit_events(dirs["audit"], "backup.restore_failed")
    assert ev["detail"]["state"] == "not_rolled_back"
