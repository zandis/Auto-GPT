"""10K-13 (D-1379): the backup-key ceremony on the box's host. Hospital IT as root, with a witness who is another
person, makes the backup key pair once; the private key goes to a stick (the ``backup-keygen`` key file) and to a
paper sheet on that stick whose lines carry check letters; the box keeps the public key; the audit names both people
and the key's fingerprint, never the key. The refusals: wrong role, no names or one person twice (in any spelling),
no audit folder, a second run (by the public key or by the audit), no stick, a folder on the box's disks, a stick that
cannot be written, a file or link of either name on the stick; and a damaged paper line. The failure domain: a
failure injected where it happens (a sync after a file is made, the stick's folder sync, a read-back, the public key's
folder, its name taken meanwhile, the audit append, an interruption, an unexpected error, another device) leaves
nothing on the stick or the box and says what was removed; a removal that fails is named with its path. Every key is
made in the test's tmp folder; outputs are checked for its absence.
"""

from __future__ import annotations

import ast
import base64
import dataclasses
import errno
import io
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit as tb_audit
from tb_common import kek as K

from tools import backup_key_ceremony as bkc
from tools import core_words, key_escrow
from tools.trialbox import backup as bk

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
OP, WIT = "IT Person One", "Witness Two"


#: the audit writer of these tests: uid 65534 for real when the tests run as root (the folder is given to it and the
#: child really drops to it), else the user running the tests (the folder is its own; the drop is injected)
WRITER = (65534, 65534) if os.geteuid() == 0 else (os.geteuid(), os.getegid())


def _drop_seam(monkeypatch: pytest.MonkeyPatch, drops: Path) -> None:
    """``bkc._drop_to`` as the tests run it: each identity asked for is noted in ``drops`` (by the child, before it
    drops); as root the real drop follows, as any other user it can only check that it is that identity already."""
    real = bkc._drop_to

    def drop(uid: int, gid: int) -> None:
        with drops.open("a", encoding="utf-8") as fh:
            fh.write(f"{uid}:{gid}\n")
        if os.geteuid() == 0:
            real(uid, gid)
        elif (os.geteuid(), os.getegid()) != (uid, gid):
            raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(bkc, "_drop_to", drop)


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A host as root with a stick the media check accepts, an audit folder of the audit writer (:data:`WRITER`) and a
    deploy folder with no key yet."""
    stick, audit, sec, deploy = (tmp_path / n for n in ("usb", "audit", "secrets", "deploy"))
    for d in (stick, audit, sec, deploy):
        d.mkdir()
    if os.geteuid() == 0:
        os.chown(audit, *WRITER)
    real = key_escrow.media_problem
    monkeypatch.setattr(key_escrow, "media_problem", lambda out, s: None if K._inside(out, stick) else real(out, s))
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    _drop_seam(monkeypatch, tmp_path / "drops.txt")
    return {"tmp": tmp_path, "stick": stick, "audit": audit, "sec": sec, "deploy": deploy,
            "pub": deploy / "secrets" / "backup.pub", "drops": tmp_path / "drops.txt"}  # fmt: skip


def _again(monkeypatch: pytest.MonkeyPatch, b: dict[str, Path]) -> None:
    """After ``monkeypatch.undo()``: the fixture's patches again, for a second run."""
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    real = key_escrow.media_problem
    monkeypatch.setattr(key_escrow, "media_problem", lambda o, s: None if K._inside(o, b["stick"]) else real(o, s))
    _drop_seam(monkeypatch, b["drops"])


def _main(b: dict[str, Path], capsys: pytest.CaptureFixture[str], *extra: str, stick: Path | None = None,
          names: tuple[str, ...] = ("--operator", OP, "--witness", WIT), lang: str = "en") -> tuple[int, str]:  # fmt: skip
    argv = ["--stick", str(stick or b["stick"]), *names, "--deploy", str(b["deploy"]), "--secrets", str(b["sec"]),
            "--audit-dir", str(b["audit"]), "--lang", lang, *extra]  # fmt: skip
    rc = bkc.main(argv, env={"TB_SITE_ID": "synthetic-site", "TB_TZ": "Asia/Tokyo"})
    out = capsys.readouterr()
    return rc, out.out + out.err


def _events(b: dict[str, Path]) -> list[dict[str, Any]]:
    rows = [json.loads(x) for f in b["audit"].rglob("*.jsonl") for x in f.read_text().splitlines()]
    return [e for e in rows if e["event"] == bkc.EVENT]


def _secret_forms(stick: Path) -> list[str]:
    """The key's letters as the stick holds them, run together and as one line of the sheet, and its raw base64."""
    sk = bk.load_private(stick / bkc.KEY_FILE)
    raw = sk.private_bytes_raw()
    letters = base64.b32encode(raw).decode().rstrip("=")
    return [letters, letters[:16], letters[16:32], base64.b64encode(raw).decode(), raw.hex()]


def _everything_written(b: dict[str, Path], out: str) -> str:
    texts = [out] + [p.read_text(errors="replace") for d in ("audit", "deploy") for p in b[d].rglob("*") if p.is_file()]
    return "\n".join(texts)


def _nothing_kept(b: dict[str, Path], stick: Path | None = None) -> None:
    assert not list((stick or b["stick"]).iterdir())
    assert not os.path.lexists(b["pub"])
    if b["deploy"].is_dir():
        assert not list(b["deploy"].rglob("*"))  # no public key, no temporary file, no folder made for them
    assert _events(b) == []


def _fd_path(fd: int) -> str:
    return os.readlink(f"/proc/self/fd/{fd}")


def _fail_fsync(monkeypatch: pytest.MonkeyPatch, when: Any) -> None:
    """``os.fsync`` raises EIO for the open file or folder whose path ``when`` accepts, as a failing stick does."""
    real = os.fsync

    def fsync(fd: int) -> None:
        if when(_fd_path(fd)):
            raise OSError(errno.EIO, "Input/output error")
        real(fd)

    monkeypatch.setattr(os, "fsync", fsync)


def _removed_all(out: str, *paths: Path) -> None:
    """The refusal says each file was removed again and nothing of the key is kept."""
    said = bkc.REMOVED_ALL["en"].split("{files}")
    assert said[0] in out and said[1] in out, out
    for p in paths:
        assert str(p) in out, (p, out)


# ------------------------------------------------------------------------------------------------ the ceremony


