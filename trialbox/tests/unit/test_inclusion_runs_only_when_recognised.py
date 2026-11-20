"""Card 10A-1d (D-1248): an inclusion runs as presence only when its line is positively recognised.

The cue reading of cards 10A-1 to 10A-1c held a line only when it found a negation cue, so every shape nobody listed
ran as "the patient has it": a drug stopped or refused, a plan, another person's condition, remission, a heading, a
checkbox ticked "No". The owner ruled the default round on 2026-11-19: what is not clearly present does not count as
met. Now a structured or mixed inclusion that asks the presence of a concept runs only when every clause of its line
is read (``services/criteria_compiler/ir_extract/recognition.py`` with the data in ``recognised_assertions.yaml``):
what governs the concept's name must be a listed frame, and an unlisted word is read only as a content word where a
content word cannot change whether the concept is present. Each rule below has a line it holds and a near line it
lets run; removing the rule (or the words it relies on) fails one of them.

Two synthetic sets, no patients. ``card_10a1d_development.tsv``: 696 lines in English, Japanese and Chinese, the
first 471 labelled before the experiment's rule was written. ``card_10a1d_plain.tsv``: 360 ordinary plain inclusion
lines (120 per language) written by another hand than the rule's, never tuned to a rule, to measure what the flip
costs: how many ordinary lines are held.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.ir_extract import recognition as rec
from criteria_compiler.ir_extract.recognition import recognised, unrecognised_presence
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import Atom, BoolExpr, LlmExtractOutput

from tools.negated_inclusion_score import compile_rows, read_rows, score

FLAG, UNREAD = "negated_inclusion_presence", "presence_not_recognised"
DEV = Path(__file__).resolve().parents[1] / "fixtures/negated_inclusion/card_10a1d_development.tsv"
ROWS = read_rows(DEV)
# the must-run lines of the development set held all the same, each for a reason D-1248 names: the cue reading (the
# second net) holds a second sentence with a negation and a need; the default holds a second clause that is itself a
# negation ("but no history of stroke"), a method or an indication the line names with no listed frame, and a score
# written without a mark between it and the name
CUED = {
    "Type 2 diabetes. Not pregnant.",
    "2型糖尿病の患者。妊娠していない。",
    "第二型糖尿病。未懷孕。",
    "需要透析之慢性腎臟病",
}
HELD_ALL_THE_SAME = {
    *CUED,
    "Multiple sclerosis; no relapse in the past 30 days",
    "Hypertension, but no history of stroke",
    "高血圧を有するが、脳卒中の既往はない。",
    "高血壓，但無中風病史",
    "Severe aortic stenosis by echocardiography",
    "Underwent surgery for colorectal cancer",
    "統合失調症でPANSS総得点70点以上",
}
PLAIN = read_rows(DEV.with_name("card_10a1d_plain.tsv"))
PLAIN_HELD = {"en": [1, 15], "ja": [4, 18], "zh": [5, 27]}  # [by the cue reading, not recognised]
_HELD: list[list[bool]] = []


def _dev_held() -> list[bool]:
    if not _HELD:
        _HELD.append(score(ROWS))
    return _HELD[0]


def test_the_development_set_is_what_d1248_counts() -> None:
    assert len(ROWS) == 696
    assert sum(r["expect"] == "held" for r in ROWS) == 412
    assert {r["lang"] for r in ROWS} == {"en", "ja", "zh"}


def test_every_must_hold_line_of_the_development_set_is_held() -> None:
    """At 71e85bbc (the cue reading alone) 201 of the first 297 of these lines ran."""
    missed = [r["text"] for r, h in zip(ROWS, _dev_held(), strict=True) if r["expect"] == "held" and not h]
    assert missed == []


def test_every_must_run_line_of_the_development_set_runs_but_those_held_all_the_same() -> None:
    """The frames and qualifiers are pinned by the lines they let run: a word dropped from the data fails here."""
    held = {r["text"] for r, h in zip(ROWS, _dev_held(), strict=True) if r["expect"] == "runs" and h}
    assert held == HELD_ALL_THE_SAME


def _rows(*lines: tuple[str, str, str]) -> list[dict[str, Any]]:
    return [{"text": t, "concept": k, "domain": d, "expect": "runs", "synonyms": [], "others": []} for t, k, d in lines]


def test_the_plain_set_counts_what_the_flip_costs() -> None:
    """How many ordinary plain inclusion lines are held: the cost of the flip, which the owner sees. 360 lines, 120 per
    language, written by another hand than the rule's. At 65f0753c (the cue reading alone) 12 were held (en 1, ja 5,
    zh 6); with the experiment's closed word list as merged, 237 (en 75, ja 78, zh 84). These counts are counts of
    these lines: they were read while the rule was built, so they are not a measure on unseen lines."""
    assert len(PLAIN) == 360 and all(r["expect"] == "runs" for r in PLAIN)
    held: dict[str, list[int]] = {"en": [0, 0], "ja": [0, 0], "zh": [0, 0]}
    for r, (net, _) in zip(PLAIN, compile_rows(PLAIN), strict=True):
        if net is not None:
            held[r["lang"]][net == "unrecognised"] += 1
    assert {k: len([r for r in PLAIN if r["lang"] == k]) for k in held} == {"en": 120, "ja": 120, "zh": 120}
    assert held == PLAIN_HELD  # [by the cue reading, not recognised]


LINE = ("Diagnosis of asthma for at least 12 months", "asthma", "condition")


@pytest.mark.parametrize(
    "text",
    [
        "Zorblat of asthma for at least 12 months",  # what governs the name is not a listed frame
        "Diagnosis of asthma zorblat for at least 12 months",  # the word right after the name
        "Diagnosis of asthma in zorblat for at least 12 months",  # what a preposition after the name takes
        "Diagnosis of pre-asthma for at least 12 months",  # a word joined to the name by a hyphen
        "Diagnosis of asthma for at least 12 months if zorblat",  # a closed-class word is read only where listed
        "Diagnosis of asthma for at least 12 months, zorblated",  # a verb form is read only when listed
        "Diagnosis of asthma for at least 12 months, zorblating daily",
        "Diagnosis of asthma for at least 12 months; zorblat",  # a clause that names no coded concept
        "Diagnosis of asthma for at least 12 months. Zorblat.",
        "Diagnosis of asthma, zorblat or wheeze, for at least 12 months",  # an arm of an alternative
        "Diagnosis of asthma for at least 12 months in the stepfather",  # a class that is never read unlisted
        "Diagnosis of asthma for at least 12 months, awaited",
        "Diagnosis of asthma for at least 12 months (FH)",
        "Diagnosis of asthma for at least 12 months: -",  # a mark that stands alone
        "Diagnosis of asthma for at least 12 months ( )",
    ],
)
def test_an_unlisted_word_is_never_read_where_it_could_change_the_meaning(text: str) -> None:
    """The line runs as written; with one unlisted word where a word can change whether the concept is present (or a
    word of a class that says it is not), it is held."""
    plain, changed = _rows(LINE, (text, "asthma", "condition"))
    assert score([plain, changed]) == [False, True], text


@pytest.mark.parametrize(
    "text",
    [
        "Diagnosis of zorblatic asthma for at least 12 months",  # an adjective before the name
        "Diagnosis of asthma for at least 12 months with zorblat wheeze",  # content words in the rest of the line
        "Diagnosis of asthma for at least 12 months, confirmed by zorblat spirometry",
        "Diagnosis of asthma (GINA zorblat 4) for at least 12 months with a ZORB-7 score of 20 or more",
    ],
)
def test_an_unlisted_content_word_is_read_where_it_cannot_change_the_meaning(text: str) -> None:
    """A closed list of every word held 88 of 100 ordinary lines. An unlisted content word (never a closed-class
    word, never a verb form) is read in the rest of the line, a bounded number of them."""
    assert score(_rows((text, "asthma", "condition"))) == [False], text
    crowded = "Diagnosis of asthma with " + " ".join(f"zorb{chr(97 + k)}" for k in range(13)) + " wheeze"
    assert score(_rows((crowded, "asthma", "condition"))) == [True]  # more than twelve in one clause


@pytest.mark.parametrize(
    ("held", "runs", "concept"),
    [
        # Japanese: nothing unlisted right after the name until a listed frame closes it; hiragana with an ending
        # that denies, doubts or conditions is never read; the owner before の is read only when listed
        ("喘息に対するゾルブラ接種", "喘息と診断されたゾルブラ外来の患者", "喘息"),
        ("喘息と診断されたらしい患者", "喘息と診断されている患者", "喘息"),
        ("ゾルブラの喘息", "重症の喘息", "喘息"),
        ("偽喘息の患者", "重症喘息の患者", "喘息"),
        # Chinese: the same after the name; before it only what 之 / 的 or a listed frame joins to it
        ("氣喘之佐布拉門診", "診斷為氣喘之患者，佐布拉門診", "氣喘"),
        ("佐布拉氣喘", "重度氣喘", "氣喘"),
        ("婉謝接受氣喘治療", "正在接受氣喘治療", "氣喘"),
        ("佐布拉之氣喘", "重度之氣喘", "氣喘"),
    ],
)
def test_japanese_and_chinese_read_unlisted_words_by_the_same_rule(held: str, runs: str, concept: str) -> None:
    assert score(_rows((held, concept, "condition"), (runs, concept, "condition"))) == [True, False], (held, runs)


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
        (("Diabetes (NO)", "diabetes", "condition"), ("Colorectal cancer (CRC)", "colorectal cancer", "condition")),
        # an abbreviation the line does not define as the concept's: its letters do not follow the name's
        (
            ("Colorectal cancer (FH)", "colorectal cancer", "condition"),
            ("Type 2 diabetes mellitus (T2DM)", "type 2 diabetes mellitus", "condition"),
        ),
        # a numbered heading, and a numbered list item
        (("5.2 Hepatitis B", "hepatitis B", "condition"), ("1. Hepatitis B", "hepatitis B", "condition")),
        # a blank, a dash or ± is not a positive mark
        (("Hypertension (±)", "hypertension", "condition"), ("Hypertension (+)", "hypertension", "condition")),
        (("Hypertension [ ]", "hypertension", "condition"), ("Hypertension [x]", "hypertension", "condition")),
        # a test named as a test, and as what confirmed the concept
        (
            ("Hepatitis B serology at screening", "hepatitis B", "condition"),
            ("Hepatitis B confirmed by serology", "hepatitis B", "condition"),
        ),
        # "ago" on a diagnosis date is not an ending
        (
            ("Prednisone, last dose 1 year ago", "prednisone", "medication"),
            ("Hypertension diagnosed at least 1 year ago", "hypertension", "condition"),
        ),
        # a measure by its shape, after the concept; never a risk
        (
            ("Heart failure risk score ≥ 3", "heart failure", "condition"),
            ("Schizophrenia with PANSS total score ≥ 70", "schizophrenia", "condition"),
        ),
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
    # every clause counts: an ending said of another concept holds the line too (the logic would have to say it)
    assert not recognised("Taking rituximab; last dose of methotrexate 2 years ago", ["rituximab"],
                          ["methotrexate"], "medication")  # fmt: skip


_SPLIT_EN = re.compile(r"[,;:.()\[\]{}\"'/?!]+")
_STOP = set(
    [
        "for",
        "against",
        "of",
        "to",
        "in",
        "on",
        "with",
        "and",
        "or",
        "nor",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "at",
        "by",
        "from",
        "after",
        "before",
        "but",
        "not",
        "no",
        "without",
        "who",
        "which",
        "that",
        "as",
        "per",
        "if",
        "unless",
        "every",
        "each",
        "any",
        "all",
        "this",
        "its",
        "it",
        "has",
        "have",
        "had",
        "must",
        "should",
        "will",
        "may",
        "can",
    ]
)
_SPLIT_CJK = re.compile(
    r"[、。，,；;：:（）()\[\]【】「」\s]+|の|を|に|が|は|で|と|へ|や|から|まで|之|的|及|或|和|與|与|且|為|为|於|于|對|对|針對|"
    r"针对|並|并|但|曾|已|未|無|无|不|ない|なし|あり|ある|する|した|して|された|されて|いる"
)


def _other_phrases(text: str, concept: str) -> list[str]:
    """The line's other noun phrases, found mechanically: runs of words between function words and marks."""
    u = unicodedata.normalize("NFKC", text)
    if re.search(r"[぀-ヿ㐀-鿿]", u):
        parts = _SPLIT_CJK.split(u.replace(unicodedata.normalize("NFKC", concept), "|"))
        out = [x.strip() for p in parts for x in p.split("|") if len(x.strip()) >= 2]
    else:
        out = []
        for part in _SPLIT_EN.split(re.sub(re.escape(concept), "|", u, flags=re.I)):
            for chunk in part.split("|"):
                run: list[str] = []
                for w in [*chunk.split(), "the"]:
                    if w.lower() in _STOP or re.fullmatch(r"[\d.\-–%≥≤<>=+±]+", w):
                        out += [" ".join(run), *(run if len(run) > 1 else [])] if run else []
                        run = []
                    else:
                        run.append(w)
    return list(dict.fromkeys(x for x in out if x and x.lower() != concept.lower()))


