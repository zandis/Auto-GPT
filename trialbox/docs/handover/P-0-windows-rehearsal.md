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
| 22a | `wsl -d TrialBox -- dmesg` (the first screen), and the size of `<drive>\TrialBox\wsl\ext4.vhdx` in Explorer before and after copying a 10 GB file into WSL2 and deleting it again (`wsl -d TrialBox -- sudo fstrim -av` once after the delete) | No message that WSL rejected a setting of `.wslconfig` (`sparseVhd`, `defaultVhdSize`); the file shrinks again after the delete | Any "wsl:" warning shown when WSL2 starts; the three sizes |
| 22b | Only on a PC where the drive may be filled: nothing to do in P-0. Note for P-15: what WSL2 does when the drive fills before the virtual disk's limit is not known | - | - |
| 23 | After line 15: `wsl -d TrialBox -u root -- bash -c "cd /opt/trialbox && python3 -m tools.trialbox doctor --env-file deploy/.env"` | A line `wsl2_memory` with PASS (WARN if it names a service with no cap), the caps' sum and WSL2's memory. With the small stand-in model the model servers are not in the sum | That line |
| 23a | After the install is finished, start the installer once more with `-DesktopSharePercent 50` (in an administrator PowerShell: `<media>\windows\box-install.ps1 -DesktopSharePercent 50`) | "WSL2 is given ..." with half the PC's figures; "The earlier .wslconfig was kept as ..."; the console stays up. `free -g` inside WSL2 still shows the OLD figure | The window's text; `free -g` before a restart |
| 23b | Restart Windows, sign in, `wsl -d TrialBox -- free -g` and `nproc` | The NEW figures. Then start the installer with `-DesktopSharePercent 25` to put the share back, and restart once more | Both outputs |

## Part 3: NEW-WIN-2, start without a person (D-602)

After Part 1 is finished. This part is the reason P-0 exists: nobody has seen WSL2 start from the boot task.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 24 | In an administrator window: `Get-ScheduledTask TrialBox-WSL2`, `powercfg /a` | The task is Ready or Running; hibernation is listed as not available | The task's State; the `powercfg /a` text |
| 25 | Note the time. Restart Windows. **Do not sign in.** Wait five minutes at the sign-in screen. From this PC nothing can be seen yet; if a second PC is on the same network, try the console's address from it and note what happens (it is expected to fail until NEW-WIN-4) | (nothing to see on this PC) | The time of the restart and the time you signed in at line 26 |
| 26a | Sign in. At once, in an administrator window: `wsl --list --running`, then `wsl -d TrialBox -- uptime -s` and `Get-ScheduledTaskInfo TrialBox-WSL2` | `TrialBox` is running; `uptime -s` shows a start time **before** you signed in. **This line alone answers whether the task can start WSL2 with nobody signed in** | The outputs, with LastRunTime and LastTaskResult. "Yes" or "no" for this line by itself |
| 26b | `wsl -d TrialBox -- systemctl is-active docker trialbox`, `wsl -d TrialBox -- docker ps --format "{{.Names}} {{.Status}}"` | Docker `active`. **The stack itself is expected NOT to be fully up before NEW-WIN-8:** WSL2 has no security chip, so the site keys wait for a passphrase after every restart. Record what is up; a "no" here says nothing about line 26a | Both outputs |
| 27 | Open the console on this PC's browser | The sign-in page, without starting anything by hand | Seconds from sign-in until the page answered |
| 27a | As a **standard** account: `Get-ScheduledTask TrialBox-WSL2`, `Stop-ScheduledTask TrialBox-WSL2`, `Disable-ScheduledTask TrialBox-WSL2`; and Start, Power, Sleep | The task commands are refused. Sleep from the Start menu is still offered to a standard account (the installer changes timers, not that button): record it for NEW-WIN-5 | What each answered; whether Sleep was offered |
| 27b | As the administrator: `Stop-ScheduledTask TrialBox-WSL2`, wait two minutes, `Get-ScheduledTask TrialBox-WSL2`, `wsl --list --running` | The task is Running again within about a minute, and `TrialBox` with it | The state after two minutes; whether the console stayed up meanwhile |
| 27c | With the install finished and the console up, double-click `Install-TrialBox.cmd` again | "Nothing was changed"; the console does not go down; the task's LastRunTime is unchanged (a task that is there is kept, not started again) | LastRunTime before and after |
| 27d | The log's lines of step 12 | No "did not accept a power setting" line. On a PC with no hibernation support such a line is expected and the install went on | The lines |
| 27e | If the account is a domain or Microsoft Entra account: repeat line 25 and 26a with the network cable out | The same as 26a | Whether the task ran with no domain controller in reach |

## Part 4: NEW-WIN-8, BitLocker and the key probe (D-603)