def test_the_ceremony_puts_the_key_on_the_stick_and_paper_and_audits_both_names(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    rc, out = _main(box, capsys)
    assert rc == 0, out
    key_file, paper = box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE
    assert sorted(p.name for p in box["stick"].iterdir()) == sorted([bkc.KEY_FILE, bkc.PAPER_FILE])
    for f in (key_file, paper):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert sorted(p.name for p in box["pub"].parent.iterdir()) == ["backup.pub"]  # no temporary file left
    # the box keeps the public half where `trialbox backup` reads it; both forms give its key
    pub = bk.load_public(box["pub"]).public_bytes_raw()
    fp = bk.fingerprint(pub)
    assert bk.load_private(key_file).public_key().public_bytes_raw() == pub
    raw = bkc.read_paper(paper.read_text(encoding="utf-8"))
    assert raw == bk.load_private(key_file).private_bytes_raw()
    sheet = paper.read_text(encoding="utf-8")
    assert f"fingerprint {fp}" in sheet and "site synthetic-site" in sheet
    assert len(re.findall(r"^\d \| ", sheet, re.MULTILINE)) == 4
    for lg in bkc.LANGS:
        assert bkc.SHEET_HEAD[lg] in sheet
    # the audit: who, when, the fingerprint; both names; never the key, a line of it or a path on the stick
    (ev,) = _events(box)
    assert ev["actor"] == bkc.ACTOR
    assert ev["ts"].endswith("+09:00")  # TB_TZ, the site's zone, as `restore` writes its events
    assert {k: ev["detail"][k] for k in ("fingerprint", "operator", "witness", "site", "forms")} == {
        "fingerprint": fp, "operator": OP, "witness": WIT, "site": "synthetic-site", "forms": ["stick", "paper"]}  # fmt: skip
    assert str(box["stick"]) not in json.dumps(ev)
    assert fp in out and OP in out and WIT in out and "Unmount (eject) the stick" in out
    written = _everything_written(box, out)
    for form in _secret_forms(box["stick"]):
        assert form not in written
    # a stream encrypted to the public key the box kept opens with the stick's key and with the paper's
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    buf = io.BytesIO()
    w = bk._Encryptor(buf, bk.load_public(box["pub"]), {"site": "synthetic-site"})
    w.write(b"synthetic rows")
    w.finish()
    for key in (bk.load_private(key_file), X25519PrivateKey.from_private_bytes(raw)):
        assert b"".join(bk.decrypt_stream(io.BytesIO(buf.getvalue()), key)) == b"synthetic rows"


def test_the_ceremony_speaks_japanese_and_chinese(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = _main(box, capsys, lang="ja")
    assert rc == 0, out
    assert "バックアップ鍵" in out and OP in out
    rc, out = _main(box, capsys, lang="zh-TW", stick=box["tmp"] / "usb")
    assert rc == 1
    assert "已拒絕" in out and "備份金鑰" in out


# ------------------------------------------------------------------------------------------------ the refusals


def test_wrong_role_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                               monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(bkc, "is_root", lambda: False)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NOT_ROOT["en"] in out
    rc, out = _main(box, capsys, lang="ja")
    assert rc == 1 and bkc.NOT_ROOT["ja"] in out
    _nothing_kept(box)


@pytest.mark.parametrize(
    ("names", "text"),
    [
        (("--operator", OP), bkc.NO_NAMES),
        (("--witness", WIT), bkc.NO_NAMES),
        (("--operator", OP, "--witness", "  "), bkc.NO_NAMES),
        (("--operator", OP, "--witness", OP.upper()), bkc.SAME_PERSON),
        (("--operator", "Taro Yamada", "--witness", "Ｔａｒｏ　Ｙａｍａｄａ"), bkc.SAME_PERSON),  # full width
        (("--operator", "Taro Yamada", "--witness", "taro  YAMADA"), bkc.SAME_PERSON),  # two spaces
        (("--operator", "山田 太郎", "--witness", "山田　　太郎"), bkc.SAME_PERSON),  # ideographic spaces
        (("--operator", "A\nB", "--witness", WIT), bkc.BAD_NAME),
        (("--operator", "x" * 101, "--witness", WIT), bkc.BAD_NAME),
    ],
)
def test_two_named_people_are_needed(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                     names: tuple[str, ...], text: dict[str, str]) -> None:  # fmt: skip
    rc, out = _main(box, capsys, names=names)
    assert rc == 1 and text["en"] in out
    _nothing_kept(box)


def test_no_audit_folder_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    box["audit"].rmdir()
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NO_AUDIT["en"] in out
    assert not list(box["stick"].iterdir()) and not box["pub"].exists()


def test_no_secrets_folder_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    box["sec"].rmdir()
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NO_SECRETS["en"].format(path=box["sec"]) in out
    _nothing_kept(box)


def test_no_stick_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    gone = box["tmp"] / "no-usb-here"
    rc, out = _main(box, capsys, stick=gone)
    assert rc == 1 and bkc.NO_STICK["en"].format(path=gone) in out
    assert not gone.exists() and not box["pub"].exists() and _events(box) == []


def test_a_folder_on_the_box_disks_is_not_a_stick(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    for folder in (box["tmp"] / "disk", box["sec"] / "inside"):
        folder.mkdir()
        rc, out = _main(box, capsys, stick=folder)
        assert rc == 1 and bkc.NOT_A_STICK["en"].format(path=folder) in out
        _nothing_kept(box, folder)


def test_a_stick_that_cannot_be_written_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(bkc, "writable", lambda folder, dir_fd=None: False)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NOT_WRITABLE["en"].format(path=box["stick"]) in out
    _nothing_kept(box)


def test_the_write_probe(tmp_path: Path) -> None:
    assert bkc.writable(tmp_path) is True
    assert list(tmp_path.iterdir()) == []  # the probe is removed
    assert bkc.writable(tmp_path / "missing") is False


@pytest.mark.parametrize("name", [bkc.KEY_FILE, bkc.PAPER_FILE])
def test_a_sync_that_fails_after_the_file_is_made_keeps_nothing(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _fail_fsync(monkeypatch, lambda path: path.endswith("/" + name))
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NOT_WRITABLE["en"].format(path=box["stick"]) in out
    made = [box["stick"] / bkc.KEY_FILE] + ([box["stick"] / bkc.PAPER_FILE] if name == bkc.PAPER_FILE else [])
    _removed_all(out, *made)
    assert "Traceback" not in out and len(out.strip().splitlines()) == 1
    _nothing_kept(box)


def test_the_stick_folder_sync_failing_keeps_nothing(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                                    monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """Every sync of the stick's folder fails, the undo's too: the files are removed but that is not confirmed on
    disk, so it is said so (H5), never that nothing of the key is kept."""
    _fail_fsync(monkeypatch, lambda path: path == str(box["stick"]))
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NOT_WRITABLE["en"].format(path=box["stick"]) in out
    key_file, paper = box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE
    assert bkc.REMOVED_NOT_DURABLE["en"].format(files=f"{paper}, {key_file}", folder=box["stick"]) in out
    assert "nothing of the key is kept" not in out
    _nothing_kept(box)


def test_short_writes_are_written_in_full(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                          monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    real = os.write

    def short(fd: int, data: Any) -> int:
        return real(fd, bytes(data)[:7] if _fd_path(fd).startswith(str(box["stick"])) else data)

    monkeypatch.setattr(os, "write", short)
    rc, out = _main(box, capsys)
    assert rc == 0, out
    assert bk.load_private(box["stick"] / bkc.KEY_FILE).public_key().public_bytes_raw() == bk.load_public(
        box["pub"]).public_bytes_raw()  # fmt: skip
    assert bkc.read_paper((box["stick"] / bkc.PAPER_FILE).read_text(encoding="utf-8"))


def test_a_file_made_on_another_device_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    """The stick pulled or mounted again between the check and the write: the file is not on the checked device."""
    real = bkc.check

    def moved(*a: Any, **k: Any) -> tuple[str, str, Any]:
        who, wit, held = real(*a, **k)
        return who, wit, dataclasses.replace(held, dev=held.dev + 1)

    monkeypatch.setattr(bkc, "check", moved)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.STICK_MOVED["en"].format(name=bkc.KEY_FILE, path=box["stick"]) in out
    _removed_all(out, box["stick"] / bkc.KEY_FILE)
    _nothing_kept(box)


def test_an_audit_append_that_fails_undoes_the_stick_and_the_public_key(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(self: tb_audit.AuditLog) -> None:
        raise tb_audit.AuditFull("audit volume has less than 64 MB free: free disk space first")

    monkeypatch.setattr(tb_audit.AuditLog, "_check_space", full)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.AUDIT_FAILED["en"].format(path=box["audit"]) in out
    # backup.pub was never at its name (it is linked only after the audit line): its temporary file is removed
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE, box["pub"].parent / ".backup.pub.",
                 box["pub"].parent)  # fmt: skip
    assert bkc.AUDIT_MAY_HOLD["en"].split("{fp}")[0] not in out  # nothing was written to the audit: not said
    assert "Traceback" not in out and len(out.strip().splitlines()) == 1
    _nothing_kept(box)
    # the box can run the ceremony again on the same stick: nothing of the failed one is in the way
    monkeypatch.undo()
    _again(monkeypatch, box)
    rc, out = _main(box, capsys)
    assert rc == 0, out
    assert len(_events(box)) == 1


@pytest.mark.parametrize("lang", bkc.LANGS)
def test_an_audit_line_synced_before_the_head_anchor_fails_is_kept_with_a_warning(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, lang: str
) -> None:
    """The append syncs the event's line, then the head anchor's own sync fails (EIO on ``.HEAD.json.tmp``, inside
    the library's ``write_head``): the line is on disk, so the ceremony is kept; but it is not said as done: the
    warning says the key is in place, the line is written, its anchor is not, names the audit's check, exit 2."""
    _fail_fsync(monkeypatch, lambda path: path.endswith("/.HEAD.json.tmp"))
    rc, out = _main(box, capsys, lang=lang)
    assert rc == bkc.KEPT_EXIT == 2, out
    (ev,) = _events(box)
    fp = bk.fingerprint(bk.load_public(box["pub"]).public_bytes_raw())
    assert ev["detail"]["fingerprint"] == fp
    assert sorted(p.name for p in box["stick"].iterdir()) == sorted([bkc.KEY_FILE, bkc.PAPER_FILE])
    want = bkc.KEPT_WARNING[lang].format(fp=fp, key=bkc.KEY_FILE, paper=bkc.PAPER_FILE, pub=box["pub"],
                                         event=bkc.EVENT, audit=box["audit"])  # fmt: skip
    assert want in out and "python tools/audit_verify.py" in out
    assert bkc.DONE[lang].split("{paper}")[1].split("{")[0] not in out  # never the closing text
    assert "Traceback" not in out
    for form in _secret_forms(box["stick"]):
        assert form not in out


def test_the_audit_writer_syncs_the_line_before_these_calls() -> None:
    """The ceremony counts a failed append as recorded only when it was raised inside a call that
    ``AuditLog._write`` makes after its ``os.fsync`` of the day file (``bkc.AFTER_LINE_SYNC``): hold the library to
    that order, so a change there fails here rather than turning the signal unsound."""
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(tb_audit.AuditLog._write)))
    calls: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            calls.setdefault(name, []).append(node.lineno)
    (synced,) = calls["fsync"]
    for name in bkc.AFTER_LINE_SYNC:
        assert calls[name] and min(calls[name]) > synced, (name, calls)
    assert min(calls["write"]) < synced  # the line is written before it is synced


def test_a_failing_sync_of_the_audit_folder_after_the_line_is_not_taken_as_recorded(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anchor's folder sync fails (inside ``write_head``) and the ceremony's own sync of the audit folder fails
    too: the day file's name is not known to be on disk, so the ceremony is undone and says the audit may hold it."""
    _fail_fsync(monkeypatch, lambda path: path == str(box["audit"]))
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.AUDIT_FAILED["en"].format(path=box["audit"]) in out
    (ev,) = _events(box)
    assert bkc.AUDIT_MAY_HOLD["en"].format(fp=ev["detail"]["fingerprint"]) in out
    assert not list(box["stick"].iterdir()) and not os.path.lexists(box["pub"])


def test_an_audit_line_whose_sync_fails_is_not_recorded(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """EIO on the ``os.fsync`` of the audit's day file only (``tb_common.audit`` ``_write``): the line is in the
    file but not known to be on disk, so the ceremony is undone, never said as done, and the refusal says the audit
    may hold the event; a rerun is then refused by the audit and says how to go on (D-1379)."""
    _fail_fsync(monkeypatch, lambda path: path.startswith(str(box["audit"]) + "/") and path.endswith(".jsonl"))
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.AUDIT_FAILED["en"].format(path=box["audit"]) in out
    assert bkc.DONE["en"].split("{paper}")[1].split("{")[0] not in out
    assert bkc.KEPT_WARNING["en"].split("{fp}")[0] not in out
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE, box["pub"].parent / ".backup.pub.")
    (ev,) = _events(box)  # the line is in the page cache, as a later reader sees it
    assert bkc.AUDIT_MAY_HOLD["en"].format(fp=ev["detail"]["fingerprint"]) in out
    assert "Traceback" not in out and len(out.strip().splitlines()) == 1
    assert not list(box["stick"].iterdir()) and not os.path.lexists(box["pub"])
    monkeypatch.undo()
    _again(monkeypatch, box)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.AUDITED_ALREADY["en"].format(at=ev["ts"], fp=ev["detail"]["fingerprint"]) in out
    assert bkc.AUDITED_NO_KEY["en"].format(fp=ev["detail"]["fingerprint"]) in out and "RUNBOOK §25" in out
    assert not list(box["stick"].iterdir())


@pytest.mark.parametrize("foreign", [False, True])
def test_stick_files_gone_before_the_undo_are_left_and_said(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, foreign: bool
) -> None:
    """The stick is pulled after its files were synced (moved away before the read-back): the undo does not say
    they were removed; with ``foreign``, another stick holds a file of the same name at the path, which the undo
    leaves as it is (not the file this run made). "Nothing of the key is kept" is never said."""
    pulled = box["tmp"] / "pulled"
    pulled.mkdir()
    key_file, paper = box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE

    def pull(path: Path) -> Any:
        for f in (key_file, paper):
            os.replace(f, pulled / f.name)
        if foreign:
            key_file.write_text("another stick's file (synthetic)\n", encoding="utf-8")
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(path))

    monkeypatch.setattr(bk, "load_private", pull)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NOT_WRITABLE["en"].format(path=box["stick"]) in out
    assert "nothing of the key is kept" not in out and bkc.REMOVED_ALL["en"].split("{files}")[0] not in out
    if foreign:
        assert bkc.LEFT_GONE["en"].format(files=paper) in out
        assert bkc.LEFT_OTHER["en"].format(files=key_file) in out
        assert key_file.read_text(encoding="utf-8") == "another stick's file (synthetic)\n"  # not deleted
    else:
        assert bkc.LEFT_GONE["en"].format(files=f"{paper}, {key_file}") in out
        assert not list(box["stick"].iterdir())
    assert sorted(p.name for p in pulled.iterdir()) == sorted([bkc.KEY_FILE, bkc.PAPER_FILE])
    assert not os.path.lexists(box["pub"]) and _events(box) == []
    for lg in ("ja", "zh-TW"):
        assert bkc.LEFT_GONE[lg].split("{files}")[0]


@pytest.mark.parametrize("replaced", [False, True])
def test_an_interruption_right_after_the_link_keeps_the_key(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, replaced: bool
) -> None:
    """Ctrl-C right after ``os.link`` made ``backup.pub``, which now comes after the audit line (H4): a backup may
    have read it, so nothing of the key is removed, exit 2; ``backup.pub`` is ours (looked at: same inode), so the
    warning says the public key is in place (review of c2fcb044, item 3). With ``replaced``, another file took the
    name before the check: whether ours was visible cannot be told, so nothing is removed either, the other file
    stays, and the warning says to check ``backup.pub``."""
    real = os.link

    def link(src: Any, dst: Any) -> None:
        real(src, dst)
        if replaced:
            other = Path(dst).with_name("other.pub")
            other.write_text("another public key (synthetic)\n", encoding="utf-8")
            os.replace(other, dst)
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", link)
    rc, out = _main(box, capsys)
    assert rc == bkc.KEPT_EXIT, out
    (ev,) = _events(box)
    fp = ev["detail"]["fingerprint"]
    text = bkc.PUB_KEPT_WARNING if replaced else bkc.PUB_LINKED_WARNING
    assert text["en"].format(fp=fp, key=bkc.KEY_FILE, paper=bkc.PAPER_FILE, pub=box["pub"], event=bkc.EVENT,
                             audit=box["audit"]) in out  # fmt: skip
    assert sorted(p.name for p in box["stick"].iterdir()) == sorted([bkc.KEY_FILE, bkc.PAPER_FILE])
    assert sorted(p.name for p in box["pub"].parent.iterdir()) == ["backup.pub"]  # the temporary file is removed
    if replaced:
        assert box["pub"].read_text(encoding="utf-8") == "another public key (synthetic)\n"
    else:
        assert bk.fingerprint(bk.load_public(box["pub"]).public_bytes_raw()) == fp
    assert bkc.REMOVED_ALL["en"].split("{files}")[0] not in out


@pytest.mark.parametrize("damage", ["torn last line", "damaged older line", "empty line"])
def test_an_audit_that_cannot_be_read_whole_is_refused(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], damage: str
) -> None:
    """The once-only check reads every line of every day file; a line that is not one JSON object, the newest file's
    torn last line included (``verify`` fails it too), is refused before anything is written, naming the file and
    the audit's check."""
    good = json.dumps({"event": "x.synthetic", "hash": "0" * 64}) + "\n"
    old, new = box["audit"] / "2026-01-01.jsonl", box["audit"] / "2026-01-02.jsonl"
    if damage == "torn last line":
        old.write_text(good, encoding="utf-8")
        new.write_text(good + '{"event":"backup.key_ceremony","detail":{"site":"synthetic-site"', encoding="utf-8")
        bad = new
    elif damage == "damaged older line":
        old.write_text(good + '{"event":"backup.key_ceremo\x00\n' + good, encoding="utf-8")
        new.write_text(good, encoding="utf-8")
        bad = old
    else:
        old.write_text(good, encoding="utf-8")
        new.write_text(good + "\n" + good, encoding="utf-8")
        bad = new
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.AUDIT_UNREADABLE["en"].format(path=bad, audit=box["audit"]) in out
    assert not list(box["stick"].iterdir()) and not os.path.lexists(box["pub"])
    with pytest.raises(bkc.CeremonyError):
        bkc.earlier_ceremony(box["audit"], "synthetic-site")


def test_a_public_key_without_a_ceremony_in_the_audit_says_so(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    pk = X25519PrivateKey.generate().public_key().public_bytes_raw()  # as backup-keygen leaves it, unaudited
    box["pub"].parent.mkdir(parents=True)
    box["pub"].write_text(base64.b64encode(pk).decode() + "\n", encoding="utf-8")
    for lg in bkc.LANGS:
        rc, out = _main(box, capsys, lang=lg)
        assert rc == 1 and bkc.ALREADY[lg].format(fp=bk.fingerprint(pk)) in out
        assert bkc.NO_CEREMONY_FOR_KEY[lg] in out
    assert not list(box["stick"].iterdir()) and _events(box) == []


def test_a_public_key_folder_that_cannot_be_made_keeps_nothing(box: dict[str, Path],
                                                              capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    box["deploy"].rmdir()
    box["deploy"].write_text("a file where the deploy folder should be (synthetic)\n", encoding="utf-8")
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.PUB_FAILED["en"].format(path=box["pub"]) in out
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    _nothing_kept(box)
    assert box["deploy"].read_text(encoding="utf-8").startswith("a file where")


def test_a_public_key_that_appears_meanwhile_is_never_overwritten(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = bkc.read_paper

    def and_a_key_appears(text: str) -> bytes:
        box["pub"].parent.mkdir(parents=True)
        box["pub"].write_text("another public key (synthetic)\n", encoding="utf-8")
        return real(text)

    monkeypatch.setattr(bkc, "read_paper", and_a_key_appears)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.PUB_FAILED["en"].format(path=box["pub"]) in out
    assert box["pub"].read_text(encoding="utf-8") == "another public key (synthetic)\n"  # not removed: not ours
    assert sorted(p.name for p in box["pub"].parent.iterdir()) == ["backup.pub"]  # the temporary file is removed
    assert not list(box["stick"].iterdir()) and _events(box) == []


@pytest.mark.parametrize(("fault", "text"), [(KeyboardInterrupt, bkc.INTERRUPTED), (RuntimeError, bkc.UNEXPECTED)])
def test_an_interruption_or_an_unexpected_error_keeps_nothing(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    fault: type[BaseException], text: dict[str, str],
) -> None:  # fmt: skip
    def stop(text: str) -> bytes:
        raise fault()

    monkeypatch.setattr(bkc, "read_paper", stop)
    rc, out = _main(box, capsys)
    assert rc == 1 and text["en"].format(kind=fault.__name__) in out
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    assert "Traceback" not in out
    _nothing_kept(box)


def test_a_removal_that_fails_is_named_with_its_path(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                                     monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    key_file = box["stick"] / bkc.KEY_FILE
    real_unlink = os.unlink

    def unlink(path: Any, *, dir_fd: int | None = None) -> None:
        if str(path) == bkc.KEY_FILE and dir_fd is not None and _fd_path(dir_fd) == str(box["stick"]):
            raise PermissionError(errno.EROFS, "Read-only file system")
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(bkc, "read_paper", lambda text: b"\x01" * 32)
    monkeypatch.setattr(os, "unlink", unlink)
    rc, out = _main(box, capsys)
    monkeypatch.undo()
    assert rc == 1 and bkc.READ_BACK["en"] in out
    assert bkc.LEFT["en"].format(files=key_file) in out
    assert bkc.REMOVED_SOME["en"].format(files=box["stick"] / bkc.PAPER_FILE) in out
    assert "nothing of the key is kept" not in out
    assert key_file.exists() and not (box["stick"] / bkc.PAPER_FILE).exists()
    assert not box["pub"].exists() and _events(box) == []
    key_file.unlink()


def test_a_refusal_before_anything_is_written_says_so(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    def boom(*a: Any, **k: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(bkc, "writable", boom)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.INTERRUPTED["en"] in out and bkc.KEPT_NOTHING["en"] in out
    _nothing_kept(box)


def test_a_failed_read_back_keeps_nothing(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                          monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(bkc, "read_paper", lambda text: b"\x01" * 32)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.READ_BACK["en"] in out
    _nothing_kept(box)


def test_a_second_run_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = _main(box, capsys)
    assert rc == 0, out
    pub_before = box["pub"].read_bytes()
    fp = bk.fingerprint(bk.load_public(box["pub"]).public_bytes_raw())
    second = box["stick"] / "second"
    second.mkdir()
    rc, out = _main(box, capsys, stick=second)
    assert rc == 1 and bkc.ALREADY["en"].format(fp=fp) in out
    assert bkc.NO_CEREMONY_FOR_KEY["en"] not in out  # the audit holds this key's ceremony
    assert not list(second.iterdir()) and box["pub"].read_bytes() == pub_before and len(_events(box)) == 1


def test_a_second_run_is_refused_by_the_audit_when_the_public_key_is_gone(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """``backup.pub`` is a file root can delete; the audit's event is what says the ceremony was run."""
    rc, out = _main(box, capsys)
    assert rc == 0, out
    (ev,) = _events(box)
    box["pub"].unlink()
    second = box["stick"] / "second"
    second.mkdir()
    rc, out = _main(box, capsys, stick=second)
    assert rc == 1
    assert bkc.AUDITED_ALREADY["en"].format(at=ev["ts"], fp=ev["detail"]["fingerprint"]) in out
    assert bkc.AUDITED_NO_KEY["en"].format(fp=ev["detail"]["fingerprint"]) in out  # how to go on: RUNBOOK §25
    assert not list(second.iterdir()) and not box["pub"].exists() and len(_events(box)) == 1
    # another site's ceremony in the same folder is not this site's
    assert bkc.earlier_ceremony(box["audit"], "another-site") is None
    assert bkc.earlier_ceremony(box["audit"], "synthetic-site") is not None


def test_a_stick_holding_a_key_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    (box["stick"] / bkc.KEY_FILE).write_text("an older key file (synthetic)\n", encoding="utf-8")
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.STICK_HAS_KEY["en"].format(name=bkc.KEY_FILE) in out
    assert (box["stick"] / bkc.KEY_FILE).read_text(encoding="utf-8") == "an older key file (synthetic)\n"
    assert not box["pub"].exists() and _events(box) == []


@pytest.mark.parametrize("name", [bkc.KEY_FILE, bkc.PAPER_FILE])
def test_a_link_of_either_name_on_the_stick_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                                       name: str) -> None:  # fmt: skip
    target = box["tmp"] / "on-the-box-disk.txt"
    (box["stick"] / name).symlink_to(target)  # dangling
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.STICK_HAS_KEY["en"].format(name=name) in out
    assert not target.exists() and (box["stick"] / name).is_symlink()
    assert [p.name for p in box["stick"].iterdir()] == [name]
    assert not box["pub"].exists() and _events(box) == []


# ------------------------------------------------------------------------------------------------ review of a1ed9c36


def test_an_unmount_after_the_media_check_never_writes_the_key_to_the_disk_below(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """H1: the stick is checked as removable, then unmounted at once: the mount point's folder on the box's disk is
    at the path again. The key files go to the folder that was checked (held open since before the check), never to
    the folder on the box's disk now at the path."""
    taken = box["tmp"] / "the-stick-unmounted"
    accepted = key_escrow.media_problem  # the fixture's check: accepts the stick

    def check_then_unmount(out: Path, sec: Path) -> str | None:
        why = accepted(out, sec)
        if why is None and box["stick"].is_dir() and not taken.exists():
            os.replace(box["stick"], taken)  # the stick's filesystem leaves the path
            box["stick"].mkdir()  # and the mount point's own folder, on the box's disk, is at the path again
        return why

    monkeypatch.setattr(key_escrow, "media_problem", check_then_unmount)
    rc, out = _main(box, capsys)
    assert not list(box["stick"].iterdir()), out  # nothing of the key on the box's disk
    assert rc == 0, out
    assert sorted(p.name for p in taken.iterdir()) == sorted([bkc.KEY_FILE, bkc.PAPER_FILE])
    assert bk.load_private(taken / bkc.KEY_FILE).public_key().public_bytes_raw() == bk.load_public(
        box["pub"]).public_bytes_raw()  # fmt: skip


def _fat_mode(monkeypatch: pytest.MonkeyPatch, stick: Path, mode: int = 0o644, uid: int | None = None) -> None:
    """``os.fstat`` of a file on the stick says ``mode`` (and ``uid``), as a FAT stick mounted with ``fmask=0133``
    shows every file whatever mode was asked for."""
    real = os.fstat

    def fstat(fd: int) -> os.stat_result:
        st = real(fd)
        if stat.S_ISREG(st.st_mode) and _fd_path(fd).startswith(str(stick) + "/"):
            vals = list(st)[:10]
            vals[0] = stat.S_IFREG | mode
            if uid is not None:
                vals[4] = uid
            return os.stat_result(vals)
        return st

    monkeypatch.setattr(os, "fstat", fstat)


@pytest.mark.parametrize(("mode", "uid"), [(0o644, None), (0o600, 1000)])
def test_a_stick_that_does_not_keep_the_key_private_is_refused_before_it_is_written(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, mode: int,
    uid: int | None,
) -> None:  # fmt: skip
    """H2: mode 0600 is asked for, but the stick's filesystem shows the file readable by others (a FAT stick mounted
    with a wide mask) or owned by another user: refused before a byte of the key is written, saying how IT mounts
    the stick (``uid=0,gid=0,umask=077``)."""
    _fat_mode(monkeypatch, box["stick"], mode, uid)
    rc, out = _main(box, capsys)
    assert rc == 1, out
    assert bkc.STICK_NOT_PRIVATE["en"].format(path=box["stick"]) in out and "umask=077" in out
    assert "Traceback" not in out
    _nothing_kept(box)


def test_a_file_that_turns_readable_after_it_is_made_is_refused_and_removed(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """H2, at the key file itself: the probe kept 0600 but the key file does not: refused before the key is
    written to it, and the empty file is removed."""
    calls = {"n": 0}
    real_fstat = os.fstat

    def fstat(fd: int) -> os.stat_result:
        st = real_fstat(fd)
        if stat.S_ISREG(st.st_mode) and _fd_path(fd) == str(box["stick"] / bkc.KEY_FILE):
            calls["n"] += 1
            vals = list(st)[:10]
            vals[0] = stat.S_IFREG | 0o644
            return os.stat_result(vals)
        return st

    monkeypatch.setattr(os, "fstat", fstat)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.STICK_NOT_PRIVATE["en"].format(path=box["stick"]) in out, out
    assert calls["n"] >= 1
    _removed_all(out, box["stick"] / bkc.KEY_FILE)
    _nothing_kept(box)


def _drops(b: dict[str, Path]) -> list[tuple[int, int]]:
    """Each identity a child was asked to drop to, in order (:func:`_drop_seam`)."""
    if not b["drops"].exists():
        return []
    return [(int(u), int(g)) for u, g in (ln.split(":") for ln in b["drops"].read_text().splitlines())]


def _earlier_day(b: dict[str, Path]) -> None:
    """A chain of an earlier day in the audit folder, the writer's own files (0640)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tb_audit.AuditLog(b["audit"], tz="Asia/Tokyo").append(
        "x.synthetic", actor="test", ts=datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Tokyo")))  # fmt: skip
    for p in b["audit"].iterdir():
        if os.geteuid() == 0:
            os.chown(p, *WRITER)
        p.chmod(0o640)


@pytest.mark.parametrize("fresh", [True, False])
def test_what_the_ceremony_writes_in_the_audit_folder_stays_the_writers(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], fresh: bool
) -> None:
    """H3, after the review of f68e5988 (item 1): root never writes in the audit folder. The append runs in a child
    that is asked to drop to the folder's owner (as root, really: uid 65534), so every file in the folder (the lock,
    the day file, the head anchor) is the writer's own, made by it; none is root's, and nothing needs giving back."""
    if not fresh:
        _earlier_day(box)
    rc, out = _main(box, capsys)
    assert rc == 0, out
    assert _drops(box) == [WRITER]  # one append, by the folder's owner
    files = sorted(box["audit"].iterdir())
    assert {p.name for p in files} >= {".lock", "HEAD.json"}
    for p in files:
        st = os.lstat(p)
        assert stat.S_ISREG(st.st_mode) and (st.st_uid, st.st_gid) == WRITER, (p, st.st_uid, st.st_gid)
    assert bkc.AUDIT_OWNER_LEFT["en"].split("{files}")[0] not in out


def test_a_file_of_roots_in_the_audit_folder_after_the_event_is_said(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """H3, now a check that reads only: a file of root's found in the writer's folder after the event (here: the
    listing shows ``.lock`` as root's) is named, with the folder's owner, after the closing text; exit 2. Nothing is
    changed through it."""
    real = bkc._audit_files

    def audit_files(audit_dir: Path, dir_fd: int | None = None) -> dict[str, Any]:
        got = real(audit_dir, dir_fd)
        return {n: dataclasses.replace(f, uid=0) if n == ".lock" else f for n, f in got.items()}

    monkeypatch.setattr(bkc, "_audit_files", audit_files)
    rc, out = _main(box, capsys)
    assert rc == bkc.KEPT_EXIT, out
    owner = f"{WRITER[0]}:{WRITER[1]}"
    assert bkc.AUDIT_OWNER_LEFT["en"].format(files=box["audit"] / ".lock", owner=owner, audit=box["audit"]) in out
    assert os.lstat(box["audit"] / ".lock").st_uid == WRITER[0]  # nothing was changed
    assert len(_events(box)) == 1 and box["pub"].exists()


def test_the_public_key_is_visible_only_after_the_audit_line_is_on_disk(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """H4: what a concurrent ``trialbox backup`` would find (``load_public`` of ``backup.pub``) while the ceremony
    appends its event: nothing; so a failing append, whose undo removes the private copies, leaves no backup made to
    that key. The append runs in the child (as root, as uid 65534, which cannot walk the test's folder by path): it
    looks through a folder and writes to a file opened before the run."""
    seen = box["tmp"] / "seen.txt"
    seen.write_text("", encoding="utf-8")
    out_fd = os.open(seen, os.O_WRONLY | os.O_APPEND)
    dep_fd = os.open(box["deploy"], os.O_RDONLY | os.O_DIRECTORY)
    real = tb_audit.AuditLog.append

    def append(self: tb_audit.AuditLog, event: str, **kw: Any) -> dict[str, Any]:
        try:
            os.stat("secrets/backup.pub", dir_fd=dep_fd, follow_symlinks=False)
            there = True
        except FileNotFoundError:
            there = False
        os.write(out_fd, f"{event} {there}\n".encode())
        return real(self, event, **kw)

    monkeypatch.setattr(tb_audit.AuditLog, "append", append)
    try:
        rc, out = _main(box, capsys)
    finally:
        os.close(out_fd)
        os.close(dep_fd)
    assert seen.read_text(encoding="utf-8").splitlines() == [f"{bkc.EVENT} False"]
    assert rc == 0, out


def test_a_public_key_name_taken_after_the_audit_writes_the_undoing_and_frees_a_rerun(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """H4, the other hole: the audit line is on disk, then ``backup.pub`` cannot be linked (another file took the
    name). The public key never became visible, so the ceremony writes ``backup.key_ceremony_undone`` (this
    fingerprint) and then undoes; the once-only check counts that pair as not done."""

    def link(src: Any, dst: Any) -> None:
        Path(dst).write_text("another public key (synthetic)\n", encoding="utf-8")
        raise FileExistsError(errno.EEXIST, "File exists", str(dst))

    monkeypatch.setattr(os, "link", link)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.PUB_FAILED["en"].format(path=box["pub"]) in out, out
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    (ev,) = _events(box)
    rows = [json.loads(x) for f in box["audit"].rglob("*.jsonl") for x in f.read_text().splitlines()]
    (undone,) = [r for r in rows if r["event"] == bkc.UNDONE_EVENT]
    assert undone["detail"]["fingerprint"] == ev["detail"]["fingerprint"]
    assert box["pub"].read_text(encoding="utf-8") == "another public key (synthetic)\n"  # not ours: left
    assert not list(box["stick"].iterdir())
    assert bkc.earlier_ceremony(box["audit"], "synthetic-site") is None
    box["pub"].unlink()
    monkeypatch.undo()
    _again(monkeypatch, box)
    rc, out = _main(box, capsys)
    assert rc == 0, out
    assert len(_events(box)) == 2


def test_a_removal_whose_folder_sync_fails_is_not_said_durable(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """H5: the undo unlinks both stick files, then the stick's folder sync fails (EIO): the removal may come back
    after a power loss, so the refusal names the files and the folder and never says nothing of the key is kept."""
    key_file, paper = box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE
    _fail_fsync(monkeypatch, lambda path: path == str(box["stick"]) and not os.path.lexists(key_file))
    monkeypatch.setattr(bkc, "read_paper", lambda text: b"\x01" * 32)  # the read-back fails: undo
    rc, out = _main(box, capsys)
    assert rc == 1, out
    assert "nothing of the key is kept" not in out, out
    assert bkc.REMOVED_NOT_DURABLE["en"].format(files=f"{paper}, {key_file}", folder=box["stick"]) in out
    assert not os.path.lexists(key_file) and not os.path.lexists(paper)


# ------------------------------------------------------------------------------------------------ review of c2fcb044


def _ceremony_events(b: dict[str, Path]) -> list[str]:
    return [json.loads(x)["event"] for f in b["audit"].rglob("*.jsonl") for x in f.read_text().splitlines()]


def test_an_interruption_in_the_check_after_the_event_writes_the_undoing(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 2 of c2fcb044, now at the read-only check after the append: Ctrl-C there, once the event's line is on
    disk: the run is not said as an audit failure; ``backup.key_ceremony_undone`` is written before the undo, and a
    rerun is allowed."""
    real, calls = bkc._root_left, {"n": 0}

    def root_left(*a: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt
        return real(*a)

    monkeypatch.setattr(bkc, "_root_left", root_left)
    rc, out = _main(box, capsys)
    assert rc == 1, out
    assert bkc.INTERRUPTED["en"] in out and bkc.AUDIT_FAILED["en"].split("{path}")[0] not in out, out
    assert _ceremony_events(box) == [bkc.EVENT, bkc.UNDONE_EVENT]
    assert bkc.AUDIT_HOLDS["en"].split("{fp}")[0] not in out
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    assert not list(box["stick"].iterdir()) and not os.path.lexists(box["pub"])
    assert bkc.earlier_ceremony(box["audit"], "synthetic-site") is None


def test_a_listing_of_the_audit_folder_that_fails_after_the_event_is_not_an_audit_failure(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The writer's audit folder cannot be listed for the check after the append (OSError): the event is on disk, so
    the key is kept and put in place, and the folder is named as not checked: exit 2."""

    def audit_files(*a: Any) -> Any:
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(bkc, "_audit_files", audit_files)
    rc, out = _main(box, capsys)
    assert rc == bkc.KEPT_EXIT, out
    assert bkc.AUDIT_FAILED["en"].split("{path}")[0] not in out, out
    owner = f"{WRITER[0]}:{WRITER[1]}"
    assert bkc.AUDIT_NOT_LISTED["en"].format(audit=box["audit"], owner=owner) in out
    assert _ceremony_events(box) == [bkc.EVENT]
    assert box["pub"].exists() and sorted(p.name for p in box["stick"].iterdir()) == sorted([bkc.KEY_FILE,
                                                                                           bkc.PAPER_FILE])  # fmt: skip


# ------------------------------------------------------------------------------------------------ review of f68e5988


def _victim(b: dict[str, Path]) -> Path:
    """A file outside the audit folder that the audit writer may not write: as root, root's own 0600 file in the
    test's folder (which uid 65534 cannot even walk); as another user, its own file made 0400."""
    victim = b["tmp"] / "elsewhere" / "victim"
    victim.parent.mkdir()
    victim.write_text("synthetic\n", encoding="utf-8")
    victim.chmod(0o600 if os.geteuid() == 0 else 0o400)
    return victim


@pytest.mark.parametrize("name", [".HEAD.json.tmp", ".lock"])
def test_a_link_planted_by_the_audit_writer_is_never_followed_with_roots_power(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """Item 1, the blocker: the audit writer owns the folder and plants ``.HEAD.json.tmp`` or ``.lock`` beforehand as
    a symlink to a file outside it (no race needed). The append runs as the folder's owner, so the link is followed
    with the owner's power only: the file outside stays as it was (as root this is a real uid 65534 and a root file;
    as another user, a file that user may not write). ``.lock``: the append fails before a line, so the ceremony is
    undone and nothing is kept. ``.HEAD.json.tmp``: the event's line is synced, its head anchor cannot be written, so
    the key is kept with the warning that says exactly that (exit 2), and ``HEAD.json`` is never made the link."""
    victim = _victim(box)
    before = (victim.read_bytes(), os.stat(victim))
    os.symlink(victim, box["audit"] / name)
    if os.geteuid() == 0:
        os.lchown(box["audit"] / name, *WRITER)
    rc, out = _main(box, capsys)
    after = os.stat(victim)
    assert victim.read_bytes() == before[0]
    assert (after.st_mode, after.st_uid, after.st_gid, after.st_size) == (
        before[1].st_mode, before[1].st_uid, before[1].st_gid, before[1].st_size)  # fmt: skip
    assert _drops(box) == [WRITER]
    assert not (box["audit"] / "HEAD.json").is_symlink()
    if name == ".lock":
        assert rc == 1 and bkc.AUDIT_FAILED["en"].format(path=box["audit"]) in out, out
        assert bkc.AUDIT_MAY_HOLD["en"].split("{fp}")[0] not in out
        _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
        _nothing_kept(box)
    else:
        assert rc == bkc.KEPT_EXIT, out
        (ev,) = _events(box)
        fp = ev["detail"]["fingerprint"]
        assert bkc.KEPT_WARNING["en"].format(fp=fp, key=bkc.KEY_FILE, paper=bkc.PAPER_FILE, pub=box["pub"],
                                             event=bkc.EVENT, audit=box["audit"]) in out  # fmt: skip
    for p in box["audit"].iterdir():  # nothing in the folder is root's
        assert os.lstat(p).st_uid == WRITER[0], p


def test_a_failed_drop_refuses_before_anything_is_written_to_the_audit(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 1: the child cannot take the folder owner's identity: it writes nothing to the audit (no lock, no day
    file, no head anchor), the ceremony is undone and the refusal says why, naming the owner; nothing is kept."""

    def drop(uid: int, gid: int) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(bkc, "_drop_to", drop)
    rc, out = _main(box, capsys)
    assert rc == 1, out
    owner = f"{WRITER[0]}:{WRITER[1]}"
    assert bkc.AUDIT_DROP_FAILED["en"].format(path=box["audit"], owner=owner) in out
    assert bkc.AUDIT_MAY_HOLD["en"].split("{fp}")[0] not in out
    assert not list(box["audit"].iterdir())
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    _nothing_kept(box)


def test_the_drop_is_real_and_checked(tmp_path: Path) -> None:
    """Item 1, the real ``_drop_to`` in a real child (no seam): as root, the child becomes uid 65534 for good (real,
    effective and saved), with no supplementary group, cannot become root again, and is not dumpable; as any other
    user, dropping supplementary groups is refused, so the child says ``drop-failed`` and runs nothing."""
    import ctypes

    folder = tmp_path / "audit"
    folder.mkdir()
    if os.geteuid() == 0:
        os.chown(folder, 65534, 65534)

    def write() -> tuple[str, bool]:
        try:
            os.setuid(0)
            return "unknown", False  # root again: the drop did not hold
        except PermissionError:
            pass
        held = os.getresuid() == (65534,) * 3 and os.getresgid() == (65534,) * 3 and not os.getgroups()
        dumpable = ctypes.CDLL(None).prctl(3, 0, 0, 0, 0)
        here = os.stat(".").st_ino == ino  # the folder held open
        return ("ok" if held and dumpable == 0 and here else "unknown"), False

    ino = os.stat(folder).st_ino
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        word, interrupted = bkc._as_owner(fd, 65534, 65534, write)
    finally:
        os.close(fd)
    assert not interrupted
    assert word == ("ok" if os.geteuid() == 0 else "drop-failed")


@pytest.mark.parametrize("how", ["raises", "interrupt", "exits", "drop fails", "hangs", "never returns"])
def test_the_child_cannot_outlive_the_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str) -> None:
    """Whatever happens in the child (an exception, Ctrl-C, ``sys.exit``, a failed drop, a hang, or code that would
    go on running the caller's program), it ends with ``os._exit`` or is killed, and it is reaped before the call
    returns: no process of it is left (an orphan would go on running the test session). The child notes its pid in a
    file opened before the call."""
    import time

    folder = tmp_path / "audit"
    folder.mkdir()
    pids = tmp_path / "pids"
    pids.write_text("", encoding="utf-8")
    pfd = os.open(pids, os.O_WRONLY | os.O_APPEND)
    monkeypatch.setattr(bkc, "_drop_to", lambda uid, gid: None)
    monkeypatch.setattr(bkc, "CHILD_LIMIT", 2.0)
    if how == "drop fails":

        def bad_drop(uid: int, gid: int) -> None:
            os.write(pfd, f"{os.getpid()}\n".encode())
            raise PermissionError(errno.EPERM, "Operation not permitted")

        monkeypatch.setattr(bkc, "_drop_to", bad_drop)

    def write() -> tuple[str, bool]:
        os.write(pfd, f"{os.getpid()}\n".encode())
        if how == "raises":
            raise RuntimeError("synthetic")
        if how == "interrupt":
            raise KeyboardInterrupt
        if how == "exits":
            sys.exit(3)
        if how == "hangs":
            time.sleep(60)
        if how == "never returns":  # as if the child ran on: it would hold the pipe until killed
            while True:
                time.sleep(0.05)
        return "ok", False

    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    began = time.monotonic()
    try:
        word, interrupted = bkc._as_owner(fd, os.geteuid(), os.getegid(), write)
    finally:
        os.close(fd)
        os.close(pfd)
    took = time.monotonic() - began
    assert not interrupted
    assert word == ("drop-failed" if how == "drop fails" else "unknown"), word
    (child,) = [int(x) for x in pids.read_text(encoding="utf-8").split()]
    assert child != os.getpid()
    assert not os.path.exists(f"/proc/{child}"), "the child outlived the call"
    assert took < (10.0 if how in ("hangs", "never returns") else 2.0), took


def test_garbage_of_the_caller_is_freed_by_the_caller_never_in_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The k-suite run of the first fix hung: the child freed a compressor copied from the test process whose worker
    threads are not in the child, and waited for them for ever. Now cyclic garbage is collected in the caller before
    the fork, and the collector is off in the child: a cycle left by the caller is freed in the caller (its pid
    noted), and the child sees the collector off."""
    import gc

    folder = tmp_path / "audit"
    folder.mkdir()
    freed = tmp_path / "freed"
    freed.write_text("", encoding="utf-8")
    ffd = os.open(freed, os.O_WRONLY | os.O_APPEND)

    class Cycle:
        def __init__(self) -> None:
            self.me = self

        def __del__(self) -> None:
            os.write(ffd, f"{os.getpid()}\n".encode())

    monkeypatch.setattr(bkc, "_drop_to", lambda uid, gid: None)
    was = gc.isenabled()
    gc.disable()  # the cycle stays until the call collects it
    try:
        Cycle()
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            word, _ = bkc._as_owner(fd, os.geteuid(), os.getegid(), lambda: ("ok" if not gc.isenabled() else "unknown",
                                                                              False))  # fmt: skip
        finally:
            os.close(fd)
    finally:
        os.close(ffd)
        if was:
            gc.enable()
    assert word == "ok"
    assert freed.read_text(encoding="utf-8").split() == [str(os.getpid())]


def test_an_audit_folder_that_is_a_link_is_refused_before_anything_is_written(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 3: the audit folder is opened with ``O_NOFOLLOW``: a folder named by a link is refused first."""
    real = box["tmp"] / "real-audit"
    box["audit"].rename(real)
    box["audit"].symlink_to(real)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.AUDIT_FOLDER_UNSAFE["en"].format(path=box["audit"]) in out, out
    assert not list(box["stick"].iterdir()) and not os.path.lexists(box["pub"]) and not list(real.iterdir())


def _roots_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    """The audit folder reads as root's (the owner seam), as on a box where the audit runs as root."""
    monkeypatch.setattr(bkc, "_folder_owner", lambda fd: (0, 0))


def test_an_audit_folder_of_roots_is_appended_to_in_this_process(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 1, a box whose audit folder is root's: no child, no drop; the append runs here, after the entries were
    checked, and the run ends as before."""
    _roots_folder(monkeypatch)
    _earlier_day(box)
    rc, out = _main(box, capsys)
    assert rc == 0, out
    assert _drops(box) == [] and len(_events(box)) == 1


@pytest.mark.parametrize("plant", ["symlink", "second name", "fifo", "group-writable folder"])
def test_an_audit_folder_of_roots_with_an_entry_that_is_not_a_plain_file_is_refused(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, plant: str
) -> None:
    """Item 1, a folder of root's: before root writes in it, every entry, looked at through the folder held open,
    must be a plain file with one name; a link (to a file outside), a file with a second name or a special file is
    refused before anything is written, naming it; so is a folder of root's its group or others may write."""
    _roots_folder(monkeypatch)
    victim = _victim(box)
    before = victim.read_bytes()
    a = box["audit"]
    if plant == "symlink":
        os.symlink(victim, a / ".HEAD.json.tmp")
        text, path = bkc.AUDIT_ENTRY_UNSAFE, a / ".HEAD.json.tmp"
    elif plant == "second name":
        (a / ".lock").write_text("", encoding="utf-8")
        os.link(a / ".lock", box["tmp"] / "elsewhere" / "second-name")
        text, path = bkc.AUDIT_ENTRY_UNSAFE, a / ".lock"
    elif plant == "fifo":
        os.mkfifo(a / ".lock")
        text, path = bkc.AUDIT_ENTRY_UNSAFE, a / ".lock"
    else:
        a.chmod(0o775)
        text, path = bkc.AUDIT_FOLDER_UNSAFE, a
    rc, out = _main(box, capsys)
    assert rc == 1 and text["en"].format(path=path) in out, out
    assert victim.read_bytes() == before
    assert not list(box["stick"].iterdir()) and not os.path.lexists(box["pub"]) and _events(box) == []


def test_a_link_planted_in_a_folder_of_roots_after_the_check_is_refused_at_the_append(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 1, a folder of root's: the entries are checked again right before the append, so a link planted after
    the first check is refused there; the ceremony is undone and the file outside is untouched."""
    _roots_folder(monkeypatch)
    victim = _victim(box)
    before = victim.read_bytes()
    real = bkc.check

    def check_then_plant(*a: Any, **k: Any) -> Any:
        got = real(*a, **k)
        os.symlink(victim, box["audit"] / ".HEAD.json.tmp")
        return got

    monkeypatch.setattr(bkc, "check", check_then_plant)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.AUDIT_ENTRY_UNSAFE["en"].format(path=box["audit"] / ".HEAD.json.tmp") in out, out
    assert victim.read_bytes() == before
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    _nothing_kept(box)


@pytest.mark.parametrize("where", ["_after_event", "_pub_state", "undo.run"])
def test_a_second_interruption_while_stopping_says_only_what_is_known(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """Item 2: Ctrl-C before ``os.link`` ran (the event is on disk), then a second Ctrl-C while that is handled: in
    ``_after_event``, in ``_pub_state``, or in the undo. The outermost handler says what is known (the event written;
    its undoing written or not, and so whether a rerun is allowed; the files that may remain, with their paths),
    exit 2, and never that nothing had been written."""

    def link(src: Any, dst: Any) -> None:
        raise KeyboardInterrupt

    def again(*a: Any, **k: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", link)
    if where == "undo.run":
        monkeypatch.setattr(bkc._Undo, "run", again)
    else:
        monkeypatch.setattr(bkc, where, again)
    rc, out = _main(box, capsys)
    assert rc == bkc.KEPT_EXIT, out
    assert bkc.KEPT_NOTHING["en"] not in out and "Traceback" not in out
    assert bkc.INTERRUPTED_LATE["en"] in out
    (ev,) = _events(box)
    fp = ev["detail"]["fingerprint"]
    if where == "undo.run":  # the undoing was written before the undo
        assert _ceremony_events(box) == [bkc.EVENT, bkc.UNDONE_EVENT]
        assert bkc.UNDONE_WRITTEN["en"].format(fp=fp) in out
        assert bkc.earlier_ceremony(box["audit"], "synthetic-site") is None
    else:
        assert _ceremony_events(box) == [bkc.EVENT]
        assert bkc.AUDIT_HOLDS["en"].format(fp=fp) in out
    said = bkc.MAY_REMAIN["en"].split("{files}")[0]
    assert said in out
    for p in (box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE, box["pub"].parent / ".backup.pub."):
        assert str(p) in out, (p, out)
    for form in _secret_forms(box["stick"]):
        assert form not in out


def test_an_undoing_synced_then_interrupted_frees_a_rerun_and_says_so(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 3: the link is refused after the event; the undoing's line is synced and then Ctrl-C lands in its head
    anchor's write: the undoing is on disk, so the rerun is allowed, and the refusal never says that the undoing could
    not be written or that a rerun is refused; a rerun then succeeds."""
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        path = _fd_path(fd)
        if path.endswith("/.HEAD.json.tmp"):
            days = sorted(Path(".").glob("*.jsonl"))  # the child works in the audit folder
            if days and bkc.UNDONE_EVENT in days[-1].read_text(encoding="utf-8").splitlines()[-1]:
                raise KeyboardInterrupt
        real_fsync(fd)

    def link(src: Any, dst: Any) -> None:
        raise FileExistsError(errno.EEXIST, "File exists", str(dst))

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "link", link)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.PUB_FAILED["en"].format(path=box["pub"]) in out, out
    assert _ceremony_events(box) == [bkc.EVENT, bkc.UNDONE_EVENT]
    assert bkc.AUDIT_HOLDS["en"].split("{fp}")[0] not in out and bkc.UNDONE_UNKNOWN["en"].split("{fp}")[0] not in out
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    assert bkc.earlier_ceremony(box["audit"], "synthetic-site") is None
    monkeypatch.undo()
    _again(monkeypatch, box)
    rc, out = _main(box, capsys)
    assert rc == 0, out


def test_the_kept_warning_says_how_to_compare_the_key_at_backup_pub() -> None:
    """Item 3: the warning for a ``backup.pub`` that may not be ours names the command that prints its fingerprint
    (this one, refused before it writes anything) and what to do when it differs (RUNBOOK §25), in each language."""
    for lg in bkc.LANGS:
        t = bkc.PUB_KEPT_WARNING[lg]
        assert "python -m tools.backup_key_ceremony" in t and "RUNBOOK §25" in t and "{fp}" in t and "{pub}" in t


def test_an_interruption_before_the_link_ran_writes_the_undoing_and_frees_a_rerun(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 3: Ctrl-C after the audit and before ``os.link`` ran: ``backup.pub`` is not there (decided by looking,
    not by where the code was), so the public key was never visible: the undoing is written, everything is removed,
    nothing says to check ``backup.pub``, and the ceremony can be run again."""

    def link(src: Any, dst: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "link", link)
    rc, out = _main(box, capsys)
    assert rc == 1, out
    assert bkc.INTERRUPTED["en"] in out and "Check that" not in out, out
    assert _ceremony_events(box) == [bkc.EVENT, bkc.UNDONE_EVENT]
    _removed_all(out, box["stick"] / bkc.KEY_FILE, box["stick"] / bkc.PAPER_FILE)
    assert not list(box["stick"].iterdir()) and not list(box["deploy"].rglob("*"))
    assert bkc.earlier_ceremony(box["audit"], "synthetic-site") is None


def test_a_public_key_linked_whose_folder_sync_fails_is_kept_and_said_in_place(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 3: ``backup.pub`` is linked, then its folder's sync fails: it is ours (same inode), so it was visible:
    everything is kept and the warning says the public key is in place, exit 2."""
    _fail_fsync(monkeypatch, lambda path: path == str(box["pub"].parent) and os.path.lexists(box["pub"]))
    rc, out = _main(box, capsys)
    assert rc == bkc.KEPT_EXIT, out
    (ev,) = _events(box)
    fp = ev["detail"]["fingerprint"]
    assert bkc.PUB_LINKED_WARNING["en"].format(fp=fp, key=bkc.KEY_FILE, paper=bkc.PAPER_FILE, pub=box["pub"],
                                               event=bkc.EVENT, audit=box["audit"]) in out  # fmt: skip
    assert bk.fingerprint(bk.load_public(box["pub"]).public_bytes_raw()) == fp
    assert sorted(p.name for p in box["pub"].parent.iterdir()) == ["backup.pub"]


def test_a_probe_shown_readable_whose_removal_fails_is_still_said_not_private(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 4: the probe shows group or other bits and then cannot be removed: the refusal is that the stick does
    not keep files private, not that it cannot be written."""
    _fat_mode(monkeypatch, box["stick"], 0o644)
    real = os.unlink

    def unlink(path: Any, *, dir_fd: int | None = None) -> None:
        if str(path).startswith(".tb-probe-"):
            raise PermissionError(errno.EPERM, "Operation not permitted")
        real(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", unlink)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.STICK_NOT_PRIVATE["en"].format(path=box["stick"]) in out, out


def test_the_not_private_text_says_what_is_checked() -> None:
    """Item 4: the check takes any mode with no bit for the group or others (0700 on a FAT stick mounted with
    ``umask=077``), so no text says the file must be mode 0600."""
    for lg in bkc.LANGS:
        assert "0600" not in bkc.STICK_NOT_PRIVATE[lg], lg


def test_two_runs_on_one_stick_the_second_is_told_a_file_is_there(
    box: dict[str, Path], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 4: another run makes the key file between this run's checks and its own create (O_EXCL fails): the
    refusal says a file of that name is on the stick, not that the stick is read-only or full, and the other run's
    file is left."""
    real = os.open

    def open_(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if path == bkc.KEY_FILE and flags & os.O_EXCL:
            os.close(real(path, os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=dir_fd))  # the other run's file
        return real(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.STICK_HAS_KEY["en"].format(name=bkc.KEY_FILE) in out, out
    assert bkc.NOT_WRITABLE["en"].split("{path}")[0] not in out
    assert [p.name for p in box["stick"].iterdir()] == [bkc.KEY_FILE] and _events(box) == []


def test_same_person_compares_folded_spellings() -> None:
    assert bkc.folded("Ｔａｒｏ\u3000 Yamada") == bkc.folded("taro yamada") == "taro yamada"
    assert bkc.folded("山田　太郎") == bkc.folded("山田 太郎")
    assert bkc.folded("Yamada Taro") != bkc.folded("Taro Yamada")


# ------------------------------------------------------------------------------------------------ the paper sheet


def _sheet(at: str = "2026-11-19T00:00:00+00:00") -> tuple[bytes, str]:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    sk = X25519PrivateKey.generate()
    raw = sk.private_bytes_raw()
    return raw, bkc.paper_sheet(raw, bk.fingerprint(sk.public_key().public_bytes_raw()), "synthetic-site", at)


def _line(sheet: str, n: int) -> str:
    return next(ln for ln in sheet.splitlines() if ln.startswith(f"{n} | "))


def _slip(sheet: str, n: int) -> str:
    """The sheet with one letter of line ``n`` mistyped."""
    ln = _line(sheet, n)
    i = ln.index("|") + 2
    bad = ln[:i] + ("B" if ln[i] != "B" else "C") + ln[i + 1 :]
    return sheet.replace(ln, bad)


def test_the_paper_sheet_reads_back_typed_loosely() -> None:
    raw, sheet = _sheet()
    assert bkc.read_paper(sheet) == raw
    loose = "\n".join(ln.lower().replace(" | ", "|") if re.match(r"^\d \| ", ln) else ln for ln in sheet.splitlines())
    assert bkc.read_paper(loose) == raw


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_a_damaged_paper_line_is_caught_and_named(n: int) -> None:
    raw, sheet = _sheet()
    with pytest.raises(bkc.PaperError) as e:
        bkc.read_paper(_slip(sheet, n))
    assert e.value.text is bkc.PAPER_CHECK and e.value.fill == {"n": n}
    letters = base64.b32encode(raw).decode().rstrip("=")
    for lg in bkc.LANGS:
        said = e.value.say(lg)
        assert f"{n}" in said
        assert not any(letters[i : i + 4] in said for i in range(0, len(letters), 4))


def test_a_letter_outside_the_alphabet_is_a_damaged_line() -> None:
    _, sheet = _sheet()
    ln = _line(sheet, 2)
    i = ln.index("|") + 2
    with pytest.raises(bkc.PaperError) as e:
        bkc.read_paper(sheet.replace(ln, ln[:i] + "0" + ln[i + 1 :]))
    assert e.value.text is bkc.PAPER_CHECK and e.value.fill == {"n": 2}


def test_a_missing_or_swapped_line_and_a_wrong_fingerprint_are_caught() -> None:
    _, sheet = _sheet()
    l2, l3, l4 = _line(sheet, 2), _line(sheet, 3), _line(sheet, 4)
    with pytest.raises(bkc.PaperError) as e:
        bkc.read_paper(sheet.replace(l2 + "\n", ""))
    assert e.value.text is bkc.PAPER_SHAPE and e.value.fill == {"n": 2}
    with pytest.raises(bkc.PaperError) as e:
        bkc.read_paper(sheet.replace(l2, "@").replace(l3, l2).replace("@", l3))
    assert e.value.text is bkc.PAPER_SHAPE and e.value.fill == {"n": 2}
    with pytest.raises(bkc.PaperError) as e:
        bkc.read_paper(sheet.replace(l4 + "\n", ""))
    assert e.value.text is bkc.PAPER_SHAPE and e.value.fill == {"n": 3}
    fp_line = next(ln for ln in sheet.splitlines() if ln.startswith("fingerprint "))
    other = "fingerprint " + "-".join(["0000"] * 5)
    with pytest.raises(bkc.PaperError) as e:
        bkc.read_paper(sheet.replace(fp_line, other))
    assert e.value.text is bkc.PAPER_FP
    with pytest.raises(bkc.PaperError) as e:
        bkc.read_paper("")
    assert e.value.text is bkc.PAPER_SHAPE


# ------------------------------------------------------------------------------------------------ the words


def test_every_text_is_in_english_japanese_and_chinese() -> None:
    texts = bkc.all_texts()
    names = {n for n, _, _ in texts}
    assert len(names) >= 17
    en = {n: t for n, lg, t in texts if lg == "en"}
    for name, lg, t in texts:
        assert t.strip(), (name, lg)
        if lg != "en":
            assert t != en[name] and not t.isascii(), (name, lg)
    # the placeholders are the same in every language
    for name in names:
        fields = {lg: sorted(re.findall(r"\{(\w+)\}", t)) for n, lg, t in texts if n == name}
        assert len({tuple(v) for v in fields.values()}) == 1, (name, fields)


def test_the_core_words_are_spelled_as_the_catalogues_spell_them() -> None:
    rel = "tools/backup_key_ceremony.py"
    rows = core_words._module_texts(rel, ast.parse((ROOT / rel).read_text(encoding="utf-8")))
    assert len(rows) == 3 * len({r.key for r in rows}) >= 51
    assert [str(r) for r in core_words.refused(rows)] == []


# ------------------------------------------------------------------------------------------------ the command line


def test_the_command_line_refuses_a_folder_that_is_not_a_stick(tmp_path: Path) -> None:
    """As a person types it on the host: a folder of the box's disk is refused (not root: refused first), in
    Japanese, with nothing written."""
    folder, audit, deploy = tmp_path / "usb", tmp_path / "audit", tmp_path / "deploy"
    for d in (folder, audit, deploy, tmp_path / "secrets"):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update(PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")))
    r = subprocess.run([sys.executable, "-m", "tools.backup_key_ceremony", "--stick", str(folder), "--operator", OP,
                        "--witness", WIT, "--deploy", str(deploy), "--secrets", str(tmp_path / "secrets"),
                        "--audit-dir", str(audit), "--lang", "ja"], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=120, check=False)  # fmt: skip
    assert r.returncode == 1, r.stdout + r.stderr
    want = bkc.NOT_ROOT["ja"] if os.geteuid() != 0 else bkc.NOT_A_STICK["ja"].format(path=folder)
    assert want in r.stderr and r.stdout == ""
    assert not list(folder.iterdir()) and not list(deploy.iterdir()) and not list(audit.iterdir())
