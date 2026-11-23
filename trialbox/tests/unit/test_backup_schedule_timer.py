"""H-92 (D-1090): the backup schedule does not depend on a cron daemon the box may lack.

The bench's rehearsal host ran no cron daemon, so ``/etc/cron.d/trialbox-backup`` never fired. Where systemd is the
init, ``backup-install`` writes each line of ``deploy/backup/trialbox-backup.cron`` as a systemd timer (the same
command, the same local time, ``Persistent=true``), enables and starts it, and removes the cron file; the cron file
stays only where systemd is not the init. Never two schedules: before a cron file is written, every backup timer is
disabled, its units removed and that verified, or nothing is changed and one action is said. ``doctor`` (``backup``)
and ``backup-status`` say which schedule runs, reading every timer; doctor FAILs (PRODUCTION) with one action when
nothing will fire it, or when both would.

No systemd and no cron daemon run here: :class:`Systemd` stands in for ``systemctl`` and keeps each timer's state
(enabled, running), with the failures a real one has (enable done, start failed); the init and the daemon are the
inputs the product asks for (``bs.systemd_init``, ``bs.cron_daemon``, ``DoctorInputs.timer_state`` /
``cron_running``).

THE INVARIANT (H-92): ``test_the_timer_runs_the_installed_cron_lines_command_from_a_bare_environment``: every timer
``backup-install`` writes runs exactly the command of the cron line it replaces, at its time, and that command runs
the nightly backup from a bare environment with the host's python (H-88's harness)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
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
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "deploy" / "backup" / f"{bs.CRON_NAME}.cron").read_text(encoding="utf-8")
box, system_python, _a_host = h88.box, h88.system_python, h88._a_host  # H-88's harness: the box, its host python
NIGHTLY, HOURLY = bs.TIMERS


def _exec(service: str) -> str:
    """The shell line of a unit's ``ExecStart=/bin/sh -c '...'``, as systemd hands it to the shell."""
    line = next(x for x in service.splitlines() if x.startswith("ExecStart="))
    m = re.fullmatch(r"ExecStart=/bin/sh -c '(.*)'", line)
    assert m, line
    return m.group(1).replace("$$", "$").replace("%%", "%")


def _section(unit: str, name: str) -> set[str]:
    """The lines of one ``[Section]`` of a unit file."""
    part = unit.split(f"[{name}]\n", 1)[1].split("\n[", 1)[0]
    return {x for x in part.splitlines() if x.strip()}


def _cron_jobs(text: str) -> dict[str, tuple[str, str]]:
    """{command: (minute, hour)} of the cron file's job lines."""
    out = {}
    for ln in text.splitlines():
        if ln[:1].isdigit():
            f = ln.split(None, 6)
            assert f[2:6] == ["*", "*", "*", "root"], ln
            out[f[6]] = (f[0], f[1])
    return out


class Systemd:
    """``systemctl`` with state: each unit enabled or not, running or not. ``fail``: verb -> how it fails
    (``"after"``: the work is done, then the call fails, as ``enable --now`` whose start fails; ``"before"``)."""

    def __init__(self, units: Path, fail: dict[str, str] | None = None) -> None:
        self.units, self.fail = units, dict(fail or {})
        self.enabled: set[str] = set()
        self.active: set[str] = set()
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> None:
        self.calls.append(args)
        verb, how = args[0], self.fail.get(args[0], "")
        if how == "before":
            raise subprocess.CalledProcessError(1, ["systemctl", *args])
        names = [a for a in args[1:] if not a.startswith("-")]
        if verb == "enable":
            self.enabled |= set(names)
            self.active |= set(names) if "--now" in args else set()
        elif verb == "disable":
            self.enabled -= set(names)
            self.active -= set(names) if "--now" in args else set()
        if how == "after":
            raise subprocess.CalledProcessError(1, ["systemctl", *args])

    def word(self, unit: str) -> str | None:
        if unit in self.enabled:
            return "enabled" if unit in self.active else "stopped"
        return "disabled" if (self.units / unit).exists() else "not-found"

    @property
    def firing(self) -> set[str]:
        return {u for u in bs.TIMERS if self.word(u) in bs.FIRES}


