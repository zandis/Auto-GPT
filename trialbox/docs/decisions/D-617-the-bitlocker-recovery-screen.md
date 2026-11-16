# D-617 The BitLocker recovery screen: a page for the owner, and the key ID with every key

- **Task:** NEW-WIN-14 (lane W): the rest of NEW-WIN-9 (`docs/plan/33-plan-v7.md` section 2.3: "the locked-box page
  of T-730 replaced by a handbook page for the BitLocker recovery screen"; D-603 names it NEW-WIN-9's)
- **PR:** this branch (`agent/NEW-WIN-14-bitlocker-recovery-page`)
- **Date:** 2026-11-16
- **Status:** accepted as written before the first run on Windows; P-0 (or the reference workstation's P-10)
  corrects it
- **Builds on:** D-603 (BitLocker and the keys), D-611 (the owner's pages), D-608 (backups)

## Context

The owner's pages gave the recovery screen one line: "type the key you were given on the set-up day". The installer
hands the owner one key per drive (the system drive and the data drive), and showed each without the key ID that
Windows' recovery screen prints to say which key it wants: an owner holding two envelopes could not tell which to
type. Nothing said what to do when the key is lost, or why the screen came.

## Decision

1. **The key ID with every key.** The installer shows and prints each recovery key with its key ID, as the recovery
   screen shows it: the first eight characters of the protector's id, in capitals. The key ID is not a secret (it
   names a key and opens nothing) and goes to the log too; the key itself still goes to the window and the
   printer only (a test holds it).
2. **The page** `docs/handover/windows-bitlocker-recovery.{en,ja,zh-TW}.md`, for the box owner and the person who
   keeps the keys: what the screen shows, what to do (the key with the same key ID; F1 to F10 when the number keys
   do nothing; wait for TrialBox; tell us what happened before), why it comes (firmware or Secure Boot changes, a
   changed board or a cleared chip, a drive moved), every start means the chip no longer opens the drive, and a
   lost key means the backup (`WINDOWS-BACKUP-RESTORE.md`). It never tells anyone to turn BitLocker off or to
   "repair" the drive to get past the screen. The owner's pages send the reader to it; the media carries it.
3. **The three languages have the same parts** and pass the wording rules (tests).

**After the review** (one fresh reviewer, "fix first", no HIGH; the code was found sound): the page now says the
blue screen is always the system drive's; a locked data drive (after sign-in, a padlock in File Explorer, no blue
screen) has its own part, where any recovery key of that drive opens it and a key that does not match means "call
us", not "lost"; the causes add USB media, docks and the start order (the first thing to check when the screen
comes at every start), boot-manager and chip updates, and too many wrong PINs; before a key counts as lost, the
last change is undone, hospital IT looks the key ID up (Active Directory, Entra, the Microsoft account), and we are
called; the Japanese page names the health line as the owner's page does. Not proven: which protector's key ID
Windows names when a data drive is locked (the installer adds a second recovery password to it, D-603 point 3).

**Reuse check.** Nothing to reuse: the page describes Windows' own screen and this installer's keys. The integrator
held drafts of such a page from another session that did not pass doclint's Reader rule; they had not reached
lane W when this was written, and this page was written from the installer.

## What is proven here, and what is not

Proven here: Pester (the key ID in the window, on the printed page and in the log, as the recovery screen's form);
the Python tests (the pages' parts in three languages, the wording rules, the Reader line, the links, the media
carrying them, the key still never logged). Not proven: that the screen on Windows 10 22H2 and Windows 11 says what
the page says (by Microsoft's documentation; P-0 or P-10), that its key ID is the first eight characters of the
protector's id as Windows reports it.

## Consequences

- The owner's handbook (T-735, lane D) can take the page in as it is, as D-611 said of the owner's pages.
