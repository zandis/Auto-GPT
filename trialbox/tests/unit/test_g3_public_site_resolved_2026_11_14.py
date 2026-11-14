"""Lane G, lane E's card 1 on the integrator's ruling (finding P6): the public-data site keeps a past, treated disease.

MedTxt-CR tags a disease that is no longer present as negative (``食道癌根治術施行``). ``tools.public_site`` wrote such a
diagnosis as active (``A``). It is now a diagnosis kept as resolved (``R``: the HIS map's FHIR clinicalStatus
``resolved``, the lake's condition ``status``), by the same reading the MedTxt scenario's check uses
(``tools.medtxt_eval.negative_kinds`` and ``treated_in_quote``). A stated absence stays skipped; an active disease
and the English site are as before.

No corpus, no model: synthetic Japanese text and markup in the corpus's shape (the disease names are real words,
the sentences are made up)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from adapter.mapping.engine import Mapper, Mapping
from lake.flatten import Flattener

from tools import medtxt_eval, public_site, scenarios

ROOT = Path(__file__).resolve().parents[2]
CLINICAL = "http://terminology.hl7.org/CodeSystem/condition-clinical"

MARKUP = ('既往歴：<d certainty="negative">胃癌</d><r state="executed">手術</r>。'
          '<d certainty="negative">肺炎</d>なし。')  # fmt: skip


def _kinds(raw: str = MARKUP) -> dict[str, set[str]]:
    return medtxt_eval.negative_kinds(raw)


def test_one_reading_for_the_scenario_check_and_the_site() -> None:
    kinds = _kinds()
    assert kinds == {"胃癌": {"treated"}, "肺炎": {"denied"}}
    assert scenarios.medtxt_negative_kinds(MARKUP) == kinds
    assert scenarios.treated_in_quote("胃癌", "胃癌手術", kinds) is True
    assert medtxt_eval.treated_in_quote("胃癌", "胃癌手術", kinds) is True


def test_a_treated_past_disease_is_kept_as_resolved() -> None:
    dx = public_site.derive_dx("既往歴：７年前に胃癌手術。現在は外来通院中。", "ja", _kinds())
    assert [(c, st) for c, _label, _ev, st in dx] == [("C16.9", "R")]


def test_a_stated_absence_is_still_skipped() -> None:
    assert public_site.derive_dx("肺炎は認めない。", "ja", _kinds()) == []
    # a treated mention the negation rule reads as denied stays skipped: never a diagnosis the text may deny
    assert public_site.derive_dx("胃癌手術歴なし。", "ja", _kinds()) == []
    # the corpus marks a treated context, but this quote names no treatment after the mention: as before
    assert public_site.derive_dx("胃癌の再発なし。", "ja", _kinds()) == []


def test_an_active_disease_is_unchanged() -> None:
    assert [d[3] for d in public_site.derive_dx("胃癌に対し化学療法中。", "ja", _kinds())] == ["A"]
    assert [d[3] for d in public_site.derive_dx("胃癌に対し化学療法中。", "ja")] == ["A"]  # no markup: as before
    # named both ways in one report: the patient has it now
    dx = public_site.derive_dx("胃癌手術。その後、胃癌の肝転移を認めた。", "ja", _kinds())
    assert [(c, st) for c, _label, _ev, st in dx] == [("C16.9", "A")]
    assert [d[3] for d in public_site.derive_dx("A 60-year-old man with hypertension.", "en")] == ["A"]


def test_the_resolved_diagnosis_reaches_the_lake_as_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """diagnosis.csv ``R`` -> FHIR Condition clinicalStatus (condition-clinical ``resolved``) -> the lake's ``status``."""
    text = "７０歳代女性。既往歴：７年前に胃癌手術。高血圧で通院中。"
    doc = public_site.Derived("MedTxt-CR", "CR:synthetic-1", "ja", text, 75, True, "F",
                              public_site.derive_dx(text, "ja", _kinds()))  # fmt: skip
    monkeypatch.setattr(public_site, "medtxt_docs", lambda: [doc])
    res = public_site.build(tmp_path, sites=("ja",))
    assert res["summary"]["dx_rows"] == 2 and res["summary"]["dx_resolved"] == 1
    assert "kept as resolved (1 rows)" in (tmp_path / "PROVENANCE.md").read_text(encoding="utf-8")
    with (tmp_path / "diagnosis.csv").open(encoding="utf-8") as fh:
        rows = {r["icd10"]: r for r in csv.DictReader(fh)}
    assert {k: r["status"] for k, r in rows.items()} == {"C16.9": "R", "I10": "A"}
    mapper = Mapper(Mapping.load(ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"), b"k" * 32, "s")
    flat = Flattener("Asia/Tokyo")
    for code, want in (("C16.9", "resolved"), ("I10", "active")):
        (cond,) = mapper.map_table("diagnosis", iter([rows[code]]))
        assert cond["clinicalStatus"]["coding"] == [{"system": CLINICAL, "code": want}]
        assert "verificationStatus" not in cond  # resolved is a fact, not an unconfirmed diagnosis
        assert flat.condition(cond)["status"] == want
    assert not mapper.unmapped
