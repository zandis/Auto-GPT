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
  - **the key goes to a stick and to paper:** step 1 writes the key file and the printable sheet to the stick, step 2
    reads both back (below);
  - **two people:** `--operator` and `--witness`, two different people (compared after NFKC, white space collapsed,
    case folded), both named in the event;
  - **audited:** the event `backup.key_ceremony` goes through the orchestrator's audit journal before `backup.pub`
    exists, so no backup can use a key the audit does not name;
  - **no key in the database or in logs:** the event holds the fingerprint, the two names, the site and the words
    "key file and sheet read back", never the key; no key byte is put in an argument, the environment, an exception
    text, an output line, a log or any file off the stick.
  The card's "KEK preset" and "shares printed" are `python -m tools.keys init`, `escrow-shares` and
  `ceremony-record` (D-893, D-894), unchanged here; "pages" is a host command by the owner's ruling of 2026-11-19.
- **Decision:** one host command, `python -m tools.backup_key_ceremony --stick <mounted folder> --operator "<name>"
  --witness "<name>" [--lang ja|zh-TW]` (`tools/backup_key_ceremony.py`), as root, in four steps:
  1. **the stick:** the X25519 key pair is made in memory (as `trialbox backup-keygen` makes it, D-126) and written to
     the stick as `trialbox-backup.key` (the `backup-keygen` format; `restore --key` reads it) and
     `trialbox-backup-key-paper.txt` (the sheet: a head in en, ja and zh-TW, the site, the date, the fingerprint, the
     key in lines of four four-letter groups, each line ending with four check letters, format `tb-backup-paper/1`).
     Each file is made new (`O_CREAT|O_EXCL|O_NOFOLLOW`, mode 0600) in the stick's folder held open, written whole,
     synced, read back from the same descriptor; then the folder is synced;
  2. **read back:** both files are opened again by name through the folder held open; each must be the inode written
     (and the bytes written in this run); the key file's key, the sheet's key (every line's check letters, the order
     and the fingerprint) and the key made must be one key, and the sheet's site this box's (`TB_SITE_ID`). From here
     on the command holds only the public key: the private key is a local of the step that made it;
  3. **the journal:** `backup.key_ceremony` is appended through the orchestrator, as `trialbox audit-sign` records
     `audit.head_signed` (`tools/trialbox/audit_heads.py`, `docker compose exec -T orchestrator python -c ...`,
     `TB_COMPOSE` as there): the code run there refuses unless the orchestrator's writer is the journal
     (`DbAuditWriter`, `TB_AUDIT_WRITER=db`); the event's family `backup` is one the orchestrator's database role may
     send (`tb_common.audit_writer.ROLE_EVENTS`). Root writes nothing in the audit folder and forks no helper of its
     own;
  4. **backup.pub, last:** written whole and synced in an unnamed file of the fixed folder (`O_TMPFILE`), then given
     its name by a link, which fails when the name exists (the effect of `O_EXCL`, and a reader never sees it half
     written); the folder is synced and the file read back.
  - **Before step 1, refused with nothing written:** not root; one name or none, a name that is not one printable line
    of at most 100 characters, or one person twice; `TB_BACKUP_PUBKEY` naming another file than the fixed one;
    `deploy/secrets` of this checkout missing, or not root's alone (owned by root, written by no one else; opened
    with `O_NOFOLLOW` and checked on the descriptor); `backup.pub` there (condition 2: "refused: the ceremony is done
    already", with its fingerprint); no orchestrator journal (condition 3: the orchestrator not answering, or writing
    the audit itself); no stick at the folder; a folder that is not on a removable stick of its own (H2, below); a
    stick folder that is not root's alone (a FAT stick is mounted `-o uid=0,gid=0,umask=077,nodev,nosuid,noexec`).
  - **The stick is hostile.** Every name on it is opened through the folder held open (`dir_fd`), never through a
    link (`O_NOFOLLOW`; a name that is there is first looked at without following it, so a device, a pipe, a folder
    or a link is refused before it is opened), and must be a plain file of one name (`st_nlink` 1), on the folder's
    filesystem, root's, with no bit for the group or others, checked on the open descriptor. A file the filesystem
    shows wider (a FAT stick mounted with a wide mask) is refused before a byte of the key is written; the empty file
    is kept and the same command finishes in it once the stick is mounted as said.
  - **H1 (review of ae382e0e):** the first statement of `main()` makes the process not dumpable
    (`prctl(PR_SET_DUMPABLE, 0)`, which also stops a piped core handler) and sets `RLIMIT_CORE` to 0, before any key
    exists; a failure there stops the command.
  - **H2 (review of ae382e0e): whole disks, not filesystem ids.** The stick's folder's device and the devices of `/`
    and of the public key's folder are each resolved to their whole disks through `/sys/dev/block/<major>:<minor>`
    (`/sys/class/block`): a partition to its parent disk, a mapped device (LVM, LUKS, RAID) through its `slaves`
    down to theirs; an anonymous device (btrfs) through its mount's source in `/proc/self/mountinfo`. The stick is
    refused unless its disks are known, removable (`removable` 1, or on USB), and share no disk with the box's
    folders; a disk that cannot be told on either side is refused. Another partition of a USB-booted system disk is
    therefore refused. `tools/key_escrow.py` is not changed.
  - **M6 (review of ae382e0e):** a folder sync that fails stops the step, whatever the error, `EINVAL` and `ENOTSUP`
    included: the stick's folder at step 1 (no journal event, no `backup.pub`), the public key's folder at step 4
    (said as "made but not confirmed on disk").
  - **M7 and the audit precheck of that review:** gone with the audit reading; the once-only check reads no audit.
  - **M8 (review of ae382e0e):** the test's leak scan finds the key in any grouping: besides the bytes, hex, base64
    and base32, it removes every character outside the base32 alphabet from the text and looks for each full line of
    the sheet; a test shows it finds the key file and the sheet themselves.
