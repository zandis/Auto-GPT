"""Recall ledger: persisted, resumable confidence sequences and the certificate (spec v4 §6.7, §10.14; S1-12)."""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from orchestrator.db_pg import SqliteBackend, open_backend
from orchestrator.recall import LedgerError, RecallLedger, render_certificate
from orchestrator.recall import state as cs_state
from orchestrator.recall.sim import SimConfig, run
from pydantic import ValidationError
from tb_common.recall import ConfidenceSequence
from tb_contracts.recall import (
    KnownPositiveLine,
    KnownPositiveLineKind,
    RecallCell,
    RecallCertificate,
    RecallObservation,
    Stratum,
)

T0 = datetime(2026, 4, 30, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))
H = KnownPositiveLineKind.HISTORICAL_ENROLLEES
B = KnownPositiveLineKind.BLINDED_CHART_REVIEW


def clock() -> datetime:
    return T0


def obs(cell: RecallCell, i: int, label: int, run_id: str = "R1") -> RecallObservation:
    return RecallObservation(
        canonical_hash=cell.canonical_hash,
        stratum=cell.stratum,
        series=cell.series,
        draw_id=f"{run_id}:{i}",
        pid_hash=f"synthetic-{i}",
        study_id="LUNG7",
        run_id=run_id,
        draw_prob=0.01,
        weight=1.0,
        label=1 if label else 0,
        route="s4",
        observed_at=T0 + timedelta(minutes=i),
    )


@pytest.fixture
def ledger(tmp_path: Path) -> RecallLedger:
    return RecallLedger(SqliteBackend(tmp_path / "ledger.db"), clock=clock)


@pytest.mark.req("S1-12", "SAFE-12")
def test_state_round_trips_byte_identically() -> None:
    rng = random.Random(3)
    cs = ConfidenceSequence(alpha=0.0125)
    cs.extend([int(rng.random() < 0.03) for _ in range(150)] + [0.25, 1.0, 0.0, 0.7])
    text = cs_state.dumps(cs)
    again = cs_state.loads(text)
    assert cs_state.dumps(again) == text
    assert again == cs  # every float identical, not just close
    # resuming and continuing equals never stopping
    tail = [int(rng.random() < 0.03) for _ in range(60)]
    again.extend(tail)
    cs.extend(tail)
    assert cs_state.dumps(again) == cs_state.dumps(cs)
    with pytest.raises(cs_state.StateError):
        cs_state.from_state({**cs_state.to_state(cs), "grid_sha": "sha256:other"})


