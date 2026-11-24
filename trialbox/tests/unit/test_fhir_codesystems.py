"""V-18 (D-1182): the code systems the box carries, loaded into the FHIR store (``tools.fhir_codesystems``).

A store in memory that keeps each resource's history as the FHIR store does; the real store's answers are in
``tests/integration/test_fhir_codesystems_compose.py``."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tools import fhir_codesystems as fc

TERM = Path("/nonexistent-terminology")  # nothing loaded at install: the shipped tables answer


class MemoryStore(fc.Store):
    def __init__(self) -> None:
        self.base = "memory"
        self.versions: dict[str, list[dict[str, Any]]] = {}

    def put(self, res: dict[str, Any]) -> None:
        hist = self.versions.setdefault(f"{res['resourceType']}/{res['id']}", [])
        body = json.loads(json.dumps(res))
        body["meta"] = {**(body.get("meta") or {}), "versionId": str(len(hist) + 1)}
        hist.append(body)

    def get(self, kind: str, rid: str, summary: bool = False) -> dict[str, Any] | None:
        hist = self.versions.get(f"{kind}/{rid}")
        return json.loads(json.dumps(hist[-1])) if hist else None

    def answers(self, system: str, code: str) -> str:
        """The current version of the system's resource: the store in memory stores at once."""
        return next((str(h[-1]["version"]) for h in self.versions.values() if h and h[-1].get("url") == system), "")

    def history(self, kind: str, rid: str, vid: str) -> dict[str, Any] | None:
        hist = self.versions.get(f"{kind}/{rid}") or []
        return json.loads(json.dumps(hist[int(vid) - 1])) if vid.isdigit() and 0 < int(vid) <= len(hist) else None


def _src(key: str) -> fc.Source:
    return next(s for s in fc.SOURCES if s.key == key)


def test_a_system_its_licence_does_not_let_the_box_carry_is_skipped_with_the_reason() -> None:
    got = fc.pick(_src("atc"), TERM, None)
    assert isinstance(got, str) and "atc is permission-to-ask" in got
    out = {o.key: o for o in fc.load(MemoryStore(), TERM, [_src("atc")])}
    assert out["atc"].state == "skipped"


def test_a_system_that_ships_nothing_and_was_not_loaded_at_install_is_skipped() -> None:
    for key in ("icd10pcs", "icd10-who"):
        assert fc.pick(_src(key), TERM, None) == "not loaded at install (the site's own copy; nothing ships)"


def test_every_shipped_source_is_named_by_a_register_row() -> None:
    for s in fc.SOURCES:
        if s.path:
            row, status = fc.register_status(s.path)
            assert row and status, s.path


def test_load_names_hashes_and_versions_each_system_and_a_second_load_changes_nothing() -> None:
    store = MemoryStore()
    keys = ["icd10cm", "loinc", "nhi-order", "department", "map-lab-loinc"]
    first = {o.key: o for o in fc.load(store, TERM, [_src(k) for k in keys])}
    assert {k: o.state for k, o in first.items()} == dict.fromkeys(keys, "loaded")
    cs = store.get("CodeSystem", "tb-icd10cm")
    assert cs is not None and cs["url"] == fc.ICD10CM and cs["name"] == "Icd10Cm"
    digest = fc.digest_of(cs)
    assert len(digest) == 64 and cs["version"] == f"FY2026+{digest[:8]}" and cs["count"] == 98186
    again = {o.key: o.state for o in fc.load(store, TERM, [_src(k) for k in keys])}
    assert again == dict.fromkeys(keys, "unchanged")
    assert all(len(h) == 1 for h in store.versions.values())