def test_a_held_line_stays_held_whatever_else_in_it_is_named_as_a_concept() -> None:
    """Every must-hold line of the development set, with each other noun phrase in it (and all of them) named as
    another concept, and then coded as an atom of an "and" logic beside the concept: none runs. Naming "spouse",
    "remission" or "pending review" as a concept never lets a line run."""
    variants, crits = [], []
    for r in (r for r in ROWS if r["expect"] == "held"):
        ps = _other_phrases(r["text"], r["concept"])
        dom = r.get("domain") or "condition"
        for sub in [[p] for p in ps] + ([ps] if len(ps) > 1 else []):
            variants.append({**r, "others": list(dict.fromkeys([*r["others"], *sub]))})
            names = [r["concept"], *sub]
            crits.append({"kind": "inclusion", "class": "structured", "text": r["text"],
                          "logic": {"op": "and", "args": [{"domain": dom, "concept": n} for n in names]},
                          "concept_candidates": [{"domain": dom, "name": n} for n in names]})  # fmt: skip
    named = [h for k in range(0, len(variants), 900) for h in score(variants[k : k + 900])]
    assert [v["text"] for v, h in zip(variants, named, strict=True) if not h] == []
    coded = []
    for k in range(0, len(crits), 900):
        out = pp.postprocess(
            "SWEEP", LlmExtractOutput.model_validate({"criteria": crits[k : k + 900]}), Terminology(), "1.0.0"
        )
        coded += [FLAG in (c.flags or []) for c in out.criteria]
    assert [c["text"] for c, h in zip(crits, coded, strict=True) if not h] == []


