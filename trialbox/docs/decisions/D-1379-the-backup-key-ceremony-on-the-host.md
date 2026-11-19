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
    named, as two files (mode 0600, created there or not at all and never through a link, written in full however
    short each write, synced; each file is checked with `fstat` to be on the device that was checked as removable,
    so a stick pulled or mounted again between the check and the write is refused; then the stick's folder is synced,
    a filesystem that cannot sync a folder by itself excepted). The closing text says to unmount (eject) the stick
    before pulling it out:
    - `trialbox-backup.key`: the key file in the format `backup-keygen` writes, so `restore --key` and
      `restore-drill --key` read it unchanged;
    - `trialbox-backup-key-paper.txt`: the paper sheet, to be printed: a head in en, ja and zh-TW, the site, the
      date, the key's fingerprint, and the key as four lines of base32 letters in groups of four (`n | ABCD EFGH IJKL
      MNOP | CHCK`), each line ending with four check letters (the first 20 bits of SHA-256 over the format, the line
      number and the line's letters). A mistyped letter, a letter outside the alphabet, a line left out, two lines
      swapped or a wrong fingerprint line is refused by `read_paper`, naming the line, never its letters (format
      `tb-backup-paper/1`).
  - **Where the stick may be:** the checks of the escrow shares (`tools/key_escrow.media_problem`, D-894): a mounted
    folder that is already there (never made here), on removable media, not on the secrets folder's disk, not on the
    system disk, not inside the secrets folder. Then a write probe (a file made, written, synced and removed); a stick
    that holds a file of either name already, a link (a dangling one too) included, is refused, saying that a file of
    that name is there (a key is never written over a file or through a link).
  - **Read back before the box keeps anything:** both files are read back from the stick; the key file and the sheet
    (through `read_paper`'s line checks) must each give the public key just made. Only then is the public half put at
    `deploy/secrets/backup.pub` (`TB_BACKUP_PUBKEY`, `--public`), where `trialbox backup` reads it.
  - **The order of the writes, and one failure domain (after review of 528e8974):** (1) the key file on the stick,
    (2) the paper sheet on the stick, (3) the stick's folder synced, (4) both read back, (5) the public key: its
    folder made if missing, a synced temporary file in it, a hard link to `backup.pub` (refused when the name exists:
    never an overwrite) and the temporary name removed, the folder synced, (6) last, the audit event. Every file and
    folder is registered for removal the moment it exists. A failure at any step after the first file is made, of any
    kind (a write, a sync, a read-back, the public key's folder or file, the audit append, a file on another device,
    an interruption with Ctrl-C, an unexpected error), removes every file and folder the command made, newest first,
    on the stick and on the box, and exits 1 with one translated line: why, then what was removed, or, if a removal
    itself fails, which file is left and where, to be removed by hand. No traceback. A file that was there before is
    never removed (a `backup.pub` that appears meanwhile stays; the command's own is never linked over it).
    **Why the audit is last:** the audit chain is append-only, so its event cannot be taken back; every other write
    can. With the event last, a failed append undoes the rest, and no run ends with the box keeping `backup.pub`
    without its audit event; an append that wrote its line and then failed (on the head anchor) is read back from the
    chain by fingerprint, and then the ceremony is done and kept, since the chain holds it. What is not covered: a
    power loss or a kill between the link of `backup.pub` and the audit's line leaves the public key without the
    event (no process is left to undo it); the next run is refused (`backup.pub` exists) and the audit shows no
    ceremony, which a person then sees.
  - **Once:** a box whose public key file exists is refused, naming that key's fingerprint; and, since `backup.pub` is
    a file root can delete, a box whose audit already holds a `backup.key_ceremony` event of this site (read with the
    chain's own reader, `tb_common.audit`'s day files from the end; an event or a run without a site counts as this
    site's) is refused too, naming that event's time and fingerprint. A new pair is the backup key's rotation
    (RUNBOOK §25), not this command; no rotation path is added.
  - **Audited:** the audit event `backup.key_ceremony` (actor `python -m tools.backup_key_ceremony`): when, the site,
    the key's fingerprint, the operator's and the witness's names, the forms (`stick`, `paper`) and the paper format.
    Never the key, a line of the sheet, or a path on the stick. Written in the site's zone, `TB_TZ`, as `restore`
    writes its events (`tools/trialbox/backup.py`). Its label is in the audit browser's catalogue
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
  loss between the public key and the audit line (above).
- **Held by:** `tests/unit/test_backup_key_ceremony.py` (the happy path with a throwaway key and a backup stream
  opened by both forms; each refusal, the same person in full-width and double-space spellings, a second run refused
  by the audit when `backup.pub` is gone, a dangling link of either name; each failure injected where it happens: a
  sync raising after each file is made, the stick's folder sync, short writes, a file on another device, the audit
  append raising (`AuditFull`) and its line written before the head fails, the public key's folder that cannot be
  made, a `backup.pub` that appears meanwhile, Ctrl-C, an unexpected error, a removal that fails; each asserting what
  is left on the stick and the box and the exit text; a damaged, missing or swapped paper line and a wrong
  fingerprint; the words in three languages; the command line).
