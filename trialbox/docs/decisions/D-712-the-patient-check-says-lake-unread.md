# D-712 The patient check says the lake could not be read when its queries fail, and a refused query is not that

- **Task:** NEW-SITE-3 (the integrator's order of 2026-11-13; what D-709 left open)
- **PR:** this branch (`agent/NEW-SITE-3-patient-check-says-lake-unread`), cut from NEW-B-32 (#539, D-673) with
  NEW-SITE-2 (#538, D-709) merged in; it lands after both
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-709 (the site set-up when the lake cannot be asked), D-673 (a query the lake did not answer
  is the lake's service error, with its status; a 200 that is not its answer is `LakeBadAnswer`)

## The problem

D-709 left one place open: on a lake whose health answers and whose queries fail, the site's patient check
answered 500, because the lake's client raised a plain `RuntimeError` there, which cannot be told from a fault
of the code. D-673 gives that failure a type and a status.

Put together, the two cards then said too much: the routes caught every service error and every HTTP error, so
a query the lake **refused** (a 400: the engine's complaint about the question, which is a fault of the
criteria's SQL or of this code) and **another service's** error were both answered "the lake could not be read",
which is untrue of them and hides them.

## The decision

- **One question decides** (`readiness.is_unread`): the lake fails or does not answer (`lake_down`: its health
  not read, an answer of 500 and above, no answer, and now a 200 that is not the lake's answer, `LakeBadAnswer`)
  or a reader raised `LakeUnread`. The readiness answer and the two routes say `lake_unread` only then.
- **The patient check and the counts** therefore say `lake_unread` for a lake whose queries fail (by test,
  through the routes), and a refused query and another service's error go on as errors (by test).
- The same question decides a saved change's "publish waits for the lake" (D-709): a bad answer of the lake now
  counts as the lake failing there too.

## What it does not do

- The readiness answer's two fixed questions (the unknown share, the feed tier) still read any failure of their
  query as "could not be read": they are the box's own questions about a snapshot the lake named, and that page
  should say so rather than fail.
- No page changes: the pages of D-709 already show `lake_unread`.
- Nothing in the lake's client is changed (lane B2's).

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`lake_down` (D-709) and the lake's typed errors (D-673); one small function is added (`readiness.is_unread`).

## Dropped (D-311)

No sign-off step.