**Choose first.** On a PC that may be encrypted (and stay so), run the installer as it is: lines 28 to 35 happen
during Part 1, at step 4. On a PC that must stay unencrypted, add `-SkipBitLocker` to the installer's start, skip
to line 36a, and write that you did. Never send a recovery key back; write only "shown" and "confirmed".

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 28 | Before the installer: `Get-BitLockerVolume` and `Get-Tpm` in an administrator window | (the starting point) | For each drive: VolumeStatus, ProtectionStatus, the protector types (not the key). TpmPresent, TpmReady. Whether the PC is signed in with a Microsoft account or joined to a domain |
| 29 | At step 4, on a drive that was not encrypted | "BitLocker recovery key for drive C:" with 48 digits, the question about the printer (it names the printer), then the request for the last six digits; the window is cleared; only then does encryption start. **No restart is asked for** | Whether the key appeared BEFORE `Get-BitLockerVolume` (in another window) showed the drive encrypting; whether a restart or a "hardware test" was asked for; any red text. Not the key |
| 29a | Close the installer's window while it waits for the six digits (once, on a drive that was not encrypted), then `Get-BitLockerVolume` | The drive is still FullyDecrypted (a recovery password protector may be listed; nothing is encrypted). Starting the installer again shows the same key | VolumeStatus; whether the same key came again (yes or no) |
| 30 | Answer `y` to the printer question on one drive | A page with the key comes out of the printer the question named | Whether it printed; the printer's kind (beside you, shared, "print to PDF"); what the window said if it did not |
| 31 | Type six wrong digits once, then the right ones | "Those are not the last six digits", then the window is cleared and the install goes on | Whether the key can still be scrolled back to in the window |
| 32 | A second drive, if the PC has one and you chose it as the data drive | Its own key the same way; no "did not set it to open together with the system drive" stop | `Get-BitLockerVolume` for it right after step 4: AutoUnlockEnabled, and how many RecoveryPassword protectors it lists (two are expected). After the next restart (line 25): is the drive open before anyone signs in? |
| 33 | On a PC that came already encrypted | The window shows the existing key and asks for its last six digits; nothing is encrypted again | Whether the key shown equals the one in your Microsoft account or on your sheet (yes or no, not the key) |
| 34 | During and after the install: `Get-BitLockerVolume`, and the host check's lines (`wsl -d TrialBox -u root -- sh /opt/trialbox/deploy/check_host.sh`, the lines that start "BitLocker") | Both drives EncryptionInProgress, later FullyEncrypted with protection On. The host check: while encrypting "still encrypting" or a FAIL naming the state; when done "starts with nobody there (bitlocker_unlock=tpm ...)", "unlocks with the system drive" and "BitLocker recovery: password kept by the box owner" | VolumeStatus AND ProtectionStatus while it encrypts (the installer assumes protection may read Off then); the host check's lines at both times |
| 34a | Start the installer again while a drive still encrypts | It goes on; no "suspended" stop | The window's text at step 4 |
| 35 | Search for a recovery key where it must not be: `Select-String -Path C:\ProgramData\TrialBox\box-install\box-install.log -Pattern "\d{6}-\d{6}"`, the same on `state.json`, and `Get-ChildItem $env:USERPROFILE\Documents -Filter PowerShell_transcript* -Recurse` | No match in the two files. No transcript file (if there is one, the PC records PowerShell windows: the installer should have stopped instead of showing a key) | The three answers |
| 35a | As a **standard** account: `Set-ItemProperty HKLM:\SOFTWARE\TrialBox -Name BitlockerUnlock -Value tpm` | Refused | The answer |
| 36a | **The key probe, the run that decides.** After the install is finished, as the owner in an administrator window: `powershell -NoProfile -ExecutionPolicy Bypass -File <media>\windows\key-probe.ps1 -AtStartup`. Restart Windows. **Do not sign in for five minutes.** Sign in, then `... key-probe.ps1 -Collect` | Lines `mode=at_startup`, `ran_at=`, `ran_as=`, `desktop_shells_running=0`, then `dpapi_user=`, `dpapi_machine=`, `acl_file=`, `wsl_handover=`, each `ok` or `fail: <why>` | All of its lines, and the time you signed in. `ran_at` must be before your sign-in and `desktop_shells_running` 0: otherwise the run did not happen with nobody there, and it is repeated |
| 36b | The same probe on demand, for comparison: `... key-probe.ps1` (no switch) | The same lines with `mode=on_demand` | All of its lines |
| 36c | `Get-ScheduledTask TrialBox-Key-Probe` afterwards | No such task | The answer |

## Part 5: NEW-WIN-4, the console on the site's network (D-604; the rehearsal of P-14)

