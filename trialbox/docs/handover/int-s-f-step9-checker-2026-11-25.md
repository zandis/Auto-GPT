# INT-S-F: the step-9 checker compares N run files against the owner's three rules

**Reader:** the people who build TrialBox: the integrator and the lane that owns the cascade. Findings for builders,
so in one language.

- **Card:** INT-S-F (Ring 0, a measurement tool; no product behaviour changes)
- **Date:** 2026-11-25
- **Tests:** `tests/unit/test_step9_compare_ints_f.py`

## What it is

`tools/step9_compare.py run1.json run2.json [...] [--bound 3] [--out report.json]`, in the form of the repository's other
compare tools (`tools/funnel_compare.py`: a documented command line, a report on stdout, an exit status).

A run file holds the SCREEN summary's `judged_store` block (`on`, `read`, `live`; `screen_cascade.py`) and the row of
every patient of the run, the excluded ones too, with the product's own field names (`CandidateRow`: `pid`, `tier`,
`criteria[].id / verdict / basis / prov / evidence`). Nothing is converted.

For every pair of runs:

| Rule | Check | Fails when |
|---|---|---|
| (i) the list | tier `high` or `review` in one run and not in the other (excluded, or absent) | any patient leaves the list; a move between `high` and `review` is only reported |
| (ii) coded | the pairs with `basis: coded` in either run | any verdict differs, or the pair is coded in one run only |
| (iii) model | the pairs with a model call behind them (`prov` not empty) | more than the bound (3 %) differ; exactly 3 % passes; the pairs are named |

"Same verdict, different evidence" (the note reference or the quote date differs) is counted per pair of runs and
never fails. The store state of each run is printed. A file with no `judged_store`, or with no boolean `on`, or runs
whose state differs, are refused with exit 2 and the missing part named. Exit 1: a rule failed.

## Not verified

The shape of a run file is the product's row; no real run's output was read here. Whether the step-9 run kept the
store on is not known from the repository.
