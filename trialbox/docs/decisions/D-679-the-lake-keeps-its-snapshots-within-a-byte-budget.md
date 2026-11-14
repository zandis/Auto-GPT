# D-679 The lake keeps its snapshots within a byte budget

- **Task:** NEW-B-38 (deep review 2026-11-13, DATA-025, High; placed with lane B by the owner on 2026-11-13)
- **PR:** this branch (`agent/NEW-B-38-lake-byte-budget`)
- **Date:** 2026-11-14
- **Status:** accepted
- **Builds on:** SPEC §10.3 (the last N nightly snapshots and each month's last one for M months), D-403 (a job's
  hold keeps its snapshot), D-462 (a snapshot being rebuilt is left alone), D-529 (a night refused before it reads),
  T-611 (only nights that passed count)

## Context

The lake kept its snapshots by count only: 3 nightly and up to 36 month-end ones (NDJSON, Parquet, DuckDB and
generations each). The review measured a dense patient at 0.55 MB of NDJSON, 0.05 MB of Parquet and 0.23 MB of
DuckDB a snapshot: about 41 GB a snapshot at 50,000 patients, 1.6 TB for 39 of them against a 2 TB disk. Nothing
looked at the bytes, and nothing checked the free space before a night wrote its snapshot: a full disk was found
by the night that failed on it.

## Decision

1. **A byte budget for the lake's folder**: `TB_LAKE_BUDGET_MB` (declared); unset, **half the disk the lake is on**
   (`LAKE_DISK_SHARE`). The other half is for what shares that disk on a box (the database, the backup's staging,
   the logs) and for a night's build while the last one is still kept.
2. **After the count's pruning, while the lake is over its budget**, in this order:
   1. the **NDJSON files of the oldest month-end snapshot** go, then the next. Its folder stays with the night's
      reports and its `passed.json`, and gets `ndjson_removed.json`; its DuckDB and Parquet stay, so the lake still
      serves it (feasibility and cohort history read the DuckDB). It can **no longer be rebuilt** (a lake schema
      change leaves it refused by `LAKE-SCHEMA`; a back-fill does not bring that date's NDJSON back), and **no night
      merges over it**: `merge_base` skips a folder with the mark;
   2. when every month-end NDJSON is gone, the **oldest month-end snapshot whole**, then the next.
3. **Never dropped for the budget**: the served snapshot (`CURRENT`), the N nightly ones (the delta's merge base is
   the newest of them), and a snapshot a job holds (D-403). A snapshot being rebuilt is skipped, as before.
4. **A budget that cannot be met** (what must stay is larger) is logged as an error and kept in the night's audit
   event (`lake_budget`: the budget, the bytes used, the month-end NDJSON and snapshots removed, `unmet`, the
   sentence). The night is not held for it: its data is right; the disk is the steward's to grow. **A pruning that
   fails** (a file the count meets goes, a disk error) is said the same way (`lake_budget: {"error": <type>}`) and
   runs again after the next night: the night is already published, and its pruning never makes it a failed one.
   The byte count leaves out a file or folder that goes while it is counted, counts a file with several names
   once, and does not follow a symbolic link.
5. **The room for tonight**: before a night reads or writes anything, the free space on the lake's volume is
   compared with what the newest earlier night that passed (and still holds its NDJSON) took: its NDJSON, Parquet
   and DuckDB, not older generations. Less refuses the night (`NoRoomForNight`, "not enough free disk for tonight's
   snapshot: about 6.0 MB needed (snapshot ... took that), 3.0 MB free ..."), audited as `ingest.failed` with
   `refused: disk` (and a second `ingest.failed` with the error's type from the night's own handler, as a night of
   the future gets, D-529). The run record keeps the sentence and its numbers (state `refused`), and `adapter run`
   prints it and ends with 2. The first night has nothing to measure by.
6. **A budget setting that is not a whole number of MB above 0** refuses the night the same way, before it reads
   (`LakeBudgetError`, `refused: setting`): a typo is found by the first night, not after one was published.

## What a person sees differently

On a box over its budget: month-end snapshots that lost their NDJSON (said in the log and the night's event), and
in time fewer month-end snapshots. On a full disk: a night refused with the two numbers, instead of a night that
fails while writing. A box within its budget sees nothing new.

## What this does not do

- The owner's brief names "an erasure hold": no such hold exists on master. An erasure (opt-out) rewrites or
  withholds records; it does not hold a snapshot. Held generations are covered by the job holds (D-403), which name
  the date of the generation they hold. If an erasure hold is made, it joins the snapshots that are never dropped.
- Month-end NDJSON is not compressed (the review measured 263 MB to 23 MB gzipped): every reader of NDJSON would
  have to read it; a separate card if the budget is often unmet.
- The budget counts the lake's folder only (a file with several names once), not the database or the backups.
- A back-fill and the publish of an accepted held night do not check the room or the budget; the next night's
  pruning applies the budget.

## Tests

`tests/unit/test_lake_byte_budget.py` (18 tests; they fail on the parent, which has no budget):

- within the budget the count alone decides;
- over it, month-end NDJSON goes first, the oldest first, the DuckDB kept; then whole month-end snapshots, the
  oldest first; the nightly ones untouched;
- a budget that cannot be met keeps what must stay, logs and returns the sentence;
- a held month-end snapshot is never dropped;
- `prune_snapshots` still answers the snapshots removed whole;
- unset, the budget is half the lake's disk; a budget that is not a whole number of MB above 0 is refused;
- a night with less free space than the last snapshot took is refused before anything is written, and audited;
- after the review (five of these fail on the first commit): the NDJSON files go and the folder, its reports and
  its mark stay, the lake lists it and no night merges over it; a pruning that fails does not fail a published
  night; a budget setting that cannot be read refuses the night before it reads; the room is measured by the
  newest night that passed, said with one decimal; the run record keeps the refusal's numbers and `adapter run`
  ends with 2; a file with two names counted once and a file that goes while it is counted (these two guard the
  count: the first commit got both right by other means).

The existing pruning, hold, retention and ingest tests pass unchanged. No state change of its own: a refused night
writes nothing, the pruning deletes as it did, and a pruning cut short runs again after the next night.

## Review

One adversarial, read-only review by a fresh agent, by running (hand-built lakes, a real lake with generations,
a pinned hold and reader links, mutants of the branch's code, a thread making and deleting spill files during the
count). It verified: the byte count equals `du -sb` on a real lake and counts reader links once; a pinned
generation's date is kept; CURRENT, the nightly ones and a held newest night are kept; the next delta's merge base
is never touched; walking 2,000 files takes 0.02 s. Its findings, all taken (test first where a test can show it):
a bad setting or a file going during the count failed a published night (now said, never the night's failure, and
a bad setting refuses the night before it reads); the refusal's numbers were not kept in the run record and the
command line crashed on it; dropping the NDJSON removed the whole folder with the night's reports and
`passed.json`, so the lake forgot the night (now only the NDJSON files go, with a mark no night merges over); the
room was measured by the newest folder, a held one too, and with old generations; the tests did not cover
reader links; the record's claims on a back-fill and on "held" (it is refused). Not verified by it: a real
near-full disk; the batch row of a refused night.