def _and(text: str, coded: str, other: str, dom: str = "condition", odom: str = "condition") -> c.CriterionIR:
    crit = {"kind": "inclusion", "class": "structured", "text": text,
            "logic": {"op": "and", "args": [{"domain": dom, "concept": coded}, {"domain": odom, "concept": other}]},
            "concept_candidates": [{"domain": dom, "name": coded}, {"domain": odom, "name": other}]}  # fmt: skip
    (out,) = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0").criteria
    return out


def test_another_concept_counts_when_the_logic_codes_it() -> None:
    """A second concept the logic codes may stand in the line, joined by a link word; one it does not code is words.
    Each atom the logic asks the presence of is read in its turn, so each must be a plain fact of the patient."""
    for text, coded, other in [
        ("HIV infection on stable antiretroviral therapy", "HIV infection", "antiretroviral therapy"),
        ("Type 2 diabetes and hypertension", "type 2 diabetes", "hypertension"),
        ("2型糖尿病及び高血圧", "2型糖尿病", "高血圧"),
        ("第二型糖尿病及高血壓", "第二型糖尿病", "高血壓"),
    ]:
        assert _and(text, coded, other).class_ == "structured", text
    # one the logic does not code is read as the words it is: ordinary content words may stand in the rest of the
    # line (D-1248 as adopted), a word that says the concept is someone else's never
    rows = _rows(("HIV infection on stable antiretroviral therapy", "HIV infection", "condition"),
                 ("HIV infection in the spouse on antiretroviral therapy", "HIV infection", "condition"))  # fmt: skip
    assert score(rows) == [False, True]


