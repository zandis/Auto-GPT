# D-603 BitLocker opened by the TPM, the recovery key handed to the owner, and a probe for the key back end

- **Task:** NEW-WIN-8, part 1 of 2 (`docs/plan/33-plan-v7.md` section 2.3; lane W)
- **PR:** this branch (`agent/NEW-WIN-8-bitlocker-unlock`)
- **Date:** 2026-11-13
- **Status:** accepted for the installer's logic and the judge. Nothing in it has run on Windows: P-0 lines 28 to
  36c. The key back end itself (part 2) is not built: its mechanism is chosen from the probe's answer
- **Owner decisions:** D-494 point 6 (Q9: BitLocker on every drive, opened by the TPM, the recovery key printed and
  held by the box owner; `bitlocker_unlock` `tpm` by default, `tpm_pin` for a site that wants a person at every
  restart), OD-13 (the owner sets the box up)
- **Changes:** D-421 point 2, one line: a TPM-only protector on the system drive is accepted when the box's
  setting says `tpm`. Every other line of D-421 stands
- **Builds on:** D-600 (the installer), D-602 (the boot task, sign-in type S4U), D-421 (`wsl2_policy.py`)

## Decision

1. **The installer turns BitLocker on, before any data is on the drive.** At step 4 (`drive`), after the data
   folder is made and before WSL2 is imported: the system drive with the TPM as its protector, the data drive
   opened with the system drive (automatic unlock). Only the space in use is encrypted first; Windows encrypts
   the rest as it fills. A drive that is already encrypted is kept as it is.
2. **The key first, then the encryption.** Per drive the order is the one Windows' own wizard keeps: the
   recovery key is made (a protector added to the still unencrypted drive), shown, and confirmed by the owner;
   only then is the drive encrypted; only then is the data drive set to open by itself. No path leaves a drive
   encrypted with its key in nobody's hands: a window closed, a refused confirmation or a failed step before the
   encryption leaves the drive plain; a failure after it leaves a drive whose key the owner holds, and the
   window says so. The installer never weakens a drive: it holds no command that turns BitLocker off, suspends
   it, removes a protector or clears automatic unlock. A drive that is being decrypted, is paused, or is
   encrypted with its protection suspended stops it; a drive that is still encrypting does not.
3. **The recovery key is handed to a person, and stored nowhere.** For each drive the 48-digit key is shown in
   the installer's window, printed when the owner says so on the default printer, which the question names
   ("only if that printer is beside you and keeps no copy"), and confirmed by typing its last six digits back;
   then the window is cleared. The six digits prove that the key was read at that moment, not that a copy left
   the PC: the window's text says to keep it away from the PC, and the handbook repeats it. The state file notes
   which key was confirmed by the drive's letter and the protector's id (an id is not a secret), so a drive that
   was decrypted and encrypted again gets its new key handed over. The key is not written to the log, the state,
   a file, or a program's arguments. A key of an unexpected form is not shown and stops the step. On a PC whose
   policy records every PowerShell window to a file ("PowerShell transcription") the installer does not show a
   key at all and stops: the site's IT turns BitLocker on and hands the key over, or switches the policy off for
   the install. A key that Windows already held (a PC that came encrypted) is read back and handed over the same
   way. With `-Yes` nobody is there to receive a key: a drive that needs a new key stops the installer; a drive
   that is already encrypted goes on with a warning that its key was not confirmed.
   On the data drive `Enable-BitLocker` adds a second recovery password of its own when it starts (the cmdlet
   wants a protector); nobody is shown that one. Either key opens the drive, and the owner holds the first.
   When the owner has confirmed the keys, the installer records "kept by the box owner" beside the unlock
   setting, and the host check's question "where is the recovery password kept" is answered by it.
