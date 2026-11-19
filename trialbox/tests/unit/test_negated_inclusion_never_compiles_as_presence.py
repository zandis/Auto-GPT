"""Card 10A-1 (review 15, finding 2.3.1; plan 10 Track A): a negated inclusion never compiles as its opposite.

The P2b launch stored two coded inclusions whose line negates what their logic asks: ``SM3NCT00002897-INC-03``
"PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy" compiled to ``any of VS_CHEMOTHERAPY``
(structured), and ``SM3NCT00256529-INC-03`` "No significant cardiopulmonary disease, or other contraindication to
EGD" the same way (mixed). An inclusion is met when its logic is true, so once the code list loads the first would
exclude every patient who never had chemotherapy, the eligible ones. The compiler never compared a coded
inclusion's logic with its line. Now an inclusion whose logic asks the presence of a concept that a negation in its
line governs (``negation_scope``) is held for a person (``negated_inclusion_presence``): never run, it answers
unknown, and unknown never excludes. The same holds for an approved inclusion an incremental compile reuses.

The cases are the committed synthetic table ``tests/fixtures/negated_inclusion/lines.json`` (three languages; the
review lines, this card's own, and lines written after the rule was tuned, ``source: fresh``). Public protocol text
and synthetic lines; no patients.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import tb_contracts as c
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.semantics import FILTERED, JUDGED
from criteria_compiler.terminology.mapper import Terminology
from doc_parser.parser import parse
from tb_contracts import Atom, LlmExtractOutput

from tests.unit.test_compiler_service import PDF, _approve, _compile, _decisions, env  # noqa: F401 (env: a fixture)

FLAG = "negated_inclusion_presence"
FIX = Path(__file__).resolve().parents[1] / "fixtures/negated_inclusion"
ROWS: list[dict[str, Any]] = json.loads((FIX / "lines.json").read_text(encoding="utf-8"))["rows"]
# lines lane J's reviewer wrote before reading ROWS (unseen when the rule was designed): kept apart, scored apart
UNSEEN: list[dict[str, Any]] = json.loads((FIX / "unseen_at_design.json").read_text(encoding="utf-8"))["rows"]
# card 10A-1b's lines, written before its rule changed (ellipsis, lists, either clause order): kept apart, scored apart
CARD: list[dict[str, Any]] = json.loads((FIX / "card_10a1b.json").read_text(encoding="utf-8"))["rows"]
# the lane J coordinator's review of card 10A-1b: lines that ran (new cue words, synonyms, a list before the cue)
REVIEW: list[dict[str, Any]] = json.loads((FIX / "review_10a1b.json").read_text(encoding="utf-8"))["rows"]
# card 10A-1c's 241 lines, written before its rules changed, each with the shape it tests (``hold_class``)
BEFORE: list[dict[str, Any]] = json.loads((FIX / "card_10a1c_before.json").read_text(encoding="utf-8"))["rows"]
# card 10A-1c's second set, written after its code was final and never used to tune it
AFTER: list[dict[str, Any]] = json.loads((FIX / "card_10a1c_after.json").read_text(encoding="utf-8"))["rows"]
# its third set, written after the lane J lead's last rulings were coded (chart marks, prefixes, the 不 descriptors)
THIRD: list[dict[str, Any]] = json.loads((FIX / "card_10a1c_third.json").read_text(encoding="utf-8"))["rows"]
# an independent tester's lines that ran at 227466c3 (now seen: a regression fixture), and this card's nearest lines
INDEP1: list[dict[str, Any]] = json.loads((FIX / "independent_set_1.json").read_text(encoding="utf-8"))["rows"]
CHEMO = {"domain": "procedure", "quantifier": "any", "concept": "chemotherapy"}  # VS_CHEMOTHERAPY once compiled
CHEMO_CAND = [{"domain": "procedure", "name": "chemotherapy", "synonyms": ["化学療法", "化學治療"]}]
_TERM: list[Terminology] = []


def _term() -> Terminology:
    """One empty terminology for the module (each takes about a second to build; the table runs hundreds of lines)."""
    if not _TERM:
        _TERM.append(Terminology())
    return _TERM[0]


def _logic(row: dict[str, Any]) -> dict[str, Any]:
    atom = {"domain": row["domain"], "concept": row["concept"]}
    if row["logic"] == "value":  # a bound read off the latest result ("no greater than 1.5 mg/dL")
        return {**atom, "quantifier": "latest", "value": {"op": "<=", "num": 2}}
    return {**atom, "quantifier": "any"}


def _cand(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The coded concept and the line's other candidates (``others``: card 10A-1b's lines), as the extractor emits."""
    return [{"domain": row["domain"], "name": row["concept"], "synonyms": row["synonyms"]}] + [
        {"domain": row["domain"], "name": x, "synonyms": []} for x in row.get("others", [])
    ]


def _post(crits: list[dict[str, Any]]) -> Any:
    return pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": crits}), _term(), "1.0.0")


def _one(text: str, logic: dict[str, Any], kind: str = "inclusion", cls: str = "structured",
         concepts: list[dict[str, Any]] | None = None, question: str | None = None) -> Any:  # fmt: skip
    crit: dict[str, Any] = {"kind": kind, "class": cls, "text": text, "logic": logic,
                            "concept_candidates": concepts if concepts is not None else CHEMO_CAND}  # fmt: skip
    if question:
        crit["note_question"] = question
    (out,) = _post([crit]).criteria
    return out


