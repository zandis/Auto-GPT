"""Reproduce the recall-certificate simulation quoted in spec/v4 (§10.14, Appendix F).

A stratum's true elusion rate is p. Each month, 40 new excluded patients are audited and the certificate is re-issued.
Over 12 monthly looks, count the ledgers whose printed 95 % upper bound fell below p at any look:

* repeated one-sided Clopper–Pearson (a single-look bound, recomputed every month);
* the anytime-valid confidence sequence in ``libs/tb_common/recall.py``.

    python -m tools.recall_sim                 # p = 0.02 and 0.005, 300 ledgers each, seed 11

Reference output (seed 11): p = 0.02 → Clopper–Pearson 0.097, sequence 0.003; p = 0.005 → 0.000 and 0.000.
"""

from __future__ import annotations

import argparse
import random

from tb_common import recall


def miscoverage(p: float, reps: int, months: int, per_month: int, rng: random.Random) -> tuple[float, float]:
    cs_fail = cp_fail = 0
    for _ in range(reps):
        cs = recall.ConfidenceSequence()
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
    return cp_fail / reps, cs_fail / reps


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="recall_sim")
    ap.add_argument("--rates", type=float, nargs="+", default=[0.005, 0.02])
    ap.add_argument("--reps", type=int, default=300)
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--per-month", type=int, default=40)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    for p in a.rates:
        cp, cs = miscoverage(p, a.reps, a.months, a.per_month, rng)
        print(f"p={p}: repeated Clopper-Pearson miscoverage {cp:.3f}; confidence sequence {cs:.3f}")


if __name__ == "__main__":
    main()
