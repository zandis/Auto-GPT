"""Card 10A-1d (D-1248): an inclusion runs as presence only when its line is positively recognised.

The cue reading of cards 10A-1 to 10A-1c held a line only when it found a negation cue, so every shape nobody listed
ran as "the patient has it": a drug stopped or refused, a plan, another person's condition, remission, a heading, a
checkbox ticked "No". Now a structured or mixed inclusion that asks the presence of a concept runs only when each
clause naming the concept is made of that concept's names and the words listed in
``services/criteria_compiler/ir_extract/recognised_assertions.yaml``. Each rule below has a line it holds and a near
line it lets run; removing the rule (or the words it relies on) fails one of them.

The development set ``tests/fixtures/negated_inclusion/card_10a1d_development.tsv`` is synthetic: 590 lines in
English, Japanese and Chinese. The first 471 were labelled before the rule was written; each later round came with
the frames it tests and their nearest must-hold lines. No patients.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.ir_extract import recognition as rec
from criteria_compiler.ir_extract.recognition import recognised, unrecognised_presence
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import Atom, LlmExtractOutput

from tools.negated_inclusion_score import read_rows, score

FLAG, UNREAD = "negated_inclusion_presence", "presence_not_recognised"
DEV = Path(__file__).resolve().parents[1] / "fixtures/negated_inclusion/card_10a1d_development.tsv"
ROWS = read_rows(DEV)
# the five must-run lines the cue rules (the second net) already held at 71e85bbc, before this card: a second
# sentence with a negation the cue rules cannot explain, and the ACR/EULAR lines whose "満たす" / "符合" clause they hold
CUED_BEFORE = {
    "Type 2 diabetes. Not pregnant.",
    "2型糖尿病の患者。妊娠していない。",
    "第二型糖尿病。未懷孕。",
    "2010年ACR/EULAR分類基準を満たす関節リウマチ",
    "符合2010年ACR/EULAR分類標準之類風濕性關節炎",
}
_HELD: list[list[bool]] = []


def _dev_held() -> list[bool]:
    if not _HELD:
        _HELD.append(score(ROWS))
    return _HELD[0]


def test_the_development_set_is_what_d1248_counts() -> None:
    assert len(ROWS) == 590
    assert sum(r["expect"] == "held" for r in ROWS) == 337
    assert {r["lang"] for r in ROWS} == {"en", "ja", "zh"}


def test_every_must_hold_line_of_the_development_set_is_held() -> None:
    """At 71e85bbc (the cue reading alone) 201 of the first 297 of these lines ran."""
    missed = [r["text"] for r, h in zip(ROWS, _dev_held(), strict=True) if r["expect"] == "held" and not h]
    assert missed == []


def test_every_must_run_line_of_the_development_set_runs_but_the_five_the_cue_rules_hold() -> None:
    """The frames and qualifiers are pinned by the lines they let run: a word dropped from the data fails here."""
    held = {r["text"] for r, h in zip(ROWS, _dev_held(), strict=True) if r["expect"] == "runs" and h}
    assert held == CUED_BEFORE


def _rows(*lines: tuple[str, str, str]) -> list[dict[str, Any]]:
    return [{"text": t, "concept": k, "domain": d, "expect": "runs", "synonyms": [], "others": []} for t, k, d in lines]


@pytest.mark.parametrize(
    "line",
    [r for r in ROWS if r["lang"] == "en" and r["expect"] == "runs" and r["text"] not in CUED_BEFORE],
    ids=lambda r: r["text"][:40],
)
def test_an_unknown_word_in_the_concepts_clause_holds_it_and_one_in_another_clause_does_not(
    line: dict[str, Any],
) -> None:
    """An unknown word is a reason to hold, never a reason to run. A clause ends at ";": a word there that names no
    concept and does not point back at this one is not this concept's clause."""
    inside = {**line, "text": "Zorblatic " + line["text"]}
    apart = {**line, "text": line["text"].rstrip(".") + "; zorblatic"}
    assert score([inside, apart]) == [True, False]


