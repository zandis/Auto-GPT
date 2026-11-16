# D-618 The site keys' KEK held by Windows and handed into WSL2 at every start (Windows half)

- **Task:** NEW-WIN-15 (lane W): NEW-WIN-8 part 2's Windows half (`docs/plan/33-plan-v7.md` section 2.3, rule 7 and
  the row "The site keys sealed to a Linux TPM device: Replaced ... NEW-WIN-8 adds a Windows-held key"; D-603 point 8)
- **PR:** this branch (`agent/NEW-WIN-15-site-key-from-windows`)
- **Date:** 2026-11-16
- **Status:** accepted for the Windows half. It does nothing until the Linux half (lane D's: `KEK_BACKEND=windows`
  in `deploy/hardening/seal_keys.sh` and its unseal unit) is on `master`; the hand-over below is what that half
  reads and writes. The store's default stands until P-0 line 36a answers. Nothing in it has run on Windows
- **Owner decisions:** D-527 (every card now, ordered only by what it depends on), D-494 point 6
- **Builds on:** D-603 (BitLocker, the key probe), D-602 (the boot task), D-836 (seal, then wrap)

## Context

WSL2 has no security chip, so on the Windows form the site keys' KEK cannot be sealed as on a Linux box, and the
box plan falls back to a passphrase typed after every restart: rule 7 ("a restart at any hour is safe; the stack
returns with nobody signed in") is broken. D-603 built the probe that shows which Windows store the boot task's
sign-in (S4U, no password stored) can open with nobody signed in; part 2 was to wait for the probe's answer at P-0.
Under D-527 every card is built now: the Windows half does not depend on the answer, only its default does.

## Decision

1. **`deploy/windows/site-key.ps1`**: `-Take` reads the KEK the Linux side handed out, once, as 64 hex figures,
   stores it, reads the store back and compares it with the hand-out's own hash inside WSL2, and only then shreds
   the hand-out. A hand-out equal to the stored KEK (a take cut between store and shred) is only shredded; another
   one replaces the stored KEK, after the same check: the Linux side makes a KEK only when it has none and wraps the
   keys under it, so the stored one wraps nothing any more (the distribution installed again). A read-back that
   differs keeps the old store as it was and the hand-out. `-Hand` writes the stored KEK, on standard input, into
   WSL2's memory, and tries again for a few minutes while WSL2 starts; it writes nothing when WSL2 holds the KEK
   already. Its task `TrialBox-Site-Key` runs at startup and every five minutes after, with the boot task's
   sign-in (S4U, highest rights), so a WSL2 started again without a start of Windows (`wsl --shutdown`, an update)
   gets the KEK again. A store that cannot be read says so ("unreadable"), apart from no store at all. The KEK travels on standard input only: never in a command
   line, the task's arguments, a log or the screen (a test reads the script for it).
2. **The store**, `-KeyStore` on the installer (carried over the restart): `acl_file` (default), a file in the
   installer's closed folder (SYSTEM, the administrators and the owner) on the BitLocker system drive, which a task
   signed in by S4U is expected to read; `dpapi_user`, the owner's protected store (DPAPI), once P-0 line 36a shows
   the S4U sign-in opens it with nobody signed in. What `acl_file` leaves standing is D-603 point 8's: an
   administrator of the workstation, or whoever opens the drive with its recovery key, can read the KEK.
3. **The installer** takes the KEK right after the Linux installer returns, before anything else and even when that
   installer stopped later, registers the task, and on a finished install registers it again when deleted or off.
   No hand-out (another key back end) leaves everything as it was. A failed take stops step 14 and says the Linux
   side still holds the KEK.
4. **`wsl-setup.sh install`** asks the Linux installer for `KEK_BACKEND=windows` (`TB_KEK_BACKEND`, which
   `seal_keys.sh` already honours) only when the host tree has lane D's whole half: a `windows)` case in
   `seal_keys.sh` and the unit `deploy/hardening/trialbox-kek-from-windows.service`. A half alone would seal keys
   that nothing opens after a restart; until both land, nothing changes for any box.
5. **The host check** reads the store's name (never its content), in the folder the task hands from, and the task,
   and fails a box whose KEK is kept by Windows without its task.

## The hand-over (for lane D's half)

- **At install** (`seal_keys.sh`, `KEK_BACKEND=windows`): make the KEK (32 random bytes) as the `tpm` case does;
  write it to `/var/lib/trialbox/kek.for-windows` (root, mode 0600, on WSL2's disk, **before** the keys are wrapped:
  a restart before Windows took it must not lose the only copy); wrap (`tools.keys init --backend file --kek-in`);
  unseal now (`tools.keys unseal --from`). Leave the hand-out; Windows shreds it after its check.
- **At each start**: Windows writes exactly 64 lower-case hex figures, no line end, to
  `/run/trialbox/kek.from-windows` (tmpfs, root, 0600; written as `.part` and moved, so it is whole when it
  appears), unless `/run/trialbox/kek` or that file is there already. The unseal unit
  `deploy/hardening/trialbox-kek-from-windows.service` waits for it (bounded), turns it into the 32 bytes (strip
  white space first, then `xxd -r -p` or Python) in `/run/trialbox`, runs `tools.keys unseal --from`, and shreds
  both, before `trialbox.service`. It also runs when WSL2 starts again without a start of Windows: Windows hands
  the KEK again within five minutes.
- **The activation**: a line `  windows)` (two spaces) in `seal_keys.sh`'s case and that unit file, both.

**Reuse check.** The probe's own hand-over form (standard input into WSL2's memory, D-603), the seal-then-wrap order
of D-836, the console proxy's self-registering task and the installer's closed folder are used as they are.

