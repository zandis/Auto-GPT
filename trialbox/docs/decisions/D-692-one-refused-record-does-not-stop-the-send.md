# D-692 One refused record does not stop the send

- **Task:** NEW-EDC-7 (deep-review finding EDC-007, **High**: one refused row stops the whole study's send)
- **PR:** this branch (`agent/NEW-EDC-7-per-record-fallback`), cut from NEW-EDC-8 (D-691, #602): the same function
- **Date:** 2026-11-14
- **Status:** proposed (merges on green CI and one adversarial review)
- **Builds on:** D-691 (the attempt ledger), D-555 (REDCap's error text is not passed on), D-690

## Context

The send put every record of the study into one REDCap import. REDCap refuses an import whole: one locked form,
one value its rules refuse, and no subject of the study was written. The send said "refused" with the kind of
error and nothing said which record was the cause. Month-end sends would fail for every subject because of one.
Case 2b of the review; shown by tests before the change.

## Decision

1. **The client says when REDCap refused.** An HTTP 400 answer with REDCap's error is `refused`: REDCap answered
   and nothing of the call applied. A call REDCap did not answer, a server error (5xx), the rate limit and a token
   refusal are not `refused` (the first two may have applied).
2. **A refused import of several rows is sent again one row at a time** (a row: record, event, instrument,
   instance; so a locked screening form does not hold the same subject's adverse event). Each row REDCap refuses
   gets a `refused` line per value, with the kind of error in the box's own words (never REDCap's text, D-555);
   the other rows are written and read back as before.
3. **When every record is refused, the send is refused** as before (loud), with the `refused` lines written.
4. **A call REDCap did not answer is not sent again row by row**: it may have applied, and D-691 reads it back on
   the next send. Met during the row-by-row pass, it stops the pass; the refusals met before it are ledgered
   first, then the send fails.
5. **A `refused` line closes the attempt** (D-691): REDCap said no, so a value a person types afterwards is theirs.
6. The send's audit line counts refused values as `records_refused` (an audit line's `refused` is the code of a
   send REDCap refused). A locked form has its kind ("a form of the record is locked"). The console's send pages count `refused`, and the
   trail names it, in three languages (lane C2's files).

## Not in this card

- **Reading a form's lock before the write.** REDCap's core API has no call that reads a lock (the review: an
  external module is needed). The per-record send is the answer that works on every instance; whether one locked
  form refuses the batch, and REDCap's exact sentence, are read on our instance (NEW-EDC-1, R3 of the review's run
  list). If the sentence differs, the kind falls back to "REDCap's own text is not shown" and the send still works.
- Rows sent one by one cost one call each, and only after a refusal. A batch refused for a reason every row shares
  (a field not in the project) costs one call per row; the rate limit met on the way stops the pass (point 4).

## The adversarial review (by running) and what it changed

| Finding | Severity | Outcome |
| --- | --- | --- |
| A non-refused error in the per-record pass dropped the refusals met before it: no `refused` line, the attempt stayed open, a person's later value was booked as TrialBox's | medium-high | fixed, test first (point 4) |
| A refused row held every other row of the same subject | low-medium | fixed, test first: the retry is by row |
| The audit line's `refused` count read as a refused send | low | fixed, test first: `records_refused` |
| A lock sentence naming a repeating instrument got the repeat kind | low | fixed, test first: the lock kind is matched first |
| One call per row when every row shares the reason | low | kept (not in this card) |
| Whether a 400 means nothing applied, and whether a locked form gives 400 at all | open | read on our instance (NEW-EDC-1, R3); a lock skipped with 200 is caught by the read-back (`readback`) |

## Evidence

`tests/unit/test_edc_per_record_fallback.py`: case 2b (record 1 locked, record 2 written; the calls are the batch,
then one per record); every record refused is loud and ledgered; a refused record written once REDCap takes it; a
refusal closes the attempt; no answer is not retried row by row; the review's four cases; the client's `refused` for 400 and not for
no answer, 403, 429, 500, 503; the console counts it. Six of the first seven failed before the change; the review's four failed before its fixes.
