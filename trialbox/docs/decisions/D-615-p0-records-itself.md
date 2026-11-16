# D-615 P-0 records itself: the owner only starts it

- **Task:** NEW-WIN-12 (lane W), on the owner's ruling D-510 of 2026-11-15 (typed in the integrator's session): a
  session does the work itself; the owner gets decisions only; for P-0 his part is starting it
- **PR:** this branch (`agent/NEW-WIN-12-p0-records-itself`), stacked on NEW-WIN-11 (D-614, #644)
- **Date:** 2026-11-15
- **Status:** accepted for the parts below. Nothing in it has run on Windows. Three questions for the owner are on
  the integrator's inbox (BitLocker on his PC, how the media reaches him, a second PC); their answers fill
  `windows\p0.json` and the page, not the code
- **Builds on:** D-600 (the installer), D-603 (the key probe), D-605 (the media), D-613, D-614

## Context

The P-0 sheet had the owner build the media on Linux, type about 85 lines of commands, copy their output by hand and
send the sheet back; the media page had him remove Stage A's tree with a command between the stages. Under D-510 the
reading is an agent's job and the owner's part is to start P-0.

## Decision

1. **A recorder.** `deploy/windows/p0-record.ps1`, read only, writes one text file per occasion: the build and WSL,
   `.wslconfig`, the port proxy, the firewall rule, the network's profile, the IP Helper listener, the WSL adapter,
   every TrialBox task (state, sign-in, rights, last run and result, triggers, limits), BitLocker states and
   protector kinds (a key's value is never read), the key probe's lines, what doctor and `deploy/.env` say inside
   WSL2, and the installer's and the forwarding script's logs. A section that fails writes its error; the others go
   on. Anything shaped like a recovery key, and any first-run code, is masked before anything is written. It never
   starts WSL2: it reads inside WSL2 only when WSL2 already runs.
2. **Line 26a answered by the boot task itself.** `wsl2_started_before_sign_in`: yes when the task `TrialBox-WSL2`
   runs and started before the first sign-in after the start of Windows (Winlogon's event 7001), or nobody signed in
   since; no when WSL2 was not running, when the task does not run, or when it started after the sign-in. Whoever
   else may have started WSL2 first (the key probe's task, a person), the box returns by itself only if the boot
   task runs. WSL2's first process's start (from `/proc/1/stat` and the kernel's boot time) is written beside it.
3. **`box-install.ps1 -P0`.** After every run, also one that stopped: the recorder copied beside the state
   (administrators only), its task `TrialBox-P0-Record` (each start of Windows, six minutes in, S4U, ten-minute
   limit) registered once, one record written and the records copied to the media's `P0-RECORD` folder. Once the
   boot task exists, the key probe is armed for the next start, once (line 36a); it is collected only by a record
   written at a start of Windows, once its result is there (its collection removes its task). A record written at a
   start of Windows finds the media itself (a `TRIALBOX-*` folder with the checksum list, `p0.json` and the P-0
   launcher on any drive) and copies the records there: the owner keeps the disk plugged in over that restart. With several fixed NTFS drives,
   the one with the most room of those big enough is taken. The resume task carries `-P0`.
4. **The media carries the choices.** `tools.windows_media build --p0 [--rehearsal] [--skip-bitlocker]` puts
   `Install-TrialBox-P0.cmd` (the launcher with `-P0` added and nothing else; a test holds the two together) at the
   media's root and writes `windows\p0.json`; the checksum list covers both. With `-P0` the installer reads it at each
   run started by hand, from the media found in the install's own order (given, beside the installer, the state's),
   so Stage B's media is read, not Stage A's; a missing `p0.json`, or one it cannot read (a value not true or false),
   stops it before anything changes, and nothing of P-0 is done on that run. Nothing of P-0 is done on a run
   without `-P0`.
   Stage B's rehearsal stays one explicit choice (D-726's condition 1), made when the media is built, logged and said
   in the window as before.
5. **No command between the stages.** `wsl-setup.sh host-tree` replaces a host tree that no install has used (none
   of the done mark, `deploy/.env`, `deploy/settings.yaml`, `deploy/updates/installed.json`, the rehearsal mark or
   the first-run answers) when the media holds another release (its `HOST-SHA256SUMS` differs). A tree an install
   has used is kept as before, and the vendor-key check holds for it.
6. **The pages.** `P-0-BUILD-THE-MEDIA.md` opens with the owner's three steps; the rest is lane W's. The sheet is lane
   W's: it maps each record section to the lines it answers and names the lines no record answers (a prompt after
   the restart, the second PC, desktop work for P-11), which are not sent to the owner.

**Reuse check.** The installer's seams, its state, `key-probe.ps1` and `tools.windows_media` are used as they are;
the recorder reads with Windows' own cmdlets. A transcript of the whole session (`Start-Transcript`) was not chosen:
it would hold what the window shows, a recovery key among it (D-603 keeps a key off any transcript).

## What is proven here, and what is not

Proven here (Pester, 173 tests with the rest; Python tests): the recorder's sections, a failing section, the masking
of a key and of a first-run code, line 26a's answer in each case (task running before a sign-in, after it, with
nobody signed in, not running, WSL2 not running), the key probe left alone after a run and before its result, the
media found for a record at a start of Windows, wsl.exe's list in UTF-16, the copy to a missing disk. With `-P0`
(through the script's own top-level path): a record after a run and after a stop, the task registered once, the key
probe armed once and only after the boot task, `p0.json` read beside the installer over an earlier media in the
state, a missing or bad `p0.json` stopping with no task and no record, its choices carried over the restart, the
drive with the most room; nothing of this without `-P0`. The media with and without `--p0`; the launcher's one
difference. The host tree replaced when unused and from another release, kept when an install used it.

Not proven (Windows only, read from the records themselves at P-0): that each cmdlet answers as written on Windows
10 22H2 under S4U at a start of Windows (Winlogon's event 7001, `Get-BitLockerVolume`, `wsl.exe --list --running`
with `WSL_UTF8`); that `key-probe.ps1 -Collect` gives its lines when run by the record task rather than by the
signed-in owner; that the USB disk is writable for the copy.

## After the review

One fresh reviewer, verdict "fix first", two HIGH. Fixed test-first: the key probe was collected, and so removed,
by the record written right after it was armed (now collected only at a start of Windows, once its result is
there); the record of a start of Windows never reached the disk (it now finds the media itself; the page keeps the
disk plugged in). Also: line 26a now rests on the boot task, not on a file time that `/proc` sets when first read,
and not on whoever started WSL2 first; `p0.json` is read from the media found in the install's order, and a first
`-P0` run without one stops; nothing of P-0 happens on a run without `-P0` or after a bad `p0.json`; wsl.exe's
UTF-16 list is read; each section is written as it is read; doctor's output passes the support bundle's redaction;
an interrupted replacement's leftover is removed; the tests run through the script's own top-level path. Kept: a
release that differs replaces an unused tree even if older (the media is trusted and checked; an unused tree holds
nothing).

## Consequences

- The owner's part of P-0 is the three steps on `P-0-BUILD-THE-MEDIA.md`. Lane W builds the media and reads the
  records.
- Open until the owner answers: BitLocker on his PC (`--skip-bitlocker` or not), how the media reaches him, the
  second-PC check.
