"""``trialbox backup`` / ``restore`` (TB-PLAN-04 step 2, D-126): one encrypted file, opened only by the hospital's key."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tb_common.db import Database

from tools.trialbox import backup as bk
from tools.trialbox.__main__ import main as cli


@pytest.fixture
def box(tmp_path: Path, db_url: str) -> dict[str, object]:
    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL, note TEXT)"])
    db.execute("INSERT INTO marks VALUES (?, ?, ?)", ("P1", "approach", "日本語のメモ"))
    db.execute("INSERT INTO marks VALUES (?, ?, ?)", ("P2", "not_now", None))
    other = Database.connect(db_url, "auth")
    other.migrate(["CREATE TABLE users (name TEXT PRIMARY KEY)"])
    other.execute("INSERT INTO users VALUES (?)", ("admin",))
    dirs = {"audit": tmp_path / "audit", "lake": tmp_path / "lake"}
    (dirs["audit"] / "2026").mkdir(parents=True)
    (dirs["audit"] / "2026" / "log.jsonl").write_text('{"e": 1}\n', encoding="utf-8")
    dirs["lake"].mkdir()
    (dirs["lake"] / "patient.parquet").write_bytes(b"PAR1" + bytes(range(256)) * 5000)  # > 1 MiB: several chunks
    priv, pub = tmp_path / "usb" / "backup.key", tmp_path / "box" / "backup.pub"
    fp = bk.keygen(priv, pub)
    return {"db": db, "auth": other, "dirs": dirs, "priv": priv, "pub": pub, "fp": fp, "url": db_url}


def _backup(box: dict[str, object], tmp_path: Path, **kw: object) -> list[Path]:
    return bk.backup(
        [tmp_path / "nas", tmp_path / "usbdisk"],
        box["pub"],  # type: ignore[arg-type]
        env={"TB_DB_URL": str(box["url"]), "TB_SITE_ID": "CGMH"},
        dirs=box["dirs"],  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def test_round_trip_restores_rows_and_files(box: dict[str, object], tmp_path: Path) -> None:
    files = _backup(box, tmp_path)
    assert [f.parent.name for f in files] == ["nas", "usbdisk"] and files[0].read_bytes() == files[1].read_bytes()
    assert files[0].name.startswith("trialbox-CGMH-") and files[0].suffix == ".tbbak"
    raw = files[0].read_bytes()
    assert b"approach" not in raw and "日本語".encode() not in raw and b"PAR1" not in raw  # encrypted
    info = bk.verify(files[0], box["priv"])  # type: ignore[arg-type]
    assert info["ok"] and info["databases"]["trialbox_wf"] == 5  # 3 rows + one _schema_version row per schema
    # the box changes after the backup: a row edited, a row added, a table dropped, a file changed and one added
    db, dirs = box["db"], box["dirs"]
    db.execute("UPDATE marks SET mark = ? WHERE pid = ?", ("withdrawn", "P1"))  # type: ignore[attr-defined]
    db.execute("INSERT INTO marks VALUES (?, ?, ?)", ("P3", "approach", None))  # type: ignore[attr-defined]
    box["auth"].execute("DROP TABLE users")  # type: ignore[attr-defined]
    (dirs["audit"] / "2026" / "log.jsonl").write_text("tampered\n")  # type: ignore[index]
    (dirs["lake"] / "new.parquet").write_bytes(b"x")  # type: ignore[index]
    out = bk.restore(files[1], box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=dirs,  # type: ignore[arg-type]
                     now=datetime(2026, 11, 9, tzinfo=UTC))  # fmt: skip
    assert out["ok"] and out["rows"]["trialbox_wf"] == 5 and out["dirs"] == ["audit", "lake"]
    db2 = Database.connect(str(box["url"]), "site")
    assert db2.fetchall("SELECT pid, mark, note FROM marks ORDER BY pid") == [
        ("P1", "approach", "日本語のメモ"), ("P2", "not_now", None)]  # fmt: skip
    assert Database.connect(str(box["url"]), "auth").fetchall("SELECT name FROM users") == [("admin",)]
    assert (dirs["audit"] / "2026" / "log.jsonl").read_text() == '{"e": 1}\n'  # type: ignore[index]
    assert not (dirs["lake"] / "new.parquet").exists()  # type: ignore[index]
    aside = tmp_path / "lake.pre-restore-20261109T000000Z"
    assert (aside / "new.parquet").exists()  # the replaced data is kept aside, never deleted


def test_tampered_truncated_and_wrong_key_backups_are_refused(box: dict[str, object], tmp_path: Path) -> None:
    f = _backup(box, tmp_path)[0]
    raw = bytearray(f.read_bytes())
    bad = tmp_path / "bad.tbbak"
    bad.write_bytes(raw[:-10])
    with pytest.raises(bk.BackupError, match="cut short"):
        bk.verify(bad, box["priv"])  # type: ignore[arg-type]
    flipped = bytearray(raw)
    flipped[len(raw) // 2] ^= 0x01
    bad.write_bytes(bytes(flipped))
    with pytest.raises(bk.BackupError, match="damaged or was changed"):
        bk.verify(bad, box["priv"])  # type: ignore[arg-type]
    other = tmp_path / "other.key"
    bk.keygen(other, tmp_path / "other.pub")
    with pytest.raises(bk.BackupError, match="made for key"):
        bk.verify(f, other)
    bad.write_bytes(b"not a backup")
    with pytest.raises(bk.BackupError, match="bad magic"):
        bk.verify(bad, box["priv"])  # type: ignore[arg-type]


def test_keys_never_overwritten_and_paper_form_loads(tmp_path: Path) -> None:
    priv, pub = tmp_path / "k.key", tmp_path / "k.pub"
    fp = bk.keygen(priv, pub)
    text = priv.read_text()
    assert f"fingerprint {fp}" in text and oct(priv.stat().st_mode)[-3:] == "600"
    with pytest.raises(bk.BackupError, match="never overwritten"):
        bk.keygen(priv, tmp_path / "k2.pub")
    # typed back from paper in lower case with odd spacing
    body = text.splitlines()[1].lower().replace(" ", "  ")
    retyped = tmp_path / "retyped.key"
    retyped.write_text(body + "\n")
    assert bk.load_private(retyped).public_key().public_bytes_raw() == bk.load_public(pub).public_bytes_raw()


def test_keep_prunes_old_backups_per_target(box: dict[str, object], tmp_path: Path) -> None:
    for day in (1, 2, 3):
        _backup(box, tmp_path, keep=2, now=datetime(2026, 11, day, 2, 0, tzinfo=UTC))
    left = sorted(p.name for p in (tmp_path / "nas").iterdir())
    assert len(left) == 2 and left[0].endswith("20261102T020000Z.tbbak")


def test_cli_refuses_restore_without_yes_and_reports_errors(box: dict[str, object], tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    f = _backup(box, tmp_path)[0]
    assert cli(["restore", str(f), "--key", str(box["priv"])]) == 2
    capsys.readouterr()
    assert cli(["backup-verify", str(f), "--key", str(box["priv"])]) == 0
    assert json.loads(capsys.readouterr().out)["site"] == "CGMH"
    bad = tmp_path / "bad.tbbak"
    bad.write_bytes(b"junk")
    assert cli(["backup-verify", str(bad), "--key", str(box["priv"])]) == 1
    assert "bad magic" in capsys.readouterr().err


def _plain_head(f: Path, key: Path, n: int = 4) -> tuple[dict[str, object], bytes]:
    with f.open("rb") as fh:
        header, _ = bk.read_header(fh)
        fh.seek(0)
        first = next(bk.decrypt_stream(fh, bk.load_private(key)))
    return header, first[:n]


def test_new_backups_are_zstd_and_restore(box: dict[str, object], tmp_path: Path) -> None:
    """D-149 (dataflow review P0-3): the tar inside the encryption is zstd -3, multi-threaded, not gzip -9."""
    f = _backup(box, tmp_path)[0]
    header, magic = _plain_head(f, box["priv"])  # type: ignore[arg-type]
    assert header["compression"] == "zstd" and magic == b"\x28\xb5\x2f\xfd"  # the zstd frame magic
    assert bk.verify(f, box["priv"])["ok"]  # type: ignore[arg-type]
    # the payload compresses like zstd: the repeated 1.2 MiB test pattern shrinks to a few kB
    assert f.stat().st_size < 64_000


def test_an_old_gzip_backup_still_restores(box: dict[str, object], tmp_path: Path) -> None:
    """A backup written before D-149 (gzip, no ``compression`` in the header) verifies and restores unchanged."""
    f = _backup(box, tmp_path, compression="gzip")[0]
    header, magic = _plain_head(f, box["priv"], 2)  # type: ignore[arg-type]
    assert "compression" not in header and magic == b"\x1f\x8b"  # exactly the old format
    box["db"].execute("UPDATE marks SET mark = ? WHERE pid = ?", ("withdrawn", "P1"))  # type: ignore[attr-defined]
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"],  # type: ignore[arg-type]
                     now=datetime(2026, 11, 9, tzinfo=UTC))  # fmt: skip
    assert out["ok"] and out["rows"]["trialbox_wf"] == 5
    db2 = Database.connect(str(box["url"]), "site")
    assert db2.fetchall("SELECT mark FROM marks WHERE pid = 'P1'") == [("approach",)]
    with pytest.raises(bk.BackupError, match="unknown compression"):
        _backup(box, tmp_path, compression="lz4")


def test_backup_needs_the_database_url(tmp_path: Path) -> None:
    pub = tmp_path / "b.pub"
    bk.keygen(tmp_path / "b.key", pub)
    with pytest.raises(bk.BackupError, match="TB_DB_URL"):
        bk.backup([tmp_path / "t"], pub, env={}, dirs={})