def test_an_update_names_what_it_replaces_and_a_rollback_puts_it_back(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryStore()
    dept = _src("department")
    fc.load(store, TERM, [dept])
    v1 = store.get("CodeSystem", "tb-department")
    assert v1 is not None
    newer = replace(dept, reader=lambda p: [*fc._parquet(p), {"code": "SYNX", "display": "Synthetic new department"}])
    (o,) = fc.load(store, TERM, [newer])
    v2 = store.get("CodeSystem", "tb-department")
    assert o.state == "loaded" and v2 is not None and v2["version"] != v1["version"]
    assert fc.replaced(v2) == (v1["version"], "1") and f"replaces {v1['version']}" in o.detail
    assert "SYNX" in {c["code"] for c in v2["concept"]}
    assert "is back in place of" in fc.rollback(store, "department")
    v3 = store.get("CodeSystem", "tb-department")
    assert v3 is not None and v3["version"] == v1["version"] and fc.digest_of(v3) == fc.digest_of(v1)
    assert "SYNX" not in {c["code"] for c in v3["concept"]}
    with pytest.raises(SystemExit, match="nothing to roll back to"):
        fc.rollback(store, "department")


def test_status_gives_each_systems_version_and_what_it_replaced() -> None:
    store = MemoryStore()
    fc.load(store, TERM, [_src("loinc")])
    rows = {r["key"]: r for r in fc.status(store)}
    assert rows["loinc"]["state"] == "loaded" and rows["loinc"]["version"].startswith("2.82+")
    assert rows["atc"]["state"] == "not loaded" and rows["atc"]["version"] == ""


def test_icd10cm_carries_its_hierarchy() -> None:
    nested = fc.nest([{"code": c} for c in ("M10", "M10.0", "M10.00", "M10.01", "A00")])
    m10 = next(c for c in nested if c["code"] == "M10")
    assert [c["code"] for c in nested] == ["A00", "M10"] and fc.count(nested) == 5
    m100 = m10["concept"][0]
    assert m100["code"] == "M10.0" and m100["property"] == [{"code": "parent", "valueCode": "M10"}]
    assert [c["code"] for c in m100["concept"]] == ["M10.00", "M10.01"]


def test_a_mapping_table_is_a_concept_map_from_its_source_to_its_target() -> None:
    src = _src("map-yj-atc")
    got = fc.pick(src, TERM, None)
    assert not isinstance(got, str)
    rows, _, _ = got
    res = fc.resource(src, fc.content(src, rows), "shipped", "test")
    (group,) = res["group"]
    assert res["resourceType"] == "ConceptMap" and group["target"] == fc.ATC
    assert group["element"][0]["target"][0]["equivalence"] == "equivalent"


def test_a_table_loaded_at_install_takes_the_place_of_the_shipped_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from criteria_compiler.terminology import installed as inst

    monkeypatch.setattr(inst, "read_table", lambda d, name: [{"code": "SYN-1", "display": "Synthetic analyte"}]
                        if name == "loinc_table" else None)  # fmt: skip
    monkeypatch.setattr(inst, "manifest", lambda d: {"tables": {"loinc_table": {"version": "9.99"}}})
    got = fc.pick(_src("loinc"), TERM, None)
    assert not isinstance(got, str)
    rows, version, origin = got
    assert rows == [{"code": "SYN-1", "display": "Synthetic analyte"}] and version == "9.99"
    assert origin == "loinc_table, loaded at install"


def test_the_command_goes_on_and_lists_only_a_fault_in_the_poc_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A system the box was not given (icd10pcs) or may not carry (atc) is expected: a warning, not a line of the
    list (H-94: the rehearsal box's install lists nothing). A system given but not stored is a fault: a line."""
    store = MemoryStore()
    monkeypatch.setattr(fc, "Store", lambda base: store)
    monkeypatch.setattr(fc, "SOURCES", (_src("atc"), _src("department"), _src("icd10pcs")))
    rc = fc.main(["--fhir", "http://fhir.invalid/fhir", "load", "--terminology", str(TERM), "--deploy", str(tmp_path)])
    assert rc == 0 and not (tmp_path / "site/poc-stops.jsonl").exists()
    err = capsys.readouterr().err
    assert "warning: atc not loaded" in err and "warning: icd10pcs not loaded" in err
    assert store.get("CodeSystem", "tb-department") is not None

    def refuse(res: dict[str, Any]) -> None:
        raise RuntimeError("the store said no")

    monkeypatch.setattr(store, "put", refuse)
    monkeypatch.setattr(fc, "SOURCES", (_src("department"),))
    store.versions.clear()
    fc.main(["--fhir", "http://fhir.invalid/fhir", "load", "--terminology", str(TERM), "--deploy", str(tmp_path)])
    lines = [json.loads(x) for x in (tmp_path / "site/poc-stops.jsonl").read_text("utf-8").splitlines()]
    assert [x["key"] for x in lines] == ["fhir_codesystems/department"] and "the store said no" in lines[0]["skipped"]


class SlowStore(MemoryStore):
    """Answers a code only from the ``after``-th question on, as the store does while it stores in the background."""

    def __init__(self, after: int) -> None:
        super().__init__()
        self.after = after
        self.asked: list[str] = []

    def answers(self, system: str, code: str) -> str:
        self.asked.append(code)
        return "v1" if len(self.asked) >= self.after else ""


def test_the_load_waits_until_the_store_answers_and_never_asks_one_code_twice() -> None:
    items = fc.nest([{"code": c} for c in ("A00", "A00.0", "B01", "B01.1", "C02")])
    assert fc.late_codes(items) == ["C02", "B01.1", "B01", "A00.0", "A00"]
    naps: list[float] = []
    store = SlowStore(after=3)
    assert fc.wait_stored(store, fc.SOURCES[0], "v1", items, 600, step=5, sleep=naps.append)
    assert store.asked == ["C02", "B01.1", "B01"] and len(set(store.asked)) == len(store.asked)
    assert naps[0] == pytest.approx(5 / fc.STORE_RATE)  # first, the time the store takes for this many codes
    assert not fc.wait_stored(SlowStore(after=99), fc.SOURCES[0], "v1", items, 600, sleep=lambda s: None)
