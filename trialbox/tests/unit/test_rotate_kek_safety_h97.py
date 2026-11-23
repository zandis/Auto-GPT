"""H-97, the review of #1429 (F1, F2, F4, F5): a KEK rotation is audited before it changes anything, survives a kill
at any step, writes its events as the audit folder's owner, and runs one at a time.

- F1: the started event is written before any key file changes; if it cannot be written the rotation is refused and
  nothing changes. The done event follows the commit; if it cannot be written the journal stays and ``status
  --audit-dir`` writes it.
- F2: run as root against an audit folder another user owns, the append is made by that user (a child process).
- F4: a journal in the secrets folder names the step; a kill at any step leaves a box that ``status --audit-dir`` (or
  the next ``rotate-kek``) finishes or rolls back, every key opening under the KEK ``kek.json`` names.
- F5: an exclusive lock on the secrets folder: a second rotation while one runs is refused and changes nothing.

The passphrases here are synthetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tb_common import kek as K
from tb_common.audit import AuditLog

from tools import keys

pytestmark = pytest.mark.nodb
OLD = "synthetic-h97-" + "safety-old-passphrase"  # synthetic
NEW = "synthetic-h97-" + "safety-new-passphrase"  # synthetic
ROOT = Path(__file__).resolve().parents[2]


def _pp(path: Path, text: str) -> Path:
    path.write_text(text + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _box(tmp: Path) -> dict[str, Path]:
    """A DEV box sealed under OLD with two wrapped keys and its audit chain; the KEK not unsealed."""
    deploy = tmp / "deploy"
    deploy.mkdir(parents=True)
    (deploy / ".env").write_text("TB_ENV=DEV\n", encoding="utf-8")
    sec = tmp / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(os.urandom(32))
    (sec / "objects.key").write_bytes(os.urandom(32))
    rc = keys.main(["init", "--backend", "passphrase", "--secrets", str(sec), "--scrypt-n", "1024",
                    "--passphrase-file", str(_pp(tmp / "init.pass", OLD))], env={})  # fmt: skip
    assert rc == 0
    audit = tmp / "audit"
    AuditLog(audit).append("test.box_ready", actor="tester")
    return {"sec": sec, "audit": audit, "deploy": deploy, "tmp": tmp, "runtime": tmp / "kek.runtime"}


def _argv(b: dict[str, Path], new: str = NEW) -> list[str]:
    return ["rotate-kek", "--backend", "passphrase", "--secrets", str(b["sec"]), "--scrypt-n", "1024",
            "--passphrase-file", str(_pp(b["tmp"] / "old.pass", OLD)),
            "--new-passphrase-file", str(_pp(b["tmp"] / f"new-{abs(hash(new))}.pass", new)),
            "--keep-passphrase-files", "--audit-dir", str(b["audit"])]  # fmt: skip


def _env(b: dict[str, Path]) -> dict[str, str]:
    return {"TB_KEK_FILE": str(b["runtime"])}


def _events(audit: Path) -> list[str]:
    rows = [json.loads(x) for f in sorted(audit.glob("*.jsonl")) for x in f.read_text(encoding="utf-8").splitlines()]
    return [str(e["event"]) for e in rows if str(e["event"]).startswith("keys.rotate_kek")]


def _opens_under(sec: Path) -> str | None:
    """Which passphrase opens every wrapped key under the KEK kek.json names, or None (a lost key)."""
    meta = K.read_meta(sec) or {}
    for name, phrase in (("OLD", OLD), ("NEW", NEW)):
        kek = K.derive_from_passphrase(phrase, meta)
        if K.kek_id(kek) != meta.get("kek_id"):
            continue
        try:
            for p in sorted(sec.glob("*" + K.WRAPPED_SUFFIX)):
                key = p.name[: -len(K.WRAPPED_SUFFIX)]
                K.unwrap(kek, K.read_wrapped(sec / key), key)
        except K.KekError:
            return None
        return name
    return None


def _leftovers(sec: Path) -> list[str]:
    """A staged file, the journal, or a write cut short (``.<name>.<hex>.tmp``)."""
    return sorted(f.name for f in sec.iterdir() if f.name.endswith((".next", ".tmp")) or f.name == keys.JOURNAL)


@pytest.fixture(autouse=True)
def _the_box_says_dev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(keys, "DEFAULT_DEPLOY", str(tmp_path / "deploy"))


def test_a_rotation_whose_started_event_cannot_be_written_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: the audit volume is full (AuditFull, an OSError): the started event fails, so no key file, no kek.json, no
    journal changes, and the old passphrase still opens every key."""
    b = _box(tmp_path)
    before = {f.name: f.read_bytes() for f in b["sec"].iterdir()}
    monkeypatch.setenv("TB_AUDIT_MIN_FREE_MB", str(1 << 40))  # more than any disk: the append refuses
    assert keys.main(_argv(b), env=_env(b)) == 1
    err = capsys.readouterr().err
    assert "started event could not be written" in err and "nothing was changed" in err and NEW not in err
    assert {f.name: f.read_bytes() for f in b["sec"].iterdir()} == before
    assert _events(b["audit"]) == [] and _opens_under(b["sec"]) == "OLD"


