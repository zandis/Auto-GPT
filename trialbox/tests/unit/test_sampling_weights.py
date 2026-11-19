"""Card 10G-37: an audited or actively sampled set is scored by inverse-probability weights.

The estimate of a 0/1 share is the Horvitz–Thompson mean over the frame named in ``ids.json``. Its interval
uses the Kish size of those weights (Korn–Graubard), widened by the Poisson-sampling variance when that draw is
not a fixed-size equal-probability sample. A set that records no inclusion probability is unchanged, byte for byte.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from tools.public_accuracy import replay, score

pytestmark = [pytest.mark.nodb]

_UNWEIGHTED_KEYS = ("k", "n", "rate", "ci95")
_UNWEIGHTED_REPORT = Path(__file__).with_name("fixtures") / "unweighted_pair_score.json"
_PAIR_RATE_NAMES = ("eligible_lost", "wrong_exclusions", "unanswered", "left_open")


def test_the_weighted_mean_is_unbiased_on_a_planted_population() -> None:
    """Every subset of a frame of 2, included independently. The event is the unit with the smaller probability:
    an estimator that reuses the largest sampled probability returns about 0.5556 on the draw of both units, not
    the Horvitz–Thompson value 2.5, and its expectation is not the frame's share. The weighted mean's is."""
    outcomes = [1, 0]
    pi = [0.2, 0.9]
    population = 2
    truth = sum(outcomes) / population
    # both units drawn: y/π uses 0.2 for the event, not the other unit's 0.9
    assert score.ht_mean([1, 0], [0.2, 0.9], 2) == 2.5
    weighted = 0.0
    sample_mean = 0.0
    for mask in range(1 << population):
        prob = 1.0
        drawn_y: list[int] = []
        drawn_pi: list[float] = []
        for i in range(population):
            drawn = bool(mask & (1 << i))
            prob *= pi[i] if drawn else 1.0 - pi[i]
            if drawn:
                drawn_y.append(outcomes[i])
                drawn_pi.append(pi[i])
        weighted += prob * score.ht_mean(drawn_y, drawn_pi, population)
        if drawn_y:
            sample_mean += prob * (sum(drawn_y) / len(drawn_y))
    assert abs(weighted - truth) < 1e-12
    assert abs(sample_mean - truth) > 0.3


def test_equal_probabilities_match_the_sample_interval_and_a_census_is_a_point() -> None:
    # simple random sample of 4 from 16, one event: the weighted share is k/n and the interval is Clopper–Pearson
    srs = score.weighted_rate([1, 0, 0, 0], [0.25, 0.25, 0.25, 0.25], 16)
    assert srs["rate"] == 0.25 and srs["k"] == 1 and srs["n"] == 4
    assert srs["ci95"] == list(score.clopper_pearson(1, 4))
    assert srs["estimated_events"] == 4.0 and srs["population"] == 16
    # the whole frame, every probability 1: nothing was left out, so the interval is the point
    census = score.weighted_rate([1, 0, 1], [1, 1, 1], 3)
    assert census["rate"] == 0.6667 and census["ci95"] == [0.6667, 0.6667]
    # unequal weights on five non-events: the effective size is below 5, so the upper bound is wider
    rare = score.weighted_rate([0, 0, 0, 0, 0], [0.5, 0.5, 0.5, 0.5, 0.05], 20)
    assert rare["effective_n"] == 1.8846 and rare["rate"] == 0.0
    assert rare["ci95"] == [0.0, 0.8588]
    assert rare["ci95"][1] > score.clopper_pearson(0, 5)[1]
    # a draw can estimate more events than the frame; the point is not clipped, the interval stays in [0, 1]
    over = score.weighted_rate([1], [0.1], 2)
    assert over["rate"] == 5.0 and over["ci95"][1] == 1.0 and over["ci95"][0] >= 0.0


def test_one_draw_from_an_independent_sample_does_not_exclude_the_frame() -> None:
    """100 event rows, each included independently at 0.02. Exactly one row is drawn about 27% of the time.
    The Horvitz–Thompson share on that draw is 0.5; a 95% interval that stops at 0.9996 leaves out the true share 1."""
    got = score.weighted_rate([1], [0.02], 100)
    assert got["rate"] == 0.5 and got["population"] == 100
    assert got["ci95"][0] <= 1.0 <= got["ci95"][1]


def test_a_tiny_inclusion_probability_does_not_abort_the_report() -> None:
    """Squaring 1/π must not overflow into a non-finite Kish size and a beta error."""
    got = score.weighted_rate([1], [1e-200], 100)
    assert math.isfinite(got["effective_n"])
    assert all(math.isfinite(bound) for bound in got["ci95"])
    assert 0.0 <= got["ci95"][0] <= got["ci95"][1] <= 1.0


def test_a_bad_weight_is_refused() -> None:
    with pytest.raises(ValueError):
        score.ht_mean([True], [1.0], 1)  # a bool is not an outcome
    with pytest.raises(ValueError):
        score.ht_mean([1], [True], 1)  # a bool is not a probability
    assert score.ht_mean([1], [1], 1) == 1.0  # the integer 1 is a probability of 1
    with pytest.raises(ValueError):
        score.ht_mean([1], [0.0], 1)
    with pytest.raises(ValueError):
        score.ht_mean([1, 0], [0.5], 2)


def _screen(mrn: str, tier: str, verdict: str) -> dict[str, Any]:
    return {"tier": tier, "verdicts": [{"id": "C1", "verdict": verdict}]}


def _answers(rulesets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        rs: {"screen": "done", "draft": [{"id": "C1", "kind": "exclusion", "class": "note", "text": "Pregnancy"}],
             "patients": patients}
        for rs, patients in rulesets.items()
    }


def _write(tmp_path: Path, pairs: list[dict[str, Any]], answers: dict[str, Any], frames: dict[str, Any] | None,
           *, rulesets: dict[str, str] | None = None, lang: dict[str, str] | None = None,
           crits: list[dict[str, Any]] | None = None) -> tuple[Path, Path]:
    built = tmp_path / "built"
    gold = built / "gold"
    gold.mkdir(parents=True)
    rs = rulesets or {"SYN-1": "SYN-1"}
    ids: dict[str, Any] = {"set": "planted", "rulesets": rs, "lang": lang or {v: "en" for v in rs.values()}}
    if frames is not None:
        ids["sampling"] = {"frames": frames}
    (gold / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    (gold / "pairs.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pairs), encoding="utf-8")
    (gold / "criteria.jsonl").write_text("".join(json.dumps(c) + "\n" for c in (crits or [])), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    return built, work


_PAIR_FRAMES = {
    "eligible_lost": 10,
    "wrong_exclusions": 4,
    "unanswered": 10,
    "left_open": 10,
}


def _two_eligible(probabilities: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One eligible patient excluded at probability 0.5, one listed at probability 1, both answered."""
    pairs = [
        {"mrn": "71000001", "ruleset": "SYN-1", "label": "eligible"},
        {"mrn": "71000002", "ruleset": "SYN-1", "label": "eligible"},
    ]
    if probabilities:
        pairs[0]["inclusion_probability"] = 0.5
        pairs[1]["inclusion_probability"] = 1.0
    answers = _answers({
        "SYN-1": {
            score.pid_of("71000001"): _screen("71000001", "excluded", "fail"),
            score.pid_of("71000002"): _screen("71000002", "review", "pass"),
        }
    })
    return pairs, answers


