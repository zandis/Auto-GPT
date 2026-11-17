# D-1134 a stored run's exclusions are traced by patient, offline

- **Task:** lane H, card H-18 (the review of launch P2b, run `box-20261117T073759Z-57263236`)
- **PR:** this branch (`claude/lane-h-18-p2b-review`)
- **Date:** 2026-11-17
- **Status:** reserved
- **Builds on:** D-1111 (the offline replay and its safe extractor), D-1064 and D-1118 (conflicted pairs), D-1126
  (a stored run's traces read offline)

## Context

The replay (D-1111) counts: 4 of 420 eligible patients wrongly excluded in P2b, and 14 exclusions on lines no gold
row judges. It does not say which patient, on which line, at which stage, or what the models answered. The review of
P1b found those by hand. The integrator asked for them by name for P2b.

## Decision

1. `python -m tools.public_accuracy.trace RUN ...` reads stored sets as the replay reads them (tarballs through
   `replay.safe_extract`, into a new empty folder outside the repository). It runs nothing in them and changes
   nothing. It calls no model, no network and no GPU. It prints a listing, and with `--json` writes a report
   (`schema_version` 1). Exit 0 when it ran, 2 on an input it will not read.
2. **Exclusions.** Each gold pair labelled eligible that the box excluded is listed. With `--patient` or `--ruleset`,
   every excluded pair of that patient or protocol is listed. Each failed line is given with:
   - its class and compiled logic, as `answers.json` stores them;
   - the verdict's basis, and the SCREEN stage it implies (`coded`: S1, `notes`/`pair`/`single`: S3 or S4, `person`:
     S5; the mapping of `screen_cascade.basis_of`);
   - the quote;
   - whether the benchmark wrote the line (`gold/written.json`), and whether a gold criterion row judges it;
   - the pair's own criterion labels;
   - the note-question calls of the protocol's SCREEN job on that line: each model's answer, a schema repair, and
     whether the quote is in the excerpts the model was sent.
3. **Judged.** The note questions of each SCREEN job are grouped by the prompt's input, with the models' replies in
   order. A schema repair and a reply that is no JSON are said. With `--ref`, the set's build day, each question's
   first excerpt day is joined to the patients whose visit `site.build` placed on that day. That is at most two
   patients, since day i and day i + 300 coincide. The count of questions on no placed visit day checks the day given.
4. It names. It decides no figure and calls no target met (D-1064 item 4).

## Figures

On P2b (`docs/plan/measurements/p2b-review-2026-11-17.md`): the 5 sigir pairs (4 without the conflicted one) with
their lines and stages; tcga's 500 questions by reply, 2 of them with two verifier replies that are no JSON; with
`--ref 2026-11-17` all 306 sigir questions fall on placed visit days, and with 2026-11-16 or 2026-11-18 none does.

## Test

`tests/unit/test_h18_trace_2026_11_17.py`, on a made-up run in the records' real shape. It covers:

- the eligible pair excluded on a written line at S1, and the one excluded on a note line with its two calls;
- a pair of another label left out unless a patient or protocol is asked for;
- questions grouped with repairs and a reply that is no JSON;
- the visit-day join, and its count of days on no visit;
- the builder's visit-day formula;
- the command line on a tarball, and an unsafe tarball refused.
