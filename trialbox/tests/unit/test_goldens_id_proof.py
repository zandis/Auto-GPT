"""D-1253 review H: the goldens id proof (``tools/goldens_id_proof.py compare``) never passes with nothing compared.

It fails on an empty dump, a data set with no file or no row in both dumps, a file only in the new dump or only in
the old one, and a list whose order changed. A list whose items hold record ids (listed in the order of the ids) may
be in another order once the ids are mapped; any other list keeps its order. Synthetic dumps only."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from tools import goldens_id_proof as proof

A, B = "a" * 32, "b" * 32  # old ids
X, Y = "f" * 32, "0" * 32  # their new ids: the order flips


def _dump(root: Path, files: dict[str, list[dict[str, Any]]]) -> Path:
    for rel, rows in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r) + "\n" for r in rows)
    return root


def _old_new(tmp_path: Path, old_extra: dict[str, list[dict[str, Any]]] | None = None,
             new_extra: dict[str, list[dict[str, Any]]] | None = None) -> tuple[Path, Path]:  # fmt: skip
    table = "s1/tables/condition.jsonl.gz"
    old = {table: [{"cid": A, "code": "E11"}, {"cid": B, "code": "I10"}], **(old_extra or {})}
    new = {table: [{"cid": X, "code": "E11"}, {"cid": Y, "code": "I10"}], **(new_extra or {})}
    return _dump(tmp_path / "old", old), _dump(tmp_path / "new", new)


def test_ids_that_map_one_to_one_and_nothing_else_moved_is_proved(tmp_path: Path) -> None:
    outcome = "s1/rulesets/R.outcomes.jsonl.gz"
    old, new = _old_new(tmp_path, {outcome: [{"evidence": [A, B], "steps": ["z", "a"]}]},
                        {outcome: [{"evidence": [Y, X], "steps": ["z", "a"]}]})  # fmt: skip
    assert proof.compare(old, new) == 0  # the list of ids may change order; the other keeps its order


def test_empty_dumps_prove_nothing(tmp_path: Path) -> None:
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    assert proof.compare(tmp_path / "old", tmp_path / "new") == 1


def test_a_data_set_whose_files_hold_no_row_proves_nothing(tmp_path: Path) -> None:
    old = _dump(tmp_path / "old", {"s1/tables/condition.jsonl.gz": []})
    new = _dump(tmp_path / "new", {"s1/tables/condition.jsonl.gz": []})
    assert proof.compare(old, new) == 1


def test_a_list_whose_order_changed_is_a_difference(tmp_path: Path) -> None:
    outcome = "s1/rulesets/R.outcomes.jsonl.gz"
    old, new = _old_new(tmp_path, {outcome: [{"steps": ["z", "a"]}]}, {outcome: [{"steps": ["a", "z"]}]})
    assert proof.compare(old, new) == 1


@pytest.mark.parametrize("side", ["new", "old"])
def test_a_file_on_one_side_only_is_a_difference(tmp_path: Path, side: str) -> None:
    extra = {"s1/tables/note.jsonl.gz": [{"did": A}]}
    old, new = _old_new(tmp_path, extra if side == "old" else None, extra if side == "new" else None)
    assert proof.compare(old, new) == 1
