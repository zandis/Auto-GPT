"""INT-S-B (D-1072): a patient whose note reading speaks against a criterion stays on the list, and the page and the
workbook say so. Where they printed ``unknown`` with the reason ``not_final``, they print "A note may speak against
[criterion]. Not excluded. Please check." with every verified quote and its date; those rows come last among the
review rows of the same appointment day (and only there); a header line counts the patients. Display only: who is on
the list, and every status, is what it was. The property tests enumerate their inputs (no ``hypothesis``, as
``tests/unit/test_safety_properties.py``)."""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any, Literal

import pytest
from console import studies as st
from console.i18n import CATALOGUES
from jinja2 import Environment, FileSystemLoader
from openpyxl import load_workbook
from orchestrator.reports import candidate_xlsx
from orchestrator.scenarios.evaluate import sort_key, sort_rows
from tb_common.ruleset import Ruleset
from tb_common.wording import check
from tb_contracts import CandidateRow, CriterionVerdict, Evidence, Opinion

from tests.unit.test_feas_unit import META

ROOT = Path(__file__).resolve().parents[2]
TPL = ROOT / "services" / "console" / "templates"
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
EXC = next(c for c in GZQO.active() if c.class_ == "note" and c.kind == "exclusion")
LANGS = ("en", "ja", "zh-TW")
SAID = {
    "en": "A note may speak against {c}. Not excluded. Please check.",
    "ja": "記録の文章が{c}に反する可能性があります。除外していません。確認してください。",
    "zh-TW": "病歷文字可能不利於{c}。未排除。請確認。",
}
COUNT = {
    "en": "Patients with a note that may speak against a criterion: {n}. None is excluded.",
    "ja": "記録の文章が基準に反する可能性がある患者：{n}名。いずれも除外していません。",
    "zh-TW": "病歷文字可能不利於某項條件的病人：{n} 位。皆未排除。",
}
JUDGE_Q, JUDGE_D = "History of breast cancer 2019.", "2026-09-30"
VERIF_Q, VERIF_D = "Breast cancer, treated in 2019.", "2026-10-01"


def against(cid: str = EXC.id) -> CriterionVerdict:
    """What a pair's stated, affirmed note exclusion stores (D-1072): a soft fail, ``final: false``, both quotes."""
    return CriterionVerdict(
        id=cid,
        verdict="fail",
        basis="pair",
        final=False,
        affirmed=True,
        evidence=Evidence(
            reason="notes_suggest_not_eligible",
            quote=JUDGE_Q,
            quote_date=JUDGE_D,
            confidence=0.9,
            opinions=[
                Opinion(role="judge", verdict="fail", quote=JUDGE_Q, quote_date=JUDGE_D),
                Opinion(role="verifier", verdict="fail", quote=VERIF_Q, quote_date=VERIF_D),
            ],
        ),
    )


def plain(cid: str = EXC.id) -> CriterionVerdict:
    return CriterionVerdict(
        id=cid, verdict="pass", evidence=Evidence(reason="note", quote="No cancer.", confidence=0.9)
    )


def row(
    pid: str, tier: Literal["high", "review", "excluded"], when: str | None, *criteria: CriterionVerdict
) -> CandidateRow:
    at = datetime.fromisoformat(when).replace(tzinfo=UTC) if when else None
    return CandidateRow(pid=pid, tier=tier, next_appointment=at, criteria=list(criteria), actions=[])


def sheet(rows: list[CandidateRow], lang: str = "en") -> Any:
    wb = load_workbook(io.BytesIO(candidate_xlsx.render(rows, GZQO, replace(META, locale=lang), {}, {})))
    return wb["candidates"]


def cell_of(ws: Any, pid: str) -> Any:
    col = [c.value for c in ws[1]].index(f"C_{EXC.id}") + 1
    return next(r[col - 1] for r in ws.iter_rows(min_row=2) if r[1].value == pid)


# ------------------------------------------------------------------------------------------- the workbook
@pytest.mark.parametrize("lang", LANGS)
def test_the_workbook_says_a_note_may_speak_against_with_every_quote_and_date(lang: str) -> None:
    cell = cell_of(sheet([row("P1", "review", "2026-10-07T09:00", against())], lang), "P1")
    assert cell.value == SAID[lang].format(c=EXC.label or EXC.id)
    for text in (JUDGE_Q, JUDGE_D, VERIF_Q, VERIF_D):
        assert text in cell.comment.text, text


