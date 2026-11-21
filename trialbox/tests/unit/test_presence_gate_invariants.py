"""First extraction, including a misleading model paraphrase, through to the compiled patient predicate."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ir_extract.postprocess import PresenceSource, postprocess
from criteria_compiler.semantics import compiled
from criteria_compiler.service import _presence_passages
from criteria_compiler.terminology.mapper import Terminology
from doc_parser.parser import parse
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from orchestrator.scenarios.evaluate import SqlEngine, evaluate_patients
from tb_common.audit import AuditLog
from tb_common.crypto import sha256_text
from tb_common.ruleset import SEED_RULESETS, Ruleset
from tb_contracts import Atom, LlmExtractOutput

from tests.offlist_fixture import SNAPSHOT, build_lake
from tests.unit.test_compiler_service import _compile, env  # noqa: F401 (compiler service fixture)

# Each column changes the meaning of the same diagnosis. Only the first line is a patient affirmative.
PASSAGES = {
    "en": (
        "The patient has gout.",
        "The patient does not have gout.",
        "Family history of gout.",
        "If the patient has gout.",
        "The patient's donor has gout.",
        "The patient has gout. This was ruled out.",
        "Conditions to rule out: gout",
    ),
    "zh-TW": (
        "患者患有痛風。",
        "患者沒有痛風。",
        "痛風家族史。",
        "若患者患有痛風。",
        "捐贈者患有痛風。",
        "患者患有痛風。後來已排除。",
        "須排除的疾病：痛風",
    ),
    "ja": (
        "患者は痛風と診断された。",
        "患者に痛風はない。",
        "痛風の家族歴あり。",
        "患者が痛風の場合。",
        "ドナーは痛風と診断された。",
        "患者は痛風と診断された。その後否定された。",
        "除外すべき疾患：痛風",
    ),
}


def proposal(text: str, cls: str = "structured") -> dict[str, Any]:
    return {
        "text": text,
        "class": cls,
        "kind": "inclusion",
        "logic": {"domain": "condition", "concept": "gout"},
        "concept_candidates": [{"domain": "condition", "name": "gout"}],
    }


@pytest.fixture(scope="module")
def term() -> Terminology:
    return Terminology()


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    return LakeLocal(build_lake(tmp_path_factory.mktemp("presence")), HashEmbedder())


@pytest.mark.parametrize("language", PASSAGES)
def test_held_passages_never_match_a_patient_with_the_code(
    language: str, term: Terminology, lake: LakeLocal, tmp_path: Path
) -> None:
    lines = PASSAGES[language]
    sources = [PresenceSource(t, "inclusion", language) for t in lines]
    # The aligned model answer drops the second sentence. The original source must win.
    answers = [proposal(lines[0] if i == 5 else t) for i, t in enumerate(lines)]
    extracted = LlmExtractOutput.model_validate({"criteria": answers})
    post = postprocess("TRIAL", extracted, term, sources=sources, audit=AuditLog(tmp_path))
    first, *held = post.criteria
    assert [c.text for c in post.criteria] == list(lines)
    assert compiled(post.criteria) == [first] and first.class_ == "structured"
    for c in held:
        assert c.class_ == "human" and c.human_question and c.note_question is None
        assert {"needs_review", "presence_requires_review"} <= set(c.flags or [])
        assert isinstance(c.logic, Atom) and c.logic.valueset == "NONE"
        assert {"en": "full passage", "zh-TW": "完整原文", "ja": "原文全体"}[language] in c.human_question
    events = [json.loads(row) for path in tmp_path.glob("*.jsonl") for row in path.read_text().splitlines()]
    assert [e["input_sha"] for e in events if e["event"] == "compile.presence_admitted"] == [sha256_text(lines[0])]
    sql = SqlGenerator("TRIAL", "1.0.0", post.vs_index("TRIAL", term)).render(post.criteria)
    # OFF-NONE has a dated ICD-10-CM M10.00 diagnosis in the public synthetic off-list fixture.
    (patient,) = lake.query(sql, [[SNAPSHOT], ["OFF-NONE"]], SNAPSHOT).to_pylist()
    assert patient["pid"] == "OFF-NONE"
    assert {k: v for k, v in patient.items() if k.startswith("C_")} == {f"C_{first.id}": True}
    manifest = Ruleset.load(SEED_RULESETS / "GZQO").manifest.model_copy(
        update={"id": "TRIAL", "criteria": [c.id for c in post.criteria]}
    )
    ruleset = Ruleset(manifest, post.criteria, post.valuesets, sql=sql)
    screened = evaluate_patients(
        ruleset, ["OFF-NONE"], date.fromisoformat(SNAPSHOT), SqlEngine(lake, SNAPSHOT), judge=None, threshold=0.9
    )
    verdicts = {v.id: v.verdict for v in screened["OFF-NONE"].verdicts}
    assert verdicts == {first.id: "pass", **{c.id: "pending_human" for c in held}}


@pytest.mark.parametrize("answer", ["retry", "paraphrase", "cropped-item"])
def test_compile_carries_original_source_through_alignment_and_retry(
    env: dict[str, Any],  # noqa: F811 (compiler service fixture)
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    from tb_common.llm import LlmResult
    from tb_contracts import dump_json

    affirmative = PASSAGES["en"][0]
    split = PASSAGES["en"][5]
    section = f"Inclusion Criteria\n1. {affirmative}\n2. {split}\nFamily history:\n- {affirmative}"
    doc = parse(section.encode(), "synthetic.txt", backend="lite")
    assert doc.ie_block.inclusion == [affirmative, split, "Family history:", affirmative]
    if answer == "cropped-item":
        # A stale or incomplete parsed block can agree with the model on just the first sentence.
        doc.ie_block.inclusion[1] = affirmative
    calls: list[list[str]] = []

    def chat(prompt: str, variables: dict[str, Any], **kwargs: Any) -> LlmResult:
        lines = [ln["text"] for ln in variables["criteria"]]
        calls.append(lines)
        if answer == "retry" and len(calls) == 1:
            # Leave out the contextual child. It will be retried without the heading in the model prompt.
            answers = [proposal(ln) for ln in lines[:-1]]
        else:
            answers = [proposal(ln) for ln in lines]
        if answer == "paraphrase":
            answers[1] = proposal("Patient has a diagnosis of gout.")
        return LlmResult({"criteria": answers}, prompt, 4, "synthetic", "local", "i", "o", 1, 1, 1)

    monkeypatch.setattr(env["deps"].llm, "chat_json", chat)
    # The patient assertion is checked against the produced SQL above. This wiring test needs no JVM.
    env["deps"].translator = None
    key = "attachments/J/presence.json"
    env["store"].put(key, dump_json(doc).encode())
    result = _compile(env, key=key)
    if answer == "retry":
        assert len(calls) == 2 and calls[-1] == [affirmative]
    else:
        assert len(calls) == 1
    first, split_line, heading, child = result.criteria
    assert first.class_ == "structured"
    for c in (split_line, heading, child):
        assert c.class_ == "human" and "presence_requires_review" in (c.flags or [])
        assert c.human_question and "full passage" in c.human_question
    assert child.text == "Family history:\n" + affirmative


@pytest.mark.parametrize(
    ("language", "section", "heading"),
    [("en", "Inclusion Criteria", "Family history"), ("zh-TW", "納入條件", "家族史"), ("ja", "選択基準", "家族歴")],
)
def test_an_unnumbered_heading_can_govern_a_numbered_assertion(language: str, section: str, heading: str) -> None:
    line = PASSAGES[language][0]
    doc = parse(f"{section}\n{heading}\n2. {line}".encode(), "source.txt", backend="lite")
    _, _, passage = _presence_passages(doc)["inclusion"][1]
    assert not passage.standalone and passage.text == f"{heading}\n{line}"


# The assertions name the protocol's actual passages. Both the frozen extraction and the
# document are read separately so a model answer cannot stand in for a missing passage.
@pytest.mark.parametrize(
    ("ruleset", "released"),
    [
        (
            "GZQO",
            [
                "Type 1 diabetes mellitus.",
                "History of acute or chronic pancreatitis.",
                "Use of a GLP-1 receptor agonist or GIP/GLP-1 receptor agonist within 90 days before screening.",
                "Myocardial infarction or stroke within 90 days before screening.",
            ],
        ),
        (
            "AD-MAB",
            [
                "スクリーニング前90日以内に抗凝固薬（ワルファリン、直接経口抗凝固薬）を使用した者。",
                "スクリーニング前12か月以内に脳卒中または一過性脳虚血発作（TIA）の既往がある者。",
            ],
        ),
        (
            "NEUR-COH",
            [
                "軽度認知障害（MCI）または認知症（アルツハイマー型、血管性、その他）と診断されている者"
                "（ICD-10-CM G31.84、G30、F01〜F03）。",
            ],
        ),
        (
            "RA-JAK",
            [
                "Rheumatoid arthritis diagnosed at least 6 months before screening.",
                "Any prior biologic DMARD or JAK inhibitor.",
                "Herpes zoster within 12 months before screening.",
                "History of venous thromboembolism (deep vein thrombosis or pulmonary embolism).",
                "Malignancy within the past 5 years.",
            ],
        ),
    ],
)
def test_numbered_protocol_items_released_from_the_original_passage(
    ruleset: str, released: list[str], term: Terminology, tmp_path: Path
) -> None:
    root = Path(__file__).resolve().parents[2]
    suffix = "pdf" if ruleset == "GZQO" else "docx"
    (document,) = (root / "tests/fixtures/protocols").glob(f"{ruleset}*.{suffix}")
    parsed = parse(document.read_bytes(), document.name, backend="lite")
    sources = [s for section in _presence_passages(parsed).values() for _, _, s in section]
    cassette = root / "services/llm_stub/cassettes/ir_extract" / f"{ruleset}.json"
    extraction = LlmExtractOutput.model_validate_json(cassette.read_bytes())
    post = postprocess(ruleset, extraction, term, sources=sources, audit=AuditLog(tmp_path))
    got = {c.text: c for c in post.criteria}
    expected = Ruleset.load(SEED_RULESETS / ruleset).by_id()
    for text in released:
        criterion = got[text]
        prior = expected[criterion.id]
        assert criterion.class_ == prior.class_ and criterion in compiled(post.criteria)
        assert criterion.logic == prior.logic and criterion.note_question == prior.note_question


@pytest.mark.parametrize("heading", ["Family history", "Study Population"])
def test_governing_parent_survives_numbered_section_headings(heading: str) -> None:
    text = "History of acute or chronic pancreatitis."
    doc = parse(f"# 5 {heading}\nDiagnoses in the donor\n5.1 Inclusion Criteria\n1. {text}".encode(), "s.txt")
    ((_, _, passage),) = _presence_passages(doc)["inclusion"]
    qualifier = "Diagnoses in the donor" if heading == "Study Population" else "5 Family history"
    assert not passage.standalone and passage.text == f"{qualifier}\n{text}"


@pytest.mark.parametrize("subject", ["donor", "patient"])
def test_bullets_and_governing_instruction_on_retry(
    env: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    subject: str,
) -> None:
    from tb_common.llm import LlmResult
    from tb_contracts import dump_json

    donor = subject == "donor"
    first = "The following diagnoses refer to the donor." if donor else "The patient has gout."
    second = "The patient has a diagnosis of rheumatoid arthritis."
    rows = [f"1. {first}", f"2. {second}"] if donor else [f"- {first}", f"- {second}"]
    doc = parse(("\n".join(["Inclusion Criteria", *rows])).encode(), "section.txt", backend="lite")
    calls = []

    def chat(prompt: str, variables: dict[str, Any], **kwargs: Any) -> LlmResult:
        lines = [ln["text"] for ln in variables["criteria"]]
        calls.append(lines)
        answers = [proposal(line) for line in (lines[:1] if len(calls) == 1 else lines)]
        if len(calls) == 2:
            answers[0]["logic"]["concept"] = answers[0]["concept_candidates"][0]["name"] = "rheumatoid arthritis"
        return LlmResult({"criteria": answers}, prompt, 4, "test", "local", "i", "o", 1, 1, 1)

    monkeypatch.setattr(env["deps"].llm, "chat_json", chat)
    env["deps"].translator = None
    key = "attachments/J/section.json"
    env["store"].put(key, dump_json(doc).encode())
    result = _compile(env, key=key)
    assert calls == [[first, second], [second]]
    assert [c.class_ for c in result.criteria] == (["human", "human"] if donor else ["structured", "structured"])
    if donor:
        assert result.criteria[-1].text == first + "\n" + second


def test_admission_receipt_uses_replacement_id(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from tb_common.llm import LlmResult
    from tb_contracts import dump_json

    base = Ruleset.load(SEED_RULESETS / "GZQO")
    base.criteria = [base.by_id()[f"GZQO-EXC-0{i}"] for i in (1, 2)]
    base.manifest.criteria = [c.id for c in base.criteria]
    monkeypatch.setattr(env["comp"], "_approved", lambda _: base)
    line = "The patient has gout."
    parsed = parse(
        f"Exclusion Criteria\n1. {base.criteria[0].text}\n2. {line}".encode(), "amendment.txt", backend="lite"
    )
    key = "attachments/J/amendment.json"
    env["store"].put(key, dump_json(parsed).encode())
    answer = {**proposal(line), "kind": "exclusion"}
    monkeypatch.setattr(
        env["deps"].llm,
        "chat_json",
        lambda *a, **kw: LlmResult({"criteria": [answer]}, "p", 4, "test", "local", "i", "o", 1, 1, 1),
    )
    result = _compile(env, key=key)
    receipt_ids = [
        e["detail"]["criterion"]
        for path in (env["tmp"] / "audit").glob("*.jsonl")
        for row in path.read_text().splitlines()
        if (e := json.loads(row))["event"] == "compile.presence_admitted"
    ]
    assert receipt_ids == [result.criteria[-1].id] == ["GZQO-EXC-02"]


def test_present_tense_does_not_match_a_resolved_diagnosis(term: Terminology, tmp_path: Path) -> None:
    from lake.store import Lake

    from tests.unit.test_clinical_status import _cond

    text = "The patient has gout."
    answer = proposal(text)
    post = postprocess(
        "T",
        LlmExtractOutput.model_validate({"criteria": [answer]}),
        term,
        sources=[PresenceSource(text, "inclusion", "en")],
        audit=AuditLog(tmp_path),
    )
    assert post.criteria[0].class_ == "structured"
    sql = SqlGenerator("T", "1.0.0", post.vs_index("T", term)).render(post.criteria)
    nd = tmp_path / "ndjson"
    nd.mkdir()
    patients = ["P-RESOLVED", "P-ACTIVE"]
    (nd / "Patient.ndjson").write_text("\n".join(json.dumps({"resourceType": "Patient", "id": p}) for p in patients))
    (nd / "Condition.ndjson").write_text("\n".join(json.dumps(_cond(p, p, "M10.00", p[2:].lower())) for p in patients))
    (nd / "Observation.ndjson").write_text("")
    Lake(tmp_path / "lake").rebuild("2026-10-05", HashEmbedder(), nd)
    lake = LakeLocal(tmp_path / "lake", HashEmbedder())
    rows = lake.query(sql, [["2026-10-05"], ["P-RESOLVED", "P-ACTIVE"]]).to_pylist()
    assert {row["pid"]: row["C_T-INC-01"] for row in rows} == {"P-RESOLVED": None, "P-ACTIVE": True}


@pytest.mark.parametrize(
    ("language", "title", "lead", "child"),
    [
        ("en", "Inclusion Criteria", "The criteria below apply to the partner.", "History of stroke"),
        ("zh-TW", "納入條件", "下列診斷指捐贈者。", "患者患有痛風。"),
        ("ja", "選択基準", "以下の項目はドナーに関する。", "患者は痛風と診断された。"),
    ],
)
def test_numbered_instructions_govern_the_next_item_in_each_language(
    language: str, title: str, lead: str, child: str
) -> None:
    doc = parse(f"{title}\n1. {lead}\n2. {child}".encode(), "section.txt", backend="lite")
    _, _, source = _presence_passages(doc)["inclusion"][1]
    assert source == PresenceSource(lead + "\n" + child, "inclusion", language, standalone=False)


@pytest.mark.parametrize(
    ("ruleset", "released"),
    [("GZQO", {"GZQO-EXC-01", "GZQO-EXC-02"}), ("AD-MAB", set()), ("NEUR-COH", set()), ("RA-JAK", set())],
)
def test_single_concept_admissions_across_shipped_protocols(
    ruleset: str, released: set[str], term: Terminology, tmp_path: Path
) -> None:
    from criteria_compiler.semantics import Kind, atoms, kind

    root = Path(__file__).resolve().parents[2]
    suffix = "pdf" if ruleset == "GZQO" else "docx"
    (document,) = (root / "tests/fixtures/protocols").glob(f"{ruleset}*.{suffix}")
    parsed = parse(document.read_bytes(), document.name, backend="lite")
    sources = [s for section in _presence_passages(parsed).values() for _, _, s in section]
    extracted = LlmExtractOutput.model_validate_json(
        (root / "services/llm_stub/cassettes/ir_extract" / f"{ruleset}.json").read_bytes()
    )
    post = postprocess(ruleset, extracted, term, sources=sources, audit=AuditLog(tmp_path))
    before = {
        c.id
        for c in compiled(Ruleset.load(SEED_RULESETS / ruleset).criteria)
        if any(kind(a) is Kind.PRESENCE for a in atoms(c.logic))
    }
    assert {c.id for c in compiled(post.criteria) if c.id in before} == released
    assert {
        c.id
        for c in post.criteria
        if c.id in before and c.class_ == "human" and "presence_requires_review" in (c.flags or [])
    } == before - released


@pytest.mark.parametrize(
    "heading", ["The diagnoses in this list concern the donor.", "Active diagnoses.", "Donor medical history."]
)
def test_a_numbered_scope_label_survives_its_terminal_period(heading: str) -> None:
    child = "History of stroke"
    parsed = parse(f"Inclusion Criteria\n1. {heading}\n2. {child}".encode(), "section.txt", backend="lite")
    _, _, source = _presence_passages(parsed)["inclusion"][1]
    assert not source.standalone and source.text == heading + "\n" + child
