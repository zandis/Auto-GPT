"""NEW-LIFE-2, the "any of" step (deep review 2026-11-12, LIFE-002; the design approved on #639, 2026-11-15, D-793).

D-785 sent every line of a group to a person and D-789 made the parser keep the groups. A set of alternative groups now
becomes one criterion whose logic is ``or(and(group 1), and(group 2), …)``, built from the members' own extracted IR
(no new model call), and compiles like any other, but only when every member is ``structured``; otherwise the set
stays with a person, as before. Alternatives are two or more adjacent lead-in groups the parser gave, each lead-in
short or naming a diagnosis, or a lead-in that says "one of / any of / either … or / いずれか / 任一" over its bullets.
An OR excludes only when every alternative fails, so it never excludes more than the old AND. The public early-AD
protocol NCT03887455's MCI and mild AD dementia groups are the test case. Synthetic and public text, the stub model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from criteria_compiler.structure import alternatives

ROOT = Path(__file__).resolve().parents[2]


def _lines(spec: list[tuple[str, int | None]], kind: str = "inclusion") -> list[dict[str, Any]]:
    return [
        {"text": t, "kind": kind, "source_ref": f"Inclusion Criteria #{i + 1}", "parent": p}
        for i, (t, p) in enumerate(spec)
    ]


def test_the_public_early_ad_protocols_mci_and_mild_ad_groups_are_alternatives() -> None:
    from doc_parser.parser import parse

    data = json.loads((ROOT / "tests/fixtures/public_protocols/NCT03887455.json").read_text("utf-8"))

    def find(o: Any) -> Any:
        if isinstance(o, dict):
            for k, v in o.items():
                got = v if k == "eligibilityCriteria" else find(v)
                if got:
                    return got
        return None

    block = parse(find(data).encode(), "x.txt").ie_block
    inc = block.inclusion
    pos = (block.item_refs or {})["inclusion"]
    lines = [{"text": t, "kind": "inclusion", "source_ref": f"{r.section} #{r.n}", "parent": r.parent}
             for t, r in zip(inc, pos, strict=True)]  # fmt: skip
    sets = alternatives(lines)
    mci = next(i for i, t in enumerate(inc) if t.startswith("Diagnosis: Mild Cognitive Impairment"))
    mild = inc.index("Mild Alzheimer's disease dementia:")
    key = inc.index("Key Inclusion Criteria that must be met by all participants:")
    assert len(sets) >= 1
    first = sets[0]
    assert [g.lead for g in first.groups] == [mci, mild]
    assert first.groups[0].members == list(range(mci + 1, mild))
    assert first.groups[1].members == list(range(mild + 1, key))


def test_a_lead_in_that_says_one_of_makes_each_bullet_an_alternative() -> None:
    lines = _lines([("Has one of the following:", None), ("asthma", 0), ("COPD", 0)])
    sets = alternatives(lines)
    assert len(sets) == 1 and [g.members for g in sets[0].groups] == [[1], [2]]


def test_long_lead_ins_that_name_no_diagnosis_are_no_alternatives() -> None:
    lines = _lines(
        [
            ("Participants enrolled at the sites of the first recruitment wave of the study:", None),
            ("age 18 or older", 0),
            ("Participants enrolled at the sites of the second recruitment wave of the study:", None),
            ("age 20 or older", 2),
        ]
    )
    assert alternatives(lines) == []


def test_a_single_group_or_a_required_lead_in_is_no_set() -> None:
    assert alternatives(_lines([("MCI due to AD:", None), ("CDR 0.5", 0)])) == []
    required = _lines([("Required for all participants:", None), ("age 18", 0), ("Gout:", None), ("urate 8", 2)])
    assert alternatives(required) == []


def test_lines_without_the_parsers_groups_give_no_set() -> None:
    lines = [{"text": t, "kind": "inclusion", "source_ref": "x"} for t in ("MCI:", "CDR 0.5", "Mild AD:", "CDR 1")]
    assert alternatives(lines) == []


# ------------------------------------------------------------------------------------------------- the compile
BMI = "Body mass index (BMI) ≥27 kg/m² at screening."
EGFR = "Estimated GFR ≥30 mL/min/1.73 m² (CKD-EPI 2021) at screening."
URATE = "Serum urate ≥6.8 mg/dL at screening, or ≥6.0 mg/dL if receiving urate-lowering therapy."
ULT = "Receiving stable urate-lowering therapy for at least 3 months (continuous within the past 6 months, gaps ≤30 days)."
FLARES = "At least 2 gout flares within the 12 months before screening."
AGE = "Male or female participants aged 18 years or older at screening."


def _compile(tmp_path: Path, spec: list[tuple[str, int | None]]) -> Any:
    import tb_contracts as c
    from criteria_compiler.repo import RulesetRepo
    from criteria_compiler.service import Compiler, CompilerDeps
    from criteria_compiler.terminology.mapper import Terminology
    from doc_parser.parser import parse
    from fastapi.testclient import TestClient
    from llm_stub.app import app as stub
    from tb_common.audit import AuditLog
    from tb_common.llm import LlmClient
    from tb_common.objstore import FsStore

    from tests.rulesets_guard import copy_rulesets
    from tests.unit.test_compiler_service import PDF, FakeGate, FakeTranslator

    seed = tmp_path / "seed"
    copy_rulesets(seed, "GZQO")
    store = FsStore(tmp_path / "obj")
    audit = AuditLog(tmp_path / "audit")
    llm = LlmClient("http://stub/v1", "stub", audit=audit)
    llm.http = TestClient(stub)
    deps = CompilerDeps(
        store=store, repo=RulesetRepo(tmp_path / "repo", seed), llm=llm, term=Terminology(),
        settings_thresholds={"equivalence_min_pct": 98.0}, translator=FakeTranslator(),  # type: ignore[arg-type]
        audit=audit, equivalence=FakeGate(), mrn_regex=r"^\d{8}$",
    )  # fmt: skip
    parsed = parse(PDF.read_bytes(), PDF.name)
    texts = [t for t, _ in spec]
    refs = [c.ItemRef(section="Inclusion Criteria", n=i + 1, parent=p) for i, (_, p) in enumerate(spec)]
    exc = parsed.ie_block.exclusion[:1]
    block = parsed.ie_block.model_copy(
        update={
            "inclusion": texts,
            "exclusion": exc,
            "refs": None,
            "item_refs": {"inclusion": refs, "exclusion": [c.ItemRef(section="Exclusion Criteria", n=1)]},
        }
    )
    store.put("a/p.json", c.dump_json(parsed.model_copy(update={"ie_block": block})).encode())
    return Compiler(deps).compile(
        c.CompileRequest(
            job_id="01JTEST0000000000000000003",
            ruleset="GZQO",
            parsed_doc_key="a/p.json",
            requested_by="crc1@hospa.test",
            options={"index_date": "2026-10-05"},
        )
    )


def test_a_set_of_structured_alternatives_compiles_as_one_or_criterion(tmp_path: Path) -> None:
    res = _compile(
        tmp_path,
        [("Obese gout:", None), (BMI, 0), (EGFR, 0), ("Hyperuricaemic gout:", None), (URATE, 3), (ULT, 3),
         ("Required for all participants:", None), (AGE, 6)],
    )  # fmt: skip
    by_text = {x.text: x for x in res.criteria}
    combined = [x for x in res.criteria if "any_of" in (x.flags or [])]
    assert len(combined) == 1
    one = combined[0]
    assert one.class_ == "structured" and "needs_review" not in (one.flags or [])
    logic = one.logic.model_dump(by_alias=True, exclude_none=True)
    assert logic["op"] == "or" and [a["op"] for a in logic["args"]] == ["and", "and"]
    assert all(t not in by_text for t in (BMI, EGFR, URATE, ULT, "Hyperuricaemic gout:"))  # folded into the one
    assert "Obese gout:" in one.text and "Hyperuricaemic gout:" in one.text and BMI in one.text
    assert by_text[AGE].class_ == "structured" and "structure" not in (by_text[AGE].flags or [])
    assert any(one.id in w and "any of" in w for w in res.warnings)
    assert not any(w.startswith("some lines may be alternatives") for w in res.warnings)  # none went to a person


def test_a_set_with_a_note_member_stays_with_a_person(tmp_path: Path) -> None:
    res = _compile(tmp_path, [("Obese gout:", None), (BMI, 0), ("Flaring gout:", None), (FLARES, 2), (URATE, 2)])
    assert not [x for x in res.criteria if "any_of" in (x.flags or [])]
    by_text = {x.text: x for x in res.criteria}
    assert by_text[BMI].class_ == "human" and "group_member" in (by_text[BMI].flags or [])
