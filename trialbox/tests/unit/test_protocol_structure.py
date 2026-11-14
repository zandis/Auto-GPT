"""NEW-LIFE-2, the compiler's half (deep review 2026-11-12, LIFE-002): a protocol's structure is no longer lost in
silence.

A real early-AD protocol pasted as text became 48 ANDed criteria with ``warnings: []``: the heading "Diagnosis: Mild
Cognitive Impairment…" was criterion 1, the alternatives under "MCI due to AD:" and "Mild AD dementia:" were all
required, "Key Inclusion Criteria that must be met…" was glued to the end of a criterion, and the extension phase's
criteria ("completed the Core Study", "completed Week 207") sat in the same list. An MCI patient was then excluded for
not having "probable AD dementia" if the model classed that line structured. Now the compiler reads the lines it is
given (``criteria_compiler.structure``): a line ending with a colon (a heading or a group's lead-in), the lines under
it (perhaps alternatives), a line with a section heading inside it, a line naming another study phase, and the lines
of a second inclusion or exclusion section are each sent to a person (class ``human``, ``needs_review``,
``structure``) with a warning that says why; the rest compiles as before. Synthetic protocol text, no model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.structure import check

ROOT = Path(__file__).resolve().parents[2]


def _lines(texts: list[str], kind: str = "inclusion", section: str = "Inclusion Criteria") -> list[dict[str, Any]]:
    return [{"text": t, "kind": kind, "source_ref": f"{section} #{i}"} for i, t in enumerate(texts, start=1)]


AD = _lines(
    [
        "Diagnosis: Mild Cognitive Impairment due to Alzheimer's disease or mild Alzheimer's disease dementia:",
        "Age 50 to 90 years at screening",
        "MCI due to AD:",
        "Objective memory impairment on a delayed recall test",
        "Global CDR score of 0.5",
        "Mild AD dementia:",
        "Meets criteria for probable Alzheimer's disease dementia",
        "Has a study partner who sees the participant at least 8 hours a week Key Inclusion Criteria that must be met",
        "Extension Phase: completed the Core Study through Week 207",
    ]
)


def _flags(lines: list[dict[str, Any]]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for f in check(lines).findings:
        out.setdefault(f.index, set()).add(f.flag)
    return out


def test_headings_groups_glued_headings_and_phases_are_found() -> None:
    got = _flags(AD)
    assert got[0] == {"group_heading"} and got[2] == {"group_heading"} and got[5] == {"group_heading"}
    assert "group_member" in got[3] and "group_member" in got[4] and "group_member" in got[6]
    assert "heading_in_line" in got[7]
    assert "other_phase" in got[8]
    assert 1 in got  # under the first lead-in: perhaps one of its alternatives, a person decides


def test_a_plain_list_is_left_alone() -> None:
    plain = _lines(["Age 18 years or older", "Serum urate at least 7.0 mg/dL", "Signed informed consent"])
    rep = check(plain)
    assert rep.findings == [] and rep.warnings == []


def test_a_second_inclusion_section_is_another_phase_or_population() -> None:
    lines = _lines(["Age 18 years or older", "Serum urate at least 7.0 mg/dL"]) + _lines(
        ["Completed the double-blind period"], section="Inclusion Criteria for the Open-Label Period"
    )
    rep = check(lines)
    got = _flags(lines)
    assert "second_section" in got[2] and 0 not in got and 1 not in got
    assert any("two inclusion sections" in w for w in rep.warnings)


@pytest.mark.parametrize(
    "text,flag",
    [
        ("継続投与期：本試験の52週投与を完了した者", "other_phase"),
        ("年齢20歳以上の者 主な選択基準", "heading_in_line"),
        ("延伸期：已完成主試驗第52週者", "other_phase"),
        ("年滿20歲 主要納入條件", "heading_in_line"),
        ("以下のいずれかに該当する者：", "group_heading"),
        ("符合下列任一項者：", "group_heading"),
    ],
)
def test_japanese_and_chinese_too(text: str, flag: str) -> None:
    assert flag in _flags(_lines([text, "年齢20歳以上の者"])).get(0, set())


def test_a_line_that_only_starts_with_the_heading_is_no_glued_heading() -> None:
    """A section's own first line ("Inclusion criteria include adults …") is not two lines glued."""
    assert _flags(_lines(["Inclusion criteria include adults aged 18 or older"])) == {}


# ------------------------------------------------------------------------------------------------- the compile
def _env(tmp_path: Path) -> Any:
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
        store=store,
        repo=RulesetRepo(tmp_path / "repo", seed),
        llm=llm,
        term=Terminology(),
        settings_thresholds={"equivalence_min_pct": 98.0},
        translator=FakeTranslator(),  # type: ignore[arg-type]
        audit=audit,
        equivalence=FakeGate(),
        mrn_regex=r"^\d{8}$",
    )
    parsed = parse(PDF.read_bytes(), PDF.name)
    block = parsed.ie_block.model_copy(
        update={
            "inclusion": [x["text"] for x in AD],
            "exclusion": ["Contraindication to MRI"],
            "refs": {x["text"]: x["source_ref"] for x in AD},
        }
    )
    store.put("attachments/S/parsed.json", c.dump_json(parsed.model_copy(update={"ie_block": block})).encode())
    comp = Compiler(deps)
    return comp.compile(
        c.CompileRequest(
            job_id="01JTEST0000000000000000001",
            ruleset="ADSTRUCT",
            parsed_doc_key="attachments/S/parsed.json",
            requested_by="crc1@hospa.test",
            options={"index_date": "2026-10-05"},
        )
    )


def test_the_compile_sends_each_found_line_to_a_person_and_says_why(tmp_path: Path) -> None:
    res = _env(tmp_path)
    by_text = {x.text: x for x in res.criteria}
    flagged = {i for i in _flags(AD)}
    for i, line in enumerate(AD):
        crit = by_text[line["text"]]
        if i in flagged:
            assert crit.class_ == "human" and {"needs_review", "structure"} <= set(crit.flags or []), line["text"]
            assert crit.id in res.needs_review
            assert any(w.startswith(f"{crit.id}: ") for w in res.warnings)
    assert by_text["Contraindication to MRI"].class_ != "human" or "structure" not in (
        by_text["Contraindication to MRI"].flags or []
    )
    assert any("alternatives" in w for w in res.warnings)
