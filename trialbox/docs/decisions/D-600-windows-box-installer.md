# D-600 The Windows installer: what it may change, how it continues, what it never removes

- **Task:** NEW-WIN-1 (`docs/plan/33-plan-v7.md` section 2.3; lane W)
- **PR:** this branch (`agent/NEW-WIN-1-box-install-ps1`)
- **Date:** 2026-11-12
- **Status:** accepted for the logic built and tested here; nothing in it has run on Windows. The run on a Windows
  11 PC with an NVIDIA card is test P-0 (`docs/handover/P-0-windows-rehearsal.md`)
- **Owner decisions:** D-494 (the site machine is a Windows workstation, TrialBox in WSL2, Docker Engine inside
  WSL2, no Linux NVIDIA driver), OD-10 (no figure that is not from the hardware or a declared setting), OD-13 (the
  audience is the box owner: one installer, no shell step)
- **Builds on:** D-466 (`deploy/box-install.sh`, the first-run wizard), D-421 (WSL2 host checks), D-367 (the signed
  host tree), D-125 (the offline media)

## Context

`deploy/box-install.sh` installs TrialBox on Linux. D-494 put the site's machine under Windows. The owner starts
one file on the offline media; everything between a factory Windows and the first-run code must follow from it,
across the restart that enabling WSL2 needs. The machine is also a desktop and may already hold a TrialBox with
data, so the rules below say what the installer may touch.

## Decision

1. **One installer, twelve steps, each checks the machine first.** `deploy/windows/box-install.ps1` (started by
   `Install-TrialBox.cmd`) runs the steps `media`, `windows`, `gpu-driver`, `drive`, `wsl-enable`, `wslconfig`,
   `import`, `systemd`, `packages`, `gpu-container`, `host-tree`, `linux-install`. No step trusts a note that an
   earlier run "did" it: each one reads the machine. A second run therefore goes on where the first stopped. The
   steps inside WSL2 are `deploy/windows/wsl-setup.sh`, run as root, one step per call.
2. **It never removes or replaces what it did not make.** There is no `wsl --unregister`, no delete and no format
   in it. A WSL distribution of the chosen name that this install did not import stops it. A virtual disk already
   in the data folder stops it. `/opt/trialbox` that is not a host tree stops it. An existing `.wslconfig` is
   kept as it is (and reported when it lacks `swap=0`). An install this installer finished is left alone: a second
   start changes nothing, and `wsl-setup.sh install` refuses a box that carries the done mark.
3. **The distribution is the box's own.** Name `TrialBox`, imported to `<data drive>\TrialBox\wsl`. It is not the
   desktop user's `Ubuntu`. It belongs to the Windows account that ran the installer (WSL keeps distributions per
   account): the installer records that account and refuses to continue under another.
4. **Folders it makes are closed to standard accounts.** `<data drive>\TrialBox` and
   `%ProgramData%\TrialBox\box-install` are made for SYSTEM, the administrators and the installing account, with
   nothing inherited. A folder of that name that another account owns is refused. Reason: the first holds the
   virtual disk and the scripts WSL2 runs as root; the second holds the script the resume task runs elevated.
5. **The restart.** When Windows reports that a feature or the WSL package needs a restart, the installer copies
   itself to the state folder, registers the task `TrialBox-Install-Resume` (at this account's sign-in, elevated,
   no stored password), asks the owner to press Enter, and restarts. After the sign-in the task runs the copy with
   `-Resume`; the step that finds WSL ready removes the task. The task's definition holds two paths and no secret.
6. **The media is checked for damage, not for origin, on Windows.** Every file the installer uses must be listed
   in the media's `SHA256SUMS` and match it. The WSL package must carry a valid Microsoft signature. The release's
   origin is checked where it always was: `deploy/install.sh` verifies the bundle's Ed25519 signature inside WSL2
   before it loads anything, and goes on from the signed host tree (D-367). The installer shows the vendor key's
   sha256 for the owner to compare with the sheet given out of band. A person who can alter the media can alter
   the installer on it; the media's custody is the control for that, as for the Linux form.
7. **No Linux NVIDIA driver, three times.** A driver package among the media's packages stops the step before
   `dpkg` runs; an installed driver package or a loaded kernel driver stops it before and after the packages. The
   container toolkit's packages are not a driver.
8. **A container sees the card before the Linux installer starts.** No image is on the box yet and none may be
   downloaded. `wsl-setup.sh gpu` builds a probe image from the system's own files (the Windows driver's
   `nvidia-smi` and the C library it links to; the driver's libraries are left out) and runs it with `--gpus all`:
   it answers only when the NVIDIA Container Toolkit brought the driver into the container.
9. **The Linux installer owns the window.** `box-install.sh` runs attached to the installer's window, so the
   owner sees its question and the first-run code there. Its output is not captured by PowerShell and not written
   to the log. `wsl-setup.sh` passes it through a reader that keeps one thing: whether the line "TrialBox is
   ready" came. Then it writes the done mark `deploy/site/box/windows-install-done`. An exit code other than 0
   with the mark present means the host check still has FAIL lines; the install is counted as done and the owner
   is told.
10. **The log is the P-0 record.** `%ProgramData%\TrialBox\box-install\box-install.log`, in English whatever the
    window's language: every step's start, `ok` or `STOP step n/12 <name>: <reason>`, and the output of the steps
    inside WSL2. No password, no first-run code, no key. The window's messages are in en, ja and zh-TW
    (`box-install.messages.json`), chosen from the Windows display language.
11. **Figures.** `-MinFreeGB` (500, the figure `preflight.ps1` and `preflight.sh` declare, D-125),
    `-MinWindowsBuild` (22000, the first Windows 11) and `-StartWaitSeconds` (120, how long a restarted
    distribution may take to show systemd) are declared parameters with their reasons in the script. `.wslconfig`
    gets `swap=0` and no memory or processor figure: those come from the hardware in NEW-WIN-3.

## What is proven here, and what is not

Proven in CI (job `powershell`, Pester on PowerShell 7 on Linux, every Windows command replaced): the order of
the steps; every refusal of point 2 and the edition, virtualisation, driver, disk and media refusals; the restart
and the continuation; a run interrupted at each WSL2 step and started again imports once; the log's lines.
Proven by `tests/unit/test_windows_box_install.py` on stubs: each step of `wsl-setup.sh`, the messages.

Not proven, and on the P-0 checklist: everything a seam replaces. In particular, by the vendors' documentation
and not run: that `Enable-WindowsOptionalFeature` reports the restart; that a task with run level "highest" starts
elevated at sign-in without a prompt; that `wsl --import` refuses an existing name; that a fixed drive is mounted
at `/mnt/<letter>` and a USB disk mounts with `mount -t drvfs`; that the toolkit brings the driver's library into
a container made by `docker import`; that Windows PowerShell 5.1 runs the file as PowerShell 7 parses it (the
analyzer's 5.1 syntax rule is the only check here); the folder permissions of point 4.

## Consequences

- For lane D, not built here: `deploy/box-install.sh` under WSL2 still writes `/etc/issue.d` (harmless, never
  shown) and calls `timedatectl set-timezone` (Windows keeps the clock). A WSL2 switch there is a card of lane D.
  This installer does not depend on it.
- NEW-WIN-3 replaces the `wslconfig` step's file with one computed from the hardware; NEW-WIN-2 registers the
  boot task; NEW-WIN-8 BitLocker and the keys; NEW-WIN-4 the console's address on the site's network. Until
  NEW-WIN-4, which address opens the first-run page from the workstation's own browser is a P-0 observation.
