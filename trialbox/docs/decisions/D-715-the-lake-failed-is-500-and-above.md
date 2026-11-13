# D-715 "The lake could not be read" is a status of 500 and above; a fault of the question is shown as a fault

- **Task:** NEW-SITE-5 (the integrator's order of 2026-11-13, after lane B2's D-675)
- **PR:** this branch (`agent/NEW-SITE-5-lake-failed-is-5xx`), cut from NEW-B-34 (#549, D-675) with NEW-SITE-3
  (#548, D-712) merged in; it lands after both
- **Date:** 2026-11-13
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-675 (the status of a failed lake query says who failed: the question, 4xx, or the lake, 5xx),
  D-712 and D-709 (the site set-up when the lake cannot be read)

## The problem

D-712 had to read every failed query of the lake but a 400 as "the lake could not be read", because the lake
answered its own failures and the engine's complaint about the question with the same 422. That hid a fault of
the question behind "try again". D-675 separates them: 400 and 422 are the question's, 503 and 500 the lake's.
And the two fixed readers of the readiness answer (the unknown share, the feed tier) still turned every failure
of their query into "could not be read", a fault of their own question too.

## The decision

- **One rule, the lake's own**: a status of **500 and above** from the lake's service is the lake failing ("could
  not be read"); below 500 the lake answered, and the question or the caller's set-up is at fault (400, 422, and
  the service-token check's 401 and 403): the error goes on and shows as one. `readiness.is_unread` is again
  "a reader's `LakeUnread`, or `lake_down`"; the special reading of D-712 is gone.
- **The two readers decide the same way** (`readiness._query_failed`). Through the lake's client the status
  decides. A space other than the hospital's reads its lake as a library, which raises the lake's own classes;
  there the lake's own rule decides (`lake.store.query_failure_status`: what the engine files under a wrong
  statement or wrong data is the question's; a snapshot not there, a limit, an I/O error, anything unexpected is
  the lake's).
- So the patient check, the counts and the readiness answer say `lake_unread` when the lake failed, and fail
  visibly when their own question is wrong. Lane B2's list of the callers of `query()` says so for the two
  readers, which it had marked open.

## What it does not do

- **The readiness page can now fail** (500) where it said "could not be read": when one of its two fixed
  questions is itself wrong for the lake it asks (a column or table the question names is not there). That is a
  fault of this code against that lake and should be seen; it is the purpose of the change.
- **The service-token check's 503** (a box with no token configured) reads as the lake failing: it is not the
  lake's word, as D-675 says, and cannot be told from it by the status. Said; not changed.
- A library lake's unexpected error (a fault of the code inside the lake's own reader) is 500 by the lake's rule
  and reads as "could not be read".
- The routes catch the same error types as before (a service error, an HTTP error, `LakeUnread`); a library
  lake's own classes raised by the patient check's engine go on as errors there, as before.
- No page and no word changes.

## Review

See "What the adversarial review changed" when the review is in.

## Reuse check

`lake_down` (D-709), `LakeQueryFailed.status` (D-673) and `lake.store.query_failure_status` (D-675). One small
function is added (`readiness._query_failed`); the special case of D-712 is removed.

## Dropped (D-311)

No sign-off step.
