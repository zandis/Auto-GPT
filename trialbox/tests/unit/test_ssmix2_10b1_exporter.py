"""Plan 10 card 10B-1 (D-1262): the SS-MIX2 exporter's declared variants and the shape check written from the
specification's tables (``tools/ssmix2_shape_check.py``). Every rule of the check has a case here that breaks
exactly the shape it names. All data is synthetic (``tools.synth_hospital``, seed 42)."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from tools import ssmix2_export, ssmix2_shape_check, ssmix2_spec_export
from tools.synth_hospital import run as synth_run

# the legacy_vendor output of the 60-patient hospital below, digested on master d28f6c03 (before this card) with
# reportlab's invariant mode: the same bytes, file for file (D-1262 "Byte identity")
MASTER_DIGEST = "7429bd273044081073b6498efb2758925bb40a73f564e3b01225a2ca7d72d1fb"
MASTER_FILES = 1509


@pytest.fixture(scope="module")
def hospital(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("h10b1")
    synth_run(base / "synth", profile="ci", sites="jp-ss:JP:60", ref_date=date(2026, 11, 1), seed=42)
    return base / "synth" / "jp-ss"


@pytest.fixture(scope="module")
def spec(hospital: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("spec") / "ss"
    ssmix2_export.export(hospital, out, variant="spec")
    return out


def _check(root: Path) -> ssmix2_shape_check.Report:
    return ssmix2_shape_check.check(root, root / "extended_storage", ("extended",))


# ----------------------------------------------------------------------------------------------- the variants
def test_the_variant_is_declared_legacy_vendor_by_default_and_an_unknown_one_is_refused(tmp_path: Path) -> None:
    assert ssmix2_export.VARIANTS == ("legacy_vendor", "spec")
    assert ssmix2_export.DEFAULT_VARIANT == "legacy_vendor"
    with pytest.raises(ValueError, match="unknown SS-MIX2 export variant"):
        ssmix2_export.export(tmp_path, tmp_path / "out", variant="vendor-x")
    with pytest.raises(SystemExit):
        ssmix2_export.main(["--csv", str(tmp_path), "--out", str(tmp_path / "o"), "--variant", "x"])
    with pytest.raises(SystemExit):  # vendor byte patterns are not the specification's
        ssmix2_export.main(["--csv", str(tmp_path), "--out", str(tmp_path / "o"), "--variant", "spec", "--hard-cases"])


def test_legacy_vendor_is_byte_identical_to_the_exporter_before_the_card(
    hospital: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reportlab import rl_config

    monkeypatch.setattr(rl_config, "invariant", 1)  # the legacy PDFs otherwise carry their creation time
    ssmix2_export.export(hospital, tmp_path / "default")
    ssmix2_export.export(hospital, tmp_path / "named", variant="legacy_vendor")
    for out in ("default", "named"):
        h = hashlib.sha256()
        files = sorted(p for p in (tmp_path / out).rglob("*") if p.is_file())
        for p in files:
            h.update(p.relative_to(tmp_path / out).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
        assert (len(files), h.hexdigest()) == (MASTER_FILES, MASTER_DIGEST), out


def test_the_spec_variant_passes_the_shape_check_with_no_failure_and_writes_every_type(spec: Path) -> None:
    rep = _check(spec)
    assert rep.total == 0, rep.lines(3)
    assert set(ssmix2_shape_check.TYPES) <= {t for t, n in rep.messages.items() if n}
    assert rep.messages["extended"] > 0


def test_the_spec_variant_carries_history_and_deletions(spec: Path) -> None:
    flags = {p.name[-1] for p in spec.rglob("*_*_*_*_*_*_*") if p.is_file()}
    assert flags == {"0", "1", "2"}
    events = {p.read_bytes().split(b"|")[8].decode() for p in spec.rglob("*_0") if p.is_file()}
    assert {"ADT^A23^ADT_A21", "ADT^A11^ADT_A09", "ADT^A13^ADT_A01", "RDE^O11^RDE_O11"} <= events


def test_the_spec_variant_is_deterministic(hospital: Path, spec: Path, tmp_path: Path) -> None:
    again = tmp_path / "ss"
    ssmix2_export.export(hospital, again, variant="spec")
    a = sorted((p.relative_to(spec), p.read_bytes()) for p in spec.rglob("*") if p.is_file())
    b = sorted((p.relative_to(again), p.read_bytes()) for p in again.rglob("*") if p.is_file())
    assert a == b


def test_the_legacy_vendor_output_fails_the_shape_check(hospital: Path, tmp_path: Path) -> None:
    """The measured size of defect (b) (D-1262 lists it on the 400-patient hospital)."""
    ssmix2_export.export(hospital, tmp_path / "ss")
    rep = _check(tmp_path / "ss")
    assert rep.failures["PPR-01"]["N4"] and rep.failures["PPR-01"]["D1"]  # one file per diagnosis, dated
    assert rep.failures["ADT-00"]["N4"] and rep.failures["ADT-12"]["M2"] and rep.failures["extended"]["X4"]
    assert len({t for t, n in rep.messages.items() if n and t in ssmix2_shape_check.TYPES}) <= 10  # of 26


def test_the_cli_reports_and_exits_by_the_failures(spec: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = [str(spec), "--extended", str(spec / "extended_storage"), "--exclude", "extended"]
    assert ssmix2_shape_check.main(args) == 0
    assert "total rule failures: 0" in capsys.readouterr().out
    assert ssmix2_shape_check.main([str(spec)]) == 1  # the extended folders are not standardised storage
    assert ssmix2_shape_check.main(["--rules", str(spec)]) == 0
    out = capsys.readouterr().out
    assert all(rule in out for rule in ssmix2_shape_check.RULES)


# ----------------------------------------------------------------------------------------------- one case per rule
def _copy_record(spec: Path, dest: Path, typ: str, contains: bytes = b"") -> Path:
    """Copy the first flag-1 file of ``typ`` (holding ``contains``) into ``dest`` at its own place; return it."""
    for p in sorted(spec.rglob(f"*_{typ}_*_1")):
        if contains in p.read_bytes():
            target = dest / p.relative_to(spec)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
            return target
    raise AssertionError(typ)


def _edit(path: Path, segment: str, n: int, value: str) -> None:
    text = path.read_bytes().decode("iso2022_jp")
    out = []
    for s in text.split("\r"):
        f = s.split("|")
        if f[0] == segment:
            i = n - 1 if segment == "MSH" else n
            f += [""] * (i + 1 - len(f))
            f[i] = value
        out.append("|".join(f))
    path.write_bytes("\r".join(out).encode("iso2022_jp"))


def _move(path: Path, new_rel: str, root: Path) -> Path:
    target = root / new_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)
    return target


def _rename(path: Path, part: int, value: str) -> Path:
    parts = path.name.split("_")
    parts[part] = value
    new = path.with_name("_".join(parts))
    path.rename(new)
    return new


def _sibling(path: Path, stamp: str, flag: str) -> Path:
    parts = path.name.split("_")
    parts[4], parts[6] = stamp, flag
    new = path.with_name("_".join(parts))
    shutil.copyfile(path, new)
    return new


def _repid(root: Path, p: Path, pid: str) -> None:
    rel = p.relative_to(root).parts
    name = p.name.replace(rel[2], pid, 1)
    _move(p, f"{pid[0:3]}/{pid[3:6]}/{pid}/{rel[3]}/{rel[4]}/{name}", root)


def _reday(root: Path, p: Path, day: str) -> None:
    rel = p.relative_to(root).parts
    _move(p, f"{'/'.join(rel[:3])}/{day}/{rel[4]}/{p.name.replace('_' + rel[3] + '_', '_' + day + '_', 1)}", root)


def _retype(root: Path, p: Path, typ: str) -> None:
    rel = p.relative_to(root).parts
    _move(p, f"{'/'.join(rel[:4])}/{typ}/{p.name.replace(rel[4], typ, 1)}", root)


Case = tuple[str, str, bytes, Callable[[Path, Path], object]]
STANDARD_CASES: list[Case] = [
    ("T1", "ADT-12", b"", lambda r, p: p.rename(p.parent.parent / p.name)),
    ("T2", "ADT-12", b"", lambda r, p: _repid(r, p, "12345")),
    ("T3", "ADT-12", b"", lambda r, p: _reday(r, p, "20261340")),
    ("T4", "ADT-12", b"", lambda r, p: _retype(r, p, "ADT-99")),
    ("N1", "ADT-12", b"", lambda r, p: p.rename(p.with_name(p.name.rsplit("_", 1)[0]))),
    ("N2", "ADT-12", b"", lambda r, p: _rename(p, 4, "20261399000000000")),
    ("N3", "ADT-12", b"", lambda r, p: _rename(p, 6, "1.txt")),
    ("N4", "ADT-00", b"", lambda r, p: _rename(p, 3, "1")),
    ("N5", "OMP-01", b"", lambda r, p: _rename(p, 3, "OTHER")),
    ("N6", "ADT-12", b"", lambda r, p: _edit(p, "PID", 3, "99999999^^^^PI")),
    ("K1", "ADT-12", b"", lambda r, p: _sibling(p, "20000101000000000", "1")),
    ("K2", "ADT-12", b"", lambda r, p: _sibling(p, "20991231000000000", "0")),
    ("K3", "ADT-12", b"", lambda r, p: _sibling(p, p.name.split("_")[4], "2")),
    ("D1", "ADT-12", b"", lambda r, p: _edit(p, "PV1", 44, "19990101")),
    ("M1", "ADT-12", b"", lambda r, p: _edit(p, "MSH", 9, "ADT^A01^ADT_A01")),
    ("M2", "ADT-12", b"", lambda r, p: _edit(p, "MSH", 9, "ADT^A04^ADT_A04")),
    ("M3", "ADT-12", b"", lambda r, p: _edit(p, "MSH", 11, "T")),
    ("E1", "ADT-12", b"", lambda r, p: p.write_bytes(p.read_bytes().decode("iso2022_jp").encode("utf-8"))),
    ("E2", "ADT-12", b"", lambda r, p: p.write_bytes(p.read_bytes().replace(b"\r", b"\r\n"))),
    ("G1", "ADT-12", b"", lambda r, p: p.write_bytes(b"\r".join(s for s in p.read_bytes().split(b"\r")
                                                               if not s.startswith(b"PV1")))),
    ("F1", "ADT-12", b"", lambda r, p: _edit(p, "PID", 5, "")),
    ("C1", "PPR-01", b"", lambda r, p: p.write_bytes(p.read_bytes().replace(b"^MDCDX2", b"^XYZ"))),
    ("P1", "PPR-01", b"", lambda r, p: _edit(p, "PRB", 1, "ZZ")),
    ("P2", "PPR-01", b"I10", lambda r, p: _edit(p, "PRB", 10, "K29.7^^I10^O^^JHSD0004")),
    ("P3", "PPR-01", b"", lambda r, p: _edit(p, "PRB", 14, "Q^x^HL70241")),
    ("P4", "PPR-01", b"", lambda r, p: (_edit(p, "PRB", 14, "D^x^HL70241"), _edit(p, "PRB", 9, "20260101"))),
    ("P5", "PPR-01", b"", lambda r, p: _edit(p, "PRB", 18, "3^x^JHSD0007")),
    ("R1", "OMP-01", b"^^YJ", lambda r, p: _edit(p, "RXE", 31, "NOTMINE^^99DRG^3943001F1020^^YJ")),
]  # fmt: skip


@pytest.mark.parametrize(("rule", "typ", "contains", "mutate"), STANDARD_CASES, ids=[c[0] for c in STANDARD_CASES])
def test_each_standardised_rule_fails_on_the_shape_it_names(
    spec: Path, tmp_path: Path, rule: str, typ: str, contains: bytes, mutate: Callable[[Path, Path], object]
) -> None:
    root = tmp_path / "ss"
    p = _copy_record(spec, root, typ, contains)
    assert _check(root).total == 0
    mutate(root, p)
    rep = _check(root)
    assert any(rule in c for c in rep.failures.values()), rep.lines(2)


def _copy_document(spec: Path, dest: Path) -> Path:
    folder = sorted(p for p in (spec / "extended_storage").rglob("*_1") if p.is_dir())[0]
    target = dest / "extended_storage" / folder.relative_to(spec / "extended_storage")
    shutil.copytree(folder, target)
    return target


def _ext_move(root: Path, folder: Path, depth_rel: str) -> None:
    target = root / "extended_storage" / depth_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    folder.rename(target)


def _kind(folder: Path, kind: str) -> None:
    new = folder.parent.parent / kind / folder.name
    new.parent.mkdir(parents=True)
    folder.rename(new)


EXTENDED_CASES = [
    ("X1", lambda r, f: [p.rename(f.parents[1] / p.name) for p in list(f.iterdir())]),
    ("X2", lambda r, f: _ext_move(r, f, "/".join([*f.relative_to(r / "extended_storage").parts[:3], "2026x",
                                                     *f.relative_to(r / "extended_storage").parts[4:]]))),
    ("X3", lambda r, f: _kind(f, "L0101^退院時サマリー^99DOC^18842-5^退院時サマリ^XX")),
    ("X4", lambda r, f: [p.rename(f.parent / p.name) for p in list(f.iterdir())]),
    ("X5", lambda r, f: f.rename(f.with_name(f.name.rsplit("_", 1)[0]))),
    ("X6", lambda r, f: [p.rename(p.with_suffix("")) for p in f.iterdir() if p.name != "_contents.xml"]),
    ("X7", lambda r, f: (f / "_contents.xml").write_bytes(b'<?xml version="1.0"?><Contents/>')),
]  # fmt: skip


@pytest.mark.parametrize(("rule", "mutate"), EXTENDED_CASES, ids=[c[0] for c in EXTENDED_CASES])
def test_each_extended_storage_rule_fails_on_the_shape_it_names(
    spec: Path, tmp_path: Path, rule: str, mutate: Callable[[Path, Path], object]
) -> None:
    root = tmp_path / "ss"
    folder = _copy_document(spec, root)
    assert _check(root).total == 0
    mutate(root, folder)
    assert _check(root).failures["extended"][rule], _check(root).lines(2)


def test_an_entity_in_contents_xml_is_refused_not_expanded(spec: Path, tmp_path: Path) -> None:
    root = tmp_path / "ss"
    folder = _copy_document(spec, root)
    (folder / "_contents.xml").write_bytes(b'<!DOCTYPE c [<!ENTITY e "x">]><Contents createDateTime="t"/>')
    assert _check(root).failures["extended"]["X7"] == 1


def test_every_rule_has_its_case_and_its_source() -> None:
    covered = {c[0] for c in STANDARD_CASES} | {c[0] for c in EXTENDED_CASES}
    assert covered == set(ssmix2_shape_check.RULES)
    assert all(v.split(" ")[0] in ("G", "S", "C", "E") for v in ssmix2_shape_check.RULES.values())


def test_the_spec_writer_takes_no_shape_from_the_reader() -> None:
    """The ``spec`` variant and the shape check import nothing of ``adapter.sources.ssmix2`` (card 10B-1)."""
    for module in (ssmix2_spec_export, ssmix2_shape_check):
        text = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert "adapter.sources" not in text and "ssmix2.source" not in text
