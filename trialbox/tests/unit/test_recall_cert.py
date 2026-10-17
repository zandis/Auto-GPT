"""Recall-certificate statistics: Clopper–Pearson and the anytime-valid confidence sequence (libs/tb_common/recall.py)."""

from __future__ import annotations

import itertools
import random

import pytest
from tb_common import recall


def test_clopper_pearson_known_values() -> None:
    assert recall.cp_upper(0, 299) == pytest.approx(0.00997, abs=2e-4)  # rule of three
    assert recall.cp_upper(1, 473) == pytest.approx(0.0100, abs=3e-4)
    assert recall.cp_lower(59, 59) == pytest.approx(0.9505, abs=1e-3)  # 59 known positives, none missed
    assert recall.cp_lower(61, 61) == pytest.approx(0.952, abs=1e-3)


def test_sequence_bound_is_monotone_and_shrinks() -> None:
    cs = recall.ConfidenceSequence(alpha=0.05)
    bounds = [cs.update(0) for _ in range(600)]
    assert all(b2 <= b1 for b1, b2 in itertools.pairwise(bounds))
    assert bounds[-1] < 0.02  # 600 clean samples
    # the price of anytime validity: wider than a single-look Clopper–Pearson bound at the same n
    assert bounds[-1] > recall.cp_upper(0, 600)


def test_sequence_covers_true_rate_over_monthly_looks() -> None:
    """Coverage over the whole sequence: the bound must stay above the true rate at every one of 12 monthly looks in
    >= 95 % of simulated ledgers. Repeated Clopper–Pearson looks fall short of this (optional stopping)."""
    rng = random.Random(7)
    p, months, per_month, reps = 0.02, 12, 40, 150
    cs_fail = cp_fail = 0
    for _ in range(reps):
        cs = recall.ConfidenceSequence(alpha=0.05)
        xs: list[int] = []
        cs_ok = cp_ok = True
        for _m in range(months):
            batch = [int(rng.random() < p) for _ in range(per_month)]
            xs += batch
            cs.extend(batch)
            cs_ok &= cs.upper >= p
            cp_ok &= recall.cp_upper(sum(xs), len(xs)) >= p
        cs_fail += not cs_ok
        cp_fail += not cp_ok
    assert cs_fail / reps <= 0.05
    assert cp_fail >= cs_fail  # the single-look bound is never better covered


def test_certificate_combines_strata() -> None:
    rng = random.Random(1)
    strata, obs = [], {}
    for stage, excluded, n, rate in [("S1", 15100, 600, 0.0), ("S2-index", 2900, 450, 0.002), ("S3", 240, 120, 0.0)]:
        xs = [int(rng.random() < rate) for _ in range(n)]
        obs[stage] = xs
        strata.append(recall.Stratum(stage, excluded, n, sum(xs)))
    any_cert = recall.certificate(strata, known_positive=(61, 0), observations=obs)
    one_look = recall.certificate(strata, known_positive=(61, 0), anytime=False)
    assert any_cert.recall_lower == pytest.approx(0.952, abs=1e-3)
    assert any_cert.missed_upper >= one_look.missed_upper > one_look.missed_point
    assert set(any_cert.per_stratum_upper) == {"S1", "S2-index", "S3"}
    assert "Bonferroni" in any_cert.method
    with pytest.raises(ValueError):
        recall.certificate(strata, observations={"S1": obs["S1"]})


def test_recall_lower_sequence() -> None:
    lb = recall.recall_lower_sequence([0] * 120)
    assert 0.9 < lb < recall.cp_lower(120, 120)  # anytime-valid, so below the single-look bound
    assert recall.recall_lower_sequence([1] * 5) < 0.5


def test_weighted_observations_and_sequence_recall_line() -> None:
    cs = recall.ConfidenceSequence()
    cs.extend([0.0, 0.25, 0.0, 0.1] * 50)
    assert 0.0 < cs.upper < 0.3
    with pytest.raises(ValueError):
        cs.update(1.5)
    strata = [recall.Stratum("S1", 1000, 100, 0)]
    cert = recall.certificate(strata, observations={"S1": [0] * 100}, known_positive_sequence=[0] * 120)
    assert cert.known_positives == 120 and cert.recall_lower is not None
    assert cert.recall_lower < recall.cp_lower(120, 120)
    assert recall.GRID_POINTS[1] == pytest.approx(0.00005)
