"""Card 10B-2b (D-1252) part A: supersession by the guideline, across files of one day and across days.

The rules are the SS-MIX2 標準化ストレージ 構成の説明と構築ガイドライン Ver.1.2j (JAMI, 2026-08-14), 3.1.2 and
3.1.4, as D-1252 states them (R1 to R8), and lane J's rulings on what the guideline does not settle (P1 to P9). Every
storage is synthetic (``tests/ssmix2_probes.py`` writes the messages). Each test fails on #1095's head unless it says
it is a guard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import AdapterConfig, run_ingest
from adapter.sources.ssmix2.source import Ssmix2Source

from tests import ssmix2_probes as pb
from tests.ssmix2_probes import DAY_A, DAY_B, DAY_C, P1, F, omp, ppr, prb, stamp

ROOT = Path(__file__).resolve().parents[2]
JP_MAPPING = ROOT / "services/adapter/mapping/jp_core/ssmix2_site.yaml"
EMPTY: dict[str, dict[str, dict[str, str]]] = {"medis": {}, "jlac10": {}, "yj": {}}
BAD = b"\x00\xff not hl7"
A = prb("99990001", "肺炎", "DX001")
B = prb("99990002", "胃炎", "DX002", icd10="K297")


def _read(root: Path, table: str, order_key: str = "per_day") -> tuple[dict[str, Row], list[str], Ssmix2Source]:
    src = Ssmix2Source(root, licensed=EMPTY, order_key=order_key)
    key = {"diagnosis": "diag_no", "medication": "rx_no"}[table]
    live = {str(r[key]): r for r in src.rows(table, table, None, None)}
    dead = sorted(str(r[key]) for r in src.deleted_rows(table, table, None, None))
    return live, dead, src


Row = dict[str, Any]


def _rx(no: str, day: str, n: int, flag: str, *, orc1: str = "NW", raw: bytes | None = None, **kw: Any) -> F:
    return F(P1, day, "OMP-01", no, stamp(day, n), flag, omp(P1, no, day, [(orc1, "1", "999000001")]), raw=raw, **kw)


def _snap(n: int, flag: str, body: list[str], *, day: str = "-", raw: bytes | None = None, dept: str = "01") -> F:
    return F(P1, day, "PPR-01", "ALL9", stamp(DAY_A, n), flag, ppr(P1, body), raw=raw, dept=dept)


def _put(root: Path, *files: F) -> None:
    for f in files:
        f.write(root)


# ------------------------------------------------------------------------------------------------ resolve (R3 to R6)
def _sf(root: Path, n: int, flag: str, dept: str = "01") -> Any:
    from adapter.sources.ssmix2.source import parse_name

    f = _rx("RX1", DAY_A, n, flag, dept=dept)
    f.write(root)
    return parse_name(
        root / P1[0:3] / P1[3:6] / P1 / DAY_A / "OMP-01" / f"{P1}_{DAY_A}_OMP-01_RX1_{f.stamp}_{dept}_{flag}"
    )


@pytest.mark.parametrize(
    ("flags", "state"),
    [(("2", "1"), "live"), (("1", "0"), "deleted"), (("1", "2"), "past"), (("0", "1"), "live"), (("1", "1"), "live")],
)
def test_resolve_takes_the_newest_by_its_stamp_and_names_its_state(
    tmp_path: Path, flags: tuple[str, str], state: str
) -> None:
    """Guard of the new function (not on #1095's head): G 3.1.4(2)⑥, R3 to R6, P1 to P3."""
    from adapter.sources.ssmix2.source import resolve

    vs = [_sf(tmp_path, i, f) for i, f in enumerate(flags)]
    got, newest, candidates, older = resolve(vs)
    assert got == state and newest == vs[-1] and older == vs[:-1]
    if flags == ("0", "1"):
        assert candidates == []  # nothing before the deletion could be in force


def test_a_tie_with_a_deletion_is_a_deletion_and_two_live_files_with_one_stamp_are_a_tie(tmp_path: Path) -> None:
    from adapter.sources.ssmix2.source import resolve

    a, b = _sf(tmp_path / "x", 3, "1", "01"), _sf(tmp_path / "x", 3, "0", "02")
    assert resolve([b, a])[0] == "deleted"
    c, d = _sf(tmp_path / "y", 3, "1", "01"), _sf(tmp_path / "y", 3, "1", "02")
    assert resolve([c, d])[0] == "tie"


def test_key_part_is_one_normalisation() -> None:
    from adapter.sources.ssmix2.source import key_part

    assert key_part("ＲＸ０１") == key_part("RX01") == key_part(" RX01 ") == "RX01"
    assert key_part("rx01") != key_part("RX01")  # case is kept: the guideline says nothing that would fold it


# ------------------------------------------------------------------------------------------------ P3, P4, P5
@pytest.mark.parametrize("why", ["garbage", "another patient", "flag 2", "tie"])
def test_an_order_with_no_version_in_force_is_unknown_never_the_older_version(tmp_path: Path, why: str) -> None:
    older = _rx("RX1", DAY_A, 0, "1")
    newer = {
        "garbage": _rx("RX1", DAY_A, 1, "1", raw=BAD),
        "another patient": F(
            P1, DAY_A, "OMP-01", "RX1", stamp(DAY_A, 1), "1", omp("10000002", "RX1", DAY_A, [("NW", "1", "9")])
        ),
        "flag 2": _rx("RX1", DAY_A, 1, "2"),
        "tie": _rx("RX1", DAY_A, 0, "1", dept="02"),
    }[why]
    _put(tmp_path, older, newer)
    live, dead, src = _read(tmp_path, "medication")
    assert live["RX1"]["status"] == "unknown"
    assert live["RX1"]["version_note"]
    assert dead == []
    assert any("read as unknown" in k for k in src.stats)


@pytest.mark.parametrize("why", ["garbage", "duplicate number", "flag 2", "tie", "another patient"])
def test_a_snapshot_with_no_version_in_force_makes_every_diagnosis_unknown(tmp_path: Path, why: str) -> None:
    older = _snap(0, "1", [A, B])
    newer = {
        "garbage": _snap(1, "1", [], raw=BAD),
        "duplicate number": _snap(1, "1", [A, prb("99990002", "胃炎", "DX001")]),
        "flag 2": _snap(1, "2", [A]),
        "tie": _snap(0, "1", [A], dept="02"),
        "another patient": F(P1, "-", "PPR-01", "ALL9", stamp(DAY_A, 1), "1", ppr("10000002", [A, B])),
    }[why]
    _put(tmp_path, older, newer)
    live, dead, _src = _read(tmp_path, "diagnosis")
    assert {k: (r["status"], r["suspected"]) for k, r in live.items()} == {"DX001": ("U", "U"), "DX002": ("U", "U")}
    assert dead == []


def test_a_guideline_storage_reads_the_newest_as_in_force_and_drops_what_it_dropped(tmp_path: Path) -> None:
    """The guideline's own procedure (G 3.1.4(2)⑥1)): the older version renamed to 2, the newer written as 1. On
    #1095's head a flag-2 snapshot was left out of the supersession, so a diagnosis the newer one dropped stayed
    live."""
    _put(tmp_path, _snap(0, "2", [A, B]), _snap(1, "1", [A]))
    live, dead, _src = _read(tmp_path, "diagnosis")
    assert {k: (r["status"], r["suspected"]) for k, r in live.items()} == {"DX001": ("A", "")}
    assert dead == ["DX002"]


# ------------------------------------------------------------------------------------------------ R5, P2: deletions
def test_a_deletion_tombstones_every_line_any_older_version_named(tmp_path: Path) -> None:
    two = [("NW", "1", "999000001"), ("NW", "2", "999000002")]
    _put(
        tmp_path,
        F(P1, DAY_A, "OMP-01", "RX1", stamp(DAY_A, 0), "1", omp(P1, "RX1", DAY_A, two)),
        F(P1, DAY_A, "OMP-01", "RX1", stamp(DAY_A, 1), "1", omp(P1, "RX1", DAY_A, two[:1])),
        F(P1, DAY_A, "OMP-01", "RX1", stamp(DAY_A, 2), "0", omp(P1, "RX1", DAY_A, two[:1])),
    )
    live, dead, src = _read(tmp_path, "medication")
    assert live == {}
    assert "RX1#2:999000002" in dead and "RX1" in dead  # the line only the oldest version held is deleted too
    assert src.stats["OMP-01:deleted while an older valid file remains"] == 1


def test_a_diagnosis_a_deleted_middle_snapshot_removed_stays_removed_when_a_newer_snapshot_lacks_it(
    tmp_path: Path,
) -> None:
    """Guard (passes on both heads): night 1 stores [A, B]; on night 2 a deletion and a newer snapshot [B] arrive
    together: A must leave the lake."""
    files = [_snap(0, "1", [A, B]), _snap(1, "0", [A, B]), _snap(2, "1", [B])]
    files[1].night = files[2].night = 1
    case = pb.Case("middle deleted", "G", "diagnosis", files, {f"{P1}/DX001": "GONE", f"{P1}/DX002": "CA"})
    assert pb.run_case(case, tmp_path) == case.expect


def test_a_delete_whose_patient_is_not_certain_leaves_the_older_version_unknown(tmp_path: Path) -> None:
    other = F(P1, DAY_A, "OMP-01", "RX1", stamp(DAY_A, 1), "0", omp("10000002", "RX1", DAY_A, [("CA", "1", "9")]))
    _put(tmp_path, _rx("RX1", DAY_A, 0, "1"), other)
    live, dead, _src = _read(tmp_path, "medication")
    assert live["RX1"]["status"] == "unknown" and dead == []


# ------------------------------------------------------------------------------------------------ P6: across days
def test_a_delete_on_another_day_makes_the_order_unknown_and_never_deletes_it(tmp_path: Path) -> None:
    _put(tmp_path, _rx("RX1", DAY_A, 0, "1"), _rx("RX1", DAY_B, 0, "0", orc1="CA"))
    live, dead, src = _read(tmp_path, "medication")
    assert {k: r["status"] for k, r in live.items()} == {f"RX1@{DAY_A}": "unknown"}
    assert set(dead) == {f"RX1@{DAY_B}", "RX1"}  # the plain key an earlier night may hold is tombstoned
    assert src.stats["OMP-01:delete filed under another day"] == 1


def test_the_newer_day_is_in_force_and_the_older_day_unknown(tmp_path: Path) -> None:
    _put(tmp_path, _rx("RX1", DAY_A, 0, "1"), _rx("RX1", DAY_B, 0, "1"), _rx("RX1", DAY_C, 0, "1", raw=BAD))
    live, _dead, _src = _read(tmp_path, "medication")
    # day C's file cannot be read: it names nothing, and no other day is in force while it is newer
    assert {k: r["status"] for k, r in live.items()} == {f"RX1@{DAY_A}": "unknown", f"RX1@{DAY_B}": "unknown"}


def test_under_unique_the_days_are_one_record_and_the_newest_decides(tmp_path: Path) -> None:
    """Guard (passes on both heads): the site's declared exception (D-1000)."""
    _put(tmp_path, _rx("RX1", DAY_A, 0, "1"), _rx("RX1", DAY_B, 0, "0", orc1="CA"))
    live, dead, _src = _read(tmp_path, "medication", order_key="unique")
    assert live == {} and dead == ["RX1"]


def test_the_key_of_a_number_filed_on_a_second_day_never_leaves_its_first_key_live(tmp_path: Path) -> None:
    case = pb.Case("two nights", "D", "medication",
                   [_rx("RX1", DAY_A, 0, "1"), _rx("RX1", DAY_B, 0, "1", night=1)],
                   {"10000001/RX1": "GONE", f"10000001/RX1@{DAY_A}": "NC", f"10000001/RX1@{DAY_B}": "CA"})  # fmt: skip
    got = pb.run_case(case, tmp_path)
    assert got == case.expect


# ------------------------------------------------------------------------------------------------ P8: key widths
@pytest.mark.parametrize("wide", ["ＲＸ１", "RX１", "RX1 "])
def test_a_delete_written_in_another_width_reaches_its_record(tmp_path: Path, wide: str) -> None:
    newer = F(P1, DAY_A, "OMP-01", wide, stamp(DAY_A, 1), "0", omp(P1, "RX1", DAY_A, [("CA", "1", "999000001")]))
    _put(tmp_path, _rx("RX1", DAY_A, 0, "1"), newer)
    live, dead, src = _read(tmp_path, "medication")
    assert live == {} and dead == ["RX1"]
    assert src.stats["storage:order number written in another width or with a blank (one key)"] == 1


# ------------------------------------------------------------------------------------------------ P9: PPR layouts
def _per(no: str, day: str, n: int, flag: str, body: list[str]) -> F:
    return F(P1, day, "PPR-01", no, stamp(DAY_A, n), flag, ppr(P1, body))


def test_a_per_diagnosis_file_older_than_the_snapshot_is_superseded_by_it(tmp_path: Path) -> None:
    _put(tmp_path, _per("DX001", DAY_A, 0, "1", [A]), _snap(1, "1", [B]))
    live, dead, src = _read(tmp_path, "diagnosis")
    assert set(live) == {"DX002"} and dead == ["DX001"]
    assert src.stats["PPR-01:per-diagnosis file superseded by a newer snapshot"] == 1


def test_a_per_diagnosis_file_newer_than_the_snapshot_is_unknown(tmp_path: Path) -> None:
    _put(tmp_path, _snap(0, "1", [A, B]), _per("DX001", DAY_A, 1, "1", [A]))
    live, _dead, _src = _read(tmp_path, "diagnosis")
    assert (live["DX001"]["status"], live["DX001"]["suspected"]) == ("U", "U")
    assert (live["DX002"]["status"], live["DX002"]["suspected"]) == ("A", "")


@pytest.mark.parametrize("second", [("DX001", DAY_B), ("DX009", DAY_A)])
def test_one_diagnosis_number_in_two_records_is_unknown(tmp_path: Path, second: tuple[str, str]) -> None:
    _put(tmp_path, _per("DX001", DAY_A, 0, "1", [A]), _per(second[0], second[1], 1, "1", [A]))
    src = Ssmix2Source(tmp_path, licensed=EMPTY)
    rows = list(src.rows("diagnosis", "diagnosis", None, None))
    assert {(r["status"], r["suspected"]) for r in rows} == {("U", "U")}


# ------------------------------------------------------------------------------------------------ delta
def test_a_row_read_as_unknown_passes_the_delta_window(tmp_path: Path) -> None:
    _put(tmp_path, _rx("RX1", DAY_A, 0, "1"), _rx("RX1", DAY_A, 1, "1", raw=BAD))
    src = Ssmix2Source(tmp_path, licensed=EMPTY)
    rows = list(src.rows("medication", "medication", "order_date", "2026-12-31"))
    assert [(r["rx_no"], r["status"]) for r in rows] == [("RX1", "unknown")]


# ------------------------------------------------------------------------------------------------ the lake (lane J)
def _cfg(tmp_path: Path) -> AdapterConfig:
    sec = tmp_path / "secrets"
    sec.mkdir(exist_ok=True)
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    return AdapterConfig(lake_dir=tmp_path / "lake", secrets_dir=sec, mapping_path=JP_MAPPING, site_id="JP-T",
                         tz="Asia/Tokyo", audit_dir=tmp_path / "audit", validation_max_pct=100.0)  # fmt: skip


def _codes(res: dict[str, Any], element: str) -> set[str]:
    return {str(c.get("code")) for c in (res.get(element) or {}).get("coding", [])}


@pytest.mark.parametrize("delta", [False, True])
def test_the_lake_row_of_an_earlier_night_changes_from_confirmed_to_unknown(tmp_path: Path, delta: bool) -> None:
    """Lane J's ruling on P3 / P4: on the night an unreadable newer file arrives, the confirmed, active diagnosis and
    the active order the lake held from the night before become unconfirmed and unknown, through the adapter and
    the site mapping (not only in the reader's rows)."""
    root = tmp_path / "storage"
    _put(root, _snap(0, "1", [A]), _rx("RX1", DAY_A, 0, "1"))
    # 150 other synthetic patients, readable: one unreadable file is then under the share of a table's files that
    # holds the night (QUARANTINE_MAX_PCT, 1 %), as in a real storage
    for i in range(150):
        other = f"1000{i + 100:04d}"
        # their own diagnosis and order numbers: the lake's ids are made of the key column (``diag_no``, ``rx_no``)
        filler = [prb("99990002", "胃炎", f"DF{i:03d}", icd10="K297")]
        F(other, "-", "PPR-01", "ALL9", stamp(DAY_A, 0), "1", ppr(other, filler)).write(root)
        rx = f"RF{i:03d}"
        F(other, DAY_A, "OMP-01", rx, stamp(DAY_A, 0), "1", omp(other, rx, DAY_A, [("NW", "1", "999000009")])).write(
            root
        )
    cfg = _cfg(tmp_path)
    first = run_ingest(cfg, "ssmix2", str(root), snapshot="2026-10-01", load_fhir=False, rebuild_lake=False,
                       validate=False)  # fmt: skip
    assert not first.errors, first.errors
    snap1 = snapshot_dir(cfg.lake_dir, "2026-10-01")
    (cond1,) = [c for c in read_type(snap1, "Condition") if "99990001" in json.dumps(c)]
    assert _codes(cond1, "clinicalStatus") == {"active"} and not _codes(cond1, "verificationStatus")
    (med1,) = [m for m in read_type(snap1, "MedicationRequest") if "999000001" in json.dumps(m)]
    assert med1["status"] == "active"

    _put(root, _snap(1, "1", [], raw=BAD), _rx("RX1", DAY_A, 1, "1", raw=BAD))
    second = run_ingest(cfg, "ssmix2", str(root), snapshot="2026-10-02", load_fhir=False, rebuild_lake=False,
                        validate=False, since="2026-10-01" if delta else None)  # fmt: skip
    assert not second.errors, second.errors
    snap2 = snapshot_dir(cfg.lake_dir, "2026-10-02")
    (cond2,) = [c for c in read_type(snap2, "Condition") if "99990001" in json.dumps(c)]
    assert cond2["id"] == cond1["id"]
    assert "active" not in _codes(cond2, "clinicalStatus") and "unconfirmed" in _codes(cond2, "verificationStatus")
    (med2,) = [m for m in read_type(snap2, "MedicationRequest") if "999000001" in json.dumps(m)]
    assert med2["id"] == med1["id"] and med2["status"] == "unknown"
    assert json.dumps(cond2, ensure_ascii=False).count("肺炎") >= 1  # the text is kept


# ------------------------------------------------------------------------------------------------ the probe sets
def test_the_supersession_probe_set_reads_every_labelled_id_right() -> None:
    report = pb.measure({"supersession": pb.supersession_cases()})
    bad = [(r["name"], r["expect"], r["got"]) for r in report["supersession"] if r["wrong"]]
    assert bad == []
