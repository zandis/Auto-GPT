"""``trialbox backup`` / ``restore`` (TB-PLAN-04 step 2, D-126): one encrypted file, opened only by the hospital's key."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tb_common.db import Database

from tools.backup_drill import write_legacy
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
    out = bk.restore(files[1], box["priv"], env={"TB_DB_URL": str(box["url"]), "TB_SITE_ID": "CGMH"},  # type: ignore[arg-type]
                     dirs=dirs, public_key=box["pub"], keep_to=tmp_path / "kept")  # type: ignore[arg-type]  # fmt: skip
    assert out["ok"] and out["rows"]["trialbox_wf"] == 5 and out["dirs"] == ["audit", "lake"]
    db2 = Database.connect(str(box["url"]), "site")
    assert db2.fetchall("SELECT pid, mark, note FROM marks ORDER BY pid") == [
        ("P1", "approach", "日本語のメモ"), ("P2", "not_now", None)]  # fmt: skip
    assert Database.connect(str(box["url"]), "auth").fetchall("SELECT name FROM users") == [("admin",)]
    assert (dirs["audit"] / "2026" / "log.jsonl").read_text() == '{"e": 1}\n'  # type: ignore[index]
    assert not (dirs["lake"] / "new.parquet").exists()  # type: ignore[index]
    (aside,) = tmp_path.glob("lake.pre-restore-*")
    assert (aside / "new.parquet").exists()  # the replaced data is kept aside, never deleted
    # D-274 (CR-056): the box as it was is kept as one more encrypted backup, which restores the changed state
    kept = Path(out["kept_copy"])
    assert kept.parent == tmp_path / "kept" and bk.read_sidecar(kept) and bk.verify(kept, box["priv"])["ok"]  # type: ignore[arg-type]
    # D-274 (DI-10): the restore is a row in the restored audit log
    assert out["audit"] == str(dirs["audit"])  # type: ignore[index]
    rows = [json.loads(ln) for p in sorted(dirs["audit"].rglob("*.jsonl")) for ln in p.read_text().splitlines()  # type: ignore[index]
            if ln.startswith("{") and '"event"' in ln]  # fmt: skip
    done = [r for r in rows if r.get("event") == "backup.restored"]
    assert len(done) == 1 and done[0]["detail"]["kept_copy"] == str(kept) and done[0]["detail"]["file"] == files[1].name


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
    assert left == [f"trialbox-CGMH-2026110{d}T020000Z.tbbak{s}" for d in (2, 3) for s in ("", ".sha256")]


def test_cli_refuses_restore_without_yes_and_reports_errors(box: dict[str, object], tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    f = _backup(box, tmp_path)[0]
    assert cli(["restore", str(f), "--key", str(box["priv"])]) == 2
    capsys.readouterr()
    deploy = tmp_path / "deploy"
    assert cli(["backup-verify", str(f), "--key", str(box["priv"]), "--deploy", str(deploy)]) == 0
    assert json.loads(capsys.readouterr().out)["site"] == "CGMH"
    rec = json.loads((deploy / "site" / "backup-verified.json").read_text())  # T-209a (OPS-047): the health reads it
    assert rec["file"] == f.name and len(rec["sha256"]) == 64 and rec["site"] == "CGMH"
    bad = tmp_path / "bad.tbbak"
    bad.write_bytes(b"junk")
    assert cli(["backup-verify", str(bad), "--key", str(box["priv"]), "--deploy", str(deploy)]) == 1
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


@pytest.mark.parametrize(("compression", "magic"), [("gzip", b"\x1f\x8b"), ("zstd", b"\x28\xb5\x2f\xfd")])
def test_a_backup_in_a_previous_format_still_restores(
    box: dict[str, object], tmp_path: Path, compression: str, magic: bytes
) -> None:
    """Layout 1, exactly as written before D-187: gzip (before D-149, no ``compression`` in the header) and zstd
    (D-149). Each verifies and restores unchanged; its lake files all come back (layout 1 left nothing out)."""
    lake = box["dirs"]["lake"]  # type: ignore[index]
    (lake / "ndjson" / "2026-01-31").mkdir(parents=True)
    (lake / "ndjson" / "2026-01-31" / "Patient.ndjson").write_text("{}\n")
    (lake / "CURRENT").write_text("2026-11-08")
    f = write_legacy(tmp_path / "old", box["pub"], {"TB_DB_URL": str(box["url"]), "TB_SITE_ID": "CGMH"},  # type: ignore[arg-type]
                     box["dirs"], compression, datetime(2026, 1, 2, tzinfo=UTC))  # type: ignore[arg-type]  # fmt: skip
    header, head = _plain_head(f, box["priv"], len(magic))  # type: ignore[arg-type]
    assert "layout" not in header and ("compression" in header) == (compression == "zstd") and head == magic
    assert bk.read_sidecar(f) is None  # old backups had no sidecar
    assert bk.verify(f, box["priv"])["layout"] == 1  # type: ignore[arg-type]
    box["db"].execute("UPDATE marks SET mark = ? WHERE pid = ?", ("withdrawn", "P1"))  # type: ignore[attr-defined]
    (lake / "ndjson" / "2026-01-31" / "Patient.ndjson").unlink()
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"], no_copy=True,  # type: ignore[arg-type]
                     now=datetime(2026, 11, 9, tzinfo=UTC), max_age_days=None)  # fmt: skip
    assert (
        out["ok"]
        and out["layout"] == 1
        and out["rows"]["trialbox_wf"] == 5
        and out["refdata"]["missing"] == []
        and out["warnings"] == []
    )
    db2 = Database.connect(str(box["url"]), "site")
    assert db2.fetchall("SELECT mark FROM marks WHERE pid = 'P1'") == [("approach",)]
    assert (lake / "ndjson" / "2026-01-31" / "Patient.ndjson").exists()
    with pytest.raises(bk.BackupError, match="unknown compression"):
        _backup(box, tmp_path, compression="lz4")


def test_backup_needs_the_database_url(tmp_path: Path) -> None:
    pub = tmp_path / "b.pub"
    bk.keygen(tmp_path / "b.key", pub)
    with pytest.raises(bk.BackupError, match="TB_DB_URL"):
        bk.backup([tmp_path / "t"], pub, env={}, dirs={})


# ------------------------------------------------------------------------------------------------ layout 2 (D-187)
def test_hashes_come_from_the_stream_and_the_sidecar_matches_the_file(
    box: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WS-08.6 / R-45: a backup never reads a file a second time to hash it; the manifest's sha256 and size are those
    of the bytes in the tar, and ``<file>.sha256`` is the sha256 of the encrypted file as written."""
    real = bk._sha_file
    reads: list[Path] = []

    def counting(p: Path) -> str:
        reads.append(Path(p))
        return real(p)

    monkeypatch.setattr(bk, "_sha_file", counting)
    files = _backup(box, tmp_path)
    assert [r.parent.name for r in reads] == ["nas", "usbdisk"]  # only the written files, read back from each target
    monkeypatch.setattr(bk, "_sha_file", real)
    for f in files:
        assert bk.read_sidecar(f) == hashlib.sha256(f.read_bytes()).hexdigest()
        assert bk.sidecar(f).read_text() == f"{bk.read_sidecar(f)}  {f.name}\n"  # sha256sum -c format
    m = bk.unpack(files[0], box["priv"], tmp_path / "x")  # type: ignore[arg-type]
    assert m["layout"] == 2 and m["hashing"] == "stream"
    parquet = (box["dirs"]["lake"] / "patient.parquet").read_bytes()  # type: ignore[index]
    assert m["files"]["dirs/lake/patient.parquet"] == hashlib.sha256(parquet).hexdigest()
    assert m["sizes"]["dirs/lake/patient.parquet"] == len(parquet)
    assert set(m["sizes"]) == set(m["files"])


