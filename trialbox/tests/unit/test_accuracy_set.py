"""NEW-LLM-6 (deep review 2026-11-12, LLM-006, LLM-009): the accuracy set per language and stratum, its scorer and its
runner.

The measured note accuracy rested on one template study in Japanese (464 exclusions, two criteria) and the 54-case
canary. Nothing measured long notes, negated lists, family history, era dates (和暦, 民國), time windows or lab
thresholds written in a note, nor zh-TW and en with the product's ``judge`` prompt. ``tools/accuracy_set.py``
generates, from a seed, at least 200 gold exclusions and 200 gold non-exclusions per language over at least ten
criterion types and seven strata (long notes are cut by the product's own excerpt builder), scores the answers of
each model and of the pair per language and stratum with intervals (wrong exclusions with an exact upper bound), a
ten-bin confidence table and the error and unknown rates at candidate confidence floors, and runs a model with the
canary's call and parser while keeping the confidence. Synthetic text only, no model.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import accuracy_set as acc

ROOT = Path(__file__).resolve().parents[2]
LANGS = ("ja", "zh-TW", "en")
STRATA = {"plain", "long", "negation", "family", "era", "lab", "window"}


@pytest.fixture(scope="module")
def cases() -> list[dict[str, Any]]:
    return acc.generate(seed=acc.SEED)


def _oracle(cases: list[dict[str, Any]], conf: float = 0.9) -> dict[str, dict[str, Any]]:
    """What a model that is always right would answer, quoting the gold evidence."""
    out = {}
    for c in cases:
        data = {"verdict": c["expected"], "confidence": conf, "quote": c.get("evidence"), "reason": "gold"}
        out[c["id"]] = acc.answer_of(data, c["excerpts"])
    return out


# ------------------------------------------------------------------------------------------------- the set
def test_the_set_is_the_same_for_a_seed_and_another_for_another() -> None:
    one = acc.generate(seed=acc.SEED, per_class=1)  # one round of every cell (the whole set: the manifest test)
    assert acc.generate(seed=acc.SEED, per_class=1) == one
    assert acc.generate(seed=acc.SEED + 1, per_class=1) != one


@pytest.mark.parametrize("lang", LANGS)
def test_each_language_has_200_gold_exclusions_and_200_non_exclusions(cases: list[dict[str, Any]], lang: str) -> None:
    mine = [c for c in cases if c["language"] == lang]
    excluded = [c for c in mine if acc.gold_excludes(c) is True]
    kept = [c for c in mine if acc.gold_excludes(c) is False]
    assert len(excluded) >= 200 and len(kept) >= 200
    assert len({c["type"] for c in excluded}) >= 10 and len({c["type"] for c in kept}) >= 10
    assert {c["stratum"] for c in mine} == (STRATA if lang != "en" else STRATA - {"era"})  # no era calendar in en
    assert {c["kind"] for c in mine} == {"inclusion", "exclusion"}
    assert any(c["expected"] == "unknown" for c in mine if c["stratum"] == "family")


def test_every_case_is_a_canary_case(cases: list[dict[str, Any]]) -> None:
    keys = {"id", "language", "criterion_text", "note_question", "index_date", "excerpts", "expected"}
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert keys <= set(c) and c["expected"] in ("pass", "fail", "unknown")
        date.fromisoformat(c["index_date"])
        assert c["excerpts"] and all({"date", "note_type", "text"} <= set(e) for e in c["excerpts"])


def test_every_decided_case_quotes_its_evidence_and_an_always_right_model_scores_all(
    cases: list[dict[str, Any]],
) -> None:
    for c in cases:
        if c["expected"] != "unknown":
            assert any(acc.quote_in(c["evidence"], e["text"]) for e in c["excerpts"]), c["id"]
    rep = acc.score(cases, {"judge": _oracle(cases)})
    m = rep["models"]["judge"]
    assert m["all"]["correct"] == m["all"]["n"] == len(cases)
    assert m["all"]["wrong_exclusions"] == 0 and m["all"]["missed_exclusions"] == 0


@pytest.mark.parametrize("lang", LANGS)
def test_notes_are_written_in_the_sites_language(cases: list[dict[str, Any]], lang: str) -> None:
    kana = re.compile(r"[぀-ヿ]")
    han = re.compile(r"[一-鿿]")
    for c in (c for c in cases if c["language"] == lang):
        text = " ".join(e["text"] for e in c["excerpts"])
        if lang == "ja":
            assert kana.search(text), c["id"]
        elif lang == "zh-TW":
            assert han.search(text) and not kana.search(text), c["id"]
        else:
            assert not han.search(text) and not kana.search(text), c["id"]


def test_a_long_note_is_cut_by_the_products_excerpt_builder(cases: list[dict[str, Any]]) -> None:
    from matching.excerpts import DEFAULT_TOKENS, note_tokens

    longs = [c for c in cases if c["stratum"] == "long"]
    assert longs
    for c in longs:
        assert c["left_out"] >= 1 and c["note_tokens"] > DEFAULT_TOKENS // 2, c["id"]
        assert sum(note_tokens(e["text"]) for e in c["excerpts"]) <= DEFAULT_TOKENS
        assert any("[…]" in e["text"] for e in c["excerpts"])  # the cut is shown as the product shows it


def test_era_dates() -> None:
    assert acc.wareki(date(2024, 5, 1)) == "令和6年5月1日"
    assert acc.wareki(date(2019, 5, 1)) == "令和元年5月1日"
    assert acc.wareki(date(2019, 4, 30)) == "平成31年4月30日"
    assert acc.minguo(date(2024, 5, 1)) == "民國113年5月1日"


@pytest.mark.parametrize("lang,mark", [("ja", "令和|平成"), ("zh-TW", "民國")])
def test_era_cases_write_era_dates_and_their_gold_follows_the_window(
    cases: list[dict[str, Any]], lang: str, mark: str
) -> None:
    era = [c for c in cases if c["language"] == lang and c["stratum"] == "era"]
    assert {c["expected"] for c in era} == {"pass", "fail"}
    for c in era:
        assert re.search(mark, c["evidence"]), c["id"]
        inside = (date.fromisoformat(c["index_date"]) - date.fromisoformat(c["event_date"])).days <= c["window_days"]
        assert (c["expected"] == "pass") == inside, c["id"]


def test_lab_cases_hold_the_threshold_itself(cases: list[dict[str, Any]]) -> None:
    lab = [c for c in cases if c["stratum"] == "lab"]
    assert any(c["value"] == c["threshold"] for c in lab)  # the boundary is in the set
    for c in lab:
        met = c["value"] >= c["threshold"] if c["op"] == ">=" else c["value"] < c["threshold"]
        assert (c["expected"] == "pass") == met, c["id"]


def test_the_manifest_pins_the_set(cases: list[dict[str, Any]]) -> None:
    """The set is regenerated, not committed: the manifest's hash says it is the set that was measured."""
    man = json.loads((ROOT / "eval" / "accuracy" / "MANIFEST.json").read_text("utf-8"))
    assert man["seed"] == acc.SEED and man["per_class"] == acc.PER_CLASS
    assert acc.set_hash(cases) == man["sha256"] and acc.counts(cases) == man["counts"]
    data = yaml.safe_load((ROOT / "eval" / "DATASETS.yaml").read_text("utf-8"))["datasets"]
    assert data["accuracy"]["data_class"] == "D0" and data["accuracy"]["kind"] == "synthetic"


