# D-1379 The backup-key ceremony in four resumable steps: the key to a stick and to paper, two people, journalled (10K-13)

- **Task:** lane K, plan 10 row 10K-13 (review 18, SO-13: "Key ceremony pages: backup key to stick and paper, KEK
  preset, shares printed, two people, audited"; proved by "No key written to the database or logs; the audit lists
  both names"). · **Date:** 2026-11-20
- **The owner's rulings:** 2026-11-19 20:20 UTC, "10K-13 backup-key ceremony on the host: yes"; 2026-11-20 10:30 UTC,
  after two independent reviews of the first build (pull request #1228, about 2,100 lines with an undo, a forked audit
  helper and root appending to the audit folder), the owner agreed to a smaller ceremony on four conditions:
  1. four resumable steps, no undo, nothing is ever deleted: a run cut short is finished by running the same command
     again with the same stick; a key from an abandoned run stays on its stick until IT wipes it, and the command's
     text and the runbook say so;
  2. "once" means the public key file `backup.pub` exists;
  3. the command refuses on a box with no orchestrator journal;
  4. the public key's folder is fixed and root-only.
  This decision replaces the design of #1228 under the same number.
- **What the card asks, and where it is met:**
  - **the key goes to a stick and to paper:** step 1 writes the key file and the printable sheet file to the stick,
    step 2 reads both back; the sheet says how to type it back for `restore --key` (below);
  - **two people:** `--operator` and `--witness`, two different names (compared after NFKC, white space collapsed,
    case folded), both in the event. The tool sees two typed names, not two people (limits, below);
  - **audited:** the event `backup.key_ceremony` goes through the orchestrator's audit journal, which must answer
    with its number, before this command makes `backup.pub`, so no backup can use a key made by this command that the
    journal does not name (a `backup.pub` made otherwise, by `trialbox backup-keygen`, is not covered);
  - **no key in the database or in logs:** the event holds the fingerprint, the two names, the site and the words
    "key file and sheet file read back after sync", never the key; no key byte is put in an argument, the
    environment, an exception text, an output line, a log or any file off the stick.
  The card's "KEK preset" and "shares printed" are `python -m tools.keys init`, `escrow-shares` and
  `ceremony-record` (D-893, D-894), unchanged here; "pages" is a host command by the owner's ruling of 2026-11-19.
- **Decision:** one host command, `python -m tools.backup_key_ceremony --stick <mounted folder> --operator "<name>"
  --witness "<name>" [--lang ja|zh-TW]` (`tools/backup_key_ceremony.py`), as root, one run at a time (an exclusive
  `flock` on the public key's folder for the whole run), in four steps:
  1. **the stick:** with no key file and no sheet on the stick, a temporary file `.trialbox-backup.key.<random>.part`
     is made (`O_EXCL`) and checked while empty, the X25519 key pair is made in memory (as `trialbox backup-keygen` makes it, D-126),
     and its **record** is written on the box: `deploy/secrets/backup-ceremony-<fingerprint>.pending` (fingerprint,
     public key, time; mode 0644; `O_EXCL`; synced; never removed). Then the key file (the `backup-keygen` format;
     `restore --key` reads it) and the sheet `trialbox-backup-key-paper.txt` (a head in en, ja and zh-TW that says how
     to restore from paper, the site, the date, the fingerprint, the key in lines of four four-letter groups between
     two bars, each line followed by four check letters, format `tb-backup-paper/1`) are each written into a temporary
     name beside the final one, synced, read back from the same descriptor with its cached pages dropped first
     (`posix_fadvise DONTNEED`), and only then renamed to the final name; then the folder is synced. So a final name
     never holds part of a file (review of 36c97bd1, H-4). A temporary file a run cut short left (by a kill or a power
     cut) **stays on the stick: it is never removed and never read again**, and a rerun writes a new one; it may hold
     part or all of a key that never became the box's key, and goes with the stick, which IT keeps sealed or wipes.
     (We chose to leave it rather than refuse a stick that holds one: refusing would stop the same-stick rerun the
     owner's first condition asks for.) A whole key file already on the stick is taken up again **only when the box
     holds its record** (a run of this box cut short), and it and the sheet are **synced again on every rerun** (H-3);
     any other key file, and a sheet without a key file, is refused before a key is made;
  2. **read back:** both files are opened again by name through the folder held open, their cached pages dropped
     first; each must be the inode written (and the bytes written in this run); the key file's key, the sheet's key
     (every line's check letters, the order and the fingerprint) and the key must be one, and the sheet's site this
     box's (`TB_SITE_ID`). From here on the command holds only the public key;
  3. **the journal:** `backup.key_ceremony` is appended through the orchestrator, as `trialbox audit-sign` records
     `audit.head_signed` (`tools/trialbox/audit_heads.py`, `docker compose exec -T orchestrator python -c ...`). The
     code run there refuses unless the orchestrator's writer is the journal (`DbAuditWriter`), and prints the number
     the journal gave the event (`journal.seq`, which only a stored row has); step 4 runs only after a positive number
     came back. The command line is fixed in the tool (`docker -H unix:///var/run/docker.sock compose
     --project-directory deploy`), the socket must be root's, and the call gets an environment with no `DOCKER_*` or
     `COMPOSE_*` setting but the local socket and an empty, temporary Docker config folder (removed after the call;
     it never holds anything of the key): a Docker context, host, TLS setting or `TB_COMPOSE` naming another box's
     journal cannot be used (H-1). The compose project is named on the command line (`-p`): the one project whose
     running orchestrator the local daemon shows as started from this checkout's deploy folder (its
     `com.docker.compose.project.working_dir` label), never a name from the environment; none, or more than one, is
     refused before anything is written, so the event cannot go to another deployment on the same daemon. Root writes nothing in the audit folder and forks no helper;
  4. **backup.pub, last:** written whole, mode 0644 whatever the umask, and synced in an unnamed file of the fixed
     folder (`O_TMPFILE`), then given its name by a link, which fails when the name exists (the effect of `O_EXCL`; a
     reader never sees it half written); the folder is synced and the file read back.
  - **Before step 1, refused with nothing written:** not root; one name or none, a name that is not one printable line
    of at most 100 characters, or one name twice; `TB_BACKUP_PUBKEY` naming another file than the fixed one;
    `deploy/secrets` of this checkout missing, a link, another account's or writable by others, or a folder above it
    that is a link, another account's, or writable by others without the sticky bit; another run going on; `backup.pub`
    there (condition 2: "refused: the ceremony is done already", with its fingerprint); a folder whose filesystem
    cannot make an `O_TMPFILE` (step 4 needs it; found here, not after the journal); no orchestrator journal
    (condition 3: the orchestrator not answering, writing the audit itself, **its journal's database not answering one
    connection, or that database not holding the journal's `audit.append` this role may call** (M-6)); no stick at the folder; a folder that is not on a removable stick of its own (H2, below); a
    stick folder that is another account's or writable by others (a FAT stick is mounted
    `-o uid=0,gid=0,umask=077,nodev,nosuid,noexec`).
  - **The stick is hostile.** Every name on it is opened through the folder held open (`dir_fd`), never through a
    link (`O_NOFOLLOW`; a name that is there is first looked at without following it, so a device, a pipe, a folder
    or a link is refused before it is opened), and must be a plain file of one name (`st_nlink` 1), at most 16 KiB, on
    the folder's filesystem, root's, with no bit for the group or others, checked on the open descriptor. An empty
    file the filesystem shows wider is refused before any key exists; a key file that holds the key and is shown
    wider is refused saying the key may be read by others and to unmount at once.
  - **H1:** the first statement of `main()` makes the process not dumpable (`prctl(PR_SET_DUMPABLE, 0)`, which also
    stops a piped core handler), sets `RLIMIT_CORE` to 0, and locks its memory now and later
    (`mlockall(MCL_CURRENT | MCL_FUTURE)`), before any key exists. When the lock is not granted the command goes on
    only if no swap area is in use (`/proc/swaps`; an unreadable list counts as swap on), and otherwise refuses with
    nothing written, in all three languages (H-5).
  - **H2: whole disks, not filesystem ids.** The stick's device and the devices of `/` and of the public key's folder
    are each resolved to their whole disks through `/sys/dev/block/<major>:<minor>`: a partition to its parent disk, a
    mapped device (LVM, LUKS, RAID) through its `slaves`; an anonymous device only through an absolute `/dev/` source
    of its mount that is a block node, never a `fuse.*` filesystem (`fuseblk` is). **The stick must be one block
    device** (H-2): not an anonymous device (btrfs, which can mirror onto an internal disk whatever member mountinfo
    names; FUSE; a network share), not a mapped device (no `slaves`) and not a member of one (no `holders`: md, LVM,
    LUKS); its one whole disk known, removable (`removable` 1, or on USB), sharing no disk with the box's folders, and
    **holding no other mounted filesystem** (a USB backup disk is not a stick). The stick's folder is also refused
    when it is a `TB_BACKUP_TARGETS` folder, inside one, holds one, or is on a target's filesystem (real paths and
    devices compared): the key never sits beside the backups it opens. `tools/key_escrow.py` is not changed.
  - **M6:** a folder sync that fails stops the step, whatever the error, `EINVAL` and `ENOTSUP` included.
  - **M8:** the test's leak scan finds the key in any grouping.
- **Every end state, and what is said** (each text in en, ja and zh-TW; exit 0 only for "done"):

  | Stopped | What is on the stick / the box | Said | The same command again with the same stick |
  | --- | --- | --- | --- |
  | a refusal before step 1 | nothing written | the reason, "nothing was written" | the same refusal until it is fixed |
  | after the record, before the key file is renamed | a temporary file (empty, or holding part or all of the key); the record | (killed) or "stopped at step 1" | a new key, a second record and a new temporary file; the old one stays, never the box's key |
  | in step 1, the key file renamed | the key file, perhaps the sheet or a temporary sheet; the record | "stopped at step 1 of 4 (errno) ... run the same command again with the same stick" | takes the key up (its record is here), syncs it again and finishes |
  | in or after step 2 | both files | as step 1, "step 2" | finishes |
  | in step 3 | both files; the event perhaps journalled | "the journal did not confirm the event (it may hold it or not)" | records the event again and finishes |
  | in step 4 before the link | both files, the event | "stopped at step 4 ... backup.pub was not made" | records again and finishes |
  | after the link, folder sync failed | both files, the event, `backup.pub` | "made but not confirmed on disk" | "refused: done already" if it is there, else finishes |
  | `backup.pub` made by someone else during the run | both files, the event | "appeared while this run went on ... not made by this run ... its key is not the box's key" | "refused: done already" |
  | done | both files, the event, `backup.pub` | the closing text with the journal number (unmount, print, seal; the abandoned-stick sentence) | "refused: done already" |
  | interrupted (Ctrl-C) | any of the above | "nothing is undone and nothing is deleted; run the same command again" | as above |

  A stick that cannot finish a run is refused, saying truthfully whether this run wrote to it: before any write in
  this run (a key file that is not a whole key, a sheet of another key or site, a name that is not a plain file, a
  file over 16 KiB) "this run wrote nothing to the stick"; after a write (a file that did not read back as written,
  or another inode at the name) "what this run wrote stays on the stick". Either way the key on it never became the
  box's key and stays until IT wipes the stick; the command is then run with an empty stick. Run again with another,
  empty stick, the command starts a new run with a new key and a second record; the closing text says that a key left
  on an earlier stick never became the box's key and stays there until IT wipes it. So the journal can hold a
  `backup.key_ceremony` whose key never reached `backup.pub` (an abandoned run), and two events with one fingerprint
  (a rerun after step 3); each event is true when written: that key was on the stick and read back after a sync.
- **The invariant, and its test:** "`backup.pub` exists only if the journal holds the ceremony event for its key and
  the stick's key file and sheet were read back equal to that key; and no private key byte appears in the journal,
  stdout/stderr, or any file off the stick" (also: the box holds that key's record). It is asserted by
  `tests/unit/test_backup_key_ceremony.py::test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point`:
  the command in a process of its own is killed with SIGKILL right after each stop point (the record, the key's
  temporary file written, its rename, the sheet's temporary file written, step 1, step 2, step 3, the link of step 4), or stopped by a failing journal (the container answers
  non-zero, the journal raises inside `append`, or a no-op answers success and stores nothing); the invariant is
  checked in that state, the same command is run again with the same stick, the invariant checked again, and a third
  run refused. A tool whose journal code swallowed a failed append and still claimed a number fails it.
- **Deliberately not built:** an undo, a removal of anything, an "undone" event; end-state messages that guess what
  happened (each stop says the one step it was at); root writing in the audit folder, a forked helper, the once-only
  check read from the audit trail; reading the event back from the audit chain (the orchestrator's role cannot read
  the journal; the number `audit.append` returns is the proof that the row is stored); a `--public`, `--audit-dir`,
  `--secrets` or compose option; a reader of a sheet typed back with its check letters (a person checks them by
  hand); a printer; a console page; a rotation (security document 10 §6).
- **Not protected against (limits, stated):** the witness is a typed name: nothing proves a second person was there
  (the printed ceremony record of `tools.keys ceremony-record`, signed by hand, remains the evidence); the private
  key is a Python `bytes`, not wiped: it lives in locked memory (or with no swap on) until the step that made it
  returns, in a process that is not dumpable; printing the sheet through the host's print spool (CUPS) can leave a copy
  there: §7 says to print from the stick on a printer that keeps no copy; `posix_fadvise` is a request: a filesystem
  may still serve the read-back from its cache, and a stick with a lying controller is not detected; a key file torn
  by a power cut while it is written makes that stick unable to finish (refused, as above); `deploy/secrets` must be
  on a filesystem with `O_TMPFILE` (ext4, xfs, btrfs, tmpfs); a root-on-ZFS host cannot tell its system disk and
  refuses every stick (availability only), and so does a btrfs or LUKS stick; root can always bypass the tool.
  Two more, which the integrator asks the owner to accept (second review of 6c33ba4f): **an ext4 stick whose journal
  is external, on a partition of an internal disk, is not detected** (with `data=journal` the key's blocks pass
  through that internal journal); and **swap switched on during the ceremony, after the memory lock was refused and
  no swap was on at the start, is not detected** (swap is checked once, at the start). Both need an administrator to
  set the host up so; §7 says to use a plain removable stick and to keep swap off or allow the memory lock. The tests used no real stick, `/sys`,
  orchestrator or journal.
- **Open follow-ups (a later docs card):** the install and the other runbooks still name `trialbox backup-keygen` for
  the one-time key (`deploy/install.sh`, runbook 05, runbook 01 step 9, runbook 25, §1 and §4 step 1 of
  `docs/security/10-key-ceremony-and-escrow.md`); its §7 describes this command; nothing at backup time compares
  `backup.pub` with the journal.
- **Held by:** `tests/unit/test_backup_key_ceremony.py` (as root and as another user): the invariant test above
  (stop points also after the key's temporary file is written, after its rename, and after the sheet's temporary
  file is written); the review of 36c97bd1: `test_h_1_the_journal_is_asked_on_the_local_socket_whatever_docker_context_is_set`,
  `test_h_2_a_stick_that_is_not_one_removable_block_device_is_refused`,
  `test_h_3_a_rerun_syncs_the_files_a_run_cut_short_left`,
  `test_h_4_a_write_cut_short_never_leaves_part_of_a_file_at_its_final_name`,
  `test_h_5_no_key_is_made_while_swap_is_on_and_memory_cannot_be_locked`, `[journal-without-schema]` and
  `[socket-not-roots]` among the refusals, `test_m_7_a_key_file_restore_would_reject_is_never_taken`; the second
  review of 6c33ba4f: `test_h2_second_review_a_stick_folder_beside_the_backups_is_refused`,
  `test_h3_second_review_the_compose_project_is_this_checkouts_own`; the
  whole run (the key file read by `backup.load_private`, the event's fields, the closing text with the journal number,
  the record and `backup.pub` 0644 under umask 077, `TB_COMPOSE=true` in the environment ignored); the paper sheet
  typed as it says gives the key to master's `backup.load_private`; H1 (a spy on the key's making sees not dumpable
  and core 0); each refusal with nothing written (a folder above the public one writable by others, another run
  holding the lock, no `O_TMPFILE`, a file-mode journal, the journal's database down, no orchestrator, a no-op
  orchestrator, and the others); a link, a dangling link, a second name, a pipe, a folder and a 1 GiB sparse file at
  the key file's name; a planted whole key file never adopted; a sheet without a key file refused before a key is
  made; a stick showing 0644 refused before any key and then finished; a key file shown to others after step 1 said
  as exposed; a file of another owner, a key file swapped for a copy (another inode), and a wrong first read on the
  writing descriptor each refused; a rerun with another empty stick (the first stick unchanged, two records, the
  sentence said); a torn key file, another site's sheet, another key's sheet and swapped lines refused unchanged; a
  journal timeout; `backup.pub` appearing during the run; M6 at both folders; H2, a USB disk holding another mount,
  and FUSE or relative mount sources on a made-up `/sys` and mountinfo; the orchestrator's code against a file-mode
  and a journal writer; the key forms against `backup-keygen`'s; the texts in three languages; the command line.