def test_a_file_that_shrinks_while_it_is_read_fails_the_backup(
    box: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The size is fixed when the file is opened; a file cut short under the backup is never stored half."""
    orig = bk._HashReader.read

    def short(self: bk._HashReader, size: int = -1) -> bytes:
        b = orig(self, size)
        return b[: len(b) // 2] if len(b) > 1000 else b

    monkeypatch.setattr(bk._HashReader, "read", short)
    with pytest.raises(bk.BackupError, match="changed while it was backed up"):
        _backup(box, tmp_path)
    assert not list((tmp_path / "nas").glob("*.tbbak"))  # no finished file, no sidecar


def test_a_file_that_does_not_match_its_sidecar_is_refused(box: dict[str, object], tmp_path: Path) -> None:
    f = _backup(box, tmp_path)[1]
    bk.sidecar(f).write_text(f"{'0' * 64}  {f.name}\n")
    with pytest.raises(bk.BackupError, match="does not match its .sha256"):
        bk.verify(f, box["priv"])  # type: ignore[arg-type]


def _chunk_starts(raw: bytes) -> list[int]:
    (n,) = struct.unpack(">I", raw[len(bk.MAGIC) : len(bk.MAGIC) + 4])
    pos, starts = len(bk.MAGIC) + 4 + n, []
    while pos < len(raw):
        starts.append(pos)
        size, _ = struct.unpack(">I?", raw[pos : pos + 5])
        pos += 5 + size
    return starts


def test_a_backup_cut_after_the_tar_end_is_refused(box: dict[str, object], tmp_path: Path) -> None:
    """A final chunk that holds only bytes after the tar's end is still required: dropping it is refused (the
    reader drains the stream to the final flag; before, the tar reader stopped at the tar's end and never looked)."""
    import io
    import tarfile

    import zstandard

    data = json.dumps({"layout": 2, "site": "CGMH", "created_at": "2026-11-09T00:00:00+00:00", "databases": {},
                       "dirs": {}, "files": {}}).encode()  # fmt: skip
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w|") as tar:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    f = tmp_path / "crafted.tbbak"
    with f.open("wb") as out:
        enc = bk._Encryptor(out, bk.load_public(box["pub"]), {"layout": 2, "compression": "zstd"})  # type: ignore[arg-type]
        enc._seal(zstandard.ZstdCompressor().compress(buf.getvalue()), last=False)
        enc._seal(b"\0" * 16, last=True)  # trailing bytes after the zstd frame and the tar's end
    assert bk.verify(f, box["priv"])["ok"]  # type: ignore[arg-type]
    raw = f.read_bytes()
    cut = tmp_path / "cut.tbbak"
    cut.write_bytes(raw[: _chunk_starts(raw)[-1]])
    with pytest.raises(bk.BackupError, match="cut short"):
        bk.verify(cut, box["priv"])  # type: ignore[arg-type]


def test_a_backup_cut_in_the_middle_is_refused_plainly(box: dict[str, object], tmp_path: Path) -> None:
    (box["dirs"]["lake"] / "noise.bin").write_bytes(os.urandom(3 * bk.CHUNK))  # type: ignore[index]
    f = _backup(box, tmp_path)[0]
    raw = f.read_bytes()
    starts = _chunk_starts(raw)
    assert len(starts) >= 3
    cut = tmp_path / "cut.tbbak"
    cut.write_bytes(raw[: starts[-2]])
    with pytest.raises(bk.BackupError):
        bk.verify(cut, box["priv"])  # type: ignore[arg-type]


def test_a_newer_layout_is_refused_with_a_plain_message(
    box: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bk, "LAYOUT", 3)
    f = _backup(box, tmp_path)[0]
    with pytest.raises(bk.BackupError, match="newer TrialBox"):
        bk.verify(f, box["priv"])  # type: ignore[arg-type]


def test_the_lake_keeps_current_and_the_merge_base_ndjson_and_leaves_out_old_ndjson_and_spill(
    box: dict[str, object], tmp_path: Path
) -> None:
    lake: Path = box["dirs"]["lake"]  # type: ignore[index]
    snaps = ("2026-10-30", "2026-10-31", "2026-11-07", "2026-11-08", "2026-11-09")
    for snap in snaps:
        (lake / "ndjson" / snap).mkdir(parents=True)
        (lake / "ndjson" / snap / "Patient.ndjson").write_text(f'{{"id":"{snap}"}}\n')
        (lake / "parquet" / f"snapshot={snap}").mkdir(parents=True)
        (lake / "parquet" / f"snapshot={snap}" / "patient.parquet").write_bytes(b"PAR1" + snap.encode())
        (lake / "db").mkdir(exist_ok=True)
        (lake / "db" / f"{snap}.duckdb").write_bytes(b"duck" + snap.encode())
    (lake / "CURRENT").write_text("2026-11-07\n")  # 2026-11-08 and -09 were held nights, newer than CURRENT
    (lake / "embed_cache.duckdb").write_bytes(b"vectors")
    (lake / "site").mkdir()
    (lake / "site" / "Observation.ndjson").write_text("{}\n")
    (lake / "tmp").mkdir()
    (lake / "tmp" / "spill.tmp").write_bytes(b"x" * 100)
    (lake / "db" / "2026-11-10.building").write_bytes(b"half")
    keep, left = bk.select_files("lake", lake)
    nd = sorted(k for k in keep if k.startswith("ndjson/"))
    # CURRENT, and the two newest: the next night (11-10) merges over 11-09, a re-run of 11-09 over 11-08
    assert nd == [f"ndjson/{s}/Patient.ndjson" for s in ("2026-11-07", "2026-11-08", "2026-11-09")]
    assert sum(k.startswith("parquet/") for k in keep) == 5 and sum(k.endswith(".duckdb") for k in keep) == 6
    assert {"embed_cache.duckdb", "site/Observation.ndjson", "CURRENT", "patient.parquet"} <= set(keep)
    assert left == {"lake NDJSON of older snapshots (their Parquet and DuckDB are kept)": 2, "lake tmp/ (spill)": 1,
                    "lake snapshot being built": 1}  # fmt: skip
    assert bk.select_files("audit", lake)[1] == {}  # the rules are the lake's only: other folders are taken whole
    f = _backup(box, tmp_path)[0]
    m = bk.unpack(f, box["priv"], tmp_path / "x")  # type: ignore[arg-type]
    assert m["excluded"]["lake"] == left and m["dirs"]["lake"]["files"] == len(keep)
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"], no_copy=True,  # type: ignore[arg-type]
                     )  # fmt: skip
    assert out["ok"]
    assert sorted(str(p.relative_to(lake)) for p in (lake / "ndjson").rglob("*.ndjson")) == nd
    assert not (lake / "tmp").exists() and (lake / "db" / "2026-10-31.duckdb").exists()