# ------------------------------------------------------------------------------------------------- the scorer
def _case(cid: str, kind: str, expected: str, lang: str = "en", stratum: str = "plain") -> dict[str, Any]:
    return {"id": cid, "language": lang, "stratum": stratum, "kind": kind, "type": "t", "expected": expected}


def _ans(verdict: str, conf: float = 0.9) -> dict[str, Any]:
    return {"verdict": verdict, "confidence": conf}


def test_wrong_exclusions_are_counted_for_both_kinds_and_an_unknown_is_none() -> None:
    cs = [
        _case("a", "exclusion", "fail"),  # "met" on an exclusion not met: excludes wrongly
        _case("b", "inclusion", "pass"),  # "not met" on an inclusion met: excludes wrongly
        _case("c", "exclusion", "unknown"),  # family history: unknown is gold, a "met" excludes wrongly
        _case("d", "exclusion", "fail"),  # unknown answered: review, no exclusion
        _case("e", "exclusion", "pass"),  # a gold exclusion missed
    ]
    ans = {"a": _ans("pass"), "b": _ans("fail"), "c": _ans("pass"), "d": _ans("unknown", 0.0), "e": _ans("fail")}
    m = acc.score(cs, {"judge": ans})["models"]["judge"]["all"]
    assert m["wrong_exclusions"] == 3 and m["non_exclusions"] == 4
    assert m["missed_exclusions"] == 1 and m["exclusions"] == 1
    assert m["wrong_exclusion_upper95"] == pytest.approx(acc.exact_upper(3, 4))


def test_the_exact_upper_bound() -> None:
    assert acc.exact_upper(0, 464) == pytest.approx(1 - 0.05 ** (1 / 464))  # the 0.65 % of the deep review
    assert acc.exact_upper(0, 0) == 1.0 and acc.exact_upper(5, 5) == 1.0
    bounds = [acc.exact_upper(k, 79) for k in range(6)]
    assert bounds == sorted(bounds) and all(k / 79 < b for k, b in enumerate(bounds))