def test_the_concept_as_the_object_of_another_is_held() -> None:
    """When the coded concept is what another named concept is for, against or of, or belongs to it, the line is
    held for the concept, even with both coded."""
    for text, coded, other in [
        ("Vaccination for hepatitis B", "hepatitis B", "vaccination"),
        ("Colonoscopy for colorectal cancer", "colorectal cancer", "colonoscopy"),
        ("Underwent surgery for colorectal cancer", "colorectal cancer", "surgery"),
        ("B型肝炎に対するワクチン接種", "B型肝炎", "ワクチン接種"),
        ("針對B型肝炎之疫苗接種", "B型肝炎", "疫苗接種"),
        ("Spouse with COVID-19", "COVID-19", "spouse"),
        ("配偶者がHIV感染症", "HIV感染症", "配偶者"),
    ]:
        assert _and(text, coded, other).class_ == "human", text


def test_a_code_counts_only_when_it_is_one_of_the_concepts_own() -> None:
    assert recognised("Colorectal cancer (C18.9)", ["colorectal cancer"], codes=["C18.9"])
    assert not recognised("Colorectal cancer (Z80.0)", ["colorectal cancer"], codes=["C18.9"])
    assert not recognised("Colorectal cancer (C18.9)", ["colorectal cancer"])


def test_an_alternative_runs_only_when_the_logic_carries_it() -> None:
    """How it is told: the other concept is an arm of an "or" above this atom in the criterion's own logic."""
    af = Atom(domain="condition", valueset="VS_AF", quantifier="any")
    afl = Atom(domain="condition", valueset="VS_AFL", quantifier="any")
    names = {"VS_AF": ["atrial fibrillation"], "VS_AFL": ["atrial flutter"]}
    line = "Either atrial fibrillation or atrial flutter"
    assert not unrecognised_presence(line, BoolExpr(op="or", args=[af, afl]), lambda vs: names.get(vs, []))
    assert unrecognised_presence(line, BoolExpr(op="and", args=[af, afl]), lambda vs: names.get(vs, []))
    assert unrecognised_presence(line, af, lambda vs: names.get(vs, []), ["atrial flutter"])
    # an "or" between two tests that confirmed the concept is not an alternative of the concept
    assert recognised("Chronic subdural hematoma verified on cranial CT or MRI", ["chronic subdural hematoma"],
                      ["CT", "MRI"])  # fmt: skip


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
    rec.clear_caches()
    try:
        with pytest.raises(ValueError, match="not a word"):
            recognised("Patients with asthma", ["asthma"])
    finally:
        monkeypatch.undo()
        rec.clear_caches()


