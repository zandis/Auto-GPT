"""Card 10G-37 (plan 10, track G; lane H; D-1334): sampling weights in the scorer for an audited or actively sampled
set. The weighted estimate is unbiased on a planted population (exact enumeration of every draw), and the interval
covers the frame's rate at least 95 % of the time in a seeded simulation over rare strata with small inclusion
probabilities and draws with no event, the cases the integrator's review of PR #1200 named. Each finding of that
review has its test here.

Synthetic data only: planted populations and made-up chart ids, no patient."""

from __future__ import annotations

import itertools
import json
import random
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import replay, score, weights

pytestmark = pytest.mark.nodb


def _design(frames: dict[str, int], drawn: dict[str, int], langs: dict[str, str] | None = None) -> weights.Design:
    return weights.Design("pair", dict(frames), dict(langs or {}), dict(drawn))


def _units(sample: dict[str, list[int]]) -> list[tuple[str, bool, bool]]:
    """Every drawn row in the domain; 1 is an event."""
    return [(h, True, bool(y)) for h, ys in sample.items() for y in ys]


def _block(frame: dict[str, list[int]], sample_idx: dict[str, list[int]]) -> dict[str, Any]:
    sample = {h: [frame[h][i] for i in idx] for h, idx in sample_idx.items()}
    return weights.estimate(
        _units(sample), _design({h: len(v) for h, v in frame.items()}, {h: len(i) for h, i in sample_idx.items()})
    )


# ---------------------------------------------------------------- the card's test: unbiased on a planted population
def test_the_weighted_estimate_is_unbiased_on_a_planted_population_over_every_draw() -> None:
    """Two strata, unequal inclusion (3 of 8 and 2 of 6): the mean of the estimate over all 840 equally likely draws
    is the frame's rate exactly (the domain here is the whole frame, so the estimate is a total over a known N)."""
    frame = {"a": [1, 0, 0, 1, 0, 0, 0, 0], "b": [1, 1, 0, 1, 0, 1]}
    truth = Fraction(sum(map(sum, frame.values())), sum(map(len, frame.values())))
    draws = list(itertools.product(itertools.combinations(range(8), 3), itertools.combinations(range(6), 2)))
    assert len(draws) == 840
    total = Fraction(0)
    for ia, ib in draws:
        sample = {"a": [frame["a"][i] for i in ia], "b": [frame["b"][i] for i in ib]}
        y = sum((Fraction(len(frame[h]) * sum(ys), len(ys)) for h, ys in sample.items()), Fraction(0))  # weighted
        b = weights.estimate(_units(sample), _design({"a": 8, "b": 6}, {"a": 3, "b": 2}))
        assert b["estimated_events"] == round(float(y), 4)
        total += y / 14
    assert total / len(draws) == truth
    # and the unweighted share of the sample is biased here: the rare-heavy stratum b is over-drawn
    naive = sum(Fraction(sum(frame["a"][i] for i in ia) + sum(frame["b"][i] for i in ib), 5) for ia, ib in draws)
    assert naive / len(draws) != truth


def test_the_weighted_totals_of_a_domain_rate_are_unbiased_over_every_draw() -> None:
    """A domain rate (events among a domain read from the answers): both weighted totals are unbiased."""
    # (in the domain, an event) per unit; stratum a 7 units draw 3, b 5 units draw 2
    frame = {
        "a": [(1, 1), (1, 0), (0, 0), (1, 0), (0, 0), (1, 1), (0, 0)],
        "b": [(1, 1), (0, 0), (1, 1), (1, 0), (0, 0)],
    }
    draws = list(itertools.product(itertools.combinations(range(7), 3), itertools.combinations(range(5), 2)))
    ys = xs = Fraction(0)
    for ia, ib in draws:
        units = [("a", bool(frame["a"][i][0]), bool(frame["a"][i][1])) for i in ia]
        units += [("b", bool(frame["b"][i][0]), bool(frame["b"][i][1])) for i in ib]
        d = _design({"a": 7, "b": 5}, {"a": 3, "b": 2})
        totals = weights.weighted_totals(units, d)
        assert totals is not None
        b = weights.estimate(units, d)
        assert (b["estimated_events"], b["estimated_in_domain"]) == (
            round(float(totals[0]), 4),
            round(float(totals[1]), 4),
        )
        ys, xs = ys + totals[0], xs + totals[1]
    true_y = sum(e for v in frame.values() for d, e in v if d)
    true_x = sum(d for v in frame.values() for d, _ in v)
    assert ys / len(draws) == true_y and xs / len(draws) == true_x