@pytest.mark.parametrize(
    ("held", "runs"),
    [
        # R0 of this card: the line never names the coded concept
        (("Insulin resistance", "metformin", "medication"), ("Taking metformin", "metformin", "medication")),
        # a negating prefix on the name itself
        (("Non-diabetic", "diabetes", "condition"), ("Diabetic", "diabetes", "condition")),
        # a heading: the clause ends in a colon
        (("Asthma:", "asthma", "condition"), ("Asthma: moderate", "asthma", "condition")),
        # `holds`: listed words that together say otherwise
        (("Asthma: 0", "asthma", "condition"), ("Asthma, step 2", "asthma", "condition")),
        (
            ("Up to 2 prior lines of chemotherapy", "chemotherapy", "procedure"),
            ("At least 2 prior lines of chemotherapy", "chemotherapy", "procedure"),
        ),
        (
            ("0-2 prior lines of chemotherapy", "chemotherapy", "procedure"),
            ("1-2 prior lines of chemotherapy", "chemotherapy", "procedure"),
        ),
        (
            ("Chemotherapy on day 1", "chemotherapy", "procedure"),
            ("Chemotherapy for 14 days", "chemotherapy", "procedure"),
        ),
        (("化學治療第1天", "化學治療", "procedure"), ("曾接受化學治療", "化學治療", "procedure")),
        (("化学療法2レジメン以下", "化学療法", "procedure"), ("化学療法2レジメン以上", "化学療法", "procedure")),
        # `exceptions`: what an exception names is cut out; the coded concept inside one holds
        (
            ("Any active malignancy except basal cell carcinoma", "basal cell carcinoma", "condition"),
            ("Any active malignancy except basal cell carcinoma", "malignancy", "condition"),
        ),
        (
            ("基底細胞癌を除く活動性悪性腫瘍", "基底細胞癌", "condition"),
            ("基底細胞癌を除く活動性悪性腫瘍", "悪性腫瘍", "condition"),
        ),
        (
            ("除基底細胞癌外之活動性惡性腫瘤", "基底細胞癌", "condition"),
            ("除基底細胞癌外之活動性惡性腫瘤", "惡性腫瘤", "condition"),
        ),
        # `needs`: "criteria" asserts only with a word that says the patient meets them
        (
            ("Criteria for rheumatoid arthritis", "rheumatoid arthritis", "condition"),
            ("Rheumatoid arthritis meeting the 2010 ACR/EULAR criteria", "rheumatoid arthritis", "condition"),
        ),
        # `anaphora`: another clause that points back at the concept must be recognised as well
        (
            ("Type 2 diabetes. Diagnosis pending confirmation.", "type 2 diabetes", "condition"),
            ("Type 2 diabetes. Diagnosis confirmed by a physician.", "type 2 diabetes", "condition"),
        ),
        # a class applies to its domains: "refractory" qualifies a disease, says a drug failed
        (("Refractory rituximab", "rituximab", "medication"), ("Refractory epilepsy", "epilepsy", "condition")),
        # a bracketed abbreviation right after the name, not a chart's answer
        (("Diabetes (NO)", "diabetes", "condition"), ("Diabetes (DM)", "diabetes", "condition")),
        # a line of kanji alone is read with the Japanese and the Chinese words
        (("寛解期乳癌", "乳癌", "condition"), ("転移性乳癌", "乳癌", "condition")),
        # a bound on a count of the concept itself: zero meets it
        (
            ("≤1 prior myocardial infarction", "myocardial infarction", "condition"),
            ("At least 1 prior myocardial infarction", "myocardial infarction", "condition"),
        ),
        (("喘息発作が年2回以下", "喘息発作", "condition"), ("喘息発作が年2回以上", "喘息発作", "condition")),
        (("心衰竭住院不超過2次", "心衰竭住院", "encounter"), ("心衰竭住院至少2次", "心衰竭住院", "encounter")),
        # `ended`: a clause that says it ended, with no past window in the atom (the scorer's atom has none)
        (
            ("Previously treated with tamoxifen; last dose 2 years ago", "tamoxifen", "medication"),
            ("Previously treated with tamoxifen", "tamoxifen", "medication"),
        ),
        (
            ("メトトレキサート最終投与から6か月以上経過", "メトトレキサート", "medication"),
            ("メトトレキサートを6か月以上服用中", "メトトレキサート", "medication"),
        ),
        # "status after" and "post" are listed for procedures only
        (
            ("Post-COVID-19", "COVID-19", "condition"),
            ("At least 6 months post-hysterectomy", "hysterectomy", "procedure"),
        ),
        # "criteria for X" is a definition unless the patient meets them
        (
            ("Diagnostic criteria for schizophrenia", "schizophrenia", "condition"),
            ("Meeting DSM-5 diagnostic criteria for schizophrenia", "schizophrenia", "condition"),
        ),
        # "undergoing" is listed; "undergo" after a plan or an eligibility is not
        (
            ("Eligible to undergo carotid endarterectomy", "carotid endarterectomy", "procedure"),
            ("Patients undergoing carotid endarterectomy", "carotid endarterectomy", "procedure"),
        ),
        # a time anchor that may lie after the start of the study is not listed
        (
            ("Insulin at randomisation", "insulin", "medication"),
            ("Insulin before randomisation", "insulin", "medication"),
        ),
    ],
    ids=lambda x: x[0][:30],
)
def test_each_rule_holds_its_line_and_lets_its_near_line_run(
    held: tuple[str, str, str], runs: tuple[str, str, str]
) -> None:
    assert score(_rows(held, runs)) == [True, False]