def _deploy(tmp_path: Path, env: str) -> Path:
    deploy = tmp_path / "opt" / "tb" / "deploy"
    (deploy / "backup").mkdir(parents=True)
    (deploy / "backup" / f"{bs.CRON_NAME}.cron").write_text(TEMPLATE, encoding="utf-8")
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


def _doctor(deploy: Path, env: dict[str, str], cron: Path, words: Any, running: bool) -> doctor.Check:
    """doctor's backup check with each timer's word (a callable, a dict, one word for every timer, or None: no
    systemd)."""
    if callable(words):
        look = words
    else:
        table = words if isinstance(words, dict) else dict.fromkeys(bs.TIMERS, words)
        look = table.get
    inp = doctor.DoctorInputs(env=env, deploy=deploy, cron_dir=cron, host_tz="Asia/Taipei", timer_state=look,
                              cron_running=lambda: running)  # fmt: skip
    return doctor.check_backup(inp)


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A root shell on a host whose init is systemd, no cron daemon; the box good apart from its schedule."""
    units, cron = tmp_path / "systemd", tmp_path / "cron.d"
    units.mkdir()
    cron.mkdir()
    sd = Systemd(units)
    monkeypatch.setattr(bs, "systemd_init", lambda: True)
    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setattr(bs, "_systemctl", sd)
    monkeypatch.setattr(bs, "timer_word", sd.word)
    monkeypatch.setattr(bs, "cron_daemon", lambda proc=None: False)
    monkeypatch.delenv("TB_SYSTEMD", raising=False)
    monkeypatch.setenv("TB_COMPOSE", "false")  # no docker here: archiving is reported off
    for k in ("TB_ENV", "TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_BACKUP_TARGETS", "TB_PG_ARCHIVE_MODE"):
        monkeypatch.delenv(k, raising=False)
    deploy, env = _good_box(tmp_path)
    return {"sd": sd, "units": units, "cron": cron, "deploy": deploy, "env": env}


def _install(h: dict[str, Any]) -> int:
    return bs.main_install(h["deploy"], h["cron"], first=False, systemd_dir=h["units"])


def _schedules(h: dict[str, Any]) -> set[str]:
    """What would fire: the timers systemd would run, and the cron file."""
    sd: Systemd = h["sd"]
    return sd.firing | ({"cron"} if (h["cron"] / bs.CRON_NAME).exists() else set())


# ------------------------------------------------------------------------------------------------ the invariant
def test_the_timer_runs_the_installed_cron_lines_command_from_a_bare_environment(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE INVARIANT (H-92): each timer runs the command of the cron line it replaces, at the same time, Persistent,
    nothing else in its [Timer]; its service runs after the stack with cron's PATH; the nightly one, run as systemd
    hands it to the shell (cwd /, PATH only, the host's python), makes a real backup that verifies with the test's
    own key. No secret in a unit."""
    cfg = bs.config(box["deploy"], launch.env_file(box["deploy"] / ".env"))
    cron, units = box["dir"] / "t-cron.d", box["dir"] / "t-systemd"
    cron.mkdir(exist_ok=True)
    units.mkdir(exist_ok=True)
    bs.install_cron(cfg, cron, box["root"], has_mta=False)
    jobs = _cron_jobs((cron / bs.CRON_NAME).read_text(encoding="utf-8"))
    sd = Systemd(units)
    monkeypatch.setattr(bs, "_systemctl", sd)
    bs.install_timers(cfg, units, cron, box["root"], has_mta=False)
    timers = sorted(p.name for p in units.glob("*.timer"))
    assert timers == sorted(bs.TIMERS) and len(jobs) == 2, (timers, jobs)
    assert sd.firing == set(timers) and sd.calls[0] == ("daemon-reload",) and not (cron / bs.CRON_NAME).exists()
    seen = {}
    for t in timers:
        timer = (units / t).read_text(encoding="utf-8")
        service = (units / t.replace(".timer", ".service")).read_text(encoding="utf-8")
        cmd = _exec(service)
        assert cmd in jobs, (cmd, jobs)
        minute, hour = jobs[cmd]
        cal = f"OnCalendar=*-*-* {'*' if hour == '*' else hour.zfill(2)}:{minute.zfill(2)}:00"
        assert _section(timer, "Timer") == {cal, "Persistent=true"}, timer  # no delay, no other trigger
        unit = _section(service, "Unit")
        assert "After=docker.service trialbox.service" in unit, unit  # a missed night runs after the stack's start
        assert f"Environment=PATH={bs.CRON_PATH}" in _section(service, "Service"), service  # cron's PATH
        seen[cmd] = t
    assert set(seen) == set(jobs)
    every = "".join(p.read_text(encoding="utf-8") for p in units.iterdir())
    assert DSN not in every and "TB_DB_URL" not in every and "PYTHONPATH" not in every and "PASSWORD" not in every
    nightly = _exec((units / NIGHTLY.replace(".timer", ".service")).read_text(encoding="utf-8"))
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


