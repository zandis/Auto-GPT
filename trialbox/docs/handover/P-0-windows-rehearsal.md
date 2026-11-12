# P-0: the Windows installer rehearsed on a Windows 11 PC with an NVIDIA card

Plan v7.2 section 7.2, test P-0; plan step 8a (due 2027-01-08). Cards NEW-WIN-1 (D-600), then NEW-WIN-3, NEW-WIN-2
and NEW-WIN-8 as they land: this sheet grows one part per card.

**Why this run exists.** The installer's logic is tested in CI with every Windows command replaced by a stand-in.
Nothing in it has run on Windows. This run is the first time. Each line below is a behaviour the installer relies
on from Microsoft's or NVIDIA's documentation and has not seen.

**The machine.** Any Windows 11 PC (Pro, Pro for Workstations, Enterprise or Education) with an NVIDIA card and
its Windows driver, virtualisation on in the firmware, and 500 GB free on a fixed NTFS drive (with less room, add
`-MinFreeGB <what the drive has>` in step 3 and write the figure down). Not a machine that holds anything you need:
the run enables Windows features, restarts once, and adds a WSL system. It removes nothing.

**Data.** Synthetic only. No patient data, no site secret. Use a media built with the small stand-in model.

**What to send back.** The file `C:\ProgramData\TrialBox\box-install\box-install.log` (it holds no password, no
first-run code and no key), this sheet with each line marked, and a photo or the text of the window wherever a
line says "record". Never send the first-run code, a password, or the BitLocker recovery key.

## Part 1: NEW-WIN-1, the installer

