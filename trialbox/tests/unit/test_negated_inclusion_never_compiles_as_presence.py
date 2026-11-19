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


ALL = [*ROWS, *UNSEEN, *CARD, *REVIEW]


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
    """Card 10A-1's table: every negated line held; 6 of the 69 that should run are held by the fail-safe (8 before
    card 10A-1b). The lines unseen at design: every negated line held; 12 of the 23 that should run are held (20
    before). Card 10A-1b's own lines: every negated line held (12 of 40 ran before it: a cue over a list); 1 of the 40
    that should run is held (18 before)."""
    assert _score(ROWS) == (116, 116, 6, 69)
    assert _score(UNSEEN) == (21, 21, 12, 23)
    assert _score(CARD) == (40, 40, 1, 40)
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
    rows = [*ROWS, *UNSEEN, *CARD, *REVIEW]
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
    assert pp.approved_negated(line, {"VS_T2DM": t2dm})  # the ketoacidosis not known: held
    assert not pp.approved_negated(line, {"VS_T2DM": t2dm, "VS_KETO": keto})
    listed = crit("No prior chemotherapy or radiotherapy", "VS_RADIO")
    assert pp.approved_negated(listed, {"VS_RADIO": radio, "VS_CHEMO": chemo})


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
