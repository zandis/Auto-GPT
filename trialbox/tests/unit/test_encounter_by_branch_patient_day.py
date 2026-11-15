"""F7 (D-806): a diagnosis or a vital links to its visit by branch, patient and day when the source's visit numbers do
not join.

Some exports number a visit differently in each table: the visit number on a diagnosis row is not the one on the
visit row, so ``{ref: {type: Encounter, hid: enc_no}}`` points at no visit. What joins is the patient and the day,
within one branch. ``{ref: {type: Encounter, by_day: ...}}`` links a row to the one visit its table holds for that
branch, patient and day. A day with several visits links to none, and a day with no visit links to none; both are
counted, never guessed. Synthetic rows only."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pytest
import yaml
from adapter.mapping.engine import Mapper, Mapping, MappingError, resource_id

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
BY_DAY = {"type": "Encounter", "by_day": {"table": "encounter", "keys": ["branch", "mrn"], "day": "diag_date",
                                          "their_day": "visit_datetime"}}  # fmt: skip


def _mapping(tmp_path: Path, order: list[str] | None = None) -> Mapping:
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    for spec in (doc.get("lookups") or {}).values():
        spec["file"] = str(BASE.parent / spec["file"])
    diag = next(r for r in doc["resources"] if r["type"] == "Condition" and r["table"] == "diagnosis")
    diag["elements"]["encounter.reference"] = {"ref": BY_DAY}
    if order is not None:
        doc["tables"] = {t: doc["tables"][t] for t in order}
    path = tmp_path / "site.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return Mapping.load(path)


def _visit(no: str, branch: str, mrn: str, when: str) -> dict[str, str]:
    return {"enc_no": no, "branch": branch, "mrn": mrn, "visit_datetime": when, "dept_code": "RHEU", "staff_id": "S1",
            "enc_type": "OPD"}  # fmt: skip


def _diag(no: str, branch: str, mrn: str, day: str) -> dict[str, str]:
    # the visit number on a diagnosis row is of another numbering: it never names a visit row
    return {"diag_no": no, "enc_no": f"other-{no}", "branch": branch, "mrn": mrn, "icd10": "M10.9", "diag_date": day,
            "recorded_date": day, "status": "A"}  # fmt: skip


def _run(tmp_path: Path, visits: list[dict[str, str]], diags: list[dict[str, str]]) -> tuple[Mapper, dict[str, Any]]:
    m = Mapper(_mapping(tmp_path), b"k" * 32, "s")
    list(m.map_table("encounter", iter(visits)))
    links = {str(r["id"]): (r.get("encounter") or {}).get("reference") for r in m.map_table("diagnosis", iter(diags))
             if r["resourceType"] == "Condition"}  # fmt: skip
    return m, {"links": list(links.values())}


def test_a_diagnosis_links_to_the_one_visit_of_its_branch_patient_and_day(tmp_path: Path) -> None:
    visits = [_visit("V1", "A", "P1", "2026-01-13 09:10:00"), _visit("V2", "A", "P1", "2026-01-20 10:00:00"),
              _visit("V3", "B", "P1", "2026-01-13 11:00:00")]  # fmt: skip
    m, got = _run(tmp_path, visits, [_diag("D1", "A", "P1", "2026-01-13")])
    assert got["links"] == [f"Encounter/{resource_id(b'k' * 32, 'Encounter', 'V1')}"]
    assert m.encounter_links() == {"diagnosis": {"linked": 1}}


def test_a_day_with_several_visits_links_to_none_and_is_counted(tmp_path: Path) -> None:
    visits = [_visit("V1", "A", "P1", "2026-01-13 09:10:00"), _visit("V2", "A", "P1", "2026-01-13 15:30:00")]
    m, got = _run(tmp_path, visits, [_diag("D1", "A", "P1", "2026-01-13"), _diag("D2", "A", "P1", "2026-01-13")])
    assert got["links"] == [None, None]
    assert m.encounter_links() == {"diagnosis": {"several_visits_that_day": 2}}


def test_a_day_with_no_visit_of_that_branch_links_to_none_and_is_counted(tmp_path: Path) -> None:
    visits = [_visit("V1", "B", "P1", "2026-01-13 09:10:00"), _visit("V2", "A", "P1", "2026-01-14 09:10:00")]
    m, got = _run(tmp_path, visits, [_diag("D1", "A", "P1", "2026-01-13"), _diag("D2", "A", "P2", "2026-01-14")])
    assert got["links"] == [None, None]
    assert m.encounter_links() == {"diagnosis": {"no_visit_that_day": 2}}


def test_the_visit_numbers_still_link_where_a_mapping_says_so(tmp_path: Path) -> None:
    """Nothing changes for a mapping that links by visit number."""
    doc: dict[str, Any] = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    diag = next(r for r in doc["resources"] if r["type"] == "Condition" and r["table"] == "diagnosis")
    assert diag["elements"]["encounter.reference"] == {"ref": {"type": "Encounter", "hid": "enc_no"}}


def test_the_visit_table_must_be_mapped_before_the_table_that_links_by_day(tmp_path: Path) -> None:
    order = ["patient", "practitioner", "diagnosis", "encounter", "appointment", "lab", "vital", "medication",
             "procedure", "report", "note", "claim", "registry"]  # fmt: skip
    with pytest.raises(MappingError, match="encounter.*before.*diagnosis"):
        _mapping(tmp_path, order)


@pytest.mark.parametrize("bad", [{"table": "nope"}, {"table": "lab"}, {"keys": []}, {"day": ""}])
def test_a_by_day_link_stated_badly_is_refused_when_the_mapping_loads(tmp_path: Path, bad: dict[str, Any]) -> None:
    BY_DAY["by_day"] = {**BY_DAY["by_day"], **bad}  # type: ignore[dict-item]
    try:
        with pytest.raises(MappingError):
            _mapping(tmp_path)
    finally:
        BY_DAY["by_day"] = {"table": "encounter", "keys": ["branch", "mrn"], "day": "diag_date",
                            "their_day": "visit_datetime"}  # fmt: skip


def test_the_visit_table_is_read_whole_on_a_delta_night(tmp_path: Path) -> None:
    """On a night that reads only changed rows, an unchanged visit would be missing from the day's visits, and a day
    with two visits would look like a day with one: a wrong link. The visit table is read whole."""
    assert _mapping(tmp_path).read_whole() == {"encounter"}


def _mapper_that(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, visit: str, does: str) -> Mapper:
    """A mapper that refuses (``raise``) or leaves out (``skip``) the visit row ``visit``, as a bad value or a
    ``where`` would."""
    m = Mapper(_mapping(tmp_path), b"k" * 32, "s")
    real = m.map_row

    def map_row(rs: Any, row: dict[str, str]) -> Any:
        if rs.type == "Encounter" and row.get("enc_no") == visit:
            if does == "raise":
                raise ValueError("a value the mapping cannot read")
            return None
        return real(rs, row)

    monkeypatch.setattr(m, "map_row", map_row)
    return m


def _diagnose(m: Mapper, visits: list[dict[str, str]]) -> dict[str, Any]:
    for v in visits:
        with contextlib.suppress(ValueError):  # the night counts it as rejected and goes on
            list(m.map_table("encounter", iter([v])))
    (res,) = [r for r in m.map_table("diagnosis", iter([_diag("D1", "A", "P1", "2026-01-13")]))
              if r["resourceType"] == "Condition"]  # fmt: skip
    return dict(res)


@pytest.mark.parametrize("does", ["raise", "skip"])
def test_a_visit_refused_or_left_out_still_makes_its_day_one_of_several(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, does: str
) -> None:
    """A day of two visits, one refused or left out: never linked to the other."""
    m = _mapper_that(tmp_path, monkeypatch, "V2", does)
    res = _diagnose(m, [_visit("V1", "A", "P1", "2026-01-13 09:10:00"), _visit("V2", "A", "P1", "2026-01-13 15:00:00")])
    assert "encounter" not in res and m.encounter_links() == {"diagnosis": {"several_visits_that_day": 1}}


@pytest.mark.parametrize("does", ["raise", "skip"])
def test_the_one_visit_of_a_day_refused_or_left_out_is_not_pointed_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, does: str
) -> None:
    m = _mapper_that(tmp_path, monkeypatch, "V1", does)
    res = _diagnose(m, [_visit("V1", "A", "P1", "2026-01-13 09:10:00")])
    assert "encounter" not in res and m.encounter_links() == {"diagnosis": {"visit_not_mapped": 1}}


ENC_COLS = ["enc_no", "branch", "mrn", "visit_datetime", "dept_code", "staff_id", "enc_type", "updated_at"]
DIAG_COLS = ["diag_no", "enc_no", "branch", "mrn", "icd10", "diag_date", "recorded_date", "status", "updated_at"]


def _feed(path: Path, visits: list[dict[str, str]], diags: list[dict[str, str]]) -> str:
    import csv

    path.mkdir(parents=True, exist_ok=True)
    for name, cols, rows in (("encounter", ENC_COLS, visits), ("diagnosis", DIAG_COLS, diags)):
        with (path / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    return str(path)


def test_a_delta_night_links_a_changed_diagnosis_to_its_unchanged_visit(tmp_path: Path) -> None:
    import json

    from adapter.ndjson import read_type, snapshot_dir
    from adapter.pipeline import run_ingest

    from tests.unit.test_dataflow_lake_p0 import _cfg

    cfg = _cfg(tmp_path)
    cfg.mapping_path = _mapping(tmp_path).path
    visit = {**_visit("V1", "A", "10000001", "2026-09-30 09:10:00"), "updated_at": "2026-09-30"}
    d1 = {**_diag("D1", "A", "10000001", "2026-09-30"), "updated_at": "2026-09-30"}
    d2 = {**_diag("D2", "A", "10000001", "2026-09-30"), "updated_at": "2026-10-01"}  # changed after the first night
    feed = _feed(tmp_path / "feed", [visit], [d1, d2])
    run_ingest(cfg, "csv", feed, snapshot="2026-10-01", load_fhir=False, validate=False)
    run_ingest(cfg, "csv", feed, since="2026-10-01", snapshot="2026-10-02", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-10-02")
    want = f"Encounter/{resource_id(_key(cfg), 'Encounter', 'V1')}"
    assert {(c.get("encounter") or {}).get("reference") for c in read_type(folder, "Condition")} == {want}
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["diagnosis"]["encounter_by_day"] == {"linked": 1}  # D2: the one row read tonight


def _key(cfg: Any) -> bytes:
    return bytes((cfg.secrets_dir / "site_hmac.key").read_bytes())
