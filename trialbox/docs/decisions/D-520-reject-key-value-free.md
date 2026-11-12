# D-520 The key a rejected row is counted under holds no feed value

- **Task:** NEW-B-1 (a finding sent to the night and capacity lane on 2026-11-12, confirmed by running)
- **PR:** this branch (`agent/NEW-B-1-reject-key-value-free`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** STD-025 (T-615a: a row the mapping cannot read is rejected and counted by reason; the table goes
  on), D-271 (a held night), the data-handling rule "no feed value in a log"

## Context

A row the mapping cannot read is rejected and counted under a key (`adapter/pipeline.py`). The key was the
mapper's message with quoted text replaced by a regex (`'...'` or `"..."` becomes `<value>`). The mapper writes the
value with `repr`. For a value that holds quote marks of both kinds `repr` escapes one of them; the regex then ends
the "quoted value" at the escaped mark and a fragment of the feed's value stays in the key. The key is written to
`completeness.json`, to the night's error (and so to the ingest report and the audit) and to the log. Run on master:
the date column value `it's "CHART-7731" on 2026` gave the key `unparseable date <value>s <value> on 2026'`.

## Decision

1. **The key is the exception's type and its message up to the first value**: `adapter.pipeline.reject_key`. The
   message is cut at its first quote mark (ASCII or typographic, or a back-tick) and everything from there on is
   `<value>`: no pairing of marks, so no value can end the cut early. A run of digits before the cut is `<n>` (a
   number the message wrote without quote marks).
2. **The type comes first** (`MappingError: unparseable datetime <value>`): two mappers that word a message the same
   way are still told apart, and a message that is only a value still has a key.
3. **A rule for whoever writes a row-level error in the mapping:** say what is wrong before the value, and write
   the value with `repr`. Text after the value is not kept.

## Consequences

- The keys in `completeness.json` and in the night's error change form (the type is in front). One existing test
  pins a key and follows (`tests/unit/test_ssmix2_hardening.py`).
- Counts per reason can merge where two messages differed only after the value (for example the column named after
  it). The count per table and the hold rule (`REJECT_MAX_PCT`) are unchanged.

## Not decided here

- A value a message writes without quote marks and without digits (a bare word) is not recognised as a value. No
  row-level error of the mapping does that today; a reason code on the exception (`MappingError.reason`) would
  close it for good and is the mapping's (lane E).
- The back-fill counts rejects without a reason (`adapter/backfill.py`): nothing to scrub there.