Needs a second PC on the same network (a laptop on the same switch or Wi-Fi). After Part 1 is finished.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 37 | At step 13 read the window; then `wsl -d TrialBox -- wslinfo --networking-mode` and `Get-NetFirewallHyperVRule -Name TrialBox-Console` | "The console will answer on this PC's name, port 443 ..."; `mirrored`; the rule exists: inbound, TCP 443, RemoteAddresses LocalSubnet | The three answers; the PC's Windows build (`winver`) and `wsl --version` |
| 38 | On this PC: `wsl -d TrialBox -- hostname -I` and `ipconfig` | WSL2 shows the PC's own network address (not a 172.x address of its own) | Both address lists |
| 39 | From the **second PC**: open `https://<this PC's name>/` in a browser | The console's sign-in page (a certificate warning is expected: the box's own certificate) | Whether the name opened it; if not, whether `https://<this PC's address>/` did; the browser's message |
| 40 | From the second PC, in PowerShell: `443, 80, 22, 5432, 8000, 8080, 2375, 3389 \| ForEach-Object { Test-NetConnection <this PC's name> -Port $_ -WarningAction SilentlyContinue \| Select-Object RemotePort, TcpTestSucceeded }` | True for 443 only | The table. Any other True is a finding: say which port |
| 41 | From a PC on **another** network, if one is at hand (a phone's hotspot counts): the same test of port 443 | False | The answer, or "no other network at hand" |
| 42 | **Outward.** On this PC: `wsl -d TrialBox -u root -- sh -c "systemctl is-active trialbox-egress.service; nft list table inet trialbox_egress \| head -20"` | `active`, and the table's first lines | The output |
| 43 | A container must have no way out: `wsl -d TrialBox -u root -- sh -c "docker exec $(docker ps --format '{{.Names}}' \| grep -m1 lake) python3 -c \"import socket; s=socket.create_connection(('1.1.1.1', 443), 5); print('OUT')\""` | An error (timed out or refused), not `OUT` | What was printed. `OUT` means the egress table does not hold under this form: the most important finding of this part |
| 44 | Restart Windows, sign in, and repeat lines 39, 40 and 43 | The same answers | Any difference after the restart |
| 45 | **The other form, by hand, for comparison only** (do this last; it changes `.wslconfig`): write down the answers above; in `C:\Users\<you>\.wslconfig` change `networkingMode=mirrored` to `networkingMode=nat`; `wsl --shutdown`; start WSL (`wsl -d TrialBox -- true`); note WSL2's address (`wsl -d TrialBox -- hostname -I`); as administrator: `netsh interface portproxy add v4tov4 listenport=443 listenaddress=0.0.0.0 connectport=443 connectaddress=<that address>` and `New-NetFirewallRule -DisplayName TrialBox-Console-Proxy -Direction Inbound -Protocol TCP -LocalPort 443 -RemoteAddress LocalSubnet -Action Allow`. Repeat lines 39, 40 and 43. Then put it back: `netsh interface portproxy delete v4tov4 listenport=443 listenaddress=0.0.0.0`, `Remove-NetFirewallRule -DisplayName TrialBox-Console-Proxy`, `networkingMode=mirrored` again, `wsl --shutdown` | (a comparison) | The same three answers under this form, and that everything was put back |

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
- Line 26a "no" (WSL2 started only after the sign-in): the S4U task cannot start WSL2. D-602 point 4: the fallback is
  chosen with NEW-WIN-8. This is the most important answer of the whole sheet; send it even if nothing else is done.
  Line 26b does not enter this decision: it shows what NEW-WIN-8 still has to make true.
- Line 29 "a restart was asked for": BitLocker cannot be turned on in one pass; the installer's step must carry it
  across a restart like step 5 does.
- Line 32 "no": the data drive stays locked after a restart; the stack cannot come back by itself.
- Line 29 "the drive was encrypting before the key appeared", or line 29a "the drive was encrypted": the order of
  D-603 point 2 does not hold on Windows; BitLocker is then set up by hand until it does.
- Line 34 "protection Off while encrypting": expected; anything else is recorded for the judge's wording.
- Line 36a: the key back end is built on the first of `dpapi_user`, `acl_file`, `dpapi_machine` that says `ok` AT
  STARTUP, and needs `wsl_handover=ok` there. Line 36b does not decide: a store that is `ok` only on demand is of
  no use. All `fail` at startup with line 26a "yes": a stored password for the task, or a service (D-602 point 4).
- Lines 39, 40 and 43 decide the networking form (D-604): mirrored networking is kept when the console opens from the
  second PC, only port 443 answers and the container has no way out, also after the restart (line 44). If line 43
  prints `OUT` under mirrored networking and not under line 45's form, the port proxy is built; if under both, the
  egress rule moves to Windows Firewall.
- Line 14: the address NEW-WIN-4 must make work from another PC.
