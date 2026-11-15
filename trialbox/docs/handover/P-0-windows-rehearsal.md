# P-0: the Windows installer rehearsed on a Windows 10 or Windows 11 PC with an NVIDIA card

**Reader:** the box owner, who runs the rehearsal, and the people who build TrialBox, who read its result.

Plan v7.2 section 7.2, test P-0; plan step 8a (due 2027-01-08). Cards NEW-WIN-1 (D-600), then NEW-WIN-3, NEW-WIN-2
and NEW-WIN-8 as they land: this sheet grows one part per card.

**Why this run exists.** The installer's logic is tested in CI with every Windows command replaced by a stand-in.
Nothing in it has run on Windows. This run is the first time. Each line below is a behaviour the installer relies
on from Microsoft's or NVIDIA's documentation and has not seen.

**The machine.** A Windows 10 22H2 (build 19045) or Windows 11 PC (Pro, Pro for Workstations, Enterprise or
Education) with an NVIDIA card and
its Windows driver, virtualisation on in the firmware, and 500 GB free on a fixed NTFS drive (with less room, add
`-MinFreeGB <what the drive has>` in step 3 and write the figure down). It may be your own computer: first read
"On your own computer" in `P-0-BUILD-THE-MEDIA.md`, which says what the run changes for the whole computer and how
each part is put back. The run removes nothing.