@pytest.mark.parametrize("lang", LANGS)
def test_the_workbook_header_counts_the_patients(lang: str) -> None:
    rows = [row("P1", "review", "2026-10-07T09:00", against()), row("P2", "review", None, against()),
            row("P3", "high", "2026-10-07T10:00", plain())]  # fmt: skip
    values = [c.value for r in sheet(rows, lang).iter_rows() for c in r]
    assert COUNT[lang].format(n=2) in values


def test_a_patient_with_no_note_against_is_unchanged_in_the_workbook() -> None:
    only = [row("P3", "high", "2026-10-07T10:00", plain())]
    both = [row("P1", "review", "2026-10-07T09:00", against()), *only]
    a, b = sheet(only), sheet(both)
    assert [c.value for c in cell_of_row(a, "P3")] == [c.value for c in cell_of_row(b, "P3")]
    assert cell_of(a, "P3").comment.text == cell_of(b, "P3").comment.text
    assert COUNT["en"].format(n=1) not in [c.value for r in a.iter_rows() for c in r]  # no flagged row: no line


def cell_of_row(ws: Any, pid: str) -> Any:
    return next(r for r in ws.iter_rows(min_row=2) if r[1].value == pid)


# ------------------------------------------------------------------------------------------- the investigator's page
def meta_of(c: Any = EXC) -> dict[str, st.CriterionMeta]:
    return {c.id: st.CriterionMeta(c.id, c.kind, c.class_, c.label or c.id, c.text)}


def stored(v: CriterionVerdict) -> dict[str, Any]:
    return v.model_dump(mode="json", exclude_none=True)


def page(lang: str, crits: list[dict[str, Any]]) -> str:
    cat = CATALOGUES[lang]
    env = Environment(loader=FileSystemLoader(str(TPL)), autoescape=True)

    def t(key: str, **kw: object) -> str:
        return cat[key].format(**kw) if key in cat else key

    env.globals.update(t=t, t_or=lambda k, d="": cat.get(k, d), tone=lambda *a: "", given=lambda v, *a: v,
                       reason_label=lambda *a: "", lang=lang, values_unread=False)  # fmt: skip
    return env.get_template("_criteria.html").render(crits=crits)


@pytest.mark.parametrize("lang", LANGS)
def test_the_criteria_page_says_a_note_may_speak_against_with_the_quotes_and_dates(lang: str) -> None:
    crits = st.patient_rows([stored(against())], meta_of())
    html = page(lang, crits).replace("&#39;", "'")
    assert SAID[lang].format(c=EXC.label or EXC.id) in html
    for text in (JUDGE_Q, JUDGE_D, VERIF_Q, VERIF_D):
        assert text in html, text
    assert f'data-testid="verdict-{EXC.id}"' not in html  # no "unknown" pill beside it


def test_a_patient_with_no_note_against_has_the_same_page_row() -> None:
    crits = st.patient_rows([stored(plain())], meta_of())
    assert crits[0]["against"] is False
    assert f'data-testid="verdict-{EXC.id}"' in page("en", crits)
    assert "may speak against" not in page("en", crits)


def test_a_note_against_stays_open_and_is_named_for_the_list() -> None:
    fit = st.fit_facts([stored(against())], meta_of())
    assert fit.against == [EXC.label or EXC.id] and fit.open == [EXC.label or EXC.id]  # not "ready": a person checks


def weekly(*rows: CandidateRow) -> list[str]:
    cl = {"rows": [r.model_dump(mode="json") for r in rows]}
    return [r["pid"] for r in st.weekly_rows(cl, meta_of(), {}, {}, {}, "J1")]


def test_the_weekly_list_puts_them_last_among_the_days_review_rows_only() -> None:
    a = row("A", "review", "2026-10-07T09:00", against())
    b = row("B", "review", "2026-10-07T10:00", plain())
    h = row("H", "high", "2026-10-07T11:00", plain())
    c = row("C", "review", "2026-10-08T08:00", plain())
    assert weekly(a, b, h, c) == ["B", "A", "H", "C"]  # a high row keeps its place; day two stays after day one
    d = row("D", "review", "2026-10-06T08:00", against())
    assert weekly(d, a, b, c)[0] == "D"  # earlier day: not moved behind a later day's plain rows


