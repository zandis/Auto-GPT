"""H-126: after an interrupted restore, the re-run said "healthy" while the site was down (the integrator's red
7128848504, from the MVP walk's step 8 on a 16-service box).

A double Ctrl-C 25 s into ``trialbox restore --last --key <k> --yes --restart`` left caddy, console and llm-verifier
stopped; the re-run stopped what still ran, restored, started only what it had stopped (H-100's F6) and printed
"the services run again and are healthy: 13". Now ``--restart`` starts every service the box's compose defines and
checks the full expected set; the line names both counts and a shortfall is exit 1; the hold is said.

The box's commands are a stand-in compose that keeps each service's state (synthetic names, no data); the restore's
container is a stand-in that records whether the data part ran. A signal is sent at each step of the stop, restore
and start sequence, then the command is run again.
"""

from __future__ import annotations

import json
import re
import shlex
import signal
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_restore_from_the_host_h100 import _box
from tools.trialbox import box_restore, update

#: a box of 16 long-running services, as the walk's (synthetic names of this repository's compose files), and one
#: one-shot service (``restart: "no"``) that runs to the end and exits
SERVICES = ("db", "fhir-store", "lake", "embed-service", "doc-parser", "criteria-compiler", "adapter", "audit-writer",
            "orchestrator", "mail-gateway", "gateway", "console", "caddy", "llm-service", "llm-verifier", "model-guard")  # fmt: skip
ONE_SHOT = "judge-sleep-init"
_SAID = box_restore._said  # the host's own reading of the container's result
SITE = ("caddy", "console")  # the site answers when both run and are healthy

STEPS = ("stop", "restore-before-data", "restore-after-data", "restore-after-data-exit", "after-container", "start",
         "health")  # fmt: skip


class Interrupt:
    """Where the signal comes, and which: Ctrl-C (KeyboardInterrupt) or SIGTERM (HostInterrupted)."""

    def __init__(self, step: str | None = None, kind: str = "int") -> None:
        self.step, self.kind = step, kind

    def fire(self, step: str) -> None:
        if self.step == step:
            self.step = None  # once
            raise KeyboardInterrupt if self.kind == "int" else box_restore.HostInterrupted("signal SIGTERM")