**Data.** Synthetic only. No patient data, no site secret. How to build a media, in two stages (first without Docker, with a stand-in
bundle; then with a signed bundle whose models are placeholders): `docs/handover/P-0-BUILD-THE-MEDIA.md`. Build it with
`python3 -m tools.windows_media build` and check the copy on the disk with `python3 -m tools.windows_media check`
(`docs/handover/OFFLINE-MEDIA.md`, "Making the media").

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
| 13 | Step 14 `linux-install` (steps 12 `boot-task` and 13 `network` come before it: Parts 3, 5 and 6) | The Linux installer's own text in the same window: the hardware, the question "Is this the machine", the install's progress, then an address and a one-time code | Whether the question was visible **before** you typed; minutes to the code. Do not record the code |
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
| 23a | After the install is finished, start the installer once more with `-DesktopSharePercent 50` (in an administrator PowerShell: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<media>\windows\box-install.ps1" -DesktopSharePercent 50`) | "WSL2 is given ..." with half the PC's figures; "The earlier .wslconfig was kept as ..."; the console stays up. `free -g` inside WSL2 still shows the OLD figure | The window's text; `free -g` before a restart |
| 23b | Restart Windows, sign in, `wsl -d TrialBox -- free -g` and `nproc` | The NEW figures. Then start the installer with `-DesktopSharePercent 25` to put the share back, and restart once more | Both outputs |

## Part 3: NEW-WIN-2, start without a person (D-602)

After step 12 `boot-task` has run. With a Stage A media the install stops in step 14, which is enough for this part
except lines 26b, 27 and 27c (they need a finished install). This part is the reason P-0 exists: nobody has seen
WSL2 start from the boot task.

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
| 36a | **The key probe, the run that decides.** Once step 12 has run (a Stage A media is enough), as the owner in an administrator window: `powershell -NoProfile -ExecutionPolicy Bypass -File <media>\windows\key-probe.ps1 -AtStartup`. Restart Windows. **Do not sign in for five minutes.** Sign in, then `... key-probe.ps1 -Collect` | Lines `mode=at_startup`, `ran_at=`, `ran_as=`, `desktop_shells_running=0`, then `dpapi_user=`, `dpapi_machine=`, `acl_file=`, `wsl_handover=`, each `ok` or `fail: <why>` | All of its lines, and the time you signed in. `ran_at` must be before your sign-in and `desktop_shells_running` 0: otherwise the run did not happen with nobody there, and it is repeated |
| 36b | The same probe on demand, for comparison: `... key-probe.ps1` (no switch) | The same lines with `mode=on_demand` | All of its lines |
| 36c | `Get-ScheduledTask TrialBox-Key-Probe` afterwards | No such task | The answer |

## Part 5: NEW-WIN-4, the console on the site's network (D-604; the rehearsal of P-14)

Needs a second PC on the same network (a laptop on the same switch or Wi-Fi). After Part 1 is finished. **On
Windows 10** lines 37 and 38 are Part 9's instead (no mirrored networking, no Hyper-V firewall); lines 39 to 44
are the same.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 37 | At step 13 read the window; then `wsl -d TrialBox -- wslinfo --networking-mode`, `Get-NetFirewallHyperVRule -Name TrialBox-Console` and `Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'` | "The console will answer on this PC's name, port 443 ..."; `mirrored`; the rule: inbound, TCP 443, RemoteAddresses LocalSubnet, enabled; the setting: DefaultInboundAction Block | The answers in full (LoopbackEnabled too); the PC's Windows build (`winver`), `wsl --version`, and the network's profile (`Get-NetConnectionProfile`) |
| 38 | On this PC: `wsl -d TrialBox -- ip -j -4 addr show scope global`, `ipconfig`, and `wsl -d TrialBox -u root -- grep CLINIC_RANGES /opt/trialbox/deploy/site/hardening.conf` | WSL2 shows the PC's own network address; CLINIC_RANGES is that network. The installer's window had no "not open to the network this PC is on" warning | The three outputs. If CLINIC_RANGES is a 10.255.255.254/32 or another adapter's network, the console will not answer from other PCs: record it and go on |
| 39 | From the **second PC**: open `https://<this PC's name>/` in a browser | The console's sign-in page (a certificate warning is expected: the box's own certificate) | Whether the name opened it; if not, whether `https://<this PC's IPv4 address>/` did; `Resolve-DnsName <this PC's name>` on the second PC (IPv4, IPv6 or both) |
| 40 | From the second PC, in PowerShell: `443, 80, 22, 2375, 3389, 5432, 8000, 8010, 8020, 8080, 8090, 9090 \| ForEach-Object { Test-NetConnection <this PC's name> -Port $_ -WarningAction SilentlyContinue \| Select-Object RemotePort, TcpTestSucceeded }` | True for 443 only | The table. Any other True is a finding: say which port |
| 41 | On **this PC**, signed in as a **standard** account: open `https://localhost/` and `https://<this PC's name>/`; then `8090, 8010, 9090, 5432, 2375 \| ForEach-Object { Test-NetConnection localhost -Port $_ -WarningAction SilentlyContinue \| Select-Object RemotePort, TcpTestSucceeded }` | The console opens (staff use it at the workstation). False for every other port | Which address opened the console; the table |
| 42 | **Outward: is the egress table loaded.** `wsl -d TrialBox -u root -- bash /opt/trialbox/deploy/windows/wsl-setup.sh egress-check` | "egress table trialbox_egress loaded; trialbox-egress.service active" | The line |
| 43 | **Outward: does it act.** `wsl -d TrialBox -u root -- bash /opt/trialbox/deploy/windows/wsl-setup.sh egress-proof` (the installer ran the same at the end of step 14) | A line naming a container, `result=no-connection`, `denied_after` larger than `denied_before`, then `verdict=held` | Both lines exactly. `verdict=OUT` means a container reached outside: the most important finding of this part. `verdict=inconclusive` is recorded as it is; it is not a pass |
| 43a | Name lookups from a container that is allowed out: `wsl -d TrialBox -u root -- sh -c 'docker exec $(docker ps --format "{{.Names}}" \| grep -m1 mail-gateway) getent hosts localhost'` and the mail settings' test in the console, if a mail server was given | A name is answered; mail to the configured server works | What was printed (typed as shown, with single quotes outside) |
| 44 | Restart Windows, sign in, and repeat lines 39, 40 and 43 | The same answers | Any difference after the restart |

