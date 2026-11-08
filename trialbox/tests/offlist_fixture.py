"""The off-list / unknown-system equivalence fixture (review F3 and F-10, D-113, D-130) for unit and gate tests.

``tests/fixtures/equivalence/offlist/``: FHIR NDJSON (14 patients) whose diagnoses and medicines are coded inside a
grouper's family but outside its list, in systems no ValueSet can read (WHO ICD-10, a MEDIS 病名 code, ICD-9-CM, free
text, a YJ code without ATC), or plainly; ``ruleset.json`` the criteria; ``expected.json`` the oracle.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
from tb_contracts import CriterionIR

FIX = Path(__file__).resolve().parent / "fixtures" / "equivalence" / "offlist"
SNAPSHOT = "2026-10-05"


def offlist_ruleset(
    term: Terminology | None = None,
) -> tuple[list[CriterionIR], dict[str, dict[str, Any]], ValueSets, dict[str, Any]]:
    term = term or Terminology()
    spec = json.loads((FIX / "ruleset.json").read_text("utf-8"))
    crit = [CriterionIR.model_validate(x) for x in spec["criteria"]]
    vs: dict[str, dict[str, Any]] = {}
    for name, (domain, concept) in spec["valuesets"].items():
        res = term.map(domain, concept)
        assert res.concepts and res.families, (name, concept)  # both are code-prefix groupers
        vs[name] = valueset(spec["id"], name, concept, res.concepts, spec["version"], families=res.families)
    expected = json.loads((FIX / "expected.json").read_text("utf-8"))
    return crit, vs, ValueSets(spec["id"], vs, term), expected


def index_date(expected: dict[str, Any]) -> date:
    return date.fromisoformat(expected["index_date"])


def compiled(expected: dict[str, Any]) -> dict[str, dict[str, bool | None]]:
    """``{pid: {criterion: value}}`` both engines must give."""
    ids = expected["criteria"]
    return {pid: dict(zip(ids, vals, strict=True)) for pid, vals in expected["compiled"].items()}


def resources() -> list[dict[str, Any]]:
    out = []
    for f in sorted(FIX.glob("*.ndjson")):
        out += [json.loads(line) for line in f.read_text("utf-8").splitlines() if line.strip()]
    return out


def build_lake(lake_dir: Path) -> Path:
    """An in-process lake holding only the fixture (snapshot ``SNAPSHOT``)."""
    from embed_service.embedder import HashEmbedder
    from lake.store import Lake

    Lake(lake_dir).rebuild(SNAPSHOT, HashEmbedder(), FIX)
    return lake_dir
