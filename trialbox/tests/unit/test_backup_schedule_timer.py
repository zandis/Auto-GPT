"""H-92: the backup schedule does not depend on a cron daemon the box may lack.

The bench's rehearsal host ran no cron daemon, so ``/etc/cron.d/trialbox-backup`` never fired. Where systemd is the
init, ``backup-install`` writes each line of ``deploy/backup/trialbox-backup.cron`` as a systemd timer (the same
command, the same local time, ``Persistent=true``), enables it and removes the cron file; the cron file stays only
where systemd is not the init. ``doctor`` (``backup``) and ``backup-status`` say which schedule runs, and doctor
FAILs (PRODUCTION) with one action when nothing will fire it, or when both would.

No systemd and no cron daemon run here: ``systemctl`` is a recorder, the init and the daemon are the inputs the
product asks for (``bs.systemd_init``, ``bs.cron_daemon``, ``DoctorInputs.timer_state`` / ``cron_running``).

THE INVARIANT (H-92): ``test_the_timer_runs_the_installed_cron_lines_command_from_a_bare_environment``: every timer
``backup-install`` writes runs exactly the command of the cron line it replaces, at its time, and that command runs
the nightly backup from a bare environment with the host's python (H-88's harness)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.unit import test_host_commands_own_environment as h88
from tests.unit.test_host_commands_own_environment import DSN, PY_IMAGE, _no_import_fault, bare, calls
from tools.trialbox import backup_schedule as bs
from tools.trialbox import doctor, launch
from tools.trialbox.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[2]
box, system_python, _a_host = h88.box, h88.system_python, h88._a_host  # H-88's harness: the box, its host python


def _exec(service: str) -> str:
    """The shell line of a unit's ``ExecStart=/bin/sh -c '...'``, as systemd hands it to the shell."""
    line = next(x for x in service.splitlines() if x.startswith("ExecStart="))
    m = re.fullmatch(r"ExecStart=/bin/sh -c '(.*)'", line)
    assert m, line
    return m.group(1).replace("$$", "$").replace("%%", "%")


def _cron_jobs(text: str) -> dict[str, tuple[str, str]]:
    """{command: (minute, hour)} of the cron file's job lines."""
    out = {}
    for ln in text.splitlines():
        if ln[:1].isdigit():
            f = ln.split(None, 6)
            assert f[2:6] == ["*", "*", "*", "root"], ln
            out[f[6]] = (f[0], f[1])
    return out


class Systemctl:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = fail

    def __call__(self, *args: str) -> None:
        self.calls.append(args)
        if self.fail:
            raise OSError("systemctl: Failed to connect to bus")

    @property
    def enabled(self) -> set[str]:
        return {u for c in self.calls if c[:2] == ("enable", "--now") for u in c[2:]}