# --------------------------------------------------------------------------------- what the timer can carry
def test_the_mail_cron_sent_is_sent_by_the_timer_and_systemds_own_characters_are_doubled() -> None:
    """cron's MAILTO mailed what a line printed; the timer's unit pipes the same to sendmail. systemd expands % and
    $ itself: both are doubled (review R1)."""
    text = bs.cron_text(TEMPLATE, Path("/opt/x"), "it@hospital.example")
    units = bs.unit_files(text, "it@hospital.example")
    service = units[NIGHTLY.replace(".timer", ".service")]
    script = _exec(service)
    raw = next(x for x in service.splitlines() if x.startswith("ExecStart="))
    assert "$$out" in raw and not re.search(r"(?<!\$)\$[a-z(?]", raw), raw  # systemd would expand $out itself
    assert "sendmail -t" in script and 'echo "To: it@hospital.example"' in script
    assert next(c for c in _cron_jobs(text) if "backup-nightly" in c) in script
    pct = bs.unit_files(bs.cron_text(TEMPLATE, Path("/opt/x"), "").replace("backup.log", "backup-%F.log"))
    raw = next(x for x in pct[NIGHTLY.replace(".timer", ".service")].splitlines() if x.startswith("ExecStart="))
    assert "backup-%%F.log" in raw and "backup-%F.log" not in raw, raw
    with pytest.raises(ValueError):
        bs.unit_files(text, "it@x.example; reboot")


@pytest.mark.parametrize(
    "line",
    [
        "45 4 1 * * root cd /x && python3 -m tools.trialbox backup-nightly",  # monthly (review R5)
        "45 4 * 6 * root cd /x && python3 -m tools.trialbox backup-nightly",  # one month
        "45 4 * * 1 root cd /x && python3 -m tools.trialbox backup-nightly",  # one weekday
        "*/5 * * * * root cd /x && python3 -m tools.trialbox backup-status",  # a step
        "99 4 * * * root cd /x && python3 -m tools.trialbox backup-nightly",  # minute out of range (F5)
        "45 77 * * * root cd /x && python3 -m tools.trialbox backup-nightly",  # hour out of range (F5)
        "CRON_TZ=UTC",  # an environment line cron reads and the timer would not (F5)
        "PATH=/opt/site/bin:/usr/bin",
        "45 4 * * * root cd /x && echo no tool here",
    ],
)
def test_a_cron_line_the_timer_cannot_carry_exactly_is_refused(line: str) -> None:
    text = bs.cron_text(TEMPLATE, Path("/opt/x"), "") + line + "\n"
    with pytest.raises(ValueError):
        bs.timer_jobs(text)