def test_a_lake_without_current_keeps_all_ndjson(tmp_path: Path) -> None:
    for snap in ("2026-11-01", "2026-11-02"):
        (tmp_path / "ndjson" / snap).mkdir(parents=True)
        (tmp_path / "ndjson" / snap / "Patient.ndjson").write_text("{}\n")
    keep, left = bk.select_files("lake", tmp_path)
    assert len(keep) == 2 and left == {}


def test_an_older_snapshot_keeps_its_reports(tmp_path: Path) -> None:
    for snap in ("2026-10-30", "2026-11-01", "2026-11-02", "2026-11-03"):
        (tmp_path / "ndjson" / snap).mkdir(parents=True)
        (tmp_path / "ndjson" / snap / "Patient.ndjson").write_text("{}\n")
    (tmp_path / "ndjson" / "2026-10-30" / "reader.json").write_text("{}")
    (tmp_path / "ndjson" / "2026-10-30" / "tombstones.json").write_text("{}")
    (tmp_path / "CURRENT").write_text("2026-11-03")
    keep, left = bk.select_files("lake", tmp_path)
    assert {"ndjson/2026-10-30/reader.json", "ndjson/2026-10-30/tombstones.json"} <= set(keep)
    assert "ndjson/2026-10-30/Patient.ndjson" not in keep and sum(left.values()) == 2


