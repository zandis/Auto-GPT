"""``trialbox backup`` / ``restore`` (TB-PLAN-04 step 2, D-126): one encrypted file, opened only by the hospital's key."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from datetime import UTC, datetime
from pathlib import Path

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
    assert left == [f"trialbox-CGMH-2026110{d}T020000Z.tbbak{s}" for d in (2, 3) for s in ("", ".sha256")]


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
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"],  # type: ignore[arg-type]
                     now=datetime(2026, 11, 9, tzinfo=UTC))  # fmt: skip
    assert out["ok"] and out["layout"] == 1 and out["rows"]["trialbox_wf"] == 5 and out["reload_refdata"] == []
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
    assert [r.parent.name for r in reads] == ["usbdisk"]  # only the copy on the second target is read back
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
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"],  # type: ignore[arg-type]
                     now=datetime(2026, 11, 9, tzinfo=UTC))  # fmt: skip
    assert out["ok"]
    assert sorted(str(p.relative_to(lake)) for p in (lake / "ndjson").rglob("*.ndjson")) == nd
    assert not (lake / "tmp").exists() and (lake / "db" / "2026-10-31.duckdb").exists()


def test_a_lake_without_current_keeps_all_ndjson(tmp_path: Path) -> None:
    for snap in ("2026-11-01", "2026-11-02"):
        (tmp_path / "ndjson" / snap).mkdir(parents=True)
        (tmp_path / "ndjson" / snap / "Patient.ndjson").write_text("{}\n")
    keep, left = bk.select_files("lake", tmp_path)
    assert len(keep) == 2 and left == {}


def test_refdata_rows_are_left_out_listed_and_the_rest_restores(box: dict[str, object], tmp_path: Path) -> None:
    """The reference pack (schema ``refdata``) is public and reloaded from the pack: its tables are in the dump, its
    rows are not, and the manifest and the restore name the packs to load again."""
    ref = Database.connect(str(box["url"]), "refdata")
    ref.migrate([
        "CREATE TABLE pack (pack_id TEXT PRIMARY KEY, data_as_of TEXT NOT NULL, origin TEXT NOT NULL)",
        "CREATE TABLE ctgov_study (nct_id TEXT PRIMARY KEY, body TEXT)",
    ])  # fmt: skip
    ref.execute("INSERT INTO pack VALUES (?, ?, ?)", ("trialbox-refdata-20261109", "2026-11-09", "vendor"))
    ref.execute("INSERT INTO ctgov_study VALUES (?, ?)", ("NCT99000001", "x" * 50_000))
    f = _backup(box, tmp_path)[0]
    m = bk.unpack(f, box["priv"], tmp_path / "x")  # type: ignore[arg-type]
    db = m["databases"]["trialbox_wf"]
    assert db["excluded_data_schemas"] == [ref.schema]
    assert not any(k.startswith(f"{ref.schema}.") for k in db["rows"])
    assert m["refdata_packs"] == [{"pack_id": "trialbox-refdata-20261109", "data_as_of": "2026-11-09",
                                   "origin": "vendor"}]  # fmt: skip
    dump = (tmp_path / "x" / "db" / "trialbox_wf.dump").read_bytes()
    assert b"NCT99000001" not in dump and b"approach" in dump  # -Z0: the dump is plain inside the encrypted stream
    out = bk.restore(f, box["priv"], env={"TB_DB_URL": str(box["url"])}, dirs=box["dirs"],  # type: ignore[arg-type]
                     now=datetime(2026, 11, 9, tzinfo=UTC))  # fmt: skip
    assert out["ok"] and out["reload_refdata"][0]["pack_id"] == "trialbox-refdata-20261109"
    ref2 = Database.connect(str(box["url"]), "refdata")
    assert ref2.fetchall("SELECT count(*) FROM ctgov_study") == [(0,)]  # the table is there, empty until reloaded
    assert Database.connect(str(box["url"]), "site").fetchall("SELECT count(*) FROM marks") == [(2,)]


def test_dumps_taken_by_the_db_container_carry_what_they_left_out(box: dict[str, object], tmp_path: Path) -> None:
    """TB_PG_DUMP_DIR (the nightly run and the update path): ``<name>.dump.json`` says which rows the dump left out;
    without it the dump is a full one (the update path) and nothing is marked left out."""
    pre = tmp_path / "dumps"
    pre.mkdir()
    src = bk.db_sources({"TB_DB_URL": str(box["url"])})[0]
    bk.dump(src, pre / "trialbox_wf.dump", {"TB_DB_URL": str(box["url"])})
    assert bk.dump(src, tmp_path / "a.dump", {"TB_PG_DUMP_DIR": str(pre)}) == ()
    (pre / "trialbox_wf.dump.json").write_text(json.dumps({"exclude_table_data_schemas": [src.exclude_data()[0]]}))
    assert bk.dump(src, tmp_path / "b.dump", {"TB_PG_DUMP_DIR": str(pre)}) == src.exclude_data()
    assert bk.DbSource("hapi", "x", ()).exclude_data() == ()  # HAPI keeps every row
