# D-749 A SCREEN run's excluded patients are written one line each, and read without loading the list

- **Task:** NEW-B-48, T-694 part 5 (F-36 of `docs/reviews/2026-11-11-scale-timeouts.md`; PERF-030), the writers
  (lane B2); the console's readers are lane C2's (the integrator's split, #593/#639)
- **PR:** this branch (`agent/NEW-B-48-excluded-patients-streamed`)
- **Date:** 2026-11-15
- **Status:** accepted
- **Builds on:** P-04 / D-143 (the excluded list, console only, never mailed), D-652 / D-653 (its header's "not
  read" fields), D-642 (the micro-batch's sources)

## Context

SCREEN wrote every excluded patient into one JSON document (`json.dumps(indent=1)`), and every micro-batch read the
whole document again to collect patient ids: about 85 MB at 50,000 patients and 850 MB at 500,000, and five to ten
times that as Python objects. The not-matched sample read it whole too.

## Decision

1. **`excluded_<ruleset>_v<version>.jsonl`** (`orchestrator/excluded.py`): UTF-8, one JSON object per line, keys
   sorted; a header line (`{"kind": "header", "format": 1, …}`: the old document's top-level fields), one line per
   excluded patient (`{"kind": "row", "pid", "criteria", "actions"}`: the old `rows` entries, in order), an end line
   (`{"kind": "end", "rows": <count>}`). A file without its end, or whose count is not its rows', was cut off: the
   readers raise `Incomplete`, never a short list. (The format was posted for lane C2 on the inbox, #639.)
2. **The readers here take the lines when a run has them**, else the old document (a run of before): the micro-batch
   reads only the ids, one line at a time (its key, the stored file's name, ends `.jsonl`); the not-matched sample
   reads the document from the lines.
3. **The old document stays beside the lines** until lane C2's console readers take the lines (their card); a later
   card then stops writing it. Both are `phi`, sent to nobody.

## Not in this card

The object store takes and gives whole blobs (each is encrypted as one), so the file is still built and read as one
blob: what goes is the list of Python objects on reading and the one large document on writing. The verdicts of every
scoped patient that `run_screen` keeps (F-36's other half: full verdicts for listed patients only) is unchanged.

## Tests

`tests/unit/test_excluded_streamed.py` (7 tests; all fail on the parent): the file's lines; reading it back gives the
old document, and an old document is still read; a cut-off file (no end line) is said, by the full read and by the
ids; the ids are read line by line from either form; the names; the SCREEN job publishes both files with the same
rows, `phi`, to nobody; the micro-batch reads the ids of a list of lines. The micro-batch's and the console's existing
tests pass unchanged. No state change.
