# D-705 The re-run's refusal is held by its own list, and an error handed whole to a helper is listed

- **Task:** NEW-TRUST-9 (two follow-ups of D-555 and D-700; the integrator's word of 2026-11-13)
- **PR:** this branch (`agent/NEW-TRUST-9-own-text-and-helpers`)
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI)
- **Builds on:** D-555, D-557 (the listed error classes and what their texts may name), D-700 (the reading of every
  service), D-666 (the re-run's refusal)

## Two gaps

1. **The re-run's refusal** (`ReplayUnknown`, D-666) reaches an answer with its text. When it first met D-555's
   test it was put on the list of places that may take another error's text. That list says where; it does not
   hold what the text may name. A class whose sentences are written in the repository belongs with the listed
   classes, each with what a text is built from.
2. **An error handed whole to a helper** (`missing_table(exc, "document")` in the matching, found by lane A2) is
   read inside the helper, where D-700's reading of statements does not look.

## The decision

1. `ReplayUnknown` joins the listed classes of `tests/unit/test_error_answers.py`: its texts may name the earlier
   job's id and nothing else. It leaves the list of places.
2. `tests/unit/test_error_text_across_services.py` lists every call that passes a general error whole to a
   function inside its `except` block (log calls, `type`, `str`, `repr` and the text-free `trace_of` apart): for
   this lane exactly, by file and function, with what the helper does with it; for other lanes as a ceiling by
   file, function and count. A new such call fails.

No product code changes.

## What it does not do

- It does not judge the other lanes' helpers (the adapter's `failure.words`, `lake_error`, the lake's
  `error_answer`, the mail gateway's `NotSent`, the matching's `missing_table`, the trace store's `refusal`): each
  is listed with its count. Lane A2 is changing the matching's.
- When lane B2's later card brings `cohort.ReplayUnsure` and `cohort.RecordChanged`, they belong with the listed
  classes in the same way.

## Review

No reviewer was asked: a test file tightened, no product code.

## Reuse check

The two tests' own reading helpers; nothing is added.

## Dropped (D-311)

No sign-off step.
