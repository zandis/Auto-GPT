# Windows install checklist: the box form (NEW-WIN-9, D-611; D-600 to D-610)

**Reader:** the box owner, or Aimedics for a prepared box.

For the person who sets the workstation up: the box owner, or an Aimedics engineer beside them. Hospital IT is
needed for two things only: the network address, and the data connection. Offline: the USB disk of
`OFFLINE-MEDIA.md`. The owner's own pages are `windows-owner.{en,ja,zh-TW}.md`; what a desktop user may run is
`desktop-use.{en,ja,zh-TW}.md`; backups are `WINDOWS-BACKUP-RESTORE.md`.

**Status.** The installer's logic is tested with every Windows command replaced by a stand-in. Nothing below has
run on Windows until the rehearsal (`P-0-windows-rehearsal.md`) has; until then keep that sheet beside this one
and write down where the two differ.

**Before the visit**
- [ ] The workstation: Windows 11 Pro, Pro for Workstations, Enterprise or Education (Home is refused), build
      22621 or later; an NVIDIA card; a second fixed NTFS drive with 500 GB free for the data (the installer
      chooses it when there is exactly one, and asks otherwise).
- [ ] The tier has a measured serving record on the media (`measured/`); without it the Linux installer refuses
      the tier.
- [ ] The media was built for this release and checked on the disk itself
      (`python3 -m tools.windows_media check`, `OFFLINE-MEDIA.md`).
- [ ] Hospital IT has the network sheet (`docs/network-sheet.*.html`): the console's port 443 from the site's own
      network, the mail server, no other inbound or outbound line. If IT manages Windows Update on this PC, they
      know the night's hours: their policy is kept by the installer, not replaced.
- [ ] The owner knows where the BitLocker recovery keys will be kept (a sealed envelope with hospital IT, or
      IT's own directory). Never on the workstation, never sent to Aimedics.

**On the workstation, as the administrator account that will own the box**
- [ ] Firmware: virtualisation (VT-x / AMD-V) on; a TPM present and ready.
- [ ] Install the NVIDIA Windows driver from the media's `windows\nvidia\` (the version the serving record
      names). No Linux NVIDIA driver is ever installed; the installer refuses a media or a system that has one.
- [ ] Double-click `Install-TrialBox.cmd`. It does, in order, and goes on by itself after the one restart Windows
      may need: the media check; Windows and the card; the data folder and BitLocker (each drive's recovery key is
      shown, printed if you say so, and confirmed by its last six digits before the drive is encrypted); WSL2 and
      its `.wslconfig` from the hardware; the Ubuntu image; Docker Engine and the NVIDIA Container Toolkit from
      the media; the card in a container; the start-at-boot task; the Windows Update window and "only
      administrators shut down"; the console's firewall rule; then the Linux installer in the same window.
- [ ] Options, only when needed (start `windows\box-install.ps1` from an administrator PowerShell):
      `-DataDrive D:`; `-DesktopSharePercent 25` (memory and processors kept for the desktop);
      `-BitLockerUnlock tpm_pin` (a person types a PIN at every restart; the site sets the PIN up with its IT);
      `-UpdateWindowStart 19 -UpdateWindowHours 6` (when Windows Update may restart the PC; outside the night).
- [ ] In the browser, on the address the window shows: the first-run code, then the set-up pages (the site, the
      people, mail). The window ends with "TrialBox is ready".
- [ ] With hospital IT: the data connection (the source folder or share), and `trialbox backup-keygen`: the
      private key on their USB stick, in a sealed envelope (RUNBOOK §5).
- [ ] Backups (`WINDOWS-BACKUP-RESTORE.md`): the hospital's share, or an outside USB disk marked with
      `box-install.ps1 -BackupDrive E:`; then measure the path once (`wsl-setup.sh backup-speed`).
- [ ] Create a standard Windows account for each person who uses this PC as a desktop, and hand them
      `desktop-use.<language>.md`. The NVIDIA Control Panel setting on that page is set once, by hand.

**Check, then hand over**
- [ ] From an administrator PowerShell:
      `wsl -d TrialBox -u root -- sh -c 'cd /opt/trialbox && python3 -m tools.trialbox doctor --env-file deploy/.env --settings deploy/settings.yaml'`:
      no FAIL line. The lines of this form: `wsl2_memory`, `update_window`, `wsl2_versions`, `backup`,
      `backup_speed`.
- [ ] The host check, from an elevated terminal: `wsl -d TrialBox -u root -- sh /opt/trialbox/deploy/check_host.sh`:
      no FAIL line (BitLocker, the recovery keys' keeper, the page file, hibernation, WSL swap, Remote Desktop,
      Windows Update, drivers, the sign-in screen, the start-at-boot task, the clock, the virtual disk). Again
      after every Windows feature update.
- [ ] Restart Windows, do not sign in, wait five minutes, then open the console from another PC on the site's
      network: it answers. This is the proof that the box comes back with nobody there.
- [ ] `sudo python3 -m tools.trialbox secrets rotate` inside WSL2 with the owner present: new tokens and database
      passwords that Aimedics has never seen (RUNBOOK §5 "Secrets").
- [ ] Print `deploy/site/network-sheet.<lang>.html` (the site's own sheet) for hospital IT.
- [ ] Run the go-live acceptance (RUNBOOK §6) and sign the install record. Keep the installer's log with it:
      `C:\ProgramData\TrialBox\box-install\box-install.log` (no secret is written to it).

**Later**
- After a change of hardware (memory, a disk, the card) or of drive letters: start `Install-TrialBox.cmd` once
  more. It changes nothing that is right and puts right what follows the hardware.
- The virtual disk is sparse and gives freed space back; where the host check says it only grows, compact it
  monthly (`wsl --shutdown`, then `Optimize-VHD` or `diskpart compact vdisk`).
- Never: `wsl --unregister TrialBox` (it deletes the box's data), Docker Desktop, a Linux NVIDIA driver inside
  WSL2, an export of the distribution kept as a "backup".
