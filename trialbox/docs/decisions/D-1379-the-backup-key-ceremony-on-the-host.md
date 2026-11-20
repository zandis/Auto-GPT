# D-1379 The backup-key ceremony on the host: the key to a stick and to paper, two people, audited (10K-13)

- **Task:** lane K, plan 10 row 10K-13 (review 18, SO-13: "Key ceremony pages: backup key to stick and paper, KEK
  preset, shares printed, two people, audited"; proved by "No key written to the database or logs; the audit lists
  both names"). · **Date:** 2026-11-19
- **The owner's ruling:** the card is a key export and a new power, so it waited for the owner. The owner ruled on
  2026-11-19 at 20:20 UTC: "10K-13 backup-key ceremony on the host: yes." This decision builds that and no more.
- **Decision:**
  - **One host command**, `python -m tools.backup_key_ceremony --stick <mounted folder> --operator "<name>"
    --witness "<name>"` (`tools/backup_key_ceremony.py`), run once on the box's host. It makes the backup key pair
    (X25519, as `trialbox backup-keygen` does, D-126) in memory.
  - **Who may run it:** root on the box's host (hospital IT types the commands as root, TB-SOP-03 §2), with two named
    people: the person who runs it (`--operator`) and a witness who is another person (`--witness`; two names are
    the same person when they are equal after NFKC, every run of white space, the ideographic space included, made
    one space, and case folding: `Ｔａｒｏ　Ｙａｍａｄａ`, `taro  YAMADA` and `Taro Yamada` are one person). Decision 97 (the site decides who administers the box) is kept: the site
    chooses the two people; the tool takes their names and checks only that there are two. Not root, a name missing,
    a name that is not one printable line of at most 100 characters, or one person twice: refused.
  - **What leaves the box, and in what form; nothing else:** the private key, written only to the removable stick
    named, as two files (created there or not at all and never through a link, written in full however short each
    write, synced; then the stick's folder is synced, a filesystem that cannot sync a folder by itself excepted). The
    closing text says to unmount (eject) the stick before pulling it out:
    - `trialbox-backup.key`: the key file in the format `backup-keygen` writes, so `restore --key` and
      `restore-drill --key` read it unchanged;
    - `trialbox-backup-key-paper.txt`: the paper sheet, to be printed: a head in en, ja and zh-TW, the site, the
      date, the key's fingerprint, and the key as four lines of base32 letters in groups of four (`n | ABCD EFGH IJKL
      MNOP | CHCK`), each line ending with four check letters (the first 20 bits of SHA-256 over the format, the line
      number and the line's letters). A mistyped letter, a letter outside the alphabet, a line left out, two lines
      swapped or a wrong fingerprint line is refused by `read_paper`, naming the line, never its letters (format
      `tb-backup-paper/1`).
  - **The stick that was checked is the stick written (after review of a1ed9c36, H1):** the stick's folder is opened
    once, as a folder descriptor, before the removable-media check, and held open for the whole run. The check is
    made on that open folder (`tools/key_escrow.media_problem` given `/proc/self/fd/<fd>`, which leads to the folder
    held open whatever is mounted at the path since; Linux only, as the box is), and its device is that descriptor's
    `fstat`. Both files are made in that folder (`dir_fd`), each `fstat`-compared to that device before a byte is
    written; the existing-name checks, the write probe, the folder's sync, the read-back (each file opened again by
    name in that folder and checked to be the same device and inode) and the undo go through the same descriptor. No
    path on the stick is resolved again after the check, so an unmount between the check and the writes cannot send
    the key to the box's disk under the mount point.
  - **The key's files are the key's alone (after review of a1ed9c36, H2): refused unless the mode holds.** Mode 0600
    is asked for, and then checked on the open file with `fstat`: no bit for the group or others, and owned by root
    (the user running the command). The write probe is checked the same way before anything is written, and each key
    file again right after it is made and before the key is written to it. A stick whose filesystem cannot keep that
    (a FAT or exFAT stick mounted with a wide `umask`/`fmask`, or owned by a desktop user through `uid=`) is refused,
    and the refusal tells IT how to mount it: `mount -o uid=0,gid=0,umask=077 <device> <folder>`, or use a stick
    formatted with ext4. The narrower choice is taken over going on with a warning: a key readable by every local
    user while it sits mounted on the box is not the same as a stick in a sealed envelope. **For the owner:** an
    ordinary FAT stick mounted with the defaults (the desktop's automount, or a plain `mount` as root, which shows
    files 0755 or 0644) is refused; IT must mount it as above.
  - **Where the stick may be:** the checks of the escrow shares (`tools/key_escrow.media_problem`, D-894): a mounted
    folder that is already there (never made here), on removable media, not on the secrets folder's disk, not on the
    system disk, not inside the secrets folder. Then the write probe (a file made, mode-checked, written, synced and
    removed); a stick that holds a file of either name already, a link (a dangling one too) included, is refused,
    saying that a file of that name is there (a key is never written over a file or through a link).
  - **Read back before the box keeps anything:** both files are read back from the stick; the key file and the sheet
    (through `read_paper`'s line checks) must each give the public key just made.
  - **The order of the writes (after review of a1ed9c36, H4):** (1) the key file on the stick, (2) the paper sheet on
    the stick, (3) the stick's folder synced, (4) both read back, (5) the public key as a synced temporary file beside
    `deploy/secrets/backup.pub` (`TB_BACKUP_PUBKEY`, `--public`; its folder made if missing), not yet at its name, and
    the name checked to be free, (6) the audit event, its line synced, written as the audit folder's owner and never
    as root (below), and the folder then checked, read only, to hold no file of root's, (7) only then a hard link of the temporary file to `backup.pub` (refused when the name
    exists: never an overwrite), the temporary name removed and the folder synced. `trialbox backup` reads the public
    key from `backup.pub` (`load_public`, with no lock this command could share), so it can find the key only once
    the event that names it is on disk; a failing append, whose undo removes the private copies, leaves no backup
    made to that key. The order of a1ed9c36 (`backup.pub` before the audit) is gone.
  - **The opposite hole, an audit line without `backup.pub` (H4):** when the event is on disk and the link fails (the
    name taken meanwhile, another error of the link itself), `backup.pub` never became visible, so no backup was made
    to the key: the command writes a second event, `backup.key_ceremony_undone` (same actor, the fingerprint, the
    site, the two names, `why`: the error's kind), and then undoes the stick files and the temporary file. The product
    had no compensating-event convention to follow; this is the smallest one. The once-only check counts a ceremony
    with a later `backup.key_ceremony_undone` of this command and this fingerprint as not done, so the ceremony can be
    run again, witnessed and audited. The undoing is written as the event is (by the folder's owner, below) and judged
    the same way: once its line is synced it counts as written, even when its head anchor then fails or Ctrl-C lands
    there (after review of f68e5988), and the refusal says nothing against a rerun, which the once-only check allows.
    If it is not written, the undo still runs (no backup can use the key) and the refusal says the audit holds this
    run's event and its undoing is not written: a new run is refused, and the new pair is made as RUNBOOK §25 says;
    if it is not known to be on disk, the refusal says that if a rerun is refused, the new pair is made so. **Whether `backup.pub` was visible is decided by looking
    at it (after review of c2fcb044), never by where the code stopped:** after any failure once the event's line is on
    disk, `backup.pub` is `lstat`ed and its device and inode compared with the staged file's. Ours: it was visible,
    so everything of the key is kept, only the temporary name is removed, and a translated warning says the public key
    is in place but the run stopped before it finished (run `python tools/audit_verify.py`, do not run the ceremony
    again, unmount the stick); exit 2. Not visible: the link was never tried (Ctrl-C while the event was being
    written, or an interruption or an error in the check after it), the link itself refused (`OSError`), or the link was being tried and nothing is at
    the name while the staged file still has only its temporary name (Ctrl-C before `os.link` ran): then
    `backup.key_ceremony_undone` is written and everything is undone, as above, and the ceremony can be run again.
    Anything else (another file at the name, a name that cannot be looked at, the name gone after the link returned):
    it may have been visible, so nothing of the key is removed; exit 2. The warning says what to do (after review of
    f68e5988): run `python tools/audit_verify.py`, then run this command again with the same options, which is
    refused before it writes anything and names the key at `backup.pub` by its fingerprint (`ALREADY`, or, with no
    `backup.pub`, the audit's refusal that says there is none); if that is not the audited fingerprint, the key at
    `backup.pub` is not the ceremony's key: keep the stick and the sheet sealed and follow RUNBOOK §25.
  - **One failure domain until the link, and what an undo says (after review of a1ed9c36, H5):** every file and
    folder is registered for removal the moment it exists, with the device and inode `fstat` gave it when it was made.
    A failure at any step after the first file is made and before the link, of any kind (a write, a sync, a
    read-back, a mode the stick does not keep, the public key's folder or file, the audit append, a file on another
    device, an interruption with Ctrl-C, an unexpected error), removes the files and folders the command made, newest
    first, on the stick and on the box, and exits 1 with one translated line: why, then what was removed and what is
    left. No traceback. **A file is removed only if it is still the file made** (after review of 13e286f0): its folder
    on the device the file was made on, and the name the same device, inode and size; the removal goes through that
    folder's descriptor. **Then each folder something was removed from is synced** (strictly: a filesystem that does
    not sync a folder counts as a failure here); a removal whose folder does not sync is said as removed but not
    confirmed on disk, naming the files and the folder (after a power loss they may come back: look again, and
    destroy or wipe a stick that held them). A folder removed too is held by its parent's sync. A key file not found
    there (the stick was pulled after its files were synced, or the folder is gone with it) is said as **not found,
    so not removed: the stick that was pulled may hold it: destroy or wipe that stick**; another file at its name is
    left as it is and said the same way; a removal that fails is named with its path, to be removed by hand.
    **"Nothing of the key is kept" is said only when every file made was removed and every such folder synced.** A
    file that was there before is never removed (a `backup.pub` that appears meanwhile stays; the command's own is
    never linked over it); a folder made here that now holds such a file stays too.
  - **When a failed append counts as recorded** (after review of 13e286f0): only when the line is known to be on
    disk: the exception was raised inside a call that `tb_common.audit`'s `AuditLog._write` makes only after its
    `os.fsync` of the day file returned (`write_head`, the head anchor, or the listing after it), in the `_write` of
    this ceremony's own event (read from the traceback: this event, this fingerprint), and the audit folder, which
    holds the day file's name, then syncs. The library is not changed; a test holds its order. Since the review of
    f68e5988 the append runs in another process (since the review of 1a7426e0: the one audit helper, below), so this
    judgement is made there, on its own traceback, and only its result crosses to the parent, as one word of a fixed
    list (`ok`, `line-synced`, `not-written`, `unknown`; `drop-failed` only as the helper's first word; a helper gone
    without a word is `unknown`); the parent decides from that word exactly as it decided from the exception before. Then the ceremony goes
    on to the link, and does not print its closing text: it prints a translated warning (the key is in place, the
    audit line is written, its head anchor is not confirmed: run `python tools/audit_verify.py <audit folder>` now, do
    not run the ceremony again, unmount the stick) and exits 2. Every other append failure undoes the ceremony, also
    when the line may be in the file (the page cache) without being known on disk; `backup.pub` was never at its name.
    **An undone ceremony whose line the audit may still hold:** the refusal adds that the audit may still hold this
    run's event (with its fingerprint), that a new run is then refused, and that the new pair is made as RUNBOOK §25
    says; it is said whenever the chain, read whole, holds the event or cannot be read. A later run is then refused by
    the audit, and that refusal adds how to go on (after review of c2fcb044): the key of that ceremony (its
    fingerprint) may still be on its stick and paper sheet and is valid, but no command of this box puts its public
    key back at `backup.pub` (none is built: `backup-keygen` only makes a new pair, and no `--pub-from-key` or other
    command derives `backup.pub` from a private key; adding one is a new power, left to the owner); keep that stick
    and sheet sealed (a backup made while its `backup.pub` was there opens only with it); make the new pair as RUNBOOK
    §25 says (`python -m tools.trialbox backup-keygen`) and enter its fingerprint in the ceremony record. **The event
    counts as on disk from the moment the helper says its line is synced** (`ok` or `line-synced`): the state is set
    then and is not changed by what comes after; Ctrl-C while the helper wrote (noted by the parent, which still waits
    for the helper's word: Ctrl-C only shortens that wait to 10 s and is a flag there, never an exception, and an
    interruption right before or right after the answer is read makes the parent read the pending answer, or take the
    one already read, before it decides; since the review of 1a7426e0) and an interruption or an unexpected error in the check after it are handled as "event
    present, `backup.pub` not visible" (the undoing first, then the undo), said as interrupted or unexpected, never as
    the audit failing; a listing of the audit folder that fails in that check (`OSError`) is not an error at all: the
    key is put in place and a translated warning says the folder was not checked (exit 2).
  - **Root never writes in the audit folder (after review of f68e5988, a Blocker; H3 of a1ed9c36):** the command
    runs as root, and the audit folder is the audit writer's (another user, uid 10001 in the image), so that user can
    plant any name in it beforehand, `.HEAD.json.tmp`, `.lock` or a day file among them, as a symlink to a file of
    root's; an append as root (`tb_common.audit` opens those names by path and follows links) would then truncate or
    append to that file, and `os.replace` would make `HEAD.json` the link. No race is needed. The library has the same
    hole on master for `trialbox backup` and `restore` (reported to the integrator; `libs/tb_common/audit.py` is not
    this card's file and is not changed); this command must not add another root command that reaches it. So the
    give-back of c2fcb044 and bdfbb858 (root appends, then hands the files to the folder's owner) is gone, and with it
    its residuals and the mode it copied from a file of the writer's. The audit folder is opened with
    `O_RDONLY|O_DIRECTORY|O_NOFOLLOW` (a folder named by a link is refused before anything is written, as is a folder
    of root's that its group or others may write) and its owner is that open folder's `fstat`.
  - **One audit helper, started before any key exists (after review of 1a7426e0, a Blocker):** until 1a7426e0 each
    append ran in a child forked from the parent after the key was made; `del` only dropped references, so the
    child's copy of the parent's memory held the key (the reviewer found 48 of the paper sheet's 52 base32 letters in
    a dropped child's memory image at `_drop_to` in a real root run, the rest brute-forceable against the audited
    fingerprint). The writer account cannot `ptrace` a non-dumpable process, but it can signal one of its own uid
    (`SIGSTOP`, `SIGKILL`, `SIGSEGV`, `SIGQUIT`), and on a host with a crash handler a forced crash could write a core
    holding the key to the box's disk. Now **the order** is: the checks run (root, the two names, the audit folder
    opened and checked, `backup.pub` absent); then, still in the checks and before the stick's folder is even opened,
    the parent runs the cyclic garbage collector, blocks Ctrl-C across one `fork` (only across the fork itself: since
    the review of 68f46dfb the parent restores its signal mask first thing in the block that always reaps the helper, so
    a Ctrl-C while it waits for `ready` ends the run within the 10 s grace, nothing made, the helper reaped), and the
    child becomes **the audit helper**: it closes every descriptor but the audit folder held open and its two pipe ends
    (0, 1 and 2 become `/dev/null`; `os.closerange`, which is `close_range` on Linux), sets `RLIMIT_CORE` to 0 and `PR_SET_DUMPABLE` to
    0, calls `setgroups([])`, `setgid` and `setuid` to the folder's owner, checks that the real, effective and saved
    ids are all that owner's and no supplementary group is left, makes itself not dumpable again (a change of identity
    resets it), `fchdir`s to the folder held open and closes it, ignores Ctrl-C, turns the cyclic collector off, and
    only then says `ready`. The parent goes on only after `ready`: the once-only read (below) is the helper's first
    request; then the stick's checks; then the parent sets `RLIMIT_CORE` to 0 for itself (soft and hard: a crash of
    root's from then on writes no core), and only then is the key made, the sheet built, both files written and read
    back. Nothing forks after the key exists. **The protocol** is a pipe pair and one line each way: `earlier?`
    (answered `none`, `found {"ts","fp"}`, `unreadable {"name"}` or `unknown`), `event <json>` and `undone <json>`
    (the event's own fields: time, site, fingerprint, the two names, the forms, the paper format, and for the undoing
    the error's kind; never key material, a line of the sheet or a path on the stick; answered with one word of
    `ok`, `line-synced`, `not-written`, `unknown`), and `quit`. The helper appends with `tb_common.audit` as it is,
    with relative paths in its working folder; a link the writer planted is followed with the writer's own power
    only. **Lifetime:** the helper lives for the whole run and ends on `quit` or when its request pipe closes; every
    path of it ends with `os._exit` in a `finally`, never returning into the program or running its exit handlers;
    the parent always reaps it (in a `finally` around the run): an answer that takes longer than 120 s, or 10 s
    after Ctrl-C (at once on a second Ctrl-C), gets it killed (`SIGKILL`); at the end it is asked to `quit` and
    killed when it has not ended within 10 s. **A helper that dies, hangs or answers garbage** (not one word of the
    list, or two answers) is gone for the run: the append it was asked for, and every later one, is `unknown` (the
    ceremony is undone and the refusal adds that the audit may hold the event), and the refusal says the true cause
    in three languages: the audit helper stopped answering, and either it was stopped or killed by a signal (seen as
    a stopped or signalled child by `waitpid`, or state `T` in `/proc`), which the audit folder's owner can do, or it
    ended, did not answer within 120 s or answered something that is not an outcome; never "full, or a broken chain".
    A helper that cannot take the identity says `drop-failed` before the key exists: the ceremony is refused naming
    the owner (`AUDIT_DROP_FAILED`), and nothing at all is made. The cyclic garbage collector runs in the parent
    before the fork and is off in the helper: the first version of the child hung in the unit suite when it freed a
    zstd compressor copied from the test process, whose worker threads do not exist in a child, and that orphan held
    a test slot until it was killed. Every file in the folder is thus made by its owner, and nothing needs giving
    back; after each append the folder is listed through a descriptor, read only, and a file of root's found there is
    named in a translated warning with the folder's owner and `chown` (exit 2); a folder that cannot be listed there
    is said as not checked (exit 2). **How the reviewer's memory probe can be repeated by hand** (not portable to CI,
    so not a test; the tests pin the order instead): on a scratch host, as root, with an audit folder owned by
    uid 10001 and a real stick, run the command under `gdb -p` or with a breakpoint on `_new_key` (or simply add a
    `time.sleep(60)` there in a scratch copy); while it waits, note the helper's pid (the one child of the command,
    `pgrep -P`), and then, after the key is made (a second pause after the read-back), dump the helper's memory as
    root (`gcore <pid>`, or read `/proc/<pid>/maps` and `/proc/<pid>/mem`), and search the dump for the paper sheet's
    letters (`_letters` of the stick key's raw bytes, with and without spaces) and for the raw key bytes: none may be
    found; the same dump of the parent finds them, which shows the probe works.
  - **A box whose audit folder is root's** (the audit runs as root there): no helper (no owner to drop to); the
    once-only read and the appends run in this process. Since the review of 68f46dfb (point 1) the once-only read too
    `fchdir`s to the folder held open since the checks, reads with relative paths and `fchdir`s back (until then it read
    the folder by its path, so a rename-swap could have shown it a planted folder). Each append first checks the
    folder's mode and every entry, listed and looked at through the folder held open since the checks without following, to be a regular file with
    one name; a link, a file with a second name or a special file is refused, naming it, before anything is written
    (in the checks) and again right before each append (then undone). Since the review of 1a7426e0 (item 2) the
    append then `fchdir`s to that same descriptor, appends with relative paths, and `fchdir`s back to the working
    folder it saved; the folder is never opened by its path again, so a rename-swap of the folder by whoever may
    write its parent between the check and the append does not redirect the append (the event lands in the folder
    checked). **Residual, stated:** on such a box a name planted in the folder itself between that listing and the
    append is followed as root; only a process that may write a folder of root's that its group and others may not,
    that is root itself, can plant it; and if the `fchdir` back fails after the append (the saved working folder
    unusable), the run stops on an unexpected error with the event's state taken as not known.
  - **Residuals of the helper, stated:** the writer account sees the helper (a process of its own uid) and can signal
    it; the helper holds no key (it was forked before the key existed), no descriptor to the stick or the secrets
    folder, writes no core and is not dumpable. By stopping or killing it the writer account can make a run fail
    (said as above) and, with good timing (after the event's line is written and before the answer), leave the event
    in the audit and so block a rerun of this command; it can already block reruns by appending a forged
    `backup.key_ceremony` event, so this adds no power. A `SIGKILL` that tears the audit's last line makes the next
    run refuse with `AUDIT_UNREADABLE` until the writer's next append repairs the line; that refusal now says so. The
    "may hold" read after a failed append (`_audit_state`) runs in the helper, as the folder's owner, not in the root
    parent (correcting the text of 1a7426e0); the once-only read of a box whose audit folder is the writer's runs in
    the helper too; only the read for a `backup.pub` that exists (whether the audit holds a ceremony for that key)
    still runs as root, by path, before the helper starts and before any key exists; it only reads, follows a planted
    link to read a file as JSON, and prints the file's path at most. The helper's memory holds the stick's **path** (it
    is in the command line, which the fork copies): not secret, and never sent over the pipe or written to the audit.
    **The memory probe was repeated** by an independent reviewer of 68f46dfb, as above but on a scratch area with the
    audit folder owned by uid 65534 and a scratch folder accepted as the stick: the helper's memory, read through
    `/proc/<pid>/maps` and `/proc/<pid>/mem`, held 0 hits of the key (searched for as above) at four moments: after
    `ready`, after the key was made, after the event's append, and before `quit`; the same scan of the parent found 19
    (the control); the pipe carried 230 bytes, public fields only. To repeat it: pause the command at each of those four
    moments (a breakpoint, or a `time.sleep` in a scratch copy), scan both processes as above, and compare the request
    lines with the event's public fields. **Not verified:** a run on a real deployed box with uid 10001 (the tests drop
    to uid 65534 for real when run as root, and inject the drop as any other user), a real stick, a real Ctrl-C at a
    terminal (the tests send SIGINT), a power loss, and the memory probe on a box whose audit folder is root's (that
    branch has no helper and was not probed).
  - **What is guaranteed, and what is not:** a run that exits 0 has the key on the stick (both files read back, each
    the key's alone on that filesystem), the event's line in the audit with the head anchor written (by the folder's
    owner), no file of root's found in the audit folder after it, and then the public key at `backup.pub`. A run that exits 2 has the key on the stick
    and its event's line synced, and says what is not confirmed (the head anchor, a file of root's found in the
    audit folder or the folder not listed, or a public key whose placing did not finish). **A second Ctrl-C (after
    review of f68e5988):** while a failure is being handled (in the handling after the event, the look at `backup.pub`,
    the undo) or after the run returned, the interruption reaches the outermost handler, which says only what the run
    is known to have done, kept as each step happens: whether the event is written (or may be), whether its undoing is
    written (and so whether a rerun is allowed), and which files may remain, with their paths, to look at and remove
    by hand (or, once `backup.pub` may be the key just made, to remove neither it nor the stick's files); exit 2.
    "Nothing had been written" is said only when no file was made (a file being made counts) and no event written. A run that exits 1 after the first file was made has removed every file
    it says it removed, says which removals are not confirmed on disk, and `backup.pub` was never at its name. Not
    covered: a power loss or a kill after the event's line is on disk and before `backup.pub` is linked leaves the
    event without the public key (no process is left to write the undoing; the next run is refused by the audit and
    says how to go on: RUNBOOK §25); a power loss while a key file is being written leaves what the filesystem kept
    on the stick; a stick pulled after its files were synced keeps the key, which the refusal says.
  - **Once:** a box whose public key file exists is refused, naming that key's fingerprint, and, when the audit
    holds no `backup.key_ceremony` with that fingerprint, saying so (a ceremony cut short, or a key made by
    `backup-keygen`); and, since `backup.pub` is a file root can delete, a box whose audit already holds a
    `backup.key_ceremony` event of this site that no later `backup.key_ceremony_undone` of this command undoes (read
    with the chain's own reader, `tb_common.audit`'s day files from the end; an event or a run without a site counts
    as this site's) is refused too, naming that event's time and fingerprint. Every line of every day file must read
    as one JSON object: an audit with a damaged, empty or cut-off line, the newest file's torn last line included, is
    refused, naming the file and `python tools/audit_verify.py`. A new pair is the backup key's rotation (RUNBOOK
    §25), not this command; no rotation path is added.
  - **Audited:** the audit event `backup.key_ceremony` (actor `python -m tools.backup_key_ceremony`): when, the site,
    the key's fingerprint, the operator's and the witness's names, the forms (`stick`, `paper`) and the paper format;
    and, only when `backup.pub` could not be put in place after it, `backup.key_ceremony_undone` (the same names and
    fingerprint, and the error's kind).
    Never the key, a line of the sheet, or a path on the stick. Written in the site's zone, `TB_TZ`, as `restore`
    writes its events (`tools/trialbox/backup.py`). The labels are in the audit browser's catalogue
    (`services/console/i18n_audit.py` `EVENTS`, a Python catalogue, no template), en, ja, zh-TW. No audit folder
    (`--audit-dir`, `TB_AUDIT_DIR`): refused before anything is made. No key is written to a database or a log; the screen shows the fingerprint,
    the two file names, the public key's path and the two names.
  - **Words:** every refusal and the closing line in en, ja and zh-TW (`--lang`, English by default; no new setting), with the same
    placeholders in each; the core words as the catalogues spell them.
- **Smaller points (after review of c2fcb044):** the refusal for a stick that does not keep files private says what
  is checked (a bit for the group or others, or an owner other than root; 0700 on a FAT stick mounted `umask=077`
  passes), not "mode 0600"; a write probe shown readable by others is refused as that even when its removal fails;
  and when another run on the same stick makes the key file between this run's checks and its create (`O_EXCL`
  fails), the refusal says a file of that name is on the stick (never "read-only or full"), and the other run's file
  is left. **A residual, stated:** `backup.key_ceremony_undone` is honoured on its actor and fingerprint alone, and
  the audit writer (uid 10001) can append any event, one of these included; when `backup.pub` is absent, such a
  forged undoing reopens the once-only gate for a new, witnessed and audited ceremony. Binding the undoing to the
  ceremony event's hash-chain position would not close it (the writer reads the chain and can name that position
  too), so it is not done: the audit writer is already trusted with the whole trail, and a `backup.pub` that exists
  refuses a second run whatever the audit holds.
- **Smaller points (after review of f68e5988):** the audit folder is opened with `O_NOFOLLOW` wherever it is opened
  (the checks, each append, the check after it); no mode is copied from any file in the audit folder any more (the
  give-back that copied one, possibly from a leftover file of root's, is gone); after an undoing whose line is synced
  and then interrupted, the refusal no longer says the undoing could not be written or that a rerun is refused; the
  warning for a `backup.pub` that may not be the ceremony's names the command that prints its fingerprint and what to
  do when it differs (above).
- **Not in this card (open for the owner):** reading the paper sheet back into a restore (`restore --key` takes the
  stick's file; `read_paper` exists and the ceremony uses it for its read-back, but no restore command reads a typed
  sheet); a supported step that puts `backup.pub` back from the stick's key after an event without a public key
  (a power loss or kill between the audit line and the link, or a `backup.pub` removed later): today the key on the
  stick stays valid but the box can only make a new pair (RUNBOOK §25); how the sheet reaches paper (it is a file on the stick; no printer is driven from the box); a console page
  for the ceremony (the card says "pages"; the owner's ruling says "on the host"); the KEK preset and the printed
  shares, which `python -m tools.keys init`, `escrow-shares` and `ceremony-record` already do (D-893, D-894) and which
  this card does not change; a rotation of the backup key through this command.
- **Open follow-ups (other open cards hold these files; not changed here):** the install and the runbooks still send
  hospital IT to the unwitnessed `trialbox backup-keygen` for the one-time key: `deploy/install.sh` (line 932),
  `docs/runbook/05-updates-backup-restore-secrets.md` (line 75), `docs/runbook/01-install-a-new-site.md` (line 177,
  step 9, by way of runbook 05) and `docs/security/10-key-ceremony-and-escrow.md` §1's table and §4 step 1 (lines 12
  and 47-48), which got only a pointer line at its end. Each should name this command instead. Also open: a power
  loss between the audit line and the public key's link (the audit then refuses a rerun; RUNBOOK §25), and ordinary
  FAT sticks, which must be mounted `uid=0,gid=0,umask=077` (above).
- **Held by:** `tests/unit/test_backup_key_ceremony.py` (the happy path with a throwaway key and a backup stream
  opened by both forms; each refusal, the same person in full-width and double-space spellings, a second run refused
  by the audit when `backup.pub` is gone, a dangling link of either name; each failure injected where it happens: a
  sync raising after each file is made, the stick's folder sync (the undo's sync failing too: not confirmed on disk),
  short writes, a file on another device, the audit append raising (`AuditFull`), EIO on the `fsync` of the audit's
  day file only (undone, "may still hold", the rerun refused with how to go on), EIO on the head anchor's sync after
  the line was synced (kept, the warning in three languages, exit 2), the audit folder's sync failing (undone), the
  library's order held by a test, the public key's folder that cannot be made, a `backup.pub` that appears before the
  audit, the stick's files moved away before the read-back (and another file at the key file's name), Ctrl-C, an
  unexpected error, a removal that fails; and from the review of a1ed9c36: the stick unmounted right after the media
  check (H1: the key goes to the folder checked, nothing to the folder now at the path), a stick whose files show
  0644 or another owner (H2: refused before a byte of the key, at the probe and at the key file), an audit folder
  of the writer, empty or with an earlier day (H3, since f68e5988: every file made by the writer, none root's), a file
  of root's found there after the event (named, exit 2), what a concurrent backup would find while the event is appended (H4: no `backup.pub`),
  the link refused after the audit (H4: `backup.key_ceremony_undone`, undone, a rerun allowed), Ctrl-C right after
  the link (kept, exit 2, with and without another file at the name), and the stick's folder sync failing after the
  undo's unlinks (H5: named, never "nothing of the key is kept"); a torn, damaged or empty audit line refused; a
  `backup.pub` with no ceremony in the audit; a damaged, missing or swapped paper line and a wrong fingerprint; the
  words in three languages; the command line); from the review of c2fcb044, as root and as uid 65534: Ctrl-C in
  the check after the event (the undoing written, a rerun allowed, never "the audit event could not be written"),
  the audit folder's listing failing there (kept, exit 2), Ctrl-C before `os.link` ran (the undoing, everything
  removed), the public key linked and its folder's sync failing (kept, "in place"), a probe shown readable whose
  removal fails, the private-mode text, and two runs on one stick (the give-back's own tests went with it); and from
  the review of f68e5988, as root (the child really drops to uid 65534) and as uid 65534 (the drop injected): the
  child asked to drop to the folder's owner, once per append; a `.HEAD.json.tmp` or `.lock` planted as a symlink to
  a file outside that the writer may not write (as root: root's 0600 file) is never followed with root's power (the
  file unchanged; `.lock`: undone, nothing kept; `.HEAD.json.tmp`: the line synced, kept with the head-anchor
  warning, `HEAD.json` never the link); a failed drop refused before anything is written to the audit; the real drop
  in a real child (as root: uid 65534 for good, no group, not root again, not dumpable; as another user: refused); an
  audit folder named by a link refused; a folder of root's appended to in-process, and refused for a link, a second
  name, a special file or a group-writable mode, and for a link planted after the first check (undone); a second
  Ctrl-C in `_after_event`, in `_pub_state` and in the undo (only what is known, exit 2, never "nothing had been
  written"); an undoing synced and then interrupted (no "rerun refused"; the rerun succeeds); and the kept warning's
  next step in three languages; the child reaped before the call returns whatever happens in it (an exception,
  Ctrl-C, `sys.exit`, a failed drop, a hang, a child that would run on), and garbage of the caller freed in the
  caller with the collector off in the child. A mutation that skips the real drop fails five of them as root. From
  the review of 1a7426e0, as root and as uid 65534: the helper alive and dropped (its four uids the writer's in
  `/proc`) when the key-making function is called, `RLIMIT_CORE` 0 in the parent by then (a spy on `_new_key` and on
  `os.fork`); no fork after the key is made, also on the path that writes the undoing; every byte the parent sends
  the helper is a request of the fixed list whose event fields equal the audited detail, holding no form of the key,
  no line of the sheet and not the stick's path; the helper holding only its two pipes and `/dev/null`, with no core
  and not dumpable; the real drop in the real helper; the helper reaped whatever happens in it (an exception, Ctrl-C,
  `sys.exit`, a failed drop, a hang, a helper that never ends, garbage, two answers, a kill, a stop), with the cause
  said; a real SIGINT while the helper appends (its answer read, the undoing written, a rerun allowed) and an
  interruption right before or after the answer is read (the same); the helper killed or stopped by the writer (the
  true cause in en, ja and zh-TW, never "full, or a broken chain"); a folder of root's renamed away after the check
  (the event in the folder checked, the working folder restored, no fork); and the unreadable-audit text naming the
  writer's repair. Mutations that skip the pending-answer read, the descriptor closing, the relative append or the
  parent's core limit each fail their test.
