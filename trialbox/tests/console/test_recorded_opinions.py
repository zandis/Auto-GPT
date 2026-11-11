"""T-515 (D-323, review UX-007): test-model results are labelled and recorded first and second checks are shown.

These are the console's tests: the fixture shape, where a case lands on the candidate list and what the pages show.
How the matching engine itself forms the two checks and refuses one model asked twice is fix group D-276's, tested in
``tests/unit/test_note_pair_disagreement.py``, ``test_two_model_identity.py`` and the other files that name D-276.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from console import recorded_opinions as ro
from console import studies

from tests.console.test_console_app import box, login  # noqa: F401 - box is a fixture
from tests.console.test_criterion_labels import PW, _gzqo, english_words
from tests.console.test_excluded_page import _with_excluded

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "demo" / "fixtures" / "opinions"
A, B = "a" * 32, "b" * 32


def _case(case: str = "agree", v1: str = "pass", v2: str = "pass", quote: str = "[synthetic] x") -> dict[str, Any]:
    return {"ruleset": "GZQO", "criterion": "GZQO-INC-05", "case": case, "opinions": [
        {"role": "judge", "verdict": v1, "quote": quote}, {"role": "verifier", "verdict": v2, "quote": quote}]}  # fmt: skip


def _file(*cases: dict[str, Any], kind: str = "synthetic") -> dict[str, Any]:
    return {"version": 1, "source": {"kind": kind, "name": "unit"}, "cases": list(cases)}


def _cl() -> dict[str, Any]:
    def row(pid: str, tier: str, verdict: str) -> dict[str, Any]:
        return {"pid": pid, "tier": tier, "criteria": [{"id": "GZQO-INC-05", "verdict": verdict, "evidence": {}}]}

    return {"rows": [row("c" * 32, "excluded", "pass"), row(B, "review", "unknown"), row(A, "high", "pass")]}


# ---------------------------------------------------------------------------------------------- the fixture
def test_the_shipped_fixture_is_synthetic_and_has_an_agreement_and_a_disagreement() -> None:
    rec = ro.load(SHIPPED)
    assert {c.case for c in rec.cases} == {"agree", "disagree"}
    assert all(c.kind == "synthetic" for c in rec.cases)
    assert all(str(o["quote"]).startswith("[synthetic]") for c in rec.cases for o in c.opinions)
    assert not (SHIPPED / "g1-short-run.json").exists()  # the documented slot: the G1 file drops in later
    assert "g1-short-run.json" in (SHIPPED / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (_file(_case(quote="no mark")), "starts with [synthetic]"),
        (_file(_case("agree", "pass", "fail")), "an 'agree' case has one verdict"),
        (_file(_case("disagree", "pass", "pass")), "an 'agree' case has one verdict"),
        (_file({**_case(), "opinions": _case()["opinions"][:1]}), "one judge and one verifier"),
        ({**_file(_case()), "source": {"kind": "made-up", "name": "x"}}, "source.kind"),
        ({**_file(_case()), "version": 2}, "version 1"),
    ],
)
def test_a_fixture_that_breaks_the_shape_is_refused(data: dict[str, Any], why: str) -> None:
    with pytest.raises(ro.FixtureError, match=why.replace("[", r"\[").replace("]", r"\]")):
        ro.parse(data)


def test_a_recorded_file_needs_no_synthetic_mark(tmp_path: Path) -> None:
    (tmp_path / "g1-short-run.json").write_text(json.dumps(_file(_case(quote="real words"), kind="recorded")))
    assert ro.load(tmp_path).cases[0].kind == "recorded"


def test_only_a_dev_or_test_box_reads_fixtures() -> None:
    assert ro.from_env({"TB_ENV": "DEV", ro.ENV_KEY: str(SHIPPED)})
    assert ro.from_env({"TB_ENV": "test", ro.ENV_KEY: str(SHIPPED)})
    assert not ro.from_env({ro.ENV_KEY: str(SHIPPED)})  # PRODUCTION when unset (D-127)
    assert not ro.from_env({"TB_ENV": "PRODUCTION", ro.ENV_KEY: str(SHIPPED)})
    assert not ro.from_env({"TB_ENV": "DEV"}) and not ro.from_env({"TB_ENV": "DEV", ro.ENV_KEY: "/nowhere"})


# ---------------------------------------------------------------------------------------------- where a case lands
def test_a_case_lands_only_on_a_listed_row_with_the_verdict_it_implies() -> None:
    rec = ro.Recorded(tuple(ro.parse(_file(_case(), _case("disagree", "pass", "fail")))))
    cl = _cl()
    before = copy.deepcopy(cl)
    out = rec.apply(cl, "gzqo")
    assert cl == before  # a copy; the loaded list is not changed
    rows = {r["pid"]: r["criteria"][0]["evidence"].get("opinions") for r in out["rows"]}  # type: ignore[index]
    assert [o["verdict"] for o in rows[A]] == ["pass", "pass"]  # agree: on the "met" row
    assert [o["verdict"] for o in rows[B]] == ["pass", "fail"]  # disagree: on the unknown row
    assert rows["c" * 32] is None  # an excluded patient is not listed
    assert {o["recorded"] for o in rows[A]} == {"synthetic"} and rows[A][0]["recorded_source"] == "unit"
    assert rec.apply(cl, "GOUT-COH") is cl and rec.apply(None, "GZQO") is None


def test_a_case_never_contradicts_the_row_and_a_pid_pins_it() -> None:
    fail = ro.Recorded(tuple(ro.parse(_file(_case("agree", "fail", "fail")))))
    out = fail.apply(_cl(), "GZQO")
    assert not any(r["criteria"][0]["evidence"].get("opinions") for r in out["rows"])  # type: ignore[index]
    pinned = ro.Recorded(tuple(ro.parse(_file({**_case("disagree", "fail", "pass"), "pid": A}))))
    out = pinned.apply(_cl(), "GZQO")
    assert not any(r["criteria"][0]["evidence"].get("opinions") for r in out["rows"])  # type: ignore[index]


def test_an_opinion_says_where_it_came_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TB_LLM_MODE", raising=False)
    monkeypatch.setenv("TB_ENV", "DEV")
    live = [{"role": "judge", "verdict": "pass", "quote": "q"}, {"role": "verifier", "verdict": "fail", "quote": "r"}]
    rows = studies.patient_rows([{"id": "X", "verdict": "unknown", "evidence": {"opinions": live}}], {})
    assert [o["label"] for o in rows[0]["opinions"]] == ["test_model", "test_model"] and rows[0]["disagree"]
    monkeypatch.setenv("TB_LLM_MODE", "vllm")  # a real model on this box: no label
    rows = studies.patient_rows([{"id": "X", "verdict": "pass", "evidence": {"opinions": live[:1]}}], {})
    assert rows[0]["opinions"][0]["label"] == "" and not rows[0]["disagree"]
    rec = [{**o, "recorded": "recorded", "recorded_source": "G1 short run"} for o in live]
    rows = studies.patient_rows([{"id": "X", "verdict": "unknown", "evidence": {"opinions": rec}}], {})
    assert rows[0]["opinions"][0]["label"] == "recorded" and rows[0]["opinions"][0]["source_name"] == "G1 short run"


# ---------------------------------------------------------------------------------------------- the pages
WORDS = {
    "en": ("synthetic example", "the two checks disagree", "First check", "test model"),
    "ja": ("合成した例", "2 つの確認で判断が分かれています", "1回目の確認", "テスト用モデル"),
    "zh-TW": ("合成範例", "兩次確認的判斷不一致", "第一次確認", "測試用模型"),
}


@pytest.mark.parametrize("lang", sorted(WORDS))
def test_the_demo_pages_show_an_agreement_and_a_disagreement_with_their_source(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    lang: str,
) -> None:
    _gzqo(box)
    _with_excluded(box)
    box["app"].state.helpers.recorded = ro.from_env({"TB_ENV": "DEV", ro.ENV_KEY: str(SHIPPED)})
    monkeypatch.delenv("TB_LLM_MODE", raising=False)
    monkeypatch.setenv("TB_ENV", "DEV")
    box["users"].create("walker", "investigator", PW, "walker@hospa.test")
    c, csrf = login(box["app"], "walker", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    synthetic, disagree, first, test_model = WORDS[lang]
    agree = c.get(f"/studies/GZQO/patients/{A}").text
    for role in ("judge", "verifier"):
        assert f'data-testid="opinion-GZQO-INC-05-{role}"' in agree
        assert f'data-testid="opinion-src-GZQO-INC-05-{role}" data-source="synthetic"' in agree
    assert "[synthetic] Gout flare of the right first toe" in agree and "[synthetic] Two flares" in agree
    assert synthetic in agree and first in agree and 'data-testid="opinion-explain"' in agree
    assert 'data-testid="opinion-disagree-' not in agree
    assert 'data-testid="test-model-GZQO-INC-05"' in agree and test_model in agree  # the verdict: test model
    other = c.get(f"/studies/GZQO/patients/{B}").text
    assert 'data-testid="opinion-disagree-GZQO-INC-05"' in other and disagree in other
    assert "[synthetic] Patient reports joint pain" in other and "[synthetic] Ankle pain after a fall" in other
    week = c.get(f"/studies/GZQO/week?pid={A}").text
    assert 'data-testid="opinion-src-GZQO-INC-05-judge" data-source="synthetic"' in week and synthetic in week
    if lang != "en":
        assert english_words(agree) == [] and english_words(other) == []
    box["app"].state.helpers.recorded = ro.Recorded()  # no fixture (any production box): no opinion block
    assert 'data-testid="opinion-' not in c.get(f"/studies/GZQO/patients/{A}").text
