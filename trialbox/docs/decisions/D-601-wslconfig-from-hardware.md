# D-601 `.wslconfig` from the hardware, and the memory caps held to WSL2's share

- **Task:** NEW-WIN-3 (`docs/plan/33-plan-v7.md` section 2.3; lane W)
- **PR:** this branch (`agent/NEW-WIN-3-wslconfig-from-hardware`), stacked on NEW-WIN-1 (D-600)
- **Date:** 2026-11-12
- **Status:** accepted for the arithmetic and the check built here; that the models load and answer under the
  share is measurement P-12 on the reference workstation, and the figure of point 2 is corrected from it
- **Owner decisions:** OD-10 (no figure that is not from the hardware or a declared setting with a reason), D-494
  point 7 (WSL2's share is computed from the installed hardware and one declared setting, the desktop's share)
- **Builds on:** D-600 (the installer), D-421 (`swap=0`, `sparseVhd`), D-466 and D-360 (`tools/box plan` shares
  the memory it sees among the compose caps)

## Context

`wslconfig.example` held a fixed 64 GB. `tools/box plan` runs inside WSL2 and sees only what `.wslconfig` gave
WSL2, so the file must exist, with the right figures, before WSL2 first starts. The workstation is also a desktop:
Windows and the person at it need a part of the memory and the processors.

## Decision

1. **Two readings and one setting.** The installer reads the installed memory (the sum of the memory modules, and
   never more than Windows reports it can use, to the nearest GB) and the logical processors on the Windows side
   (`Get-TbHardware`; the same two facts are added to `host_facts.ps1` as `installed_memory_gb` and
   `logical_processors`). WSL2 gets each, less the desktop's share, rounded down to a whole GB and a whole
   processor. A share that leaves less than 1 GB or one processor stops the installer (WSL2 cannot start on
   nothing; the share may be any whole percent from 0 to 99).
2. **The desktop's share is the declared setting `TB_WSL_DESKTOP_SHARE_PCT`, default 25.** The installer's
   `-DesktopSharePercent` has the same default (a test holds the two together). Reason for 25: on the reference
   workstation (192 to 256 GB, 16 cores or more) it leaves Windows 48 to 64 GB and four cores or more for office
   work, a browser and video calls (plan section 2.3 rule 6), and WSL2 144 to 192 GB. No measurement stands
   behind it yet: P-12 records the peak memory in WSL2 and the free memory in Windows, and the default is
   corrected from that record. The share an install used is kept in its `state.json`: a later start without the
   parameter uses the same share, and one with the parameter changes it. The product reads the setting in one
   place only, the remedy text of the doctor line; it steers nothing inside WSL2.
3. **The file.** `[wsl2] memory=`, `processors=`, `swap=0`, `defaultVhdSize=` the data drive's size in bytes (the
   virtual disk may grow to the drive, not to WSL's own default limit), `[experimental] sparseVhd=true`. Its
   first line starts with `# TrialBox`. It is written at step 6, before the distribution is imported.
4. **Whose file it is.** A `.wslconfig` that is plain ASCII and whose first line starts with `# TrialBox` is the
   installer's. On every start, also of a finished install, the installer computes the file again; when the
   result differs (memory was added, the share was changed) it keeps the earlier file beside it as
   `.wslconfig.before-trialbox-<time>`, writes the new one, and says that the figures apply when WSL2 next starts
   (a restart of Windows; the installer does not stop a running box). When nothing differs, nothing is written.
   An empty file is written like a missing one. Any other `.wslconfig` (another start, another encoding) is the
   account's own and is kept; the installer says that memory, processors and the disk limit are then that file's
   or WSL's own, and says when it lacks `swap=0`. The doctor line cannot see that case: the box plan caps the
   services to whatever memory WSL2 has.
5. **The caps must fit the share.** `trialbox doctor` gets the line `wsl2_memory`: on a WSL2 kernel it sums the
   memory caps of the services that run and FAILs when the sum is above WSL2's `MemTotal`. It reads the box's
   compose files as compose does: every file of `COMPOSE_FILE` (one that is missing is a FAIL, never a pass on a
   part), a later file's service overriding an earlier one's, a service behind a profile counted only when
   `COMPOSE_PROFILES` names it (in stub mode the model servers are not counted), `mem_limit` or
   `deploy.resources.limits.memory`, each `${VAR:-default}` from `deploy/.env`, sizes in bytes or with k, m, g.
   A service with no cap is named and makes the line a WARN. Without `--env-file` nothing is judged (WARN). On a
   plain Linux host, and on WSL1, it passes with "not WSL2". The model servers are counted at their caps: no serving record carries their measured host memory
   yet. When one does, the line takes the measured figure for them (a later card, with the cloud-run lane).

## What is proven here, and what is not

Proven: the arithmetic and the file's lines (Pester); that the file is written before the import; that a foreign
file is kept and the installer's own is rewritten; the doctor line on a fake `/proc`, including the real compose
set capped by `tools/box plan` at 144 GiB.

A finding for the box plan (lane D), not changed here: for the profile `rtx4090`, `tools/box plan` sets a cap for
the judge's server only, while the overlay it names (`docker-compose.rtx5090.yml`) also runs a verifier at its
48 GB default. The doctor line fails such a box; it is not the reference hardware.

`defaultVhdSize` is the whole data drive, as the card says. The drive also holds the installer's small staging
folder, so the virtual disk can never reach that limit: what WSL2 does when the drive fills first is not known
(P-0 line 22b). `host_facts.ps1` prints the two hardware facts for the record (the P-0 log, the host check's
input); the installer reads the same two through its own seam.

Not proven, by Microsoft's documentation and not run ("Advanced settings configuration in WSL"): that WSL2 honours
`memory`, `processors`, `swap=0` and `defaultVhdSize` as written and that `defaultVhdSize` applies to a
distribution imported after the file exists; that `Win32_PhysicalMemory` lists the modules on the workstation's
board; that `sparseVhd=true` is accepted and gives space back; that a changed file takes effect only after WSL2
restarts. These are P-0 lines 20 to 23b. That the models load and the dense night runs under the share is P-12.
