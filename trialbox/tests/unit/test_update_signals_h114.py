"""H-114 (ESC-4): the update's signals. SIGINT, SIGTERM and SIGHUP are handled alike; the first one stops the update
where a failure is caught, and from then on, and for the whole of a rollback, no signal stops anything: the box ends
fully on the new release or fully back on the old one, the error line and the ``update.rolled_back`` /
``update.applied`` audit event say which, and a rollback cut short anyway (``kill -9``) is found by the next run and
finished by ``tools/apply_update.sh rollback`` (the marker and ``point.json``, D-210; H-99 kept them for a PoC box).

Each case runs the real :class:`tools.trialbox.update.Updater` in a child process of its own with a stand-in box
whose steps send real signals to that process (a signal the updater leaves to its default ends the child, never this
test run). ``tools/apply_update.sh`` is run as it is, with stand-ins for the verifier, the settings guard and the
update path, as tests/unit/test_poc_stops_h94.py does."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

DRIVER = r"""
import json, os, signal, sys, time
from pathlib import Path
from tools import update_status as us
from tools.trialbox import update as up

spec = json.loads(Path(sys.argv[1]).read_text())
out = Path(sys.argv[2])
calls = Path(spec["calls"])
updates = Path(spec["updates"])
where = spec.get("signals", {})


def note(name):
    with calls.open("a") as fh:
        fh.write(name + "\n")


sent = set()


def send(at):  # each place sends its signals once (the check runs again after a rollback)
    if at in sent:
        return
    sent.add(at)
    for name in where.get(at, []):
        if spec.get("closed_terminal") and name == "SIGHUP":  # the session is gone: its terminal cannot be written
            r, w = os.pipe()
            os.close(r)
            os.dup2(w, 1)
            os.dup2(w, 2)
        note(f"send {name} at {at}")
        os.kill(os.getpid(), getattr(signal, name))
        for _ in range(50):  # the handler runs between two bytecodes; some work after each signal
            time.sleep(0.001)
        note(f"after {name} at {at}")


class Box:
    name = "stand-in"

    def _step(self, n):
        note(n)
        send(n)
        if spec.get("fail") == n:
            raise RuntimeError(f"{n} broke")

    def running(self):
        return True

    def preflight(self, plan):
        self._step("preflight")
        return []

    def backup(self, plan, rb):
        self._step("backup")
        return "nas"

    def resume(self, plan):
        self._step("resume")
        note("resume done")

    def snapshot(self, plan, rb, point):
        self._step("snapshot")
        point.images["trialbox/lake:1"] = "trialbox/lake:rollback-B1"

    def apply(self, plan, rb, point):
        self._step("apply")
        return []

    def restart(self, plan):
        self._step("restart")

    def post_apply(self, plan):
        self._step("post_apply")
        return []

    def check(self, plan):
        self._step("check")
        return "healthy"

    def rollback(self, plan, rb, point):
        note("rollback")
        send("rollback")
        if spec.get("rollback_dies"):
            raise SystemExit("the rollback's step was killed")
        note("rollback done")

    def audit(self, event, plan, detail):
        with Path(spec["audits"]).open("a") as fh:
            fh.write(json.dumps([event, detail]) + "\n")


stage = Path(spec["stage"])
stage.mkdir(parents=True, exist_ok=True)
compat = {"format": us.COMPAT_FORMAT, "bundle_id": "B1", "rows": [{}], "provides": {"model_pin": "judge@2"}}
plan = up.Plan("B1", "f" * 64, "vendor", [], stage, release_seq=2, compat=compat,
               trust_after={"format": us.TRUST_FORMAT, "keys": {"ed25519:" + "1" * 16: {}}})


def on_step(name):
    note(f"step {name}")
    send(f"step {name}")


res = {}
try:
    if spec.get("mode") == "recover":
        res["result"] = up.Updater(Box(), updates, say=lambda m: print(m, flush=True)).recover("B1")
    else:
        res["result"] = up.Updater(Box(), updates, say=lambda m: print(m, flush=True), on_step=on_step).run(plan)
    res["outcome"] = "ok"
