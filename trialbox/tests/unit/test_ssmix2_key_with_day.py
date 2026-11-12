"""NEW-DIN-4 (DIN-004): the current version of an SS-MIX2 file is chosen per (patient, day, type, order number).

Before: the day was not part of the key. An order number used again on another day replaced the earlier order
(18 results gone, no count, no message). All data is synthetic.
"""

from __future__ import annotations

from pathlib import Path

from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir

MRN = "10000001"


def _store(
    root: Path, typ: str, order: str, day: str, segs: list[str], stamp: str = "000000000", flag: str = "1"
) -> None:
    d = storage_dir(root, MRN, day, typ)
    d.mkdir(parents=True, exist_ok=True)
    body = "\r".join([f"MSH|^~\\&|HIS||TB||{day}||X|1|P|2.5||||||~ISO IR87", *segs]) + "\r"
    (d / f"{MRN}_{day}_{typ}_{order}_{day}{stamp}_-_{flag}").write_bytes(body.encode("iso2022_jp"))


def _obx(n: int, value: str, day: str, uid: str = "") -> str:
    obx = ["OBX", str(n), "NM", "3D046000001906202^HbA1c^JC10", "", value, "%", *[""] * 15]
    obx[11], obx[14], obx[21] = "F", f"{day}090000", uid
    return "|".join(obx)


def _labs(root: Path) -> list[dict[str, str]]:
    src = Ssmix2Source(root, licensed={})
    rows = [dict(r) for r in src.rows("lab", "OML-11", None, None)]
    _labs.stats = dict(src.stats)  # type: ignore[attr-defined]
    return rows


def test_an_order_number_used_again_on_another_day_does_not_replace_the_earlier_order(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _store(root, "OML-11", "O1", "20261001", ["OBR|1|O1", _obx(1, "6.0", "20261001"), _obx(2, "6.1", "20261001")])
    _store(root, "OML-11", "O1", "20261015", ["OBR|1|O1", _obx(1, "7.5", "20261015")])
    rows = _labs(root)
    assert sorted((r["lab_no"], r["result_value"]) for r in rows) == [
        ("O1-1", "6.0"), ("O1-2", "6.1"), ("O1@20261015-1", "7.5")]  # fmt: skip
    assert _labs.stats["OML-11:order number used on another day"] == 1  # type: ignore[attr-defined]


def test_the_first_days_results_keep_the_ids_they_had(tmp_path: Path) -> None:
    """The earlier day is read as if it were alone: a night before the number came back made the same ids."""
    root = tmp_path / "s"
    _store(root, "OML-11", "O1", "20261001", ["OBR|1|O1", _obx(1, "6.0", "20261001")])
    alone = {r["lab_no"] for r in _labs(root)}
    _store(root, "OML-11", "O1", "20261015", ["OBR|1|O1", _obx(1, "7.5", "20261015")])
    assert alone == {"O1-1"} and alone < {r["lab_no"] for r in _labs(root)}


def test_a_result_with_its_own_id_keeps_it_on_every_day(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _store(root, "OML-11", "O1", "20261001", ["OBR|1|O1", _obx(1, "6.0", "20261001", "U1")])
    _store(root, "OML-11", "O1", "20261015", ["OBR|1|O1", _obx(1, "7.5", "20261015", "U2")])
    assert sorted(r["lab_no"] for r in _labs(root)) == ["U1", "U2"]


def test_within_one_day_the_newest_version_still_wins_and_a_delete_removes_that_day_only(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _store(root, "OML-11", "O1", "20261001", ["OBR|1|O1", _obx(1, "6.0", "20261001")], stamp="080000000")
    _store(root, "OML-11", "O1", "20261001", ["OBR|1|O1", _obx(1, "6.4", "20261001")], stamp="090000000")
    _store(root, "OML-11", "O1", "20261015", ["OBR|1|O1", _obx(1, "7.5", "20261015")], stamp="080000000")
    assert sorted(r["result_value"] for r in _labs(root)) == ["6.4", "7.5"]
    _store(root, "OML-11", "O1", "20261015", ["OBR|1|O1", _obx(1, "7.5", "20261015")], stamp="100000000", flag="0")
    assert [r["result_value"] for r in _labs(root)] == ["6.4"]  # the first day's order is still there


def test_nothing_is_counted_when_no_number_repeats(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _store(root, "OML-11", "O1", "20261001", ["OBR|1|O1", _obx(1, "6.0", "20261001")])
    _store(root, "OML-11", "O2", "20261015", ["OBR|1|O2", _obx(1, "7.5", "20261015")])
    assert sorted(r["lab_no"] for r in _labs(root)) == ["O1-1", "O2-1"]
    assert not [k for k in _labs.stats if "another day" in k]  # type: ignore[attr-defined]
