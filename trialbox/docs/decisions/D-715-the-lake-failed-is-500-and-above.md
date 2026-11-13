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
- **Anything that is not an error of the lake's client reads as "could not be read" in the two readers**, on
  the hospital's lake as well as on a library lake: the lake's own rule files "anything nobody expected" under
  500. So a fault of the reader's own code after the answer (an answer with no row) still reads as the lake
  failing, as it did before this card. A statement the guard refuses is 400 through the service and 500 by that
  rule on a library lake; the two fixed statements cannot meet it.
- The counts route asks the readiness answer first, so it fails with it when a fixed question is wrong.
- The routes catch the same error types as before (a service error, an HTTP error, `LakeUnread`); a library
  lake's own classes raised by the patient check's engine go on as errors there, as before.
- No page and no word changes.

## What the adversarial review changed

One review by a fresh reviewer, who drove the real lake service through its client and the set-up routes.
Verdict: sound; nothing blocking.

- Ran: every failure of the lake tried (a snapshot file damaged or removed, a generation removed, a served name
  with no file, a real memory limit, and the lake's own error classes raised inside it) gave `lake_unread` on
  the readiness answer, the patient check and the counts, and no failed page; every fault of the question
  (binder, catalogue, conversion) gave an error and never "could not be read".
- A healthy box does not fail: a fresh lake, a fresh practice space and a space's library lake (which has every
  table) answer as before. Dropping a table by hand from a real snapshot makes the readiness answer fail; no
  way to reach that state in the product was found (the build makes every table).
- One test was missing and is added: the readiness route itself answers 500 for a wrong fixed question and the
  page that says so for a failed lake.
- The record understated one rule (the bullet above on what is not an error of the client): said.
- For lane B2 (sent to the integrator): a memory limit met while the snapshot is opened answers 500, not the
  503 of a limit; here it reads as unread either way.
- Not checked by the reviewer: a snapshot built by an older release; a lake in the middle of a rebuild; a real
  proxy or token registry.

## Reuse check

`lake_down` (D-709), `LakeQueryFailed.status` (D-673) and `lake.store.query_failure_status` (D-675). One small
function is added (`readiness._query_failed`); the special case of D-712 is removed.

## Dropped (D-311)

No sign-off step.
