"""Pure units of the cascade and the DL-1 analytics (no data, no gateway)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from deliverables.analytics import TierEstimate, adjusted_estimate, projection, wilson
from matching.cascade.judge import JudgeReply, expected_tokens, verify_span
from matching.cascade.s2b_semantic import (
    MIN_JUDGED_POSITIVES,
    PUBLIC_PRIOR_THRESHOLD,
    SITE_SAFETY_MARGIN,
    BatchEmbedder,
    ThresholdTable,
    screen,
)

EXCERPTS = [
    {"did": "d1", "date": "2026-03-02", "text": "Patient   on dialysis since 2025."},
    {"did": "d2", "date": "2020-01-01", "text": "History of stroke."},
]


def _reply(quote: str | None, quote_date: str | None = None) -> JudgeReply:
    return JudgeReply("fail", 0.9, quote, quote_date, "r")


@pytest.mark.req("CAS-16")
def test_span_must_verify_text_window_and_date() -> None:
    lo, hi = date(2025, 10, 1), date(2026, 10, 1)
    span = verify_span(_reply("on dialysis since 2025", "2026-03-02"), EXCERPTS, lo, hi)
    assert span is not None and span["did"] == "d1" and span["sentence_hash"].startswith("sha256:")
    assert verify_span(_reply("on dialysis since 2024"), EXCERPTS, lo, hi) is None  # not in the text
    assert verify_span(_reply("History of stroke"), EXCERPTS, lo, hi) is None  # chunk outside the window
    assert verify_span(_reply("on dialysis", "2026-03-03"), EXCERPTS, lo, hi) is None  # date mismatch
    assert verify_span(_reply(None), EXCERPTS, lo, hi) is None
    assert expected_tokens(EXCERPTS) > 300


@pytest.mark.req("CAS-14", "CAS-15")
def test_s2b_threshold_prior_until_enough_judged_positives() -> None:
    t = ThresholdTable(site={"exclusion|en": (0.3, MIN_JUDGED_POSITIVES - 1), "exclusion|zh": (0.3, 150)})
    assert t.get("exclusion", "en").source == "public_prior"
    assert t.get("exclusion", "en").value == pytest.approx(PUBLIC_PRIOR_THRESHOLD - SITE_SAFETY_MARGIN)
    assert t.get("exclusion", "zh").source == "ltt_site" and t.get("exclusion", "zh").value == 0.3


class _Emb:
    model = "test"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "dialysis" in x else [0.0, 1.0] for x in texts]


@pytest.mark.req("CAS-15")
def test_s2b_screen_one_batch_per_pair() -> None:
    emb = BatchEmbedder(_Emb())
    thr = ThresholdTable().get("exclusion", "en")
    hit = screen(emb, "on dialysis?", ["walks daily", "dialysis three times a week"], thr)
    miss = screen(emb, "on dialysis?", ["walks daily"], thr)
    assert hit.above and hit.top[0][0] == 1 and not miss.above
    assert emb.batches == 2
    assert not screen(emb, "q", [], thr).above and emb.batches == 2


@pytest.mark.req("RPT-22", "FR-M3-2")
def test_interval_helpers() -> None:
    lo, hi = wilson(5, 20)
    assert 0.0 < lo < 0.25 < hi < 1.0
    assert wilson(0, 0) == (0.0, 1.0)
    tiers = [
        TierEstimate("strong", 10, 10.0, 8.0, 12.0, 10, "census"),
        TierEstimate("potential:data_gap", 5, 5.0, 3.0, 7.0, 5, "census"),
        TierEstimate("potential:uncertain", 0, 0.0, 0.0, 0.0, 0, "census"),
    ]
    est, lo2, hi2, _ = adjusted_estimate(tiers)
    assert est == pytest.approx(12.0) and lo2 < est < hi2  # strong + 0.4 × potential
    a = projection(2.0, 0.5, reach=0.5, accept=0.5, months=12, paths=500, seed=7)
    assert len(a) == 12 and a == projection(2.0, 0.5, reach=0.5, accept=0.5, months=12, paths=500, seed=7)


@pytest.mark.req("SAFE-13", "CAS-10")
def test_certificate_refused_without_exclusions(tmp_path: Path) -> None:
    from matching.cascade.certificate import AuditPlan, certify
    from matching.cascade.engine import CascadeResult
    from matching.cascade.model import CascadeMetrics

    res: Any = CascadeResult(
        study_id="S",
        ruleset="R",
        ruleset_version="1",
        semantics="v1",
        ir_hash="sha256:0",
        criterion_hashes={},
        index_dates=[],
        traces={},
        stages=[],
        metrics=CascadeMetrics(),
        queue=[],
        final_list=[],
        applied=[],
        note_criteria=[],
        human_criteria=[],
    )
    out = certify(res, tmp_path / "l.sqlite", run_id="r", period="2026-10", plan=AuditPlan())
    assert out.status == "refused" and out.reasons == ["no exclusions to certify"]
    assert out.as_pack_input()["refused"] is True
