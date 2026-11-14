"""B14 (lane G findings 2026-11-13; owner ruling D-502): a criterion whose logic names a value set no concept candidate
defined goes to a person; it no longer fails the whole protocol.

The production model wrote, on public protocol NCT03887455, an atom naming "CDR score" without listing it among its
concept candidates. ``ValueSets.codes`` raised ``KeyError``; ``demote_uncompilable`` and ``build_artifacts`` catch
only ``CompileError`` and ``/compile`` only ``CompileFailed``, so the box answered HTTP 500 and every other criterion
was lost. An unknown value set is now a ``CompileError`` (still a ``KeyError`` for any older caller): the criterion
becomes ``human`` with ``needs_review`` and ``compile_error`` (a ``mixed`` one becomes ``note``), and the rest
compiles. Synthetic ruleset, no model.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from criteria_compiler.semantics import CompileError
from criteria_compiler.service import Compiler
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]


def _rs() -> Ruleset:
    return Ruleset.load(ROOT / "rulesets" / "GOUT-COH")


@pytest.mark.parametrize("method", ["codes", "url", "version"])
def test_an_unknown_value_set_is_a_compile_error_and_still_a_key_error(method: str) -> None:
    vsi = ValueSets("SYNP1", {}, None)
    with pytest.raises(CompileError, match="VS_CDR_SCORE"):
        getattr(vsi, method)("VS_CDR_SCORE")
    with pytest.raises(KeyError):
        getattr(vsi, method)("VS_CDR_SCORE")


def test_a_criterion_naming_an_undefined_value_set_goes_to_a_person_and_the_rest_compiles() -> None:
    rs = _rs()
    good = next(c for c in rs.active() if c.id == "GOUT-COH-INC-02")  # latest serum urate, structured
    bad = good.model_copy(
        update={"id": "GOUT-COH-INC-90", "logic": good.logic.model_copy(update={"valueset": "VS_CDR_SCORE"})}
    )
    comp = Compiler(SimpleNamespace(term=Terminology()))  # type: ignore[arg-type]
    out, warnings = comp.demote_uncompilable(rs.id, rs.version, [good, bad], rs.valuesets)
    by_id = {c.id: c for c in out}
    assert by_id["GOUT-COH-INC-02"].class_ == "structured"
    moved = by_id["GOUT-COH-INC-90"]
    assert moved.class_ == "human" and {"needs_review", "compile_error"} <= set(moved.flags or [])
    assert any("GOUT-COH-INC-90" in w and "VS_CDR_SCORE" in w for w in warnings)


def test_a_mixed_criterion_naming_one_keeps_its_note_question() -> None:
    rs = _rs()
    good = next(c for c in rs.active() if c.id == "GOUT-COH-INC-02")
    mixed = good.model_copy(
        update={
            "id": "GOUT-COH-INC-91",
            "class_": "mixed",
            "note_question": "Is the CDR score 0.5 or more?",
            "logic": good.logic.model_copy(update={"valueset": "VS_CDR_SCORE"}),
        }
    )
    comp = Compiler(SimpleNamespace(term=Terminology()))  # type: ignore[arg-type]
    out, _ = comp.demote_uncompilable(rs.id, rs.version, [mixed], rs.valuesets)
    assert out[0].class_ == "note" and "compile_error" in (out[0].flags or [])