- **Every end state, and what is said** (each text in en, ja and zh-TW; exit 0 only for "done"):

  | Stopped | What is on the stick / the box | Said | The same command again with the same stick |
  | --- | --- | --- | --- |
  | a refusal before step 1 | nothing written | the reason, "nothing was written" | the same refusal until it is fixed |
  | in step 1 (an error) | the key file, perhaps the sheet | "stopped at step 1 of 4 (errno) ... run the same command again with the same stick" | reads the key file and finishes |
  | killed in step 1 | the key file, perhaps the sheet | (nothing: killed) | reads the key file and finishes |
  | in or after step 2 | both files | as step 1, "step 2" | reads both and finishes |
  | in step 3 | both files; the event perhaps journalled | "the journal did not confirm the event (it may hold it or not)" | records the event again and finishes |
  | in step 4 before the link | both files, the event | "stopped at step 4 ... backup.pub was not made" | records again and finishes |
  | after the link, folder sync failed | both files, the event, `backup.pub` | "made but not confirmed on disk" | "refused: done already" if it is there, else finishes |
  | done | both files, the event, `backup.pub` | the closing text (unmount, print, seal; the abandoned-stick sentence) | "refused: done already" |
  | interrupted (Ctrl-C) | any of the above | "nothing is undone and nothing is deleted; run the same command again" | as above |

  A stick that cannot finish a run (a key file that is not a whole key, as a power cut while it is written can
  leave; a sheet of another key or another site; a name that is not a plain file) is refused with nothing changed:
  the key on it never became the box's key and stays until IT wipes the stick; the command is then run with an empty
  stick. Run again with another, empty stick, the command starts a new run with a new key; the closing text says that
  a key left on an earlier stick never became the box's key and stays there until IT wipes it. So the journal can hold
  a `backup.key_ceremony` whose key never reached `backup.pub` (an abandoned run), and two events with one
  fingerprint (a rerun after step 3); each event is true when written: that key was on the stick and read back.
- **The invariant, and its test:** "`backup.pub` exists only if the journal holds the ceremony event for its key and
  the stick's key file and sheet were read back equal to that key; and no private key byte appears in the journal,
  stdout/stderr, or any file off the stick". It is asserted by
  `tests/unit/test_backup_key_ceremony.py::test_invariant_backup_pub_only_after_journal_and_read_back_across_every_stop_point`:
  the command in a process of its own is killed with SIGKILL right after each stop point (the key file written, step
  1, step 2, step 3, the link of step 4), the invariant checked in that state, the same command run again with the same
  stick (it finishes with the same key, or says it is done), the invariant checked again, and a third run refused.
- **Deliberately not built:** an undo, a removal of anything, an "undone" event; end-state messages that guess what
  happened (each stop says the one step it was at); root writing in the audit folder, a forked helper, the once-only
  check read from the audit trail; a `--public`, `--audit-dir` or `--secrets` option; a reader of a sheet typed back
  by a person (the check letters allow one); a printer; a console page; a rotation (RUNBOOK §25).
- **What is left, said here:** the read-back goes through the kernel, so it may be served from the page cache (the
  folder and files are synced first; the closing text says to unmount before pulling the stick); a key file torn by a
  power cut while it is written makes that stick unable to finish (refused, as above); the private key is a Python
  `bytes` that cannot be wiped, so it lives until the step that made it returns, in a process that is not dumpable;
  `deploy/secrets` must be on a filesystem with `O_TMPFILE` (ext4, xfs, btrfs, tmpfs), else step 4 stops with
  `EOPNOTSUPP`; a real stick, a real orchestrator and a real journal were not used by the tests.
- **Open follow-ups (a later docs card):** the install and the other runbooks still name `trialbox backup-keygen` for
  the one-time key (`deploy/install.sh`, runbook 05, runbook 01 step 9, §1 and §4 step 1 of
  `docs/security/10-key-ceremony-and-escrow.md`); its §7 describes this command.
- **Held by:** `tests/unit/test_backup_key_ceremony.py` (as root and as another user): the invariant test above; the
  whole run (the key file read by `backup.load_private`, the event's fields, the closing text, one name in the folder,
  the journal called to check and to record); H1 (a spy on the key's making sees not dumpable and core 0, and
  `harden()` is the first statement of `main()`); each refusal with nothing written; a link, a dangling link, a second
  name, a pipe and a folder at the key file's name; a stick showing 0644 refused and then finished; a rerun with
  another empty stick (the first stick unchanged, the sentence said); a torn key file, another site's sheet, another
  key's sheet and swapped lines refused unchanged; M6 at both folders; H2 on a made-up `/sys`; the orchestrator's
  code against a file-mode and a journal writer; the key forms against `backup-keygen`'s; the texts in three
  languages; the command line.