Mark each line **yes**, **no** or **not reached**. On a "no", stop, record the window's last ten lines, and send
the log: the installer can be started again later and goes on from the step that stopped.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 1 | Sign in with the administrator account that will own the box. Open the media in Explorer | The folder `TRIALBOX-<version>` with `Install-TrialBox.cmd` | Windows edition and build (`winver`); the card and driver version; drive letters and free space |
| 2 | Double-click `Install-TrialBox.cmd` | One Windows prompt asking to allow changes (UAC), then a PowerShell window titled as administrator. No red text about execution policy | Whether a "file came from another computer" warning appeared |
| 3 | Watch step 1 `media` | "Checking the media": several minutes for the bundle; no "damaged" message | Minutes it took |
| 4 | Steps 2 to 4 | The card's line is shown; the data folder `<drive>\TrialBox` is named. With one other fixed drive it is chosen without a question; otherwise the window asks for a drive letter | The drive chosen; whether it asked |
| 5 | In a second, **non-administrator** PowerShell window (a standard account if the PC has one): `Get-ChildItem <drive>\TrialBox` and `Get-ChildItem C:\ProgramData\TrialBox\box-install` | Both answer "Access is denied" | The exact answer of each |
| 6 | Step 5 `wsl-enable` on a PC where WSL was never on | The window says Windows must restart and waits for Enter | Whether it asked for a restart (a PC that already had WSL goes straight on: record that) |
| 7 | Press Enter. After the restart sign in with the same account | A PowerShell window opens by itself, elevated, with **no** UAC prompt, and the installer goes on from step 5 | Seconds from sign-in to the window; whether a prompt appeared; whether the media's drive letter changed |
| 8 | Step 6 and 7 | `C:\Users\<you>\.wslconfig` exists with `swap=0`; "Setting up the Linux system TrialBox" | `wsl --list --verbose` in another window: `TrialBox`, version 2. `<drive>\TrialBox\wsl\ext4.vhdx` exists |
| 9 | Step 8 `systemd` | No "did not start with systemd" message | From the log: how many `pid1` lines before `systemd` |
| 10 | Step 9 `packages` | "Installing Docker Engine and the NVIDIA Container Toolkit"; no error from `dpkg` | The log's line "Docker Engine <version> with the nvidia runtime" |
| 11 | Step 10 `gpu-container` | "A container sees the graphics card: <the card's name, driver, memory>" | The line. On a failure: the log's lines of this step in full (this is the step least certain to work as written) |
| 12 | Step 11 `host-tree` | "Compare this line with the key sheet": a sha256 | Whether it equals the sheet's |
| 13 | Step 12 `linux-install` | The Linux installer's own text in the same window: the hardware, the question "Is this the machine", the install's progress, then an address and a one-time code | Whether the question was visible **before** you typed; minutes to the code. Do not record the code |
| 14 | On this PC's browser open the address shown. If the name does not open, try `https://localhost/login/first-run` | The first-run page | Which of the two addresses opened, and the browser's certificate message. (From another PC is NEW-WIN-4's part) |
| 15 | Finish the set-up in the browser | The window ends with "TrialBox is ready" and then "The install is finished" or the note about FAIL lines of the host check | The host check's FAIL and WARN lines (BitLocker, the boot task and the update policy are expected until NEW-WIN-2 and NEW-WIN-8) |
| 16 | Double-click `Install-TrialBox.cmd` again | "TrialBox is already installed on this machine by this installer. Nothing was changed." | The window's text |

**Smaller observations during Part 1** (from the adversarial review of #362; each is a behaviour the installer
assumes). Write them down as you go; none needs an extra run.

| # | Look at | The installer assumes | Record |
| --- | --- | --- | --- |
| 16a | Step 1 on a PC with no network | The WSL package's Microsoft signature reads "Valid" offline | A "not signed by Microsoft" stop here means the check needs the network: record it |
| 16b | Step 5 before the WSL package is installed (the log's first lines of the step) | The Windows-supplied `wsl.exe --version` fails at once, without asking for a key press | Whether the window waited for a key |
| 16c | A media folder whose path has a space (for example `E:\TrialBox media\TRIALBOX-1.0`) | The launcher and every WSL2 step take the path as one piece | Use such a path if you can; record where it broke if it did |
| 16d | Before line 1, as a **standard** account: try to make the folder `C:\ProgramData\TrialBox`. Then run the installer as the administrator | If the standard account could make it and put a file in it: the installer stops with "already exists and belongs to another account". If the folder was empty or absent: it goes on, and afterwards the standard account cannot open it | Which of the two happened |
| 16e | After line 15, as a standard account: `wsl --list` and `wsl --shutdown` | The owner's `TrialBox` is not listed, and the console still answers after the standard account's `wsl --shutdown` (plan section 2.3 rule 5) | Both outputs; whether the console went down |
| 16f | At line 7, if the PC has a second account: sign in with **that** account first after the restart | Nothing starts for that account; signing in as the owner afterwards continues the install | What happened |
| 16g | Start `Install-TrialBox.cmd` and answer **No** to the Windows prompt | The first window stays open with a message and "Press any key" | The text |
| 16h | Unplug the media before signing in at line 7 (a USB disk only) | The window says to connect the media and to start again; after plugging it in, also under another drive letter, a new start continues | The window's text; the two drive letters |

**Interruptions** (after line 16, on the same PC, only if time allows; each is one restart of the installer):

| # | Do | Expect |
| --- | --- | --- |
| 17 | In an administrator PowerShell: `wsl --shutdown`, then start the installer again with `-StateDir C:\tb-p0-state2 -DataDrive <the same drive>` | It stops at step 7 `import`: "A WSL system named TrialBox already exists ... did not make it". `wsl --list` still shows `TrialBox`; the virtual disk's size and date are unchanged |
| 18 | Read `Get-ScheduledTask TrialBox-Install-Resume` | No such task (it was removed when step 5 found WSL ready) |
| 19 | On a drive with no `TrialBox` folder (or on a second PC): as administrator make `<drive>\TrialBox` in Explorer, put any file in it, and start the installer with `-StateDir C:\tb-p0-state3 -DataDrive <that drive>` | It stops at step 4 `drive`: "The folder ... already exists and belongs to another account" (a folder open to other accounts is taken only when empty). The file is still there. Then empty the folder and start again: step 4 passes and line 5's "Access is denied" holds for it |

## Part 2: NEW-WIN-3, `.wslconfig` from the hardware (D-601)

Read these during Part 1; they need no extra run.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 20 | At step 6 read the window, then open `C:\Users\<you>\.wslconfig` in Notepad | "WSL2 is given N GB of memory and M processors; 25 percent ... stays with Windows". The file's `memory=` and `processors=` are three quarters of the PC's, rounded down | The PC's installed memory and logical processors (Task Manager, Performance) and the file's two lines |
| 21 | After step 8, in another administrator window: `wsl -d TrialBox -- free -g` and `wsl -d TrialBox -- nproc` | Total memory within 1 GB of the file's `memory=`; `nproc` equal to `processors=`; the Swap line is 0 | The three figures |
| 22 | `wsl -d TrialBox -- df -h /` | The size of `/` is near the data drive's size, not 1 TB | The Size column and the drive's size |
| 23 | After line 15: `wsl -d TrialBox -u root -- bash -c "cd /opt/trialbox && python3 -m tools.trialbox doctor --env-file deploy/.env"` | A line `wsl2_memory` with PASS, the caps' sum and WSL2's memory | That line |

## What the answers decide

- Line 2 "no": the launcher or the execution policy; fix in `Install-TrialBox.cmd`.
- Line 19 "no": a folder that a standard account could write to was taken with its contents; D-600 point 4 does
  not hold on Windows as written. This blocks NEW-WIN-8.
- Line 16d or 16e "no": a standard account can reach the installer's folder or stop the box; this blocks NEW-WIN-8
  and goes to NEW-WIN-6.
- Line 5 "no": the folder permissions of D-600 point 4 are not what the installer set; a standard desktop account
  could read the virtual disk. This blocks NEW-WIN-8.
- Line 7 "no": the continuation after the restart needs another form (for example a start-up shortcut that asks
  for elevation); the owner would otherwise start the installer by hand, which already works.
- Line 11 "no": the probe image of D-600 point 8 is replaced by a small image on the media.
- Line 13 "question not visible": the pass-through in `wsl-setup.sh install` holds lines back; fix there.
- Line 20 or 21 "no": WSL2 does not take the share the installer wrote; NEW-WIN-3's file is wrong for this WSL
  version. Line 22 "no": the disk limit needs `wsl --manage TrialBox --resize` after the import instead.
- Line 14: the address NEW-WIN-4 must make work from another PC.
