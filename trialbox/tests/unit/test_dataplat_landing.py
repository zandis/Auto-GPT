"""L0 landing (spec v4 §5.3 L0, §5.8.2, DP-04; S1-02)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dataplat.common import write_once
from dataplat.landing import LandingError, LandingZone, changed_tables, fingerprint, read_drop, shape
from tb_contracts.dataclass import DataClass
from tb_contracts.landing import ColumnShape, ConnectorKind, ControlTotals, L0BatchManifest

T0 = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)

LAB = "lab_no,mrn,result_value,sample_datetime\r\nL1,M001,1.2,2026-10-01 08:00:00\r\nL2,M002,,2026-10-02 09:30:00\r\n"
PAT = "mrn,birth_date\r\nM001,1950-01-02\r\nM002,1961-03-04\r\n"


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def _drop(d: Path, lab: str = LAB) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "lab.csv").write_text(lab, encoding="utf-8")
    (d / "patient.csv").write_text(PAT, encoding="utf-8")
    return d


@pytest.mark.req("S1-02", "DP-04")
def test_manifest_has_the_s1_02_fields_and_d4_label(tmp_path: Path) -> None:
    src = _drop(tmp_path / "src")
    zone = LandingZone(tmp_path / "l0", Clock(T0))
    res = zone.land("his", read_drop(src).files, extract_time=T0, control_totals={"lab": ControlTotals(rows=2)})
    m = res.manifest
    assert res.created
    assert (m.source, m.kind, m.extract_time, m.rows) == ("his", ConnectorKind.FILE_DROP, T0, 4)
    assert m.bytes == len(LAB.encode()) + len(PAT.encode())
    lab = m.object_for("lab")
    assert lab is not None and lab.sha256 == hashlib.sha256(LAB.encode()).hexdigest()
    assert lab.rows == 2 and lab.encoding == "utf-8"
    assert m.schema_fingerprint and lab.schema_fingerprint
    assert m.data_class.data_class == DataClass.D4  # L0 raw batches are D4 (§5.2 Z-IDN)
    # the manifest on disk is canonical JSON and round-trips
    on_disk = (res.path / "manifest.json").read_text(encoding="utf-8")
    assert L0BatchManifest.model_validate_json(on_disk) == m
    assert json.loads(on_disk)["control_totals"]["lab"]["rows"] == 2
    # objects are stored byte for byte (no transformation)
    assert zone.object_path(m, lab).read_bytes() == LAB.encode()


@pytest.mark.req("S1-02", "DP-04")
def test_relanding_the_same_bytes_is_idempotent(tmp_path: Path) -> None:
    src = _drop(tmp_path / "src")
    zone = LandingZone(tmp_path / "l0", Clock(T0))
    first = zone.land("his", read_drop(src).files)
    zone.clock = Clock(T0 + timedelta(hours=5))
    again = zone.land("his", read_drop(src).files)
    assert not again.created
    assert again.manifest == first.manifest  # same batch id, same landed_at: nothing rewritten
    assert len(zone.batches("his")) == 1
    # the same bytes delivered with other source totals are another batch (the totals are part of the identity)
    other = zone.land("his", read_drop(src).files, control_totals={"lab": ControlTotals(rows=3)})
    assert other.created and other.manifest.batch_id != first.manifest.batch_id


@pytest.mark.req("S1-02", "DP-04")
def test_one_byte_change_is_detected(tmp_path: Path) -> None:
    zone = LandingZone(tmp_path / "l0", Clock(T0))
    a = zone.land("his", read_drop(_drop(tmp_path / "a")).files).manifest
    b = zone.land("his", read_drop(_drop(tmp_path / "b", LAB.replace("1.2", "1.3"))).files).manifest
    assert a.batch_id != b.batch_id
    assert changed_tables(a, b) == ["lab"]
    # an object altered in place after landing is caught by verify() and refused on re-landing
    obj = a.object_for("patient")
    assert obj is not None
    path = zone.object_path(a, obj)
    data = bytearray(path.read_bytes())
    data[-3] ^= 0x01
    path.chmod(0o644)
    path.write_bytes(bytes(data))
    assert zone.verify(a) == ["objects/patient.csv"]
    with pytest.raises(LandingError, match="changed in place"):
        zone.land("his", read_drop(tmp_path / "a").files)


@pytest.mark.req("DP-04")
def test_objects_are_write_once(tmp_path: Path) -> None:
    p = tmp_path / "x" / "obj.csv"
    write_once(p, b"a")
    assert p.stat().st_mode & 0o222 == 0
    with pytest.raises(FileExistsError):
        write_once(p, b"b")
    assert p.read_bytes() == b"a"


@pytest.mark.req("S1-02", "DP-04")
def test_raw_retention_is_90_days_with_legal_hold(tmp_path: Path) -> None:
    clock = Clock(T0)
    zone = LandingZone(tmp_path / "l0", clock)
    old = zone.land("his", read_drop(_drop(tmp_path / "a")).files).manifest
    held = zone.land(
        "his", read_drop(_drop(tmp_path / "b", LAB + "L3,M001,2.0,2026-10-03 10:00:00\r\n")).files
    ).manifest
    zone.hold(held, "LH-2026-001")
    clock.at = T0 + timedelta(days=89)
    assert zone.prune() == []
    clock.at = T0 + timedelta(days=91)
    newer = zone.land("his", read_drop(_drop(tmp_path / "c", LAB.replace("M002", "M003"))).files).manifest
    assert zone.prune() == [old.batch_id]
    left = {m.batch_id for m in zone.batches("his")}
    assert left == {held.batch_id, newer.batch_id}
    assert not zone.batch_dir("his", old.batch_id).exists()
    zone.release_hold(held)
    assert zone.prune() == [held.batch_id]


@pytest.mark.req("S1-02")
def test_schema_fingerprint_follows_section_5_8_2(tmp_path: Path) -> None:
    rows, enc, cols = shape(LAB.encode(), "lab.csv")
    assert (rows, enc) == (2, "utf-8")
    assert [(c.name, c.type, c.nullable) for c in cols] == [
        ("lab_no", "string", False),
        ("mrn", "string", False),
        ("result_value", "decimal", True),
        ("sample_datetime", "timestamp", False),
    ]
    expected = sorted([c.name, c.type, c.nullable] for c in cols)
    canonical = json.dumps(expected, separators=(",", ":"), ensure_ascii=False)
    assert fingerprint(cols) == hashlib.sha256(canonical.encode()).hexdigest()
    # column order does not matter, a type change does
    assert fingerprint(list(reversed(cols))) == fingerprint(cols)
    drifted = [ColumnShape(name=c.name, type="string", nullable=c.nullable) for c in cols]
    assert fingerprint(drifted) != fingerprint(cols)


def test_ndjson_objects_are_shaped_by_top_level_keys(tmp_path: Path) -> None:
    body = b'{"resourceType":"Patient","id":"a","gender":"male"}\n{"resourceType":"Patient","id":"b"}\n'
    rows, _, cols = shape(body, "Patient.ndjson")
    assert rows == 2
    assert {c.name: (c.type, c.nullable) for c in cols} == {
        "gender": ("string", True),
        "id": ("string", False),
        "resourceType": ("string", False),
    }
