# Sampling weights in the scorer (2026-11-19)

**Reader:** the people who build TrialBox: lane H, whoever scores an audited or sampled set, and the integrator.
For builders, so in one language.

Plan 10 row 10G-37 (review 20, item 20-13), decision D-1334. Taken over by lane H from draft PR #1200 after the
integrator's review of 2026-11-19 16:03 UTC. The builders' branch was not taken: its frame size per rate is what made
the replay's denominators stale, and its interval had no stated coverage. The card started over from master.

## What changed

- `tools/public_accuracy/weights.py` (new): reads the `sampling` declaration of a set's `ids.json`, and weights each
  rate to the frame with a conservative interval.
- `tools/public_accuracy/score.py`: `score.json` gains `sampling` for a set that declares a draw (the design and every
  pair, criterion and pathology rate weighted). The criterion answer is read by one function (`criterion_answer`),
  used by the unweighted and the weighted scorer alike. The pathology prose says its counts are the sample's.
- `tools/public_accuracy/replay.py`: a sampled set's target 1 and pathology figures are the frame's estimates, with
  the sample beside them; the printed report shows "n/a" for an estimate that does not exist.

A set that declares no draw is scored as before: no `sampling` key, and every existing test of the scorer and the
replay passes unchanged (165 tests in the 10 files that import them).

## The declaration

```json
"sampling": {"unit": "pair",
             "strata": {"rare": 10, "common": {"frame": 990, "lang": "en"}}}
```

`unit` is the gold file the draw is over (`pair` or `criterion`); each stratum has its frame size, and may name its
one language. Every row of that gold file has `"sampling_stratum": "<name>"`.

## The method

- **Design.** A stratified simple random sample without replacement, read conditional on each stratum's drawn count.
  A Bernoulli draw with one probability per stratum is such a sample once its count is known, so the method needs no
  probability per row.
- **Estimate.** Weight `N_h / n_h` per drawn row. The weighted events and the weighted domain are unbiased for the
  frame's counts; the rate is their ratio. Where the domain is the whole frame (the unanswered share) the rate is
  unbiased; for a domain read from the answers (eligible lost) it is a ratio of two unbiased totals, consistent and
  not exactly unbiased. A stratum with frame units and no draw gives no estimate: `rate` is None, with the reason.
- **Interval.** For each stratum sampled but not in full, exact two-sided hypergeometric bounds on the domain's events
  and on its non-events, each at level `1 - alpha/(2m)` for `m` such strata; a stratum drawn in full is exact; an
  undrawn stratum spans 0 to its frame. All bounds hold together with probability at least 0.95 (Bonferroni), and the
  rate's interval is its range over them, rounded outward.
- **Replay.** Target 1 is within for a sampled set only when the interval's upper end is 0. The pathology target is
  within only for a draw of every row: the PoC-1 claim is the counts of every report.

## What the tests show (`tests/unit/test_sampling_weights_10g37.py`, 25 tests)

- Unbiased on a planted population: over all 840 equally likely draws of a two-stratum frame (3 of 8, 2 of 6), the
  mean estimate is the frame's rate exactly (fractions, no tolerance); the unweighted sample share is not. The two
  weighted totals of a domain rate are unbiased over all 350 draws of another frame.
- Coverage, seed 1037, 1000 draws per case:

| Case | Frame rate | Covered | Draws with no event | Median width |
| --- | --- | --- | --- | --- |
| 90 certain non-events, 10 events at 0.02 (the review's case) | 0.1000 | 1000 | 825 | 0.100 |
| 990 certain non-events, 10 events at 0.01 (the first review's case) | 0.0100 | 1000 | 921 | 0.010 |
| rare stratum 5 of 40 at 0.05, common 8 of 400 at 0.1 | 0.0295 | 1000 | 316 | 0.209 |
| fixed draws: 1 event in 200 (4 drawn), 3 in 60 (20 drawn) | 0.0154 | 1000 | 283 | 0.600 |
| three strata at 0.2, 0.5 and 0.03 | 0.0900 | 1000 | 13 | 0.580 |

  The test asserts at least 950 of 1000 in each case. The builders' scorer on the first case, 1000 seeded draws: 831
  misses of 1000 (run here on `e25ccc39`'s `score.py`).
- One test per finding of the review (the table below).

## Limits (what the tests do not show)

- The interval is conservative, often far wider than nominal (the medians above); nothing here claims a 95 % interval
  that is tight. A tighter interval is not decided (D-1334).
- Coverage is shown for the five cases above and argued in general from the exact bounds and the Bonferroni sum; it
  is not shown for every design. Its argument needs the stated design: within a stratum, every unit equally likely.
- A probability that differs row by row inside a stratum is not supported; it is written as its own stratum.
- A stratum above 10,000,000 units is refused (the tails are summed with `lgamma`).
- No set in the repository declares a draw today; nothing here was run on a stored public run. The level (b) replay
  of a sampled set calls the same scorer and was read, not run.

## Findings

The review of PR #1200 at 16:03 UTC, each closed by this card's code (`findings.json` beside this page):

| Id | Severity | Finding (on PR #1200's branch) | Closed by |
| --- | --- | --- | --- |
| H10G37-01 | High | the interval under-covers when low-probability events go undrawn ([0, 0.0402] for a rate of 0.1) | the stratified conservative interval; `test_the_interval_covers_the_frame_rate_in_a_seeded_simulation`, `test_the_review_case_a_draw_with_no_rare_event_is_not_given_a_narrow_interval` |
| H10G37-02 | Medium | a declared frame disappears when the set draws no rows | `test_a_declared_frame_with_no_draw_is_kept_and_bounds_the_rate` |
| H10G37-03 | Medium | the pair scorer keeps a stored wrong-exclusions denominator on a replay | `test_a_replay_that_excludes_fewer_pairs_gets_its_own_denominator` |
| H10G37-04 | Medium | the criterion scorer keeps a stored denominator on a replay | `test_a_replay_that_answers_fewer_criteria_gets_its_own_denominator` |
| H10G37-05 | Medium | the pathology scorer keeps a stored eligible-loss denominator | `test_the_pathology_figure_of_a_replay_answering_fewer_gets_its_own_denominator` |
| H10G37-06 | Low | tiny probabilities overflow the weight sum | `test_a_tiny_inclusion_probability_neither_overflows_nor_aborts` |
| H10G37-07 | Low | the replay crashes on a block with no estimate | `test_a_figure_with_an_unknown_estimate_renders_and_pools_as_unknown` |
| H10G37-08 | Low | the pathology prose gives sample counts beside weighted fields | `test_the_pathology_prose_is_labelled_as_the_sample` |

The first review (withdrawn by the integrator at 15:33 as a review of the first version) is covered too: a zero in the
sample is not within target 1 (`test_zero_in_the_sample_is_not_within_the_target_unless_the_frame_is_shown_empty`),
an undrawn language stays in the pooled frame (`test_an_undrawn_language_stratum_stays_in_the_pooled_frame`), a
boolean frame size is refused (`test_a_declaration_that_does_not_hold_is_refused_with_its_reason`), and the replay's
pathology headline is the frame's estimate. No finding is left open.