# ---------------------------------------------------------------- coverage by a seeded simulation
def _bernoulli(rng: random.Random, frame: dict[str, list[int]], pi: dict[str, float]) -> dict[str, list[int]]:
    return {h: [i for i in range(len(v)) if rng.random() < pi[h]] for h, v in frame.items()}


def _srs(rng: random.Random, frame: dict[str, list[int]], n: dict[str, int]) -> dict[str, list[int]]:
    return {h: sorted(rng.sample(range(len(v)), n[h])) for h, v in frame.items()}


CASES = [
    # the integrator's case at 16:03: 90 certainty non-events, 10 events each included at 0.02
    (
        "review-2: 90 sure non-events, 10 events at 0.02",
        {"sure": [0] * 90, "rare": [1] * 10},
        ("bernoulli", {"sure": 1.0, "rare": 0.02}),
    ),
    # the first review's case: 990 certainty non-events, 10 events at 0.01
    (
        "review-1: 990 sure non-events, 10 events at 0.01",
        {"sure": [0] * 990, "rare": [1] * 10},
        ("bernoulli", {"sure": 1.0, "rare": 0.01}),
    ),
    # a rare stratum sampled, not certain, beside a large common stratum sampled lightly: zero-event draws are common
    (
        "rare 5 of 40 at 0.05, common 2 % events at 0.1",
        {"rare": [1] * 5 + [0] * 35, "common": [1] * 8 + [0] * 392},
        ("bernoulli", {"rare": 0.05, "common": 0.1}),
    ),
    # fixed-size draws, unequal: one event in a stratum of 200 drawn 4, rate small everywhere
    (
        "srs: 1 event in 200 (draw 4), 3 in 60 (draw 20)",
        {"x": [1] + [0] * 199, "y": [1] * 3 + [0] * 57},
        ("srs", {"x": 4, "y": 20}),
    ),
    # three strata, one with no draw at all in most samples
    (
        "three strata, one at 0.03",
        {"a": [1] * 2 + [0] * 48, "b": [1] * 6 + [0] * 14, "c": [1] * 1 + [0] * 29},
        ("bernoulli", {"a": 0.2, "b": 0.5, "c": 0.03}),
    ),
]


@pytest.mark.parametrize("name,frame,draw", CASES, ids=[c[0] for c in CASES])
def test_the_interval_covers_the_frame_rate_in_a_seeded_simulation(
    name: str, frame: dict[str, list[int]], draw: tuple[str, dict[str, Any]]
) -> None:
    rng = random.Random(1037)
    truth = sum(map(sum, frame.values())) / sum(map(len, frame.values()))
    reps, covered, no_event = 1000, 0, 0
    for _ in range(reps):
        idx = _bernoulli(rng, frame, draw[1]) if draw[0] == "bernoulli" else _srs(rng, frame, draw[1])
        b = _block(frame, idx)
        no_event += b["k"] == 0
        covered += b["ci95"][0] <= truth <= b["ci95"][1]
    assert no_event > 0, "the case must include draws with no event"
    assert covered / reps >= 0.95, f"{name}: covered {covered} of {reps}"


def test_the_review_case_a_draw_with_no_rare_event_is_not_given_a_narrow_interval() -> None:
    """At 16:03 the old scorer gave [0, 0.0402] here; the frame's rate is 0.1."""
    b = _block({"sure": [0] * 90, "rare": [1] * 10}, {"sure": list(range(90)), "rare": []})
    assert b["ci95"] == [0.0, 0.1] and b["rate"] is None and b["undrawn_strata"] == ["rare"]
    assert "no row was drawn from rare" in b["rate_not_estimated_because"]
    one = _block({"sure": [0] * 90, "rare": [1] * 10}, {"sure": list(range(90)), "rare": [3]})
    assert one["rate"] == 0.1 and one["ci95"][0] <= 0.1 <= one["ci95"][1]