## What is proven here, and what is not

Proven here, with every Windows and WSL2 command behind a seam: Pester (the take, the read-back check, a hand-out
kept on a mismatch with the old store restored, an equal hand-out only shredded, a new KEK replacing the stored
one, no stray `.part`, both stores, the hand at a start, tries while WSL2 starts, nothing written when WSL2 holds the
KEK, an unreadable store told apart; the installer's take right after the Linux installer, also after a stop, a
replacement, the task registered once and again when deleted, `-KeyStore` over the restart, no hand-out leaving all
as it was, a failed take stopping step 14); a reading of the script's text (the 64 figures written to standard input
with no line end, no pipe into `wsl.exe`, no line that holds the KEK writes to the screen, a log or an argument:
lines with other names are not covered by it); Python tests (the activation only with both of lane D's files; the
host check's lines). Not proven: DPAPI and the closed file under S4U at a start with nobody signed in (P-0 line
36a); `wsl.exe` passing standard input byte for byte; the task's five-minute runs; the Linux half (lane D's card).

## After the review

One fresh reviewer, verdict "fix first", one HIGH. Fixed test-first: a stored KEK with a new hand-out (a
reinstalled distribution) was kept and the new one left on WSL2's disk, so the keys would not open after a restart
(the new KEK now replaces it after the check; an equal one is only shredded); the task's restart settings do not
repeat an action that ended, and a WSL2 started again without a start of Windows got nothing (tries inside `-Hand`,
a run every five minutes, nothing written when WSL2 holds the KEK); a pipe from PowerShell 5.1 added CR LF (written
exactly now); an unreadable store looked like no store; the host check's folder was fixed; the activation needed
only half of lane D's card; a `.part` could stay. D-618's claims narrowed to what the tests read.

## Consequences

- Lane D's card: `KEK_BACKEND=windows` in `seal_keys.sh` and its unseal unit, by the hand-over above.
- When P-0 line 36a answers `dpapi_user=ok` at startup, the installer's default becomes `dpapi_user` (a one-line
  card); `acl_file=ok` only keeps it.
