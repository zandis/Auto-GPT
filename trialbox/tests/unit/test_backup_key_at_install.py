"""E2E P-01 (the integrator's ruling Q1 of 2026-11-27): a PRODUCTION box makes its backup key at install, and a
backup made with it restores.

The journey the E2E run could not walk: a PRODUCTION box (``TB_ENV`` unset) is installed with no backup key; its
install shows the key once on the terminal (the paper copy hospital IT keeps sealed), the screen is cleared, IT types
the whole copy back, and only then ``backup.pub`` exists. ``trialbox backup-keygen`` stays refused there. The nightly
backup is made with that public key; IT types the letters of the paper copy into a file, as the copy says, and the
restore drill restores that backup from it into scratch databases. An unattended install (no terminal) seals the key
under the install's KEK passphrase (the integrator's ruling (1) of 2026-11-27) and the same backup restores from it.
Every row and passphrase is synthetic.
"""

from __future__ import annotations

import base64
import builtins
import contextlib
import errno
import inspect
import io
import json
import os
import pty
import re
import select
import stat
import subprocess
import sys
import termios
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TextIO, cast

import pytest
from tb_common.db import Database

from tests import pg_client
from tests.unit.test_backup_key_ceremony import SITE, Box
from tools import backup_key_ceremony as bkc
from tools.trialbox import backup as bk
from tools.trialbox import restore_drill as rd
from tools.trialbox.__main__ import main as trialbox_main

LINE = re.compile(r"(\d+) \| ([A-Z2-7 ]+) \| ([A-Z2-7]{4})")
PASS = "synthetic install passphrase p01"  # the install's KEK passphrase (synthetic)
ROOT = Path(__file__).resolve().parents[2]
UNSEEN = bkc._unseen  # the real one: the stand-in terminal below has no terminal settings


def _copied(shown: str) -> list[str]:
    """The paper copy as IT copied it: the letters between the bars of each line."""
    return [" ".join(m[1].split()) for m in LINE.findall(shown)]


class Terminal:
    """The install's terminal: what was shown on it, and IT at it: Enter once the copy is made, then each line of
    the copy typed back (``wrong``: line number -> what is typed instead, every try), or ``stop`` at a read."""

    def __init__(self, wrong: dict[int, list[str]] | None = None, stop: int | None = None) -> None:
        self.shown, self.wrong, self.stop, self.reads = io.StringIO(), wrong or {}, stop, 0
        self.copy: list[str] = []

    def write(self, text: str) -> int:
        return self.shown.write(text)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self.shown.getvalue()

    def readline(self) -> str:
        self.reads += 1
        if self.reads == self.stop:
            raise KeyboardInterrupt
        if self.reads == 1:  # Enter: the copy is made (taken from the screen while it is shown)
            self.copy = _copied(self.getvalue())
            return "\n"
        n = int(re.findall(r"line (\d+) of", self.getvalue())[-1])
        tries = self.wrong.get(n)
        return (tries.pop(0) if tries else self.copy[n - 1]) + "\n"


def _tty(term: Terminal) -> TextIO:
    return cast(TextIO, term)


def _install(term: Terminal) -> dict[str, str]:
    return bkc.install(_env(), _tty(term), _tty(term))


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    b = Box(tmp_path)
    monkeypatch.setattr(bkc, "DEPLOY", b.deploy)
    monkeypatch.setattr(bkc, "PUB_DIR", b.pub_dir)
    monkeypatch.setattr(bkc, "COMPOSE", b.compose)
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    monkeypatch.delenv("TB_ENV", raising=False)  # unset: a PRODUCTION box
    monkeypatch.delenv("TB_BACKUP_PUBKEY", raising=False)
    monkeypatch.delenv("TB_BACKUP_TARGETS", raising=False)
    monkeypatch.delenv("TB_BACKUP_OFFBOX", raising=False)
    # H-04: the stand-in terminal has no terminal settings, so the echo-off context is given as a no-op here; the echo
    # is proven off on a real pseudo-terminal (test_the_command_on_a_real_terminal), and a failing one refuses
    monkeypatch.setattr(bkc, "_unseen", lambda _tty: contextlib.nullcontext())
    return b


NFS = ("0:999", "nfs4", "nas.example:/backups")  # a share's mount: its own device, no disk of the box
REAL_MOUNTINFO, REAL_MOUNT_ID = bkc.MOUNTINFO, bkc._mount_id


def _offbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """H-02 (P01-DESIGN (i)): the box's off-box target: a share mounted exactly at the folder (a fake mountinfo line:
    an NFS mount, its own device; the target's descriptor is on that mount), declared once by the install."""
    nas = tmp_path / "nas"
    nas.mkdir(exist_ok=True)
    _mounted(tmp_path, monkeypatch, (nas, *NFS, ()))
    if not (bkc.PUB_DIR / bkc.TARGET_RECORD).exists():
        bkc.declare_target(str(nas), "install", False, {})
    return nas


def _mounted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *mounts: tuple[Path, str, str, str, tuple[Path, ...]],
    first_id: int = 2_000_000_000,
    root: str = "/",
) -> None:
    """H-02: fake mounts. Each ``(mount point, major:minor, filesystem type, source, folders on it)`` is a line added
    to the real /proc/self/mountinfo, and a descriptor of its mount point or of a folder on it is on that mount. A
    second call replaces the first one's mounts (none given: no fake mount left). ``first_id`` and ``root``: a
    remount (another mount id) and a bind of another folder of the same filesystem (another mount root)."""
    lines = [REAL_MOUNTINFO.read_text(encoding="utf-8")]
    ids: list[tuple[int, list[Path]]] = []
    for i, (point, mm, fstype, src, on) in enumerate(mounts):
        mid = first_id + i  # no real mount has this id
        lines.append(f"{mid} 1 {mm} {root} {point} rw,relatime shared:1 - {fstype} {src} rw\n")
        ids.append((mid, [point, *on]))
    fake = tmp_path / "mountinfo.fake"
    fake.write_text("".join(lines), encoding="utf-8")

    def mount_id(fd: int) -> int:
        st = os.fstat(fd)
        for mid, on in ids:
            if any(p.exists() and os.path.samestat(st, p.stat()) for p in on):
                return mid
        return REAL_MOUNT_ID(fd)

    monkeypatch.setattr(bkc, "MOUNTINFO", fake)
    monkeypatch.setattr(bkc, "_mount_id", mount_id)


def _no_unnamed_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """A filesystem without unnamed files (vfat, exFAT): O_TMPFILE is refused (EOPNOTSUPP)."""
    real = os.open

    def open_(path: Any, flags: int, *a: Any, **k: Any) -> int:
        if flags & os.O_TMPFILE == os.O_TMPFILE:
            raise OSError(errno.EOPNOTSUPP, os.strerror(errno.EOPNOTSUPP))
        return real(path, flags, *a, **k)

    monkeypatch.setattr(os, "open", open_)


def _sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An unattended install's sealed key on the box (a fake NFS target declared first)."""
    _offbox(tmp_path, monkeypatch)
    return Path(bkc.install_sealed(bkc._env(), PASS)["sealed"])


def _restore_key(box: Box) -> Path:
    """P01-DESIGN (ii): the one place an unsealed key file is written."""
    return box.pub_dir / bkc.RESTORE_DIR / bkc.RESTORE_KEY


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Every key the ceremony makes, to look for it in the box's files."""
    keys: list[bytes] = []
    real = bkc.new_key

    def spy() -> bytes:
        keys.append(real())
        return keys[-1]

    monkeypatch.setattr(bkc, "new_key", spy)
    return keys


def _env() -> dict[str, str]:
    return {"TB_SITE_ID": SITE}


def _no_key_on_the_box(box: Box, key: bytes) -> None:
    """The box keeps the public half and its records, never the key: not its paper letters, not the key file's text,
    not its bytes (L-02)."""
    letters = base64.b32encode(key).decode().rstrip("=")
    body = bkc.key_text(key).decode().splitlines()[1]
    for f in box.pub_dir.iterdir():
        data = f.read_bytes()
        assert letters.encode() not in data and body.encode() not in data and key not in data, f.name


def _restores(box: Box, pub: Path, key_file: Path, tmp_path: Path, db_url: str, mp: pytest.MonkeyPatch) -> None:
    """The nightly backup made with ``pub``, then the restore drill from ``key_file`` into scratch databases."""
    for var, cmd in pg_client.env().items():
        mp.setenv(var, cmd)
    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL)"])
    db.execute("INSERT INTO marks VALUES (?, ?)", ("P1", "approach"))
    dirs = {"audit": tmp_path / "audit", "lake": tmp_path / "lake"}
    for d in dirs.values():
        d.mkdir()
    (dirs["lake"] / "patient.parquet").write_bytes(b"PAR1" + bytes(range(256)) * 50)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": SITE, **pg_client.env()}
    (backup, *_) = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)
    res = rd.drill(backup, key_file, env, work=tmp_path, free=lambda _p: 10**12)
    assert res["ok"], res
    assert res["databases"]["trialbox_wf"]["differ_count"] == 0 and res["databases"]["trialbox_wf"]["rows"] > 0


