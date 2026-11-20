# 1. The host

*T-634, D-408. The host baseline: one host system, a disk that opens only in the hospital, sealed site keys, an
input firewall, SSH, offline OS patches, and `deploy/check_host.sh` that checks all of it. The scripts are in
`deploy/hardening/`; the site's choices are in `deploy/site/hardening.conf` (from `hardening.example.conf`).*

- **The host system.** *Default until the owner answers (TB-DR-09 Q1):* a bare **Ubuntu 24.04 LTS** on the box, or
  the DGX Spark's own Ubuntu-based system on that form. Windows 11 with WSL2 and BitLocker only when a hospital asks
  for it in writing (T-210a, `check_host --wsl2`). CGMH runs TrialBox in containers on its own server (§17 of the
  RUNBOOK): the hospital owns that host and this page applies to it only as advice. The host check WARNs on any other
  system.
- **Disk.** Install Ubuntu on **LUKS2** ("Use an entire disk" and "Encrypt the LVM group"). Every store of PHI is on
  it: lake, FHIR store, objects, pid map, audit. The host check resolves Docker's data root and the backup folder to
  their block device and FAILs when that device is not dm-crypt (not "any crypt device on the box").
- **The disk opens only in the hospital (OPS-043).** No TPM-only unlock: a box that unlocks with its TPM alone boots
  to a running stack wherever it is carried. Hospital IT binds the volume once, at OS install, with
  `deploy/hardening/disk-unlock.sh bind --device /dev/<luks-partition>`: one clevis binding that needs **both** this
  board's TPM (PCR 7, the Secure Boot state) **and** one of the hospital's Tang servers (`TANG_URLS`), then every
  TPM-only token is wiped and the initramfs rebuilt. A moved disk, or the whole box off the hospital network, stops at
  the passphrase prompt. The LUKS recovery passphrase goes in the hospital's sealed-envelope procedure, never on the
  box. A site without a Tang server uses a TPM PIN instead (`systemd-cryptenroll --tpm2-with-pin=yes`): the box then
  needs a person at every restart. The host check judges every way into the volume
  (`deploy/hardening/luks_policy.py`): FAIL for TPM2 without a PIN, a clevis `tpm2` alone, or an `sss` whose threshold
  the TPM reaches without Tang; PASS for Tang or a PIN; WARN when nothing opens it automatically.
