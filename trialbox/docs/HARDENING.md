# TrialBox appliance hardening (SPEC §2, §10.1, §10.3)

This is the host checklist for an installed box. `deploy/check_host.sh [--gb10]` checks it and changes nothing.
Run the check after installation and after every update.

## 1. Disk: LUKS full-disk encryption, no swap

- Install the OS on **LUKS2** (the Ubuntu Server installer: "Use an entire disk" + "Encrypt the LVM group").
  `/var/lib/docker`, the compose volumes and `deploy/` are then encrypted at rest. All PHI lives there: lake,
  fhir-store, MinIO, pid map, audit.
- **Unlock with the TPM** so the box restarts unattended but the disk is useless elsewhere:

  ```sh
  systemd-cryptenroll --tpm2-device=auto --tpm2-pcrs=7 /dev/<luks-partition>   # bind to Secure Boot state
  # /etc/crypttab: <name> UUID=<uuid> none tpm2-device=auto
  update-initramfs -u
  ```

  Keep the LUKS recovery passphrase in the hospital's sealed-envelope procedure, not on the box.
- **Swap off** so PHI never pages to disk: `swapoff -a`, remove swap from `/etc/fstab`, mask `swap.target`.
  `check_host.sh` fails while swap is on.

## 2. Secrets: TPM-sealed keys, root-only files

| Secret | Where | Protection |
| --- | --- | --- |
| `deploy/.env` (mail, MinIO, DB passwords) | host | `chmod 600`, root-owned |
| `site_hmac.key` (pid pseudonymisation, D-09) | `tb-secrets` volume | 0600; TPM-sealed at rest (below) |
| `pid_map.key` (AES-GCM key of the pid map and identity table, D-10/D-66) | `tb-secrets` volume | 0600; TPM-sealed at rest |
| S/MIME key (optional attachment mode) | `tb-secrets` volume | 0600 |
| vendor update key | `deploy/keys/vendor_ed25519.pub` | public key only; the private key never leaves the vendor |

SPEC asks for the pid-map key in a TPM-sealed file. Store the keys encrypted with `systemd-creds` bound to the TPM,
and decrypt them into the secrets volume (tmpfs) when the stack starts:

```sh
systemd-creds encrypt --with-key=tpm2 --name=pid_map.key /root/pid_map.key /etc/trialbox/creds/pid_map.key.cred
shred -u /root/pid_map.key
# trialbox.service: ExecStartPre= systemd-creds decrypt /etc/trialbox/creds/pid_map.key.cred \
#     /var/lib/docker/volumes/trialbox_tb-secrets/_data/pid_map.key
```

Do the same for `site_hmac.key`. Losing the site key changes every pid, so back it up in sealed form with the LUKS
recovery material.

## 3. Network: default-deny egress

`deploy/network.sh apply` loads an nftables table that drops every packet from the TrialBox networks to anywhere
outside the box, except:

| From | To | When |
| --- | --- | --- |
| mail-gateway | `SMTP_HOST:SMTP_PORT`, `IMAP_HOST:IMAP_PORT` | always |
| criteria-compiler | host of `CLOUD_LLM_BASE_URL` | only when set (PHI guard enforced in code, §7.4) |
| criteria-compiler | clinicaltrials.gov:443 | `TB_CTGOV_MODE=live` (public registry, COHORT) |
| orchestrator | host of `NHI_TWPAS_BASE_URL` | only when set (SUBMIT) |
| any service | `EGRESS_EXTRA` entries | site additions, documented in the RUNBOOK |

In addition, `trialbox-net` is `internal: true`, so services that are not on `trialbox-egress` have no route out at
all. Container addresses change on restart, so re-apply the table from a systemd unit after `docker compose up`:

```ini
# /etc/systemd/system/trialbox-egress.service
[Unit]
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
ExecStart=/opt/trialbox/deploy/network.sh apply
# plus a .path unit on /run/docker.sock or a 5-minute timer
```

`sudo make test-egress` proves the rule set on a running stack. A fake outside host (a network namespace) is
reachable before the rules are applied. Afterwards only the allowlisted container→port pairs connect, and traffic
inside the box is unaffected.

## 4. Updates: offline, signed, never automatic

The vendor builds bundles with `tools/sign_bundle.py` (Ed25519). The operator runs
`tools/apply_update.sh bundle.tar`, which:
1. verifies the signature, the manifest schema and every payload's size and sha256 in a container with no network;
2. rejects tampered, unsigned, foreign-key, path-traversal and symlink bundles, changing nothing;
3. applies images (`docker load`), models, and approved rulesets (equivalence gate re-checked, tagged in the
   ruleset repository);
4. writes an `update.applied` audit event.

Run `--dry-run` first. Driver updates (GB10: 580.142 pinned) are outside the bundle channel and need a change
request.

## 5. Retention and audit

The daily `RETENTION` job applies these limits:
- attachments after 90 d;
- outputs and the ClinicalTrials.gov cache after 365 d;
- pools and feedback of rulesets retired more than 24 months ago.

Every deletion is audited with the object's sha256. The adapter keeps 3 nightly snapshots plus 36 month-end
snapshots.

The audit chain (`/data/audit`, 10 years) is append-only. Copy it nightly to the hospital share (`rsync -a`, no
`--delete`) and verify it with `tools/audit_verify.py`. Container logs rotate by size (json-file, 5 × 50 MB per
service). They contain no PHI (pids only), so the log retention (180 d) is met by size long before age.

## 6. GB10 notes

- NVIDIA driver **580.142** exactly. Run `apt-mark hold` on the driver packages. `check_host.sh --gb10` fails on
  any other version.
- vLLM image pinned by digest in `deploy/docker-compose.gb10.yml`. Unified memory is shared, so the vLLM memory
  fraction is 0.60 and HAPI gets an explicit heap.
- TrialBox images are multi-arch (`make images-multiarch`). The Python lock resolves to aarch64 wheels for every
  package (`--only-binary=:all:`).