def _held(x: Any) -> None:
    assert x.class_ == "human" and x.human_question, (x.class_, x.text)
    assert FLAG in (x.flags or []), x.flags
    assert getattr(x.logic, "valueset", None) == "NONE"  # the presence logic is never run


def test_the_two_p2b_lines_are_held() -> None:
    _held(_one("PRIOR CONCURRENT THERAPY: No prior chemotherapy or radiotherapy", CHEMO))
    _held(_one("No significant cardiopulmonary disease, or other contraindication to EGD",
               {"domain": "condition", "quantifier": "any", "concept": "cardiopulmonary disease"},
               cls="mixed", concepts=[{"domain": "condition", "name": "cardiopulmonary disease"}],
               question="Does the patient have significant cardiopulmonary disease?"))  # fmt: skip


ALL = [*ROWS, *UNSEEN, *CARD, *REVIEW, *BEFORE, *AFTER, *THIRD, *INDEP1]


@pytest.mark.parametrize("cls", ["structured", "mixed"])
@pytest.mark.parametrize("row", ALL, ids=[f"{r['source']}-{r['lang']}-{i}" for i, r in enumerate(ALL)])
def test_property_each_line_of_the_tables_is_held_or_runs_as_expected(row: dict[str, Any], cls: str) -> None:
    """A negated line is always held (never a miss). A line that should run runs, unless the table marks it
    ``over_held``: the fail-safe holds it today, which costs a person's look and is counted below."""
    q = "Does the patient meet it?" if cls == "mixed" else None
    x = _one(row["text"], _logic(row), cls=cls, concepts=_cand(row), question=q)
    if row["expect"] == "held" or row.get("over_held"):
        _held(x)
    else:
        assert FLAG not in (x.flags or []), (row["text"], x.class_, x.flags)


def _score(rows: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    out = _post([{"kind": "inclusion", "class": "structured", "text": r["text"], "logic": _logic(r),
                  "concept_candidates": _cand(r)} for r in rows]).criteria  # fmt: skip
    neg = [x.class_ == "human" for r, x in zip(rows, out, strict=True) if r["expect"] == "held"]
    run = [x.class_ == "human" for r, x in zip(rows, out, strict=True) if r["expect"] == "runs"]
    return sum(neg), len(neg), sum(run), len(run)


def test_the_counts_the_pull_request_reports() -> None:
    """Every negated line of the four tables held. Card 10A-1b held 12 of its own 40 negated lines that ran before it
    (a cue over a list) and the coordinator's 34 that ran (cue words such as "forbidden", 不可, 禁止, 不允許, "other
    than X"; a synonym of the coded concept). The lines that should run and are held: card 10A-1's table 8 of 69, the
    lines unseen at design 20 of 23 (the same as before card 10A-1b; 19 since card 10A-1c's R8), card 10A-1b's own 17 of 40 (18 before), the
    coordinator's 0 of 8. Card 10A-1c: these counts are about these lines only, never about the reader (a reader
    that looks for cues misses shapes nobody listed). Its 241 lines: 4 of 121 negated lines ran on master, 82 of 120
    held that should run (109 on master). Its second and third sets: 7 and 26 of 63 ran on master; 25 and 12 of 63
    held that should run (48 and 30 on master). Independent set 1, the tester's lines that ran at 227466c3, now
    seen. "No more than 2 prior lines of chemotherapy" is a must-hold line since card 10A-1c (zero meets it)."""
    assert _score(ROWS) == (117, 117, 8, 68)
    assert _score(UNSEEN) == (21, 21, 19, 23)
    assert _score(CARD) == (40, 40, 17, 40)
    assert _score(REVIEW) == (36, 36, 0, 8)
    assert _score(BEFORE) == (121, 121, 82, 120)
    assert _score(AFTER) == (63, 63, 25, 63)
    assert _score(THIRD) == (63, 63, 12, 63)
    assert _score(INDEP1) == (73, 73, 0, 26)
    assert {r["lang"] for r in ALL} == {"en", "ja", "zh"}


@pytest.mark.parametrize(
    "text",
    ["chemotherapy has not responded to steroids and " * 900, "化学療法後に増悪が認められない、" * 2500,
     "化學治療後未見惡化，" * 4000, "Prior chemotherapy is allowed. " * 1300, "no more than 2 " * 2700],
    ids=["en", "ja", "zh", "plain", "bounds"],
)  # fmt: skip
def test_a_long_line_takes_linear_time(text: str) -> None:
    """A concept or a cue repeated in one 40 kB line: every look is a window of 300 characters, never the line."""
    import time

    from criteria_compiler.ir_extract.negation_scope import negated_presence

    gout = Atom(domain="procedure", valueset="VS_CHEMOTHERAPY", quantifier="any")
    t0 = time.perf_counter()
    negated_presence(text, gout, lambda vs: ["化学療法", "化學治療"])
    assert time.perf_counter() - t0 < 3.0  # 0.4 s or less here; quadratic was 6 s


NEGATED = [r for r in ROWS if r["expect"] == "held" and r["logic"] == "presence"]
AGE18 = {"domain": "demographic", "age": {"min": 18}}
PRESENCE: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
    lambda a: {"op": "and", "args": [AGE18, a]},
    lambda a: {"op": "not", "args": [{"op": "not", "args": [a]}]},
    lambda a: {**a, "quantifier": "all"},
]
ABSENCE: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
    lambda a: {**a, "quantifier": "none"},
    lambda a: {"op": "not", "args": [a]},
    lambda a: {"op": "and", "args": [AGE18, {**a, "quantifier": "none"}]},
]