except up.UpdateRefused as exc:
    res["outcome"], res["message"] = "refused", str(exc)
except up.UpdateFailed as exc:
    res["outcome"], res["message"] = "failed", str(exc)
except BaseException as exc:  # anything else escaped the updater: the case fails on it
    res["outcome"], res["message"] = f"escaped {type(exc).__name__}", str(exc)
res["result"] = {k: v for k, v in (res.get("result") or {}).items() if k != "steps"}
res["marker"] = us.marker(updates)
res["installed"] = us.installed(updates).get("release_seq") if (updates / us.INSTALLED).exists() else None
out.write_text(json.dumps(res))
"""


def _drive(tmp: Path, **spec: Any) -> dict[str, Any]:
    """The updater in a child process; returns what it ended with, the box's calls and the audit events."""
    tmp.mkdir(parents=True, exist_ok=True)
    driver = tmp / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    spec.setdefault("updates", str(tmp / "updates"))
    spec.update(stage=str(tmp / "stage"), calls=str(tmp / "calls.txt"), audits=str(tmp / "audits.jsonl"))
    (tmp / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    out = tmp / "out.json"
    out.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    env.update(PYTHONPATH=f"{ROOT}:{ROOT / 'libs'}", TB_DOCKER="true")
    r = subprocess.run([sys.executable, str(driver), str(tmp / "spec.json"), str(out)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    calls = (tmp / "calls.txt").read_text().splitlines() if (tmp / "calls.txt").exists() else []
    audits = [json.loads(x) for x in (tmp / "audits.jsonl").read_text().splitlines()] \
        if (tmp / "audits.jsonl").exists() else []  # fmt: skip
    assert out.is_file(), f"the update process ended by itself (rc {r.returncode}) after {calls}: {r.stderr[-1500:]}"
    return {**json.loads(out.read_text()), "calls": calls, "audits": audits, "rc": r.returncode, "err": r.stderr}


def _rolled_back_whole(d: dict[str, Any], first: str | None, ignored: list[str]) -> None:
    """Fully back on the old release: the rollback ran to its end, the check after it, the marker gone, no record of
    the new release, the error line and the audit event both say so and name the signals."""
    assert d["outcome"] == "failed", d
    assert "rolled back" in d["message"] and "back on the release before B1" in d["message"], d["message"]
    assert "rollback done" in d["calls"] and d["calls"].index("rollback done") < len(d["calls"]) - 1
    assert d["calls"][d["calls"].index("rollback done") + 1] == "check"  # the check after the rollback
    assert d["marker"] is None and d["installed"] is None
    events = [e for e, _ in d["audits"]]
    assert events == ["update.rolled_back"], events
    detail = d["audits"][0][1]
    assert detail["rolled_back"] is True and detail["state"] == "previous release"
    assert detail.get("signal") == first and detail.get("signals_ignored", []) == ignored, detail


PAIRS = [("SIGINT", "SIGTERM"), ("SIGTERM", "SIGINT"), ("SIGHUP", "SIGTERM"), ("SIGTERM", "SIGHUP"),
         ("SIGHUP", "SIGINT"), ("SIGINT", "SIGHUP"), ("SIGHUP", "SIGHUP"), ("SIGINT", "SIGINT")]  # fmt: skip


@pytest.mark.parametrize(("one", "two"), PAIRS)
def test_i1_a_second_signal_never_abandons_the_update_s_rollback(tmp_path: Path, one: str, two: str) -> None:
    """THE INVARIANT. The first signal stops the apply; the second comes during the rollback it started: the
    rollback runs to its end, the box is fully on the old release, and both signals are named."""
    d = _drive(tmp_path, signals={"apply": [one], "rollback": [two]})
    assert d["calls"][d["calls"].index(f"send {one} at apply") + 1] == "rollback"  # stopped at once, not later
    _rolled_back_whole(d, first=one, ignored=[two])
    assert f"stopped by {one}" in d["message"]


@pytest.mark.parametrize(("one", "two"), PAIRS)
def test_i2_two_signals_during_a_rollback_a_failure_started_are_both_ignored(tmp_path: Path, one: str,
                                                                            two: str) -> None:  # fmt: skip
    d = _drive(tmp_path, fail="restart", signals={"rollback": [one, two]})
    _rolled_back_whole(d, first=None, ignored=[one, two])
    assert "RuntimeError: restart broke" in d["message"]


@pytest.mark.parametrize("sig", ["SIGINT", "SIGTERM", "SIGHUP"])
@pytest.mark.parametrize(
    ("at", "ends"),
    [
        ("preflight", "nothing"), ("step backup", "nothing"), ("backup", "nothing"),
        ("step rollback point", "nothing"), ("snapshot", "nothing"),
        ("step apply", "old"), ("apply", "old"), ("step migrate and restart", "old"), ("restart", "old"),
        ("step rulesets", "old"), ("post_apply", "old"), ("step check", "old"), ("check", "old"),
        ("step refdata", "new"), ("step finish", "new"),
    ],
)  # fmt: skip
def test_b1_a_signal_at_each_step_boundary_leaves_the_box_on_one_release(tmp_path: Path, sig: str, at: str,
                                                                        ends: str) -> None:  # fmt: skip
    """INT, TERM and HUP alike, at each step's start (the marker names it) and inside each step: before the rollback
    point nothing has changed and the services are started again; from the apply to the check the update is rolled
    back; after the check the checked release is finished. Never a marker left, never a box between the two."""
    d = _drive(tmp_path, signals={at: [sig]})
    assert d["marker"] is None, d
    if ends == "nothing":
        assert d["outcome"] in ("refused", "failed") and "nothing was changed" in d["message"], d
        assert d["installed"] is None and "apply" not in d["calls"]
        if at != "preflight":
            assert "resume done" in d["calls"]  # the services backup stopped are started again
    elif ends == "old":
        _rolled_back_whole(d, first=sig, ignored=[])
    else:
        assert d["outcome"] == "ok" and d["installed"] == 2, d
        assert [e for e, _ in d["audits"]] == ["update.applied"]
        assert d["audits"][0][1].get("signal") == sig and d["result"].get("signal") == sig


def test_h1_a_hangup_whose_terminal_is_gone_still_rolls_back(tmp_path: Path) -> None:
    """A closed session: SIGHUP, then every write to the terminal fails, then SIGTERM. The progress lines cannot
    end the rollback; the history file keeps them."""
    d = _drive(tmp_path, closed_terminal=True, signals={"apply": ["SIGHUP"], "rollback": ["SIGTERM"]})
    _rolled_back_whole(d, first="SIGHUP", ignored=["SIGTERM"])
    hist = (tmp_path / "updates" / "history.jsonl").read_text()
    assert '"step": "rollback", "ok": true' in hist and "SIGTERM ignored: the rollback finished" in hist


def test_r1_a_rollback_cut_short_is_found_by_the_next_run_and_finished(tmp_path: Path) -> None:
    """Whatever still ends a rollback's step (here SystemExit from it) is caught: ``ROLLBACK FAILED``, the audit
    event says the box may be between the two releases, the marker stays at "rollback failed". The next update is
    refused while it stands; ``tools/apply_update.sh rollback`` (``recover``) finishes it, a signal during that
    recovery ignored too."""
    d = _drive(tmp_path / "a", signals={"apply": ["SIGTERM"]}, rollback_dies=True)
    assert d["outcome"] == "failed" and "ROLLBACK FAILED" in d["message"] and "between the two releases" in \
        d["message"], d  # fmt: skip
    assert (d["marker"] or {}).get("step") == "rollback failed"
    detail = d["audits"][-1][1]
    assert d["audits"][-1][0] == "update.rolled_back" and detail["rolled_back"] is False
    assert detail["state"] == "between releases (rollback failed)" and detail["signal"] == "SIGTERM"
    updates = tmp_path / "a" / "updates"
    again = _drive(tmp_path / "b", updates=str(updates))
    assert again["outcome"] == "refused" and "B1 is unfinished (step 'rollback failed')" in again["message"]
    rec = _drive(tmp_path / "c", updates=str(updates), mode="recover", signals={"rollback": ["SIGINT", "SIGTERM"]})
    assert rec["outcome"] == "ok" and rec["marker"] is None, rec
    assert rec["calls"][:3] == ["rollback", "send SIGINT at rollback", "after SIGINT at rollback"]
    assert "rollback done" in rec["calls"]
    detail = rec["audits"][-1][1]
    assert detail["recovered"] is True and detail["state"] == "previous release"
    assert detail["signals_ignored"] == ["SIGINT", "SIGTERM"] and "signal" not in detail


# ------------------------------------------------------------------------------------------ tools/apply_update.sh
AU_DOCKER = '#!/bin/sh\necho \'{"bundle_id": "b1", "stand_in": true}\'\n'
AU_PYTHON3 = r"""#!/bin/sh
case "$1 $2 $3" in "-m tools.trialbox update")
  [ -z "$TB_H114_SIG_UPDATE" ] || kill -"$TB_H114_SIG_UPDATE" "$PPID"
  echo "update path ran (stand-in)"; exit 7 ;;
esac
case "$1 $2" in "-c import") exit 1 ;; esac
exec "$TB_H114_REAL_PY" "$@"
"""


def _apply_update(tmp: Path, **env: str) -> subprocess.CompletedProcess[str]:
    box = tmp / "box"
    (box / "tools").mkdir(parents=True)
    (box / "deploy" / "keys").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "apply_update.sh", box / "tools" / "apply_update.sh")
    (box / "deploy" / "keys" / "vendor_ed25519.pub").write_text("stand-in key\n")
    (box / "deploy" / ".env").write_text("TB_ENV=TEST\n")
    # the settings guard: the last step before the update path; a signal to the shell while it runs
    (box / "deploy" / "settings_guard.sh").write_text(
        '#!/bin/sh\n[ -z "$TB_H114_SIG_GUARD" ] || kill -"$TB_H114_SIG_GUARD" "$PPID"\nexit 0\n'
    )
    (tmp / "b.tar").write_bytes(b"stand-in bundle\n")
    b = tmp / "bin"
    b.mkdir()
    for name, text in (("docker", AU_DOCKER), ("python3", AU_PYTHON3)):
        (b / name).write_text(text, encoding="utf-8")
        (b / name).chmod(0o755)
    full = {k: v for k, v in os.environ.items() if not k.startswith(("TB_", "PYTHON"))}
    full.update(PATH=f"{b}:{os.environ['PATH']}", TB_VERIFY_IN_DOCKER="1", TB_H114_REAL_PY=sys.executable,
                TB_SECRETS_HOST_DIR=str(tmp / "no-secrets"), TMPDIR=str(tmp), **env)  # fmt: skip
    return subprocess.run(["sh", str(box / "tools" / "apply_update.sh"), str(tmp / "b.tar")], cwd=tmp, env=full,
                          capture_output=True, text=True, check=False, timeout=120)  # fmt: skip


@pytest.mark.parametrize(("sig", "rc"), [("INT", 130), ("TERM", 143), ("HUP", 129)])
def test_s1_a_signal_before_the_update_path_ends_the_script_and_changes_nothing(tmp_path: Path, sig: str,
                                                                               rc: int) -> None:  # fmt: skip
    r = _apply_update(tmp_path, TB_H114_SIG_GUARD=sig)
    assert "update path ran" not in r.stdout, r.stdout + r.stderr
    assert r.returncode == rc and f"stopped by SIG{sig} before the update started; nothing was changed" in r.stderr
    assert not list(tmp_path.glob("tb-update.*"))  # the stage is removed


@pytest.mark.parametrize("sig", ["INT", "TERM", "HUP"])
def test_s2_a_signal_to_the_shell_during_the_update_path_leaves_it_its_own_end(tmp_path: Path, sig: str) -> None:
    """The update path took the terminal's signal itself and said its state: the shell adds no line of its own and
    ends with the update path's code."""
    r = _apply_update(tmp_path, TB_H114_SIG_UPDATE=sig)
    assert "update path ran (stand-in)" in r.stdout and r.returncode == 7, r.stdout + r.stderr
    assert "nothing was changed" not in r.stderr and not list(tmp_path.glob("tb-update.*"))


def test_the_handlers_are_put_back_after_the_update(tmp_path: Path) -> None:
    """In this process: an update leaves the process's own handlers as they were (pytest's SIGINT included)."""
    sys.path.insert(0, str(ROOT))
    from tools.trialbox import update as up

    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    with up.Stops():
        pass
    assert {s: signal.getsignal(s) for s in before} == before


# ------------------------------------------------------------------------------------------ the card's other rows
def test_1409_2_a_payload_that_is_no_longer_a_file_on_the_second_read_is_refused(tmp_path: Path) -> None:
    """OCR 1409-2: the second read of the stick pops each signed name before it checks the member is a file, so a
    name that came back as a link (the stick changed between the two reads) was dropped in silence."""
    import io
    import tarfile

    sys.path.insert(0, str(ROOT))
    from tools.trialbox import update as up

    bundle = tmp_path / "b.tar"
    with tarfile.open(bundle, "w") as tf:
        body = b"synthetic weights"
        ok = tarfile.TarInfo("files/models/a.bin")
        ok.size = len(body)
        tf.addfile(ok, io.BytesIO(body))
        link = tarfile.TarInfo("files/models/b.bin")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/hostname"
        tf.addfile(link)
    files = [{"path": f"models/{n}", "kind": "model", "sha256": "0" * 64, "size": 17} for n in ("a.bin", "b.bin")]
    with pytest.raises(up.UpdateFailed, match="files/models/b.bin as something other than a file"):
        up.streamed_payloads(bundle, {"files": files}, ["model"])
    assert [p.path for p in up.streamed_payloads(bundle, {"files": files[:1]}, ["model"])] == ["models/a.bin"]


def test_1421_3_a_host_restore_and_a_backup_never_run_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """OCR 1421-3: the host restore took only its own lock, so the nightly backup could run over the folders it was
    restoring. Now it holds the backup's lock (``deploy/site/backup.lock``) for its whole run: a restore under a
    running backup is refused before anything stops, and a backup under a running restore is refused (BackupBusy)."""
    import fcntl

    sys.path.insert(0, str(ROOT))
    from tests.unit.test_restore_from_the_host_h100 import Recorder, _box, _restore
    from tools.trialbox import backup_schedule as bs

    deploy = _box(tmp_path)
    (deploy / "site").mkdir(parents=True, exist_ok=True)
    fd = os.open(deploy / "site" / "backup.lock", os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        rec = Recorder(running=["db", "console"])
        code, seen = _restore(deploy, tmp_path, monkeypatch, rec, "{}", 0, "--restart")
        assert code == 2 and not seen and not [c for c in rec.calls if "stop" in c], rec.calls
        assert "a backup of this box is running (deploy/site/backup.lock)" in capsys.readouterr().err
    finally:
        os.close(fd)
    during: list[bool] = []

    class Nightly(Recorder):  # the nightly, started while the restore runs the box's commands
        def __call__(self, argv: list[str], **kw: object) -> str:
            with bs._lock(deploy) as mine:
                during.append(mine)
            return super().__call__(argv, **kw)

    code, seen = _restore(deploy, tmp_path, monkeypatch, Nightly(running=["db", "console"]), "{}", 0, "--restart")
    assert code == 0 and len(seen) == 1 and during and not any(during), during
    with bs._lock(deploy) as mine:  # and free again once the restore has ended
        assert mine