## Part 6: NEW-WIN-5, Windows Update, the driver and the right to shut down (D-606)

Everything here is by Microsoft's documentation and has not been seen run: the policy values "Configure Automatic
Updates" (`AUOptions`, `ScheduledInstallTime`), "Turn off auto-restart for updates during active hours"
(`SetActiveHours`, `ActiveHoursStart`, `ActiveHoursEnd`), "Do not include drivers with Windows Updates"
(`ExcludeWUDriversInQualityUpdate`), the user right "Shut down the system" set with `secedit`, and "Shutdown: Allow
system to be shut down without having to log on".

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 45 | After the install, read the log's lines of step 12 | "Windows Update: drivers excluded", "Windows Update: installs daily at 19:00; restarts by itself only from 19:00 to 1:00", "shutdown right was: ..." | The lines; on a PC joined to a domain, whether it said "a policy is already set ... kept" instead |
| 46 | Settings, Windows Update, Advanced options | "Some settings are managed by your organization"; active hours shown as 01:00 to 19:00 and not changeable | What the page shows; a screenshot |
| 47 | `gpresult /scope computer /v` is **not** the place (these are local registry values); instead in an administrator PowerShell: `Get-ItemProperty HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate, HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU` | `AUOptions 4`, `ScheduledInstallTime 19`, `SetActiveHours 1`, `ActiveHoursStart 1`, `ActiveHoursEnd 19`, `ExcludeWUDriversInQualityUpdate 1` | The values |
| 48 | Sign in as a **standard** account. Open the Start menu's power button | No "Shut down" and no "Restart" (sign out and lock stay). Note whether "Sleep" is offered | What the menu offers; if Shut down is still there, sign out and in once more and look again |
| 49 | At the sign-in screen (nobody signed in), the power button at the lower right | No shut down offered | What it offers |
| 50 | As the standard account, in a terminal: `shutdown /s /t 0` | "Access is denied" (5) | The text |
| 51 | **Does the window hold.** With an update waiting (a PC that is behind on updates). The rehearsal PC holds synthetic data only and may be online for this line; a site workstation is never put online for it. Nobody restarts the PC or schedules a restart by hand during this line. Leave the PC on over one window. Next day: `Get-WinEvent -FilterHashtable @{LogName='System'; Id=1074} -MaxEvents 5 \| Format-List TimeCreated, Message` | Any restart Windows Update started lies between 19:00 and 01:00; none outside | Each restart's time and who asked for it. This line can take days; record what was seen and when |
| 52 | After line 51's restart, nobody signs in. From another PC, or after signing in: was TrialBox back? `Get-ScheduledTaskInfo TrialBox-WSL2` | The task ran at startup; the console answers (line 23) | LastRunTime against the restart's time |
| 53 | Device Manager, the NVIDIA card, Driver tab; and inside WSL2 `nvidia-smi --query-gpu=driver_version --format=csv,noheader` | The same version before and after line 51's updates | Both versions, before and after |
| 54 | `wsl -d TrialBox -u root -- sh -c 'cd /opt/trialbox && python3 -m tools.trialbox doctor --env-file deploy/.env --settings deploy/settings.yaml'`, the lines `update_window` and `wsl2_versions` | `update_window` WARN with the window the installer set and the time between the night's start and the window (WARN, not PASS: the night's length is not measured; also WARN when `settings.yaml` names no `nightly_at`); `wsl2_versions` WARN "no serving record for the card" on a rehearsal PC (its card was never measured), with the driver and the kernel it read | Both lines whole |
| 55 | The host check from inside WSL2 (`deploy/check_host.sh`, an elevated terminal), the Windows lines | PASS "installs at 19:00 and restarts by itself only from 19:00 to 1:00", PASS "takes no drivers", PASS "the sign-in screen does not offer it" | The three lines |
| 56 | Start the installer once more with `-UpdateWindowStart 12 -UpdateWindowHours 8` | "restarts this PC by itself only between 12:00 and 20:00"; line 47's values follow (install time 12, active hours 20 to 12); `cat /opt/trialbox/deploy/site/box/windows-update-window` inside WSL2 says `12+8`, and line 54 judges that window | The values; then set it back by starting it with `-UpdateWindowStart 19 -UpdateWindowHours 6` |

