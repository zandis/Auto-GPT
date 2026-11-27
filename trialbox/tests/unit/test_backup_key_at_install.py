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
import contextlib
import errno
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
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO, cast

import pytest
from tb_common.db import Database

from tests import pg_client
from tests.unit.test_backup_key_ceremony import SITE, Box
from tools import backup_key_ceremony as bkc
from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bs
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


def _offbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """H-02: the box's backup target, off the box (declared, with its mark, as backup_schedule.target_kind counts it)."""
    nas = tmp_path / "nas"
    nas.mkdir(exist_ok=True)
    (nas / bs.OFFBOX_MARKER).write_text("", encoding="utf-8")
    monkeypatch.setenv("TB_BACKUP_TARGETS", str(nas))
    monkeypatch.setenv("TB_BACKUP_OFFBOX", str(nas))
    return nas


def _sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An unattended install's sealed key on the box (an off-box target set)."""
    _offbox(tmp_path, monkeypatch)
    return Path(bkc.install_sealed(bkc._env(), PASS)["sealed"])


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

            monkeypatch.setattr(bkc.termios, "tcsetattr", refuse)
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
    out = tmp_path / "usb" / "trialbox-backup.key"
    out.parent.mkdir()
    asked: list[str] = []

    def it(text: str) -> str | None:
        if not asked and "passphrase" in text.lower():
            asked.append(text)
            return PASS + "\n"
        return None

    rc, shown = _on_a_terminal(box, ["--unseal", str(sealed), "--out", str(out)], it, timeout=30)
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
    key_file = tmp_path / "usb" / "trialbox-backup.key"
    key_file.parent.mkdir()
    monkeypatch.setattr("sys.stdin", io.StringIO("not the passphrase of it\n"))
    assert bkc.main(["--unseal", str(sealed), "--out", str(key_file)]) == 1
    assert "does not open with this passphrase" in capsys.readouterr().err and not key_file.exists()
    # the passphrase gives the key file back, and the nightly backup restores from it
    monkeypatch.setattr("sys.stdin", io.StringIO(PASS + "\n"))
    assert bkc.main(["--unseal", str(sealed), "--out", str(key_file)]) == 0
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


def test_the_sealed_key_is_on_the_offbox_target_before_backup_pub_and_restores_from_there_alone(
    box: Box, made: list[bytes], tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-02: the sealed copy goes to the off-box backup target (synced, read back) before backup.pub exists; with the
    box's disk lost (its own sealed file gone) the target's copy and the passphrase restore the nightly backup."""
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
    key_file = tmp_path / "usb" / "trialbox-backup.key"
    key_file.parent.mkdir()
    assert bkc.unseal_to(copy, key_file, PASS) == fp and bkc.read_key(key_file.read_bytes()) == made[-1]
    _restores(box, box.pub, key_file, tmp_path, db_url, monkeypatch)


@pytest.mark.parametrize("target", ["none", "on the box", "write fails"])
def test_no_offbox_copy_makes_no_backup_pub(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """H-02: no target, a target on the box's own disk only, or an off-box copy that cannot be written: refused, and
    no backup.pub (no backup may encrypt to a key whose only copy is on the box)."""
    if target == "on the box":
        (tmp_path / "backups").mkdir()
        monkeypatch.setenv("TB_BACKUP_TARGETS", str(tmp_path / "backups"))
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
    assert got.value.text is (bkc.STEP_FAILED if target == "write fails" else bkc.NO_OFFBOX_COPY)
    assert not box.pub.exists() and [e for e in box.journal() if e["event"] == bkc.EVENT] == []
    if target != "write fails":  # refused before a key is made
        assert box.pending() == [] and list(box.pub_dir.glob("*.sealed")) == []


@pytest.mark.parametrize("cut", ["key_text", "fsync"])
def test_an_interrupted_unseal_leaves_nothing_that_blocks_its_retry(
    box: Box, made: list[bytes], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    """M-03: an unseal cut short (before or while the key file is written) leaves no file, partial or temporary, at
    the place given; the same command again makes the key file."""
    sealed = _sealed(tmp_path, monkeypatch)
    usb = tmp_path / "usb"
    usb.mkdir()
    out = usb / "trialbox-backup.key"

    def cut_here(*_a: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as m:
        m.setattr(bkc if cut == "key_text" else bkc.os, cut, cut_here)
        with pytest.raises(KeyboardInterrupt):
            bkc.unseal_to(sealed, out, PASS)
    assert list(usb.iterdir()) == []
    bkc.unseal_to(sealed, out, PASS)
    assert list(usb.iterdir()) == [out] and stat.S_IMODE(out.stat().st_mode) == 0o600
    assert bkc.read_key(out.read_bytes()) == made[-1]


def test_an_unseal_input_larger_than_a_sealed_key_is_refused_by_its_size(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-05: a file larger than MAX_FILE (a sealed key padded to 1 MiB: its first MAX_FILE bytes would open) is
    refused by its size, before it is read; nothing is written."""
    sealed = _sealed(tmp_path, monkeypatch)
    big = tmp_path / "big.sealed"
    big.write_bytes(sealed.read_bytes() + b" " * (1 << 20))
    out = tmp_path / "k"
    with pytest.raises(bkc.Stop) as got:
        bkc.unseal_to(big, out, PASS)
    assert got.value.text is bkc.NOT_UNSEALED and not out.exists()


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
