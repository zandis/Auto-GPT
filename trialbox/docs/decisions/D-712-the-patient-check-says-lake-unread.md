# D-712 The patient check says the lake could not be read when its queries fail, and another service's error is not that

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
a statement the lake **rejected** (a 400, `SqlRejected`: a fault of the criteria's SQL or of this code) and
**another service's** error were both answered "the lake could not be read", which is untrue of them and hides
them.

## The decision

- **One question decides** (`readiness.is_unread`): a reader raised `LakeUnread`; or the lake fails or does not
  answer (`lake_down`: its health not read, an answer of 500 and above, no answer, and now a 200 that is not the
  lake's answer, `LakeBadAnswer`); or **a query the lake did not answer with a table, whatever its status but
  400**. The readiness answer and the two routes say `lake_unread` only then.
- **Why every status but 400.** The lake answers its own failures of a query with 404 and 422 (a snapshot file
  gone or damaged, a snapshot replaced under the query, a limit), never with 5xx, and the engine's complaint
  about the question is 422 too: the status does not tell them apart. So a failed query is read as "could not
  be read" (the page says to try again and to tell the administrator if it stays), and the route logs the
  type and the status each time, so a fault of the question is not lost. 400 is the lake rejecting the
  statement itself and goes on as an error; so does another service's error. Each by test, through the routes.
- The same question decides a saved change's "publish waits for the lake" (D-709): a bad answer of the lake now
  counts as the lake failing there too.

## What it does not do

- The readiness answer's two fixed questions (the unknown share, the feed tier) still read any failure of their
  query as "could not be read": they are the box's own questions about a snapshot the lake named, and that page
  should say so rather than fail.
- No page changes: the pages of D-709 already show `lake_unread`.
- Nothing in the lake's client is changed (lane B2's).

## What the adversarial review changed

One review by a fresh reviewer, who drove the real lake service through its client and the set-up routes.
Verdict: fix first, one finding.

- **The first rule read the status: 500 and above was "the lake failing", 4xx "a refusal".** The real lake never
  answers a failed query with 5xx: a snapshot file removed gave 404 and a damaged one 422, and the patient check
  answered 500 for both while the readiness answer and the counts said `lake_unread` for the same lake. The rule
  is the one above now; the cases are in the test with the statuses the lake really gives (404, 422, 401, 503).
- The counts route's own branch had no test; it has one.
- Ran and sound: no "busy" answer exists on the lake's query route; the saved change's waiting with a bad answer
  of the lake is not silent (the tick logs each failure) and not stuck; the readiness answer gained no new 500;
  the three tests fail on the base or with the question answered always yes or always no.
- **For lane B2 (sent to the integrator):** the lake's query route answers its own failures (I/O, a stale
  snapshot) and the engine's complaint about the question with the same 422. A 5xx for the lake's own failures
  would let a caller tell them apart; until then a fault of the question at the patient check reads as "could
  not be read" and is in the log.
- Not checked by the reviewer: a real HTTP deployment (a proxy's statuses).

## Reuse check

`lake_down` (D-709) and the lake's typed errors (D-673); one small function is added (`readiness.is_unread`).

## Dropped (D-311)

No sign-off step.