4. **`bitlocker_unlock`.** `-BitLockerUnlock tpm` (the default, D-494) or `tpm_pin`. The installer records the
   choice in `HKLM\SOFTWARE\TrialBox\BitlockerUnlock` (only administrators write there), `host_facts.ps1` prints it
   as the fact `bitlocker_unlock`, and `wsl2_policy.py` judges by it: under `tpm` a system drive the TPM opens
   passes ("starts with nobody there": the TPM alone, or the TPM with the site's network unlock), one that asks
   for a PIN or a key fails (the setting and the drive disagree), and one the TPM does not open fails; under
   `tpm_pin` the TPM alone fails, as D-421 wrote. The choice is kept in the install's state: a later start
   without the parameter never turns `tpm_pin` into `tpm`. **No setting recorded is judged as `tpm_pin`**: a workstation that the box installer did not set
   up keeps D-421's rule, and none of D-421's tests changes. With `tpm_pin` the installer does not set a PIN (it
   needs a Windows policy and a person who will know it): it requires the TPM-and-PIN protector to be there
   already and stops otherwise.
5. **The data drive must open by itself.** The judge fails a data drive whose automatic unlock is off (the
   virtual disk would stay locked after a restart); the installer turns it on.
6. **What `tpm` leaves standing** (D-494, said again in the installer's window): a person who takes the whole
   workstation gets a machine that starts; between them and the data stand the Windows sign-in and the console's
   sign-in, and, once part 2 is built, whatever protects the site keys.
   **What an unfinished install leaves:** BitLocker stays on. Every later stop of the installer says for which
   drives this install turned it on, and no message after step 4 says "nothing was changed".
7. **`-SkipBitLocker`** leaves BitLocker as it is, for a rehearsal on a PC that must stay unencrypted. Nothing
   is recorded, and the host check fails the drive. It is not for a site.
8. **The key back end is chosen by a probe, not by guessing.** WSL2 has no security chip, so today the site keys
   under WSL2 wait for a passphrase after every restart. The key must come from Windows, handed over by the
   boot task, whose sign-in type (S4U, no stored password) may not be allowed to open every Windows store.
   `deploy/windows/key-probe.ps1` stores a **dummy** value three ways (the account's protected store, the
   machine's protected store, a file in the installer's closed folder) and lets a task with the boot task's
   sign-in type try to read each back and hand the value into WSL2's memory. **The run that decides is the one
   at startup with nobody signed in** (`-AtStartup`, a restart, `-Collect`): it is the boot task's own
   situation. The on-demand run, with the owner signed in, is for comparison only: a store that answers there
   and not at startup opens only because the owner's session had it open. The task runs a copy of the script in
   the closed folder and is always removed again. Part 2 builds the back end on the strongest way that answered
   `ok` **at startup**, with `wsl_handover=ok`:
   - the account's protected store: the key is bound to the owner's account;
   - else the closed file: the key is readable by SYSTEM, every administrator of the workstation and the
     owner, and by whoever opens the drive with its recovery key. That is the protection the virtual disk
     itself has (the drive's encryption and the folder's permissions), no more: an administrator account of
     the workstation is inside it;
   - the machine's protected store is the last choice: any account on the workstation, a desktop user's too,
     can open it, so it adds nothing to the Windows sign-in.
   If the task cannot run at all with nobody signed in (P-0 line 26a), neither can a key hand-over: then the
   fallback of D-602 point 4 is decided first.

## What is proven here, and what is not

Proven (Pester, every BitLocker command replaced): the order (before the import); drives already encrypted are
kept; both drives turned on and each key handed over; no digit group of a key in the log or the state; a
confirmed key is not asked for again; wrong digits, no answer, `-Yes`; no security chip; a suspended drive; a
system drive the TPM does not open; automatic unlock; `tpm_pin`; the rehearsal switch; the setting across the
restart. Proven (pytest): the judge under `tpm`, `tpm_pin`, no setting and an unknown one; the data drive's
automatic unlock; that the script holds no command that weakens a drive.

Not proven, by Microsoft's documentation and not run (Microsoft Learn: `Enable-BitLocker`,
`Add-BitLockerKeyProtector`, `Enable-BitLockerAutoUnlock`, `Get-Tpm`): that a recovery password can be added to
a drive before it is encrypted and read back; that `Enable-BitLocker -TpmProtector -UsedSpaceOnly
-SkipHardwareTest` then starts encryption without a restart; that `Enable-BitLocker -RecoveryPasswordProtector`
is accepted on a data drive that already has one; what status and protection Windows reports while the first
encryption runs; that only administrators can write `HKLM\SOFTWARE\TrialBox`; that `Clear-Host` empties the
window's scroll-back; that automatic unlock of the data drive is accepted while the system drive is
still encrypting; that `Out-Printer` prints; what the cmdlets answer on a PC with device encryption tied to a
Microsoft account, or under a domain policy that escrows keys. `key-probe.ps1` runs in no test here (Windows
stores and the Task Scheduler only): it is parsed, held to PowerShell 5.1 syntax, and read by a test for what it
must not do. P-0 lines 28 to 36c.

## Consequences

- Part 2 of NEW-WIN-8 (the key back end) waits for the owner's P-0 run. It needs a change in lane C's or lane
  D's files (`deploy/hardening/seal_keys.sh`, the KEK back ends of `tools/box/plan.py`): a back end that reads
  the key from WSL2's memory, where the boot task put it. That card is named to the integrator when the probe
  has answered.
- The handbook page for the BitLocker recovery screen (plan section 2.3, replacing the locked-box page of T-730)
  is NEW-WIN-9's.