## Part 7: NEW-WIN-6, the card shared with the desktop (D-607; the rehearsal of P-11)

The rehearsal PC's card is not the site's card and its models are the small stand-in: the figures here show
whether each reading works, not whether the real pair has room. That is P-11, on the reference workstation.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 57 | With TrialBox up, inside WSL2: `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits`; then open a browser with a video on the Windows desktop and run it again | Two whole numbers; the first grows when the desktop program starts: WSL2 sees the memory Windows programs hold | Both readings, with and without the browser |
| 58 | The console's health line (or `wsl -d TrialBox -u root -- sh -c 'cd /opt/trialbox && python3 -m tools.trialbox ops run'` and then the health page) | A part "programs outside TrialBox hold X GiB of the graphics card; Y GiB is spare beside the models", or "no serving record says what the models need" on a rehearsal PC without a record | The line whole. Did the health facts get written at all (the runner is a timer as root inside WSL2)? |
| 59 | The host check from an elevated terminal (`deploy/check_host.sh`), the line "graphics card by program (Windows)" | "WSL2 holds N MiB; programs outside TrialBox hold M MiB (name MiB, ...)". The process name Windows gives WSL2's virtual machine (`vmmem` or `vmmemWSL`) is counted as WSL2, not as outside | The line whole; in Task Manager, Details, the name of the WSL2 process; whether N is near the models' memory or near zero (if near zero, Windows does not attribute WSL2's card memory to that process and the line must be corrected) |
| 60 | NVIDIA Control Panel, Manage 3D settings, Global Settings: is there "CUDA - Sysmem Fallback Policy"? Set "Prefer No Sysmem Fallback". Then, inside WSL2, start a program that asks for more card memory than is free (the installer's GPU probe image with a large allocation, or a second copy of the stand-in model server) | With the setting: the program fails at once with an out-of-memory error, and TrialBox's models keep answering at their usual speed. Without it: note what happens | Whether the setting exists on this driver; what the over-asking program did with and without it; the console's response time during it. This decides whether the setting governs WSL2 at all |
| 61 | Start a GPU program on the Windows desktop that takes most of the spare card memory (a game or a renderer). Look at the health line after two minutes | "red", naming how much programs outside TrialBox hold; line 59 names the program | The line; the minutes it took to turn |
| 62 | The host check's line "administrator accounts". Then create a standard account (Settings, Accounts, Other users), sign in with it, and try: `wsl --shutdown`, `wsl -l -v`, opening `<data drive>\TrialBox` in Explorer | "administrator accounts: one"; the standard account sees no TrialBox distribution (`wsl -l -v` lists none of the owner's), cannot stop it, and Explorer refuses the folder | Each answer. If `wsl --shutdown` by a standard account stops the owner's distribution, rule 5 of the plan does not hold on this Windows |

## Part 8: NEW-WIN-7, backup paths (D-608)

Needs a USB disk (BitLocker on it or not) and, if there is one, a file share the rehearsal PC can reach. Every
mount line below is as Microsoft documents WSL2 to print it; none has been seen.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 63 | After the install: `wsl -d TrialBox -u root -- cat /opt/trialbox/deploy/site/box/windows-drives`, and the log's line "this PC's own drives recorded" | The letters of the system drive, the data drive and every other fixed drive; **not** the media's letter when the media is a USB disk | The line; `Get-Disk \| Format-Table Number, BusType, FriendlyName` beside it. A USB disk that Windows lists with another BusType than USB breaks the rule: write its BusType down |
| 64 | Plug in the USB disk (say it becomes `E:`). Inside WSL2: `ls /mnt/e` | The disk's files. If `/mnt/e` is not there: `mkdir -p /mnt/e && mount -t drvfs E: /mnt/e`, and note that a drive plugged in after WSL2 started is not mounted by itself | Whether it was there by itself; `grep -E " /mnt/[a-z] " /proc/mounts` whole (this is the line the backup check reads: the source `E:\` or `drvfs`, the type `9p`, `path=E:\` in the options) |
| 64a | In an administrator PowerShell: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<media>\\windows\\box-install.ps1" -BackupDrive E:`; then the same with the data drive's letter, and with a letter that does not exist | "Drive E: is marked as an outside drive for backups", and a file `.trialbox-outside-drive` at `E:\\`; the data drive: "one of this PC's own drives"; the missing letter: "could not be checked or marked" | Each message; `(Get-Partition -DriveLetter E \| Get-Disk).BusType` for the USB disk (the rule needs it to read `USB`) |
| 65 | Set `TB_BACKUP_TARGETS=/mnt/e/trialbox` in `deploy/.env`, make the folder, then `python3 -m tools.trialbox doctor --env-file deploy/.env`, the `backup` line | The target counted as off-box ("1 off-box") | The line whole. Before line 64a it must say "no off-box backup target"; so must `/mnt/d/...` (the data drive) |
| 66 | `bash /opt/trialbox/deploy/windows/wsl-setup.sh backup-speed /mnt/e/trialbox 1024`, and the same for a folder inside WSL2 (`/opt/trialbox/deploy/backups`) | `mbps=...` for each; the test file is gone | Both speeds: this is the figure nobody has for a path through Windows |
| 67 | `doctor`'s `backup_speed` line | PASS, or the value to set for `TB_BACKUP_MIN_MBPS` | The line |
| 68 | `python3 -m tools.trialbox backup-nightly --deploy deploy` to the USB disk | It ends with a good backup on `/mnt/e/trialbox`; no step "stopped as hung" | Its duration; the file's size; any step that was cut |
| 69 | **With nobody signed in.** Restart Windows, do not sign in, wait for the night's backup time (or set the schedule a few minutes ahead before restarting). Then sign in and look at the target and at `deploy/site/backup-last.json` | A new backup on the USB disk: the drive was reachable from the boot task's session | Whether `/mnt/e` existed in that session. This decides whether an outside drive works unattended at all |
| 70 | The same as line 69 with the file share (`mount -t drvfs '\\server\share' /mnt/share` as root, target `/mnt/share/trialbox`) | Expected to **fail** when nobody is signed in: the boot task's sign-in (S4U) carries no network credentials, so Windows cannot reach the share for it | What happened, with the error. If it fails, the share is mounted another way (CIFS inside WSL2 with a credentials file kept in `/etc`, root only), which is a card of its own |

## Part 9: NEW-WIN-10, Windows 10 22H2 (D-613; owner ruling D-503)

Only on a Windows 10 PC (build 19045). Windows 10 has no mirrored networking for WSL2: the installer adds one
port-proxy rule for the console's port, kept pointed at WSL2's own address by the task `TrialBox-Console-Proxy`,
and one Windows Firewall rule for that port from this PC's own network on private and domain networks only. By
Microsoft's documentation (netsh `interface portproxy`; Task Scheduler with S4U); none of it has been run.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 71 | Before the installer: `winver`, and in PowerShell `(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber`; `wsl --version` | Build 19045; WSL 2.x | The three answers. A WSL that was already on is kept |
| 72 | At step 6, read `%USERPROFILE%\.wslconfig` | `localhostForwarding=false` and no `networkingMode` line | The file. If you already had a `.wslconfig`, it was kept as it is: write down whether it sets `localhostForwarding` |
| 73 | At step 13, read the window; then `netsh interface portproxy show v4tov4` and `wsl -d TrialBox -- hostname -I` | One row `0.0.0.0 443 <WSL2's address> 443`, the address the same as `hostname -I`'s first | Both outputs |
| 74 | `Get-NetFirewallRule -Name TrialBox-Console \| Format-List Enabled,Direction,Action,Profile`; `Get-NetFirewallRule -Name TrialBox-Console \| Get-NetFirewallAddressFilter`; `Get-NetConnectionProfile` | Enabled, Inbound, Allow, profile `Domain, Private`, remote address `LocalSubnet`. The network this PC is on shows as Private or Domain | All of it. **If the network shows Public, the console is not reachable from other PCs**: record it; the fix is the network's profile, which is the site's IT's choice |
| 75 | `Get-ScheduledTask TrialBox-Console-Proxy \| Format-List State,Principal`; `Get-ScheduledTaskInfo TrialBox-Console-Proxy` | Ready; LogonType S4U, RunLevel Highest; LastTaskResult 0 | The values |
| 76 | On this PC: `https://localhost/` and `https://<this PC's name>/` | The console's sign-in page on both | Which opened |
| 77 | From the second PC: lines 39 and 40 | As there | As there |
| 78 | **Does the rule follow WSL2.** `wsl --shutdown`, wait one minute, `wsl -d TrialBox -- hostname -I` (WSL2 starts again with a new address), then wait up to 6 minutes and run `netsh interface portproxy show v4tov4` | The row points at the new address; the console opens again from the second PC | The minutes until it pointed right; `C:\ProgramData\TrialBox\box-install\console-proxy.log`'s last lines |
| 79 | **With nobody signed in.** Restart Windows, do not sign in, wait 6 minutes, then from the second PC open the console | It answers | Whether it answered before anyone signed in. With line 26a this decides whether Windows 10 serves a site unattended |
| 80 | The host check (`deploy/check_host.sh`, an elevated terminal), its Windows lines | No FAIL for the network form; a WARN that Windows 10's support has ended | The lines whole |
| 81 | **Is anything listening.** `Get-Service iphlpsvc \| Format-List Status,StartType`; `netstat -ano -p tcp \| findstr :443`; then `tasklist /svc /fi "PID eq <the PID netstat shows>"` | Running, Automatic; one `LISTENING` line on `0.0.0.0:443`, its process a `svchost.exe` that hosts `iphlpsvc` | All three outputs. A row in line 73 with no listener here means the IP Helper service does not serve it |
| 82 | **The task's limits.** `$t = Get-ScheduledTask TrialBox-Console-Proxy`; `$t.Triggers \| ForEach-Object { $_.Repetition \| Format-List Interval,Duration }`; `$t.Settings.ExecutionTimeLimit` | One trigger with Interval `PT5M` and a Duration of about ten years (`P3650D`); ExecutionTimeLimit `PT2M` | The values. A Duration of one day or less means the five-minute runs stop |
| 83 | **Which address is forwarded to.** `wsl -d TrialBox -u root --exec ip -4 -o addr show dev eth0`; `Get-NetIPAddress -AddressFamily IPv4 \| Where-Object InterfaceAlias -like 'vEthernet (WSL*' \| Format-List InterfaceAlias,IPAddress,PrefixLength` | eth0's address is the one in line 73's row, and inside the subnet of the `vEthernet (WSL...)` adapter | Both outputs, with the adapter's exact name: a later card may refuse an address outside that subnet (D-613) |

## Part 10: NEW-WIN-11, Stage B as a rehearsal box (D-614; lane D's D-726)

Stage B only, started with `-Rehearsal` (P-0-BUILD-THE-MEDIA.md, "On the Windows PC", step 4). By reading; not run.

| # | Do | Expect | Record |
| --- | --- | --- | --- |
| 84 | Read the window at its start; then, after step 14, `wsl -d TrialBox -u root -- grep -E '^TB_(ENV|REHEARSAL)=' /opt/trialbox/deploy/.env` and `wsl -d TrialBox -u root -- ls /opt/trialbox/deploy/site/rehearsal.json` | "This is a rehearsal install" before step 1 changes anything; `TB_ENV=TEST` and `TB_REHEARSAL=1`; the mark is there | The window's first lines and both outputs |
| 85 | `wsl -d TrialBox -u root -- bash -c "cd /opt/trialbox && python3 -m tools.trialbox doctor --env-file deploy/.env"`, the `rehearsal` line | WARN "rehearsal box"; no FAIL for it | The line whole |

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
- Lines 39, 40, 41 and 43 decide the networking form (D-604): mirrored networking is kept when the console opens from
  the second PC, only port 443 answers there and on localhost, and line 43 says `verdict=held`, also after the
  restart (line 44). `verdict=OUT`: the egress rule moves to Windows Firewall, or the port proxy is built as a card
  of its own. Line 38 wrong: the fix is in the box plan's network detection (lane D), not in the form.
- Line 14: the address NEW-WIN-4 must make work from another PC.
- Line 46 or 47 wrong: the policy values are not the ones Windows 11 reads on this edition; the window is then set
  by the site's IT, and the installer only checks.
- Line 48 or 50 "shut down still possible": the user right did not take (a domain policy sets it back, or secedit's
  form is wrong); line 49 is a separate value and is read separately.
- Line 51 "a restart outside the window": active hours do not bind a scheduled install the way D-606 point 2
  assumes; the next form to try is Windows' maintenance windows (24H2), else "notify only" (hospital IT starts
  installs).