class Box:
    """A stand-in compose with each service's state. ``never_starts`` and ``unhealthy`` plant a service that does not
    come back, or comes back unhealthy."""

    def __init__(self, never_starts: tuple[str, ...] = (), unhealthy: tuple[str, ...] = ()) -> None:
        self.running = set(SERVICES)
        self.data = "before"
        self.never_starts, self.unhealthy = set(never_starts), set(unhealthy)
        self.signal = Interrupt()
        self.calls: list[list[str]] = []

    def site_answers(self) -> bool:
        return all(s in self.running and s not in self.unhealthy for s in SITE)

    def __call__(self, argv: list[str], **kw: object) -> str:
        argv = list(argv)
        self.calls.append(argv)
        if "config" in argv and "--services" in argv:
            return "\n".join([*SERVICES, ONE_SHOT])
        if "config" in argv and "json" in argv:
            spec = {s: {"restart": "unless-stopped"} for s in SERVICES}
            spec[ONE_SHOT] = {"restart": "no"}
            return json.dumps({"name": "trialbox", "services": spec})
        if "ps" in argv:
            if "--format" in argv:
                self.signal.fire("health")
                return "\n".join(
                    f"{s} {'unhealthy' if s in self.unhealthy else 'healthy'}" for s in sorted(self.running)
                )
            return "\n".join(sorted(self.running))
        if "stop" in argv:
            names = argv[argv.index("stop") + 1 :]
            for i, s in enumerate(names):
                if i == len(names) // 2:
                    self.signal.fire("stop")  # part-way: half of them stopped
                self.running.discard(s)
            return ""
        if "up" in argv:
            named = [a for a in argv[argv.index("up") + 1 :] if a in SERVICES or a == ONE_SHOT]
            todo = [s for s in (named or SERVICES) if s not in self.never_starts]
            for i, s in enumerate(todo):
                if i == len(todo) // 2:
                    self.signal.fire("start")  # part-way: half of them started
                self.running.add(s)
            gone = (set(named or SERVICES) - self.running) | (self.unhealthy & self.running)
            if gone:
                raise update.UpdateFailed(f"compose up --wait: {', '.join(sorted(gone))} did not come up healthy")
            return ""
        if "exec" in argv:  # the orchestrator's audit, the databases' size: not asked of this stand-in
            raise update.UpdateFailed("synthetic: not answered")
        return ""

    def container(self, argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
        assert self.running <= box_restore.RESTORE_MAY_RUN, self.running  # D-724: only db runs while it restores
        self.signal.fire("restore-before-data")
        self.data = "restored"
        self.signal.fire("restore-after-data")
        if self.signal.step == "restore-after-data-exit":  # the container itself ended on the signal, data done
            self.signal.step = None
            return 130, ""
        return 0, json.dumps({"complete": True, "hold": "held", "state": "restored"})


def _run(deploy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, box: Box) -> int:
    from tools.trialbox import __main__ as cli

    monkeypatch.setattr(box_restore.BoxRestore, "_run", lambda self, argv, **kw: box(argv, **kw))
    monkeypatch.setattr(box_restore, "_call", box.container)

    def read(out: str) -> dict[str, Any]:  # the host reads the container's result: a signal may come here too
        box.signal.fire("after-container")
        return _SAID(out)

    monkeypatch.setattr(box_restore, "_said", read)
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "nas" / "trialbox-CGMH-20261109T194500Z.tbbak"
    argv = ["restore", str(f), "--key", "usb/backup.key", "--yes", "--restart", "--deploy", str(deploy)]
    return int(cli.main(argv, installed=True))


@pytest.mark.parametrize("kind", ["int", "term"])
@pytest.mark.parametrize("step", STEPS)
def test_a_rerun_after_a_signal_at_every_step_serves_the_site_or_says_it_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], step: str, kind: str
) -> None:
    """THE INVARIANT (H-126): a signal at any step of the stop, the restore and the start leaves a box whose re-run
    (the same command) ends with every expected service running and healthy, the site answering, the line "N of N"
    and the hold said; the interrupted run itself never says "healthy"."""
    deploy = _box(tmp_path)
    box = Box()
    box.signal = Interrupt(step, kind)
    try:
        first: object = _run(deploy, tmp_path, monkeypatch, box)
    except (KeyboardInterrupt, box_restore.HostInterrupted) as e:  # escaped the command: nothing said
        first = e
    err = capsys.readouterr().err
    assert first in (1, 130) and "are healthy" not in err, (first, err[-1500:])
    assert "restore: the box now:" in err, err[-1500:]  # the state, said
    assert box.signal.step is None, "the signal was not sent at this step"
    again = _run(deploy, tmp_path, monkeypatch, box)
    err = capsys.readouterr().err
    assert again == 0, (again, err[-2000:])
    assert box.data == "restored" and box.running == set(SERVICES) and box.site_answers(), (box.running, err[-1500:])
    n = len(SERVICES)
    assert f"the services run again and are healthy: {n} of {n} (" in err, err[-1500:]
    assert "the hold screening.after_restore stays held" in err and "/ops/flags" in err, err[-1500:]
    assert not list(deploy.glob(".restore-*")), "a scratch folder was left"