# ------------------------------------------------------------------------------------------------ one snapshot (H1)
def test_rows_are_counted_in_the_dumps_own_snapshot_while_the_box_writes(
    box: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row written after the snapshot (here: by the pg_dump wrapper, just before pg_dump starts) is neither in the
    dump nor in the manifest's counts, so the restore matches exactly. Counting on the live database afterwards, as
    before, put it in the counts and not in the dump: a good backup then failed its restore."""
    db: Database = box["db"]  # type: ignore[assignment]
    from tb_common.db import split_url

    dsn = split_url(str(box["url"]))[0]
    wrapper = tmp_path / "pg_dump_late_write.sh"
    wrapper.write_text(f'#!/bin/sh\npsql -X -q --dbname "$LATE_DSN" -c "INSERT INTO {db.schema}.marks VALUES '
                       "('P9', 'late', NULL)\" >/dev/null\nexec pg_dump \"$@\"\n")  # fmt: skip
    wrapper.chmod(0o755)
    monkeypatch.setenv("LATE_DSN", dsn)
    env = {"TB_DB_URL": str(box["url"]), "TB_SITE_ID": "CGMH", "TB_PG_DUMP_CMD": str(wrapper)}
    f = bk.backup([tmp_path / "nas"], box["pub"], env=env, dirs=box["dirs"])[0]  # type: ignore[arg-type]
    assert db.fetchall("SELECT count(*) FROM marks") == [(3,)]  # the late row is in the live database
    m = bk.unpack(f, box["priv"], tmp_path / "x")  # type: ignore[arg-type]
    twf = m["databases"]["trialbox_wf"]
    assert twf["rows_from"] == "snapshot" and twf["rows"][f"{db.schema}.marks"][0] == 2
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"], no_copy=True,  # type: ignore[arg-type]
                     )  # fmt: skip
    assert out["ok"] and out["warnings"] == [] and db.fetchall("SELECT count(*) FROM marks") == [(2,)]


def test_a_snapshot_backup_whose_rows_do_not_come_back_fails_the_restore(
    box: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = _backup(box, tmp_path)[0]
    real = bk.row_counts
    monkeypatch.setattr(
        bk, "row_counts", lambda src, skip=(), scheme="rs1": {**real(src, skip, scheme), "x.lost": [1, "0"]}
    )
    with pytest.raises(bk.BackupError, match="differs from the backup"):
        bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"], no_copy=True)  # type: ignore[arg-type]


def test_a_backup_counted_on_a_live_box_warns_on_a_row_mismatch(box: dict[str, object], tmp_path: Path) -> None:
    """The update path's dumps (TB_PG_DUMP_DIR without ``.rows``) are counted when the backup runs: a row written in
    between is a warning on restore, not a failure."""
    pre = tmp_path / "dumps"
    pre.mkdir()
    src = bk.db_sources({"TB_DB_URL": str(box["url"])})[0]
    bk.dump(src, pre / "trialbox_wf.dump", {"TB_DB_URL": str(box["url"])})
    box["db"].execute("INSERT INTO marks VALUES (?, ?, ?)", ("P9", "late", None))  # type: ignore[attr-defined]
    env = {"TB_DB_URL": str(box["url"]), "TB_PG_DUMP_DIR": str(pre), "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], box["pub"], env=env, dirs=box["dirs"])[0]  # type: ignore[arg-type]
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"], no_copy=True)  # type: ignore[arg-type]
    assert out["ok"] and len(out["warnings"]) == 1 and "running box" in out["warnings"][0]


def test_a_file_rewritten_while_it_is_read_is_read_again(
    box: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DuckDB-like file rewritten in place at the same size during the read: the torn copy is followed by a whole
    one, which the manifest names and the restore extracts. A file that never settles fails the backup."""
    target = box["dirs"]["lake"] / "patient.parquet"  # type: ignore[index]
    new = b"NEW!" + bytes(range(256)) * 5000
    orig = bk._HashReader.read
    state = {"done": False}

    def rewriting(self: bk._HashReader, size: int = -1) -> bytes:
        b = orig(self, size)
        if not state["done"] and b.startswith(b"PAR1"):
            state["done"] = True
            target.write_bytes(new)  # same size, new content, new mtime
            os.utime(target, ns=(target.stat().st_atime_ns, target.stat().st_mtime_ns + 10**9))
        return b

    monkeypatch.setattr(bk._HashReader, "read", rewriting)
    f = _backup(box, tmp_path)[0]
    monkeypatch.setattr(bk._HashReader, "read", orig)
    m = bk.unpack(f, box["priv"], tmp_path / "x")  # type: ignore[arg-type]
    assert m["files"]["dirs/lake/patient.parquet"] == hashlib.sha256(new).hexdigest()
    assert (tmp_path / "x" / "dirs" / "lake" / "patient.parquet").read_bytes() == new

    def always(self: bk._HashReader, size: int = -1) -> bytes:
        b = orig(self, size)
        if b.startswith(b"NEW!"):
            os.utime(target, ns=(target.stat().st_atime_ns, target.stat().st_mtime_ns + 10**9))
        return b

    monkeypatch.setattr(bk._HashReader, "read", always)
    with pytest.raises(bk.BackupError, match="kept changing"):
        _backup(box, tmp_path / "again")


# ------------------------------------------------------------------------------------------------ sites (H4)
def test_prune_keeps_other_sites_files_on_a_shared_target(box: dict[str, object], tmp_path: Path) -> None:
    nas = tmp_path / "nas"
    nas.mkdir()
    other = nas / "trialbox-OTHER-20200101T000000Z.tbbak"
    other.write_bytes(b"x")
    bk.sidecar(other).write_text("y")
    prefix_like = nas / "trialbox-CGMH-EXTRA-20200101T000000Z.tbbak"  # a site whose name starts like this one's
    prefix_like.write_bytes(b"x")
    for day in (1, 2):
        _backup(box, tmp_path, keep=1, now=datetime(2026, 11, day, tzinfo=UTC))
    assert other.exists() and bk.sidecar(other).exists() and prefix_like.exists()
    assert len(list(nas.glob("trialbox-CGMH-2026*.tbbak"))) == 1


# ------------------------------------------------------------------------------------------------ refdata (H5)
def _refdata_box(box: dict[str, object], tmp_path: Path) -> tuple[Path, Database]:
    """The sample vendor pack loaded through the real store, plus a source the hospital fetched itself."""
    from tb_common import refdata as rd

    from tools import refdata_fetch as rf

    tar = rf.build(rf.sample_raw(tmp_path / "rd" / "raw"), tmp_path / "rd", "20261109", sample=True)
    with rd.RefStore(str(box["url"])) as st, rd.opened(tar) as pack:
        st.load(pack, by="test")
    ref = Database.connect(str(box["url"]), "refdata")
    ref.execute("INSERT INTO source (source_id, pack_id, name, kind, distribution, records, url, downloaded_at, "
                "licence, attribution) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("umin-site", "site-pack", "UMIN-CTR", "trial", "site-fetch", 1, "https://example.invalid", "2026",
                 "site", "site"))  # fmt: skip
    ref.execute("INSERT INTO trial (registry, trial_id, title, status, conditions, countries, record, source_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("umin", "UMIN000099", "site trial", "open", "gout", "Japan", "{}", "umin-site"))  # fmt: skip
    return tar, ref


def _refdata_state(ref: Database) -> dict[str, Any]:
    return {t: ref.fetchall(f"SELECT * FROM {t} ORDER BY 1, 2") for t in ("ctgov_study", "trial", "term")} | {
        "source": ref.fetchall("SELECT source_id, distribution FROM source ORDER BY 1"),
        "versions": ref.fetchall("SELECT * FROM _schema_version ORDER BY 1"),
    }


def test_vendor_reference_rows_are_left_out_and_loaded_again_on_restore(box: dict[str, object], tmp_path: Path) -> None:
    tar, ref = _refdata_box(box, tmp_path)
    before = _refdata_state(ref)
    assert before["ctgov_study"] and before["versions"]
    f = _backup(box, tmp_path)[0]
    m = bk.unpack(f, box["priv"], tmp_path / "x")  # type: ignore[arg-type]
    twf = m["databases"]["trialbox_wf"]
    assert sorted(twf["excluded_tables"]) == sorted(f"{ref.schema}.{t}" for t in ("ctgov_study", "term", "trial"))
    assert f"{ref.schema}.pack" in twf["rows"] and f"{ref.schema}.source" in twf["rows"]
    assert f"{ref.schema}._schema_version" in twf["rows"]
    assert twf["site_rows"][f"{ref.schema}.trial"][0] == 1  # the hospital's own row is in the backup
    dump = (tmp_path / "x" / "db" / "trialbox_wf.dump").read_bytes()
    assert b"NCT99000001" not in dump  # the vendor's rows are not
    assert [p["pack_id"] for p in m["refdata_packs"]] == [tar.name.removesuffix(".tar")]
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"], no_copy=True,  # type: ignore[arg-type]
                     refdata_dir=tar.parent)  # fmt: skip
    assert out["ok"] and out["refdata"] == {"reloaded": [tar.name.removesuffix(".tar")], "missing": []}
    after = _refdata_state(Database.connect(str(box["url"]), "refdata"))
    assert after == before


