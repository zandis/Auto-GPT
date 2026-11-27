"""Admission is a decision about this source and this predicate, independent of model assurances."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from criteria_compiler.ir_extract.postprocess import PresenceSource, admit_presence
from criteria_compiler.ir_extract.presence_approvals import approval_of
from criteria_compiler.terminology.mapper import MappingResult, Terminology, valueset
from tb_common.audit import AuditLog
from tb_common.ruleset import SEED_RULESETS, Ruleset
from tb_contracts import Atom, BoolExpr, CriterionIR, CriterionReview

TEXT = "The patient has gout."


@pytest.fixture(scope="module")
def term() -> Terminology:
    return Terminology()


@pytest.fixture
def maps(term: Terminology) -> dict[str, MappingResult]:
    return {"VS_GOUT": term.map("condition", "gout")}


@pytest.fixture
def criterion() -> CriterionIR:
    return CriterionIR.model_validate(
        {
            "id": "T-INC-01",
            "ruleset": "T",
            "class": "structured",
            "kind": "inclusion",
            "text": TEXT,
            "logic": {"domain": "condition", "valueset": "VS_GOUT"},
        }
    )


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path)


SOURCE = PresenceSource(TEXT, "inclusion", "en")


@pytest.mark.parametrize(
    "source",
    [
        None,
        PresenceSource(TEXT, "exclusion", "en"),
        PresenceSource(TEXT, "inclusion", "und"),
        PresenceSource(TEXT, "inclusion", "en", standalone=False),
        PresenceSource("Family history. " + TEXT, "inclusion", "en"),
    ],
)
def test_missing_or_insufficient_source(
    criterion: CriterionIR,
    term: Terminology,
    maps: dict[str, MappingResult],
    source: PresenceSource | None,
    audit: AuditLog,
) -> None:
    held = admit_presence(criterion, source, maps, term, audit=audit)
    assert held.class_ == "human" and "presence_requires_review" in (held.flags or [])


@pytest.mark.parametrize(
    "logic",
    [
        Atom(domain="condition", valueset="VS_OTHER"),
        Atom(domain="condition", valueset="VS_GOUT", quantifier="none"),
        Atom(domain="condition", valueset="VS_GOUT", quantifier="count>=", count=2),
        BoolExpr(op="not", args=[Atom(domain="condition", valueset="VS_GOUT")]),
    ],
)
def test_text_must_support_the_entire_predicate(
    criterion: CriterionIR, term: Terminology, maps: dict[str, MappingResult], logic: Atom | BoolExpr, audit: AuditLog
) -> None:
    assert (
        admit_presence(criterion.model_copy(update={"logic": logic}), SOURCE, maps, term, audit=audit).class_ == "human"
    )


def test_real_codes_must_match_the_source_diagnosis(criterion: CriterionIR, term: Terminology, audit: AuditLog) -> None:
    assert (
        admit_presence(
            criterion, SOURCE, {"VS_GOUT": term.map("condition", "rheumatoid arthritis")}, term, audit=audit
        ).class_
        == "human"
    )


def test_only_an_independent_decision_on_the_same_text_and_ir(
    criterion: CriterionIR, term: Terminology, maps: dict[str, MappingResult], audit: AuditLog
) -> None:
    line = "A reviewer must confirm gout."
    candidate = criterion.model_copy(update={"text": line})
    source = PresenceSource(line, "inclusion", "en")
    review = CriterionReview(status="approved", by="synthetic-reviewer", at=datetime(2026, 1, 1, tzinfo=UTC))
    recorded = candidate.model_copy(update={"review": review})
    mapped = maps["VS_GOUT"]
    stored_vs = valueset("T", "VS_GOUT", mapped.name, mapped.concepts, "1.0.0", families=mapped.families)
    manifest = Ruleset.load(SEED_RULESETS / "GZQO").manifest.model_copy(update={"id": "T", "criteria": [recorded.id]})
    snapshot = Ruleset(manifest, [recorded], {"VS_GOUT": stored_vs})
    assert admit_presence(recorded, source, maps, term, audit=audit).class_ == "human"
    assert admit_presence(candidate, source, maps, term, audit=audit, approved=snapshot) == candidate
    assert admit_presence(candidate, source, {}, term, audit=audit, approved=snapshot).class_ == "human"
    snapshot.criteria = [recorded, recorded]
    assert admit_presence(candidate, source, maps, term, audit=audit, approved=snapshot).class_ == "human"
    for changed in (
        {"text": line + " "},
        {"logic": Atom(domain="procedure", valueset="VS_GOUT")},
        {"review": CriterionReview(status="approved")},
    ):
        snapshot.criteria = [recorded.model_copy(update=changed)]
        assert admit_presence(candidate, source, maps, term, audit=audit, approved=snapshot).class_ == "human"
    snapshot.criteria = [recorded]
    snapshot.valuesets["VS_GOUT"] = {**stored_vs, "compose": {"include": []}}
    assert admit_presence(candidate, source, maps, term, audit=audit, approved=snapshot).class_ == "human"


def test_an_unavailable_audit_holds_the_affirmative(
    criterion: CriterionIR,
    term: Terminology,
    maps: dict[str, MappingResult],
    audit: AuditLog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise OSError("unavailable")

    assert admit_presence(criterion, SOURCE, maps, term).class_ == "human"
    monkeypatch.setattr(audit, "append", unavailable)
    assert admit_presence(criterion, SOURCE, maps, term, audit=audit).class_ == "human"


def test_refused_terminology_setting_holds_even_an_exact_phrase(
    criterion: CriterionIR,
    term: Terminology,
    maps: dict[str, MappingResult],
    audit: AuditLog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Terminology, "terminology_refused", property(lambda self: [{"table": "unavailable"}]))
    held = admit_presence(criterion, SOURCE, maps, term, audit=audit)
    assert held.class_ == "human" and "presence_requires_review" in (held.flags or [])


def test_a_numeric_predicate_does_not_need_presence_admission(criterion: CriterionIR, term: Terminology) -> None:
    atom = Atom.model_validate({"domain": "observation", "valueset": "VS_URATE", "value": {"op": ">", "num": 6}})
    numeric = criterion.model_copy(update={"logic": atom})
    assert admit_presence(numeric, None, {}, term) is numeric


def test_a_timed_alternative_needs_both_diagnoses_and_the_same_window_per_branch(
    criterion: CriterionIR, term: Terminology, audit: AuditLog
) -> None:
    from tb_contracts import Window

    text = "Myocardial infarction or stroke within 90 days before screening."
    source = PresenceSource(text, "exclusion", "en")
    maps = {name: term.map("condition", name) for name in ("stroke", "myocardial infarction")}
    stroke, mi = [Atom(domain="condition", valueset=name, window=Window(from_days=-90, to_days=0)) for name in maps]
    candidate = criterion.model_copy(
        update={"kind": source.kind, "text": text, "logic": BoolExpr(op="or", args=[stroke, mi])}
    )
    # The owner's ruling (2026-11-22): an alternative runs only on a person's recorded approval of its exact text.
    source = replace(source, approvals=(approval_of(candidate, maps, actor="reviewer A", recorded_at="2026-11-22"),))
    assert admit_presence(candidate, source, maps, term, audit=audit) == candidate
    for wrong in (
        stroke,
        BoolExpr(op="and", args=[mi, stroke]),
        BoolExpr(op="or", args=[mi, mi]),
        BoolExpr(op="or", args=[stroke, mi.model_copy(update={"window": None})]),
        BoolExpr(op="or", args=[stroke, mi.model_copy(update={"quantifier": "none"})]),
    ):
        assert (
            admit_presence(candidate.model_copy(update={"logic": wrong}), source, maps, term, audit=audit).class_
            == "human"
        )


def test_qualifying_text_and_the_mixed_fallback_must_agree(
    criterion: CriterionIR, term: Terminology, audit: AuditLog
) -> None:
    line = "History of venous thromboembolism (deep vein thrombosis or pulmonary embolism)."
    candidate = criterion.model_copy(
        update={
            "text": line,
            "class_": "mixed",
            "logic": Atom(domain="condition", valueset="VTE"),
            "note_question": "Do the notes document a deep vein thrombosis or a pulmonary embolism at any time?",
        }
    )
    maps = {"VTE": term.map("condition", "venous thromboembolism")}
    # The owner's ruling (2026-11-22): a qualified line runs only on a person's recorded approval of its exact text.
    approval = approval_of(candidate, maps, actor="reviewer A", recorded_at="2026-11-22")
    source = PresenceSource(line, "inclusion", "en", approvals=(approval,))
    assert admit_presence(candidate, source, maps, term, audit=audit) == candidate
    wrong = candidate.model_copy(update={"note_question": "Does a parent have a pulmonary embolism?"})
    assert admit_presence(wrong, source, maps, term, audit=audit).class_ == "human"
    for qualified in ("Family history: " + line, line + " Subsequently ruled out."):
        held = admit_presence(
            candidate.model_copy(update={"text": qualified}),
            PresenceSource(qualified, "inclusion", "en"),
            maps,
            term,
            audit=audit,
        )
        assert held.class_ == "human"


def test_codes_listed_in_the_passage_constrain_even_a_matching_site_mapping(
    criterion: CriterionIR, term: Terminology, audit: AuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = (
        "軽度認知障害（MCI）または認知症（アルツハイマー型、血管性、その他）と診断されている者"
        "（ICD-10-CM G31.84、G30、F01〜F03）。"
    )
    candidate = criterion.model_copy(update={"text": text, "logic": Atom(domain="condition", valueset="VS_MCI")})
    source = PresenceSource(text, "inclusion", "ja")
    wrong = term.map("condition", "gout")
    monkeypatch.setattr(term, "map", lambda *args: wrong)
    held = admit_presence(candidate, source, {"VS_MCI": wrong}, term, audit=audit)
    assert held.class_ == "human"


@pytest.mark.parametrize(
    ("language", "line", "name", "domain", "days", "release"),
    [
        ("en", "  12)  History   of stroke", "stroke", "condition", None, True),
        ("en", "History of acute or chronic pancreatitis", "acute or chronic pancreatitis", "condition", None, True),
        ("en", "- Patients with acute appendicitis.", "acute appendicitis", "condition", None, True),
        (
            "en",
            "The patient received methotrexate within 7 days before screening.",
            "methotrexate",
            "medication",
            7,
            True,
        ),
        ("zh-TW", "（三）曾使用 methotrexate。", "methotrexate", "medication", None, True),
        ("ja", "・スクリーニング前7日以内に脳卒中の既往がある者。", "stroke", "condition", 7, True),
        (
            "en",
            "Rheumatoid arthritis diagnosed at least 6 months before screening.",
            "rheumatoid arthritis",
            "condition",
            -180,
            False,
        ),
        ("en", "Malignancy within the past 5 years.", "malignancy", "condition", 1825, False),
        ("en", "Acute appendicitis (except in childhood).", "acute appendicitis", "condition", None, False),
        ("ja", "現在活動性の痛風。", "gout", "condition", None, False),
        ("zh-TW", "目前有痛風", "gout", "condition", None, False),
        ("en", "Myocardial infarction or stroke", "stroke", "condition", None, False),
    ],
)
def test_plain_passage_in_each_language(
    language: str,
    line: str,
    name: str,
    domain: str,
    days: int | None,
    release: bool,
    criterion: CriterionIR,
    term: Terminology,
    audit: AuditLog,
) -> None:
    from tb_contracts import Window

    window = None if days is None else Window(from_days=-days, to_days=0) if days > 0 else Window(to_days=days)
    atom = Atom.model_validate({"domain": domain, "valueset": "V", "window": window})
    candidate = criterion.model_copy(update={"text": line, "logic": atom})
    got = admit_presence(
        candidate, PresenceSource(line, "inclusion", language), {"V": term.map(domain, name)}, term, audit=audit
    )
    assert (got.class_ == "structured") == release


@pytest.mark.parametrize(
    ("language", "line"),
    [
        ("en", "The patient underwent laparoscopic gastric bypass."),
        ("zh-TW", "患者曾接受腹腔鏡胃繞道手術。"),
        ("ja", "患者はlaparoscopic gastric bypassを受けた。"),
    ],
)
def test_named_procedure_uses_the_same_gate(
    language: str, line: str, criterion: CriterionIR, term: Terminology, audit: AuditLog
) -> None:
    name = "腹腔鏡胃繞道手術" if language == "zh-TW" else "laparoscopic gastric bypass"
    atom = Atom(domain="procedure", valueset="P")
    candidate = criterion.model_copy(update={"text": line, "logic": atom})
    assert (
        admit_presence(
            candidate,
            PresenceSource(line, "inclusion", language),
            {"P": term.map("procedure", name)},
            term,
            audit=audit,
        )
        == candidate
    )


@pytest.mark.parametrize(
    ("language", "text", "name"),
    [
        ("en", "The patient has had stroke in the past 2 weeks.", "stroke"),
        ("zh-TW", "過去2週內有痛風病史。", "gout"),
        ("ja", "過去2週間以内に脳卒中の既往がある。", "stroke"),
    ],
)
def test_lookback_means_the_same_number_of_days(
    language: str, text: str, name: str, criterion: CriterionIR, term: Terminology, audit: AuditLog
) -> None:
    from tb_contracts import Window

    source = PresenceSource(text, criterion.kind, language)
    maps = {"V": term.map("condition", name)}
    for days in (13, 14, 15):
        atom = Atom(domain="condition", valueset="V", window=Window(from_days=-days))
        got = admit_presence(
            criterion.model_copy(update={"text": text, "logic": atom}), source, maps, term, audit=audit
        )
        assert (got.class_ == "structured") == (days == 14)


@pytest.mark.parametrize(("ending", "released"), [(";", True), ("！", True), ("?", False), (":", False)])
def test_list_punctuation_preserves_questions_and_lead_ins(
    ending: str,
    released: bool,
    criterion: CriterionIR,
    term: Terminology,
    maps: dict[str, MappingResult],
    audit: AuditLog,
) -> None:
    source = PresenceSource("History of gout" + ending, criterion.kind, "en")
    got = admit_presence(criterion.model_copy(update={"text": source.text}), source, maps, term, audit=audit)
    assert (got.class_ == "structured") == released
