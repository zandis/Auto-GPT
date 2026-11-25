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
| (i) withheld | a run whose list was withheld | every patient counts as having left the list |
| (iii) model | the pairs with a model call behind them (`prov` not empty) | more than the bound (3 %) differ; exactly 3 % passes; the pairs are named |

"Same verdict, different evidence" (the note reference or the quote date differs) is counted per pair of runs and
never fails. The store state of each run is printed. A file with no `judged_store`, or with no boolean `on`, or runs
whose state differs, are refused with exit 2 and the missing part named. Exit 1: a rule failed.

## The run file, exactly

```json
{
  "commit": "<the build's commit>",
  "snapshot": "2026-10-01",
  "flags": {"derived.stored_read": false},
  "consent_state": "<the consent register state the run read, a digest or a version>",
  "list_withheld": false,
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

- `judged_store` is the SCREEN summary's block. `on` must be a boolean. With `on` true, `read` must be recorded and be 0:
  a run that replays stored answers proves nothing and is refused. Runs whose `on` differs are refused too.
- `commit`, `snapshot`, `flags["derived.stored_read"]` and `consent_state` must be present and equal in every run
  (a missing one is named). `snapshot` is the candidate list's field; the flag is the product's `derived.stored_read`.
  `commit` and `consent_state` are not fields of a candidate list today: the walk's script writes them. `list_withheld`
  (true or false, required) says the run's list was withheld (the more-than-10 % rule); true counts every patient as
  having left the list. I found no field of that name in the product, so its name is the tool's.
- `rows` has one row for every patient of the run, the excluded ones too (`tier`: `high`, `review` or `excluded`), the
  product's `CandidateRow` with its `criteria` (`CriterionVerdict`). The tool reads `pid`, `tier`, and per criterion `id`,
  `verdict`, `basis`, `prov` and `evidence.resource_refs / quote_date`.
- Refused (exit 2, the row named): no rows; no coded pair or no model pair in a run; a row without `pid`, a criterion
  without `id`, a patient or a pair twice (never last-wins). Pairs with neither `basis: coded` nor a call (a search rule,
  a person) are counted and the differing ones named, not gated.
- The candidate list file of a job holds only the listed tiers, so it is not a run file by itself. The walk's step-9
  script must write this file for each run (the walk will adapt its script); there is no reader of the screen output
  in this card.

Reported and not gated (thresholds come from a rehearsal run): per criterion, the share of differing model verdicts
(a criterion with more than half of the differences is named), and section 4: the patients whose tier differs between
runs and, with `--note-truth FILE`, per run and criterion the harm against the synthetic fixtures' note truth. The file
is `{pid: {criterion: "yes"|"no"|"unknown"}}`, the shape `tools.scenarios.note_truth` returns from the sites'
`note_truth.json` (it maps MRNs to pseudonymous ids with the site key). The direction is `BLOCKING_TRUTH` of
`tools/scenarios.py`: for an exclusion criterion a truth of `yes` speaks against the patient, for an inclusion
criterion `no`. Reported: false demotions (the truth does not speak against the patient, the run says "not met"),
misses (it does, the run did not say "not met"), the "unknown" truths apart, and pairs the run did not judge. Without the
file it prints that the harm measure is not available.

## Not verified

The shape of a run file is the product's row; no real run's output was read here. Whether the step-9 run kept the
store on is not known from the repository.