- **Containers (10G-1, D-1323).** The 15 services of `deploy/docker-compose.yml` drop every capability
  (`cap_drop: [ALL]`), cannot gain a privilege (`no-new-privileges`), run on a read-only root filesystem with a
  `/tmp` tmpfs and as a fixed numeric non-root user (`10001:10001` the TrialBox images, `999:999` the database,
  `65532:65532` the FHIR store); no capability is added back. Written exceptions: the adapter and the orchestrator
  keep a writable root (the HL7 validator writes its package cache), and the vLLM server runs as root with a writable
  root (its compile caches) until a GPU box proves otherwise. The services the overlays add (H-58, D-1337) take the
  same controls, each as its image's own user, with written exceptions: the second vLLM server as the first; the
  rtx5090 swap helpers' user; Caddy's user and capabilities (root on 443, the hospital's key file); Authelia's user,
  capabilities and writable root (its entrypoint changes owner and user at start); the test Mailpit's writable root.
  `tests/unit/test_container_hardening.py` checks every service of every stack.
- **Swap off** so PHI never pages to disk (`swapoff -a`, remove it from `/etc/fstab`, mask `swap.target`). The host
  check fails while swap is on.
- **Sealed site keys at install.** `install.sh` seals `site_hmac.key` and `pid_map.key` (and every key of D-347) under
  a KEK right after it makes them and before any service starts (`deploy/hardening/seal_keys.sh`), in VALIDATION and
  PRODUCTION always. `KEK_BACKEND=tpm` (the default): a random KEK sealed with `systemd-creds encrypt
  --with-key=host+tpm2` to `/etc/credstore.encrypted/trialbox-kek`; `trialbox-unseal.service` opens it at boot and
  writes `/run/trialbox/kek` (tmpfs) for the services. The host key it is bound to lives on the LUKS volume, so a
  moved box has neither. `shamir` (stewards' shares on removable media) and `passphrase` are the other back ends
  (§4). The host check FAILs a plain `site_hmac.key` or `pid_map.key` in VALIDATION and PRODUCTION (WARN in DEV and
  TEST).
- **Input firewall (OPS-052).** `deploy/hardening/apply.sh` (run by `install.sh` when the site file exists) loads the
  nftables table `inet trialbox_input` and installs `trialbox-input.service` to load it at every boot: input policy
  drop; loopback, replies, the ICMP that IP needs, DHCP replies and the Docker bridges in; **443 only from
  `CLINIC_RANGES`**. Docker publishes 443 through DNAT, past the input hook, so a prerouting chain drops 443 to this
  host from any other source before Docker sees it. Forwarded container traffic stays the egress table's (§2).
  `apply.sh render` prints the ruleset and changes nothing.
- **SSH.** `SSH=off` (the default) stops and disables the service. `SSH=it`: port 22 from `IT_RANGES` only and
  `sshd_config.d/50-trialbox.conf` (keys only, no root login, no forwarding, three tries), checked with `sshd -t`.
  The host check FAILs password or root login while SSH runs.
  **Over SSH, `SSH=off` would lock the session out**: `apply.sh` refuses it from an SSH session and changes nothing,
  and `install.sh` asks the same rule (`apply.sh check`) before it loads anything (H-70): run it from the box's
  console, set `SSH=it` with your address in `IT_RANGES`, or add `--ssh-off-over-ssh` to either to go ahead.
- **OS patches (OPS-024).** Who and how fast is RUNBOOK §24. Offline, Aimedics ships a dated apt snapshot as a signed
  bundle (`deploy/hardening/ospatch.py make`, then `tools/sign_bundle.py`); hospital IT applies it in the window with
  `tools/apply_update.sh ospatch <bundle>`: the signature and every package are checked first, the snapshot must be
  for this system and architecture and newer than the last one, held packages (the NVIDIA driver) stay, apt reads the
  staged repository only. A kernel or `/var/run/reboot-required` means a reboot, then `tools/apply_update.sh
  ospatch-check` (doctor and the canary); otherwise the canary runs at once. A failing canary is exit 1, a P1 and a
  roll-back with hospital IT. The host check WARNs on a pending reboot and FAILs on a failed canary.
- **The host check.** `deploy/check_host.sh` (`--baseline` for the items above only) also checks free space under
  Docker's data root (WARN below 20%, FAIL below 10%), both cron files of the install, the host time zone and the TPM.
  Run it after install, after every update and after every OS patch.
- **GB10:** driver 580.142 exactly, held; the vLLM image pinned by digest.
- **Windows (T-210a, D-421):** the box runs in WSL2 only on a hospital's written demand. BitLocker takes the place
  of LUKS: on the system drive, the drive of the distribution's `ext4.vhdx` and every page-file drive, with a TPM and
  PIN (a TPM-only protector FAILs, as for LUKS) and a recovery password kept by hospital IT. Hibernation and Fast
  Startup off, `.wslconfig` with `swap=0` and `sparseVhd=true` (`deploy/windows/wslconfig.example`), Remote Desktop
  off, Windows Update installs and restarts only when hospital IT starts them, and a start-at-boot task that keeps
  WSL2 running whether or not anyone is signed in (`deploy/windows/register_keepalive.ps1`). `preflight.ps1` checks
  all of it before the install and `check_host --wsl2` (on by itself on a WSL2 kernel) after it, with one judge,
  `deploy/windows/wsl2_policy.py`. Key custody on Windows (DPAPI or the Windows TPM) is T-210b.