def test_a_restore_without_the_pack_keeps_the_site_rows_and_says_it_is_not_done(
    box: dict[str, object], tmp_path: Path, capsys: Any
) -> None:
    tar, _ref = _refdata_box(box, tmp_path)
    f = _backup(box, tmp_path)[0]
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"], no_copy=True,  # type: ignore[arg-type]
                     refdata_dir=tmp_path / "empty")  # fmt: skip
    assert not out["ok"] and out["refdata"]["missing"] == [tar.name.removesuffix(".tar")]
    ref2 = Database.connect(str(box["url"]), "refdata")
    assert ref2.fetchall("SELECT trial_id FROM trial") == [("UMIN000099",)]  # site-fetch rows came back
    assert ref2.fetchall("SELECT count(*) FROM ctgov_study") == [(0,)]
    assert ref2.fetchall("SELECT count(*) FROM pack") == [(1,)] and ref2.fetchall(
        "SELECT count(*) FROM _schema_version"
    )
    rc = cli(["restore", str(f), "--key", str(box["priv"]), "--yes", "--no-copy", "--refdata", str(tmp_path / "empty"),
              "--dir", f"audit={box['dirs']['audit']}", "--dir", f"lake={box['dirs']['lake']}"])  # type: ignore[index]  # fmt: skip
    assert rc == 3 and "reference data is NOT loaded" in capsys.readouterr().err
    assert cli(["restore", str(f), "--key", str(box["priv"]), "--yes", "--refdata", str(tar.parent),
                "--public", str(box["pub"]), "--keep-to", str(tmp_path / "kept"),
                "--dir", f"audit={box['dirs']['audit']}", "--dir", f"lake={box['dirs']['lake']}"]) == 0  # type: ignore[index]  # fmt: skip


