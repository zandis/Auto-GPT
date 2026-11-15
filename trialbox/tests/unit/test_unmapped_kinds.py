"""NEW-B-39 (D-740): the rows holding a value the mapping could not use, split by kind (the owner's yes, 2026-11-13).

D-580's counter was one number per source table on the night's page (lane C2's #534): rows left out because no
look-up knows their code, rows kept without their value because the unit was not read (D-590), and rows whose code
the reference data could not be asked for (D-593) were one sum. The three call for different people: a steward's
code tab, the lab's unit spellings, the reference data's own outage. Now the night keeps the split per source
table, beside the total, which stays what it was (the sum). Counts only: no code, no value."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import pytest
from adapter.pipeline import run_ingest, unmapped_kind, unmapped_kinds
from tb_common.unmapped import KINDS

from tests.unit.test_dataflow_lake_p0 import _cfg

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "services/adapter/mapping/engine.py"


def test_the_kinds_are_named_and_sum_to_the_total() -> None:
    by = {
        "lab": {"X1": 3, "X2": 1},  # a look-up that knows no such code
        "column:status": {"Z": 2},  # a column whose code is not among the known ones
        "map:icd9cm->icd10cm": {"E03.0": 1},  # the map gives no single code
        "unit_mismatch": {"2160-0": 2},
        "no_unit_implausible": {"718-7": 1},
        "map:icd9cm->icd10cm:unavailable": {"042": 5, "7140": 2},
    }
    kinds = unmapped_kinds(by)
    assert kinds == {"code_unknown": 7, "unit_not_read": 3, "reference_data_not_reached": 7}
    assert sum(kinds.values()) == sum(sum(c.values()) for c in by.values())
    assert set(KINDS) == {"code_unknown", "unit_not_read", "reference_data_not_reached"}
    assert unmapped_kinds({}) == dict.fromkeys(KINDS, 0)


def _counter_places() -> list[str]:
    """Every place the mapping engine counts (each ``_note_unmapped`` call), by the name argument as written: a
    literal, an f-string, or the expression's text. A name written the same way in two places is listed twice."""
    out = []
    for node in ast.walk(ast.parse(ENGINE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_note_unmapped":
            out.append(ast.unparse(node.args[1]))
    return sorted(out)


#: each place the engine counts a value it could not use: the name as written, how many places write it, its kind
#: and a name it gives. A new place, even one that writes a name the same way as another, fails here until its kind
#: is named (the owner: a new kind is said, never folded into another)
PLACES = {
    "'no_unit_implausible'": (1, "unit_not_read", "no_unit_implausible"),
    "'shape:icd10cm'": (1, "code_unknown", "shape:icd10cm"),
    "'local:icd10cm'": (1, "code_unknown", "local:icd10cm"),  # CGRD-A3 (D-815): a site's own code, kept as written  # F6 (D-808): not of the ICD-10-CM shape, copied as fed
    "'unit_mismatch'": (1, "unit_not_read", "unit_mismatch"),
    "f'column:{c['column']}'": (1, "code_unknown", "column:status"),
    "f'column:{expr['column']}'": (1, "code_unknown", "column:sex"),
    "f'{name}:unavailable'": (1, "reference_data_not_reached", "map:icd9cm->icd10cm:unavailable"),
    "name": (2, "code_unknown", "map:icd9cm->icd10cm"),  # a code never asked (not a code); no single answer
    "str(spec['name'])": (1, "code_unknown", "lab"),
}


def test_every_place_the_engine_counts_is_named_with_its_kind() -> None:
    from collections import Counter

    assert Counter(_counter_places()) == {k: n for k, (n, _, _) in PLACES.items()}, (
        "a new place counts a value: name its kind in PLACES (and in KINDS if it is a new kind)"
    )
    for written, (_, kind, example) in PLACES.items():
        assert unmapped_kind(example) == kind, written


def test_the_engine_counts_only_through_its_one_door() -> None:
    """A write to the counter that does not go through ``_note_unmapped`` would escape the list above."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    door = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_note_unmapped")
    inside = {id(n) for n in ast.walk(door)}
    writes = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.AugAssign | ast.Assign)
        and "unmapped" in ast.unparse(n.target if isinstance(n, ast.AugAssign) else n.targets[0])
        and "[" in ast.unparse(n.target if isinstance(n, ast.AugAssign) else n.targets[0])
        and id(n) not in inside
    ]
    assert writes == [], f"the counter is written outside _note_unmapped at lines {writes}"


def _lab_night(path: Path, rows: list[dict[str, str]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    cols = ["lab_no", "mrn", "local_code", "item_name", "result_value", "unit", "sample_datetime", "updated_at"]
    with (path / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def _lab(no: str, code: str, value: str, unit: str) -> dict[str, str]:
    return {"lab_no": no, "mrn": "10000001", "local_code": code, "item_name": "x", "result_value": value,
            "unit": unit, "sample_datetime": "2026-09-30 10:30:00"}  # fmt: skip


def test_the_night_keeps_the_split_per_table_beside_the_total(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _lab_night(tmp_path / "full", [
        _lab("L1", "NOSUCH1", "5", "mg/dL"),  # no look-up knows the code: left out
        _lab("L2", "NOSUCH2", "6", "mg/dL"),
        _lab("L3", "CRE", "97", "umol/L"),  # a unit the look-up's unit is not: kept without the value
        _lab("L4", "CRE", "1.1", "mg/dL"),  # fine
    ])  # fmt: skip
    rep = run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, rebuild_lake=False,
                     validate=False)  # fmt: skip
    audit = [json.loads(x) for f in (tmp_path / "audit").glob("*.jsonl") for x in f.read_text().splitlines()]
    (night,) = [e for e in audit if e["event"] in ("ingest.done", "ingest.held") and e.get("snapshot") == "2026-10-01"]
    detail = night["detail"]
    assert detail["unmapped"]["lab"] == 3, (rep.errors, detail.get("unmapped"))
    assert detail["unmapped_kinds"]["lab"] == {"code_unknown": 2, "unit_not_read": 1, "reference_data_not_reached": 0}
    text = json.dumps(detail["unmapped_kinds"])
    assert "NOSUCH" not in text and "CRE" not in text  # counts only


def test_the_batch_row_is_told_to_keep_the_split() -> None:
    from datacore.dataops import DETAIL_KEYS

    assert "unmapped_kinds" in DETAIL_KEYS  # the page's own test (tests/console) reads it back through the API


def test_a_split_that_adds_up_to_the_total_is_answered() -> None:
    from console.dataops_page import unmapped_kinds_of

    kinds = {"code_unknown": 2, "unit_not_read": 1, "reference_data_not_reached": 0}
    assert unmapped_kinds_of({"unmapped": {"lab": 3}, "unmapped_kinds": {"lab": kinds}}) == {"lab": kinds}


@pytest.mark.parametrize(
    "kinds",
    [None, "x", {"lab": "x"}, {"lab": {"code_unknown": "2"}}, {"lab": {"other": 1}},
     {"lab": {"code_unknown": 9, "unit_not_read": 0, "reference_data_not_reached": 0}},  # not the total
     {"lab": {"code_unknown": -1, "unit_not_read": 4, "reference_data_not_reached": 0}}],
)  # fmt: skip
def test_a_split_that_is_not_counts_of_the_named_kinds_adding_up_to_the_total_is_not_shown(kinds: object) -> None:
    from console.dataops_page import unmapped_kinds_of

    assert unmapped_kinds_of({"unmapped": {"lab": 3}, "unmapped_kinds": kinds}) == {}