def test_a_production_box_makes_its_backup_key_at_install_and_a_backup_restores(
    box: Box,
    made: list[bytes],
    tmp_path: Path,
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # the ad hoc commands stay refused on PRODUCTION (rc1): the install is the box's one way to its key (L-02)
    assert trialbox_main(["backup-keygen", "--private", str(tmp_path / "k"), "--public", str(tmp_path / "p")]) == 1
    assert "rc1 holds no backup key ceremony" in capsys.readouterr().err
    assert not (tmp_path / "k").exists() and not (tmp_path / "p").exists()
    term = Terminal()
    rec = _install(term)
    shown = term.getvalue()
    assert box.pub.is_file() and rec["pub"] == str(box.pub)
    fp = bk.fingerprint(bk.load_public(box.pub).public_bytes_raw())
    assert rec["fingerprint"] == fp and f"fingerprint {fp}" in shown and shown.endswith(bkc.CLEAR)
    # H-01: the screen is cleared before the copy is typed back, and nothing of the key is shown after that
    before, after = shown.split(bkc.CLEAR, 1)
    assert len(LINE.findall(before)) == len(term.copy) > 1 and LINE.findall(after) == []
    assert all("".join(line.split()) not in after for line in term.copy)
    assert [e["detail"]["fingerprint"] for e in box.journal() if e["event"] == bkc.EVENT] == [fp]
    letters = "".join("".join(m[1].split()) for m in LINE.findall(shown))
    for f in box.pub_dir.iterdir():  # the box keeps the public half and its record, never a letter of the key
        assert letters not in f.read_text(encoding="utf-8"), f.name
    _no_key_on_the_box(box, made[-1])
    # a second install changes nothing: "once" is backup.pub
    with pytest.raises(bkc.Stop) as again:
        _install(Terminal())
    assert again.value.text is bkc.ALREADY and bk.fingerprint(bk.load_public(box.pub).public_bytes_raw()) == fp

    # IT types the paper copy into a file and restores the nightly backup from it
    typed = tmp_path / "usb" / "typed-from-paper.key"
    typed.parent.mkdir()
    typed.write_text("\n".join(_copied(shown)) + "\n", encoding="utf-8")
    _restores(box, box.pub, typed, tmp_path, db_url, monkeypatch)


def test_a_copy_wrong_in_an_earlier_line_makes_no_backup_pub(box: Box) -> None:
    """H-01 / P-03: the last line's check letters are right, line 1 of the copy is not: the copy kept would not
    restore, so no backup encrypts to that key."""
    term = Terminal(wrong={1: ["AAAA AAAA AAAA AAAA"] * bkc.TRIES})
    with pytest.raises(bkc.Stop) as got:
        _install(term)
    assert got.value.text is bkc.NOT_CONFIRMED and got.value.fill == {"n": 1} and not box.pub.exists()
    assert [e for e in box.journal() if e["event"] == bkc.EVENT] == []
    assert len(box.pending()) == 1  # the record of the key that was shown and not taken stays (never removed)
    assert term.getvalue().endswith(bkc.CLEAR)
    _install(Terminal())  # the install run again: a new key, shown once
    assert box.pub.is_file() and len(box.pending()) == 2


def test_a_line_typed_wrong_once_may_be_typed_again(box: Box) -> None:
    term = Terminal(wrong={2: ["AAAA"]})
    _install(term)
    assert box.pub.is_file() and "line 2 does not match its check letters" in term.getvalue()


def test_an_interrupted_install_clears_the_screen(box: Box) -> None:
    """M-01: Ctrl-C at the read-back (or any stop after the key was shown) still clears the screen and its
    scroll-back; nothing is made but the record."""
    for stop in (1, 3):
        term = Terminal(stop=stop)
        with pytest.raises(KeyboardInterrupt):
            _install(term)
        assert LINE.findall(term.getvalue()) and term.getvalue().endswith(bkc.CLEAR)
    assert not box.pub.exists() and len(box.pending()) == 2


CHILD = r"""
import json, sys
from pathlib import Path
from tools import backup_key_ceremony as b
cfg = json.loads(sys.argv[1])
b.DEPLOY = Path(cfg["deploy"]); b.PUB_DIR = b.DEPLOY / "secrets"; b.COMPOSE = cfg["compose"]
b.is_root = lambda: True; b.harden = lambda: None; b.TTY = cfg["tty"]
sys.exit(b.main(cfg["argv"]))
"""


def _on_a_terminal(
    box: Box, argv: list[str], answer: Callable[[str], str | None], timeout: float = 60
) -> tuple[int | None, str]:
    """M-04: ``main(argv)`` in a process of its own whose terminal (``TTY``, stdin, stdout and stderr) is a
    pseudo-terminal; ``answer`` gets what was shown since its last answer and returns what to type, or None. At
    ``timeout`` the process is killed, whatever its prompt said: ``(None, what was shown)``, never a test that hangs."""
    master, slave = pty.openpty()
    cfg = {"deploy": str(box.deploy), "compose": box.compose, "tty": os.ttyname(slave), "argv": argv}
    p = subprocess.Popen([sys.executable, "-c", CHILD, json.dumps(cfg)], cwd=ROOT, env=box.env(), stdin=slave,
                         stdout=slave, stderr=slave, start_new_session=True)  # fmt: skip
    os.close(slave)
    shown, fresh, deadline = b"", b"", time.monotonic() + timeout
    rc: int | None = None
    try:
        while time.monotonic() < deadline:
            if not select.select([master], [], [], 0.2)[0]:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:  # EIO: the process closed its terminal (it ended)
                break
            shown, fresh = shown + chunk, fresh + chunk
            if (say := answer(fresh.decode("utf-8", "replace"))) is not None:
                os.write(master, say.encode())
                fresh = b""
        with contextlib.suppress(subprocess.TimeoutExpired):
            rc = p.wait(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        os.close(master)
    return rc, shown.decode("utf-8", "replace")


def test_the_command_on_a_real_terminal(box: Box) -> None:
    """P-02: ``--install`` on a pseudo-terminal, as install.sh runs it (``/dev/tty`` cannot be opened ``r+``: it is
    not seekable). The copy typed back is not echoed. M-04: in a process of its own, killed at its deadline."""
    copy: list[str] = []

    def it(text: str) -> str | None:
        if not copy and "press enter" in text.lower() and LINE.search(text):
            copy.extend(_copied(text))
            return "\n"
        if copy and (m := re.search(r"line (\d+) of \d+: [^\n]*: $", text)):
            return copy[int(m.group(1)) - 1] + "\n"
        return None

    rc, shown = _on_a_terminal(box, ["--install"], it)
    assert rc == 0, shown.rsplit(bkc.CLEAR, 1)[-1]
    assert box.pub.is_file() and copy
    after = shown.split(bkc.CLEAR, 1)[1]
    assert all("".join(line.split()) not in "".join(after.split()) for line in copy)  # not echoed


def test_a_prompt_nobody_answers_ends_at_the_deadline(box: Box) -> None:
    """M-04: a prompt the driver does not know (here none is answered) is a bounded failure: the process is killed at
    its deadline; no backup.pub."""
    start = time.monotonic()
    rc, _ = _on_a_terminal(box, ["--install"], lambda _text: None, timeout=5)
    assert rc is None and time.monotonic() - start < 30
    assert not box.pub.exists()


class _NoSettings(Terminal):
    """The install's terminal whose descriptor's settings fail (H-04)."""

    def __init__(self, fd: int) -> None:
        super().__init__()
        self.fd = fd

    def fileno(self) -> int:
        return self.fd


@pytest.mark.parametrize("fails", ["read", "change"])
def test_terminal_settings_that_fail_refuse_before_a_line_is_asked(
    box: Box, monkeypatch: pytest.MonkeyPatch, fails: str
) -> None:
    """H-04: the echo cannot be turned off (the terminal's settings cannot be read, or cannot be changed): refused
    before the first line of the copy is asked, never a copy typed back visible; no backup.pub, the screen cleared."""
    monkeypatch.setattr(bkc, "_unseen", UNSEEN)
    master, slave = pty.openpty()
    null = os.open(os.devnull, os.O_RDONLY)
    try:
        if fails == "change":

            def refuse(*_a: object) -> None:
                raise termios.error(errno.EIO, "Input/output error")

            monkeypatch.setattr(termios, "tcsetattr", refuse)
        term = _NoSettings(null if fails == "read" else slave)  # /dev/null: no terminal settings to read
        with pytest.raises(bkc.Stop) as got:
            _install(term)
        assert got.value.text is bkc.TERMINAL_UNSAFE and term.reads == 1
        assert "line 1 of" not in term.getvalue() and term.getvalue().endswith(bkc.CLEAR)
        assert not box.pub.exists() and [e for e in box.journal() if e["event"] == bkc.EVENT] == []
    finally:
        for fd in (master, slave, null):
            os.close(fd)


def test_the_unseal_passphrase_is_not_echoed_on_a_terminal(
    box: Box, made: list[bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-03: ``--unseal`` run by hand, as the runbook gives it: the passphrase is asked on the terminal with its echo
    off, and never shown."""
    sealed = _sealed(tmp_path, monkeypatch)
    out = _restore_key(box)  # P01-DESIGN (ii): --out is gone; the key file is made only on the box
    asked: list[str] = []

    def it(text: str) -> str | None:
        if not asked and "passphrase" in text.lower():
            asked.append(text)
            return PASS + "\n"
        return None

    rc, shown = _on_a_terminal(box, ["--unseal", str(sealed)], it, timeout=30)
    assert rc == 0 and asked, shown
    assert PASS not in shown and bkc.read_key(out.read_bytes()) == made[-1]


def test_no_terminal_makes_nothing(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bkc, "TTY", str(tmp_path / "no-terminal"))
    monkeypatch.setattr(bkc, "harden", lambda: None)
    assert bkc.main(["--install"]) == 1
    assert capsys.readouterr().err.strip() == bkc.NO_TERMINAL["en"]
    assert not box.pub.exists() and box.pending() == []


def test_an_unattended_install_seals_the_key_under_the_install_passphrase_and_a_backup_restores(
    box: Box,
    made: list[bytes],
    tmp_path: Path,
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Residual 2 of r1p1a: an install with no terminal makes the key through the passphrase (ruling (1)), not a
    FAIL. The key is never plain on the box; the sealed file and the passphrase give the key file back."""
    _offbox(tmp_path, monkeypatch)  # H-02: the sealed copy goes to an off-box target before backup.pub
    monkeypatch.setattr(bkc, "harden", lambda: None)
    monkeypatch.setattr(bkc, "TTY", str(tmp_path / "no-terminal"))
    monkeypatch.setattr("sys.stdin", io.StringIO(PASS + "\n"))
    assert bkc.main(["--install", "--sealed-stdin"]) == 0
    out = capsys.readouterr()
    fp = bk.fingerprint(bk.load_public(box.pub).public_bytes_raw())
    sealed = box.pub_dir / bkc.sealed_name(fp)
    assert sealed.is_file() and stat.S_IMODE(sealed.stat().st_mode) == 0o600 and str(sealed) in out.out
    assert PASS not in out.out + out.err
    doc: dict[str, Any] = json.loads(sealed.read_text(encoding="utf-8"))
    assert doc["format"] == bkc.SEALED_FORMAT and doc["kdf"]["name"] == "scrypt" and len(doc["kdf"]["salt"]) == 32
    assert {"n", "r", "p"} <= set(doc["kdf"]) and PASS not in sealed.read_text(encoding="utf-8")
    assert [e["detail"]["fingerprint"] for e in box.journal() if e["event"] == bkc.EVENT] == [fp]
    _no_key_on_the_box(box, made[-1])

    # a wrong passphrase opens nothing and writes nothing
    key_file = _restore_key(box)
    monkeypatch.setattr("sys.stdin", io.StringIO("not the passphrase of it\n"))
    assert bkc.main(["--unseal", str(sealed)]) == 1
    assert "does not open with this passphrase" in capsys.readouterr().err and not key_file.exists()
    # the passphrase gives the key file back, and the nightly backup restores from it
    monkeypatch.setattr("sys.stdin", io.StringIO(PASS + "\n"))
    assert bkc.main(["--unseal", str(sealed)]) == 0
    assert str(key_file) in capsys.readouterr().out
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600 and bkc.read_key(key_file.read_bytes()) == made[-1]
    _restores(box, box.pub, key_file, tmp_path, db_url, monkeypatch)


def test_an_unattended_install_without_a_passphrase_makes_nothing(
    box: Box, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bkc, "harden", lambda: None)
    for given in ("", "short\n"):
        monkeypatch.setattr("sys.stdin", io.StringIO(given))
        assert bkc.main(["--install", "--sealed-stdin"]) == 1
        assert capsys.readouterr().err.strip() == bkc.NO_PASSPHRASE["en"]
    assert not box.pub.exists() and box.pending() == [] and list(box.pub_dir.glob("*.sealed")) == []


def test_the_sealed_key_is_on_the_declared_target_before_backup_pub_and_restores_from_there_alone(
    box: Box, made: list[bytes], tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-02: the sealed copy goes to the declared off-box target (synced, read back) before backup.pub exists; with
    the box's disk lost (its own sealed file gone) the target's copy and the passphrase restore the nightly backup."""
    nas = _offbox(tmp_path, monkeypatch)
    at_pub: list[list[str]] = []
    real = bkc._pub_last

    def pub_last(pfd: int, pub: bytes) -> None:
        at_pub.append(sorted(p.name for p in nas.glob("*.sealed")))
        real(pfd, pub)

    monkeypatch.setattr(bkc, "_pub_last", pub_last)
    rec = bkc.install_sealed(bkc._env(), PASS)
    fp, on_box = rec["fingerprint"], Path(rec["sealed"])
    copy = nas / bkc.sealed_name(fp)
    assert at_pub == [[copy.name]] and box.pub.is_file()
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600 and copy.read_bytes() == on_box.read_bytes()
    _no_key_on_the_box(box, made[-1])
    on_box.unlink()  # the box's disk is lost
    key_file = _restore_key(box)
    assert bkc.unseal_to(copy, PASS) == fp and bkc.read_key(key_file.read_bytes()) == made[-1]
    _restores(box, box.pub, key_file, tmp_path, db_url, monkeypatch)


@pytest.mark.parametrize("target", ["none", "on the box", "write fails"])
def test_no_offbox_copy_makes_no_backup_pub(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """H-02: no declared target, a declaration naming a folder on the box's own disk (written by hand: the folder is
    no such mount), or an off-box copy that cannot be written: refused, and no backup.pub (no backup may encrypt to a
    key whose only copy is on the box)."""
    if target == "on the box":
        (tmp_path / "backups").mkdir()
        forged = {"format": bkc.TARGET_FORMAT, "path": str(tmp_path / "backups"), "fsuuid": None,
                  "mountpoint": str(tmp_path / "backups"), "fstype": NFS[1], "source": NFS[2]}  # fmt: skip
        (box.pub_dir / bkc.TARGET_RECORD).write_text(json.dumps(forged), encoding="utf-8")
    elif target == "write fails":
        nas = _offbox(tmp_path, monkeypatch)
        real = bkc._new_file

        def new_file(dfd: int, name: str | None, data: bytes, mode: int = 0o644) -> int:
            if os.path.samestat(os.fstat(dfd), os.stat(nas)):
                raise OSError(errno.EIO, "Input/output error")
            return real(dfd, name, data, mode)

        monkeypatch.setattr(bkc, "_new_file", new_file)
    with pytest.raises(bkc.Stop) as got:
        bkc.install_sealed(bkc._env(), PASS)
    want = {"none": bkc.NO_TARGET_DECLARED, "on the box": bkc.TARGET_MISMATCH, "write fails": bkc.STEP_FAILED}
    assert got.value.text is want[target]
    assert not box.pub.exists() and [e for e in box.journal() if e["event"] == bkc.EVENT] == []
    if target != "write fails":  # refused before a key is made
        assert box.pending() == [] and list(box.pub_dir.glob("*.sealed")) == []


@pytest.mark.parametrize("cut", ["key_text", "fsync"])
def test_an_interrupted_unseal_leaves_nothing_that_blocks_its_retry(
    box: Box, made: list[bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    """M-03: an unseal cut short (before or while the key file is written) leaves no file, partial or temporary, in
    the restore folder; the same command again makes the key file."""
    sealed = _sealed(tmp_path, monkeypatch)
    out = _restore_key(box)

    def cut_here(*_a: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as m:
        m.setattr(bkc if cut == "key_text" else os, cut, cut_here)
        with pytest.raises(KeyboardInterrupt):
            bkc.unseal_to(sealed, PASS)
    assert list(out.parent.iterdir()) == []
    bkc.unseal_to(sealed, PASS)
    assert list(out.parent.iterdir()) == [out] and stat.S_IMODE(out.stat().st_mode) == 0o600
    assert bkc.read_key(out.read_bytes()) == made[-1]


def test_an_unseal_input_larger_than_a_sealed_key_is_refused_by_its_size(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-05: a file larger than MAX_FILE (a sealed key padded to 1 MiB: its first MAX_FILE bytes would open) is
    refused by its size, before it is read (M-08: not a sealed key, too large); nothing is written."""
    sealed = _sealed(tmp_path, monkeypatch)
    big = tmp_path / "big.sealed"
    big.write_bytes(sealed.read_bytes() + b" " * (1 << 20))

    def is_big(fd: int) -> bool:
        return os.path.samestat(os.fstat(fd), os.stat(big))

    def never_big(real: Callable[..., Any]) -> Callable[..., Any]:
        def read(fd: int, *a: Any, **k: Any) -> Any:  # M-07: a whole read then a refusal is caught at the read
            assert not is_big(fd), "the oversized file was read"
            return real(fd, *a, **k)

        return read

    class Watched:  # M-07 (fourth review): a file object over it (os.fdopen, open, Path.read_bytes) read is caught too
        def __init__(self, f: Any) -> None:
            self._f = f

        def __getattr__(self, name: str) -> Any:
            got = getattr(self._f, name)
            if name.startswith("read"):  # read, read1, readall, readinto, readinto1, readline, readlines
                assert not is_big(self._f.fileno()), "the oversized file was read"
            return got

        def __iter__(self) -> Any:
            assert not is_big(self._f.fileno()), "the oversized file was read"
            return iter(self._f)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_e: object) -> None:
            self._f.close()

    def opened(real: Callable[..., Any]) -> Callable[..., Any]:
        return lambda *a, **k: Watched(real(*a, **k))

    with monkeypatch.context() as m, pytest.raises(bkc.Stop) as got:
        for name in ("read", "pread", "readv", "preadv", "readinto"):
            if hasattr(os, name):
                m.setattr(os, name, never_big(getattr(os, name)))
        m.setattr(io, "open", opened(io.open))  # os.fdopen and Path.open go through io.open
        m.setattr(builtins, "open", opened(builtins.open))
        m.setattr(bkc, "_read", never_big(bkc._read))
        bkc.unseal_to(big, PASS)
    assert got.value.text is bkc.SEALED_NOT_A_KEY and got.value.fill["what"] == "too large"
    assert not _restore_key(box).exists()


# ------------------------------------------------------------------------------------------------ H-02: one declared
# off-box target, checked by identity on every run (P01-DESIGN (i)); no device heuristic remains
def _nothing_made(box: Box, nas: Path) -> None:
    assert not box.pub.exists() and box.pending() == [] and list(box.pub_dir.glob("*.sealed")) == []
    assert list(nas.iterdir()) == [] and [e for e in box.journal() if e["event"] == bkc.EVENT] == []


def _events(box: Box, event: str) -> list[dict[str, Any]]:
    return [e["detail"] for e in box.journal() if e["event"] == event]


def test_the_declared_target_is_recorded_and_journaled(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = tmp_path / "nas"
    nas.mkdir()
    _mounted(tmp_path, monkeypatch, (nas, *NFS, ()))
    bkc.declare_target(str(nas), "install", False, {})
    rec_file = box.pub_dir / bkc.TARGET_RECORD
    rec = json.loads(rec_file.read_text(encoding="utf-8"))
    assert stat.S_IMODE(rec_file.stat().st_mode) == 0o600
    assert {k: rec[k] for k in ("path", "mountpoint", "fstype", "source", "fsuuid")} == {
        "path": str(nas),
        "mountpoint": str(nas),
        "fstype": "nfs4",
        "source": "nas.example:/backups",
        "fsuuid": None,
    }
    assert rec["operator"] == "install" and isinstance(rec["journal"], int) and rec["journal"] > 0
    assert _events(box, "backup.target_declared") == [
        {"path": str(nas), "declared": f"nfs4 nas.example:/backups @ {nas}", "replaced": "none", "operator": "install"}
    ]


def test_a_second_local_disk_mounted_exactly_at_the_target_is_refused_without_a_declaration(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The codex case of H-02: a second internal disk mounted exactly at the folder the settings name. With no
    declaration it is refused; no device heuristic remains that could pass or refuse it."""
    nas = tmp_path / "nas"
    nas.mkdir()
    _mounted(tmp_path, monkeypatch, (nas, "8:17", "ext4", "/dev/sdb1", ()))
    with pytest.raises(bkc.Stop) as got:
        bkc.install_sealed({"TB_BACKUP_OFFBOX": str(nas), "TB_BACKUP_TARGETS": str(nas)}, PASS)
    assert got.value.text is bkc.NO_TARGET_DECLARED
    _nothing_made(box, nas)
    # H-02 (sixth review): the refusal is journaled, and it is the only backup event
    assert [e["event"] for e in box.journal() if e["event"].startswith("backup.")] == ["backup.target_undeclared"]


def _refused_at_the_run(box: Box, nas: Path) -> bkc.Stop:
    with pytest.raises(bkc.Stop) as got:
        bkc.install_sealed(bkc._env(), PASS)
    _nothing_made(box, nas)
    return got.value


def test_a_declared_target_whose_source_changed_is_refused(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = _offbox(tmp_path, monkeypatch)
    _mounted(tmp_path, monkeypatch, (nas, NFS[0], NFS[1], "other.example:/backups", ()))
    e = _refused_at_the_run(box, nas)
    assert e.text is bkc.TARGET_MISMATCH
    assert (
        e.fill["declared"] == f"nfs4 nas.example:/backups @ {nas}"
        and e.fill["found"] == f"nfs4 other.example:/backups @ {nas}"
    )
    assert _events(box, "backup.target_mismatch") == [{"path": str(nas), "declared": e.fill["declared"],
                                                      "found": e.fill["found"]}]  # fmt: skip


def test_a_declared_target_unmounted_leaves_a_folder_that_is_refused(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The share unmounted: its mount point is left, a folder on the box's own filesystem (the same device)."""
    nas = _offbox(tmp_path, monkeypatch)
    _mounted(tmp_path, monkeypatch)  # no fake mount left
    assert nas.stat().st_dev == box.pub_dir.stat().st_dev
    e = _refused_at_the_run(box, nas)
    assert e.text is bkc.TARGET_MISMATCH and len(_events(box, "backup.target_mismatch")) == 1


def test_a_declared_target_mounted_elsewhere_is_refused(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = _offbox(tmp_path, monkeypatch)
    other = tmp_path / "other"
    other.mkdir()
    _mounted(tmp_path, monkeypatch, (other, *NFS, (nas,)))  # the same share, now mounted at another folder
    e = _refused_at_the_run(box, nas)
    assert e.text is bkc.TARGET_MISMATCH and f"@ {other}" in e.fill["found"]


def test_a_mismatch_the_journal_does_not_take_still_refuses(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = _offbox(tmp_path, monkeypatch)
    _mounted(tmp_path, monkeypatch)
    real = bkc.record

    def no_journal(detail: Any, event: str = bkc.EVENT) -> int:
        if event == "backup.target_mismatch":
            raise bkc.Stop(bkc.JOURNAL_UNSURE)
        return real(detail, event)

    monkeypatch.setattr(bkc, "record", no_journal)
    assert _refused_at_the_run(box, nas).text is bkc.TARGET_MISMATCH_UNJOURNALED


@pytest.mark.parametrize("fstype", ["tmpfs", "ramfs", "devtmpfs", "overlay", "proc", "sysfs", "squashfs"])
def test_tmpfs_and_overlay_cannot_be_declared(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fstype: str
) -> None:
    nas = tmp_path / "nas"
    nas.mkdir()
    _mounted(tmp_path, monkeypatch, (nas, "0:998", fstype, fstype, ()))
    with pytest.raises(bkc.Stop) as got:
        bkc.declare_target(str(nas), "install", False, {})
    assert got.value.text is bkc.TARGET_UNDECLARABLE and not (box.pub_dir / bkc.TARGET_RECORD).exists()


def test_a_mount_of_the_box_own_filesystem_cannot_be_declared(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = tmp_path / "nas"
    nas.mkdir()
    dev = box.pub_dir.stat().st_dev
    _mounted(tmp_path, monkeypatch, (nas, f"{os.major(dev)}:{os.minor(dev)}", "nfs4", "nas.example:/backups", ()))
    with pytest.raises(bkc.Stop) as got:
        bkc.declare_target(str(nas), "install", False, {})
    assert got.value.text is bkc.TARGET_UNDECLARABLE and not (box.pub_dir / bkc.TARGET_RECORD).exists()


def test_a_folder_inside_a_mount_cannot_be_declared(box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The removed test's first case: a share mounted at /srv, the folder named a folder inside it."""
    srv = tmp_path / "srv"
    nas = srv / "backups" / "nas"
    nas.mkdir(parents=True)
    _mounted(tmp_path, monkeypatch, (srv, *NFS, (nas,)))
    with pytest.raises(bkc.Stop) as got:
        bkc.declare_target(str(nas), "install", False, {})
    assert got.value.text is bkc.TARGET_UNDECLARABLE and got.value.fill["why"] == "not exactly a mount point"
    assert not (box.pub_dir / bkc.TARGET_RECORD).exists()


def test_a_dev_source_without_a_by_uuid_name_cannot_be_declared(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = tmp_path / "nas"
    nas.mkdir()
    (tmp_path / "by-uuid").mkdir()
    monkeypatch.setattr(bkc, "BY_UUID", tmp_path / "by-uuid")
    _mounted(tmp_path, monkeypatch, (nas, "8:17", "ext4", "/dev/sdb1", ()))
    with pytest.raises(bkc.Stop) as got:
        bkc.declare_target(str(nas), "install", False, {})
    assert got.value.text is bkc.TARGET_UNDECLARABLE and not (box.pub_dir / bkc.TARGET_RECORD).exists()


def test_a_dev_source_replugged_is_refused_until_it_is_declared_again(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nas = tmp_path / "nas"
    nas.mkdir()
    by_uuid = tmp_path / "by-uuid"
    by_uuid.mkdir()
    link = by_uuid / "0f1e2d3c-usb"
    monkeypatch.setattr(bkc, "BY_UUID", by_uuid)
    link.symlink_to("/dev/sdb1")
    _mounted(tmp_path, monkeypatch, (nas, "8:17", "ext4", "/dev/sdb1", ()))
    bkc.declare_target(str(nas), "install", False, {})
    assert json.loads((box.pub_dir / bkc.TARGET_RECORD).read_text(encoding="utf-8"))["fsuuid"] == link.name
    link.unlink()
    link.symlink_to("/dev/sdc1")  # re-plugged: another letter, the same filesystem
    _mounted(tmp_path, monkeypatch, (nas, "8:33", "ext4", "/dev/sdc1", ()))
    with pytest.raises(bkc.Stop) as got:  # H-02 (sixth review): not the mount recorded; only the operator declares it
        bkc.install_sealed(bkc._env(), PASS)
    assert got.value.text is bkc.TARGET_MISMATCH and not box.pub.exists()
    bkc.declare_target(str(nas), "IT Operator", True, {})
    rec = bkc.install_sealed(bkc._env(), PASS)
    assert (nas / bkc.sealed_name(rec["fingerprint"])).is_file()
    box.pub.unlink()
    link.unlink()
    link.symlink_to("/dev/sdd1")  # the by-uuid name now names another node: not the declared filesystem
    with pytest.raises(bkc.Stop) as got:
        bkc.install_sealed(bkc._env(), PASS)
    assert got.value.text is bkc.TARGET_MISMATCH and not box.pub.exists()


def test_the_installer_declares_only_when_no_record_exists(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _offbox(tmp_path, monkeypatch)
    b = tmp_path / "b"
    b.mkdir()
    before = (box.pub_dir / bkc.TARGET_RECORD).read_bytes()
    rec = bkc.install_sealed({"TB_BACKUP_OFFBOX": str(b), "TB_BACKUP_TARGETS": str(b)}, PASS)
    assert (box.pub_dir / bkc.TARGET_RECORD).read_bytes() == before and json.loads(before)["path"] == str(a)
    assert rec["copy"] == str(a / bkc.sealed_name(rec["fingerprint"])) and Path(rec["copy"]).is_file()
    assert list(b.iterdir()) == []


def test_replace_keeps_the_old_record(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
    _mounted(tmp_path, monkeypatch, (a, *NFS, ()), (b, "0:997", "cifs", "//filer.example/backups", ()))
    monkeypatch.setattr(bkc, "harden", lambda: None)
    bkc.declare_target(str(a), "install", False, {})
    first = (box.pub_dir / bkc.TARGET_RECORD).read_bytes()
    with pytest.raises(bkc.Stop) as got:  # without --replace: refused, unchanged
        bkc.declare_target(str(b), "IT Operator", False, {})
    assert got.value.text is bkc.TARGET_ALREADY_DECLARED and (box.pub_dir / bkc.TARGET_RECORD).read_bytes() == first
    assert bkc.main(["--declare-backup-target", str(b), "--operator", "IT Operator", "--replace"]) == 0
    assert str(b) in capsys.readouterr().out
    olds = list(box.pub_dir.glob("backup-target.*.old"))
    assert len(olds) == 1 and olds[0].read_bytes() == first
    assert json.loads((box.pub_dir / bkc.TARGET_RECORD).read_text(encoding="utf-8"))["path"] == str(b)
    declared = _events(box, "backup.target_declared")
    assert len(declared) == 2 and declared[1]["operator"] == "IT Operator"
    assert declared[1]["replaced"] == f"nfs4 nas.example:/backups @ {a}"
    assert declared[1]["declared"] == f"cifs //filer.example/backups @ {b}"


def test_mount_id_unreadable_is_refused(box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The removed test's last case: a mount off the box at the target, its descriptor's mount id unreadable."""
    nas = _offbox(tmp_path, monkeypatch)

    def no_id(_fd: int) -> int:
        raise OSError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(bkc, "_mount_id", no_id)
    assert _refused_at_the_run(box, nas).text is bkc.TARGET_MISMATCH


def test_an_offbox_target_exactly_a_mount_off_the_box_takes_the_sealed_copy(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-02: a share mounted exactly at the declared target (a fake mountinfo line: its own device, no filesystem of
    the box): the sealed copy is written there and backup.pub is made."""
    nas = _offbox(tmp_path, monkeypatch)
    rec = bkc.install_sealed(bkc._env(), PASS)
    assert (nas / bkc.sealed_name(rec["fingerprint"])).is_file() and box.pub.is_file()


# ------------------------------------------------------------------------------------------------ H-07, M-03: no
# plaintext off the box, nothing swept (P01-DESIGN (ii))
def test_the_module_has_no_fallback_writer() -> None:
    assert not hasattr(bkc, "_sweep") and not hasattr(bkc, "_rename_noreplace") and not hasattr(bkc, "UNSEAL_MARK")
    source = Path(bkc.__file__).read_text(encoding="utf-8")
    assert source.count("os.unlink(") == 1 and "os.unlink(" in inspect.getsource(bkc.forget_restore_key)


def test_unseal_has_no_out_and_writes_only_into_the_restore_folder(
    box: Box, made: list[bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = _sealed(tmp_path, monkeypatch)
    usb = tmp_path / "usb"  # a FAT stick: nothing of the key goes there
    usb.mkdir()
    monkeypatch.setattr(bkc, "harden", lambda: None)
    with pytest.raises(SystemExit) as gone:
        bkc.main(["--unseal", str(sealed), "--out", str(usb / "trialbox-backup.key")])
    assert gone.value.code == 2
    assert bkc.unseal_to(sealed, PASS) == bkc.fingerprint(bkc.public_of(made[-1]))
    out = _restore_key(box)
    assert list(out.parent.iterdir()) == [out] and stat.S_IMODE(out.stat().st_mode) == 0o600
    assert stat.S_IMODE(out.parent.stat().st_mode) == 0o700 and bkc.read_key(out.read_bytes()) == made[-1]
    assert list(usb.iterdir()) == []


KILLED = r"""
import os, signal, sys
from pathlib import Path
from tools import backup_key_ceremony as b
b.DEPLOY = Path(sys.argv[2]); b.PUB_DIR = b.DEPLOY / "secrets"
def kill(*_a, **_k):  # where the key file would get its name: killed, its written key bytes left as they are
    os.kill(os.getpid(), signal.SIGKILL)
os.link = kill
b.unseal_to(Path(sys.argv[1]), sys.stdin.readline().rstrip("\n"))
"""


def test_an_unseal_killed_before_the_link_leaves_no_named_file(
    box: Box, made: list[bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-03 (replaces the killed-after-the-write test): an unseal killed (SIGKILL, no handler runs) where the key file
    would get its name leaves no plaintext key anywhere (the file has no name until it is linked), and the restore
    folder empty; the retry makes it."""
    sealed = _sealed(tmp_path, monkeypatch)
    r = subprocess.run([sys.executable, "-c", KILLED, str(sealed), str(box.deploy)], cwd=ROOT, env=box.env(),
                       input=PASS + "\n", capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert r.returncode == -9, r.stderr
    restore = _restore_key(box).parent
    assert restore.is_dir() and list(restore.iterdir()) == []
    text = bkc.key_text(made[-1])
    assert [p for p in tmp_path.rglob("*") if p.is_file() and not p.is_symlink() and text in p.read_bytes()] == []
    bkc.unseal_to(sealed, PASS)
    assert list(restore.iterdir()) == [_restore_key(box)] and bkc.read_key(_restore_key(box).read_bytes()) == made[-1]


def test_an_existing_restore_key_is_never_replaced_and_never_deleted(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-05 and H-07: a key file already there (another unseal's, or a user's) is kept byte for byte; no other entry
    appears beside it."""
    sealed = _sealed(tmp_path, monkeypatch)
    out = _restore_key(box)
    out.parent.mkdir(mode=0o700)
    out.write_bytes(b"theirs\n")
    out.chmod(0o600)
    with pytest.raises(bkc.Stop) as got:
        bkc.unseal_to(sealed, PASS)
    assert got.value.text is bkc.RESTORE_KEY_PRESENT
    assert out.read_bytes() == b"theirs\n" and list(out.parent.iterdir()) == [out]


def test_two_unseals_at_once_never_replace_each_other(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-05: two unseals of two sealed keys at the same moment (both past any look at the name): exactly one makes
    the key file, the other is refused, and the file holds the key of the one that said so."""
    first = _sealed(tmp_path, monkeypatch)
    box.pub.unlink()  # a second sealed key (an older one)
    second = _sealed(tmp_path, monkeypatch)
    out = _restore_key(box)
    both = threading.Barrier(2, timeout=60)
    real = bkc.key_text

    def key_text(raw: bytes) -> bytes:
        both.wait()
        return real(raw)

    def one(sealed: Path) -> str | None:
        try:
            return bkc.unseal_to(sealed, PASS)
        except bkc.Stop as e:
            assert e.text is bkc.RESTORE_KEY_PRESENT
            return None

    monkeypatch.setattr(bkc, "key_text", key_text)
    with ThreadPoolExecutor(2) as ex:
        got = list(ex.map(one, [first, second]))
    won = [fp for fp in got if fp]
    assert len(won) == 1, got
    key = bkc.read_key(out.read_bytes())
    assert key is not None and bkc.fingerprint(bkc.public_of(key)) == won[0] and list(out.parent.iterdir()) == [out]


def test_forget_restore_key_removes_only_that_file(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sealed = _sealed(tmp_path, monkeypatch)
    bkc.unseal_to(sealed, PASS)
    out = _restore_key(box)
    other = out.parent / "other.key"
    other.write_bytes(b"another file\n")
    monkeypatch.setattr(bkc, "harden", lambda: None)
    assert bkc.main(["--forget-restore-key"]) == 0 and str(out) in capsys.readouterr().out
    assert not out.exists() and other.read_bytes() == b"another file\n"
    assert _events(box, "backup.restore_key_forgotten") == [{"path": str(out)}]
    out.symlink_to(other)  # a link at the name: refused, left, and what it names untouched
    with pytest.raises(bkc.Stop) as got:
        bkc.forget_restore_key()
    assert got.value.text is bkc.RESTORE_KEY_NOT_A_FILE and out.is_symlink() and other.read_bytes() == b"another file\n"
    assert len(_events(box, "backup.restore_key_forgotten")) == 1


def test_a_restore_folder_without_unnamed_files_refuses(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No fallback writer: a filesystem without unnamed files is refused, never a named temporary file."""
    sealed = _sealed(tmp_path, monkeypatch)
    _no_unnamed_files(monkeypatch)
    with pytest.raises(bkc.Stop) as got:
        bkc.unseal_to(sealed, PASS)
    assert got.value.text is bkc.NO_TMPFILE and list(_restore_key(box).parent.iterdir()) == []


# ------------------------------------------------------------------------------------------------ M-08: three outcomes
def _clean(e: bkc.Stop, sealed: bytes) -> None:
    """No text carries a byte of the passphrase or of the sealed file (its wrapped key's base64)."""
    blob = json.loads(sealed)["key"]["blob"]
    for lg in bkc.LANGS:
        said = e.say(lg) + str(e)
        assert PASS not in said and all(blob[i : i + 12] not in said for i in range(0, len(blob) - 12, 6)), lg


@pytest.mark.parametrize(("call", "err"), [("pread", errno.EIO), ("open", errno.EACCES), ("fstat", errno.EIO)])
def test_an_io_error_on_the_sealed_medium_is_named_as_such(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, call: str, err: int
) -> None:
    sealed = _sealed(tmp_path, monkeypatch)
    real = getattr(os, call)

    def on_sealed(what: Any) -> bool:
        where = f"/proc/self/fd/{what}" if isinstance(what, int) else what
        return isinstance(where, (str, Path)) and os.path.realpath(where) == os.path.realpath(sealed)

    def failing(what: Any, *a: Any, **k: Any) -> Any:
        if on_sealed(what):
            raise OSError(err, os.strerror(err))
        return real(what, *a, **k)

    with monkeypatch.context() as m, pytest.raises(bkc.Stop) as got:
        m.setattr(os, call, failing)
        bkc.unseal_to(sealed, PASS)
    assert got.value.text is bkc.SEALED_UNREADABLE and got.value.fill["why"] == errno.errorcode[err]
    assert not _restore_key(box).exists()
    _clean(got.value, sealed.read_bytes())


def test_a_wrong_passphrase_is_named_as_such(box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sealed = _sealed(tmp_path, monkeypatch)
    with pytest.raises(bkc.Stop) as got:
        bkc.unseal_to(sealed, "not the passphrase of it")
    assert got.value.text is bkc.SEALED_WRONG_PASSPHRASE and not _restore_key(box).exists()
    _clean(got.value, sealed.read_bytes())


@pytest.mark.parametrize("case", ["empty object", "format", "fingerprint", "fields", "not json", "folder", "fifo"])
def test_a_malformed_sealed_file_is_named_as_such(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    sealed = _sealed(tmp_path, monkeypatch)
    doc = json.loads(sealed.read_bytes())
    bad = tmp_path / "bad.sealed"
    if case == "folder":
        bad.mkdir()
    elif case == "fifo":
        os.mkfifo(bad)
    else:
        if case == "format":
            doc["format"] = "x/9"
        elif case == "fingerprint":
            doc["fingerprint"] = "0000-0000-0000-0000-0000"
        elif case == "fields":
            del doc["kdf"]
        data = {"empty object": b"{}", "not json": b"\xff not json"}.get(case) or json.dumps(doc).encode()
        bad.write_bytes(data)
    with pytest.raises(bkc.Stop) as got:
        bkc.unseal_to(bad, PASS)
    what = {"empty object": "format", "folder": "not a file", "fifo": "not a file"}.get(case, case)
    assert got.value.text is bkc.SEALED_NOT_A_KEY and got.value.fill["what"] == what
    assert not _restore_key(box).exists()
    _clean(got.value, sealed.read_bytes())


def test_no_text_carries_a_byte_of_the_file_or_the_passphrase() -> None:
    """Every text of the three outcomes takes only the sealed file's path and a fixed word (an errno name, a
    ``what``), never a field that could hold the file's bytes or the passphrase."""
    import string

    for t in (bkc.SEALED_UNREADABLE, bkc.SEALED_NOT_A_KEY, bkc.SEALED_WRONG_PASSPHRASE):
        for lg in bkc.LANGS:
            fields = {f for _, f, _, _ in string.Formatter().parse(t[lg]) if f}
            assert fields <= {"sealed", "why", "what"}, (lg, fields)


def test_a_target_without_file_modes_takes_the_sealed_copy(
    box: Box, made: list[bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-01: a FAT or exFAT target has no file modes (a change of mode fails, EPERM): the sealed copy is made there
    all the same (made 0600 where modes exist; it is encrypted). No key file goes to such media any more."""
    nas = tmp_path / "nas"
    real = os.fchmod

    def fchmod(fd: int, mode: int) -> None:
        if os.readlink(f"/proc/self/fd/{fd}").startswith(str(nas)):
            raise PermissionError(errno.EPERM, "Operation not permitted")
        real(fd, mode)

    monkeypatch.setattr(os, "fchmod", fchmod)
    sealed = _sealed(tmp_path, monkeypatch)  # the sealed copy onto the target without modes
    fp = bkc.fingerprint(bkc.public_of(made[-1]))
    assert (nas / bkc.sealed_name(fp)).read_bytes() == sealed.read_bytes()


def test_the_ceremony_module_parses_before_python_3_12() -> None:
    """N-02: install.sh runs the host's python3 (Ubuntu 24.04: 3.12); the module still parses on 3.11 (no PEP 695
    syntax), so an older host gets the ceremony's own refusals, never a SyntaxError."""
    import ast

    ast.parse(Path(bkc.__file__).read_text(encoding="utf-8"), feature_version=(3, 11))


INSTALL = (Path(__file__).resolve().parents[2] / "deploy" / "install.sh").read_text(encoding="utf-8")
STEP = INSTALL.index("# E2E P-01 (the integrator's ruling Q1, 2026-11-27)")
END = INSTALL.index('esac\nKP_VALUE=""', STEP) + len('esac\nKP_VALUE=""')


def test_the_install_makes_the_key_on_a_production_box() -> None:
    step: Any = re.search(r"in DEV\|TEST\|VALIDATION\)\n(.*?)\n\*\)\n(.*?)\nesac", INSTALL[STEP:END], re.S)
    assert step, "install.sh: the backup key step for a PRODUCTION box"
    other, production = step.group(1), step.group(2)
    assert "python3 -m tools.backup_key_ceremony --install" in production
    assert "! -f deploy/secrets/backup.pub" in production and "FAILS+=" in production
    # residual 1: a PRODUCTION box is never told to run the refused command; another box still is
    assert "backup-keygen" not in production and "backup-keygen" in other
    # residual 2: with no terminal, the install's passphrase on stdin (never an argument or the environment)
    assert "printf '%s\\n' \"$KP_VALUE\" | " in production and "--install --sealed-stdin" in production
    assert INSTALL.index('{ : </dev/tty; } 2>/dev/null && KP_VALUE=""') < STEP


def test_the_install_without_a_terminal_hands_the_passphrase_to_the_sealed_path(tmp_path: Path) -> None:
    """The step as it stands, run by bash with no terminal: the ceremony gets ``--install --sealed-stdin`` and the
    passphrase on stdin; without a passphrase it is a FAIL line that names no refused command."""
    import subprocess

    block = INSTALL[STEP:END]
    rec = tmp_path / "rec"
    fake = tmp_path / "bin" / "python3"
    fake.parent.mkdir()
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > {rec}; cat >> {rec}\n', encoding="utf-8")
    fake.chmod(0o755)
    (tmp_path / "deploy" / "secrets").mkdir(parents=True)
    (tmp_path / "deploy" / "secrets" / "backup-target.json").write_text("{}", encoding="utf-8")  # declared already
    for value, sealed in (("synthetic-pass-p01-xyz", True), ("", False)):
        rec.unlink(missing_ok=True)
        script = (f"say() {{ :; }}\nFAILS=()\nTB_ENV_SITE=\nKP_VALUE={value}\n{block}\n"
                  'printf "%s\\n" "${FAILS[@]}"; printf "after=%s\\n" "$KP_VALUE"\n')  # fmt: skip
        r = subprocess.run(["setsid", "bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
                           check=False, stdin=subprocess.DEVNULL,
                           env={"PATH": f"{fake.parent}:{os.environ['PATH']}"})  # fmt: skip
        assert r.returncode == 0, r.stderr
        assert r.stdout.splitlines()[-1] == "after="
        if sealed:
            args, given = rec.read_text(encoding="utf-8").splitlines()
            assert args == "-m tools.backup_key_ceremony --install --sealed-stdin" and given == value
            assert "no backup key" not in r.stdout
        else:
            assert not rec.exists() and "no backup key" in r.stdout and "backup-keygen" not in r.stdout


@pytest.mark.parametrize(("tb_env", "says"), [(None, "backup_key_ceremony --install"), ("TEST", "backup-keygen")])
def test_the_console_backup_without_a_key_says_what_this_box_runs(
    tmp_path: Path, tb_env: str | None, says: str
) -> None:
    """Residual 1 of r1p1a: the operations runner's refusal names the command this box may run (PRODUCTION refuses
    backup-keygen, rc1)."""
    from tools.trialbox import ops as tb_ops

    (tmp_path / "deploy" / "secrets").mkdir(parents=True)
    env = {"TB_BACKUP_TARGETS": str(tmp_path), **({"TB_ENV": tb_env} if tb_env else {})}
    with pytest.raises(tb_ops.OpsFailed) as got:
        tb_ops.OpsRunner(tb_ops.Box("compose", tmp_path / "deploy", env), tb_ops.OpsDir(tmp_path / "ops")).do_backup({})
    assert says in str(got.value) and ("backup-keygen" in str(got.value)) == (tb_env == "TEST")


def _between(start: str, end: str) -> str:
    a = INSTALL.index(start)
    return INSTALL[a : INSTALL.index(end, a)]


@pytest.mark.parametrize("seal_step", [True, False])
def test_the_unattended_install_takes_the_passphrase_file_to_the_backup_key_and_removes_it(
    tmp_path: Path, seal_step: bool
) -> None:
    """M-02: the real install input path, run by bash with no terminal: the installer's reader takes
    ``--kek-passphrase-file`` (0600, its owner the user that runs it), the KEK seal step (when it runs on this box) and
    the backup key's sealed path get the passphrase on stdin, and the file is gone at the end; no FAIL. A file others
    can read is refused before anything."""
    reader = _between("KP_WHO=install\n", "# ---- end of KEK-INPUT\n")
    seal = _between('HB_CONF="$ROOT/deploy/site/hardening.conf"\n', "# D-378:")
    key_step = _between("# E2E P-01 (the integrator's ruling Q1, 2026-11-27)", "# T-117b (D-274)")
    rec, bin_ = tmp_path / "rec", tmp_path / "bin"
    for d in (rec, bin_, tmp_path / "deploy" / "hardening", tmp_path / "deploy" / "secrets"):
        d.mkdir(parents=True)
    (tmp_path / "deploy" / "secrets" / "backup-target.json").write_text("{}", encoding="utf-8")  # declared already
    for name, body in (("python3", f'printf "%s\\n" "$*" >> {rec}/ceremony; cat >> {rec}/ceremony\n'),
                       ("systemd-creds", "exit 1\n")):  # fmt: skip
        (bin_ / name).write_text("#!/bin/sh\n" + body, encoding="utf-8")
        (bin_ / name).chmod(0o755)
    (tmp_path / "deploy" / "hardening" / "seal_keys.sh").write_text(f"cat > {rec}/seal\n", encoding="utf-8")
    keys = tmp_path / "root"
    keys.mkdir(mode=0o700)

    def run(pp: Path) -> subprocess.CompletedProcess[str]:
        script = ('die() { echo "die: $*"; exit 1; }\nsay() { :; }\nstop_or_warn() { FAILS+=("$3"); }\nFAILS=()\n'
                  f"PP_FILE={pp}\nPP_STDIN=0\nPP_FD=\nPP_REMOVE=\nPP_KEEP=0\nROOT={tmp_path}\n{reader}"
                  'id() { if [ "$1" = -u ]; then echo 0; else command id "$@"; fi; }\n'  # the seal step runs as root
                  f"KEYS_OK=1\nHOST_PROFILE={'server' if seal_step else 'poc'}\nTB_ENV_SITE=PRODUCTION\n"
                  f"IMAGE_PY=img\nTB_SECRETS_HOST_DIR={tmp_path}/sec\n{seal}{key_step}"
                  'for f in "${FAILS[@]}"; do echo "FAIL: $f"; done\n')  # fmt: skip
        return subprocess.run(["setsid", "bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
                              check=False, stdin=subprocess.DEVNULL, timeout=60,
                              env={"PATH": f"{bin_}:{os.environ['PATH']}"})  # fmt: skip

    loose = keys / "loose.pass"
    loose.write_text(PASS + "\n", encoding="utf-8")
    loose.chmod(0o644)
    r = run(loose)
    assert r.returncode == 1 and "has mode 644, not 0600: refused" in r.stderr and list(rec.iterdir()) == []
    pp = keys / "trialbox-kek.pass"
    pp.write_text(PASS + "\n", encoding="utf-8")
    pp.chmod(0o600)
    r = run(pp)
    assert r.returncode == 0, r.stderr
    assert (rec / "ceremony").read_text(encoding="utf-8").splitlines() == [
        "-m tools.backup_key_ceremony --install --sealed-stdin",
        PASS,
    ]
    assert ((rec / "seal").read_text(encoding="utf-8") == PASS + "\n") if seal_step else not (rec / "seal").exists()
    assert not pp.exists() and f"the passphrase file {pp} is removed" in r.stdout
    assert "FAIL:" not in r.stdout and "was not used" not in r.stdout + r.stderr and PASS not in r.stdout + r.stderr


@pytest.mark.parametrize("passphrase", ["synthetic-pass-p01-xyz", ""])
def test_a_production_install_ignores_test_box(tmp_path: Path, passphrase: str) -> None:
    """M-06/N-03: TEST_BOX left in the environment of a PRODUCTION install (TB_ENV_SITE=PRODUCTION, no backup.pub)
    is ignored, and said: the backup key step still runs (the sealed path with a passphrase, else its FAIL line)."""
    rec = tmp_path / "rec"
    fake = tmp_path / "bin" / "python3"
    fake.parent.mkdir()
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > {rec}; cat >> {rec}\n', encoding="utf-8")
    fake.chmod(0o755)
    (tmp_path / "deploy" / "secrets").mkdir(parents=True)
    (tmp_path / "deploy" / "secrets" / "backup-target.json").write_text("{}", encoding="utf-8")  # declared already
    script = (f"say() {{ :; }}\nFAILS=()\nTB_ENV_SITE=PRODUCTION\nKP_VALUE={passphrase}\n{INSTALL[STEP:END]}\n"
              'for f in "${FAILS[@]}"; do echo "FAIL: $f"; done\n')  # fmt: skip
    r = subprocess.run(["setsid", "bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False,
                       stdin=subprocess.DEVNULL, env={"PATH": f"{fake.parent}:{os.environ['PATH']}", "TEST_BOX": "0"})  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert "TEST_BOX is ignored on a PRODUCTION install" in r.stderr
    if passphrase:
        assert rec.read_text(encoding="utf-8").splitlines() == [
            "-m tools.backup_key_ceremony --install --sealed-stdin",
            passphrase,
        ]
        assert "FAIL:" not in r.stdout
    else:
        assert not rec.exists() and "FAIL: no backup key" in r.stdout


@pytest.mark.parametrize("case", ["declares", "not set", "declaration refused", "declared already"])
def test_the_unattended_install_declares_the_offbox_target_only_when_there_is_none(tmp_path: Path, case: str) -> None:
    """P01-DESIGN (i), step 11: with no terminal and no declaration, the install declares TB_BACKUP_OFFBOX (from
    deploy/.env) as ``--operator install`` before the sealed path; a declaration there is never replaced (no declare
    call); TB_BACKUP_OFFBOX not set, or the declaration refused, is a FAIL line naming the setting, and the sealed
    path does not run."""
    rec, bin_ = tmp_path / "rec", tmp_path / "bin"
    bin_.mkdir()
    refuse = 'case "$*" in *--declare-backup-target*) exit 1;; esac\n' if case == "declaration refused" else ""
    (bin_ / "python3").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {rec}; cat >> {rec}\n{refuse}', encoding="utf-8")
    (bin_ / "python3").chmod(0o755)
    (tmp_path / "deploy" / "secrets").mkdir(parents=True)
    if case == "declared already":
        (tmp_path / "deploy" / "secrets" / "backup-target.json").write_text("{}", encoding="utf-8")
    offbox = "" if case == "not set" else "/mnt/nas"
    (tmp_path / "deploy" / ".env").write_text(f"TB_ENV=PRODUCTION\nTB_BACKUP_OFFBOX={offbox}\n", encoding="utf-8")
    envget = INSTALL[INSTALL.index("envget() {") : INSTALL.index("\n", INSTALL.index("envget() {"))]
    script = (f"say() {{ :; }}\nFAILS=()\n{envget}\nTB_ENV_SITE=PRODUCTION\nKP_VALUE={PASS!r}\nKP_FILE=\n"
              f"{INSTALL[STEP:END]}\n" 'for f in "${FAILS[@]}"; do echo "FAIL: $f"; done\n')  # fmt: skip
    r = subprocess.run(["setsid", "bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False,
                       stdin=subprocess.DEVNULL, env={"PATH": f"{bin_}:{os.environ['PATH']}"})  # fmt: skip
    assert r.returncode == 0, r.stderr
    calls = rec.read_text(encoding="utf-8").splitlines() if rec.exists() else []
    sealed = ["-m tools.backup_key_ceremony --install --sealed-stdin", PASS]
    declare = ["-m tools.backup_key_ceremony --declare-backup-target /mnt/nas --operator install"]
    if case == "declares":
        assert calls == declare + sealed and "FAIL:" not in r.stdout
    elif case == "declared already":
        assert calls == sealed and "FAIL:" not in r.stdout
    else:
        assert calls == ([] if case == "not set" else declare)
        assert f"TB_BACKUP_OFFBOX in deploy/.env: {offbox or 'not set'}" in r.stdout and PASS not in r.stdout


# ------------------------------------------------------------------------------------------------ sixth review (#1602)
@pytest.mark.parametrize("changed", ["mount id", "mount root", "folder"])
def test_a_declared_target_remounted_with_the_same_source_and_mount_point_is_refused(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    """H-02: the record holds the mount's id, its root and the folder's device and inode as the declaration saw
    them. A remount (another id), a bind of another folder of the same share (another root) or another folder at
    the path, with the source and the mount point the same, is refused and journaled."""
    nas = _offbox(tmp_path, monkeypatch)
    rec = json.loads((box.pub_dir / bkc.TARGET_RECORD).read_text(encoding="utf-8"))
    st = nas.stat()
    assert rec["mnt_id"] == 2_000_000_000 and rec["mnt_root"] == "/" and rec["fstat"] == [st.st_dev, st.st_ino]
    if changed == "folder":
        new = tmp_path / "nas.new"
        new.mkdir()  # made while the old folder exists: another inode
        nas.rmdir()
        new.rename(nas)
    _mounted(tmp_path, monkeypatch, (nas, *NFS, ()), first_id=2_000_000_000 + 100 * (changed == "mount id"),
             root="/other" if changed == "mount root" else "/")  # fmt: skip
    e = _refused_at_the_run(box, nas)
    assert e.text is bkc.TARGET_MISMATCH and e.fill["declared"] == f"nfs4 nas.example:/backups @ {nas}"
    said = {"mount id": "mnt_id 2000000100 not 2000000000", "mount root": "mnt_root /other not /", "folder": "fstat"}
    assert e.fill["found"].startswith(f"nfs4 nas.example:/backups @ {nas}, ") and said[changed] in e.fill["found"]
    assert _events(box, "backup.target_mismatch") == [{"path": str(nas), "declared": e.fill["declared"],
                                                      "found": e.fill["found"]}]  # fmt: skip


@pytest.mark.parametrize("case", ["missing", "not a declaration", "journal down"])
def test_no_declaration_is_refused_and_journaled(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """H-02: a missing record, or one that is not a declaration, refuses before a key is made, with its event
    (backup.target_undeclared); a journal that does not take it is said, and the run still stops."""
    nas = tmp_path / "nas"
    nas.mkdir()
    _mounted(tmp_path, monkeypatch, (nas, *NFS, ()))
    if case == "not a declaration":
        (box.pub_dir / bkc.TARGET_RECORD).write_text("{}", encoding="utf-8")
    if case == "journal down":
        real = bkc.record

        def no_journal(detail: Any, event: str = bkc.EVENT) -> int:
            if event == "backup.target_undeclared":
                raise bkc.Stop(bkc.JOURNAL_UNSURE)
            return real(detail, event)

        monkeypatch.setattr(bkc, "record", no_journal)
    e = _refused_at_the_run(box, nas)
    record = str(box.pub_dir / bkc.TARGET_RECORD)
    if case == "journal down":
        assert e.text is bkc.NO_TARGET_DECLARED_UNJOURNALED and _events(box, "backup.target_undeclared") == []
    else:
        assert e.text is bkc.NO_TARGET_DECLARED
        assert _events(box, "backup.target_undeclared") == [{"record": record, "found": case}]


def test_a_declared_target_whose_folder_is_gone_is_refused_and_journaled(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-10: an automounter took the declared folder away with the share (ENOENT): a mismatch, journaled, with the
    errno; nothing made."""
    nas = _offbox(tmp_path, monkeypatch)
    nas.rmdir()
    with pytest.raises(bkc.Stop) as got:
        bkc.install_sealed(bkc._env(), PASS)
    e = got.value
    assert e.text is bkc.TARGET_MISMATCH and e.fill["found"] == "cannot be opened (ENOENT)"
    assert _events(box, "backup.target_mismatch") == [
        {"path": str(nas), "declared": f"nfs4 nas.example:/backups @ {nas}", "found": "cannot be opened (ENOENT)"}
    ]
    assert not box.pub.exists() and box.pending() == [] and list(box.pub_dir.glob("*.sealed")) == []


def test_a_deeply_nested_sealed_file_is_named_as_not_a_key(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-08: nesting deeper than the decoder recurses, well below MAX_FILE, is a malformed key, not an error."""
    _sealed(tmp_path, monkeypatch)
    bad = tmp_path / "nested.sealed"
    bad.write_bytes(b"[" * (bkc.MAX_FILE - 1))
    with pytest.raises(bkc.Stop) as got:
        bkc.unseal_to(bad, PASS)
    assert got.value.text is bkc.SEALED_NOT_A_KEY and got.value.fill["what"] == "not json"
    assert not _restore_key(box).exists()


def _two_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
    _mounted(tmp_path, monkeypatch, (a, *NFS, ()), (b, "0:997", "cifs", "//filer.example/backups", ()))
    return a, b


@pytest.mark.parametrize("cut", ["write", "rename"])
def test_a_replace_cut_short_leaves_the_old_declaration_in_force(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    """M-09: the new record is written whole and synced under its own name, the old one is kept under another,
    then one rename puts the new one in place. A replace killed before that rename leaves the old declaration whole
    (the installer still sees one and declares nothing); the replace run again completes."""
    a, b = _two_targets(tmp_path, monkeypatch)
    bkc.declare_target(str(a), "install", False, {})
    rec_file = box.pub_dir / bkc.TARGET_RECORD
    first = rec_file.read_bytes()
    real_new, real_rename = bkc._new_file, os.rename

    def new_file(dfd: int, name: str | None, data: bytes, mode: int = 0o644) -> int:
        if name is not None and name.startswith("backup-target."):
            raise KeyboardInterrupt  # killed while the new record is written
        return real_new(dfd, name, data, mode)

    def rename(src: Any, dst: Any, *x: Any, **k: Any) -> None:
        if dst == bkc.TARGET_RECORD:
            raise KeyboardInterrupt  # killed at the rename that puts the new record in place
        real_rename(src, dst, *x, **k)

    with monkeypatch.context() as m, pytest.raises(KeyboardInterrupt):
        if cut == "write":
            m.setattr(bkc, "_new_file", new_file)
        else:
            m.setattr(os, "rename", rename)
        bkc.declare_target(str(b), "IT Operator", True, {})
    assert rec_file.read_bytes() == first
    with pytest.raises(bkc.Stop) as got:  # the installer's own call: the old declaration stands
        bkc.declare_target(str(b), "install", False, {})
    assert got.value.text is bkc.TARGET_ALREADY_DECLARED
    bkc.declare_target(str(b), "IT Operator", True, {})
    assert json.loads(rec_file.read_text(encoding="utf-8"))["path"] == str(b)
    assert {p.read_bytes() for p in box.pub_dir.glob("backup-target.*.old")} == {first}


def test_two_replaces_in_one_second_keep_both_old_records(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-09: the old record's name does not hang on the second it was declared in: replaces within one second keep
    every old record."""
    from datetime import datetime as real

    a, b = _two_targets(tmp_path, monkeypatch)

    class OneSecond(real):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return real(2026, 11, 28, 1, 2, 3, tzinfo=tz)

    monkeypatch.setattr(bkc, "datetime", OneSecond)
    rec_file = box.pub_dir / bkc.TARGET_RECORD
    bkc.declare_target(str(a), "install", False, {})
    first = rec_file.read_bytes()
    bkc.declare_target(str(b), "IT Operator", True, {})
    second = rec_file.read_bytes()
    bkc.declare_target(str(a), "IT Operator", True, {})
    assert sorted(p.read_bytes() for p in box.pub_dir.glob("backup-target.*.old")) == sorted([first, second])
    assert json.loads(rec_file.read_text(encoding="utf-8"))["path"] == str(a)


def test_a_forget_the_journal_does_not_take_removes_nothing_and_fails(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-11: the deletion is journaled before the name goes: a journal that does not take it leaves the key file
    and the command fails; run again with the journal back, it removes the file, journaled once."""
    sealed = _sealed(tmp_path, monkeypatch)
    bkc.unseal_to(sealed, PASS)
    out = _restore_key(box)
    real = bkc.record

    def no_journal(detail: Any, event: str = bkc.EVENT) -> int:
        if event == "backup.restore_key_forgotten":
            raise bkc.Stop(bkc.JOURNAL_UNSURE)
        return real(detail, event)

    monkeypatch.setattr(bkc, "harden", lambda: None)
    monkeypatch.setattr(bkc, "record", no_journal)
    assert bkc.main(["--forget-restore-key"]) != 0 and out.is_file()
    monkeypatch.setattr(bkc, "record", real)
    assert bkc.main(["--forget-restore-key"]) == 0 and not out.exists()
    assert _events(box, "backup.restore_key_forgotten") == [{"path": str(out)}]


def test_a_forget_never_removes_a_key_it_did_not_look_at(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-12: forget B has looked at the key; meanwhile forget A and an unseal run. B must never remove a key the
    unseal made after B looked: looking and removing hold the restore folder's lock, which the unseal's link takes."""
    sealed = _sealed(tmp_path, monkeypatch)
    bkc.unseal_to(sealed, PASS)
    out = _restore_key(box)
    main_thread, real_stat = threading.get_ident(), os.stat
    other: list[Any] = []

    def meanwhile() -> None:
        try:
            bkc.forget_restore_key()  # A
        except bkc.Stop as e:
            other.append(e.text)
        other.append(bkc.unseal_to(sealed, PASS))

    t = threading.Thread(target=meanwhile)

    def stat_(path: Any, *a: Any, **k: Any) -> Any:
        st = real_stat(path, *a, **k)
        if path == bkc.RESTORE_KEY and threading.get_ident() == main_thread and t.ident is None:
            t.start()
            t.join(5)  # A and the unseal, while B holds what it looked at
        return st

    monkeypatch.setattr(os, "stat", stat_)
    bkc.forget_restore_key()  # B
    t.join(60)
    assert not t.is_alive() and other[0] is bkc.RESTORE_KEY_NOT_A_FILE
    assert out.is_file() and bkc.read_key(out.read_bytes()) is not None  # the unseal's key: never removed


def _shell_install(tmp_path: Path, ceremony: str) -> tuple[Path, Callable[..., subprocess.CompletedProcess[str]]]:
    """The installer's reader (--kek-passphrase-file) and its backup key step, run by bash with no terminal, a
    declaration in place and ``ceremony`` as the python3 the step runs. Returns the passphrase file and the runner
    (``tail``: the script after the reader; ``keep``: --keep-kek-passphrase-file; ``env``: added to PATH; ``pre``:
    the script before the variables the installer sets)."""
    reader = _between("KP_WHO=install\n", "# ---- end of KEK-INPUT\n")
    bin_, secrets = tmp_path / "bin", tmp_path / "deploy" / "secrets"
    for d in (bin_, secrets):
        d.mkdir(parents=True)
    (secrets / "backup-target.json").write_text("{}", encoding="utf-8")  # declared already
    (bin_ / "python3").write_text("#!/bin/sh\n" + ceremony, encoding="utf-8")
    (bin_ / "python3").chmod(0o755)
    keys = tmp_path / "root"
    keys.mkdir(mode=0o700)
    pp = keys / "trialbox-kek.pass"

    def run(
        tail: str, keep: bool = False, env: dict[str, str] | None = None, pre: str = ""
    ) -> subprocess.CompletedProcess[str]:
        script = (f'{pre}die() {{ echo "die: $*"; exit 1; }}\nsay() {{ :; }}\nFAILS=()\n'
                  f"PP_FILE={pp}\nPP_STDIN=0\nPP_FD=\nPP_REMOVE=\nPP_KEEP={int(keep)}\nROOT={tmp_path}\n{reader}"
                  f"{tail}")  # fmt: skip
        return subprocess.run(["setsid", "bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
                              check=False, stdin=subprocess.DEVNULL, timeout=60,
                              env={"PATH": f"{bin_}:{os.environ['PATH']}", **(env or {})})  # fmt: skip

    return pp, run


def _write_pass(pp: Path) -> None:
    pp.write_text(PASS + "\n", encoding="utf-8")
    pp.chmod(0o600)


def test_a_kill_after_backup_pub_leaves_no_passphrase_file_and_the_next_start_removes_a_left_one(
    tmp_path: Path,
) -> None:
    """H-08: the install's passphrase file is removed before the ceremony can make backup.pub: the installer killed
    right after backup.pub is made (before its next line) leaves no passphrase file beside the sealed key. One left
    beside a sealed key (an older installer killed there) is removed at the next start, before anything else, unless
    --keep-kek-passphrase-file."""
    secrets = tmp_path / "deploy" / "secrets"
    killed = f"cat >/dev/null\n: > {secrets}/backup-key-0000.sealed\n: > {secrets}/backup.pub\nkill -KILL 0\n"
    pp, run = _shell_install(tmp_path, killed)
    key_step = _between("# E2E P-01 (the integrator's ruling Q1, 2026-11-27)", "# T-117b (D-274)")
    _write_pass(pp)
    r = run(f"TB_ENV_SITE=PRODUCTION\n{key_step}echo finished\n")
    assert r.returncode < 0 and "finished" not in r.stdout, r.stdout + r.stderr  # killed in the ceremony
    assert (secrets / "backup.pub").is_file() and not pp.exists()
    _write_pass(pp)  # left over beside the sealed key
    r = run("echo started\n", keep=True)
    assert r.returncode == 0 and pp.exists() and "started" in r.stdout, r.stderr
    r = run("echo started\n")
    assert r.returncode == 0 and "started" in r.stdout, r.stderr
    assert not pp.exists() and f"the passphrase file {pp} is removed" in r.stdout and PASS not in r.stdout + r.stderr


@pytest.mark.parametrize("allexport", [False, True])
def test_the_install_passphrase_is_in_no_child_environment(tmp_path: Path, allexport: bool) -> None:
    """H-09: a caller's exported KP_VALUE (empty, as a launcher might export it) loses its export where the reader
    starts, and so does bash's allexport (bash -a: every assignment after it exported): no child of the installer
    has the passphrase, or KP_VALUE, in its environment; the ceremony gets it on stdin alone."""
    rec = tmp_path / "rec"
    rec.mkdir()
    pp, run = _shell_install(tmp_path, f"cat > {rec}/stdin\ncat /proc/$$/environ > {rec}/ceremony.environ\n")
    key_step = _between("# E2E P-01 (the integrator's ruling Q1, 2026-11-27)", "# T-117b (D-274)")
    _write_pass(pp)
    r = run(f"cat /proc/self/environ > {rec}/child.environ\nTB_ENV_SITE=PRODUCTION\n{key_step}",
            env={"KP_VALUE": "", "kp_again": ""}, pre="set -a\n" if allexport else "")  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert (rec / "stdin").read_text(encoding="utf-8") == PASS + "\n"
    for name in ("child.environ", "ceremony.environ"):
        seen = (rec / name).read_bytes()
        assert seen and PASS.encode() not in seen and b"KP_VALUE=" not in seen and b"kp_again=" not in seen, name


def test_a_deeply_nested_declaration_is_refused_journaled_and_replaced(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-16 (seventh review): a declaration nested deeper than the decoder recurses is not a declaration: the run
    refuses with backup.target_undeclared, and --replace (its repair) declares the target again."""
    nas = tmp_path / "nas"
    nas.mkdir()
    _mounted(tmp_path, monkeypatch, (nas, *NFS, ()))
    rec_file = box.pub_dir / bkc.TARGET_RECORD
    rec_file.write_bytes(b"[" * (bkc.MAX_FILE - 1))
    e = _refused_at_the_run(box, nas)
    assert e.text is bkc.NO_TARGET_DECLARED
    assert _events(box, "backup.target_undeclared") == [{"record": str(rec_file), "found": "not a declaration"}]
    bkc.declare_target(str(nas), "IT Operator", True, {})
    assert json.loads(rec_file.read_text(encoding="utf-8"))["path"] == str(nas)


@pytest.mark.parametrize(
    ("line", "want"),
    [
        ("TB_BACKUP_OFFBOX=/mnt/IT's-backup", "/mnt/IT's-backup"),
        ('TB_BACKUP_OFFBOX="/mnt/IT\'s-backup"', "/mnt/IT's-backup"),
        ("TB_BACKUP_OFFBOX='/mnt/backup'", "/mnt/backup"),
    ],
)
def test_the_installer_declares_the_configured_path_as_written(tmp_path: Path, line: str, want: str) -> None:
    """M-17 (seventh review): only a matching pair of outer quotes is taken off TB_BACKUP_OFFBOX; a quote inside the
    path stays, so the installer declares the folder deploy/.env names, not another one."""
    (tmp_path / "deploy" / "secrets").mkdir(parents=True)
    (tmp_path / "deploy" / ".env").write_text(f"OTHER=1\n{line}\n", encoding="utf-8")
    step = _between('      KP_OFFBOX=""\n', "      if [ ! -f deploy/secrets/backup-target.json ]")
    script = 'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n' + step + 'printf "%s" "$KP_OFFBOX" > got\n'
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False, timeout=30)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "got").read_text(encoding="utf-8") == want
