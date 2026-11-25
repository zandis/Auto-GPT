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

## The run file, exactly

```json
{
  "judged_store": {"on": true, "read": 0, "live": 12},
  "rows": [
    {"pid": "p001", "tier": "high", "actions": [],
     "criteria": [
       {"id": "c0", "verdict": "pass", "basis": "coded", "prov": [],
        "evidence": {"resource_refs": ["Condition/c1"]}},
       {"id": "c1", "verdict": "pass", "basis": "pair", "prov": ["call-1"],
        "evidence": {"resource_refs": ["DocumentReference/n1"], "quote": "...", "quote_date": "2026-10-01"}}]}
  ]
}
```

- `judged_store` is the SCREEN summary's block (`on` must be a boolean; `read` and `live` are printed).
- `rows` has one row for every patient of the run, the excluded ones too (`tier`: `high`, `review` or `excluded`), the
  product's `CandidateRow` with its `criteria` (`CriterionVerdict`). The tool reads `pid`, `tier`, and per criterion
  `id`, `verdict`, `basis`, `prov` and `evidence.resource_refs / quote_date`.
- The candidate list file of a job holds only the listed tiers, so it is not a run file by itself. The walk's step-9
  script must write this file for each run (the walk will adapt its script); there is no reader of the screen output
  in this card.

## Not verified

The shape of a run file is the product's row; no real run's output was read here. Whether the step-9 run kept the
store on is not known from the repository.