def test_another_named_concept_needs_a_link_word() -> None:
    """Another concept the extractor named may share the clause only when a link word or a list mark joins it."""
    assert recognised("Underwent surgery for colorectal cancer", ["surgery"], ["colorectal cancer"], "procedure")
    assert recognised("Type 2 diabetes and hypertension", ["type 2 diabetes"], ["hypertension"])
    assert not recognised("Metformin allergy", ["metformin"], ["allergy"], "medication")


def test_requiring_is_listed_only_before_another_named_concept() -> None:
    """ "requiring {O}": a treatment of the concept, named; never the coded concept itself ("requiring chemotherapy")."""
    assert recognised("Heart failure requiring dialysis", ["heart failure"], ["dialysis"])
    assert not recognised("Heart failure not requiring dialysis", ["heart failure"], ["dialysis"])
    assert not recognised("Patients requiring chemotherapy", ["chemotherapy"], domain="procedure")
    assert recognised("透析を要する慢性腎臓病", ["慢性腎臓病"], ["透析"])
    assert not recognised("化学療法を要する患者", ["化学療法"], domain="procedure")


def test_a_clause_that_says_it_ended_runs_only_when_the_atom_asks_the_past() -> None:
    """How it is told: the atom's window ends before the index day. Without one the line is held."""
    line = "Previously treated with rituximab; last dose more than 12 months ago"
    now = Atom(domain="medication", valueset="VS_RTX", quantifier="any")
    past = Atom.model_validate({"domain": "medication", "valueset": "VS_RTX", "quantifier": "any",
                                "window": {"anchor": "index", "to_days": -365}})  # fmt: skip
    assert unrecognised_presence(line, now, lambda vs: ["rituximab"])
    assert not unrecognised_presence(line, past, lambda vs: ["rituximab"])
    # a clause that names another concept is about that one
    assert recognised("Taking rituximab; last dose of methotrexate 2 years ago", ["rituximab"], ["methotrexate"],
                      "medication")  # fmt: skip