def test_the_scorer_weights_a_sampled_set_and_leaves_an_unweighted_set_unchanged(tmp_path: Path) -> None:
    pairs, answers = _two_eligible(True)
    built, work = _write(tmp_path / "w", pairs, answers, _PAIR_FRAMES)
    report = score.score(built, work)
    lost = report["pairs"]["summary"]["en"]["eligible_lost"]
    # unweighted this is 1/2 = 0.5; the frame mean is (1/10) * (1/0.5) = 0.2
    assert lost["k"] == 1 and lost["n"] == 2 and lost["rate"] == 0.2
    assert lost["population"] == 10 and lost["estimated_events"] == 2.0
    assert lost["weighted"] is True and lost["effective_n"] == 1.8 and lost["method"] == "horvitz-thompson"
    assert lost["ci95"] == [0.0, 0.9406]
    wrong = report["pairs"]["summary"]["en"]["wrong_exclusions"]
    assert wrong["k"] == 1 and wrong["n"] == 1 and wrong["rate"] == 0.5 and wrong["population"] == 4
    assert report["pairs"]["summary"]["en"]["excluded_caught"] == score.rate(0, 0)  # no excluded-label pair
    assert report["schema_version"] == 5

    bare, bare_work = _write(tmp_path / "u", *_two_eligible(False), None)
    plain = score.score(bare, bare_work)
    en = plain["pairs"]["summary"]["en"]
    assert en["eligible_lost"] == score.rate(1, 2)
    assert en["wrong_exclusions"] == score.rate(1, 1)
    assert list(en["eligible_lost"]) == list(_UNWEIGHTED_KEYS)
    assert json.dumps(en["eligible_lost"], sort_keys=True) == json.dumps(score.rate(1, 2), sort_keys=True)
    assert "weighted" not in json.dumps(plain)
    assert plain["schema_version"] == 5
    # the whole report, not one rate block: a changed top-level phrase would still pass the asserts above
    blob = json.dumps(plain, sort_keys=True, separators=(",", ":"))
    assert blob == _UNWEIGHTED_REPORT.read_text(encoding="utf-8").rstrip("\n")
    assert plain["what"] == "joined by ids after the run; the gold was not in the box"