@pytest.mark.req("S1-12", "SAFE-10")
def test_ledger_persists_and_resumes_per_cell(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    a = RecallCell(canonical_hash="crit:egfr-mutation", stratum=Stratum.S1_AFFIRMATIVE)
    b = RecallCell(canonical_hash="crit:egfr-mutation", stratum=Stratum.S3_NOT_MET)
    rng = random.Random(5)
    ys_a: list[int] = []
    memory = ConfidenceSequence(alpha=0.05)
    for month in range(6):
        backend = SqliteBackend(db)
        led = RecallLedger(backend, clock=clock)
        batch = [int(rng.random() < 0.05) for _ in range(30)]
        assert led.append([obs(a, i, x, f"M{month}") for i, x in enumerate(batch)]) == 30
        led.append([obs(b, 0, 1, f"M{month}")])
        if month == 0:
            led.state_json(a, 0.05)  # the state is created once, then advanced with every append
        ys_a += batch
        memory.extend(batch)
        stored = led.state_json(a, 0.05)
        assert stored == cs_state.dumps(memory)
        backend.close()
    led = RecallLedger(SqliteBackend(db), clock=clock)
    assert led.observations(a) == [float(x) for x in ys_a]
    counts = led.counts(a)
    assert (counts.n, counts.found) == (180, sum(ys_a))
    assert led.counts(b).n == 6
    # appends are idempotent per draw_id
    assert led.append([obs(a, 0, 1, "M0")]) == 0
    # a state at a new alpha is built from the stored observations and equals the in-memory sequence
    fresh = ConfidenceSequence(alpha=0.01)
    fresh.extend(ys_a)
    assert led.state_json(a, 0.01) == cs_state.dumps(fresh)
    assert led.looks(a) == 6


@pytest.mark.req("S1-12", "SAFE-16", "SAFE-12")
def test_twelve_looks_through_the_ledger_reproduce_the_reference(tmp_path: Path) -> None:
    """Seed 11, p = 0.02, 12 looks of 40, 300 ledgers; each look resumes the sequence from storage. The miss rates
    equal the in-memory reference of ``python -m tools.recall_sim``: CS 0.3 % (≤ 5 %), repeated CP 9.7 % (> 5 %)."""
    cfg = SimConfig(run_rates=(0.02,), workers=min(4, os.cpu_count() or 1))
    (res,) = run(cfg, tmp_path)
    assert res.rate == 0.02 and res.reps == 300
    assert res.cs_miss <= 0.05
    assert res.cp_miss > 0.05
    assert (round(res.cp_miss, 3), round(res.cs_miss, 3)) == (0.097, 0.003)


def _example_ledger(ledger: RecallLedger) -> dict[RecallCell, int]:
    """The §6.7 example: five strata of one study, one miss at sample 200 of S2-absence(index)."""
    spec = [
        (Stratum.S1_AFFIRMATIVE, 15100, 600, None),
        (Stratum.S2_ABSENCE_INDEX, 2900, 450, 199),
        (Stratum.S2_ZERO_HIT_NOTE, 1800, 300, None),
        (Stratum.S2B_BELOW, 950, 300, None),
        (Stratum.S3_NOT_MET, 240, 120, None),
    ]
    excluded: dict[RecallCell, int] = {}
    for stratum, e, n, miss_at in spec:
        cell = RecallCell(canonical_hash=f"crit:{stratum.value}", stratum=stratum, criterion_type="diagnosis")
        ledger.append([obs(cell, i, int(i == miss_at)) for i in range(n)])
        excluded[cell] = e
    for i in range(61):
        ledger.add_known_positive(H, "thoracic-2023-2026", f"h{i}", f"synthetic-h{i}", missed=False)
    for i in range(34):
        ledger.add_known_positive(B, "LUNG7-blinded", f"b{i}", f"synthetic-b{i}", missed=i == 0)
    return excluded


POPS = {
    H: ("thoracic-2023-2026", "patients enrolled in any thoracic-oncology study 2023–2026, pooled per criterion type"),
    B: ("LUNG7-blinded", "CRC-confirmed candidates from blinded review, cumulative"),
}


@pytest.mark.req("S1-12", "SAFE-14", "DM-16")
def test_certificate_from_ledger_matches_the_spec_example(ledger: RecallLedger) -> None:
    excluded = _example_ledger(ledger)
    ledger.record_run("R1", "LUNG7", "LUNG7/v1.0.0", "2026-10", excluded)
    cert = render_certificate(ledger, "R1", rc_id="rc_test", populations=POPS, seed=912733)
    by_stage = {c.stage: c for c in cert.cells}
    expected = {
        Stratum.S1_AFFIRMATIVE: (0.03597, 0.0110),
        Stratum.S2_ABSENCE_INDEX: (0.00691, 0.0248),
        Stratum.S2_ZERO_HIT_NOTE: (0.00429, 0.0354),
        Stratum.S2B_BELOW: (0.00226, 0.0394),
        Stratum.S3_NOT_MET: (0.00057, 0.1137),
    }
    for stage, (alpha_c, upper) in expected.items():
        assert by_stage[stage].alpha_c == pytest.approx(alpha_c, abs=1e-5)
        assert by_stage[stage].upper_cs == pytest.approx(upper, abs=1e-4)
        assert by_stage[stage].upper_cp_single_look < by_stage[stage].upper_cs  # the price of anytime validity
    assert sum(c.alpha_c for c in cert.cells) == pytest.approx(0.05)
    assert cert.missed_upper == pytest.approx(365.4, abs=1.0)
    assert cert.per_1000_excluded_upper == pytest.approx(17.4, abs=0.1)
    line_h, line_b = cert.known_positive
    assert (line_h.line, line_h.biased, line_h.r, line_h.missed) == (H, True, 61, 0)
    assert line_h.recall_lower == pytest.approx(0.909, abs=1e-3)
    assert line_h.recall_lower_single_look_info == pytest.approx(0.952, abs=1e-3)
    assert line_h.label == "historical enrollees; biased: found by the previous process"
    assert (line_b.line, line_b.biased, line_b.r, line_b.missed) == (B, False, 34, 1)
    assert line_b.recall_lower == pytest.approx(0.809, abs=1e-3)
    assert line_b.label == "blinded chart review; unbiased population; r = 34"
    assert cert.quoted_line is B  # r ≥ 30
    assert "0.809" in cert.statement["en"] and "17.4 per 1,000" in cert.statement["en"]
    assert cert.data_class.value == "D1"
    # the certificate is a pure function of the ledger: rendering again gives identical bytes
    again = render_certificate(ledger, "R1", rc_id="rc_test", populations=POPS, seed=912733)
    assert again.model_dump_json() == cert.model_dump_json()
    # every printed bound is recomputable from the referenced state
    s1 = by_stage[Stratum.S1_AFFIRMATIVE]
    cell = next(c for c in excluded if c.stratum is Stratum.S1_AFFIRMATIVE)
    assert s1.cs_state.n == 600 and s1.cs_state.sha.startswith("sha256:")
    assert cs_state.loads(ledger.state_json(cell, s1.alpha_c)).upper == s1.upper_cs


@pytest.mark.req("SAFE-14")
def test_allocation_is_preregistered_and_frozen(ledger: RecallLedger) -> None:
    excluded = _example_ledger(ledger)
    ledger.record_run("R1", "LUNG7", "LUNG7/v1.0.0", "2026-10", excluded)
    first = render_certificate(ledger, "R1", rc_id="rc1", populations=POPS)
    # next month the counts change; the allocation does not
    ledger.record_run(
        "R2", "LUNG7", "LUNG7/v1.0.0", "2026-11", {c: e * 2 if i else e for i, (c, e) in enumerate(excluded.items())}
    )
    second = render_certificate(ledger, "R2", rc_id="rc2", populations=POPS)
    assert [c.alpha_c for c in first.cells] == [c.alpha_c for c in second.cells]
    assert second.registered_at == first.registered_at
    # a cell outside the registration needs a new series
    stray = RecallCell(canonical_hash="crit:new", stratum=Stratum.S1_AFFIRMATIVE)
    ledger.record_run("R3", "LUNG7", "LUNG7/v1.0.0", "2026-12", {**excluded, stray: 10})
    with pytest.raises(LedgerError, match="new series"):
        render_certificate(ledger, "R3", rc_id="rc3", populations=POPS)


def test_line_h_is_quoted_until_line_b_has_30(ledger: RecallLedger) -> None:
    cell = RecallCell(canonical_hash="crit:x", stratum=Stratum.S1_AFFIRMATIVE)
    ledger.append([obs(cell, i, 0) for i in range(50)])
    for i in range(10):
        ledger.add_known_positive(B, "LUNG7-blinded", f"b{i}", f"synthetic-b{i}", missed=False)
    assert not ledger.add_known_positive(B, "LUNG7-blinded", "b0", "synthetic-b0", missed=True)  # idempotent
    ledger.record_run("R1", "LUNG7", "v1", "2026-10", {cell: 100})
    cert = render_certificate(ledger, "R1", rc_id="rc", populations=POPS)
    assert cert.quoted_line is H
    assert "r = 10" in cert.statement["en"]


def test_contracts_enforce_two_labelled_lines() -> None:
    with pytest.raises(ValidationError):
        KnownPositiveLine(line=B, biased=True, label="x", population="p", r=1, missed=0, recall_lower=0.5, method="m")
    with pytest.raises(ValidationError):
        KnownPositiveLine(line=H, biased=True, label="x", population="p", r=1, missed=2, recall_lower=0.5, method="m")
    line = KnownPositiveLine(
        line=H, biased=True, label="x", population="p", r=1, missed=0, recall_lower=0.5, method="m"
    )
    with pytest.raises(ValidationError):
        RecallCertificate(
            rc_id="rc",
            study_id="S",
            run_id="R",
            ruleset="r",
            period="2026-10",
            alpha=0.05,
            k_cells=1,
            series=1,
            registered_at="2026-10-01T00:00:00+08:00",
            method="m",
            cells=[],
            strata=[],
            missed_point=0,
            missed_upper=0,
            per_1000_excluded_upper=0,
            known_positive=(line, line),
            quoted_line=H,
            statement={},
        )
    with pytest.raises(ValidationError):
        RecallObservation(
            canonical_hash="c",
            stratum=Stratum.S1_AFFIRMATIVE,
            draw_id="d",
            pid_hash="p",
            study_id="s",
            run_id="r",
            draw_prob=0.5,
            weight=1.0,
            label=1,
            route="s4",
            observed_at=datetime(2026, 1, 1),  # naive
        )


@pytest.mark.req("S1-12")
@pytest.mark.skipif(not os.environ.get("TB_PG_DSN"), reason="set TB_PG_DSN to a disposable PostgreSQL database")
def test_postgres_ledger_round_trip() -> None:
    pytest.importorskip("psycopg")
    backend = open_backend(os.environ["TB_PG_DSN"])
    with backend.transaction() as tx:
        for t in (
            "recall_cell",
            "recall_observation",
            "recall_sequence_state",
            "recall_run_cell",
            "recall_registration",
            "recall_known_positive",
        ):
            tx.execute(f"DROP TABLE IF EXISTS {t}")
    led = RecallLedger(backend, clock=clock)
    cell = RecallCell(canonical_hash="crit:pg", stratum=Stratum.S2B_BELOW)
    led.append([obs(cell, i, int(i == 7)) for i in range(40)])
    memory = ConfidenceSequence(alpha=0.05)
    memory.extend([float(i == 7) for i in range(40)])
    assert led.state_json(cell, 0.05) == cs_state.dumps(memory)
    led.append([obs(cell, i, 0, "R2") for i in range(40)])
    memory.extend([0.0] * 40)
    assert led.state_json(cell, 0.05) == cs_state.dumps(memory)
    backend.close()
