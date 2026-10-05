"""IR -> CQL / IR -> SQL: snapshot tests for every atom type, quantifier and bool form (SPEC §11.1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import CompileError, kind, window
from tb_contracts import Atom, CriterionIR

from tests.atoms_ruleset import atoms_ruleset

SNAP = Path(__file__).resolve().parents[1] / "fixtures" / "ir" / "snapshots"


def _check(name: str, text: str) -> None:
    path = SNAP / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8"), f"{name} changed; rerun with UPDATE_SNAPSHOTS=1 if intended"


def test_atoms_cql_snapshot_and_determinism() -> None:
    crit, _, vsi = atoms_ruleset()
    a = CqlGenerator("ATOMS", "1.0.0", vsi).render(crit)
    b = CqlGenerator("ATOMS", "1.0.0", vsi).render(crit)
    assert a == b
    _check("ATOMS.cql", a)
    for c in crit:
        assert f'define "C_{c.id}"' in a and f'define "E_{c.id}"' in a


def test_atoms_sql_snapshot_and_determinism() -> None:
    crit, _, vsi = atoms_ruleset()
    a = SqlGenerator("ATOMS", "1.0.0", vsi).render(crit)
    assert a == SqlGenerator("ATOMS", "1.0.0", vsi).render(crit)
    _check("ATOMS.sql", a)
    for c in crit:
        assert f'"C_{c.id}"' in a


def test_library_version_tracks_content() -> None:
    crit, _, vsi = atoms_ruleset()
    g1 = CqlGenerator("ATOMS", "1.0.0", vsi)
    g1.render(crit)
    g2 = CqlGenerator("ATOMS", "1.0.0", vsi)
    g2.render(crit[:-1])
    assert g1.library_version != g2.library_version and g1.library_version.startswith("1.0.0-b")


def test_only_structured_criteria_are_compiled() -> None:
    crit, _, vsi = atoms_ruleset()
    human = crit[0].model_copy(update={"class_": "human", "id": "ATOMS-INC-99"})
    text = CqlGenerator("ATOMS", "1.0.0", vsi).render([*crit, human])
    assert "ATOMS-INC-99" not in text


def _atom(**kw: object) -> Atom:
    return Atom.model_validate({"domain": "observation", "valueset": "VS_X", **kw})


@pytest.mark.parametrize(
    "bad",
    [
        {"quantifier": "latest"},
        {"quantifier": "all"},
        {"domain": "condition", "quantifier": "count>="},
        {"domain": "demographic", "valueset": "NONE"},
        {"domain": "condition", "duration": {"min_days": 10}},
        {"value": {"op": "between", "num": 1}},
        {"value": {"op": "in"}},
        {"value": {"op": ">"}},
        {"domain": "condition", "value": {"op": ">", "num": 1}},
        {"domain": "condition", "derived": "bmi"},
        {"domain": "condition", "valueset": "NONE"},
    ],
)
def test_invalid_atoms_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(CompileError):
        kind(_atom(**bad))


def test_windows() -> None:
    assert window(_atom()).from_days is None
    assert window(_atom(derived="das28")).from_days == -90
    assert window(_atom(derived="bmi", window={"from_days": -30, "to_days": 0})).from_days == -30
    with pytest.raises(CompileError):
        window(_atom(window={"from_days": 10, "to_days": -10}))
    with pytest.raises(CompileError):
        window(_atom(window={"from_days": -10, "to_days": 0, "anchor": "event"}))


def test_not_requires_one_argument() -> None:
    _, _, vsi = atoms_ruleset()
    bad = CriterionIR.model_validate(
        {
            "id": "ATOMS-EXC-99",
            "ruleset": "ATOMS",
            "text": "x",
            "kind": "exclusion",
            "class": "structured",
            "logic": {
                "op": "not",
                "args": [
                    {"domain": "condition", "valueset": "VS_GOUT"},
                    {"domain": "condition", "valueset": "VS_GOUT"},
                ],
            },
        }
    )
    with pytest.raises(CompileError):
        CqlGenerator("ATOMS", "1.0.0", vsi).render([bad])


def test_sql_comment_cannot_break_out() -> None:
    """Criterion text goes into a ``--`` comment: a newline in it (reviewer's Alt+Enter in review.xlsx, model output)
    must not turn the rest of the text into SQL."""
    import sqlglot

    crit, _, vsi = atoms_ruleset()
    evil = crit[0].model_copy(update={"text": "Age ≥ 18\nyears) AS x; DROP TABLE patient; --\r\n end"})
    sql = SqlGenerator("ATOMS", "1.0.0", vsi).render([evil])
    assert all(line.lstrip().startswith("--") for line in sql.splitlines() if "DROP TABLE" in line)
    stmts = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    assert len(stmts) == 1 and stmts[0].key == "select"
