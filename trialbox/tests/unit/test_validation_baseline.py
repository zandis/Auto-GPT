"""TOL-HOLDS (SAFE-1 A5): the validator gate measured against the classes and rates a steward accepted, once.

A night over the ceiling holds as before until a steward accepts one held night; that accept records each class's
rate. From then on the night holds only for a NEW class (over the ceiling) or a class above its baseline by the
margin, and a night the baseline excuses publishes with a warning. The baseline only ever excuses: a night under the
ceiling passes with or without it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from adapter import validation_baseline as vb
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest
from adapter.validate.validator import Hl7Validator, StructuralValidator, ValidationResult
from datacore.dataops import DataOps

from tests.unit.test_adapter_lake_words import _outcome
from tests.unit.test_dataflow_lake_p0 import _Lakes, _row
from tests.unit.test_t723_publish_night import N1, N2, N3, Fhir, _fhir_cfg, _night

N4 = "2026-10-04"
BIRTH = "Patient Patient.birthDate: required"
CODE = "Condition Condition.code: code-invalid"


def _result(classes: dict[str, int], types: dict[str, int], extra_errors: int = 0) -> ValidationResult:
    """A sample of ``types`` where ``classes[c]`` resources show class ``c`` (one class per resource)."""
    per: dict[int, list[str]] = {}
    for c, n in classes.items():
        for _ in range(n):
            per[len(per)] = [c]
    return ValidationResult(validator="stub", sampled=sum(types.values()), errors=len(per) + extra_errors,
                            classes=per, types=dict(types))  # fmt: skip


class _Pattern:
    """The REAL2 twin's pattern: 7 % of the sampled Patients miss birthDate (the night: 7 of 200, 3.5 %)."""

    def __init__(self, classes: dict[str, int], types: dict[str, int]) -> None:
        self.classes, self.types = classes, types

    def validate(self, picked: list[dict[str, Any]]) -> ValidationResult:
        return _result(self.classes, self.types)


SAME = _Pattern({BIRTH: 7}, {"Patient": 100, "Condition": 100})


# ------------------------------------------------------------------------------------------------ the verdict
@pytest.mark.nodb
def test_without_a_baseline_the_gate_is_the_ceiling_as_before() -> None:
    hold, warn = vb.judge(None, _result({BIRTH: 7}, {"Patient": 100, "Condition": 100}), 0.5)
    assert hold and not warn
    assert vb.judge(None, _result({BIRTH: 1}, {"Patient": 100, "Condition": 200}), 0.5) == ([], [])


@pytest.mark.nodb
def test_a_baseline_class_within_its_margin_is_excused_with_a_warning() -> None:
    base = {BIRTH: 7.0}
    hold, warn = vb.judge(base, _result({BIRTH: 13}, {"Patient": 100, "Condition": 100}), 0.5)  # 13 % < 14 %
    assert hold == [] and len(warn) == 1 and "Patient.birthDate" in warn[0] and "7" in warn[0]


@pytest.mark.nodb
def test_a_class_above_its_margin_holds() -> None:
    hold, _ = vb.judge({BIRTH: 7.0}, _result({BIRTH: 15}, {"Patient": 100, "Condition": 100}), 0.5)  # > 2 x 7
    assert len(hold) == 1 and "Patient.birthDate" in hold[0]
    hold, _ = vb.judge({BIRTH: 0.2}, _result({BIRTH: 2}, {"Patient": 100, "Condition": 100}), 0.5)  # > 0.2 + 1
    assert len(hold) == 1
    hold, _ = vb.judge({BIRTH: 0.2}, _result({BIRTH: 1}, {"Patient": 100, "Condition": 100}), 0.5)  # 1 % <= 1.2 %
    assert hold == []


@pytest.mark.nodb
def test_a_new_class_over_the_ceiling_holds_and_under_it_passes() -> None:
    base = {BIRTH: 7.0}
    hold, _ = vb.judge(base, _result({BIRTH: 7, CODE: 2}, {"Patient": 100, "Condition": 100}), 0.5)  # 1 % new
    assert len(hold) == 1 and "Condition.code" in hold[0]
    hold, _ = vb.judge(base, _result({BIRTH: 7, CODE: 2}, {"Patient": 100, "Condition": 900}), 0.5)  # 0.2 % new
    assert hold == []


@pytest.mark.nodb
def test_errors_the_validator_names_no_class_for_are_never_excused() -> None:
    hold, _ = vb.judge({BIRTH: 7.0}, _result({}, {"Patient": 100}, extra_errors=7), 0.5)
    assert hold


@pytest.mark.nodb
@pytest.mark.parametrize("vague", ["Patient Patient: structure", "Patient ?: invalid"])
def test_a_class_that_names_no_element_is_never_excused(vague: str) -> None:
    """An accepted vague class (a model error, an issue with no element) must not excuse an unrelated error later."""
    assert vb.judge({vague: 7.0}, _result({vague: 7}, {"Patient": 100}), 0.5)[0]
    mixed = _result({}, {"Patient": 100})
    mixed.classes = {i: [BIRTH, vague] for i in range(7)}
    mixed.errors = 7
    assert vb.judge({BIRTH: 7.0, vague: 7.0}, mixed, 0.5)[0]