- Line 53 "the driver changed": the exclusion does not hold the driver; `wsl2_versions` then fails by design, and
  the driver is held another way (a device-installation restriction for the card's hardware id).
- Line 57 "the first number does not grow": WSL2 does not see Windows programs' card memory; the health line
  `desktop_gpu` then cannot work from inside WSL2 and must read Windows (line 59's counters, through the boot task).
- Line 59 "N near zero": the per-program line is corrected to say only what Windows programs hold.
- Line 60 decides the handbook's NVIDIA step: kept, or struck when it has no effect on WSL2.
- Line 62 "a standard account stopped WSL2": owner decision needed; the distribution would then run under a
  service account no desktop user shares a session with.
- Line 63 "the USB media's letter is among them", or line 64's mount line reads differently: the rule of D-608
  point 2 is corrected to what Windows really prints before any site relies on an outside drive.
- Line 66 gives the first measured speed of a backup path through Windows; `TB_BACKUP_MIN_MBPS`'s default for
  the Windows form is set from it.
- Lines 69 and 70 decide which off-box target a site can use unattended: the outside drive, the share, or the
  share mounted by CIFS inside WSL2.
- Line 73 or 78 "no row", or a row that does not follow WSL2: the port proxy does not serve WSL2 on this PC as
  Microsoft documents it; the console on Windows 10 then needs another form (WSL's own localhost forwarding behind
  a rule for the PC's address), a card of its own.
- Line 74 "Public": the console stays closed to other PCs until the site's IT names the network private or domain;
  the installer does not change a network's profile.
- Line 79 "no": as line 26a "no".
- Line 81 "no listener" with a row in line 73: the IP Helper service does not serve the port proxy on this PC; the
  installer checks only that the service runs, so this is a card of its own.
- Line 84 "no `--rehearsal` reached the Linux installer" (no mark, `TB_ENV` not TEST): the hand-over in
  `wsl-setup.sh install`; fix in lane W. A refusal "holds a site's install ... from no rehearsal" after Stage A: the
  box is emptied (`docs/runbook/16-box-install-rehearsal.md`, "A rehearsal box") and the install started again with `-Rehearsal`.
- Line 82 "a short Duration": the task is registered with the repetition written out another way
  (`console-proxy.ps1`), a fix within lane W.
