"""10G-6 (review 16-23, ASVS 12.1.2; D-1102): a rule-set zip is checked from its central directory before any member
is read: members, each member's and the total uncompressed size, the expansion ratio and the names. Each cap at the
limit, one over and far over. The zips are built here and are a few kB: the large sizes are declared in the central
directory, not stored."""

from __future__ import annotations

import io
import stat
import struct
import warnings
import zipfile
from pathlib import Path

import pytest
from criteria_compiler.import_ruleset import ImportRefused, install, read_zip
from criteria_compiler.repo import RulesetRepo
from orchestrator.clients import StepFailed
from orchestrator.scenarios import cohort
from tb_common import zipcap
from tb_common.zipcap import ZipRefused, check_ruleset_zip

pytestmark = [pytest.mark.nodb]
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = b"id: X\nversion: 1.0.0\nstatus: approved\nequivalence: {overall_pct: 100}\n"

Entry = tuple[str, int, int]  # name, declared uncompressed size, declared compressed size


def declared_zip(entries: list[Entry], mode: int | None = None) -> bytes:
    """A stored zip of empty members whose central directory declares the given sizes (nothing large is written)."""
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a duplicate name is the point of one case
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for name, _u, _c in entries:
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                if mode is not None:
                    info.external_attr = mode << 16
                z.writestr(info, b"")
    data = bytearray(buf.getvalue())
    at = data.index(b"PK\x01\x02")
    for _name, u, c in entries:  # each central directory record: compressed size at +20, uncompressed at +24
        assert data[at : at + 4] == b"PK\x01\x02"
        struct.pack_into("<II", data, at + 20, c, u)
        n, x, k = struct.unpack_from("<HHH", data, at + 28)
        at += 46 + n + x + k
    return bytes(data)


def check(data: bytes) -> str:
    """'ok', or the refusal's code; a member read while checking fails the test."""

    def refuse(*_a: object, **_k: object) -> None:
        raise AssertionError("a member was read before the caps were checked")

    with zipfile.ZipFile(io.BytesIO(data)) as z, pytest.MonkeyPatch.context() as mp:
        mp.setattr(zipfile.ZipFile, "open", refuse)
        try:
            check_ruleset_zip(z)
        except ZipRefused as exc:
            return exc.code
    return "ok"


def test_the_caps_are_the_stated_values() -> None:
    assert zipcap.RULESET_ZIP_MAX_MEMBERS == 2000
    assert zipcap.RULESET_ZIP_MAX_MEMBER_BYTES == 100_000_000
    assert zipcap.RULESET_ZIP_MAX_TOTAL_BYTES == 200_000_000
    assert zipcap.RULESET_ZIP_MAX_RATIO == 200
    text = (ROOT / "docs/decisions/D-1102-rule-set-zip-caps.md").read_text(encoding="utf-8")
    for phrase in ("2,000 members", "100,000,000 bytes", "200,000,000 bytes", "200 times"):
        assert phrase in text


@pytest.mark.parametrize(("n", "want"), [(2000, "ok"), (2001, "zip.members"), (20_000, "zip.members")])
def test_members_at_one_over_and_far_over(n: int, want: str) -> None:
    assert check(declared_zip([(f"X/v/{i}.json", 0, 0) for i in range(n)])) == want


@pytest.mark.parametrize(("size", "want"), [(100_000_000, "ok"), (100_000_001, "zip.member_size"),
                                            (1_000_000_000, "zip.member_size")])  # fmt: skip
def test_member_size_at_one_over_and_far_over(size: int, want: str) -> None:
    assert check(declared_zip([("X/sql/a.sql", size, size // 100)])) == want


@pytest.mark.parametrize(("extra", "want"), [(0, "ok"), (1, "zip.total_size"), (1_800_000_000, "zip.total_size")])
def test_total_size_at_one_over_and_far_over(extra: int, want: str) -> None:
    entries = [("X/a", 100_000_000, 1_000_000), ("X/b", 100_000_000, 1_000_000)]
    entries += [(f"X/c{i}", min(extra - i * 90_000_000, 90_000_000), 900_000) for i in range(-(-extra // 90_000_000))]
    assert check(declared_zip(entries)) == want


@pytest.mark.parametrize(("size", "want"), [(2_000_000, "ok"), (2_000_001, "zip.ratio"), (20_000_000, "zip.ratio")])
def test_ratio_at_one_over_and_far_over(size: int, want: str) -> None:
    assert check(declared_zip([("X/valuesets/v.json", size, 10_000)])) == want


def test_a_small_member_is_not_judged_by_ratio() -> None:
    assert check(declared_zip([("X/a", 1_000_000, 1)])) == "ok"


def test_a_zip_bomb_fixture_is_refused_before_reading() -> None:
    """A real deflated member: 5 MB of one byte in a few kB."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("X/manifest.yaml", MANIFEST)
        z.writestr("X/sql/screen.sql", b"\0" * 5_000_000)
    assert len(buf.getvalue()) < 20_000
    assert check(buf.getvalue()) == "zip.ratio"


@pytest.mark.parametrize(
    ("name", "want"),
    [("/X/manifest.yaml", "zip.name"), ("X/../../etc/x", "zip.name"), ("X\\..\\x", "zip.name"),
     ("C:x", "zip.name"), ("X/ok.sql", "ok")],
)  # fmt: skip
def test_unsafe_names(name: str, want: str) -> None:
    info = zipfile.ZipInfo(name)
    try:
        zipcap.check_infos([info])
        got = "ok"
    except ZipRefused as exc:
        got = exc.code
    assert got == want


def test_a_symbolic_link_and_a_duplicate_are_refused() -> None:
    assert check(declared_zip([("X/link", 4, 4)], mode=stat.S_IFLNK | 0o777)) == "zip.symlink"
    assert check(declared_zip([("X/a.sql", 1, 1), ("X/a.sql", 1, 1)])) == "zip.duplicate"


def test_the_offline_install_refuses_and_writes_nothing(tmp_path: Path) -> None:
    repo = RulesetRepo(tmp_path / "repo")
    before = sorted(repo.refs.keys())
    bomb = declared_zip([("X/manifest.yaml", 0, 0), ("X/sql/a.sql", 100_000_000, 1_000_000),
                         ("X/sql/b.sql", 100_000_000, 1_000_000), ("X/sql/c.sql", 1, 1)])  # fmt: skip
    with pytest.raises(ImportRefused, match="200,000,000 bytes"):
        install(repo, bomb, "update:test")
    assert sorted(repo.refs.keys()) == before
    assert not (tmp_path / "repo" / "X").exists()


def test_the_offline_install_still_reads_a_good_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("X/manifest.yaml", MANIFEST)
        z.writestr("X/sql/screen.sql", b"SELECT 1\n")
    rid, files, _m = read_zip(buf.getvalue())
    assert rid == "X" and set(files) == {"manifest.yaml", "sql/screen.sql"}


def test_a_draft_package_is_refused_before_anything_is_written(monkeypatch: pytest.MonkeyPatch) -> None:
    import tempfile

    made: list[str] = []

    def mkdtemp(**_k: object) -> str:
        made.append("dir")
        return "/nonexistent"

    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
    with pytest.raises(StepFailed, match="draft package refused"):
        cohort.load_draft(declared_zip([(f"X/{i}", 0, 0) for i in range(2001)]))
    assert made == []
