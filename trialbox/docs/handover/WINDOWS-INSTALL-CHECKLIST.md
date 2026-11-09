# Windows install checklist for Aimedics engineers (D-125, D-138)

On site, with hospital IT present. Offline: the USB disk of `OFFLINE-MEDIA.md`. Tick each line; keep the printed
output of both pre-flight checks with the install record.

**Before the visit**
- [ ] The hospital has chosen the workstation and its Windows version (Windows 11 Pro/Enterprise 22000+ or Server
      2022+), the tier (small: RTX 5090, medium: DGX Spark, large: RTX PRO 6000) and the data drive.
- [ ] The tier has a measured serving record on the disk (`measured/`); without it the install refuses the tier.
- [ ] Hospital IT has the network sheet (`docs/network-sheet.*.html`): the console port, the mail server, no other
      inbound or outbound line.

**On Windows**
- [ ] BIOS: virtualisation (VT-x / AMD-V) on. BitLocker on every volume, recovery key with hospital IT.
- [ ] Install the NVIDIA Windows driver from `windows/nvidia/`.
- [ ] Install WSL from `windows/wsl/`, import Ubuntu with `wsl --import`, copy `.wslconfig` (memory, `swap=0`).
- [ ] `powershell -ExecutionPolicy Bypass -File windows\preflight.ps1 -DataDrive D:`: every line PASS.

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
- [ ] Run the go-live acceptance (RUNBOOK §6) and sign the install record.
