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
from typing import Any, Literal

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
            "item_refs": None,  # a block built by hand, as from a parser before NEW-LIFE-2's positional refs
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


# ------------------------------------------------------------------------------------------------- review fixes
def test_a_cohort_documents_two_sections_are_its_population_and_its_counts(tmp_path: Path) -> None:
    """Review: D-71 parses 世代定義 (who is in) and 計數條件 (what is counted) as two inclusion sections; the second
    is no other phase. A cohort compile keeps them as before."""
    lines = _lines(["痛風の診断がある者"], section="世代定義") + _lines(["尿酸値8.0 mg/dL以上"], section="計數條件")
    assert check(lines, doc_kind="cohort").findings == []
    assert check(lines).findings  # a trial with two inclusion sections still says so


def test_the_shipped_cohort_documents_compile_as_before(tmp_path: Path) -> None:
    res = _compile_doc(tmp_path, "GOUT-COH", ROOT / "tests/fixtures/protocols/GOUT-COH_世代定義_v1.docx", "cohort")
    assert not [x.id for x in res.criteria if "structure" in (x.flags or [])]


def test_a_text_in_two_sections_does_not_decide_which_section_came_first() -> None:
    """Review: the parser keys a line's section by its text, so a line in both sections carries the later one."""
    lines = [
        {"text": "Age 18 years or older", "kind": "inclusion", "source_ref": "Inclusion Criteria (Part B) #1"},
        {"text": "BMI 18 to 35", "kind": "inclusion", "source_ref": "Inclusion Criteria (Part A) #2"},
        {"text": "Age 18 years or older", "kind": "inclusion", "source_ref": "Inclusion Criteria (Part B) #1"},
        {"text": "Completed the treatment period", "kind": "inclusion", "source_ref": "Inclusion Criteria (Part B) #2"},
    ]
    got = _flags(lines)
    assert 1 not in got and "second_section" in got[3]
    assert 0 not in got and 2 not in got  # its section cannot be told: no section finding either way


def test_the_public_early_ad_protocol_groups_its_alternatives_and_not_its_required_lines() -> None:
    """NCT03887455 (public, ClinicalTrials.gov) as the parser gives it: the bullets under the MCI lead-in and under
    the mild AD dementia lead-in go to a person; "Key Inclusion Criteria that must be met by all participants:"
    opens no group, so age, MMSE, BMI and consent compile as before. Read both ways: from the lines alone (D-785's
    guess from colons) and with the parser's lead-ins (NEW-LIFE-2)."""
    import json

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
    mci = next(i for i, t in enumerate(inc) if t.startswith("Diagnosis: Mild Cognitive Impairment"))
    mild = inc.index("Mild Alzheimer's disease dementia:")
    key = inc.index("Key Inclusion Criteria that must be met by all participants:")
    members = set(range(mci + 1, mild)) | set(range(mild + 1, key))
    required = range(key + 1, key + 9)
    plain = [
        {"text": t, "kind": "inclusion", "source_ref": f"{r.section} #{r.n}"} for t, r in zip(inc, pos, strict=True)
    ]
    given = [d | {"parent": r.parent} for d, r in zip(plain, pos, strict=True)]
    for lines in (plain, given):
        got = _flags(lines)
        assert all("group_member" in got.get(i, set()) for i in members), sorted(members - set(got))
        assert all(i not in got for i in required)  # the lines all participants must meet
        assert any("other_phase" in got.get(i, set()) for i in range(key + 9, len(lines)))


@pytest.mark.parametrize(
    "text",
    [
        "Participants must meet one of the following: a. MCI due to AD b. Mild AD dementia",
        "Any of the following prior therapies: methotrexate, leflunomide",
        "Either MCI due to AD or mild AD dementia",
        "At least one of the following findings",
        "以下のいずれかに該当する患者",
        "符合下列任一項條件者",
        "符合下列條件之一者",
    ],
)
def test_alternatives_inside_one_line_are_found(text: str) -> None:
    assert "alternatives_in_line" in _flags(_lines([text])).get(0, set())


@pytest.mark.parametrize(
    "text",
    [
        "Completed the 52-week double-blind treatment period",
        "Eligible for Part 2 of the study",
        "Rolled over from the parent study",
        "Completed Period 1",
        "延長試驗期：完成主試驗者",
        "Assigned to Cohort B",
    ],
)
def test_more_phase_and_cohort_forms(text: str) -> None:
    assert "other_phase" in _flags(_lines([text])).get(0, set())


def test_a_phase_in_the_section_title_flags_its_lines() -> None:
    lines = _lines(["Age 18 or older"]) + _lines(
        ["No new safety signal"], section="Inclusion Criteria for the Open-Label Extension"
    )
    assert "other_phase" in _flags(lines)[1]


def test_a_lead_in_colon_followed_by_a_period_is_a_lead_in() -> None:
    assert "group_heading" in _flags(_lines(["Meets the following criteria:."])).get(0, set())


@pytest.mark.parametrize(
    "lead",
    [
        "Key Inclusion Criteria that must be met by all participants:",
        "All of the following:",
        "Women of childbearing potential must agree to the following:",
    ],
)
def test_a_lead_in_of_required_lines_opens_no_group(lead: str) -> None:
    """Review: such a lead-in sent every later line of its section to a person as a possible alternative."""
    got = _flags(_lines([lead, "Adequate hepatic function", "Signed informed consent"]))
    assert 1 not in got and 2 not in got


@pytest.mark.parametrize(
    "text",
    [
        "Meets all inclusion criteria of the parent protocol at screening",
        "續用時仍須符合初次申請之納入條件",
        "Scores 10 or less on Part B of the questionnaire",
        "Completed week 4 of the run-in",
    ],
)
def test_ordinary_wording_is_left_alone(text: str) -> None:
    assert _flags(_lines([text])) == {}


def test_a_criterion_the_reviewer_approved_keeps_its_decision_and_questions_say_what_to_do() -> None:
    from criteria_compiler.structure import send_to_a_person

    class C:
        def __init__(self, cid: str, text: str) -> None:
            self.id, self.text, self.flags, self.human_question, self.class_ = cid, text, None, None, "structured"

        def model_copy(self, update: dict[str, Any]) -> C:
            new = C(self.id, self.text)
            new.__dict__.update(self.__dict__ | update)
            return new

    lines = _lines(["MCI due to AD:", "Global CDR score of 0.5"])
    crits = [C("X-INC-01", "MCI due to AD:"), C("X-INC-02", "Global CDR score of 0.5")]
    out, warnings = send_to_a_person(crits, check(lines), keep={1})
    assert out[1].class_ == "structured" and len(warnings) == 1  # reused from the approved version: not re-opened
    assert "heading" in out[0].human_question and "Confirm with the patient" not in out[0].human_question


def _compile_doc(tmp_path: Path, ruleset: str, doc: Path, kind: Literal["trial", "nhi", "cohort"]) -> Any:
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
    from tests.unit.test_compiler_service import FakeGate, FakeTranslator

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
    store.put("a/p.json", c.dump_json(parse(doc.read_bytes(), doc.name, backend="lite")).encode())
    return Compiler(deps).compile(
        c.CompileRequest(
            job_id="01JTEST0000000000000000002",
            ruleset=ruleset,
            kind=kind,
            parsed_doc_key="a/p.json",
            requested_by="crc1@hospa.test",
            options={"index_date": "2026-10-05"},
        )
    )
