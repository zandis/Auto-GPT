"""NEW-DIN-4 (DIN-004, D-594): whether an SS-MIX2 order number is used again on another day is declared by the site
(``TB_SSMIX2_ORDER_NUMBERS``) and counted either way. All data is synthetic."""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.sources.ssmix2.source import Ssmix2Source, storage_dir

MRN = "10000001"
D1, D2 = "20261001", "20261015"
COUNT = "OML-11:order number on several days"


def _store(
    root: Path, typ: str, order: str, day: str, segs: list[str], stamp: str = "00" + "0000000", flag: str = "1"
) -> None:
    d = storage_dir(root, MRN, day, typ)
    d.mkdir(parents=True, exist_ok=True)
    body = "\r".join([f"MSH|^~\\&|HIS||TB||{day}||X|1|P|2.5||||||~ISO IR87", *segs]) + "\r"
    (d / f"{MRN}_{day}_{typ}_{order}_{day}{stamp}_-_{flag}").write_bytes(body.encode("iso2022_jp"))


def _obx(n: int, value: str, day: str, uid: str = "", status: str = "F") -> str:
    obx = ["OBX", str(n), "NM", "3D046000001906202^HbA1c^JC10", "", value, "%", *[""] * 15]
    obx[11], obx[14], obx[21] = status, f"{day}090000", uid
    return "|".join(obx)


def _read(root: Path, key: str | None = None) -> tuple[list[tuple[str, str]], list[str], dict[str, int]]:
    src = Ssmix2Source(root, licensed={}) if key is None else Ssmix2Source(root, licensed={}, order_key=key)
    rows = sorted((str(r["lab_no"]), str(r["result_value"])) for r in src.rows("lab", "OML-11", None, None))
    dead = sorted(str(r["lab_no"]) for r in src.deleted_rows("lab", "OML-11", None, None))
    return rows, dead, dict(src.stats)


def _reused(root: Path) -> None:
    _store(root, "OML-11", "O1", D1, ["OBR|1|O1", _obx(1, "6.0", D1), _obx(2, "6.1", D1)])
    _store(root, "OML-11", "O1", D2, ["OBR|1|O1", _obx(1, "7.5", D2)])


# ------------------------------------------------------------------------------------------------ the default
def test_by_default_one_order_number_is_one_record_as_before_and_the_repeat_is_counted(tmp_path: Path) -> None:
    _reused(tmp_path)
    rows, _, stats = _read(tmp_path)
    assert rows == [("O1-1", "7.5")]  # the behaviour until now: the newest file of the number
    assert stats[COUNT] == 1  # ... and now the site check shows that the number is on two days


def test_by_default_an_amendment_or_a_delete_filed_under_a_later_day_still_reaches_its_record(tmp_path: Path) -> None:
    """What the first repair of this card broke (its review): a vendor files the final result, or the delete,
    under the day it was sent."""
    _store(tmp_path, "OML-11", "O1", D1, ["OBR|1|O1", _obx(1, "6.0", D1, status="P")])
    _store(tmp_path, "OML-11", "O1", D2, ["OBR|1|O1", _obx(1, "6.3", D1)], stamp="10" + "0000000")
    assert _read(tmp_path)[0] == [("O1-1", "6.3")]  # one result, the final one
    _store(tmp_path, "OML-11", "O1", "20261020", ["OBR|1|O1", _obx(1, "6.3", D1)], flag="0")
    rows, dead, _ = _read(tmp_path)
    assert rows == [] and dead == ["O1-1"]  # deleted, and the tombstone names the id the lake holds


# ------------------------------------------------------------------------------------------------ per_day
def test_with_the_day_in_the_key_a_number_used_again_is_another_order(tmp_path: Path) -> None:
    _reused(tmp_path)
    rows, _, stats = _read(tmp_path, "per_day")
    assert rows == [(f"O1@{D1}-1", "6.0"), (f"O1@{D1}-2", "6.1"), (f"O1@{D2}-1", "7.5")]
    assert stats[COUNT] == 1


