"""Card 10B-22 (D-1261): the MEDIS release a person of the hospital hands to the box, read within hard caps.

* only the files the loader reads are read, by base name; a member's folder is never used, and nothing is written
  (review A, M2); the specification's PDF and Word files are never read;
* the caps: the zip's size, its member count, each file (a header that understates it is refused), all the files
  together, an encrypted member, one table twice, a file that is not a zip: each refused with its code;
* nothing is left behind: the temporary folder is removed after a check and a refusal; the skipped lines answered
  are capped and counted (review A, M1);
* the reminder after MORE than seven months (lane J, L1); the step exists where the country layer says the site uses the master.

Synthetic data only: the release is invented (tests/medis_fixture.py)."""

from __future__ import annotations

import io
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.licensed import LicensedError
from sitesetup import medis_release as mr
from tb_common import country_layer

from tests import medis_fixture as fx


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for k, v in files.items():
            zf.writestr(k, v)
    return buf.getvalue()


def test_only_the_files_the_loader_reads_are_named_by_their_base_name() -> None:
    assert mr.vet(fx.release_zip()) == {
        "readme": "readme.txt", "nmain": "nmain999.txt", "mdfy": "mdfy999.txt", "index": "index999.txt",
        "ttl_main": "ttl_main.txt", "ttl_mdfy": "ttl_mdfy.txt", "ttl_idx": "ttl_idx.txt",
    }  # fmt: skip


def test_a_member_name_is_never_trusted_and_nothing_is_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "a" / "b" / "c"
    work.mkdir(parents=True)
    monkeypatch.chdir(work)
    data = fx.release_zip(drop=("nmain999.txt",), extra={"../../../outside/nmain999.txt": b'"0","1"\r\n',
                                                          "/abs/run.sh": b"echo no", "spec/x.pdf": b"%PDF"})  # fmt: skip
    assert mr.vet(data)["nmain"] == "nmain999.txt"
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda: b"PK\x03\x04 not a zip at all", "LIC-UPLOAD-ZIP"),
        (lambda: b"\x00" * (mr.MAX_ZIP + 1), "LIC-UPLOAD-SIZE"),
        (lambda: _zip({f"f{i}.txt": b"x" for i in range(mr.MAX_MEMBERS + 1)}), "LIC-UPLOAD-MEMBERS"),
        (lambda: _zip({"a/nmain999.txt": b"1", "b/NMAIN999.TXT": b"2"}), "LIC-UPLOAD-TWICE"),
        (lambda: _zip({"a/nmain999.txt": b"1", "b/nmain998.txt": b"2"}), "LIC-UPLOAD-TWICE"),
    ],
    ids=["not a zip", "too large", "too many members", "one table twice", "two releases of one table"],
)
def test_the_caps_refuse_with_their_code(make: Any, code: str) -> None:
    with pytest.raises(LicensedError) as exc:
        mr.vet(make())
    assert exc.value.code == code


def test_a_file_larger_than_the_cap_is_refused_whatever_its_header_says(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mr, "MAX_MEMBER", 1000)
    with pytest.raises(LicensedError) as exc:
        mr.vet(_zip({"x/index999.txt": b"0" * 5000}))
    assert exc.value.code == "LIC-UPLOAD-MEMBER-SIZE"
    # a header that understates the size: never more than it claims is read, and the file is refused, not cut
    import struct

    data = bytearray(_zip({"x/index999.txt": b"0" * 5000}))
    data[22:26] = struct.pack("<I", 10)  # the local header's uncompressed size
    cd = bytes(data).rfind(b"PK\x01\x02")
    data[cd + 24 : cd + 28] = struct.pack("<I", 10)  # the central directory's
    with pytest.raises(LicensedError) as exc:
        mr.vet(bytes(data))
    assert exc.value.code == "LIC-UPLOAD-ZIP"


