# D-603 BitLocker opened by the TPM, the recovery key handed to the owner, and a probe for the key back end

- **Task:** NEW-WIN-8, part 1 of 2 (`docs/plan/33-plan-v7.md` section 2.3; lane W)
- **PR:** this branch (`agent/NEW-WIN-8-bitlocker-unlock`)
- **Date:** 2026-11-13
- **Status:** accepted for the installer's logic and the judge. Nothing in it has run on Windows: P-0 lines 28 to
  36. The key back end itself (part 2) is not built: its mechanism is chosen from the probe's answer
- **Owner decisions:** D-494 point 6 (Q9: BitLocker on every drive, opened by the TPM, the recovery key printed and
  held by the box owner; `bitlocker_unlock` `tpm` by default, `tpm_pin` for a site that wants a person at every
  restart), OD-13 (the owner sets the box up)
- **Changes:** D-421 point 2, one line: a TPM-only protector on the system drive is accepted when the box's
  setting says `tpm`. Every other line of D-421 stands
- **Builds on:** D-600 (the installer), D-602 (the boot task, sign-in type S4U), D-421 (`wsl2_policy.py`)

## Decision

1. **The installer turns BitLocker on, before any data is on the drive.** At step 4 (`drive`), after the data
   folder is made and before WSL2 is imported: the system drive with the TPM as its protector, the data drive
   with its own recovery key and automatic unlock (it opens with the system drive). Only the space in use is
   encrypted first; Windows encrypts the rest as it fills. A drive that is already encrypted is kept as it is.
2. **The installer never weakens a drive.** It holds no command that turns BitLocker off, suspends it, removes a
   protector or clears automatic unlock. A drive whose BitLocker is suspended or being removed stops it. An
   encrypted system drive that the TPM does not open stops it (the owner adds the TPM in Windows).
3. **The recovery key is handed to a person, and stored nowhere.** For each drive the 48-digit key is shown in
   the installer's window, printed on the default printer when the owner says so, and confirmed by typing its
   last six digits back. Only then does the install go on; the state file notes the drive's letter as confirmed,
   never the key. The key is not written to the log, the state, a file, or a program's arguments. A key that
   Windows already held (a PC that came encrypted) is read back and handed over the same way. With `-Yes` nobody
   is there to receive a key: a drive that needs a new key stops the installer; a drive that is already
   encrypted goes on with a warning that its key was not confirmed.
4. **`bitlocker_unlock`.** `-BitLockerUnlock tpm` (the default, D-494) or `tpm_pin`. The installer records the
   choice in `HKLM\SOFTWARE\TrialBox\BitlockerUnlock` (only administrators write there), `host_facts.ps1` prints it
   as the fact `bitlocker_unlock`, and `wsl2_policy.py` judges by it: under `tpm` a system drive the TPM opens
   passes ("starts with nobody there"), and one it does not open fails; under `tpm_pin` the TPM alone fails, as
   D-421 wrote. **No setting recorded is judged as `tpm_pin`**: a workstation that the box installer did not set
   up keeps D-421's rule, and none of D-421's tests changes. With `tpm_pin` the installer does not set a PIN (it
   needs a Windows policy and a person who will know it): it requires the TPM-and-PIN protector to be there
   already and stops otherwise.
5. **The data drive must open by itself.** The judge fails a data drive whose automatic unlock is off (the
   virtual disk would stay locked after a restart); the installer turns it on.
6. **What `tpm` leaves standing** (D-494, said again in the installer's window): a person who takes the whole
   workstation gets a machine that starts; between them and the data stand the Windows sign-in and the console's
   sign-in, and, once part 2 is built, whatever protects the site keys.
7. **`-SkipBitLocker`** leaves BitLocker as it is, for a rehearsal on a PC that must stay unencrypted. Nothing
   is recorded, and the host check fails the drive. It is not for a site.
8. **The key back end is chosen by a probe, not by guessing.** WSL2 has no security chip, so today the site keys
   under WSL2 wait for a passphrase after every restart. The key must come from Windows, handed over by the
   boot task, whose sign-in type (S4U, no stored password) may not be allowed to open every Windows store.
   `deploy/windows/key-probe.ps1` stores a **dummy** value three ways (the account's protected store, the
   machine's protected store, a file only SYSTEM, the administrators and the owner may read on the BitLocker
   drive), runs a one-time task with the boot task's sign-in type, and reports which the task could read back
   and whether it could hand the value into WSL2's memory. The owner runs it at P-0 (line 36). Part 2 builds the
   back end on the strongest way that answered `ok`:
   - the account's protected store, if the task can open it: the key is bound to the owner's account;
   - else the closed file on the BitLocker drive: the key is as safe as the drive and the folder's permissions
     (the same protection the virtual disk itself has);
   - the machine's protected store is the last choice: any account on the workstation, a desktop user's too,
     can open it.
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
`Add-BitLockerKeyProtector`, `Enable-BitLockerAutoUnlock`, `Get-Tpm`): that `Enable-BitLocker -TpmProtector
-UsedSpaceOnly -SkipHardwareTest` starts encryption without a restart; that a recovery key can be added and
read back while encryption runs; that automatic unlock of the data drive is accepted while the system drive is
still encrypting; that `Out-Printer` prints; what the cmdlets answer on a PC with device encryption tied to a
Microsoft account, or under a domain policy that escrows keys. `key-probe.ps1` runs in no test here (Windows
stores and the Task Scheduler only): it is parsed, held to PowerShell 5.1 syntax, and read by a test for what it
must not do. P-0 lines 28 to 36.

## Consequences

- Part 2 of NEW-WIN-8 (the key back end) waits for the owner's P-0 run. It needs a change in lane C's or lane
  D's files (`deploy/hardening/seal_keys.sh`, the KEK back ends of `tools/box/plan.py`): a back end that reads
  the key from WSL2's memory, where the boot task put it. That card is named to the integrator when the probe
  has answered.
- The handbook page for the BitLocker recovery screen (plan section 2.3, replacing the locked-box page of T-730)
  is NEW-WIN-9's.
