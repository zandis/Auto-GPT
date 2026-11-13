# D-490 A generation: the snapshot date plus a sequence number; a rebuild makes a new one, a job pins one

- **Task:** T-724 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.3, wave G; the night and capacity lane)
- **PR:** this branch (`agent/T-724-lake-generations`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Closes:** F-5 and the rest of F-1 of `docs/reviews/2026-11-12-architecture/lifecycle.md` (root cause S3: "the
  snapshot is a date rebuilt in place"); the open items "T-724" of D-462 and D-472 (a held snapshot's rebuild is
  refused, a build discarded at the swap)
- **Builds on:** D-383 and D-403 (a job pins and holds its snapshot), D-462 (one lake lock, the build beside the
  served files, the reader links), D-472 (the rebuild as a job), D-135 (the site's inputs joined at a rebuild)
- **Read by:** T-725 (every derived artefact records the generation it was built from), T-689 (the replay key),
  T-726

## Context

A lake snapshot was named by its date and rebuilt in place: a site publish built the served date again under the
same name, so "the snapshot of the 5th" meant different bytes before and after it. To keep a running job's reads
whole, a rebuild of a date a job held was refused (D-403), at its start or, after the whole build, at its swap
(D-462): the publish waited, and a build of minutes was thrown away. A finished job's record named a date whose
bytes had since changed, so a re-run could not be told from a changed lake (F-5).

## Decision

1. **A generation is `<date>.g<n>`**: the snapshot date and a sequence number, counted per date from 1. Every
   rebuild that reaches its swap makes the next one. Its file is `db/gen/<date>.g<n>.duckdb`, written once and
   never written again; its record `db/gen/<date>.g<n>.json` holds the date, the number, the cause (`night` for a
   date's first build, `republish` for a later one of the same date, or the word the caller gave), the SHA-256 of
   the file (the lake's hash) and the time. No patient data.
2. **The date stays as an alias.** `db/<date>.duckdb` is a hard link to the date's newest generation, replaced
   atomically at the swap (a file system without hard links gets a copy). Everything that reads by date reads as
   before: `CURRENT`, the sidecar, the Parquet folder, the reader links of D-462, the backup. "The newest
   generation of a date" is the one the alias names, not the highest number: a swap cut short between the
   generation's file and the alias leaves the date on the generation it had.
3. **A job pins a generation.** `Lake.hold(snapshot, holder, pin=True)` resolves the date to its newest generation
   under the lake lock, records it in the hold and returns it; the job's lake (`orchestrator.jobs.PinnedLake`)
   names that generation in every query, note search and vector read, and writes it into the job's record
   (`options.lake_generation`). A job that is started again after a restart pins the generation its record names;
   when that generation is gone the job fails with a message: it never reads two generations.
4. **A generation hold never blocks a rebuild.** A rebuild of a date whose generation a job reads makes the next
   generation and moves the alias; the held file is untouched and is not deleted while the hold lives. The refusal
   `SnapshotHeld` stays only for a hold on the date itself (`hold(...)` without `pin`: a caller that reads by date
   and wants the date still), which is what D-403 and D-462 built and their tests hold.
5. **Old generations go at the swap.** After the alias moved, every generation of that date that is neither the
   newest nor held is deleted with its record. Pruning a date (`adapter.pipeline.prune_snapshots`) deletes its
   generations; a date any hold names, by date or by generation, is not pruned, as before.
6. **Over HTTP** the generation travels as the header `X-TB-Lake-Generation` beside the request's date, so the
   request contracts are unchanged; `POST /holds` takes `pin` and answers the generation.

## Handed over by T-723 (D-489): three acceptance items of this card

By the integrator's ruling of 2026-11-12 (review of T-723, MED-3) the three things D-472 and D-462 had left to
T-723 are this card's, written here so they do not fall between the two:

- **(a) The site publish's record of a publish in progress** (`sitesetup/main/publishing.json`, D-472: "T-723
  replaces it with its own row and keeps the rule: follow, do not restart"). **Not built.** The record stays as it
  is; the rule holds. A data-operations row for a site publish needs the site set-up service to write the
  `dataops` schema, which it does not reach today; see the pull request's "Not done".
- **(b) A newer night promoted over a site publish's facts** (D-462's guess: the site publish's `unchanged` branch
  compares the facts' digest, not what the served night was built with). **Verified and fixed.** A generation's
  record keeps the hash of the site's own inputs it was built with (`site`); the lake says whether the generation
  it serves holds the inputs it stores now (`Lake.site_in_sync`, in `GET /generations/<date>`); the site publish
  asks before it answers "unchanged" and publishes again when the answer is no. "Not known" (a date built before
  generations) keeps the old answer.
- **(c) A named "busy" state of the night's record** (D-462). The night's record names it since T-723 (the step
  state `busy` in `publish.json` and in the data-operations row's `detail.publish`), and with generations a job
  that pins a generation no longer makes the lake busy at all. **Not built:** a row state of its own (the row of a
  busy night is FAILED with that detail); it needs a change of the `batch` table's check and a migration.

## After the review of #318 (with T-723's build without promote on master)

8. **A generation's name is never given to other bytes, a restore included.** The backup keeps the generations'
   records (`db/gen/*.json`: name, number, cause, hash; no patient data) and not their files. A generation is
   numbered after every file **and** every record of its date, and the record with the highest number stays when
   its file is swept. After a restore, a date whose bytes have the hash of a record gets that record's name back;
   a job started again whose generation's file is gone is told so (it never reads the date's newest in its place).
   A backup made before this card has no records: its dates are adopted as generation 1 again.
9. **The served date is not built without promote.** The date's own file is what the box serves, so a build
   "without promote" of the served date was served the moment it was swapped in. It is refused before anything
   is built; a publish's re-run of the served night already builds it with promote, in one step (D-489).
10. **A promotion can name the generation it promotes.** `promote_built(date, generation)` and `POST /promote`
    with `generation` refuse (409) when the date names another generation now: it was built again since. The
    rebuild job's answer and the in-process client's carry the generation. **Owed:** the adapter's publish does
    not pass it yet (the contract's `RebuildResult` has no such field and `publish.json` does not record it); until
    then the promotion without a name is as T-723 left it.
11. **Point 4, said exactly:** a generation hold never blocks the *lake's* rebuild. The adapter's publish still
    answers "lake busy" for a re-run of the served night while a job holds it (`adapter/publish.py`, review F-3 of
    T-723): safe, and stricter than the lake needs. Making the two agree is a follow-up.

## Consequences

- A job's reads are the same bytes from its first query to its last whatever is published meanwhile, without the
  publish waiting for it.
- A date costs one file per generation that is the newest or held; the alias is a link, not a copy.
- The site publish's own wait for running jobs (`sitesetup.service`, D-403's batch) is not removed here: see the
  pull request's "Not done".

## Not decided here

- Keeping a generation for a finished job's re-run (it is deleted once nobody holds it and a newer one exists).
- The site inputs' digest in the generation's record (D-462's guess about a night promoted over a publish).