@pytest.mark.nodb
def test_the_baseline_never_holds_a_night_under_the_ceiling() -> None:
    assert vb.judge({BIRTH: 0.1}, _result({BIRTH: 1, CODE: 1}, {"Patient": 10, "Condition": 990}), 0.5) == ([], [])


@pytest.mark.nodb
def test_a_class_rate_is_its_share_of_its_own_type() -> None:
    """A delta night's few resources of other types neither dilute nor inflate a table re-read whole."""
    assert vb.rates(_result({BIRTH: 7}, {"Patient": 100, "Condition": 3})) == {BIRTH: 7.0}
    assert vb.rates(_result({BIRTH: 7}, {"Patient": 100, "Condition": 5000})) == {BIRTH: 7.0}


@pytest.mark.nodb
def test_an_accept_raises_a_class_to_the_rate_accepted_and_keeps_the_others(tmp_path: Path) -> None:
    night = tmp_path / "night"
    night.mkdir()
    vb.write_night(night, {BIRTH: 7.0})
    vb.accept(tmp_path, vb.read_night(night))
    assert vb.load(tmp_path) == {BIRTH: 7.0}
    vb.write_night(night, {BIRTH: 3.0, CODE: 2.0})
    vb.accept(tmp_path, vb.read_night(night))
    assert vb.load(tmp_path) == {BIRTH: 7.0, CODE: 2.0}


@pytest.mark.nodb
def test_an_unreadable_baseline_is_no_baseline(tmp_path: Path) -> None:
    (tmp_path / vb.BASELINE).write_text("{not json", encoding="utf-8")
    assert vb.load(tmp_path) is None


# ------------------------------------------------------------------------------------------------ the classes
@pytest.mark.nodb
def test_the_hl7_validator_names_a_class_per_resource_without_the_value() -> None:
    doc = _outcome([
        {"severity": "error", "code": "required", "expression": ["Condition.code"], "details": {"text": "x '99'"}},
        {"severity": "error", "code": "required", "expression": ["Condition.code"]},
        {"severity": "warning", "code": "informational", "expression": ["Condition.note"]},
    ])  # fmt: skip
    res = Hl7Validator._parse(doc, 4)
    assert res.classes == {3: ["Condition Condition.code: required"]}


@pytest.mark.nodb
def test_the_structural_validator_names_the_missing_element() -> None:
    res = StructuralValidator().validate([{"resourceType": "Patient", "id": "p1", "gender": "female"}])
    assert res.classes == {0: ["Patient Patient.birthDate: required"]} and res.types == {"Patient": 1}


# ------------------------------------------------------------------------------------------------ the nights
def _held(cfg: Any) -> list[Any]:
    ops = DataOps()
    try:
        return list(ops.held())
    finally:
        ops.close()


def test_the_same_pattern_passes_after_one_accept_and_a_new_class_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.publish import publish_held

    lakes = _Lakes(tmp_path / "lake")
    cfg = _fhir_cfg(tmp_path, lakes)
    Fhir(monkeypatch)
    mrns = ["10000001", "10000002"]
    assert run_ingest(cfg, "csv", _night(tmp_path, "n1", [_row("D1", "2026-09-01")], mrns), snapshot=N1,
                      validate=False).passed  # fmt: skip
    rows = [_row("D1", "2026-09-01"), _row("D2", "2026-09-30")]
    rep = run_ingest(cfg, "csv", _night(tmp_path, "n2", rows, mrns), snapshot=N2, validator=SAME)  # type: ignore[arg-type]
    assert rep.held  # no baseline yet: 3.5 % is over 0.5 %
    assert publish_held(cfg, N2).promoted  # the steward's one accept
    assert vb.load(cfg.lake_dir) == {BIRTH: 7.0}
    rows3 = [*rows, _row("D3", "2026-10-02")]
    rep = run_ingest(cfg, "csv", _night(tmp_path, "n3", rows3, mrns), snapshot=N3, validator=SAME)  # type: ignore[arg-type]
    # the same pattern: night 3 waits for no accept (night 2's row stays HELD here: publish_held is called without
    # the store's decide, which the console's accept goes through)
    assert rep.passed and not rep.held and [b.snapshot for b in _held(cfg)] == [N2]
    gate = (snapshot_dir(cfg.lake_dir, N3) / "gate.json").read_text(encoding="utf-8")
    assert "PUBLISH_WITH_WARNINGS" in gate and "Patient.birthDate" in gate
    new = _Pattern({BIRTH: 7, CODE: 3}, {"Patient": 100, "Condition": 100})
    rows4 = [*rows3, _row("D4", "2026-10-03")]
    rep = run_ingest(cfg, "csv", _night(tmp_path, "n4", rows4, mrns), snapshot=N4, validator=new)  # type: ignore[arg-type]
    assert rep.held and any("Condition.code" in e for e in rep.errors or [])
