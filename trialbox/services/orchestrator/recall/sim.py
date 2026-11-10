"""The ``recall_cert`` simulation run through the recall ledger (spec v4 §10.14 SAFE-16, App. F; S1-12).

Same experiment and random stream as ``tools/recall_sim.py`` (seed 11: p = 0.005 then p = 0.02, 300 ledgers of 12
monthly looks of 40), but every look goes through the ledger: the month's observations are appended (which advances
the stored sequence state in the same transaction), the connection is closed, and the next look resumes the sequence
from the stored canonical state on a new connection. A ledger "misses" if the printed 95 % upper bound fell below p at
any look. The ledgers live in the trial database's ``recall`` schema (``TB_DB_URL``) under cell hashes tagged with the
run, and are deleted when the run ends.

    python -m orchestrator.recall.sim --config eval/suites/recall_cert/config.yaml
"""

from __future__ import annotations

import argparse
import functools
import multiprocessing
import random
import secrets
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from tb_common.recall import cp_upper
from tb_contracts.recall import RecallCell, RecallObservation, Stratum

from orchestrator.db_pg import canonical_json
from orchestrator.recall.ledger import RecallLedger, open_ledger_backend

T0 = datetime(2026, 1, 31, 12, 0, tzinfo=timezone(timedelta(hours=8)))  # a fixed synthetic instant, not a site zone


@dataclass(frozen=True)
class SimConfig:
    rates: tuple[float, ...] = (0.005, 0.02)
    reps: int = 300
    months: int = 12
    per_month: int = 40
    seed: int = 11
    alpha: float = 0.05
    run_rates: tuple[float, ...] | None = None  # None: all rates; the stream is consumed for every rate regardless
    workers: int = 4


@dataclass(frozen=True)
class SimResult:
    rate: float
    reps: int
    cp_miss: float
    cs_miss: float
    per_ledger: tuple[tuple[bool, bool], ...] = field(repr=False, default=())


def draw_batches(cfg: SimConfig) -> dict[float, list[list[list[int]]]]:
    """rate → ledger → month → 0/1 batch, consuming the stream exactly as ``tools.recall_sim`` does."""
    rng = random.Random(cfg.seed)
    out: dict[float, list[list[list[int]]]] = {}
    for p in cfg.rates:
        out[p] = [
            [[int(rng.random() < p) for _ in range(cfg.per_month)] for _m in range(cfg.months)]
            for _r in range(cfg.reps)
        ]
    return out


def _observations(cell: RecallCell, idx: int, month: int, batch: Sequence[int]) -> list[RecallObservation]:
    when = T0 + timedelta(days=30 * month)
    return [
        RecallObservation(
            canonical_hash=cell.canonical_hash,
            stratum=cell.stratum,
            series=cell.series,
            draw_id=f"{idx}:{month}:{j}",
            pid_hash=f"synthetic-{idx}-{month}-{j}",
            study_id="SIM",
            run_id=f"SIM-{month:02d}",
            draw_prob=1.0,
            weight=1.0,
            label=1 if x else 0,
            route="s4",
            observed_at=when,
        )
        for j, x in enumerate(batch)
    ]


def _month(m: int) -> datetime:
    return T0 + timedelta(days=30 * m)


def _run_chunk(
    args: tuple[str | None, str, float, float, list[tuple[int, list[list[int]]]]],
) -> list[tuple[int, bool, bool]]:
    url, tag, p, alpha, ledgers = args
    out: list[tuple[int, bool, bool]] = []
    for idx, months in ledgers:
        cell = RecallCell(canonical_hash=f"{tag}{p!r}-{idx:04d}", stratum=Stratum.S1_AFFIRMATIVE)
        cs_ok = cp_ok = True
        for m, batch in enumerate(months):
            backend = open_ledger_backend(url)  # a fresh "process" per look: the sequence is resumed from storage
            try:
                ledger = RecallLedger(backend, clock=functools.partial(_month, m))
                ledger.append(_observations(cell, idx, m, batch))
                upper = ledger.upper(cell, alpha)
                counts = ledger.counts(cell)
            finally:
                backend.close()
            cs_ok &= upper >= p
            cp_ok &= cp_upper(counts.found, counts.n, alpha) >= p
        out.append((idx, cp_ok, cs_ok))
    return out


def run_tag() -> str:
    """A cell-hash prefix of its own for one simulation run (runs share the ``recall`` schema)."""
    return f"sim-{secrets.token_hex(6)}-"


def run(cfg: SimConfig, url: str | None = None) -> list[SimResult]:
    """``url``: the trial database (``TB_DB_URL`` when None)."""
    batches = draw_batches(cfg)
    results: list[SimResult] = []
    tag = run_tag()
    RecallLedger(url=url).close()  # schema and tables exist before the workers start (no connection is forked)
    try:
        for p in cfg.rates:
            if cfg.run_rates is not None and p not in cfg.run_rates:
                continue
            results.append(_run_rate(cfg, url, tag, p, batches[p]))
    finally:
        ledger = RecallLedger(url=url)
        try:
            ledger.purge_cells(tag)
        finally:
            ledger.close()
    return results


def _run_rate(cfg: SimConfig, url: str | None, tag: str, p: float, rate_batches: list[list[list[int]]]) -> SimResult:
    ledgers = list(enumerate(rate_batches))
    k = max(1, min(cfg.workers, len(ledgers)))
    chunks = [(url, tag, p, cfg.alpha, ledgers[w::k]) for w in range(k)]
    if k == 1:
        parts = [_run_chunk(chunks[0])]
    else:
        with multiprocessing.get_context("fork").Pool(k) as pool:
            parts = pool.map(_run_chunk, chunks)
    flat = sorted(x for part in parts for x in part)
    per = tuple((cp_ok, cs_ok) for _i, cp_ok, cs_ok in flat)
    return SimResult(
        rate=p,
        reps=len(per),
        cp_miss=sum(not cp for cp, _ in per) / len(per),
        cs_miss=sum(not cs for _, cs in per) / len(per),
        per_ledger=per,
    )


def load_config(path: Path) -> tuple[SimConfig, dict[str, Any]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    s = doc["simulation"]
    cfg = SimConfig(
        rates=tuple(float(r) for r in s["rates"]),
        reps=int(s["reps"]),
        months=int(s["months"]),
        per_month=int(s["per_month"]),
        seed=int(s["seed"]),
        alpha=float(s["alpha"]),
        workers=int(s.get("workers", 4)),
    )
    return cfg, dict(doc.get("gate", {}))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orchestrator.recall.sim")
    ap.add_argument("--config", type=Path, default=Path("eval/suites/recall_cert/config.yaml"))
    ap.add_argument("--reps", type=int, help="override the number of ledgers per rate")
    ap.add_argument("--workers", type=int)
    a = ap.parse_args(argv)
    cfg, gate = load_config(a.config)
    if a.reps or a.workers:
        cfg = SimConfig(
            rates=cfg.rates,
            reps=a.reps or cfg.reps,
            months=cfg.months,
            per_month=cfg.per_month,
            seed=cfg.seed,
            alpha=cfg.alpha,
            workers=a.workers or cfg.workers,
        )
    results = run(cfg)
    ok = True
    for r in results:
        print(canonical_json({"rate": r.rate, "reps": r.reps, "cp_miss": r.cp_miss, "cs_miss": r.cs_miss}))
        if gate and r.rate == float(gate["rate"]):
            ok &= r.cs_miss <= float(gate["cs_miss_max"]) and r.cp_miss > float(gate["cp_miss_min_exclusive"])
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