def _shaped(shape: Callable[[dict[str, Any]], dict[str, Any]]) -> list[Any]:
    crits = [{"kind": "inclusion", "class": "structured", "text": r["text"], "logic": shape(_logic(r)),
              "concept_candidates": _cand(r)} for r in NEGATED]  # fmt: skip
    return list(_post(crits).criteria)


@pytest.mark.parametrize("shape", range(len(PRESENCE)))
def test_property_presence_inside_other_logic_is_held(shape: int) -> None:
    out = _shaped(PRESENCE[shape])
    assert not [x.text for x in out if x.class_ != "human" or FLAG not in (x.flags or [])]


@pytest.mark.parametrize("shape", range(len(ABSENCE)))
def test_property_a_negated_line_already_coded_negative_runs(shape: int) -> None:
    assert not [x.text for x in _shaped(ABSENCE[shape]) if FLAG in (x.flags or [])]


def test_exclusions_are_byte_identical_with_the_rule_on_and_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Card 10A-1b changes only which inclusions are held: every line of the four tables compiled as an exclusion is
    the same, byte for byte, with the rule as it is and with it off."""
    rows = [*ROWS, *UNSEEN, *CARD, *REVIEW, *BEFORE, *AFTER, *THIRD, *INDEP1]
    crits = [{"kind": "exclusion", "class": "structured", "text": r["text"], "logic": _logic(r),
              "concept_candidates": _cand(r)} for r in rows]  # fmt: skip

    def dumped() -> list[str]:
        return [c.dump_json(x) for x in _post(crits).criteria]

    on = dumped()
    monkeypatch.setattr("criteria_compiler.ir_extract.postprocess.negated_presence", lambda *a, **kw: False)
    assert dumped() == on


def test_a_reused_approved_line_reads_the_rulesets_concepts() -> None:
    """Card 10A-1b: an approved ruleset keeps no concept candidates, but each ValueSet's title is the name of one.
    The reused line reads them as its other concepts: a cue over one of them alone is explained, a cue over a list
    with this concept in it is not."""
    t2dm = {"title": "type 2 diabetes mellitus", "compose": {"include": []}}
    keto = {"title": "ketoacidosis", "compose": {"include": []}}
    chemo = {"title": "chemotherapy", "compose": {"include": []}}
    radio = {"title": "radiotherapy", "compose": {"include": []}}

    def crit(text: str, vs: str) -> Any:
        return c.CriterionIR.model_validate({"id": "T-INC-01", "ruleset": "T", "kind": "inclusion",
                                             "class": "structured", "text": text, "review": {"status": "approved"},
                                             "logic": {"domain": "condition", "valueset": vs, "quantifier": "any"}})  # fmt: skip

    line = crit("Type 2 diabetes mellitus without ketoacidosis", "VS_T2DM")
    # card 10A-1c (R8): "without" takes only the noun after it, so the line runs whether the ketoacidosis is known
    assert not pp.approved_negated(line, {"VS_T2DM": t2dm})
    assert not pp.approved_negated(line, {"VS_T2DM": t2dm, "VS_KETO": keto})
    # the reused path still holds what R8 does not release: a cue not next to the concept, and the object of "without"
    apart = crit("Type 2 diabetes mellitus, no ketoacidosis", "VS_T2DM")
    assert pp.approved_negated(apart, {"VS_T2DM": t2dm})
    assert pp.approved_negated(
        crit("Type 2 diabetes mellitus without ketoacidosis", "VS_KETO"), {"VS_T2DM": t2dm, "VS_KETO": keto}
    )
    listed = crit("No prior chemotherapy or radiotherapy", "VS_RADIO")
    assert pp.approved_negated(listed, {"VS_RADIO": radio, "VS_CHEMO": chemo})


# Card 10A-1b: each rule that lets a cue go, with lines it must let run (removing the rule fails them) and the
# near-miss shapes it must hold in en, ja and zh-TW (a rule that releases too much fails them): cue + modifier +
# concept; cue + modifier + list; a list with a modifier on a later item; the 之 / 的 / の and "of" / "with" joins.
CH = ["chemotherapy", "化学療法", "化學治療"]
HT = ["hypertension", "高血圧", "高血壓"]
ST = ["stroke", "脳卒中", "中風"]
LC = ["lung cancer", "肺癌"]
SU = ["surgery", "手術"]
HB = ["chronic hepatitis B", "慢性B型肝炎"]
AS = ["asthma", "喘息", "氣喘"]
IM = ["immunotherapy", "免疫療法", "免疫治療"]
RA = ["rheumatoid arthritis", "関節リウマチ", "類風濕性關節炎"]
MTX = ["methotrexate", "メトトレキサート", "甲氨蝶呤"]
Line = tuple[str, list[str], list[str]]  # text, the coded concept's names, the line's other candidates
RULES: dict[str, tuple[list[Line], list[Line]]] = {
    "R0 the concept is not named: any cue holds": (
        [],
        [
            ("No prior CTX or surgery.", CH, ["surgery"]),
            ("抗がん剤の使用歴はない。", CH, []),
            ("從未接受過化療的肺癌患者。", CH, []),
        ],
    ),
    "R1 a bound or a descriptor is not a cue": (
        [
            ("Non-small cell lung cancer, stage IV.", LC, []),
            ("非小細胞肺癌の患者。", LC, []),
            ("非小細胞肺癌患者。", LC, []),
            # card 10A-1c: the noun form of a negated prohibition, beside "not contraindicated" and 禁忌なし
            ("Rheumatoid arthritis with no contraindication to methotrexate.", RA, []),
            ("関節リウマチで、メトトレキサートに禁忌がない。", RA, []),
            ("類風濕性關節炎，且無禁忌症。", RA, []),
            # card 10A-1c: words that only contain 不 (a bare 不 is a cue now)
            ("控制不良之第二型糖尿病。", ["第二型糖尿病"], []),
            ("心律不整患者。", ["心律不整"], []),
            ("心功能不全之患者。", ["心功能不全"], []),
            ("月經不規則之婦女。", ["月經不規則"], []),
            ("原因不明之發燒。", ["發燒"], []),
            ("不孕症患者。", ["不孕症"], []),
            # card 10A-1c: a negating prefix on another word, or a name that holds the prefix itself, runs
            ("Nonspecific interstitial pneumonia.", ["interstitial pneumonia"], []),
            ("Nonspecific interstitial pneumonia.", ["nonspecific interstitial pneumonia"], []),
            ("Asymptomatic gallstones.", ["asymptomatic gallstones"], []),
            ("Patients with a symptomatic hernia.", ["symptomatic hernia"], []),
            ("Typical pneumonia.", ["typical pneumonia"], []),
            ("Anemia.", ["anemia"], []),
            ("非常に重症の喘息。", AS, []),
            ("無症候性脳梗塞。", ["脳梗塞"], []),
            ("Anti-HBc positive.", ["HBc"], []),  # "anti-" names a thing that is present: not a negating prefix
            ("Aerobic exercise.", ["aerobic exercise"], []),
            ("HBs抗原(+)の患者。", ["HBs抗原"], []),
            ("Prior chemotherapy - cisplatin based.", CH, []),
            ("Chemotherapy: yes.", CH, []),
            ("ナイアシン投与中の脂質異常症。", ["脂質異常症"], []),
            # card 10A-1c: a coded name that holds a descriptor whole is found in the line
            ("非小細胞肺癌の患者。", ["非小細胞肺癌"], []),
        ],
        [
            ("No non-small cell lung cancer.", LC, []),
            ("No history of hypertension, non-small cell lung cancer, or stroke.", LC, []),
            ("非小細胞肺癌がない。", LC, []),
            ("無非小細胞肺癌。", LC, []),
            # card 10A-1c: a prohibition itself; a bare 不; a descriptor reaching into the coded name from before it
            ("Methotrexate is contraindicated.", MTX, []),
            ("メトトレキサートは禁忌。", MTX, []),
            ("禁用甲氨蝶呤。", MTX, []),
            ("不吸菸者之氣喘。", ["吸菸"], []),
            # card 10A-1c: each word that only contains 不, read as a verb or a prefix, is a cue (the lead's ruling)
            ("不足以接受化學治療。", CH, []),
            ("不良於接受手術。", SU, []),
            ("不全然接受化學治療。", CH, []),
            ("不明確是否接受過化學治療。", CH, []),
            ("氧氣治療不整天使用。", ["氧氣治療"], []),
            ("不規律使用胰島素。", ["胰島素"], []),
            ("不穩定使用胰島素。", ["胰島素"], []),
            ("不佳之化學治療。", CH, []),
            ("不適合手術。", SU, []),
            ("不明原因之發燒不得納入。", ["發燒"], []),
            ("非小細胞肺癌の患者。", ["小細胞肺癌"], []),
            ("Non-Hodgkin lymphoma.", ["Hodgkin lymphoma"], []),
            ("非何杰金淋巴瘤。", ["何杰金淋巴瘤"], []),
            # card 10A-1c: a coded name right after a negating prefix in the same word is not that concept
            ("Asymptomatic gallstones.", ["symptomatic gallstones"], []),
            ("Atypical pneumonia.", ["typical pneumonia"], []),
            ("Unresectable pancreatic cancer.", ["resectable pancreatic cancer"], []),
            ("Non smokers with asthma.", ["smoker"], []),
            ("Non small cell lung cancer.", ["small cell lung cancer"], []),
            ("Ｎｏｎ－ｓｍａｌｌ ｃｅｌｌ ｌｕｎｇ ｃａｎｃｅｒ.", ["small cell lung cancer"], []),
            ("非ＳＴ上昇型心筋梗塞。", ["ST上昇型心筋梗塞"], []),
            ("無症候性脳梗塞。", ["症候性脳梗塞"], []),
            ("無症候性脳梗塞。", ["症候"], []),
            ("Afebrile neutropenia.", ["febrile neutropenia"], []),
            ("Anaerobic infection.", ["aerobic infection"], []),
            ("不完全寛解の患者。", ["完全寛解"], []),
            ("不完全緩解之患者。", ["完全緩解"], []),
            ("未分化癌。", ["分化癌"], []),
            # card 10A-1c: a chart's "none" after a name or a label
            ("HBs抗原(−)の患者。", ["HBs抗原"], []),
            ("化学療法：－", CH, []),
            ("化學治療：(−)", CH, []),
            ("Chemotherapy: -", CH, []),
            ("Chemotherapy: neg", CH, []),
            ("Chemotherapy: N/A", CH, []),
            # card 10A-1c: なし in katakana, full width and half width
            ("化学療法歴：ナシ", CH, []),
            ("化学療法歴：ﾅｼ", CH, []),
        ],
    ),
    "R2 a word the cue negates, a link word, then the concept": (
        [
            ("No progression after chemotherapy.", CH, []),
            ("No response to chemotherapy.", CH, []),
            ("化学療法後に増悪が認められない。", CH, []),
        ],
        [
            ("No poorly controlled hypertension.", HT, []),
            ("No poorly controlled hypertension, diabetes, or stroke.", ST, []),
            ("No hypertension, poorly controlled diabetes, or stroke.", ST, []),
            ("No history of poorly controlled hypertension.", HT, []),
            ("No disease controlled with surgery or chemotherapy.", CH, []),
            ("コントロール不良の高血圧がない。", HT, []),
            ("高血圧、コントロール不良の糖尿病、脳卒中がないこと。", HT, []),
            ("無控制不良的高血壓。", HT, []),
            ("無控制不良之高血壓、糖尿病或中風。", ST, []),
            ("無高血壓、控制不良的糖尿病或中風。", ST, []),
        ],
    ),
    "R3 a verbal negator closing a modifier with 的 or 之": (
        [
            ("未經治療的晚期肺癌。", LC, []),
            ("未經治療之肺癌患者。", LC, []),
        ],
        [
            ("無未控制之高血壓、不穩定心絞痛或中風。", HT, []),
            ("無未控制之高血壓、不穩定心絞痛或中風。", ST, []),
            ("無控制不良的高血壓。", HT, []),
            ("未曾接受化學治療的患者。", CH, []),
            ("未經治療之高血壓、糖尿病或中風。", ST, []),
            ("No untreated hypertension.", HT, []),
            ("未治療の高血圧がない。", HT, []),
            # card 10A-1c: a modifier with an object of its own may be a possessive ("no family history of …"):
            # R3 now lets only "未(經)治療的 / 之" go
            ("未曾有心臟病之家族史。", ["家族史"], []),
            ("未曾發生化療之副作用。", ["副作用"], []),
            ("未曾出現腦轉移之症狀。", ["症狀"], []),
        ],
    ),
    "R4 another named concept the cue reaches instead": (
        [
            ("Hypertension; no prior chemotherapy.", HT, ["chemotherapy"]),
            ("化学療法歴はない。高血圧がある。", HT, ["化学療法"]),
            ("第二型糖尿病。無酮酸中毒。", ["type 2 diabetes", "第二型糖尿病"], ["酮酸中毒"]),
        ],
        [
            ("No smoking during chemotherapy.", CH, ["smoking"]),
            ("No uncontrolled hypertension, diabetes or stroke.", ST, ["hypertension"]),
            ("No prior surgery or chemotherapy.", CH, ["surgery"]),
            ("手術及び化学療法の治療歴がない。", SU, ["化学療法"]),
            ("高血圧、コントロール不良の糖尿病がないこと。", HT, ["糖尿病"]),
            ("未曾接受手術或化學治療。", CH, ["手術"]),
            ("無高血壓、控制不良的糖尿病或中風。", ST, ["高血壓", "糖尿病"]),
        ],
    ),
    "R5 the cue's own words say what it negates": (
        [
            ("Hypertension has not responded to treatment.", HT, []),
            ("化學治療後未見惡化。", CH, []),
        ],
        [
            ("Chemotherapy has not been given.", CH, []),
            ("Poorly controlled hypertension has not been diagnosed.", HT, []),
            ("未曾接受化學治療。", CH, []),
            ("化学療法を受けていない。", CH, []),
        ],
    ),
    "R6 a word the cue negates right before it": (
        [
            ("化学療法歴があり、手術適応がない。", CH, []),
            ("化学療法を受け、効果がない。", CH, []),
        ],
        [
            ("コントロール不良の高血圧がない。", HT, []),
            ("Poorly controlled hypertension was not seen.", HT, []),
            ("高血圧、コントロール不良の糖尿病がない。", HT, []),
            ("無控制不良的高血壓。", HT, []),
        ],
    ),
    "R7 another named concept in another clause": (
        [
            ("Prior surgery is required; no prior radiotherapy.", SU, ["radiotherapy"]),
            ("手術歴はあるが、放射線治療歴はない。", SU, ["放射線治療"]),
            ("曾接受手術,但未曾接受放射線治療。", SU, ["放射線治療"]),
        ],
        [
            ("Prior surgery is required; no prior radiotherapy.", SU, []),
            ("Eligible for chemotherapy; no prior cytotoxic treatment.", CH, []),
            ("Prior surgery; no prior radiotherapy; or chemotherapy.", CH, ["surgery", "radiotherapy"]),
            ("化学療法；放射線療法：なし", CH, ["放射線療法"]),
            ("手術歴はあるが化学療法歴はない。", CH, ["手術"]),
            ("適合接受化學治療，但未曾接受化療。", CH, []),
            ("未曾接受化學治療,但曾接受手術。", CH, ["手術"]),
        ],
    ),
    "R8 a modifier after the concept, or a relative clause on absence before it (ja)": (
        [
            ("Chronic hepatitis B without cirrhosis.", HB, []),
            ("Asthma not on oral corticosteroids.", AS, []),
            ("肝硬変のない慢性B型肝炎。", HB, ["肝硬変"]),
            ("経口ステロイドを使用していない喘息。", AS, []),
        ],
        [
            ("Cirrhosis without chronic hepatitis B.", HB, []),
            ("Type 2 diabetes mellitus without ketoacidosis.", ["ketoacidosis"], []),
            ("Type 2 diabetes mellitus with or without ketoacidosis.", ["ketoacidosis"], []),
            ("Without type 2 diabetes mellitus.", ["type 2 diabetes mellitus"], []),
            ("Chemotherapy is not on the formulary.", CH, []),
            ("No chronic hepatitis B without cirrhosis.", HB, []),
            ("Smoking not in the past year.", ["smoking"], []),
            ("Alcohol use not for 2 years.", ["alcohol use"], []),
            ("Asthma without it.", AS, []),
            ("受けたことのない化学療法。", CH, []),
            # the lead's independent round: a relative clause whose head is what was never received or given
            ("受けた経験のない化学療法", CH, []),
            ("投与経験のない抗PD-1抗体", ["抗PD-1抗体"], []),
            ("受けた経験を持たない化学療法。", CH, []),
            ("肝硬変のない慢性B型肝炎。", HB, []),  # the subject of ない is not an extracted concept: cannot tell
            ("本人が受けていない化学療法。", CH, []),
            ("肝硬変のない慢性B型肝炎がない。", HB, []),
            ("化学療法のない肺癌。", CH, []),
            ("無心臟病之家族史。", ["家族史"], []),
        ],
    ),
    "S status: uncertain, hypothetical, another person's, over; a bound on a count": (
        [
            ("Sepsis confirmed by blood culture.", ["sepsis"], []),
            ("Documented atrial fibrillation on ECG.", ["atrial fibrillation"], []),
            (
                "Serum urate ≥6.8 mg/dL, or ≥6.0 mg/dL if receiving urate-lowering therapy.",
                ["urate-lowering therapy"],
                [],
            ),
            ("High-risk breast cancer.", ["breast cancer"], []),
            ("At least two prior lines of chemotherapy.", CH, []),
            ("Not more than 8 weeks since the last chemotherapy dose.", CH, []),
            ("2レジメン以上の化学療法歴がある。", CH, []),
            ("曾接受至少兩線化療。", ["化療"], []),
            ("現在喫煙している。", ["喫煙"], []),
            ("No longer responding to chemotherapy.", CH, []),
            ("Transfusion-dependent anaemia.", ["transfusion"], []),
            ("Family history of type 2 diabetes.", ["family history of type 2 diabetes"], []),
            ("Fractures should have occurred after the onset of diabetes.", ["fracture"], []),
            ("Hypertension. Should hypotension occur, stop the drug.", HT, []),
        ],
        [
            ("Suspected sepsis.", ["sepsis"], []),
            ("Family history of type 2 diabetes.", ["type 2 diabetes"], []),
            ("Should hypotension occur, stop the drug.", ["hypotension"], []),
            ("Sepsis? Blood cultures pending.", ["sepsis"], []),
            ("If sepsis develops, antibiotics are started.", ["sepsis"], []),
            ("敗血症が発症した場合は抗菌薬を開始する。", ["敗血症"], []),
            ("若發生敗血症，需使用抗生素。", ["敗血症"], []),
            ("At risk of sepsis.", ["sepsis"], []),
            ("Sister with sepsis.", ["sepsis"], []),
            ("家族歴：敗血症（母）", ["敗血症"], []),
            ("家族史：父親患敗血症", ["敗血症"], []),
            ("Sepsis, cured.", ["sepsis"], []),
            ("敗血症は治癒した。", ["敗血症"], []),
            ("敗血症已痊癒。", ["敗血症"], []),
            ("Up to three prior regimens of chemotherapy.", CH, []),
            ("化学療法は3コースまで。", CH, []),
            ("化療最多三個療程。", ["化療"], []),
            ("No longer on dialysis.", ["dialysis"], []),
            ("Never before given chemotherapy.", CH, []),
            ("Painless haematuria.", ["pain"], []),
            ("Transfusion-independent.", ["transfusion"], []),
            ("Inactive tuberculosis.", ["active tuberculosis"], []),
        ],
    ),
    "R9 an exception's own object": (
        [
            ("Prior immunotherapy other than anti-CTLA-4 antibodies.", IM, []),
            ("抗CTLA-4抗体を除く免疫療法の治療歴。", IM, []),
            ("除抗CTLA-4抗體外之免疫治療。", IM, []),
            ("抗CTLA-4抗體以外之免疫治療。", IM, []),
            # the lead's final round: the excepted item's own name begins with a negating prefix
            ("Any malignancy other than non-melanoma skin cancer within 5 years.", ["malignancy"], []),
            ("Any malignancy apart from non-melanoma skin cancer.", ["malignancy"], []),
            ("Any malignancy excluding non-melanoma skin cancer.", ["malignancy"], []),
            ("非小細胞肺癌を除く悪性腫瘍。", ["悪性腫瘍"], []),
            ("除非小細胞肺癌外之惡性腫瘤。", ["惡性腫瘤"], []),
            ("非小細胞肺癌以外之惡性腫瘤。", ["惡性腫瘤"], []),
        ],
        [
            ("Any prior therapy except immunotherapy.", IM, []),
            ("Except immunotherapy, any prior therapy.", IM, []),
            ("No immunotherapy other than anti-CTLA-4 antibodies.", IM, []),
            ("Prior immunotherapy other than within a trial is not allowed.", IM, []),
            ("免疫療法を除く治療歴がある。", IM, []),
            ("免疫療法以外の治療。", IM, []),
            ("抗CTLA-4抗体を除き、免疫療法は不可。", IM, []),
            ("除免疫治療外之其他治療。", IM, []),
            ("免疫治療以外之治療。", IM, []),
            ("除抗CTLA-4抗體外，不得接受免疫治療。", IM, []),
            ("Any malignancy other than non-melanoma skin cancer within 5 years.", ["non-melanoma skin cancer"], []),
            ("Any malignancy except non-small cell lung cancer.", ["non-small cell lung cancer"], []),
            ("Any malignancy excluding non-melanoma skin cancer.", ["non-melanoma skin cancer"], []),
            ("Any malignancy apart from non-melanoma skin cancer.", ["non-melanoma skin cancer"], []),
            ("Any malignancy aside from basal cell carcinoma.", ["basal cell carcinoma"], []),
            ("非小細胞肺癌を除く悪性腫瘍。", ["非小細胞肺癌"], []),
            ("非小細胞肺癌以外の悪性腫瘍。", ["非小細胞肺癌"], []),
            ("除非小細胞肺癌外之惡性腫瘤。", ["非小細胞肺癌"], []),
            ("非小細胞肺癌以外之惡性腫瘤。", ["非小細胞肺癌"], []),
        ],
    ),
}


RULE_RUNS = [(r, *x) for r, (runs, _) in RULES.items() for x in runs]
RULE_HELD = [(r, *x) for r, (_, held) in RULES.items() for x in held]


def _rule_atom() -> Atom:
    return Atom(domain="condition", valueset="VS_X", quantifier="any")


@pytest.mark.parametrize(
    ("rule", "text", "terms", "others"), RULE_RUNS, ids=[f"{r[:2]}-{x[0][:24]}" for r, *x in RULE_RUNS]
)
def test_each_release_rule_lets_its_shape_run(rule: str, text: str, terms: list[str], others: list[str]) -> None:
    from criteria_compiler.ir_extract.negation_scope import negated_presence

    assert not negated_presence(text, _rule_atom(), lambda vs: terms, others), (rule, text)


@pytest.mark.parametrize(
    ("rule", "text", "terms", "others"), RULE_HELD, ids=[f"{r[:2]}-{x[0][:24]}" for r, *x in RULE_HELD]
)
def test_each_release_rule_holds_its_near_misses(rule: str, text: str, terms: list[str], others: list[str]) -> None:
    from criteria_compiler.ir_extract.negation_scope import negated_presence

    assert negated_presence(text, _rule_atom(), lambda vs: terms, others), (rule, text)


def test_an_age_or_sex_alone_and_an_exclusion_are_not_this_rule() -> None:
    age = _one("No younger than 18 years", {"domain": "demographic", "age": {"min": 18}}, concepts=[])
    assert age.class_ in FILTERED and FLAG not in (age.flags or [])
    exc = _one("No prior chemotherapy", CHEMO, kind="exclusion")  # an exclusion's own rules decide it, not this one
    assert FLAG not in (exc.flags or [])


def test_a_negated_mixed_line_is_held_before_another_rule_hands_it_to_the_notes() -> None:
    """The age-at-onset rule hands a mixed line to the notes; a negated inclusion must not get there first, where a
    model would answer the presence question."""
    x = _one("No chemotherapy before age 18", {**CHEMO, "age": {"max": 18}}, cls="mixed",
             question="Did the patient receive chemotherapy before age 18?")  # fmt: skip
    _held(x)


def test_the_reason_is_said_to_the_reviewer() -> None:
    post = _post([{"kind": "inclusion", "class": "structured", "text": "No prior chemotherapy", "logic": CHEMO,
                   "concept_candidates": CHEMO_CAND}])  # fmt: skip
    assert any("T-INC-01" in w and "negates" in w and "person" in w for w in post.warnings), post.warnings


def test_held_it_answers_unknown_and_never_excludes() -> None:
    """Unknown never excludes: the held line is neither compiled for S1 nor asked of a model; it reaches the engine
    as a person's question, which never excludes (``test_safety_properties.py``, P1's tier table)."""
    x = _one("No prior chemotherapy", CHEMO)
    assert x.class_ == "human" and x.class_ not in FILTERED and x.class_ not in JUDGED
    assert isinstance(x.logic, Atom) and x.logic.domain == "demographic" and x.logic.valueset == "NONE"
    assert x.logic.age is None and x.logic.sex is None


def test_an_approved_negated_inclusion_reused_by_an_incremental_compile_goes_to_a_person(
    env: dict[str, Any],  # noqa: F811 (the compiler-service fixture)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An approved version compiled before this card (the rule off) has "No history of gout." as ``any of VS_GOUT``.
    The next compile reuses the approved line verbatim and skips postprocess: the rule must still see it, flag it,
    say so, and give it to a person, never run it."""
    doc = parse(PDF.read_bytes(), PDF.name)
    inc = list(doc.ie_block.inclusion)
    inc[1] = "No history of gout."
    doc = doc.model_copy(update={"ie_block": doc.ie_block.model_copy(update={"inclusion": inc})})
    env["store"].put("attachments/J/neg.json", c.dump_json(doc).encode())
    real = pp.postprocess

    def before_this_card(*a: Any, **kw: Any) -> Any:  # the compiler as it was: the line kept as presence
        out = real(*a, **kw)
        for i, x in enumerate(out.criteria):
            if x.text == "No history of gout.":
                gout = Atom(domain="condition", valueset="VS_GOUT", quantifier="any")
                out.criteria[i] = x.model_copy(update={"class_": "structured", "logic": gout, "flags": []})
        return out

    monkeypatch.setattr("criteria_compiler.ir_extract.postprocess.negated_presence", lambda *a, **kw: False)
    monkeypatch.setattr("criteria_compiler.service.postprocess", before_this_card)
    res = _compile(env, key="attachments/J/neg.json")
    first = next(x for x in res.criteria if x.text == "No history of gout.")
    assert first.class_ == "structured"  # the old compiler's mistake, approved as it was
    assert _approve(env, _decisions(env["store"], res.review_xlsx_key)).status == "approved"

    monkeypatch.undo()
    res2 = _compile(env, key="attachments/J/neg.json")
    again = next(x for x in res2.criteria if x.text == "No history of gout.")
    assert again.id == first.id  # the approved criterion, reused
    assert again.class_ == "human" and again.human_question and FLAG in (again.flags or [])
    assert isinstance(again.logic, Atom) and again.logic.valueset == "NONE"
    assert any(first.id in w and "approved before" in w for w in res2.warnings or []), res2.warnings