def test_a_boolean_inclusion_probability_is_not_a_census() -> None:
    """``true`` must not become 1.0 and earn the point interval of a frame that was included in full."""
    names = ("eligible_lost", "wrong_exclusions", "unanswered", "left_open", "excluded_caught")
    ids = {"lang": {"SYN-1": "en"}, "rulesets": {"SYN-1": "SYN-1"},
           "sampling": {"frames": {n: 1 for n in names}}}
    pairs = [{"mrn": "71000001", "ruleset": "SYN-1", "label": "eligible", "inclusion_probability": True}]
    answers = _answers({"SYN-1": {score.pid_of("71000001"): _screen("71000001", "excluded", "fail")}})
    with pytest.raises(ValueError, match="inclusion probability"):
        score.score_pairs(ids, pairs, answers)


def test_a_rescreen_uses_the_answered_frame_not_the_stored_one(tmp_path: Path) -> None:
    """The stored frame is 10 because that run answered 10 eligible pairs. This run answers 5. Two exclusions
    at probability 0.5 are 4 estimated events: the answered-frame figure is 4/5, not 4/10."""
    pairs = []
    patients: dict[str, Any] = {}
    for i in range(1, 11):
        mrn = f"710000{i:02d}"
        pairs.append({"mrn": mrn, "ruleset": "SYN-1", "label": "eligible", "inclusion_probability": 0.5})
        if i <= 5:
            tier, verdict = ("excluded", "fail") if i <= 2 else ("review", "pass")
            patients[score.pid_of(mrn)] = _screen(mrn, tier, verdict)
    frames = {n: 10 for n in _PAIR_RATE_NAMES}
    built, work = _write(tmp_path, pairs, _answers({"SYN-1": patients}), frames)
    lost = score.score(built, work)["pairs"]["summary"]["en"]["eligible_lost"]
    assert (lost["k"], lost["n"]) == (2, 5)
    assert lost["estimated_events"] == 4.0 and lost["population"] == 5
    fig = replay.eligible_figure("planted", score.score(built, work))
    assert (fig["numerator"], fig["denominator"]) == (4.0, 5.0)


def test_a_language_that_draws_nothing_keeps_its_frame(tmp_path: Path) -> None:
    """Eligible-loss frames of 10 English and 90 Japanese. One English exclusion at 0.5 and no Japanese draw
    is 2 events over 100, not 2 over the English frame alone."""
    pairs = [{"mrn": "71000001", "ruleset": "EN", "label": "eligible", "inclusion_probability": 0.5}]
    answers = _answers({"EN": {score.pid_of("71000001"): _screen("71000001", "excluded", "fail")}})
    frames = {n: {"en": 10, "ja": 90} for n in _PAIR_RATE_NAMES}
    built, work = _write(
        tmp_path, pairs, answers, frames, rulesets={"EN": "EN", "JA": "JA"}, lang={"EN": "en", "JA": "ja"}
    )
    fig = replay.eligible_figure("planted", score.score(built, work))
    assert (fig["numerator"], fig["denominator"]) == (2.0, 100.0)


def test_an_unweighted_language_keeps_its_declared_frame(tmp_path: Path) -> None:
    """English estimates 2 events over a frame of 10. Japanese has one unweighted non-event and a frame of 90.
    The pool is 2/100. Using the Japanese sample count (1) as its frame publishes 2/11."""
    pairs = [
        {"mrn": "71000001", "ruleset": "EN", "label": "eligible", "inclusion_probability": 0.5},
        {"mrn": "71000002", "ruleset": "JA", "label": "eligible"},
    ]
    answers = _answers({
        "EN": {score.pid_of("71000001"): _screen("71000001", "excluded", "fail")},
        "JA": {score.pid_of("71000002"): _screen("71000002", "review", "pass")},
    })
    frames = {n: {"en": 10, "ja": 90} for n in _PAIR_RATE_NAMES}
    built, work = _write(
        tmp_path, pairs, answers, frames, rulesets={"EN": "EN", "JA": "JA"}, lang={"EN": "en", "JA": "ja"}
    )
    fig = replay.eligible_figure("planted", score.score(built, work))
    assert (fig["numerator"], fig["denominator"]) == (2.0, 100.0)