def test_with_the_day_in_the_key_an_id_never_changes_meaning_when_another_days_file_appears(tmp_path: Path) -> None:
    _store(tmp_path, "OML-11", "O1", D2, ["OBR|1|O1", _obx(1, "7.5", D2)])
    alone = _read(tmp_path, "per_day")[0]
    _store(tmp_path, "OML-11", "O1", D1, ["OBR|1|O1", _obx(1, "6.0", D1)])  # an earlier day arrives later
    both = _read(tmp_path, "per_day")[0]
    assert alone == [(f"O1@{D2}-1", "7.5")] and set(alone) < set(both)


def test_with_the_day_in_the_key_a_result_with_its_own_id_keeps_it(tmp_path: Path) -> None:
    _store(tmp_path, "OML-11", "O1", D1, ["OBR|1|O1", _obx(1, "6.0", D1, "U1")])
    _store(tmp_path, "OML-11", "O1", D2, ["OBR|1|O1", _obx(1, "7.5", D2, "U2")])
    assert [r[0] for r in _read(tmp_path, "per_day")[0]] == ["U1", "U2"]


def test_with_the_day_in_the_key_the_newest_version_of_a_day_wins_and_a_delete_removes_that_day(tmp_path: Path) -> None:
    _store(tmp_path, "OML-11", "O1", D1, ["OBR|1|O1", _obx(1, "6.0", D1)], stamp="08" + "0000000")
    _store(tmp_path, "OML-11", "O1", D1, ["OBR|1|O1", _obx(1, "6.4", D1)], stamp="08" + "3000000")
    _store(tmp_path, "OML-11", "O1", D2, ["OBR|1|O1", _obx(1, "7.5", D2)], stamp="08" + "0000000")
    assert [r[1] for r in _read(tmp_path, "per_day")[0]] == ["6.4", "7.5"]
    _store(tmp_path, "OML-11", "O1", D2, ["OBR|1|O1", _obx(1, "7.5", D2)], stamp="10" + "0000000", flag="0")
    rows, dead, _ = _read(tmp_path, "per_day")
    assert rows == [(f"O1@{D1}-1", "6.4")] and dead == [f"O1@{D2}-1"]


# ------------------------------------------------------------------------------------------------ the count, the setting
def test_the_count_is_of_live_records_of_the_record_types_only(tmp_path: Path) -> None:
    _store(tmp_path, "OML-11", "O1", D1, ["OBR|1|O1", _obx(1, "6.0", D1)])
    _store(tmp_path, "OML-11", "O2", D2, ["OBR|1|O2", _obx(1, "7.5", D2)])
    assert not [k for k in _read(tmp_path)[2] if "several days" in k]  # no number repeats
    _store(tmp_path, "OML-11", "O1", D2, ["OBR|1|O1", _obx(1, "6.0", D1)], flag="0")  # a delete on a later day
    for key in ("unique", "per_day"):
        assert not [k for k in _read(tmp_path, key)[2] if "several days" in k], key
    for day in (D1, D2):  # a change message names an earlier record on a later day by design
        _store(tmp_path, "ADT-52", "E1", day, ["EVN|A02", f"PID|||{MRN}^^^^PI", "PV1|1|I||||||||||||||||E1"])
    src = Ssmix2Source(tmp_path, licensed={})
    list(src.rows("encounter", "ADT-12", None, None))
    assert not [k for k in src.stats if "several days" in k]


def test_the_setting_comes_from_the_environment_and_a_wrong_word_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tb_common.config import DECLARED

    assert "TB_SSMIX2_ORDER_NUMBERS" in DECLARED
    _reused(tmp_path)
    monkeypatch.setenv("TB_SSMIX2_ORDER_NUMBERS", "per_day")
    assert len(_read(tmp_path)[0]) == 3
    monkeypatch.setenv("TB_SSMIX2_ORDER_NUMBERS", "")
    assert len(_read(tmp_path)[0]) == 1
    monkeypatch.setenv("TB_SSMIX2_ORDER_NUMBERS", "day_and_number")
    with pytest.raises(ValueError, match="TB_SSMIX2_ORDER_NUMBERS"):
        Ssmix2Source(tmp_path, licensed={})