def test_results_are_given_per_language_and_stratum_with_an_interval() -> None:
    cs = [_case("a", "exclusion", "pass", "ja", "era"), _case("b", "exclusion", "fail", "ja", "era")]
    rep = acc.score(cs, {"judge": {"a": _ans("pass"), "b": _ans("pass")}})
    cell = rep["models"]["judge"]["by"]["ja"]["era"]
    assert cell["n"] == 2 and cell["correct"] == 1
    lo, hi = cell["accuracy_ci95"]
    assert lo < 0.5 < hi
    assert rep["models"]["judge"]["by"]["ja"]["all"]["n"] == 2


def test_a_missing_answer_is_an_error_not_a_right_one() -> None:
    cs = [_case("a", "exclusion", "unknown")]
    m = acc.score(cs, {"judge": {}})["models"]["judge"]["all"]
    assert m["correct"] == 0 and m["errors"] == 1


def test_the_confidence_table_has_ten_bins_per_language() -> None:
    cs = [_case("a", "exclusion", "pass"), _case("b", "exclusion", "fail"), _case("c", "exclusion", "pass")]
    ans = {"a": _ans("pass", 0.95), "b": _ans("pass", 0.97), "c": _ans("unknown", 0.0)}
    cal = acc.score(cs, {"judge": ans})["models"]["judge"]["calibration"]["en"]
    assert len(cal["bins"]) == 10
    top = cal["bins"][9]
    assert top["n"] == 2 and top["accuracy"] == 0.5 and top["confidence"] == pytest.approx(0.96)
    assert sum(b["n"] for b in cal["bins"]) == 2  # an unknown answer has no confidence to calibrate
    assert cal["ece"] == pytest.approx(0.46)


def test_a_floor_turns_less_sure_answers_into_unknowns() -> None:
    cs = [_case("a", "exclusion", "pass"), _case("b", "exclusion", "fail")]
    ans = {"a": _ans("pass", 0.95), "b": _ans("pass", 0.6)}
    floors = {f["floor"]: f for f in acc.score(cs, {"judge": ans})["models"]["judge"]["floors"]["en"]}
    assert floors[0.5]["decided"] == 2 and floors[0.5]["wrong"] == 1
    assert floors[0.9]["decided"] == 1 and floors[0.9]["wrong"] == 0 and floors[0.9]["unknown_rate"] == 0.5


def test_the_pair_decides_only_when_both_models_agree() -> None:
    cs = [_case("a", "exclusion", "fail"), _case("b", "exclusion", "pass")]
    judge = {"a": _ans("pass"), "b": _ans("pass")}
    verifier = {"a": _ans("fail"), "b": _ans("pass")}
    rep = acc.score(cs, {"judge": judge, "verifier": verifier})
    pair = rep["pair"]["all"]
    assert pair["wrong_exclusions"] == 0 and pair["correct"] == 1 and pair["unknown"] == 1
    assert rep["models"]["judge"]["all"]["wrong_exclusions"] == 1


# ------------------------------------------------------------------------------------------------- the runner
class Fake:
    """The canary's client shape: ``chat_json(prompt, variables, job_id=...)`` returning ``.data``."""

    def __init__(self, data: dict[str, Any] | None, fail: bool = False) -> None:
        self.data, self.fail = data, fail
        self.calls: list[tuple[str, list[str], Any]] = []

    def chat_json(self, prompt: str, variables: dict[str, Any], **kw: Any) -> Any:
        from tb_common.llm import LlmError

        self.calls.append((prompt, sorted(variables), kw.get("job_id")))
        if self.fail:
            raise LlmError("gateway refused", "upstream_down")
        return type("R", (), {"data": self.data, "model": "m"})()


def test_the_runner_keeps_the_verdict_and_the_confidence_through_the_canarys_parser(
    cases: list[dict[str, Any]],
) -> None:
    c = next(c for c in cases if c["expected"] == "pass")
    fake = Fake({"verdict": "pass", "confidence": 0.8, "quote": c["evidence"], "reason": "r"})
    got = acc.run_model(fake, [c])
    assert got[c["id"]]["verdict"] == "pass" and got[c["id"]]["confidence"] == 0.8
    assert fake.calls == [("judge", ["criterion_text", "excerpts", "index_date", "note_question"], "accuracy")]
    # a quote the excerpts do not hold is unknown, as in the product (SPEC §7.3)
    bad = acc.run_model(Fake({"verdict": "pass", "confidence": 0.8, "quote": "not in any note"}), [c])
    assert bad[c["id"]]["verdict"] == "unknown"


def test_a_refused_call_is_an_error_in_the_answers() -> None:
    c = {"id": "x", "criterion_text": "t", "note_question": "q", "index_date": "2026-11-01", "excerpts": []}
    got = acc.run_model(Fake(None, fail=True), [c])
    assert "error" in got["x"] and "verdict" not in got["x"]