def test_the_walk_three_services_left_stopped_are_started_by_the_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The walk's box as the interrupted run left it: the data restored, caddy, console and llm-verifier stopped,
    the other 13 up. The re-run starts all 16 and says "16 of 16"; never "13"."""
    deploy = _box(tmp_path)
    box = Box()
    box.running -= {"caddy", "console", "llm-verifier"}
    assert not box.site_answers()
    assert _run(deploy, tmp_path, monkeypatch, box) == 0
    err = capsys.readouterr().err
    assert box.running == set(SERVICES) and box.site_answers()
    assert "healthy: 16 of 16 (" in err and ": 13" not in err, err[-1500:]
    ups = [c for c in box.calls if "up" in c]
    assert len(ups) == 1 and ups[0][-7:] == ["up", "-d", "--pull", "never", "--wait", "--wait-timeout", "600"], ups


@pytest.mark.parametrize("plant", ["never_starts", "unhealthy"])
def test_a_planted_stopped_or_unhealthy_service_fails_the_health_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], plant: str
) -> None:
    """A service that stays stopped (or comes back unhealthy) after the start: exit 1, the counts and the name said,
    and never "healthy"."""
    deploy = _box(tmp_path)
    box = Box(**{plant: ("llm-verifier",)})
    if plant == "never_starts":
        box.running.discard("llm-verifier")  # stopped before, as the interrupted run left it
    code = _run(deploy, tmp_path, monkeypatch, box)
    err = capsys.readouterr().err
    assert code == 1, (code, err[-1500:])
    assert "are healthy" not in err and "did not all come back healthy: 15 of 16" in err, err[-1500:]
    assert re.search(r"not running or not healthy: llm-verifier\b", err), err[-1500:]
    assert "restore: the box now:" in err and "the hold screening.after_restore" in err, err[-1500:]


def test_the_expected_set_is_the_compose_project_less_its_one_shots(tmp_path: Path) -> None:
    box = Box()
    r = box_restore.BoxRestore(_box(tmp_path), run=box)
    assert r.expected([]) == set(SERVICES)
    assert r.expected(["a-service-compose-does-not-name"]) == {*SERVICES, "a-service-compose-does-not-name"}
    box.running.discard("caddy")
    ok, short = r.healthy(set(SERVICES))
    assert short == {"caddy"} and len(ok) == 15


def test_compose_that_cannot_name_the_services_is_never_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NoConfig(Box):
        def __call__(self, argv: list[str], **kw: object) -> str:
            if "config" in argv:
                raise update.UpdateFailed("synthetic: compose config failed")
            return super().__call__(argv, **kw)

    deploy = _box(tmp_path)
    box = NoConfig()
    code = _run(deploy, tmp_path, monkeypatch, box)
    err = capsys.readouterr().err
    assert code == 1 and "are healthy" not in err and "compose cannot say which services the box defines" in err
    assert box.running == set(SERVICES)  # started all the same


def test_the_hold_released_by_the_restore_is_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Released(Box):
        def container(self, argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
            super().container(argv, values, base)
            return 0, json.dumps({"complete": True, "hold": "released", "state": "restored"})

    deploy = _box(tmp_path)
    assert _run(deploy, tmp_path, monkeypatch, Released()) == 0
    assert "the hold screening.after_restore: released by the restore" in capsys.readouterr().err


def test_the_rehearsal_reruns_an_interrupted_restore_and_the_site_answers() -> None:
    """The rehearsal's live-restore (step 27) adds the walk's case on the real box: a restore signalled after its
    data part, services stopped as the walk's run left them, the same command again: every service that ran before
    runs again healthy, the line says "N of N" and the site answers through caddy."""
    root = Path(__file__).resolve().parents[2]
    box_sh = (root / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    body = box_sh[box_sh.index("\nlive-restore)") : box_sh.index("\n  ;;", box_sh.index("\nlive-restore)"))]
    h126 = body[body.index("# H-126") :]
    assert "kill -TERM" in h126 and "dc stop" in h126 and "--yes --restart" in h126
    assert r"are healthy: ([0-9]+) of \1 \(" in h126  # N of N, never a shortfall
    assert "/healthz" in h126 and '[ "$before" = "$after" ]' in h126 and "caddy-root.crt" in h126
    assert h126.index("kill -TERM") < h126.index("dc stop") < h126.rindex("--yes --restart")
    # OCR 1470-5: the interrupted run itself is checked, and a run left in the background is stopped on a fail path
    interrupted = h126[h126.index("kill -TERM") : h126.index("dc stop")]
    assert 'grep -q "are healthy" "$rr/interrupted.err"; then fail' in interrupted
    assert 'grep -q "restore: the box now:" "$rr/interrupted.err" || fail' in interrupted
    assert "1|130)" in interrupted and "stop_bg; fail" in h126


def test_a_signal_handler_is_put_back_after_each_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    deploy = _box(tmp_path)
    box = Box()
    box.signal = Interrupt("start", "term")
    _run(deploy, tmp_path, monkeypatch, box)
    capsys.readouterr()
    assert {s: signal.getsignal(s) for s in before} == before


@pytest.mark.parametrize("kind", ["int", "term"])
@pytest.mark.parametrize("step", ["stop", "start", "health"])
def test_a_second_signal_while_a_step_is_said_still_says_the_box_and_the_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], step: str, kind: str
) -> None:
    """OCR 1470-1: the walk pressed Ctrl-C twice. A first signal part-way through the stop, the start or the health
    check goes to the handler; a second one while the handler asks compose (the audit, what runs) escaped it, and
    neither the box's state nor the hold was said. A signal is modelled as a real one is delivered: never while it
    is ignored."""
    sig = signal.SIGINT if kind == "int" else signal.SIGTERM

    class Twice(Box):
        armed = False

        def __call__(self, argv: list[str], **kw: object) -> str:
            if self.armed and signal.getsignal(sig) is not signal.SIG_IGN:  # the handler's next call to compose
                self.armed = False  # the second signal, while the first is being said
                raise KeyboardInterrupt if kind == "int" else box_restore.HostInterrupted("signal SIGTERM")
            first = {"stop": "stop" in argv, "start": "up" in argv}.get(step, "ps" in argv and "--format" in argv)
            if self.signal.step == step and first:
                self.armed = True  # the first signal comes in this call
            return super().__call__(argv, **kw)

    deploy = _box(tmp_path)
    box = Twice()
    box.signal = Interrupt(step, kind)
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        got: object = _run(deploy, tmp_path, monkeypatch, box)
    except (KeyboardInterrupt, box_restore.HostInterrupted) as e:  # escaped the command: no state, no hold said
        got = e
    err = capsys.readouterr().err
    assert got == 130, (got, err[-1500:])
    assert "restore: the box now:" in err and "are healthy" not in err and box.signal.step is None, err[-1500:]
    assert step == "stop" or "the hold screening.after_restore stays held" in err, err[-1500:]
    assert {s: signal.getsignal(s) for s in before} == before  # every handler put back


@pytest.mark.parametrize(("code", "hold", "want"), [(0, "released", 1), (4, "held", 4)])
def test_a_shortfall_keeps_the_restores_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], code: int, hold: str,
    want: int,
) -> None:  # fmt: skip
    """OCR 1470-3: a held, NOT complete restore (exit 4) whose start leaves a service stopped still ends 4, so a
    script that reads 4 as "restored, held" keeps it; a complete one ends 1. Neither says "healthy"."""

    class Ends(Box):
        def container(self, argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
            super().container(argv, values, base)
            return code, json.dumps({"complete": code == 0, "hold": hold, "state": "restored"})

    deploy = _box(tmp_path)
    box = Ends(never_starts=("caddy",))
    got = _run(deploy, tmp_path, monkeypatch, box)
    err = capsys.readouterr().err
    assert got == want, (got, err[-1500:])
    assert "are healthy" not in err and "did not all come back healthy: 15 of 16" in err, err[-1500:]


@pytest.mark.parametrize(
    ("box_file", "caller", "want"),
    [("", "", "never"), ("", "missing", "never"), ("TB_INSTALL_PULL=missing\n", "", "missing"),
     ("TB_INSTALL_PULL=always\n", "missing", "never")],
)  # fmt: skip
def test_the_start_pulls_as_the_box_file_says_never_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], box_file: str, caller: str,
    want: str,
) -> None:  # fmt: skip
    """OCR 1470-2 (D-176): the whole-project start takes every image from the bundle (``--pull never``), as the
    update's start does, unless the box file says ``TB_INSTALL_PULL=missing``; a caller's exported value never
    decides it."""
    deploy = _box(tmp_path, box_file)
    if caller:
        monkeypatch.setenv("TB_INSTALL_PULL", caller)
    box = Box()
    assert _run(deploy, tmp_path, monkeypatch, box) == 0, capsys.readouterr().err[-1500:]
    (up,) = [c for c in box.calls if "up" in c]
    assert up[up.index("up") :] == ["up", "-d", "--pull", want, "--wait", "--wait-timeout", "600"], up


def test_lr14_a_rerun_refused_before_any_change_starts_only_what_it_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """LR-14 (the lifecycle review): an earlier restore ended NOT as it was and left services stopped ("do not
    start the services"); the re-run is refused inside before any change (an old backup, another site). It starts
    again only what this run stopped, never what the earlier run left stopped, says those, and never says the box
    is healthy as a whole."""

    class Refused(Box):
        def container(self, argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
            assert self.running <= box_restore.RESTORE_MAY_RUN, self.running
            return 1, json.dumps({"ok": False, "state": "unchanged"})

    deploy = _box(tmp_path)
    box = Refused()
    left = {"caddy", "console", "llm-verifier"}  # left stopped by the earlier run, on data not as it was
    box.running -= left
    ran_before = set(box.running)
    got = _run(deploy, tmp_path, monkeypatch, box)
    err = capsys.readouterr().err
    assert got == 1, (got, err[-1500:])
    assert box.running == ran_before and not (box.running & left), box.running  # nothing the earlier run left
    (up,) = [c for c in box.calls if "up" in c]
    named = [a for a in up[up.index("--wait-timeout") + 2 :] if a != "--no-deps"]
    assert "--no-deps" in up and set(named) == ran_before - {"db"}, up  # only what this run stopped
    n = len(ran_before)
    assert f"the services this run stopped run again and are healthy: {n} of {n} (" in err, err[-1500:]
    assert "the services run again and are healthy" not in err, err[-1500:]
    assert "not started by this run, as it found them stopped: caddy, console, llm-verifier" in err, err[-1500:]


@pytest.mark.parametrize("db", ["stopped", "unhealthy", "signal"])
def test_lr14_a_refused_rerun_never_prints_a_start_of_the_whole_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db: str
) -> None:
    """OCR 1470-6: a re-run refused before any change that stopped nothing (an earlier run left every service
    stopped, or only db runs) and finds db not running or not healthy, or is signalled while it checks, prints a next
    step. That step must never be ``up --no-deps`` with no service named: compose then starts the whole project, on
    data an earlier run said not to start the services on (the harm LR-14 names)."""

    class Refused(Box):
        def container(self, argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
            return 1, json.dumps({"ok": False, "state": "unchanged"})

    deploy = _box(tmp_path)
    box = Refused(unhealthy=("db",) if db == "unhealthy" else ())
    box.running = set() if db == "stopped" else {"db"}
    if db == "signal":
        box.signal = Interrupt("health", "int")
    got = _run(deploy, tmp_path, monkeypatch, box)
    err = capsys.readouterr().err
    assert got == (130 if db == "signal" else 1) and "are healthy" not in err, (got, err[-1500:])
    assert not [c for c in box.calls if "up" in c], box.calls  # nothing was started
    starts = [shlex.split(m) for m in re.findall(r"then (\S+ compose .*? up .*?)(?:,| \(RUNBOOK|$)", err, re.M)]
    assert starts, err[-1500:]
    for s in starts:  # each start the person is told names what it starts; never the whole project
        named = s[s.index("--wait-timeout") + 2 :]
        assert [a for a in named if a != "--no-deps"], s
        assert not (set(named) - {"--no-deps", "db"}), s


@pytest.mark.parametrize("path", ["shortfall", "signal", "nothing-stopped"])
def test_lr14_a_refused_rerun_names_what_it_found_stopped_on_every_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], path: str
) -> None:
    """OCR 1470-6 and 1470-7: after a refused restore the services it found stopped are named on the shortfall and
    the interrupt paths too, and a run that stopped nothing says so: never "the services this run stopped"."""

    class Refused(Box):
        def container(self, argv: list[str], values: dict[str, str], base: object = None) -> tuple[int, str]:
            return 1, json.dumps({"ok": False, "state": "unchanged"})

    deploy = _box(tmp_path)
    box = Refused(never_starts=("lake",) if path == "shortfall" else ())
    if path == "nothing-stopped":
        box.running = {"db"}
    else:
        box.running -= {"caddy", "console"}
    if path == "signal":
        box.signal = Interrupt("health", "int")
    got = _run(deploy, tmp_path, monkeypatch, box)
    err = capsys.readouterr().err
    assert got == {"shortfall": 1, "signal": 130, "nothing-stopped": 1}[path], (got, err[-1500:])
    assert "are healthy" not in err or path == "nothing-stopped", err[-1500:]
    assert "not started by this run, as it found them stopped: " in err, err[-1500:]
    assert "caddy" in err.split("as it found them stopped: ")[1].split(".")[0], err[-1500:]
    if path == "nothing-stopped":
        assert "this run stopped nothing and started nothing; db runs and is healthy (1 of 1)" in err, err[-1500:]
        assert "the services this run stopped" not in err and not [c for c in box.calls if "up" in c]