def test_the_scan_lists_an_approved_negated_inclusion_and_changes_nothing(
    env: dict[str, Any],  # noqa: F811 (the compiler-service fixture)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The approved ruleset on main is what the engine runs: the scan (``make negated-inclusion-scan``, the doctor's
    ``negated_inclusions``) names its negated inclusion by ruleset, version and criterion, and leaves main as it was."""
    from criteria_compiler.negated_inclusions import scan

    from tools.trialbox import doctor

    doc = parse(PDF.read_bytes(), PDF.name)
    inc = list(doc.ie_block.inclusion)
    inc[1] = "No history of gout."
    doc = doc.model_copy(update={"ie_block": doc.ie_block.model_copy(update={"inclusion": inc})})
    env["store"].put("attachments/J/neg.json", c.dump_json(doc).encode())
    real = pp.postprocess

    def before_this_card(*a: Any, **kw: Any) -> Any:
        out = real(*a, **kw)
        for i, x in enumerate(out.criteria):
            if x.text == "No history of gout.":
                gout = Atom(domain="condition", valueset="VS_GOUT", quantifier="any")
                out.criteria[i] = x.model_copy(update={"class_": "structured", "logic": gout, "flags": []})
        return out

    monkeypatch.setattr("criteria_compiler.ir_extract.postprocess.negated_presence", lambda *a, **kw: False)
    monkeypatch.setattr("criteria_compiler.service.postprocess", before_this_card)
    res = _compile(env, key="attachments/J/neg.json")
    assert _approve(env, _decisions(env["store"], res.review_xlsx_key)).status == "approved"
    monkeypatch.undo()
    repo = env["deps"].repo
    before = repo.ref("main")
    hits = scan(repo)
    cid = next(x.id for x in res.criteria if x.text == "No history of gout.")
    assert [(h.ruleset, h.version, h.criterion) for h in hits] == [("GZQO", "1.0.0", cid)]
    assert repo.ref("main") == before  # read-only
    check = doctor.check_negated_inclusions(doctor.DoctorInputs(env={"TB_RULESETS_DIR": str(repo.path)}))
    assert check.status == "WARN" and f"GZQO v1.0.0 {cid}" in check.detail
    none_here = doctor.check_negated_inclusions(doctor.DoctorInputs(env={"TB_RULESETS_DIR": "/nonexistent"}))
    assert none_here.status == "PASS" and none_here.detail.startswith("NOT CHECKED")


def test_the_offline_install_reports_a_negated_inclusion() -> None:
    """``import_ruleset`` installs the vendor's approved ruleset as it is and reports the ids the rule would hold."""
    from criteria_compiler.import_ruleset import negated_hits
    from tb_common.ruleset import SEED_RULESETS

    files = {p.relative_to(SEED_RULESETS / "GZQO").as_posix(): p.read_bytes()
             for p in (SEED_RULESETS / "GZQO").rglob("*") if p.is_file()}  # fmt: skip
    assert negated_hits(_zip(files)) == []
    ir = json.loads(files["ir/GZQO-INC-02.json"])
    assert ir["kind"] == "inclusion" and ir["class"] == "structured"
    files["ir/GZQO-INC-02.json"] = json.dumps({**ir, "text": "No history of gout."}).encode()
    assert negated_hits(_zip(files)) == ["GZQO-INC-02"]


def _zip(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()