def test_no_fixed_time_falls_in_the_hour_the_spring_forward_day_skips() -> None:
    """D-1090 (review F6): systemd gives *-*-* 02:17:00 no time on the spring-forward day and Persistent does not
    catch it; a fixed hour of 02 is refused. The shipped times are 04:45 and every hour at :17 (the hourly check
    has one run fewer that day, as under cron)."""
    jobs = bs.timer_jobs(bs.cron_text(TEMPLATE, Path("/opt/x"), ""))
    assert {cal for _, cal, _ in jobs} == {"*-*-* 04:45:00", "*-*-* *:17:00"}
    with pytest.raises(ValueError, match="spring-forward"):
        bs.timer_jobs(bs.cron_text(TEMPLATE.replace("45 4 * * *", "17 2 * * *"), Path("/opt/x"), ""))
    assert bs.timer_jobs(bs.cron_text(TEMPLATE.replace("45 4 * * *", "17 3 * * *"), Path("/opt/x"), ""))


# -------------------------------------------------------------------------------------- which schedule runs
def test_with_systemd_and_no_cron_daemon_the_timer_is_the_schedule_and_doctor_passes(
    host: dict[str, Any], capsys: Any
) -> None:
    assert cli(["backup-install", "--deploy", str(host["deploy"]), "--cron-dir", str(host["cron"]), "--systemd-dir",
                str(host["units"]), "--no-first-run"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "timer: " in out and NIGHTLY in out, out
    assert _schedules(host) == set(bs.TIMERS)
    assert _doctor(host["deploy"], host["env"], host["cron"], "enabled", running=False).status == "PASS"
    c = _doctor(host["deploy"], host["env"], host["cron"], host["sd"].word, running=False)
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
    assert _doctor(deploy, env, cron, None, running=True).status == "PASS"  # with a cron daemon the box passes
    monkeypatch.setenv("TB_COMPOSE", "false")
    monkeypatch.setattr(bs, "cron_daemon", lambda proc=None: False)
    monkeypatch.setattr(bs, "timer_word", lambda unit: None)
    for k in env:
        monkeypatch.delenv(k, raising=False)
    bs.main_status(deploy, cron_dir=cron)
    assert "schedule: none: FAIL" in capsys.readouterr().out
    bs.main_status(deploy, as_json=True, cron_dir=cron)
    assert json.loads(capsys.readouterr().out)["schedule"]["active"] == "none"


def test_doctor_reads_every_timer_and_only_a_running_enabled_one_counts(tmp_path: Path) -> None:
    """Review R4 and F8: a disabled timer is no schedule; a stopped one, or the hourly check disabled next to an
    enabled nightly one, is a FAIL with the action; ``enabled-runtime`` fires."""
    deploy, env = _good_box(tmp_path)
    cron = tmp_path / "cron.d"
    cron.mkdir()
    c = _doctor(deploy, env, cron, "disabled", running=False)
    assert c.status == "FAIL" and "schedule: none" in c.detail and "no backup timer enabled" in c.detail, c
    for words in ({NIGHTLY: "enabled", HOURLY: "disabled"}, {NIGHTLY: "stopped", HOURLY: "enabled"}):
        c = _doctor(deploy, env, cron, words, running=False)
        assert c.status == "FAIL" and "will not fire" in c.detail and "backup-install" in c.detail, (words, c)
    assert _doctor(deploy, env, cron, "enabled-runtime", running=False).status == "PASS"


# ------------------------------------------------------------------------------------- never two schedules
def test_an_enabled_timer_and_the_cron_file_are_never_both_left(host: dict[str, Any]) -> None:
    assert bs.install_cron(bs.config(host["deploy"], host["env"]), host["cron"], host["deploy"].parent, False)
    assert _install(host) == 0 and _schedules(host) == set(bs.TIMERS)  # the timer wins, the cron file goes
    bs.install_cron(bs.config(host["deploy"], host["env"]), host["cron"], host["deploy"].parent, False)
    c = _doctor(host["deploy"], host["env"], host["cron"], host["sd"].word, running=True)  # one put back by hand
    assert c.status == "FAIL" and "both" in c.detail and "removes the cron file" in c.detail, c
    assert _install(host) == 0 and _schedules(host) == set(bs.TIMERS)


@pytest.mark.parametrize(
    "case",
    ["enable started nothing", "reload failed on a timer box", "the cron file cannot go", "a quote in the folder"],
)
def test_a_failed_timer_install_leaves_the_cron_file_alone_and_no_timer(
    host: dict[str, Any], monkeypatch: pytest.MonkeyPatch, case: str, capsys: Any
) -> None:
    """Review F2 and F11: whatever fails part-way, the timers are disabled, their units removed and that verified
    before the cron file is written; then exactly one schedule, said."""
    sd = host["sd"]
    if case == "enable started nothing":
        sd.fail["enable"] = "after"  # enabled, then the start failed: real systemctl leaves the links
    elif case == "reload failed on a timer box":
        assert _install(host) == 0 and sd.firing == set(bs.TIMERS)
        sd.fail["daemon-reload"] = "before"
    elif case == "the cron file cannot go":
        bs.install_cron(bs.config(host["deploy"], host["env"]), host["cron"], host["deploy"].parent, False)
        real = Path.unlink

        def unlink(self: Path, missing_ok: bool = False) -> None:
            if self.name == bs.CRON_NAME and "fallback" not in sd.calls[-1]:
                sd.calls.append(("fallback",))
                raise PermissionError(13, "read-only", str(self))
            real(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", unlink)
    else:
        moved = host["deploy"].parent.parent / "o'brien"
        shutil.move(str(host["deploy"].parent), str(moved))
        host["deploy"] = moved / "deploy"
    capsys.readouterr()
    assert _install(host) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert _schedules(host) == {"cron"}, (case, sd.calls, out)
    assert not any(p.exists() for p in bs._units(host["units"])), case
    assert "the timers could not be installed" in out and "no cron daemon runs" in out, out


def test_timers_that_cannot_be_removed_stop_the_install_with_one_action(host: dict[str, Any], capsys: Any) -> None:
    """Review F2: when the timers' removal cannot be verified, no cron file is written: rc 1, one action."""
    sd = host["sd"]
    sd.fail.update({"enable": "after", "disable": "before"})
    assert _install(host) == 1
    out = capsys.readouterr().out
    assert not (host["cron"] / bs.CRON_NAME).exists() and sd.firing, out
    assert "the backup timers could not be removed" in out and "systemctl disable --now" in out, out


def test_tb_systemd_0_or_no_root_over_a_timer_box_keeps_one_schedule(
    host: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Review F3 and R2: without root the timers are left and nothing is written (rc 1, the action); with
    TB_SYSTEMD=0 (install.sh's poc profile) the timers go, verified, and the cron file is the schedule."""
    assert _install(host) == 0 and _schedules(host) == set(bs.TIMERS)
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    assert _install(host) == 1 and _schedules(host) == set(bs.TIMERS)
    assert "run this command as root" in capsys.readouterr().out
    monkeypatch.setattr("os.geteuid", lambda: 0)
    monkeypatch.setenv("TB_SYSTEMD", "0")
    assert _install(host) == 0 and _schedules(host) == {"cron"}
    assert not any(p.exists() for p in bs._units(host["units"]))
    # and a non-root run on a host without the timers takes the cron file, never systemctl
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    monkeypatch.delenv("TB_SYSTEMD")
    host["sd"].calls.clear()
    assert _install(host) == 0 and _schedules(host) == {"cron"} and not host["sd"].calls


def test_an_old_cron_only_box_keeps_working_and_is_moved_by_backup_install(host: dict[str, Any], capsys: Any) -> None:
    old = ('SHELL=/bin/sh\nPYTHONPATH=/opt/trialbox/libs\nMAILTO=""\n45 4 * * * root cd /opt/trialbox && { python3 -m '
           "tools.trialbox backup-nightly >> /var/log/x 2>&1 || :; }\n")  # fmt: skip
    (host["cron"] / bs.CRON_NAME).write_text(old, encoding="utf-8")
    c = _doctor(host["deploy"], host["env"], host["cron"], "not-found", running=True)  # a daemon still reads it
    assert c.status == "WARN" and "old form" in c.detail and "moves it to" in c.detail, c
    assert cli(["backup-install", "--deploy", str(host["deploy"]), "--cron-dir", str(host["cron"]), "--systemd-dir",
                str(host["units"]), "--no-first-run"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "removed (the timer runs it now)" in out and "first backup" not in out, out
    assert _schedules(host) == set(bs.TIMERS)
    assert _doctor(host["deploy"], host["env"], host["cron"], host["sd"].word, running=False).status == "PASS"


# ------------------------------------------------------------------------------------------------ install.sh
def _install_sh_cron_part(tmp_path: Path, systemd: bool, env: str) -> subprocess.CompletedProcess[str]:
    """install.sh's own lines, from the systemd-host test to the retention cron's end, and the line before the
    backup step, run by bash as root with no /etc/cron.d; ``systemd``: whether systemd is the init."""
    a = INSTALL.index("# H-92 (D-1090): a systemd host")
    b = INSTALL.index('if [ "$(id -u)" = 0 ] && [ -d /etc/logrotate.d ]', a)
    c = INSTALL.index("# H-92: on a systemd host backup-install")
    d = INSTALL.index('if [ "$CAN_CRON" = 1 ]; then\n  say "backups: cron', c)
    run = tmp_path / "run-systemd"
    if systemd:
        run.mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    for name, body in (("id", "echo 0"), ("systemctl", "exit 0"), ("python3", "exit 0")):
        (stub / name).write_text(f"#!/bin/sh\n{body}\n")
        (stub / name).chmod(0o755)
    script = (f'die() {{ echo "DIE: $*"; exit 3; }}\nROOT={tmp_path}\n' + INSTALL[a:b] + INSTALL[c:d]
              + 'echo "CAN_CRON=$CAN_CRON"\n').replace("/run/systemd/system", str(run))  # fmt: skip
    return subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{stub}:/usr/bin:/bin", "TB_ENV_SITE": env, "TB_CRON_DIR": str(tmp_path / "no-cron.d")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_install_sh_production_on_a_systemd_host_without_cron_goes_on_to_the_timers(tmp_path: Path) -> None:
    """Review F1: a PRODUCTION install on a systemd host with no cron package reaches the backup step (the timers);
    the stop stays where neither can schedule."""
    r = _install_sh_cron_part(tmp_path, systemd=True, env="PRODUCTION")
    assert r.returncode == 0 and "CAN_CRON=1" in r.stdout and "DIE" not in r.stdout, (r.stdout, r.stderr)
    assert "the log retention cron is not installed" in r.stderr
    (tmp_path / "neither").mkdir()
    r = _install_sh_cron_part(tmp_path / "neither", systemd=False, env="PRODUCTION")
    assert r.returncode == 3 and "DIE: the cron files cannot be installed" in r.stdout, (r.stdout, r.stderr)


def test_install_sh_hands_its_systemd_folder_to_backup_install() -> None:
    """Review F9: TB_SYSTEMD_DIR moves the units of backup-install as it moves install.sh's own."""
    step = INSTALL[INSTALL.index("python3 -m tools.trialbox backup-install --deploy deploy") :][:300]
    assert '${TB_SYSTEMD_DIR:+--systemd-dir "$TB_SYSTEMD_DIR"}' in step, step


def test_the_systemd_host_line_comes_before_the_backup_step() -> None:
    step = INSTALL.index("python3 -m tools.trialbox backup-install --deploy deploy")
    before = INSTALL[INSTALL.rindex("\n# H-92", 0, step) : step]
    assert '[ "$SYSTEMD_HOST" = 1 ] && command -v python3 >/dev/null && CAN_CRON=1\n' in before, before


def test_a_timer_enabled_but_not_running_reads_as_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F8: ``systemctl stop`` leaves the timer enabled; is-active says it will not fire."""
    answers = {"is-enabled": "enabled", "is-active": "inactive"}
    monkeypatch.setattr(bs, "_ask", lambda verb, unit: answers[verb])
    monkeypatch.setattr(bs, "systemd_init", lambda: True)
    assert bs.timer_word(NIGHTLY) == "stopped"
    answers["is-active"] = "active"
    assert bs.timer_word(NIGHTLY) == "enabled"
    answers["is-enabled"] = "disabled"
    assert bs.timer_word(NIGHTLY) == "disabled"
    monkeypatch.setattr(bs, "systemd_init", lambda: False)
    assert bs.timer_word(NIGHTLY) is None