def test_a_done_event_not_written_keeps_the_journal_and_status_writes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: the started event is written, the commit made, then the done event fails: the KEK is the new one, the
    journal stays (status says the rotation was cut short), and status --audit-dir writes the done event."""
    b = _box(tmp_path)
    real = keys.append_audit
    calls: list[str] = []

    def fail_the_done(where: Path, event: str, detail: dict[str, object]) -> None:
        calls.append(event)
        if event == keys.ROTATE_EVENT:
            raise OSError("synthetic: the audit volume went away")
        real(where, event, detail)

    monkeypatch.setattr(keys, "append_audit", fail_the_done)
    assert keys.main(_argv(b), env=_env(b)) == 1
    assert "done event could not be written" in capsys.readouterr().err
    assert _opens_under(b["sec"]) == "NEW" and _leftovers(b["sec"]) == [keys.JOURNAL]
    assert _events(b["audit"]) == [keys.ROTATE_STARTED]
    monkeypatch.setattr(keys, "append_audit", real)
    assert keys.main(["status", "--secrets", str(b["sec"])], env=_env(b)) == 1  # no audit folder: a problem
    assert "cut short" in capsys.readouterr().out
    assert keys.main(["status", "--secrets", str(b["sec"]), "--audit-dir", str(b["audit"])], env=_env(b)) == 0
    assert "was finished" in capsys.readouterr().err
    assert _events(b["audit"]) == [keys.ROTATE_STARTED, keys.ROTATE_EVENT] and _leftovers(b["sec"]) == []


#: the rotation in a child process, killed at its n-th write (os.replace: every file write and rename, the audit's
#: head anchor among them): os._exit runs no clean-up, as with SIGKILL or a power cut
_KILLED_AT = """
import os, sys
from tools import keys
n, deploy, argv = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
keys.DEFAULT_DEPLOY = deploy
count, real = [0], os.replace
def kill_at_n(src, dst):
    count[0] += 1
    if count[0] == n:
        os._exit(137)
    real(src, dst)
