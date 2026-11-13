# D-537 Every file name in a backup is stored with its own bytes, also the second name of one file

- **Task:** NEW-B-17 (the nightly's oldest red: `backup-drill` and `update-drill`, "backup content does not match
  its manifest: 1 changed, 0 unlisted", first read on the run of 2026-11-12)
- **PR:** this branch (`agent/NEW-B-17-backup-drill-manifest`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-187 (layout 2: every member hashed from the stream), D-462 (a reader's hard link to a snapshot
  file), T-724 / D-490 (a date's file is a hard link to its newest generation), NEW-B-14 (a mismatch names files)

## Context

`make backup-drill`, run locally on train 6 (master `96f955f0` and the train's cards), fails as the nightly did,
and since NEW-B-14 says where:

    backup content does not match its manifest: 2 changed, 0 unlisted; changed:
    dirs/box/orch/sitesetup/newsite/lake/db/2026-11-02.duckdb,
    dirs/box/orch/sitesetup/newsite/lake/db/gen/2026-11-02.g25.duckdb

The site set-up keeps a work lake of its own under the orchestrator's data folder. The backup's lake rules
(`select_files`) apply to the directory named `lake` only; every other directory is taken whole, so the work
lake's `db/.open/<identity>/<date>.duckdb` (D-462), `db/<date>.duckdb` and `db/gen/<date>.g<n>.duckdb` (D-490) all
go in. They are three names of one file. Python's tar writer remembers every file with more than one name and
writes each later name as a **link member with no bytes**; `_add` hashed what it had streamed for that member,
which was nothing. The manifest therefore named the sha256 of the empty string and size 0 for a file that a
restore writes whole (the link is followed), and the check after the backup failed. Nothing was wrong with the
bytes on disk, and nothing changed during the backup: the manifest was wrong about what it had stored.

"1 changed" on the run of 2026-11-12 is the same thing before generations were on that master: two names (the
reader's link and the date's file), the second one wrong.

A backup written so is refused by `trialbox restore` and `backup-verify` (`unpack`). **The nightly did not
notice**: `backup_schedule.nightly` has no private key and never opens what it wrote; it checks the sidecar and
that the copies agree. So on a box with a site set-up work lake each nightly backup was recorded as good, older
ones were pruned against it, and none of them could be restored. Only the drills, which hold a key, saw it.

## Decision

1. **`_add` never writes a link member.** When the tar writer reports a file as a link to an earlier member, the
   member is made a regular file again with the file's size, and its bytes are streamed and hashed as for any
   other file. Every name in a backup stands alone: no member needs another member to be read.
2. **A backup written before this change is still read** (`_second_names`, in `unpack`): an entry that is
   exactly the fault (the hash of nothing, size 0, and the extracted file is the same file as a listed one whose
   own hash holds: the extraction made the name a link to it) takes that file's hash and size. Its bytes were
   always whole. Any other mismatch is refused as before.
3. Nothing else changes: the retry on a file that changed under the read, the append-only rule and the lake's
   rules are as they were.

## Consequences

- A file with two names inside directories taken whole is stored once per name. For the site set-up's work lake
  that is each date's DuckDB file under its date name, under every generation file kept, and under each reader's
  link. How large a work lake gets on a real box was not measured here, nor whether the backup's size and time
  estimates count such a file once or per name; the choice that would store each date once is named below.
- The two names are read one after the other, so a file rewritten in place between the two reads is stored with
  different bytes under its two names; each matches its own manifest entry.
- A restore writes each name as a file of its own, not as links. Checked by running on a restored work lake: the
  date keeps the generation it had (no new generation is adopted, no number is given twice), told by its hash
  (D-490). Until that date is next rebuilt, each question "which generation is this date" hashes the whole date
  file (the quick answer is "the same file", which a copy is not), and the reader's link of the old file stays on
  disk as a copy until the date is rebuilt or pruned; readers get a new link and read the right file.
- The nightly still does not open what it writes. A fault of this kind is seen by the drills and by
  `backup-verify` only.

## Not decided here

- Whether a work lake under the orchestrator's folder should follow the lake's rules (no reader links, no
  generation files, no spill), which would store each date once. It is a rule about what a backup keeps, for the
  owner of the site set-up and the integrator to place.
- Whether the nightly should check what it wrote without the private key (it cannot decrypt; the member hashes
  are inside the encrypted stream).
- Symbolic links in a directory taken whole are left out of a backup and are not counted among what was left out
  (as before this change): a separate gap, sent as a finding.