def test_hypergeometric_bounds_are_exact_at_the_ends() -> None:
    assert weights.hypergeometric_bounds(0, 0, 10, 0.025) == (0, 10)
    assert weights.hypergeometric_bounds(3, 10, 10, 0.025) == (3, 3)
    lo, hi = weights.hypergeometric_bounds(0, 1, 10, 0.0125)
    assert (lo, hi) == (0, 9)  # one non-event drawn: the other nine may all be events
    # a tail is never exceeded: at the reported bounds the observed count is still plausible at that tail
    lo, hi = weights.hypergeometric_bounds(2, 20, 200, 0.025)
    assert weights._tail_ge(2, 20, lo, 200) > 0.025 and weights._tail_le(2, 20, hi, 200) > 0.025
    assert weights._tail_ge(2, 20, lo - 1, 200) <= 0.025 and weights._tail_le(2, 20, hi + 1, 200) <= 0.025


# ---------------------------------------------------------------- the scorer: sets, answers, replay
def _pid(mrn: str) -> str:
    return score.pid_of(mrn)


def _answers(rs: str, tiers: dict[str, str]) -> dict[str, Any]:
    """tier per chart: excluded, listed (a pass) or open (pending_human); a chart not named is not answered."""
    pats = {}
    for mrn, t in tiers.items():
        v = {"excluded": "fail", "listed": "pass", "open": "pending_human"}[t]
        pats[_pid(mrn)] = {"tier": "excluded" if t == "excluded" else "high", "verdicts": [{"id": "c1", "verdict": v}]}
    return {rs: {"screen": "done", "outcome": "screened", "patients": pats,
                 "draft": [{"id": "c1", "kind": "exclusion", "text": "Pregnancy"}]}}  # fmt: skip


def _ids(strata: dict[str, Any], unit: str = "pair", set_: str = "trec2021") -> dict[str, Any]:
    return {"set": set_, "lang": {"S1": "en", "S2": "ja"}, "rulesets": {"t1": "S1", "t2": "S2"},
            "sampling": {"unit": unit, "strata": strata}}  # fmt: skip


def _pairs(n: int, label: str, stratum: str, rs: str = "S1", start: int = 0) -> list[dict[str, Any]]:
    return [{"mrn": f"chart-{rs}-{start + i}", "ruleset": rs, "label": label, "sampling_stratum": stratum}
            for i in range(n)]  # fmt: skip


