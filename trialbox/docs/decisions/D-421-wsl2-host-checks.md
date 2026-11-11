# D-421 Windows with WSL2: facts read on Windows, one judge in WSL2, BitLocker in place of LUKS

- **Task:** T-210a, Windows/WSL2 hardening part a (`docs/plan/28-master-plan-v6.md` §6.2.5, row T-210a)
- **PR:** this branch (`agent/T-210a-wsl2-hardening`)
- **Date:** 2026-11-11
- **Status:** accepted; checked on stand-in command output only, the run on a real workstation remains
- **Closes:** CR-041 (first third: the Windows checks; the KEK is T-210b, encrypted outputs T-210c), OPS-061

## Context

TrialBox runs in WSL2 on Windows only on a hospital's written demand (D-408). `preflight.ps1` had six checks and none
for data at rest: no BitLocker, swap, hibernation or Remote Desktop check, and the keys were plain files (CR-041).
OPS-061 added four ways the box fails in practice: Windows Update restarts at night, WSL2 stops when nobody is signed
in, the two clocks drift, and the distribution's disk file only grows. `check_host.sh` judged LUKS, which a WSL2 host
does not have.

## Decision

1. **Facts and judge apart.** `deploy/windows/host_facts.ps1` only reads and prints `key=value` lines in a
   language-neutral form (enum names from `Get-BitLockerVolume`, `Get-ScheduledTask`, registry numbers; never the
   localised text of `manage-bde` or `powercfg`), so a Japanese or Chinese Windows prints the same lines.
   `deploy/windows/wsl2_policy.py` (standard library) is the one judge, for `preflight.ps1` before the install (it runs
   the judge through `wsl.exe`) and `check_host.sh --wsl2` after it (it runs the facts script through interop). The
   two cannot disagree, and the judge is tested on Linux.
2. **What FAILs always** (data at rest): BitLocker not fully on for the system drive, the drive of `ext4.vhdx` or a
   page-file drive; a plain `Tpm` protector on the system drive (the TPM alone opens it, and with the start-at-boot
   task a stolen workstation boots to a running stack; the same rule as D-408 for LUKS); hibernation, Fast Startup or
   a `hiberfil.sys`; `.wslconfig` without `swap=0`; free space on the disk file's drive below 10%; clocks more than
   60 s apart.
3. **What FAILs in VALIDATION and PRODUCTION and WARNs in DEV and TEST** (policy): no recovery password, or no
   statement of where it is kept (`-RecoveryKeyEscrow` / `--escrow`: the check cannot see an escrow, so the operator
   says it and the line records it); Remote Desktop on; Windows Update with no policy or one that restarts by itself;
   the start-at-boot task missing, not at startup, only for a signed-in user, disabled or not starting `wsl.exe`.
4. **What WARNs**: updates at a scheduled time (the time is printed, to agree with hospital IT), a pending restart,
   a disk file that is not sparse, free space below 20%, clocks 6 to 60 s apart, the Windows Time service stopped.
5. **`check_host --wsl2`**, on by itself on a WSL2 kernel: the WSL2 lines take the place of the LUKS, unlock and TPM
   device lines of T-634 at the same place; every other baseline line keeps its T-634 order. Run WSL from an elevated
   terminal: BitLocker's protectors need administrator rights (without them only Explorer's BitLocker state is read,
   a policy line).
6. **Templates:** `deploy/windows/wslconfig.example` (`swap=0`, `sparseVhd=true`) and
   `deploy/windows/register_keepalive.ps1` (a task at startup, S4U so it runs whether or not anyone is signed in, one
   `wsl.exe` kept open and restarted within a minute).

## Consequences

- The KEK on WSL2 has no `/dev/tpm*`: the `tpm` back end of D-408 does not apply there. T-210b brings the Windows
  back end (DPAPI or the Windows TPM) or uses `passphrase` or `shamir`.
- The facts format has a version (`facts_version=1`); a facts script and a judge from different releases FAIL once.
- Remains: one run on the rental workstation, both factory state and hardened, to confirm the cmdlets' output and
  that WSL2 runs from an S4U task.