# ------------------------------------------------------------------------------------------- the stored list order
def test_within_a_day_they_come_last_among_the_review_rows_and_not_across_days() -> None:
    a = row("A", "review", "2026-10-07T09:00", against())
    b = row("B", "review", "2026-10-07T10:00", plain())
    h = row("H", "high", "2026-10-07T11:00", plain())
    c = row("C", "review", "2026-10-08T08:00", plain())
    e = row("E", "review", "2026-10-06T08:00", against())
    n = row("N", "review", None, against())
    z = row("Z", "review", None, plain())
    assert [r.pid for r in sort_rows([a, b, h, c, e, n, z])] == ["E", "B", "A", "H", "C", "Z", "N"]


def test_the_set_of_patients_is_identical_and_the_rest_is_unchanged() -> None:
    """Over every mix of tier, day, time and flag: the same patients, in the base order when none is flagged, and
    with flagged rows moved only among their own day's review places."""
    days = ("2026-10-07", "2026-10-08", None)
    tiers: tuple[Literal["high", "review"], ...] = ("high", "review")
    specs = list(product(tiers, days, (False, True)))
    for size in (1, 2, 3):
        for combo in product(specs, repeat=size):
            rows = [
                row(f"P{i}", t, f"{d}T0{9 - i}:00" if d else None, against() if f else plain())
                for i, (t, d, f) in enumerate(combo)
            ]
            got = sort_rows(rows)
            base = sorted(rows, key=sort_key)
            assert sorted(r.pid for r in got) == sorted(r.pid for r in rows)
            if not any(f for _, _, f in combo):
                assert got == base
            for i, (x, y) in enumerate(zip(base, got, strict=True)):  # a place keeps its tier and its day
                assert (x.tier, str(x.next_appointment)[:10]) == (y.tier, str(y.next_appointment)[:10]), (combo, i)
                if x.tier == "high":
                    assert x is y


# ------------------------------------------------------------------------------------------- the words
@pytest.mark.parametrize("lang", LANGS)
def test_the_words_pass_the_claims_lint_and_are_in_the_console(lang: str) -> None:
    said = SAID[lang].format(c="X")
    assert CATALOGUES[lang]["note.against"].format(criterion="X") == said
    assert CATALOGUES[lang]["note.against.count"].format(n=3) == COUNT[lang].format(n=3)
    assert check(said, lang=lang) == [] and check(COUNT[lang].format(n=3), lang=lang) == []


@pytest.mark.parametrize(
    ("lang", "text"),
    [("en", "Excluded by the notes."), ("en", "The patient was excluded."), ("zh-TW", "病人已排除。"),
     ("ja", "病人は除外しました。")],
)  # fmt: skip
def test_a_positive_verdict_is_still_refused_beside_the_allowed_denials(lang: str, text: str) -> None:
    assert check(text, lang=lang) != []
    assert check(f"{text} {SAID[lang].format(c='X')}", lang=lang) != []


def test_the_workbook_print_header_carries_the_count() -> None:
    ws = sheet([row("P1", "review", "2026-10-07T09:00", against())])
    assert COUNT["en"].format(n=1) in ws.oddHeader.center.text


def test_a_final_pair_ring0_not_met_is_said_as_a_note_against_too() -> None:
    """Review of #1547 M2: a ring-0 row stored ``final: true`` (a run whose pair was allowed to exclude, D-1072 says
    it never does) is said, counted and sorted as a note speaking against, never as a plain "not met"."""
    fin = against().model_copy(update={"final": True})
    assert cell_of(sheet([row("P1", "review", "2026-10-07T09:00", fin)]), "P1").value == SAID["en"].format(
        c=EXC.label or EXC.id
    )
    rows = [row("P1", "review", "2026-10-07T09:00", fin), row("P2", "review", "2026-10-07T10:00", plain())]
    assert COUNT["en"].format(n=1) in [c.value for r in sheet(rows).iter_rows() for c in r]
    assert [r.pid for r in sort_rows(rows)] == ["P2", "P1"]
    assert st.patient_rows([stored(fin)], meta_of())[0]["against"] is True
    plain_fail = fin.model_copy(update={"evidence": Evidence(reason="note", quote=JUDGE_Q, confidence=0.9)})
    assert st.patient_rows([stored(plain_fail)], meta_of())[0]["against"] is False  # only the ring-0 reason
