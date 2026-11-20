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
    the name checked to be free, (6) the audit event, its line synced, and what the run wrote in the audit folder given
    back to its owner (below), (7) only then a hard link of the temporary file to `backup.pub` (refused when the name
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
    run again, witnessed and audited. If that second event cannot be written, the undo still runs (no backup can use
    the key) and the refusal says the audit holds this run's event and its undoing could not be written: a new run is
    refused, and the new pair is made as RUNBOOK §25 says. **Once `backup.pub` may have been visible, nothing of the
    key is removed:** a failure after the link returned, or an interruption during the link (whether it was made
    cannot be told), keeps the stick files and the public key, removes only the temporary name, and prints a
    translated warning (check that `backup.pub` is there with this fingerprint, run `python tools/audit_verify.py`,
    do not run the ceremony again, unmount the stick); exit 2.
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
    holds the day file's name, then syncs. The library is not changed; a test holds its order. Then the ceremony goes
    on to the link, and does not print its closing text: it prints a translated warning (the key is in place, the
    audit line is written, its head anchor is not confirmed: run `python tools/audit_verify.py <audit folder>` now, do
    not run the ceremony again, unmount the stick) and exits 2. Every other append failure undoes the ceremony, also
    when the line may be in the file (the page cache) without being known on disk; `backup.pub` was never at its name.
    **An undone ceremony whose line the audit may still hold:** the refusal adds that the audit may still hold this
    run's event (with its fingerprint), that a new run is then refused, and that the new pair is made as RUNBOOK §25
    says; it is said whenever the chain, read whole, holds the event or cannot be read. A later run is then refused by
    the audit, and that refusal adds: if that ceremony was undone or its public key removed, make the new pair as
    RUNBOOK §25 says (`python -m tools.trialbox backup-keygen`) and enter its fingerprint in the ceremony record.
  - **The audit folder stays the writer's (after review of a1ed9c36, H3):** the command runs as root, and an append
    can make the writer's lock file, a new day file, a torn line's evidence, and replaces the head anchor; root's
    files with root's mode would leave the deployed writer (another user, uid 10001 in the image) unable to append
    next. As `trialbox backup` and `restore` do it (D-724, `backup._own_writes`), after each append (the ceremony's,
    the undoing, and a failed one) every file in the audit folder that is root's now and was not root's before is
    given back: a file that was there with another owner (the head anchor, replaced) gets its owner, group and mode
    again; a new file gets the folder's owner and group and the mode of the newest day file that was there (or keeps
    its own when there was none). Files root had before are left. It is then checked: a file still root's (the owner
    change failed) is named in a translated warning with the folder's owner and `chown`; on a run that otherwise
    finished, after the closing text, with exit 2. Nothing is changed when the folder is root's.
  - **What is guaranteed, and what is not:** a run that exits 0 has the key on the stick (both files read back, each
    the key's alone on that filesystem), the event's line in the audit with the head anchor written, the audit
    folder's files the writer's, and then the public key at `backup.pub`. A run that exits 2 has the key on the stick
    and its event's line synced, and says what is not confirmed (the head anchor, an audit file left root's, or a
    public key whose placing did not finish). A run that exits 1 after the first file was made has removed every file
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
- **Not in this card (open for the owner):** reading the paper sheet back into a restore (`restore --key` takes the
  stick's file; `read_paper` exists and the ceremony uses it for its read-back, but no restore command reads a typed
  sheet); how the sheet reaches paper (it is a file on the stick; no printer is driven from the box); a console page
  for the ceremony (the card says "pages"; the owner's ruling says "on the host"); the KEK preset and the printed
  shares, which `python -m tools.keys init`, `escrow-shares` and `ceremony-record` already do (D-893, D-894) and which
  this card does not change; a rotation of the backup key through this command.
- **Open follow-ups (other open cards hold these files; not changed here):** the install and the runbooks still send
  hospital IT to the unwitnessed `trialbox backup-keygen` for the one-time key: `deploy/install.sh` (line 905),
  `docs/runbook/05-updates-backup-restore-secrets.md` (line 75), `docs/runbook/01-install-a-new-site.md` (line 176,
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
  owned by uid 10001, empty or with an earlier day (H3: every file the writer's again, modes kept) and an owner change
  that fails (named, exit 2), what a concurrent backup would find while the event is appended (H4: no `backup.pub`),
  the link refused after the audit (H4: `backup.key_ceremony_undone`, undone, a rerun allowed), Ctrl-C right after
  the link (kept, exit 2, with and without another file at the name), and the stick's folder sync failing after the
  undo's unlinks (H5: named, never "nothing of the key is kept"); a torn, damaged or empty audit line refused; a
  `backup.pub` with no ceremony in the audit; a damaged, missing or swapped paper line and a wrong fingerprint; the
  words in three languages; the command line).