def test_the_files_together_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review A, M2: each file under its own cap, all of them over the total."""
    monkeypatch.setattr(mr, "MAX_MEMBER", 1000)
    monkeypatch.setattr(mr, "MAX_TOTAL", 1500)
    with pytest.raises(LicensedError) as exc:
        mr.vet(_zip({"x/index999.txt": b"0" * 800, "x/nmain999.txt": b"1" * 800}))
    assert exc.value.code == "LIC-UPLOAD-TOTAL"
    assert mr.vet(_zip({"x/index999.txt": b"0" * 700, "x/nmain999.txt": b"1" * 700}))  # 1,400: within


def test_an_encrypted_member_is_refused() -> None:
    data = bytearray(_zip({"x/nmain999.txt": b"abc"}))
    # set the encryption bit in the local header (offset 6) and in the central directory's entry (offset 8)
    data[6] |= 1
    cd = bytes(data).rfind(b"PK\x01\x02")
    data[cd + 8] |= 1
    with pytest.raises(LicensedError) as exc:
        mr.vet(bytes(data))
    assert exc.value.code == "LIC-UPLOAD-ENCRYPTED"


def test_nothing_is_left_behind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    made: list[Path] = []
    real = tempfile.mkdtemp

    def mkdtemp(**kw: Any) -> str:
        p = real(dir=tmp_path, **kw)
        made.append(Path(p))
        return p

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    got = mr.check(fx.release_zip())
    assert got["version"] == "9.99" and got["released"] == "2026-06-01" and got["disease_rows"] >= 1
    with pytest.raises(LicensedError):
        mr.check(b"not a zip")  # refused before anything is written
    import adapter.licensed as lic

    def broken(*_a: Any, **_k: Any) -> Any:
        raise lic.LicensedError("LIC-TEST", "refused by the loader")

    monkeypatch.setattr(lic, "check_release", broken)
    with pytest.raises(LicensedError):
        mr.check(fx.release_zip())  # refused after the zip was written: removed all the same
    assert len(made) == 2 and not any(p.exists() for p in made)
    # what is kept: counts, version, date, the fingerprint, the first skipped lines and their count
    assert set(got) == {*mr.KEPT, "skipped", "skipped_count"}


def test_the_skipped_lines_answered_are_capped_and_counted() -> None:
    """Review A, M1: a release with many bad lines answers the first ones and the count; the record keeps the count."""
    out = {"version": "9.99", "skipped": [("medis", n, "bad") for n in range(1, 1001)]}
    got = mr._kept(out, "f" * 64)
    assert len(got["skipped"]) == mr.SKIPPED_KEPT and got["skipped_count"] == 1000
    assert got["skipped"][0] == {"table": "medis", "line": 1, "reason": "bad"}
    import json

    assert json.loads(mr.record(got, "u1"))["skipped"] == 1000


def test_the_check_reports_skipped_lines_by_table_line_and_reason() -> None:
    bad = fx.tables()["nmain999.txt"] + '"0","99000099","テスト悪","テストワル","1","bad!","E119"\r\n'.encode("cp932")
    got = mr.check(fx.release_zip(drop=("nmain999.txt",), extra={"byomei999/main/nmain999.txt": bad}))
    assert any(s["table"] == "medis" and s["line"] == len(fx.DISEASES) + 1 and "not a" in s["reason"]
               for s in got["skipped"])  # fmt: skip


@pytest.mark.parametrize(
    ("released", "today", "due"),
    [("2026-06-01", date(2027, 1, 1), False), ("2026-06-01", date(2027, 1, 2), True),
     ("2025-12-01", date(2026, 7, 1), False), ("2025-12-01", date(2026, 7, 2), True),
     ("2026-08-31", date(2027, 3, 31), False), ("2026-08-31", date(2027, 4, 1), True), ("", date(2030, 1, 1), False), ("2026年6月", date(2030, 1, 1), False)],
)  # fmt: skip
def test_the_reminder_comes_after_seven_months(released: str, today: date, due: bool) -> None:
    assert mr.reminder(released, today) is due


def test_the_step_exists_where_the_country_layer_says_the_master_is_used() -> None:
    assert country_layer.layer("JP").value("P7", "medis_master") is True
    assert mr.applies("JP") and mr.applies("jp")
    assert not mr.applies("TW") and not mr.applies("") and not mr.applies(None)
    assert mr.here({"TB_TZ": "Asia/Tokyo"}) and not mr.here({"TB_TZ": "Asia/Taipei"}) and not mr.here({})


def test_a_broken_layer_offers_no_step(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = country_layer.Layer("JP", file="japan_profile.json", problem="test: not whole")
    monkeypatch.setattr(country_layer, "layer", lambda country: broken)
    assert not mr.applies("JP")


def test_a_layer_without_the_value_is_refused_whole() -> None:
    import json

    doc = json.loads((country_layer.ROOT / "japan_profile.json").read_text(encoding="utf-8"))
    del doc["parts"]["P7"]["values"]["medis_master"]
    with pytest.raises(country_layer.LayerError, match="medis_master"):
        country_layer.parse(json.dumps(doc, ensure_ascii=False).encode(), "japan_profile.json")


def test_a_small_zip_of_many_rows_stays_within_a_bounded_memory() -> None:
    """Review A, M1: a zip of a few kilobytes that unpacks to many repeated rows is read within a bounded peak (traced),
    and its answer stays small: the first skipped lines and their count, never every one."""
    import json
    import tracemalloc

    row = fx.tables()["nmain999.txt"].splitlines(keepends=True)[0]
    data = fx.release_zip(drop=("nmain999.txt",), extra={"byomei999/main/nmain999.txt": row * 30_000})
    assert len(data) < 64 * 1024  # a small zip
    tracemalloc.start()
    try:
        got = mr.check(data)
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 96 * 1024 * 1024, peak  # measured: 69 MB for a table at the 16 MB cap
    assert got["skipped_count"] > mr.SKIPPED_KEPT and len(got["skipped"]) == mr.SKIPPED_KEPT
    assert len(json.dumps(got, ensure_ascii=False)) < 20_000