def test_an_unweighted_event_in_a_declared_frame_is_refused(tmp_path: Path) -> None:
    """An event with no inclusion probability cannot be read as one event, nor as a census of a larger frame."""
    pairs = [
        {"mrn": "71000001", "ruleset": "EN", "label": "eligible", "inclusion_probability": 0.5},
        {"mrn": "71000002", "ruleset": "JA", "label": "eligible"},
    ]
    answers = _answers({
        "EN": {score.pid_of("71000001"): _screen("71000001", "excluded", "fail")},
        "JA": {score.pid_of("71000002"): _screen("71000002", "excluded", "fail")},
    })
    frames = {n: {"en": 10, "ja": 90} for n in _PAIR_RATE_NAMES}
    built, work = _write(
        tmp_path, pairs, answers, frames, rulesets={"EN": "EN", "JA": "JA"}, lang={"EN": "en", "JA": "ja"}
    )
    with pytest.raises(ValueError, match="inclusion probability"):
        score.score(built, work)


def test_a_sampled_rate_without_its_frame_or_with_a_mixed_probability_is_refused(tmp_path: Path) -> None:
    pairs, answers = _two_eligible(True)
    built, work = _write(tmp_path / "missing", pairs, answers, {})
    with pytest.raises(ValueError, match=r"eligible_lost: inclusion probabilities need the frame size"):
        score.score(built, work)
    mixed = [dict(pairs[0]), {"mrn": "71000002", "ruleset": "SYN-1", "label": "eligible"}]
    built_m, work_m = _write(tmp_path / "mixed", mixed, answers, _PAIR_FRAMES)
    with pytest.raises(ValueError, match=r"eligible_lost: an inclusion probability on 1 of 2"):
        score.score(built_m, work_m)


def test_two_languages_need_a_frame_each() -> None:
    pairs = [
        {"mrn": "71000001", "ruleset": "EN", "label": "eligible", "inclusion_probability": 0.5},
        {"mrn": "71000002", "ruleset": "JA", "label": "eligible", "inclusion_probability": 1.0},
    ]
    answers = _answers({
        "EN": {score.pid_of("71000001"): _screen("71000001", "excluded", "fail")},
        "JA": {score.pid_of("71000002"): _screen("71000002", "review", "pass")},
    })
    ids = {"lang": {"EN": "en", "JA": "ja"}, "rulesets": {"EN": "EN", "JA": "JA"}}
    names = ("eligible_lost", "wrong_exclusions", "unanswered", "left_open")
    with pytest.raises(ValueError, match="per language"):
        score.score_pairs({**ids, "sampling": {"frames": {n: 10 for n in names}}}, pairs, answers)
    got = score.score_pairs(
        {**ids, "sampling": {"frames": {n: {"en": 10, "ja": 8} for n in names}}}, pairs, answers
    )
    en, ja = got["summary"]["en"]["eligible_lost"], got["summary"]["ja"]["eligible_lost"]
    assert en["rate"] == 0.2 and en["population"] == 10 and en["k"] == 1 and en["n"] == 1
    assert ja["rate"] == 0.0 and ja["population"] == 8 and ja["n"] == 1 and ja["k"] == 0


def test_a_sampled_criterion_rate_is_the_frame_mean() -> None:
    ids = {"lang": {"SYN-1": "en"}, "rulesets": {"SYN-1": "SYN-1"},
           "sampling": {"frames": {"wrong_exclusion": 10}}}
    crits = [
        {"mrn": "71000001", "ruleset": "SYN-1", "kind": "exclusion", "label": "not excluded",
         "text": "Pregnancy", "inclusion_probability": 0.5},
        {"mrn": "71000002", "ruleset": "SYN-1", "kind": "exclusion", "label": "not excluded",
         "text": "Pregnancy", "inclusion_probability": 1.0},
    ]
    answers = _answers({
        "SYN-1": {
            score.pid_of("71000001"): _screen("71000001", "excluded", "fail"),
            score.pid_of("71000002"): _screen("71000002", "review", "pass"),
        }
    })
    got = score.score_criteria(ids, crits, answers)
    w = got["wrong_exclusion"]
    assert w["rate"] == 0.2 and w["k"] == 1 and w["n"] == 2 and w["ci95"] == [0.0, 0.9406]
    assert w["population"] == 10 and w["estimated_events"] == 2.0
    assert got["caught"] == score.rate(0, 0)


