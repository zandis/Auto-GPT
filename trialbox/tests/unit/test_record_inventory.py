"""The record inventory covers every record the code keeps (card T-643, deep review REG-022, D-363).

The test reads the store modules (every ``CREATE TABLE`` under ``services/`` and ``libs/``) and the store map of
``docs/validation/record-inventory.md``: a table with no row, a row for a table that is gone and an id with no row
all fail. It also holds the records table to its columns and classes, the audit events it names to the code, and the
release-record section that ``tools/gen_traceability.py --records`` prints.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.test_validation_records import TICKED, looks_like_path, resolves
from tools import gen_traceability as gt

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "validation" / "record-inventory.md"
CLASSES = {"essential", "source", "copy", "aid", "control"}
# The records REG-022 names; each must have its own row.
NAMED = {
    "screening log": "R-03",
    "delegation log copy": "R-04",
    "consent": "R-05",
    "sae register": "R-07",
    "edc prefill": "R-08",
    "audit chain": "R-01",
    "export ledger": "R-02",
}


@pytest.fixture(scope="module")
def text() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tables() -> dict[str, set[str]]:
    return gt.store_tables()


def test_every_table_the_code_creates_has_a_row(text: str, tables: dict[str, set[str]]) -> None:
    assert len(tables) > 20, "the scan found the store modules"
    assert gt.inventory_gaps(text, tables) == []


def test_the_scan_reads_the_known_record_stores(tables: dict[str, set[str]]) -> None:
    assert {"sae_case", "sae_report", "sae_trail"} <= tables["services/console/saerecord.py"]
    assert {"draft", "decision", "signature", "sent"} <= tables["services/edc/store.py"]
    assert {"delegation", "delegation_checks"} <= tables["services/console/teamstore.py"]
    assert not any("/tests/" in m for m in tables)


def test_the_scan_skips_tests_and_reads_new_modules(tmp_path: Path) -> None:
    (tmp_path / "services" / "x").mkdir(parents=True)
    (tmp_path / "services" / "x" / "store.py").write_text(
        'S = """CREATE TABLE IF NOT EXISTS widget (a TEXT);\ncreate table gadget (b TEXT)"""\n', encoding="utf-8"
    )
    (tmp_path / "services" / "x" / "tests").mkdir()
    (tmp_path / "services" / "x" / "tests" / "t.py").write_text('"CREATE TABLE ignored (a)"', encoding="utf-8")
    (tmp_path / "libs").mkdir()
    (tmp_path / "libs" / "dyn.py").write_text('f"CREATE TABLE {name} AS SELECT 1"', encoding="utf-8")
    assert gt.store_tables(tmp_path) == {"services/x/store.py": {"widget", "gadget"}}


def test_a_new_table_without_a_row_is_found(text: str, tables: dict[str, set[str]]) -> None:
    planted = {**tables, "services/edc/store.py": tables["services/edc/store.py"] | {"countersign"}}
    gaps = gt.inventory_gaps(text, planted)
    assert gaps == [
        "record inventory: services/edc/store.py creates table countersign, which has no row in the store map"
    ]


def test_a_new_store_module_without_a_row_is_found(text: str, tables: dict[str, set[str]]) -> None:
    gaps = gt.inventory_gaps(text, {**tables, "services/console/isf.py": {"isf_bundle"}})
    assert gaps == [
        "record inventory: services/console/isf.py creates table isf_bundle, which has no row in the store map"
    ]


def test_a_row_for_a_table_that_is_gone_is_found(text: str, tables: dict[str, set[str]]) -> None:
    fewer = {**tables, "services/console/saerecord.py": tables["services/console/saerecord.py"] - {"sae_trail"}}
    assert gt.inventory_gaps(text, fewer) == [
        "record inventory: services/console/saerecord.py no longer creates table sae_trail"
    ]


def test_a_mapped_id_without_a_row_and_a_row_without_a_map_are_found(text: str, tables: dict[str, set[str]]) -> None:
    broken = text.replace(
        "| `libs/tb_common/optout.py` | `optout_events` | R-06 |",
        "| `libs/tb_common/optout.py` | `optout_events` | R-99 |",
    )
    gaps = gt.inventory_gaps(broken, tables)
    assert "record inventory: libs/tb_common/optout.py maps to R-99, which has no row" in gaps
    assert "record inventory: R-06 has no row in the store map" in gaps


def test_a_table_mapped_twice_is_found(text: str, tables: dict[str, set[str]]) -> None:
    twice = text + "| `services/console/feedback.py` | `entry` | O-02 |\n"
    assert gt.inventory_gaps(twice, tables) == [
        "record inventory: services/console/feedback.py table entry is mapped twice"
    ]


def test_every_record_row_is_complete_and_classed(text: str) -> None:
    ids = gt.inventory_ids(text)
    recs = {k: v for k, v in ids.items() if k.startswith("R-")}
    assert list(recs) == [f"R-{n:02d}" for n in range(1, len(recs) + 1)], "R ids in order, no gap"
    for rid, row in recs.items():
        assert len(row) == 7 and all(row), f"{rid}: record, class, system of record, keeper, retention, export, events"
        assert row[1] in CLASSES, f"{rid}: class {row[1]!r}"
    others = {k: v for k, v in ids.items() if k.startswith("O-")}
    assert all(len(v) == 3 and all(v) for v in others.values())


def test_the_records_reg022_names_have_their_rows(text: str) -> None:
    ids = gt.inventory_ids(text)
    for name, rid in NAMED.items():
        assert name in ids[rid][0].lower(), f"{rid} is the {name}"
    assert ids["R-04"][1] == "copy", "the box holds a copy of the signed delegation log (teamstore)"


def test_the_audit_events_named_exist_in_the_code(text: str) -> None:
    code = "\n".join(
        p.read_text(encoding="utf-8")
        for d in ("services", "libs")
        for p in (ROOT / d).rglob("*.py")
        if "/tests/" not in p.as_posix()
    )
    ids = gt.inventory_ids(text)
    missing = []
    for rid, row in ids.items():
        if rid.startswith("R-"):
            missing += [(rid, e) for e in re.findall(r"`([a-z_]+\.[a-z_.]+)`", row[6]) if f'"{e}"' not in code]
    assert not missing, f"audit events named in the inventory that the code never writes: {missing}"


def test_paths_named_in_the_inventory_exist(text: str) -> None:
    bad = sorted({t for t in TICKED.findall(text) if looks_like_path(t) and not resolves(t, DOC.parent)})
    assert not bad, bad


def test_the_release_record_section_lists_every_record(text: str, tables: dict[str, set[str]]) -> None:
    section = gt.records_section(text, gt.inventory_gaps(text, tables))
    assert section.startswith("## Record inventory\n")
    assert "store map: complete." in section
    for rid in (k for k in gt.inventory_ids(text) if k.startswith("R-")):
        assert f"\n| {rid} | " in section
    assert "O-01" not in section


def test_records_flag_prints_the_section_and_fails_on_a_gap(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert gt.main(["--records"]) == 0
    assert "## Record inventory" in capsys.readouterr().out
    short = tmp_path / "record-inventory.md"
    short.write_text(
        DOC.read_text(encoding="utf-8").replace("| `services/console/feedback.py` | `entry` | O-02 |\n", ""),
        encoding="utf-8",
    )
    monkeypatch.setattr(gt, "INVENTORY", short)
    assert gt.main(["--records"]) == 1
    assert "creates table entry, which has no row" in capsys.readouterr().out


def test_check_only_warns_on_a_gap_and_strict_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """D-311 S7: ``--check`` warns; ``--strict`` fails."""
    short = tmp_path / "record-inventory.md"
    short.write_text("# empty\n", encoding="utf-8")
    monkeypatch.setattr(gt, "INVENTORY", short)
    assert gt.main(["--check"]) == 0
    assert gt.main(["--strict"]) == 1


def test_the_layout_and_the_release_record_name_the_inventory() -> None:
    readme = (ROOT / "docs" / "validation" / "README.md").read_text(encoding="utf-8")
    assert "[`record-inventory.md`](record-inventory.md)" in readme
    rr = (ROOT / "docs" / "validation" / "release-records" / "README.md").read_text(encoding="utf-8")
    assert "gen_traceability.py --records" in rr
