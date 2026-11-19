"""10K-13 (D-1379): the backup-key ceremony on the box's host. Hospital IT as root, with a witness who is another
person, makes the backup key pair once; the private key goes to a stick (the ``backup-keygen`` key file) and to a
paper sheet on that stick whose lines carry check letters; the box keeps the public key; the audit names both people
and the key's fingerprint, never the key. The refusals: wrong role, no names or one person twice, no audit folder, a
second run, no stick, a folder on the box's disks, a stick that cannot be written, a stick holding a key, a failed
read-back; and a damaged paper line. Every key is made in the test's tmp folder; outputs are checked for its absence.
"""

from __future__ import annotations

import ast
import base64
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
from tb_common import kek as K

from tools import backup_key_ceremony as bkc
from tools import core_words, key_escrow
from tools.trialbox import backup as bk

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
OP, WIT = "IT Person One", "Witness Two"


@pytest.fixture
def box(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A host as root with a stick the media check accepts, an audit folder and a deploy folder with no key yet."""
    stick, audit, sec, deploy = (tmp_path / n for n in ("usb", "audit", "secrets", "deploy"))
    for d in (stick, audit, sec, deploy):
        d.mkdir()
    real = key_escrow.media_problem
    monkeypatch.setattr(key_escrow, "media_problem", lambda out, s: None if K._inside(out, stick) else real(out, s))
    monkeypatch.setattr(bkc, "is_root", lambda: True)
    return {"tmp": tmp_path, "stick": stick, "audit": audit, "sec": sec, "deploy": deploy,
            "pub": deploy / "secrets" / "backup.pub"}  # fmt: skip


def _main(b: dict[str, Path], capsys: pytest.CaptureFixture[str], *extra: str, stick: Path | None = None,
          names: tuple[str, ...] = ("--operator", OP, "--witness", WIT), lang: str = "en") -> tuple[int, str]:  # fmt: skip
    argv = ["--stick", str(stick or b["stick"]), *names, "--deploy", str(b["deploy"]), "--secrets", str(b["sec"]),
            "--audit-dir", str(b["audit"]), "--lang", lang, *extra]  # fmt: skip
    rc = bkc.main(argv, env={"TB_SITE_ID": "synthetic-site"})
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
    assert not b["pub"].exists()
    assert _events(b) == []


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
    assert {k: ev["detail"][k] for k in ("fingerprint", "operator", "witness", "site", "forms")} == {
        "fingerprint": fp, "operator": OP, "witness": WIT, "site": "synthetic-site", "forms": ["stick", "paper"]}  # fmt: skip
    assert str(box["stick"]) not in json.dumps(ev)
    assert fp in out and OP in out and WIT in out
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
    monkeypatch.setattr(bkc, "writable", lambda folder: False)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NOT_WRITABLE["en"].format(path=box["stick"]) in out
    _nothing_kept(box)


def test_the_write_probe(tmp_path: Path) -> None:
    assert bkc.writable(tmp_path) is True
    assert list(tmp_path.iterdir()) == []  # the probe is removed
    assert bkc.writable(tmp_path / "missing") is False


def test_a_stick_that_fails_while_written_keeps_nothing(box: dict[str, Path], capsys: pytest.CaptureFixture[str],
                                                        monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    real = bkc._write_new

    def full(path: Path, text: str) -> None:
        if path.name == bkc.PAPER_FILE:
            raise OSError(28, "No space left on device")
        real(path, text)

    monkeypatch.setattr(bkc, "_write_new", full)
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.NOT_WRITABLE["en"].format(path=box["stick"]) in out
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
    assert not list(second.iterdir()) and box["pub"].read_bytes() == pub_before and len(_events(box)) == 1


def test_a_stick_holding_a_key_is_refused(box: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    (box["stick"] / bkc.KEY_FILE).write_text("an older key file (synthetic)\n", encoding="utf-8")
    rc, out = _main(box, capsys)
    assert rc == 1 and bkc.STICK_HAS_KEY["en"].format(name=bkc.KEY_FILE) in out
    assert (box["stick"] / bkc.KEY_FILE).read_text(encoding="utf-8") == "an older key file (synthetic)\n"
    assert not box["pub"].exists() and _events(box) == []


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
