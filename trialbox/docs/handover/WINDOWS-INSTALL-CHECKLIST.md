# Windows install checklist for Aimedics engineers (D-125, D-138)

**Since NEW-WIN-1 (D-600):** the lines under "On Windows" from "Install WSL" on, and all of "In WSL2 Ubuntu" up
to `install.sh`, are done by `Install-TrialBox.cmd` on the media (`deploy/windows/box-install.ps1`). This sheet is
rewritten to the box form by NEW-WIN-9; until the installer has passed its rehearsal
(`P-0-windows-rehearsal.md`) the steps below remain the fallback.

On site, with hospital IT present. Offline: the USB disk of `OFFLINE-MEDIA.md`. Tick each line; keep the printed
output of both pre-flight checks with the install record.

**Before the visit**
- [ ] The hospital has chosen the workstation and its Windows version (Windows 11 Pro/Enterprise 22000+ or Server
      2022+), the tier (small: RTX 5090, medium: DGX Spark, large: RTX PRO 6000) and the data drive.
- [ ] The tier has a measured serving record on the disk (`measured/`); without it the install refuses the tier.
- [ ] Hospital IT has the network sheet (`docs/network-sheet.*.html`): the console port, the mail server, no other
      inbound or outbound line.

**On Windows**
- [ ] BIOS: virtualisation (VT-x / AMD-V) on. BitLocker on every volume with a TPM and PIN
      (`manage-bde -protectors -add C: -TPMAndPIN`, then delete the TPM-only protector); the recovery password with
      hospital IT (their sealed envelope or directory), never on the workstation.
- [ ] `powercfg /hibernate off` (also turns Fast Startup off). Remote Desktop off.
- [ ] Windows Update by policy: "Configure Automatic Updates" = 3 (download and notify), or a set install time
      agreed with hospital IT away from the nightly jobs. Restarts happen in the agreed window (RUNBOOK §24).
- [ ] Install the NVIDIA Windows driver from `windows/nvidia/`.
- [ ] Install WSL from `windows/wsl/`, import Ubuntu with `wsl --import`, copy `deploy\windows\wslconfig.example`
      to `%USERPROFILE%\.wslconfig` (memory, `swap=0`, `sparseVhd=true`). Without `sparseVhd` the disk file only
      grows: compact it monthly (`wsl --shutdown`, then `Optimize-VHD` or `diskpart compact vdisk`).
- [ ] As administrator: `powershell -ExecutionPolicy Bypass -File windows\register_keepalive.ps1 -User <account>`
      (WSL2 keeps running when nobody is signed in and comes back after a restart).
- [ ] As administrator: `powershell -ExecutionPolicy Bypass -File windows\preflight.ps1 -DataDrive D:
      -RecoveryKeyEscrow "<who keeps the recovery password>"`: no FAIL line (T-210a, D-421).

**In WSL2 Ubuntu**
- [ ] `/etc/wsl.conf`: `[boot] systemd=true`; restart WSL (`wsl --shutdown`).
- [ ] `sudo apt-get install ./linux/debs/*.deb` (Docker Engine, compose, nvidia-container-toolkit, nftables, cron).
- [ ] Copy the release to `/opt/trialbox`; `bash deploy/windows/preflight.sh /opt/trialbox`: every line PASS.
- [ ] `sudo deploy/install.sh linux/trialbox-<version>.tar --tier <small|medium|large> --answers site.yaml`.
- [ ] With hospital IT: `trialbox backup-keygen`, private key on their USB stick, sealed envelope (RUNBOOK §5).
- [ ] Set `TB_BACKUP_TARGETS` and `TB_AUDIT_ARCHIVE_DIR` in `deploy/.env` to the hospital share.

**Hand over**
- [ ] `sudo python3 -m tools.trialbox secrets rotate` with the owner present: new tokens and database passwords that
      Aimedics has never seen (RUNBOOK §5 "Secrets").
- [ ] Print `deploy/site/network-sheet.<lang>.html` (the site's own sheet) for hospital IT.
- [ ] From an elevated terminal: `sudo deploy/check_host.sh --wsl2 --escrow "<who keeps the recovery password>"`:
      no FAIL line. Again after every Windows Update.
- [ ] Run the go-live acceptance (RUNBOOK §6) and sign the install record.
