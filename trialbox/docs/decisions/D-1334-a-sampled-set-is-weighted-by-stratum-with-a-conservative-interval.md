# D-1334 A sampled set is weighted to its frame by stratum, with a conservative interval (10G-37)

- **Task:** lane H, plan 10 row 10G-37 (review 20, item 20-13): sampling weights in the scorer for any audited or
  actively sampled set. · **Date:** 2026-11-19
- **Decision:**
  - A set whose gold rows are a sample of a larger frame says so in `ids.json`:
    `"sampling": {"unit": "pair" | "criterion", "strata": {"<name>": <frame size> | {"frame": <size>, "lang": "<code>"}}}`,
    and every row of that unit's gold file names its `sampling_stratum`. A row with no stratum or an unknown one, a
    unit drawn twice, more rows than a stratum's frame, a frame size that is not a positive integer (`true` is not 1)
    or above 10,000,000: the declaration is refused with the reason, and no weighted figure is written.
  - The design read is a stratified simple random sample without replacement, conditional on each stratum's drawn
    count. A Bernoulli draw with one probability per stratum is such a sample once its count is known. A probability
    that differs row by row inside a stratum is not this design: each probability is written as its own stratum.
  - The estimate: weight `N_h / n_h` per drawn row; the weighted events and the weighted domain are unbiased for the
    frame's counts; the rate is their ratio. A rate's domain (eligible pairs the box answered, the box's exclusions,
    criteria answered) is read from the run's own answers on the drawn rows, never from a stored frame per rate, so a
    replay with other answers has its own denominator. A stratum with no draw gives no estimate (None, with the
    reason).
  - The interval is conservative: per stratum sampled but not in full, exact two-sided hypergeometric bounds on the
    domain's events and on its non-events, each at level `1 - alpha/(2m)` for `m` such strata (Bonferroni); a stratum
    drawn in full is exact; an undrawn stratum spans 0 to its frame. The rate's interval is its range over those
    bounds, rounded outward.
  - The report (`tools/public_accuracy` `score.json`) gains `sampling` only for such a set: the design, and per rate a
    block with the sample's `k` and `n`, `rate`, `ci95`, `estimated_events`, `estimated_in_domain`, the bounds, the
    frame and the undrawn strata. The unweighted rates beside it are the sample's counts, as before; the pathology
    prose says so. A set with no `sampling` is unchanged.
  - The replay (`tools/public_accuracy/replay.py`) reads a sampled set's frame estimate. Target 1 is within only when
    the interval's upper end is 0 (a zero in the sample is not a zero in the frame). The pathology target is within
    only for a draw of every row, since the PoC-1 claim is the counts of every report.
- **Not decided here:** a tighter interval (a joint multinomial bound, or one that is not Bonferroni); per-row
  unequal probabilities inside a stratum; any set that is sampled today (none in the repository declares a draw).
- **Held by:** `tests/unit/test_sampling_weights_10g37.py`.