def test_the_update_paths_full_dump_keeps_every_row(box: dict[str, object], tmp_path: Path) -> None:
    """``dump`` (the update path's rollback point) is a full dump, reference rows included."""
    _tar, _ref = _refdata_box(box, tmp_path)
    src = bk.db_sources({"TB_DB_URL": str(box["url"])})[0]
    bk.dump(src, tmp_path / "full.dump", {"TB_DB_URL": str(box["url"])})
    import subprocess

    listing = subprocess.run(["pg_restore", "-f", "-", str(tmp_path / "full.dump")], capture_output=True, check=True)
    assert b"NCT99000001" in listing.stdout


# ------------------------------------------------------------------------------------------------ D-274 (FG D-274)
def _env(box: dict[str, object], **kw: str) -> dict[str, str]:
    return {"TB_DB_URL": str(box["url"]), "TB_SITE_ID": "CGMH", **kw}


def _marks(box: dict[str, object]) -> list[tuple[object, ...]]:
    return Database.connect(str(box["url"]), "site").fetchall("SELECT pid, mark FROM marks ORDER BY pid")


def test_restore_refuses_another_site_an_old_or_a_future_backup_before_touching_anything(
    box: dict[str, object], tmp_path: Path
) -> None:
    """CR-056: the site and the age are checked before anything changes."""
    f = _backup(box, tmp_path, now=datetime(2026, 10, 1, tzinfo=UTC))[0]
    box["db"].execute("UPDATE marks SET mark = ? WHERE pid = ?", ("withdrawn", "P1"))  # type: ignore[attr-defined]
    kw: dict[str, Any] = {"dirs": box["dirs"], "no_copy": True, "now": datetime(2026, 10, 2, tzinfo=UTC)}
    with pytest.raises(bk.BackupError, match="site 'CGMH', this box is 'NTUH'"):
        bk.restore(f, box["priv"], env=_env(box, TB_SITE_ID="NTUH"), **kw)  # type: ignore[arg-type]
    with pytest.raises(bk.BackupError, match="30 days old"):
        bk.restore(f, box["priv"], env=_env(box), **{**kw, "now": datetime(2026, 10, 31, tzinfo=UTC)})  # type: ignore[arg-type]
    with pytest.raises(bk.BackupError, match="in the future"):
        bk.restore(f, box["priv"], env=_env(box), **{**kw, "now": datetime(2026, 9, 30, tzinfo=UTC)})  # type: ignore[arg-type]
    assert _marks(box)[0] == ("P1", "withdrawn")  # nothing was touched
    assert not list(tmp_path.glob("*.pre-restore-*"))
    out = bk.restore(f, box["priv"], env=_env(box, TB_SITE_ID="NTUH"), other_site=True, max_age_days=None,  # type: ignore[arg-type]
                     **{**kw, "now": datetime(2026, 10, 31, tzinfo=UTC)})  # fmt: skip
    assert out["ok"] and _marks(box)[0] == ("P1", "approach")