os.replace = kill_at_n
sys.exit(keys.main(argv))
"""


def _child_env(b: dict[str, Path]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_KEK")}
    env.update(
        PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")), TB_KEK_FILE=str(b["runtime"])
    )
    return env


@pytest.mark.parametrize("resumer", ["status", "rotate-kek"])
def test_a_kill_at_any_step_leaves_keys_that_open_and_the_next_command_finishes_or_rolls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], resumer: str
) -> None:
    """F4, THE RULE for a rotation cut short: the rotation is killed (no clean-up runs, as with SIGKILL or a power
    cut) at each of its writes in turn. After each, the next status --audit-dir (or rotate-kek) leaves no journal and
    no staged file, every key opens under the KEK kek.json names (the old or the new passphrase, never neither), and
    the chain says which: a done event for the new KEK, a rolled-back event for a started rotation that kept the old."""
    seen: set[str] = set()
    n = 0
    while True:
        n += 1
        assert n < 80, "the rotation never finished"
        b = _box(tmp_path / f"kill-{n}")
        child = subprocess.run([sys.executable, "-c", _KILLED_AT, str(n), str(b["deploy"]), *_argv(b)], check=False, cwd=ROOT,
                               env=_child_env(b), capture_output=True, text=True, timeout=120)  # fmt: skip
        code = child.returncode
        capsys.readouterr()
        if code == 0:  # finished before its n-th write: every step has been killed
            break
        assert code == 137, (code, child.stderr[-2000:])
        if resumer == "status":
            rc = keys.main(["status", "--secrets", str(b["sec"]), "--audit-dir", str(b["audit"])], env=_env(b))
            assert rc == 0, (n, capsys.readouterr())
        else:
            assert keys.main(_argv(b), env=_env(b)) == 0, (n, capsys.readouterr())  # resumes, or rotates afresh
        capsys.readouterr()
        assert _leftovers(b["sec"]) == [], n
        opens = _opens_under(b["sec"])
        events = _events(b["audit"])
        assert opens in ("OLD", "NEW"), (n, events)
        seen.add(opens)
        if opens == "NEW":
            assert keys.ROTATE_STARTED in events and keys.ROTATE_EVENT in events, (n, events)
        elif keys.ROTATE_STARTED in events:
            assert keys.ROTATE_ROLLED_BACK in events, (n, events)
    assert n > 8 and seen == {"OLD", "NEW"}  # kills on both sides of the commit


def test_a_rotation_cut_short_is_a_custody_problem_until_finished(tmp_path: Path) -> None:
    """F4: the doctor and check read custody: a journal is a problem that names the command that clears it."""
    b = _box(tmp_path)
    (b["sec"] / keys.JOURNAL).write_text(json.dumps({"format": keys.JOURNAL_FORMAT, "step": "staging", "keys": []}))
    problems = K.custody(b["sec"], _env(b)).problems
    assert any("cut short" in p and "status --audit-dir" in p for p in problems)


def test_a_second_rotation_while_one_runs_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """F5: while the secrets folder is held (a rotation running), rotate-kek is refused and nothing changes."""
    b = _box(tmp_path)
    before = {f.name: f.read_bytes() for f in b["sec"].iterdir()}
    with keys._Locked(b["sec"]):
        assert keys.main(_argv(b), env=_env(b)) == 1
    err = capsys.readouterr().err
    assert "another key command holds" in err and "nothing was changed" in err
    assert {f.name: f.read_bytes() for f in b["sec"].iterdir()} == before and _events(b["audit"]) == []
    assert keys.main(_argv(b), env=_env(b)) == 0 and _opens_under(b["sec"]) == "NEW"  # released: it runs


def test_two_rotations_at_once_never_lose_a_key(tmp_path: Path) -> None:
    """F5: two rotate-kek processes started together (two operators, or a re-run), five times over: at most one
    rotates, and every key opens under the KEK kek.json names, with no journal or staged file left."""
    for round_ in range(5):
        b = _box(tmp_path / f"round-{round_}")
        env = _child_env(b)
        script = (f"import sys; from tools import keys; keys.DEFAULT_DEPLOY = {str(b['deploy'])!r}; "
                  "sys.exit(keys.main(sys.argv[1:]))")  # fmt: skip
        procs = [subprocess.Popen([sys.executable, "-c", script, *_argv(b, phrase)], cwd=ROOT, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 for phrase in (NEW, "synthetic-h97-safety-the-other-one")]  # fmt: skip
        codes = [p.wait(timeout=120) for p in procs]
        assert codes.count(0) <= 1 and set(codes) <= {0, 1}, codes
        assert _leftovers(b["sec"]) == [], round_
        meta = K.read_meta(b["sec"]) or {}
        opened = [phrase for phrase in (OLD, NEW, "synthetic-h97-safety-the-other-one")
                  if K.kek_id(K.derive_from_passphrase(phrase, meta)) == meta["kek_id"]]  # fmt: skip
        assert len(opened) == 1, round_
        kek = K.derive_from_passphrase(opened[0], meta)
        for name in ("site_hmac.key", "objects.key"):
            assert K.unwrap(kek, K.read_wrapped(b["sec"] / name), name)


def test_as_root_the_append_is_made_by_the_audit_folders_owner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: run as root against an audit folder owned by the console's user (10001 here), each rotation event is
    appended by a child process started as that user and group with no other groups, so a day file or lock it
    creates is that user's and the console still appends to it. (Stood in: the child runs as the test's own user,
    and the identity it was asked for is recorded.)"""
    b = _box(tmp_path)
    asked: list[tuple[int, int, str]] = []
    real = keys._run_append

    def as_this_user(argv: list[str], data: str, uid: int, gid: int) -> subprocess.CompletedProcess[str]:
        asked.append((uid, gid, json.loads(data)["event"]))
        return real(argv, data, os.getuid(), os.getgid())

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(keys, "_audit_owner", lambda where: (10001, 10001))
    monkeypatch.setattr(keys, "_run_append", as_this_user)
    assert keys.main(_argv(b), env=_env(b)) == 0, capsys.readouterr().err
    assert asked == [(10001, 10001, keys.ROTATE_STARTED), (10001, 10001, keys.ROTATE_EVENT)]
    assert _events(b["audit"]) == [keys.ROTATE_STARTED, keys.ROTATE_EVENT]
    for phrase in (OLD, NEW):
        assert all(phrase not in f.read_text(encoding="utf-8") for f in b["audit"].glob("*.jsonl"))


def test_the_append_as_another_user_that_fails_refuses_the_rotation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1 with F2: the owner's child cannot append (it exits non-zero): the started event is missing, so nothing
    changes."""
    b = _box(tmp_path)
    before = {f.name: f.read_bytes() for f in b["sec"].iterdir()}

    def refused(argv: list[str], data: str, uid: int, gid: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "PermissionError: synthetic\n")

    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(keys, "_audit_owner", lambda where: (10001, 10001))
    monkeypatch.setattr(keys, "_run_append", refused)
    assert keys.main(_argv(b), env=_env(b)) == 1
    assert "started event could not be written" in capsys.readouterr().err
    assert {f.name: f.read_bytes() for f in b["sec"].iterdir()} == before and _opens_under(b["sec"]) == "OLD"
