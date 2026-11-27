"""E2E P-01 (the integrator's ruling Q1 of 2026-11-27): a PRODUCTION box makes its backup key at install, and a
backup made with it restores.

The journey the E2E run could not walk: a PRODUCTION box (``TB_ENV`` unset) is installed with no backup key; its
install shows the key once on the terminal (the paper copy hospital IT keeps sealed), IT types the check letters of
its last line back, and only then ``backup.pub`` exists. ``trialbox backup-keygen`` stays refused there. The nightly
backup is made with that public key; IT types the letters of the paper copy into a file, as the copy says, and the
restore drill restores that backup from it into scratch databases. Every row is synthetic.
"""

from __future__ import annotations

import io
import re
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


class Terminal:
    """The install's terminal: what was shown on it, and IT typing the check letters it read there (or ``typed``)."""

    def __init__(self, typed: str | None = None) -> None:
        self.shown, self.typed = io.StringIO(), typed

    def write(self, text: str) -> int:
        return self.shown.write(text)

    def flush(self) -> None:
        pass

    def getvalue(self) -> str:
        return self.shown.getvalue()

    def readline(self) -> str:
        if self.typed is not None:
            return self.typed + "\n"
        return str(LINE.findall(self.getvalue())[-1][2]) + "\n"


def _tty(term: Terminal) -> TextIO:
    return cast(TextIO, term)


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Box:
    b = Box(tmp_path)
    monkeypatch.setattr(bkc, "DEPLOY", b.deploy)
    monkeypatch.setattr(bkc, "PUB_DIR", b.pub_dir)
    monkeypatch.setattr(bkc, "COMPOSE", b.compose)
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    monkeypatch.delenv("TB_ENV", raising=False)  # unset: a PRODUCTION box
    monkeypatch.delenv("TB_BACKUP_PUBKEY", raising=False)
    return b


def _env() -> dict[str, str]:
    return {"TB_SITE_ID": SITE}


def test_a_production_box_makes_its_backup_key_at_install_and_a_backup_restores(
    box: Box, tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # the ad hoc commands stay refused on PRODUCTION (rc1): the install is the box's one way to its key
    assert trialbox_main(["backup-keygen", "--private", str(tmp_path / "k"), "--public", str(tmp_path / "p")]) == 1
    capsys.readouterr()
    term = Terminal()
    rec = bkc.install(_env(), _tty(term))
    shown = term.getvalue()
    assert box.pub.is_file() and rec["pub"] == str(box.pub)
    fp = bk.fingerprint(bk.load_public(box.pub).public_bytes_raw())
    assert rec["fingerprint"] == fp and f"fingerprint {fp}" in shown and shown.endswith(bkc.CLEAR)
    assert [e["detail"]["fingerprint"] for e in box.journal() if e["event"] == bkc.EVENT] == [fp]
    letters = "".join("".join(m[1].split()) for m in LINE.findall(shown))
    for f in box.pub_dir.iterdir():  # the box keeps the public half and its record, never a letter of the key
        assert letters not in f.read_text(encoding="utf-8"), f.name
    # a second install changes nothing: "once" is backup.pub
    with pytest.raises(bkc.Stop) as again:
        bkc.install(_env(), _tty(Terminal()))
    assert again.value.text is bkc.ALREADY and bk.fingerprint(bk.load_public(box.pub).public_bytes_raw()) == fp

    # the nightly backup with that public key, then IT types the paper copy into a file and restores it
    for var, cmd in pg_client.env().items():
        monkeypatch.setenv(var, cmd)
    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL)"])
    db.execute("INSERT INTO marks VALUES (?, ?)", ("P1", "approach"))
    dirs = {"audit": tmp_path / "audit", "lake": tmp_path / "lake"}
    for d in dirs.values():
        d.mkdir()
    (dirs["lake"] / "patient.parquet").write_bytes(b"PAR1" + bytes(range(256)) * 50)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": SITE, **pg_client.env()}
    (made, *_) = bk.backup([tmp_path / "nas"], box.pub, env=env, dirs=dirs)
    typed = tmp_path / "usb" / "typed-from-paper.key"
    typed.parent.mkdir()
    typed.write_text("\n".join(" ".join(m[1].split()) for m in LINE.findall(shown)) + "\n", encoding="utf-8")
    res = rd.drill(made, typed, env, work=tmp_path, free=lambda _p: 10**12)
    assert res["ok"], res
    assert res["databases"]["trialbox_wf"]["differ_count"] == 0 and res["databases"]["trialbox_wf"]["rows"] > 0


def test_letters_that_do_not_match_make_no_backup_pub(box: Box) -> None:
    with pytest.raises(bkc.Stop) as got:
        bkc.install(_env(), _tty(Terminal(typed="AAAA")))
    assert got.value.text is bkc.NOT_CONFIRMED and not box.pub.exists()
    assert [e for e in box.journal() if e["event"] == bkc.EVENT] == []
    assert len(box.pending()) == 1  # the record of the key that was shown and not taken stays (never removed)
    bkc.install(_env(), _tty(Terminal()))  # the install run again: a new key, shown once
    assert box.pub.is_file() and len(box.pending()) == 2


def test_no_terminal_makes_nothing(
    box: Box, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bkc, "TTY", str(tmp_path / "no-terminal"))
    monkeypatch.setattr(bkc, "harden", lambda: None)
    assert bkc.main(["--install"]) == 1
    assert capsys.readouterr().err.strip() == bkc.NO_TERMINAL["en"]
    assert not box.pub.exists() and box.pending() == []


def test_the_install_makes_the_key_on_a_production_box() -> None:
    text = (Path(__file__).resolve().parents[2] / "deploy" / "install.sh").read_text(encoding="utf-8")
    step: Any = re.search(r"in DEV\|TEST\|VALIDATION\) ;; \*\)\n(.*?)\nesac", text, re.S)
    assert step, "install.sh: the backup key step for a PRODUCTION box"
    assert "python3 -m tools.backup_key_ceremony --install" in step.group(1)
    assert "! -f deploy/secrets/backup.pub" in step.group(1) and "FAILS+=" in step.group(1)