def _deploy(tmp_path: Path, env: str) -> Path:
    deploy = tmp_path / "opt" / "tb" / "deploy"
    (deploy / "backup").mkdir(parents=True)
    (deploy / "backup" / f"{bs.CRON_NAME}.cron").write_text(
        (ROOT / "deploy" / "backup" / f"{bs.CRON_NAME}.cron").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (deploy / ".env").write_text(env, encoding="utf-8")
    return deploy


def _good_box(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A PRODUCTION box whose backup is good apart from its schedule: off-box share, route, archiving, 2 h old."""
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / bs.OFFBOX_MARKER).write_text("")
    env = {"TB_ENV": "PRODUCTION", "TB_TOPOLOGY": "A", "TB_BACKUP_TARGETS": str(nas), "TB_BACKUP_OFFBOX": str(nas),
           "TB_BACKUP_ALERT_CMD": "/usr/local/bin/tb-mail", "TB_PG_ARCHIVE_MODE": "on"}  # fmt: skip
    deploy = _deploy(tmp_path, "".join(f"{k}={v}\n" for k, v in env.items()))
    at = datetime.now(UTC) - timedelta(hours=2)
    f = nas / f"trialbox-CGMH-{at.strftime('%Y%m%dT%H%M%SZ')}.tbbak"
    f.write_bytes(b"x")
    bs.sidecar(f).write_text(f"{'a' * 64}  {f.name}\n")
    (deploy / "site").mkdir()
    (deploy / "site" / "backup-last.json").write_text(json.dumps({"ok": True, "good_at": at.isoformat(),
        "good_file": {"name": f.name, "bytes": 1, "sha256": "a" * 64}}))  # fmt: skip
    return deploy, env


def _doctor(deploy: Path, env: dict[str, str], cron: Path, timer: str | None, running: bool) -> doctor.Check:
    inp = doctor.DoctorInputs(env=env, deploy=deploy, cron_dir=cron, host_tz="Asia/Taipei",
                              timer_state=lambda unit: timer if unit == bs.TIMER else None,
                              cron_running=lambda: running)  # fmt: skip
    return doctor.check_backup(inp)


@pytest.fixture
def systemd_host(monkeypatch: pytest.MonkeyPatch) -> Systemctl:
    """A root shell on a host whose init is systemd (as install.sh tests it); ``systemctl`` records."""
    rec = Systemctl()
    monkeypatch.setattr(bs, "systemd_init", lambda: True)
    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr(bs, "_systemctl", rec)
    monkeypatch.setattr(bs, "cron_daemon", lambda proc=None: False)
    monkeypatch.delenv("TB_SYSTEMD", raising=False)
    monkeypatch.setenv("TB_COMPOSE", "false")  # no docker here: archiving is reported off
    for k in ("TB_ENV", "TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_BACKUP_TARGETS", "TB_PG_ARCHIVE_MODE"):
        monkeypatch.delenv(k, raising=False)
    return rec


# ------------------------------------------------------------------------------------------------ the invariant
def test_the_timer_runs_the_installed_cron_lines_command_from_a_bare_environment(box: dict[str, Any]) -> None:
    """THE INVARIANT (H-92): each timer runs the command of the cron line it replaces, at the same time, Persistent;
    the nightly one, run as systemd hands it to the shell (cwd /, PATH only, the host's python), makes a real
    backup that verifies with the test's own key. No secret in a unit."""
    cfg = bs.config(box["deploy"], launch.env_file(box["deploy"] / ".env"))
    cron, units = box["dir"] / "t-cron.d", box["dir"] / "t-systemd"
    cron.mkdir()
    units.mkdir()
    bs.install_cron(cfg, cron, box["root"], has_mta=False)
    jobs = _cron_jobs((cron / bs.CRON_NAME).read_text(encoding="utf-8"))
    rec = Systemctl()
    bs.install_timers(cfg, units, cron, box["root"], has_mta=False, systemctl=rec)
    timers = sorted(p.name for p in units.glob("*.timer"))
    assert len(timers) == len(jobs) == 2 and bs.TIMER in timers, (timers, jobs)
    assert rec.enabled == set(timers) and rec.calls[0] == ("daemon-reload",)
    seen = {}
    for t in timers:
        timer = (units / t).read_text(encoding="utf-8")
        cmd = _exec((units / t.replace(".timer", ".service")).read_text(encoding="utf-8"))
        assert cmd in jobs, (cmd, jobs)
        minute, hour = jobs[cmd]
        want = f"OnCalendar=*-*-* {'*' if hour == '*' else hour.zfill(2)}:{minute.zfill(2)}:00"
        assert want in timer.splitlines() and "Persistent=true" in timer.splitlines(), timer
        seen[cmd] = t
    assert set(seen) == set(jobs)
    every = "".join(p.read_text(encoding="utf-8") for p in units.iterdir())
    assert DSN not in every and "TB_DB_URL" not in every and "PYTHONPATH" not in every and "Environment" not in every
    nightly = _exec((units / bs.TIMER.replace(".timer", ".service")).read_text(encoding="utf-8"))
    log = box["dir"] / "timer-backup.log"
    r = bare(box, nightly.replace("/var/log/trialbox-backup.log", str(log)))
    out = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "No module named" not in out + r.stdout + r.stderr and "Traceback" not in out, out[-3000:]
    last = json.loads((box["deploy"] / "site" / "backup-last.json").read_text(encoding="utf-8"))
    assert last["ok"] and last["file"], (last, out[-2000:])
    from tools.trialbox import backup as bk

    assert bk.verify(box["nas"] / last["file"]["name"], box["key"])
    runs = [c["argv"] for c in calls(box) if c["argv"][:1] == ["run"] and PY_IMAGE in c["argv"]]
    assert runs and all(DSN not in json.dumps(a) for a in runs), runs
    hourly = next(c for c in jobs if "backup-status" in c)
    _no_import_fault(bare(box, _exec((units / seen[hourly].replace(".timer", ".service")).read_text())))


def test_the_mail_cron_sent_is_sent_by_the_timer_and_a_line_it_cannot_carry_is_refused(tmp_path: Path) -> None:
    """cron's MAILTO mailed what a line printed; the timer's unit pipes the same to sendmail. Nothing guessed."""
    text = (ROOT / "deploy" / "backup" / f"{bs.CRON_NAME}.cron").read_text(encoding="utf-8")
    text = bs.cron_text(text, Path("/opt/x"), "it@hospital.example")
    units = bs.unit_files(text, "it@hospital.example")
    script = _exec(units[bs.TIMER.replace(".timer", ".service")])
    raw = next(x for x in units[bs.TIMER.replace(".timer", ".service")].splitlines() if x.startswith("ExecStart="))
    assert "$$out" in raw and not re.search(r"(?<!\$)\$[a-z(?]", raw), raw  # systemd would expand $out itself
    assert "sendmail -t" in script and 'echo "To: it@hospital.example"' in script
    assert next(c for c in _cron_jobs(text) if "backup-nightly" in c) in script
    for bad in ("*/5 * * * * root cd /x && python3 -m tools.trialbox backup-status", "45 4 * * 1 root python3 -m "
                "tools.trialbox backup-nightly", "45 4 * * * root cd /x && echo no tool here"):  # fmt: skip
        with pytest.raises(ValueError):
            bs.unit_files(bad + "\n")
    with pytest.raises(ValueError):
        bs.unit_files(text, "it@x.example; reboot")


# -------------------------------------------------------------------------------------- which schedule runs
def test_with_systemd_and_no_cron_daemon_the_timer_is_the_schedule_and_doctor_passes(
    tmp_path: Path, systemd_host: Systemctl, capsys: Any
) -> None:
    deploy, env = _good_box(tmp_path)
    cron, units = tmp_path / "cron.d", tmp_path / "systemd"
    units.mkdir()
    assert cli(["backup-install", "--deploy", str(deploy), "--cron-dir", str(cron), "--systemd-dir", str(units),
                "--no-first-run"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "timer: " in out and bs.TIMER in out, out
    assert systemd_host.enabled == {p.name for p in units.glob("*.timer")} and bs.TIMER in systemd_host.enabled
    assert not (cron / bs.CRON_NAME).exists()
    c = _doctor(deploy, env, cron, "enabled", running=False)
    assert c.status == "PASS" and "schedule: timer" in c.detail, c


def test_with_neither_a_timer_nor_a_cron_daemon_doctor_fails_with_the_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    deploy, env = _good_box(tmp_path)
    cron = tmp_path / "cron.d"
    cron.mkdir()
    bs.install_cron(bs.config(deploy, env), cron, deploy.parent, has_mta=False)
    # no systemd (the bench's rehearsal host): the cron file alone, and no daemon to read it
    c = _doctor(deploy, env, cron, None, running=False)
    assert c.status == "FAIL" and "no cron daemon runs" in c.detail and "start the host's cron daemon" in c.detail, c
    assert "schedule: none" in c.detail
    # systemd is the init but the box still has the cron file only: one action, backup-install
    c = _doctor(deploy, env, cron, "not-found", running=False)
    assert c.status == "FAIL" and "backup-install --deploy deploy --no-first-run" in c.detail, c
    # with a cron daemon the same box passes
    assert _doctor(deploy, env, cron, None, running=True).status == "PASS"
    # backup-status says it too
    monkeypatch.setenv("TB_COMPOSE", "false")
    monkeypatch.setattr(bs, "cron_daemon", lambda proc=None: False)
    monkeypatch.setattr(bs, "unit_enabled", lambda unit: None)
    for k in env:
        monkeypatch.delenv(k, raising=False)
    bs.main_status(deploy, cron_dir=cron)
    assert "schedule: none: FAIL" in capsys.readouterr().out
    bs.main_status(deploy, as_json=True, cron_dir=cron)
    assert json.loads(capsys.readouterr().out)["schedule"]["active"] == "none"


def test_with_both_a_timer_and_a_cron_daemon_exactly_one_fires(
    tmp_path: Path, systemd_host: Systemctl, monkeypatch: pytest.MonkeyPatch
) -> None:
    deploy, env = _good_box(tmp_path)
    cron, units = tmp_path / "cron.d", tmp_path / "systemd"
    cron.mkdir()
    units.mkdir()
    bs.install_cron(bs.config(deploy, env), cron, deploy.parent, has_mta=False)
    systemd_host.calls.clear()
    assert bs.main_install(deploy, cron, first=False, systemd_dir=units) == 0
    assert not (cron / bs.CRON_NAME).exists() and bs.TIMER in systemd_host.enabled  # the timer wins: one schedule
    assert _doctor(deploy, env, cron, "enabled", running=True).status == "PASS"
    # a cron file put back by hand next to the enabled timer: both would fire, doctor says so with the action
    bs.install_cron(bs.config(deploy, env), cron, deploy.parent, has_mta=False)
    c = _doctor(deploy, env, cron, "enabled", running=True)
    assert c.status == "FAIL" and "both" in c.detail and "removes the cron file" in c.detail, c
    # systemd cannot enable the timer: the cron file instead, never both
    (cron / bs.CRON_NAME).unlink()
    for p in units.iterdir():
        p.unlink()
    bad = Systemctl(fail=True)
    monkeypatch.setattr(bs, "_systemctl", bad)
    assert bs.main_install(deploy, cron, first=False, systemd_dir=units) == 0
    assert (cron / bs.CRON_NAME).is_file() and not bad.enabled
    # TB_SYSTEMD=0 (install.sh's poc box): the cron file, no unit
    (cron / bs.CRON_NAME).unlink()
    rec = Systemctl()
    monkeypatch.setattr(bs, "_systemctl", rec)
    monkeypatch.setenv("TB_SYSTEMD", "0")
    assert bs.main_install(deploy, cron, first=False, systemd_dir=units) == 0
    assert (cron / bs.CRON_NAME).is_file() and not rec.calls


def test_an_old_cron_only_box_keeps_working_and_is_moved_by_backup_install(
    tmp_path: Path, systemd_host: Systemctl, capsys: Any
) -> None:
    deploy, env = _good_box(tmp_path)
    cron, units = tmp_path / "cron.d", tmp_path / "systemd"
    cron.mkdir()
    units.mkdir()
    old = ('SHELL=/bin/sh\nPYTHONPATH=/opt/trialbox/libs\nMAILTO=""\n45 4 * * * root cd /opt/trialbox && { python3 -m '
           "tools.trialbox backup-nightly >> /var/log/x 2>&1 || :; }\n")  # fmt: skip
    (cron / bs.CRON_NAME).write_text(old, encoding="utf-8")
    # before the move: a cron daemon reads it, so it still runs (WARN: the old form, and the move)
    c = _doctor(deploy, env, cron, "not-found", running=True)
    assert c.status == "WARN" and "old form" in c.detail and "moves it to" in c.detail, c
    assert cli(["backup-install", "--deploy", str(deploy), "--cron-dir", str(cron), "--systemd-dir", str(units),
                "--no-first-run"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "removed (the timer runs it now)" in out, out
    assert not (cron / bs.CRON_NAME).exists() and bs.TIMER in systemd_host.enabled
    assert "first backup" not in out
    assert _doctor(deploy, env, cron, "enabled", running=False).status == "PASS"


def test_install_sh_runs_the_backup_step_on_a_systemd_host_without_a_cron_folder() -> None:
    """A systemd host with no cron package has no /etc/cron.d: install.sh still runs backup-install (the timer)."""
    sh = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    step = sh.index("python3 -m tools.trialbox backup-install --deploy deploy")
    before = sh[sh.rindex("\n# H-92", 0, step) : step]
    assert "/run/systemd/system" in before and 'TB_SYSTEMD:-1}" != 0' in before and "&& CAN_CRON=1\n" in before, before
    assert before.index("&& CAN_CRON=1") < before.index('if [ "$CAN_CRON" = 1 ]; then')
