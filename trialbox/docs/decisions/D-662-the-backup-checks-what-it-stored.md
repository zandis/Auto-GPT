# D-662 The backup checks what it stored against its manifest before it is sealed

- **Task:** NEW-B-21 (finding 1 of NEW-B-17 / #449; the owner's decision of 2026-11-13, given in the integrator's
  session and passed on: the nightly backup verifies what it wrote, before encryption, without a private key; a
  backup that does not verify is recorded as failed, with the file names, never as good)
- **PR:** this branch (`agent/NEW-B-21-backup-verifies-what-it-wrote`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-187 (layout 2: every member hashed from the stream), D-537 (the hard-link fault; a mismatch
  names files), D-455 (the nightly's steps and their limits from measured speed)

## Context

The box holds only the public backup key. The nightly could therefore never open what it wrote: it checked the
file's sidecar and that the copies agree. When the manifest was wrong about what had been stored (D-537: the second
name of a hard-linked file listed with the hash of nothing), every nightly backup was recorded as good, older good
ones were pruned against it, and none could be restored. Only a drill with the private key saw it.

The manifest's hashes are taken from the bytes handed to the tar writer. Nothing compared them with what the tar
stream then held, which is what a restore reads.

## Decision

1. **The plain tar stream is read back while it is written** (`backup._StreamCheck`). Every byte the tar writer
   gives the compressor also goes down a pipe to a thread that reads it as a tar, as a restore does: a file member
   is hashed; a link member takes what it links to; a later member of a name replaces an earlier one. This is
   before compression and encryption, so no key is needed.
2. **When the tar is closed, what a restore would get is compared with the manifest**: each listed file's hash and
   size, and members the manifest does not list. On a mismatch, or when the stream cannot be read back at all,
   the backup is refused and the part file is removed: **nothing is written** that a restore, a prune or the
   "newest good backup" could pick up. The nightly records the run as failed; the earlier good backup stays the
   good one.
3. **The refusal names the files first and ends with the verdict and the counts** ("changed: a, b; the backup was
   not written: its content does not match its manifest (N changed, M unlisted)"). Every place that records an
   error keeps its end (the nightly its last 400 characters, the box's command runner its last 600): the verdict
   and the counts are never cut off, and as many names as fit are kept (with one to three names, all of them).
4. The check is of every backup the box makes with zstd (the nightly, the console's "Back up now", the copy kept
   before a restore). gzip, the format before D-149, is compressed inside the tar writer and is written by a test
   only: not checked.

## What it adds to the backup's time (measured)

Measured on this build machine (4 cores), on the lake of a dense-profile box (`tools.scale_gate`, 400 patients,
`TB_SCALE_PROFILE=dense`) five times over as folders of one backup: 317 files, 2.16 GB stored. Three runs each,
medians:

| | seconds | stored bytes per second |
| --- | --- | --- |
| without the check | 4.3 | about 500 MB/s |
| with the check | 8.6 | about 250 MB/s |

So the check about **doubles the time of the backup's own step** at this density on this machine: about 2 seconds
more per GB stored. The second hash of every byte, in one thread beside the writer, is the cost. A pipe as wide
as one chunk took it from 10.8 s to 8.6 s; reading the tar in larger blocks changed nothing and was not kept.

**The step limits do not change.** A step's limit is its bytes at `TB_BACKUP_MIN_MBPS` (5 MB/s, a tenth of the
30 to 50 MB/s measured for `pg_dump` on a box disk, D-455). With the check the backup's step still runs at fifty
times that floor here; on a box the disk and `pg_dump`, not this check, set the pace. The database dumps are
made before the tar and are not slowed.

## Consequences

- A fault of D-537's kind is found the night it happens, by the box itself, and is an alert (a failed nightly),
  not a backup that looks good.
- The check holds no file in memory: the pipe is the only buffer, and the writer waits for the reader.
- **What the check does not see**: anything after the plain stream. The compressor, the encryption and the disk
  are checked as before (the file is read back and compared with the hash taken while it was written; the
  copies with each other). A fault in decryption or decompression itself is still found only with the private
  key (`backup-verify`, the drills).
- **What it does not judge**: whether the bytes read from disk were the right ones (a file that changed under
  the read is handled by `_add`, as before), or whether the database dumps restore.
- **The check is of what `backup()` writes: file members.** It is not a second restore. For member kinds the
  backup never writes it can judge differently from a restore (run by the reviewer on hand-made streams: a link
  whose target is stored again later; a file and a folder of one name; directory and symbolic-link members, which
  the check reports and a restore accepts). The manifest member's own bytes are not compared.
- A reader thread that stopped for good would hold the backup until its step limit; no way to get it stuck was
  found (reviewer: 200 good and 200 failing backups, an interrupt with the pipe full, a full disk: no hang, no
  descriptor or thread left).
- A test that needs a backup with the old fault (to test that such a backup is still read, D-537) switches the
  check off to make one.

## Not decided here

- A drill that restores with the private key on a schedule (the hospital holds the key; RUNBOOK §5).