def _post(text: str, kind: str = "inclusion", concept: str = "kidney transplant") -> c.CriterionIR:
    crit = {"kind": kind, "class": "structured", "text": text,
            "logic": {"domain": "procedure", "concept": concept, "quantifier": "any"},
            "concept_candidates": [{"domain": "procedure", "name": concept}]}  # fmt: skip
    out = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0")
    assert len(out.criteria) == 1
    return out.criteria[0]


def test_a_line_not_recognised_is_held_as_a_cued_one_is_and_says_why() -> None:
    held = _post("Kidney transplant counselling")  # the cue rules alone let it run
    assert held.class_ == "human" and held.human_question
    assert isinstance(held.logic, Atom) and held.logic.valueset == "NONE"
    assert {FLAG, UNREAD} <= set(held.flags or [])
    cued = _post("No prior kidney transplant")
    assert FLAG in (cued.flags or []) and UNREAD not in (cued.flags or [])
    ran = _post("Kidney transplant recipient")
    assert ran.class_ == "structured" and FLAG not in (ran.flags or [])


def test_an_exclusion_is_never_read_for_recognition() -> None:
    assert _post("Kidney transplant counselling", kind="exclusion").class_ == "structured"


def test_an_approved_line_reused_is_held_when_not_recognised() -> None:
    """An incremental compile reuses an approved criterion without ``postprocess``: the same rule holds it there."""
    vs = {"VS_KTX": {"title": "kidney transplant", "compose": {"include": []}}}

    def crit(text: str) -> c.CriterionIR:
        return c.CriterionIR.model_validate({"id": "T-INC-01", "ruleset": "T", "kind": "inclusion",
                                             "class": "structured", "text": text, "review": {"status": "approved"},
                                             "logic": {"domain": "procedure", "valueset": "VS_KTX",
                                                       "quantifier": "any"}})  # fmt: skip

    held, why = pp.hold_reused_negated(crit("Kidney transplant counselling"), vs)
    assert held.class_ == "human" and UNREAD in (held.flags or []) and FLAG in (held.flags or [])
    assert why and "not recognised" in why
    same, none = pp.hold_reused_negated(crit("Kidney transplant recipient"), vs)
    assert same.class_ == "structured" and none is None