def test_a_past_occurrence_counts_only_when_the_logic_allows_it() -> None:
    assert recognised("History of asthma", ["asthma"], history=True)
    assert not recognised("History of asthma", ["asthma"], history=False)
    active = Atom(domain="condition", valueset="VS_ASTHMA", quantifier="any", clinical_status=["active"])
    anytime = Atom(domain="condition", valueset="VS_ASTHMA", quantifier="any")
    assert unrecognised_presence("History of asthma", active, lambda vs: ["asthma"])
    assert not unrecognised_presence("History of asthma", anytime, lambda vs: ["asthma"])


def test_a_measured_atom_is_never_read_for_presence() -> None:
    """As for the cue rules: an atom that compares a value asks a measure, not a presence."""
    hba1c = Atom.model_validate({"domain": "observation", "valueset": "VS_HBA1C", "quantifier": "latest",
                                 "value": {"op": "between", "num": 7, "num2": 10, "unit": "%"}})  # fmt: skip
    assert not unrecognised_presence("Zorblatic HbA1c planned", hba1c, lambda vs: ["HbA1c"])


def test_every_listed_word_is_a_string(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """YAML reads a bare on, no or yes as a boolean; a word that is not a string fails loudly, never silently."""
    bad = tmp_path / "words.yaml"
    bad.write_text("marks: ','\nlanguages:\n  en:\n    frames:\n      domains: [any]\n      words: [with, on]\n")
    monkeypatch.setattr(rec, "DATA", bad)
    for f in (rec._data, rec._vocab, rec._holds, rec._exceptions):
        f.cache_clear()
    try:
        with pytest.raises(ValueError, match="not a word"):
            recognised("Patients with asthma", ["asthma"])
    finally:
        monkeypatch.undo()
        for f in (rec._data, rec._vocab, rec._holds, rec._exceptions):
            f.cache_clear()


def _post(text: str, kind: str = "inclusion", concept: str = "kidney transplant") -> c.CriterionIR:
    crit = {"kind": kind, "class": "structured", "text": text,
            "logic": {"domain": "procedure", "concept": concept, "quantifier": "any"},
            "concept_candidates": [{"domain": "procedure", "name": concept}]}  # fmt: skip
    out = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0")
    assert len(out.criteria) == 1
    return out.criteria[0]


def test_a_line_not_recognised_is_held_as_a_cued_one_is_and_says_why() -> None:
    held = _post("Candidate for kidney transplant")  # the cue rules alone let it run (71e85bbc)
    assert held.class_ == "human" and held.human_question
    assert isinstance(held.logic, Atom) and held.logic.valueset == "NONE"
    assert {FLAG, UNREAD} <= set(held.flags or [])
    cued = _post("No prior kidney transplant")
    assert FLAG in (cued.flags or []) and UNREAD not in (cued.flags or [])
    ran = _post("Kidney transplant recipient")
    assert ran.class_ == "structured" and FLAG not in (ran.flags or [])


def test_an_exclusion_is_never_read_for_recognition() -> None:
    assert _post("Candidate for kidney transplant", kind="exclusion").class_ == "structured"


def test_an_approved_line_reused_is_held_when_not_recognised() -> None:
    """An incremental compile reuses an approved criterion without ``postprocess``: the same rule holds it there."""
    vs = {"VS_KTX": {"title": "kidney transplant", "compose": {"include": []}}}

    def crit(text: str) -> c.CriterionIR:
        return c.CriterionIR.model_validate({"id": "T-INC-01", "ruleset": "T", "kind": "inclusion",
                                             "class": "structured", "text": text, "review": {"status": "approved"},
                                             "logic": {"domain": "procedure", "valueset": "VS_KTX",
                                                       "quantifier": "any"}})  # fmt: skip

    held, why = pp.hold_reused_negated(crit("Candidate for kidney transplant"), vs)
    assert held.class_ == "human" and UNREAD in (held.flags or []) and FLAG in (held.flags or [])
    assert why and "not recognised" in why
    same, none = pp.hold_reused_negated(crit("Kidney transplant recipient"), vs)
    assert same.class_ == "structured" and none is None