def test_the_pathology_figure_is_the_frame_mean() -> None:
    ids = {
        "rulesets": {"SYN-1": "SYN-1"},
        "lang": {"SYN-1": "en"},
        "sampling": {"frames": {
            "ineligible_excluded": 10, "wrong_exclusions": 4, "eligible_lost": 10, "left_open": 10,
        }},
    }
    pairs = [
        {"mrn": "71000001", "ruleset": "SYN-1", "label": "eligible", "inclusion_probability": 0.5},
        {"mrn": "71000002", "ruleset": "SYN-1", "label": "excluded", "inclusion_probability": 1.0},
    ]
    answers = _answers({
        "SYN-1": {
            score.pid_of("71000001"): _screen("71000001", "excluded", "fail"),
            score.pid_of("71000002"): _screen("71000002", "review", "pass"),
        }
    })
    fig = score.score_pathology(ids, pairs, answers)
    assert fig["scored"] is True
    assert fig["eligible_lost"]["rate"] == 0.2 and fig["eligible_lost"]["k"] == 1 and fig["eligible_lost"]["n"] == 1
    assert fig["ineligible_excluded"]["rate"] == 0.0 and fig["ineligible_excluded"]["n"] == 1
    assert fig["wrong_exclusions"]["rate"] == 0.5 and fig["wrong_exclusions"]["population"] == 4
    assert fig["left_open"]["k"] == 0 and fig["left_open"]["weighted"] is True


def test_the_pathology_headline_uses_the_weighted_total() -> None:
    """One ineligible exclusion at probability 0.25 in a frame of 20. The detail is 4 of 20; the headline
    must not keep the sample count 1 of 1."""
    ids = {
        "rulesets": {"SYN-1": "SYN-1"},
        "lang": {"SYN-1": "en"},
        "sampling": {"frames": {
            "ineligible_excluded": 20, "wrong_exclusions": 20, "eligible_lost": 20, "left_open": 20,
        }},
    }
    pairs = [{"mrn": "71000001", "ruleset": "SYN-1", "label": "excluded", "inclusion_probability": 0.25}]
    answers = _answers({"SYN-1": {score.pid_of("71000001"): _screen("71000001", "excluded", "fail")}})
    fig = score.score_pathology(ids, pairs, answers)
    detail = fig["ineligible_excluded"]
    assert detail["k"] == 1 and detail["n"] == 1
    assert detail["estimated_events"] == 4.0 and detail["population"] == 20
    head = replay.pathology_from_run({"tcga": {"pathology": fig}}, ["tcga"])
    assert head["numerator"] == 4.0 and head["denominator"] == 20.0


def test_the_replay_publishes_the_weighted_total_and_keeps_an_unweighted_count(tmp_path: Path) -> None:
    pairs, answers = _two_eligible(True)
    built, work = _write(tmp_path / "w", pairs, answers, _PAIR_FRAMES)
    fig = replay.eligible_figure("planted", score.score(built, work))
    assert fig["numerator"] == 2.0 and fig["denominator"] == 10.0
    assert type(fig["numerator"]) is float
    bare, bare_work = _write(tmp_path / "u", *_two_eligible(False), None)
    plain = replay.eligible_figure("planted", score.score(bare, bare_work))
    assert (plain["numerator"], plain["denominator"]) == (1, 2)
    assert type(plain["numerator"]) is int and type(plain["denominator"]) is int
    # π = 0.3 over a frame of 10 is 10/3 events. Rounding each block to 4 decimals sums three of them to 9.9999.
    one = json.loads(json.dumps(score.weighted_rate([1], [0.3], 10)))
    assert one["estimated_events"] == 1 / 0.3 and one["rate"] == 0.3333
    sampled = {"set": "sigir", "gold_kind": "physician",
               "pairs": {"summary": {"en": {"eligible_lost": one}}}}
    pooled = replay.figure("a", "v1", [replay.eligible_figure("sigir", sampled)])
    assert pooled["numerator"] == 1 / 0.3 and pooled["denominator"] == 10.0
    assert pooled["by_gold_kind"]["physician"]["numerator"] == 1 / 0.3
    blocks = []
    for i in range(3):
        block = json.loads(json.dumps(score.weighted_rate([1], [0.3], 10)))
        blocks.append(replay.eligible_figure(
            f"s{i}", {"set": f"s{i}", "gold_kind": "physician",
                      "pairs": {"summary": {"en": {"eligible_lost": block}}}}
        ))
    three = replay.figure("a", "v1", blocks)
    assert three["numerator"] == 10
    assert three["by_gold_kind"]["physician"]["numerator"] == 10
    assert pooled["within_target"] is False