def _weighted(
    ids: dict[str, Any], pairs: list[dict[str, Any]], answers: dict[str, Any], crits: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    d = weights.read_design(ids, {"pair": pairs, "criterion": crits or []})
    assert d is not None
    return score.score_sampling(d, ids, pairs, crits or [], answers)


def test_a_replay_that_excludes_fewer_pairs_gets_its_own_denominator() -> None:
    """Review 16:03, Medium at score.py:532: 10 gold pairs at probability 1, a replay excluding one eligible pair
    reports 1 of 1 wrong exclusions, never 1 of a stored 10."""
    pairs = _pairs(10, "eligible", "all")
    tiers = {p["mrn"]: ("excluded" if i == 0 else "listed") for i, p in enumerate(pairs)}
    w = _weighted(_ids({"all": 10}), pairs, _answers("S1", tiers))["pairs"]["all"]
    assert (w["wrong_exclusions"]["estimated_events"], w["wrong_exclusions"]["estimated_in_domain"]) == (1.0, 1.0)
    assert w["wrong_exclusions"]["ci95"] == [1.0, 1.0]  # drawn in full: no sampling uncertainty
    assert (w["eligible_lost"]["estimated_events"], w["eligible_lost"]["estimated_in_domain"]) == (1.0, 10.0)


def test_a_replay_that_answers_fewer_criteria_gets_its_own_denominator() -> None:
    """Review 16:03, Medium at score.py:1148: 10 gold criteria at probability 1, a replay answering five and wrongly
    blocking one reports 1 of 5."""
    crits = [{"mrn": f"chart-{i}", "ruleset": "S1", "kind": "exclusion", "label": "not excluded", "text": "Pregnancy",
              "sampling_stratum": "all"} for i in range(10)]  # fmt: skip
    tiers = {f"chart-{i}": ("excluded" if i == 0 else "listed") for i in range(5)}
    w = _weighted(_ids({"all": 10}, unit="criterion"), [], _answers("S1", tiers), crits)["criteria"]
    assert (w["wrong_exclusion"]["estimated_events"], w["wrong_exclusion"]["estimated_in_domain"]) == (1.0, 5.0)
    assert w["wrong_exclusion"]["rate"] == 0.2


def test_the_pathology_figure_of_a_replay_answering_fewer_gets_its_own_denominator() -> None:
    """Review 16:03, Medium at score.py:1356: 10 eligible pairs at probability 1, five answered, one excluded: 1/5.
    And its Low at score.py:1364: the prose says it is the sample, and the frame's figure is beside it."""
    ids = _ids({"all": 12}, set_="tcga")
    pairs = _pairs(10, "eligible", "all") + _pairs(2, "excluded", "all", start=10)
    tiers = {f"chart-S1-{i}": ("excluded" if i == 0 else "listed") for i in range(5)} | {"chart-S1-10": "excluded"}
    w = _weighted(ids, pairs, _answers("S1", tiers))
    el = w["pathology"]["eligible_lost"]
    assert (el["estimated_events"], el["estimated_in_domain"], el["rate"]) == (1.0, 5.0, 0.2)
    assert w["pathology"]["wrong_exclusions"]["rate"] == 0.5
    assert "over a sample of 12 of 12 pairs" in w["pathology_figure"]


def test_the_pathology_prose_is_labelled_as_the_sample(tmp_path: Path) -> None:
    """Review 16:03, Low at score.py:1364: four ineligible pairs drawn from a frame of 20, one excluded. The scorer's
    prose of counts says it is the sample's; the frame's figure (an estimated 5 of 20) is beside it."""
    built = tmp_path / "built"
    (built / "gold").mkdir(parents=True)
    ids = {"set": "tcga", "lang": {"S1": "en"}, "rulesets": {"t1": "S1"},
           "sampling": {"unit": "pair", "strata": {"inel": 20, "el": 1}}}  # fmt: skip
    pairs = [{"mrn": "chart-1", "ruleset": "S1", "label": "excluded", "sampling_stratum": "inel"},
             {"mrn": "chart-2", "ruleset": "S1", "label": "excluded", "sampling_stratum": "inel"},
             {"mrn": "chart-3", "ruleset": "S1", "label": "excluded", "sampling_stratum": "inel"},
             {"mrn": "chart-4", "ruleset": "S1", "label": "excluded", "sampling_stratum": "inel"},
             {"mrn": "chart-5", "ruleset": "S1", "label": "eligible", "sampling_stratum": "el"}]  # fmt: skip
    (built / "gold" / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    (built / "gold" / "pairs.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pairs), encoding="utf-8")
    (built / "gold" / "criteria.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "work").mkdir()
    ans = _answers("S1", {"chart-1": "excluded", "chart-2": "listed", "chart-3": "listed", "chart-4": "listed",
                          "chart-5": "listed"})  # fmt: skip
    (tmp_path / "work" / "answers.json").write_text(json.dumps(ans), encoding="utf-8")
    out = score.score(built, tmp_path / "work")
    assert "the counts of the drawn sample, not of the frame" in out["pathology"]["figure"]
    ie = out["sampling"]["pathology"]["ineligible_excluded"]
    assert (ie["estimated_events"], ie["estimated_in_domain"]) == (5.0, 20.0)
    assert "an estimated 5.0 of 20.0" in out["sampling"]["pathology_figure"]
    fig = replay.pathology_from_run({"tcga": out}, ["tcga"])
    # Medium of the first review (replay.py:516): the headline is the frame's estimate, not the sample's 1/4
    assert (fig["numerator"], fig["denominator"]) == (5.0, 20.0)
    assert fig["within_target"] is False and "estimates the frame" in fig["within_target_because"]


def test_a_declared_frame_with_no_draw_is_kept_and_bounds_the_rate(tmp_path: Path) -> None:
    """Review 16:03, Medium at score.py:1476: an empty pairs.jsonl, an answers.json and a declared frame of 100: the
    report keeps the frame (100 units, nothing drawn) and no rate is estimated."""
    built = tmp_path / "built"
    (built / "gold").mkdir(parents=True)
    ids = _ids({"en": {"frame": 100, "lang": "en"}})
    (built / "gold" / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    (built / "gold" / "pairs.jsonl").write_text("", encoding="utf-8")
    (built / "gold" / "criteria.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "answers.json").write_text(json.dumps(_answers("S1", {})), encoding="utf-8")
    out = score.score(built, tmp_path / "work")
    smp = out["sampling"]
    assert smp["design"]["frame"] == 100 and smp["design"]["undrawn_strata"] == ["en"]
    el = smp["pairs"]["all"]["eligible_lost"]
    assert el["rate"] is None and el["frame"] == 100 and el["ci95"] == [0.0, 1.0]
    fig = replay.eligible_figure("trec2021", out)
    assert fig.get("sampling", {}).get("design", {}).get("frame") == 100 or fig.get("weighted", {}).get("frame") == 100
    assert replay.figure("a", "v1", [fig])["within_target"] is False


def test_an_undrawn_language_stratum_stays_in_the_pooled_frame() -> None:
    """First review, Medium at score.py:303: frames of 10 en pairs and 90 ja pairs, one en wrong exclusion drawn,
    no ja draw: the pooled figure is not 2 of 10; it is not estimated, and its bound reaches the ja pairs."""
    ids = _ids({"en": {"frame": 10, "lang": "en"}, "ja": {"frame": 90, "lang": "ja"}})
    pairs = _pairs(5, "eligible", "en")
    tiers = {p["mrn"]: ("excluded" if i == 0 else "listed") for i, p in enumerate(pairs)}
    w = _weighted(ids, pairs, _answers("S1", tiers))["pairs"]
    assert w["en"]["eligible_lost"]["rate"] == 0.2 and w["en"]["eligible_lost"]["frame"] == 10
    pooled = w["all"]["eligible_lost"]
    assert pooled["rate"] is None and pooled["frame"] == 100 and pooled["undrawn_strata"] == ["ja"]
    assert pooled["ci95"][1] > 0.9  # the 90 undrawn ja pairs may all be eligible and excluded
    assert w["ja"]["eligible_lost"]["rate"] is None and w["ja"]["eligible_lost"]["ci95"] == [0.0, 1.0]


def test_zero_in_the_sample_is_not_within_the_target_unless_the_frame_is_shown_empty(tmp_path: Path) -> None:
    """First review, High at replay.py:454: one pair drawn, correctly listed, from a frame of 100 holding a wrong
    exclusion the draw missed: the point estimate is 0, the target is not met. Drawn in full, it is."""
    for drawn, frame, within in ((1, 100, False), (10, 10, True)):
        pairs = _pairs(drawn, "eligible", "all")
        sc = {"set": "trec2021", "gold_kind": None,
              "pairs": score.score_pairs(_ids({"all": frame}), pairs, _answers("S1", {p["mrn"]: "listed" for p in pairs})),
              "sampling": _weighted(_ids({"all": frame}), pairs, _answers("S1", {p["mrn"]: "listed" for p in pairs}))}  # fmt: skip
        fig = replay.eligible_figure("trec2021", sc)
        assert fig["numerator"] == 0.0 and fig["sample"] == {"numerator": 0, "denominator": drawn}
        f = replay.figure("a", "v1", [fig])
        assert f["within_target"] is within, (drawn, frame)
        assert f["sampled_sets"] == ["trec2021"]


def test_a_figure_with_an_unknown_estimate_renders_and_pools_as_unknown() -> None:
    """Review 16:03, Low at replay.py:371: a weighted block with no estimate does not crash the replay; the pooled
    count is unknown (None), never a smaller number."""
    ids = _ids({"a": {"frame": 10, "lang": "en"}, "b": {"frame": 5, "lang": "en"}})
    pairs = _pairs(2, "eligible", "a")
    sc = {"set": "trec2021", "sampling": _weighted(ids, pairs, _answers("S1", {pairs[0]["mrn"]: "excluded"}))}
    fig = replay.eligible_figure("trec2021", sc)
    assert fig["numerator"] is None and fig["weighted"]["undrawn_strata"] == ["b"]
    plain = {"set": "x", "gold_kind": None, "scored": True, "numerator": 0, "denominator": 3}
    f = replay.figure("a", "v1", [plain, fig])
    assert f["numerator"] is None and f["within_target"] is False
    assert replay._per_set(fig).startswith("trec2021 est. n/a/n/a (95 % ")
    assert replay._n(None) == "n/a" and replay._n(2.5) == "2.5" and replay._n(3) == "3"


def test_a_tiny_inclusion_probability_neither_overflows_nor_aborts() -> None:
    """Review 16:03, Low at score.py:138, and the first review's Low at score.py:145: two events drawn from a frame
    of ten million (weights of five million) are scored, and a frame beyond what the scorer computes exactly is
    refused with the reason instead of aborting."""
    d = _design({"h": 10**7}, {"h": 2})
    b = weights.estimate([("h", True, True), ("h", True, True)], d)
    assert b["estimated_events"] == 10**7 and b["rate"] == 1.0 and 0.0 < b["ci95"][0] < 1.0 and b["ci95"][1] == 1.0
    why = weights.read_design({"sampling": {"unit": "pair", "strata": {"h": 10**8}}}, {"pair": []})
    assert isinstance(why, str) and "larger than this scorer computes exactly" in why


@pytest.mark.parametrize(
    "strata,row,needle",
    [
        ({"h": True}, "h", "positive integer"),  # first review, Medium at score.py:311: a boolean is not 1
        ({"h": 0}, "h", "positive integer"),
        ({"h": 2.0}, "h", "positive integer"),
        ({"h": 5}, None, "is not a declared stratum"),
        ({"h": 5}, "g", "is not a declared stratum"),
        ({"h": 1}, "h", "rows drawn from a frame of 1"),
    ],
)
def test_a_declaration_that_does_not_hold_is_refused_with_its_reason(
    strata: dict[str, Any], row: Any, needle: str
) -> None:
    rows = [{"mrn": f"c{i}", "ruleset": "S1", "label": "eligible", **({} if row is None else {"sampling_stratum": row})}
            for i in range(2)]  # fmt: skip
    why = weights.read_design({"sampling": {"unit": "pair", "strata": strata}}, {"pair": rows})
    assert isinstance(why, str) and needle in why
    sc = {"set": "trec2021", "sampling": score.score_sampling(why, {}, rows, [], {})}
    fig = replay.eligible_figure("trec2021", sc)
    assert fig["scored"] is False and fig["why"].startswith("sampling: ")


def test_a_set_that_declares_no_draw_is_scored_as_before(tmp_path: Path) -> None:
    """No ``sampling`` in ids.json: no sampling block, and the figure is the unweighted one, the same as before."""
    assert weights.read_design({"set": "x"}, {"pair": [{"mrn": "c"}]}) is None
    pairs = [{"mrn": "c1", "ruleset": "S1", "label": "eligible"}, {"mrn": "c2", "ruleset": "S1", "label": "eligible"}]
    ids = {"set": "trec2021", "lang": {"S1": "en"}, "rulesets": {"t1": "S1"}}
    sc = {"set": "trec2021", "pairs": score.score_pairs(ids, pairs, _answers("S1", {"c1": "excluded", "c2": "listed"}))}
    fig = replay.eligible_figure("trec2021", sc)
    assert (fig["numerator"], fig["denominator"]) == (1, 2) and "weighted" not in fig
    assert replay.figure("a", "v1", [fig])["numerator"] == 1
