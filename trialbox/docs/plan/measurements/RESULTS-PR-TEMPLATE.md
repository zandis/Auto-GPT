# Results pull request: the body

This is the body of a results pull request of lane G (branch `claude/g1-results-*`). It uses the headings of
`.github/PULL_REQUEST_TEMPLATE.md`. Copy the block below, then fill each `<...>` from the files the reader wrote.

Write the files first, from `trialbox/`:

```sh
python deploy/gcp/results_report.py <collected results dir> --out docs/plan/measurements/<run folder> \
    --window-patients <site patients> --studies <studies a night> --night-hours <hours> --vm-hours <billed hours>
```

Rules for the body:

- Synthetic data only. No secret, key or real identifier.
- No model name and no model id. Write the role: judge, verifier.
- Every figure comes from `README.md` or `capacity_inputs.json` of the run folder. Do not type a figure from memory.
- A part that is PENDING or MISSING is named. It is never left out and never counted as passed.
- Lane G changes no product code. A defect goes to the integrator as a list.

```markdown
## Card

Lane G, plan v7 section 7.1: tests <G-1, G-3, ...>. Run id `<run id>`, commit `<commit>` (branch `g1/rehearsed-<date>`).

## Summary

What ran: <the parts, the patients, the calls in flight>. One VM, <card>, <spot or on demand>.

Cost: <hours> h, US$<cost>. Estimate US$<estimate>. Cap US$<cap>. <Over the cap: yes or no.>

Verdict of the run: <PASSED, INCOMPLETE or FAILED>. <n> passed, <n> failed, <n> pending, <n> missing, of <n> planned.

| Test | What it asks | Verdict | Figures |
| --- | --- | --- | --- |
| G-1 | The passed chat template against the weights folder's own | <IDENTICAL, DIFFERENT, PENDING or MISSING> | sha256 passed `<...>`, folder `<...>`; <n> differing tokens |
| G-3 | The candidate list is the same at every setting | <IDENTICAL, DIFFERENT or NOT JUDGED> | settings <1, 4, 16, 48>; differing at <...> |
| G-3 | Calls per second at the chosen setting meet the night window | <PASS, FAIL or NOT COMPUTED> | <measured> calls/s at <n> in flight; needed <required> (<patients> patients, <studies> studies, <hours> h) |

The G-3 table is in `docs/plan/measurements/<run folder>/README.md`.

## Class B paths touched

no. Measurement files only.

## Decision

none.

## Acceptance

- G-1: <done, partial or not done>. <One line.>
- G-3: <done, partial or not done>. <One line.>
- <Each other part of the run: its status.>

## Tests added

none. The files are written by `deploy/gcp/results_report.py` (`tests/unit/test_g1_results_report.py`).

## Checks run

- `python deploy/gcp/results_report.py <collected results dir> --out docs/plan/measurements/<run folder> ...`: exit 0.
- `python -m tools.doclint`, `python -m tools.data_scan`.

## Problems closed or opened

The defect list for the integrator is `docs/plan/measurements/<run folder>/DEFECTS.md`: <n> entries.

<Copy the title of each entry, one line each. Cause, Fix and Card stay empty: the integrator fills them.>

## Files outside the card

none.

## Remains

What the next launch waits on:

- <Each PENDING or MISSING part, by name, and why it has no result.>
- <Each defect that must be fixed before the next launch, by its number in DEFECTS.md.>
- <The owner's yes to the next estimate: hours, US$, cap.>
- Launch only from a rehearsed commit on a `g1/rehearsed-*` branch.

## Dropped (D-311)

<What was planned for this run and not done, with the reason, or "none".>
```