def test_restore_over_a_box_with_data_needs_the_key_for_its_copy(
    box: dict[str, object], tmp_path: Path, capsys: Any
) -> None:
    f = _backup(box, tmp_path)[0]
    with pytest.raises(bk.BackupError, match="a copy is kept before a restore"):
        bk.restore(f, box["priv"], env=_env(box), dirs=box["dirs"], keep_to=tmp_path / "kept")  # type: ignore[arg-type]
    rc = cli(["restore", str(f), "--key", str(box["priv"]), "--yes", "--public", str(tmp_path / "none.pub"),
              "--dir", f"audit={box['dirs']['audit']}", "--dir", f"lake={box['dirs']['lake']}"])  # type: ignore[index]  # fmt: skip
    assert rc == 1 and "--no-copy" in capsys.readouterr().err
    out = bk.restore(f, box["priv"], env=_env(box), dirs=box["dirs"], no_copy=True)  # type: ignore[arg-type]
    assert out["kept_copy"] is None and "no copy was kept" in out["copy"]


def test_a_failed_row_check_names_the_kept_copy_is_audited_and_moves_no_folder(
    box: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-056: the rows are checked before any folder moves; the copy taken first puts the box back."""
    f = _backup(box, tmp_path)[0]
    box["db"].execute("UPDATE marks SET mark = ? WHERE pid = ?", ("withdrawn", "P1"))  # type: ignore[attr-defined]
    real = bk.row_counts
    monkeypatch.setattr(
        bk, "row_counts", lambda src, skip=(), scheme="rs1": {**real(src, skip, scheme), "x.y": [1, "0"]}
    )
    with pytest.raises(bk.BackupError, match="differs from the backup.*kept in .*trialbox restore") as err:
        bk.restore(f, box["priv"], env=_env(box), dirs=box["dirs"], public_key=box["pub"],  # type: ignore[arg-type]
                   keep_to=tmp_path / "kept")  # fmt: skip
    assert not list(tmp_path.glob("*.pre-restore-*"))  # no folder was moved
    events = [json.loads(ln) for p in box["dirs"]["audit"].rglob("*.jsonl") for ln in p.read_text().splitlines()  # type: ignore[index]
              if '"backup.restore_failed"' in ln]  # fmt: skip
    assert len(events) == 1 and events[0]["detail"]["kept_copy"] in str(err.value)
    monkeypatch.setattr(bk, "row_counts", real)
    (kept,) = (tmp_path / "kept").glob("*.tbbak")
    out = bk.restore(kept, box["priv"], env=_env(box), dirs=box["dirs"], no_copy=True)  # type: ignore[arg-type]
    assert out["ok"] and _marks(box)[0] == ("P1", "withdrawn")  # the box as it was before the failed restore


def test_a_whole_database_restore_leaves_no_table_the_backup_does_not_hold(pg_cluster_url: str, tmp_path: Path) -> None:
    """CR-056: on a box (no tb_prefix) a table or schema made after the backup is gone after the restore, and the
    row check passes; before D-274 it stayed and the check failed after everything was replaced."""
    from urllib.parse import urlsplit, urlunsplit

    import psycopg
    from tb_common.db import split_url

    dsn, _ = split_url(pg_cluster_url)
    name = f"tb_restore_{os.getpid()}_{datetime.now(UTC).strftime('%H%M%S%f')}"
    try:
        with psycopg.connect(dsn, autocommit=True) as con:
            con.execute(f'CREATE DATABASE "{name}"')
    except psycopg.Error as e:
        pytest.skip(f"cannot create a database here: {e}")
    parts = urlsplit(dsn)
    url = urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))
    try:
        with psycopg.connect(url, autocommit=True) as con:
            con.execute("CREATE SCHEMA site; CREATE TABLE site.marks (pid text PRIMARY KEY, mark text)")
            con.execute("INSERT INTO site.marks VALUES ('P1', 'approach')")
        priv, pub = tmp_path / "k.key", tmp_path / "k.pub"
        bk.keygen(priv, pub)
        env = {"TB_DB_URL": url, "TB_SITE_ID": "CGMH"}
        f = bk.backup([tmp_path / "nas"], pub, env=env, dirs={})[0]
        with psycopg.connect(url, autocommit=True) as con:
            con.execute("CREATE SCHEMA later; CREATE TABLE later.t (x int); CREATE TABLE public.extra (x int)")
            con.execute("INSERT INTO later.t VALUES (1); UPDATE site.marks SET mark = 'withdrawn'")
        out = bk.restore(f, priv, env=env, dirs={}, public_key=pub, keep_to=tmp_path / "kept")
        assert out["ok"] and out["warnings"] == [] and out["kept_copy"]
        with psycopg.connect(url, autocommit=True) as con:
            names = {r[0] for r in con.execute("SELECT table_schema || '.' || table_name FROM information_schema.tables "
                                               "WHERE table_schema NOT IN ('pg_catalog', 'information_schema')")}  # fmt: skip
            assert names == {"site.marks"}
            assert con.execute("SELECT mark FROM site.marks").fetchall() == [("approach",)]
    finally:
        with psycopg.connect(dsn, autocommit=True) as con:
            con.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_the_row_hash_builds_no_string_over_a_table_and_ignores_row_order(db_url: str) -> None:
    """CR-057: ``rs1`` sums each row's hash, so no value grows with the table; the same rows in another order hash the
    same, one changed row does not. ``md5`` (every backup before D-274) is still computed for their restore."""
    from tools.trialbox import backup_schedule as bs

    assert "string_agg" not in bs.row_agg() and "string_agg" in bs.row_agg("md5")
    a, b = Database.connect(db_url, "a"), Database.connect(db_url, "b")
    for db, order in ((a, ("P1", "P2", "P3")), (b, ("P3", "P1", "P2"))):
        db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT)"])
        for pid in order:
            db.execute("INSERT INTO marks VALUES (?, ?)", (pid, "approach"))
    src = bk.db_sources({"TB_DB_URL": db_url})[0]
    h = bk.row_counts(src)
    assert h[f"{a.schema}.marks"] == h[f"{b.schema}.marks"] and h[f"{a.schema}.marks"][1].startswith("rs1:")
    b.execute("UPDATE marks SET mark = ? WHERE pid = ?", ("not_now", "P2"))
    h2 = bk.row_counts(src)
    assert (
        h2[f"{a.schema}.marks"][0] == h2[f"{b.schema}.marks"][0] and h2[f"{a.schema}.marks"] != h2[f"{b.schema}.marks"]
    )
    assert (
        bk.row_counts(src, scheme="md5")[f"{a.schema}.marks"][1]
        == bk.row_counts(src, scheme="md5")[f"{a.schema}.marks"][1]
    )
    a.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT)", "CREATE TABLE empty (x int)"])
    assert bk.row_counts(src)[f"{a.schema}.empty"] == [0, bs.EMPTY_HASH["rs1"]]
    assert bk.row_counts(src, scheme="md5")[f"{a.schema}.empty"] == [0, bs.EMPTY_HASH["md5"]]


def test_the_host_part_is_in_the_backup_and_restored_only_where_named(box: dict[str, object], tmp_path: Path) -> None:
    """DI-12: the nightly run's host files (deploy/.env, settings) are in the backup; a restore writes them only to a
    folder named ``host`` and otherwise says where they are."""
    pre = tmp_path / "dumps"
    (pre / "host").mkdir(parents=True)
    src = bk.db_sources({"TB_DB_URL": str(box["url"])})[0]
    bk.dump(src, pre / "trialbox_wf.dump", {"TB_DB_URL": str(box["url"])})
    (pre / "host" / "deploy.env").write_text("TB_SITE_ID=CGMH\n")
    (pre / "host" / "settings.yaml").write_text("site: {tz: Asia/Taipei}\n")
    f = bk.backup([tmp_path / "nas"], box["pub"], env=_env(box, TB_PG_DUMP_DIR=str(pre)), dirs=box["dirs"])[0]  # type: ignore[arg-type]
    m = bk.unpack(f, box["priv"], tmp_path / "x")  # type: ignore[arg-type]
    assert {"dirs/host/deploy.env", "dirs/host/settings.yaml"} <= set(m["files"])
    out = bk.restore(f, box["priv"], env=_env(box), dirs=box["dirs"], no_copy=True)  # type: ignore[arg-type]
    assert out["ok"] and "not restored" in out["host"]
    where = tmp_path / "host-restored"
    out = bk.restore(f, box["priv"], env=_env(box), dirs={**box["dirs"], "host": where}, no_copy=True)  # type: ignore[dict-item,arg-type]
    assert (where / "deploy.env").read_text() == "TB_SITE_ID=CGMH\n" and out["host"].startswith("restored to")
