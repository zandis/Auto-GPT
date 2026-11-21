"""Admission is a decision about this source and this predicate, independent of model assurances."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from criteria_compiler.ir_extract.postprocess import PresenceSource, admit_presence
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
    source = PresenceSource(line, "inclusion", "en")
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
