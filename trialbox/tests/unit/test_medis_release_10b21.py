"""Card 10B-21 (D-1261): the MEDIS release a person of the hospital hands to the box, unpacked within hard caps.

* only the tables, the readme and the title lines are unpacked, by base name; a member's folder is never used (a
  name that climbs out of the folder lands inside it), and the specification's PDF and Word files are never written;
* the caps: the zip's size, its member count, each table unpacked (read in pieces, whatever the header claims), an
  encrypted member, one table twice, a file that is not a zip: each refused with its code;
* nothing is left behind: the temporary folder is removed after a check, a load and a refusal;
* the reminder after seven months; the step exists where the country layer says the site uses the master.

Synthetic data only: the release is invented (tests/medis_fixture.py)."""

from __future__ import annotations

import io
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter import licensed
from adapter.licensed import LicensedError
from sitesetup import medis_release as mr
from tb_common import country_layer

from tests import medis_fixture as fx


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loader of #1238 (card 10B-2c) until it is on master: the same signature."""
    monkeypatch.setattr(licensed, "check_release", fx.check_release, raising=False)
    monkeypatch.setattr(licensed, "load_release", fx.load_release, raising=False)


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for k, v in files.items():
            zf.writestr(k, v)
    return buf.getvalue()


def test_only_the_tables_are_unpacked_by_their_base_name(tmp_path: Path) -> None:
    out = mr.unpack(fx.release_zip(), tmp_path)
    assert sorted(p.name for p in out.iterdir()) == [
        "index999.txt", "mdfy999.txt", "nmain999.txt", "readme.txt", "ttl_idx.txt", "ttl_main.txt", "ttl_mdfy.txt",
    ]  # fmt: skip
    assert not list(tmp_path.rglob("*.pdf")) and not list(tmp_path.rglob("*.doc"))


def test_a_member_name_is_never_trusted(tmp_path: Path) -> None:
    data = fx.release_zip(drop=("nmain999.txt",), extra={"../../../outside/nmain999.txt": b'"0","1"\r\n',
                                                          "/abs/run.sh": b"echo no"})  # fmt: skip
    out = mr.unpack(data, tmp_path / "in")  # the folder must exist: made here
    assert (out / "nmain999.txt").read_bytes() == b'"0","1"\r\n'
    assert not (tmp_path / "outside").exists() and not list(tmp_path.rglob("run.sh"))


@pytest.fixture(autouse=True)
def _into(tmp_path: Path) -> None:
    (tmp_path / "in").mkdir()


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda: b"PK\x03\x04 not a zip at all", "LIC-UPLOAD-ZIP"),
        (lambda: b"\x00" * (mr.MAX_ZIP + 1), "LIC-UPLOAD-SIZE"),
        (lambda: _zip({f"f{i}.txt": b"x" for i in range(mr.MAX_MEMBERS + 1)}), "LIC-UPLOAD-MEMBERS"),
        (lambda: _zip({"a/nmain999.txt": b"1", "b/NMAIN999.TXT": b"2"}), "LIC-UPLOAD-TWICE"),
    ],
    ids=["not a zip", "too large", "too many members", "one table twice"],
)
def test_the_caps_refuse_with_their_code(make: Any, code: str, tmp_path: Path) -> None:
    with pytest.raises(LicensedError) as exc:
        mr.unpack(make(), tmp_path / "in")
    assert exc.value.code == code


def test_a_table_larger_than_the_cap_is_stopped_while_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mr, "MAX_MEMBER", 1000)
    with pytest.raises(LicensedError) as exc:
        mr.unpack(_zip({"x/index999.txt": b"0" * 5000}), tmp_path / "in")
    assert exc.value.code == "LIC-UPLOAD-MEMBER-SIZE"
    # a header that understates the size: never more than it claims is read, and the table is refused, not cut
    import struct

    data = bytearray(_zip({"x/index999.txt": b"0" * 5000}))
    data[22:26] = struct.pack("<I", 10)  # the local header's uncompressed size
    cd = bytes(data).rfind(b"PK\x01\x02")
    data[cd + 24 : cd + 28] = struct.pack("<I", 10)  # the central directory's
    with pytest.raises(LicensedError) as exc:
        mr.unpack(bytes(data), tmp_path)
    assert exc.value.code == "LIC-UPLOAD-ZIP"


def test_an_encrypted_member_is_refused(tmp_path: Path) -> None:
    data = bytearray(_zip({"x/nmain999.txt": b"abc"}))
    # set the encryption bit in the local header (offset 6) and in the central directory's entry (offset 8)
    data[6] |= 1
    cd = bytes(data).rfind(b"PK\x01\x02")
    data[cd + 8] |= 1
    with pytest.raises(LicensedError) as exc:
        mr.unpack(bytes(data), tmp_path / "in")
    assert exc.value.code == "LIC-UPLOAD-ENCRYPTED"


def test_nothing_is_left_behind(standin: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
        mr.check(b"not a zip")
    assert len(made) == 2 and not any(p.exists() for p in made)
    assert set(got) == {*mr.KEPT, "skipped"}  # what is kept: counts, version, date, the fingerprint, skipped lines


def test_the_check_reports_skipped_lines_by_table_line_and_reason(standin: None) -> None:
    bad = fx.tables()["nmain999.txt"] + '"0","99000099","テスト悪","テストワル","1","bad!","E119"\r\n'.encode("cp932")
    got = mr.check(fx.release_zip(drop=("nmain999.txt",), extra={"byomei999/main/nmain999.txt": bad}))
    assert any(s["table"] == "nmain" and s["line"] == len(fx.DISEASES) + 1 and "not a" in s["reason"]
               for s in got["skipped"])  # fmt: skip


@pytest.mark.parametrize(
    ("released", "today", "due"),
    [("2026-06-01", date(2026, 12, 31), False), ("2026-06-01", date(2027, 1, 1), True),
     ("2025-12-01", date(2026, 7, 1), True), ("2026-08-31", date(2027, 3, 30), False),
     ("2026-08-31", date(2027, 3, 31), True), ("", date(2030, 1, 1), False), ("2026年6月", date(2030, 1, 1), False)],
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
