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
    people: the person who runs it (`--operator`) and a witness who is another person (`--witness`; the same name in
    another case is the same person). Decision 97 (the site decides who administers the box) is kept: the site
    chooses the two people; the tool takes their names and checks only that there are two. Not root, a name missing,
    a name that is not one printable line of at most 100 characters, or one person twice: refused.
  - **What leaves the box, and in what form; nothing else:** the private key, written only to the removable stick
    named, as two files (mode 0600, created there or not at all, synced):
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
    that holds a key file or a paper sheet already is refused (a key is never overwritten).
  - **Read back before the box keeps anything:** both files are read back from the stick; the key file and the sheet
    must each give the public key just made. Only then is the public half written to `deploy/secrets/backup.pub`
    (`TB_BACKUP_PUBKEY`, `--public`), where `trialbox backup` reads it. A stick that fails while written (an
    `OSError`) or read back keeps nothing: the files made are removed, no public key, no audit event.
  - **Once:** a box whose public key file exists is refused, naming that key's fingerprint. A new pair is the backup
    key's rotation (RUNBOOK §25), not this command.
  - **Audited:** the audit event `backup.key_ceremony` (actor `python -m tools.backup_key_ceremony`): when, the site,
    the key's fingerprint, the operator's and the witness's names, the forms (`stick`, `paper`) and the paper format.
    Never the key, a line of the sheet, or a path on the stick. No audit folder (`--audit-dir`, `TB_AUDIT_DIR`):
    refused before anything is made. No key is written to a database or a log; the screen shows the fingerprint,
    the two file names, the public key's path and the two names.
  - **Words:** every refusal and the closing line in en, ja and zh-TW (`--lang`, else `TB_LANG`), with the same
    placeholders in each; the core words as the catalogues spell them.
- **Not in this card (open for the owner):** reading the paper sheet back into a restore (`restore --key` takes the
  stick's file; `read_paper` exists and the ceremony uses it for its read-back, but no restore command reads a typed
  sheet); how the sheet reaches paper (it is a file on the stick; no printer is driven from the box); a console page
  for the ceremony (the card says "pages"; the owner's ruling says "on the host"); the KEK preset and the printed
  shares, which `python -m tools.keys init`, `escrow-shares` and `ceremony-record` already do (D-893, D-894) and which
  this card does not change; a rotation of the backup key through this command.
- **Held by:** `tests/unit/test_backup_key_ceremony.py` (the happy path with a throwaway key and a backup stream
  opened by both forms; each refusal; a damaged, missing or swapped paper line and a wrong fingerprint; the words in
  three languages; the command line).
