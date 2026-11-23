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

import pytest

from tests.unit.test_backup_schedule import FakeBox
from tools.trialbox import backup as bk
from tools.trialbox import update


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
        "TB_DB_URL=postgresql://trialbox:zq~7!Kd~pw@db:5432/trialbox_wf\nTB_SITE_ID=CGMH\nTB_ENV=TEST\n"
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
CALLER = {"TB_DB_URL": "postgresql://x:caller-secret@caller:5432/x", "TB_HAPI_DB_URL": "postgresql://x@caller/x",
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


def _box(tmp_path: Path, extra: str = "") -> Path:
    deploy = tmp_path / "opt" / "deploy"
    (deploy / "secrets").mkdir(parents=True)
    (deploy / "secrets" / "backup.pub").write_text("synthetic public key", encoding="utf-8")
    (deploy / "docker" / "db-init").mkdir(parents=True)
    (deploy / "docker" / "db-init" / "30-service-roles.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    vols = tmp_path / "volumes"
    for v in ("audit-data", "lake-data", "tb-secrets"):
        (vols / f"trialbox_{v}" / "_data").mkdir(parents=True)
    (deploy / ".env").write_text(
        f"TB_ENV=TEST\nTB_SITE_ID=CGMH\nTB_DB_URL=postgresql://trialbox:wf-pw@db:5432/trialbox_wf\n"
        f"POSTGRES_PASSWORD={PW}\nPOSTGRES_WF_PASSWORD=wf-pw\nTB_DB_PW_LAKE=lake-pw\nTB_DOCKER_VOLUMES={vols}\n{extra}",
        encoding="utf-8",
    )
    (tmp_path / "nas").mkdir()
    (tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak").write_bytes(b"synthetic")
    (tmp_path / "usb").mkdir()
    (tmp_path / "usb" / "backup.key").write_text("synthetic private key", encoding="utf-8")
    return deploy


def _restore(deploy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rec: Recorder, out: str = "{}",
             code: int = 0, *more: str, file: bool = True) -> tuple[int, list[tuple[list[str], dict[str, str]]]]:
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
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec)
    assert code == 0 and len(seen) == 1, seen
    argv, values = seen[0]
    assert argv[0] == "docker" and "trialbox-backup:1.0.0" in argv and "caller/evil:1" not in argv
    assert all(c[0] == "docker" and c[1] == "compose" for c in rec.calls), rec.calls  # the box's runtime, not the caller's
    # the job's own URLs (update.ComposeBox._backup_container, from the same file): the same server, user and database
    job: dict[str, str] = {}
    box = update.ComposeBox(deploy, lambda argv, env=None, **kw: job.update(env or {}) or "")
    box._backup_container(tmp_path, deploy / "secrets" / "backup.pub", [str(tmp_path / "nas")])
    from psycopg.conninfo import conninfo_to_dict

    for k in ("TB_DB_URL", "TB_HAPI_DB_URL"):
        assert conninfo_to_dict(values[k]) == conninfo_to_dict(job[k].replace(PW, box_restore.quote(PW, safe=""))), k
    assert conninfo_to_dict(values["TB_HAPI_DB_URL"])["password"] == PW  # quoted in the URL, whole again when read
    assert values["TB_DB_ROLES_CMD"] == box_restore.ROLES_CMD
    assert values["TB_DB_PW_LAKE"] == "lake-pw" and values["TB_DB_PW_CONSOLE"] == "wf-pw"  # compose's own fallbacks
    assert values["TB_DB_PW_FHIR_STORE"] == ""  # D-541: no fallback
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
    assert f"audit=/var/lib/docker/volumes/trialbox_audit-data/_data" in argv
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
    assert code == 0 and seen and ["docker", "compose", "--project-directory", str(deploy), "stop", "console"] in rec.calls
    assert rec.calls.index(next(c for c in rec.calls if "stop" in c)) < len(rec.calls)
    rec = Recorder(running=None)
    rec.running = []  # compose answers nothing runs: the restore goes on
    assert _restore(deploy, tmp_path, monkeypatch, rec)[0] == 0
    code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0)  # no --yes: refused before anything
    from tools.trialbox import __main__ as cli

    assert cli.main(["restore", "f.tbbak", "--key", "k", "--deploy", str(deploy)], installed=True) == 2


@pytest.mark.parametrize(
    ("code", "hold", "starts"),
    [(0, "released", True), (4, "held", True), (4, "NOT set: OperationalError", False), (3, "held", False),
     (1, "", False)],
)
def test_restart_starts_the_services_only_after_a_complete_or_held_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], code: int, hold: str,
    starts: bool,
) -> None:  # fmt: skip
    import json

    deploy = _box(tmp_path)
    rec = Recorder(running=["db", "console"])
    got, seen = _restore(deploy, tmp_path, monkeypatch, rec, json.dumps({"hold": hold}), code, "--restart")
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
