# D-408 Host baseline: one host system, a disk that opens only in the hospital, sealed keys, firewall, OS patches

- **Task:** T-634, host baseline (`docs/plan/28-master-plan-v6.md` §6.2, row T-634)
- **PR:** this branch (`agent/T-634-host-baseline`)
- **Date:** 2026-11-11
- **Status:** accepted; the host system is a default until the owner answers (TB-DR-09 Q1)
- **Closes:** OPS-043, OPS-024 (the design and the code; the rental-box run remains), OPS-052, OPS-015 (all but
  `--wsl2`, T-210a, and NTP as a FAIL, T-211); OPS-062 (the document half for SECURITY §1; the owner's answer remains)

## Context

Three documents named three host systems (OPS-062). The documented disk unlock bound LUKS to the TPM with no PIN, so
a stolen box booted to a running stack anywhere, and sealing the site keys was a manual, optional step (OPS-043).
Nothing set an input policy or SSH settings (OPS-052). Host patching had no design for an air-gapped box (OPS-024).
`check_host.sh` passed the disk check when any dm-crypt device existed (OPS-015).

## Decision

1. **Host system, default until the owner answers:** bare Ubuntu 24.04 LTS (or the DGX Spark's own Ubuntu-based
   system on that form). Windows with WSL2 only on a hospital's written demand (T-210a). This is the review's
   recommendation (OPS-062); the owner may change it, and only SECURITY §1, the host check's WARN line and this file
   name it.
2. **Disk unlock:** clevis `sss` t=2 of {one of the hospital's Tang servers, the TPM with PCR 7}
   (`deploy/hardening/disk-unlock.sh bind`); every TPM-only token wiped. A TPM PIN is the fallback for a site without
   Tang. `deploy/hardening/luks_policy.py` judges every automatic way into the volume; the host check FAILs one that
   needs neither the network nor a person.
3. **Sealed site keys at install:** `install.sh` runs `deploy/hardening/seal_keys.sh` right after `keys-init`, in
   VALIDATION and PRODUCTION always. Default back end `tpm`: the D-347 `file` KEK sealed with `systemd-creds
   --with-key=host+tpm2`, opened at boot by `trialbox-unseal.service` into `/run/trialbox/kek`; `shamir` and
   `passphrase` stay available. The host check FAILs a plain site key in VALIDATION and PRODUCTION.
4. **Input firewall and SSH:** `deploy/hardening/apply.sh` from the site's `deploy/site/hardening.conf`: table
   `inet trialbox_input`, input policy drop, 443 only from the clinic ranges (a prerouting chain, because Docker's DNAT
   bypasses the input hook), SSH off or from the IT ranges with keys only. Loaded at boot by `trialbox-input.service`.
5. **OS patches:** an ordinary signed bundle whose payloads are `other` under `ospatch/` (a dated flat apt repository
   and `ospatch.json`), applied by `tools/apply_update.sh ospatch`: signature first, then system, architecture and
   snapshot order (no going back; release_seq is not compared, an OS snapshot is not a TrialBox release), held
   packages kept, apt reads only the staged repository (`[trusted=yes]`: the trust is the bundle signature's), the
   reboot plan, and the canary (doctor and the orchestrator selftest; the site may set `CANARY_CMD`). No new payload
   kind and no change to the manifest schema.
6. **A stricter host check:** Docker's data root and the backup folder resolved to their device; the unlock policy;
   plain keys; the firewall; SSH; free space; both cron files; the time zone; pending reboots and failed OS patches;
   `--baseline` for these alone. VALIDATION and PRODUCTION FAIL what DEV and TEST WARN.

## Consequences

- A box off the hospital network does not come back alone after a power cut: it waits for Tang or the passphrase.
  That is the point; the runbook's restart page must say so (T-638 or the RUNBOOK owner).
- A site that keeps `KEK_BACKEND=shamir` needs two stewards after every restart.
- Not tested on a real box here: the disk unlock with a moved disk, a real apt snapshot and its canary. The rental-box
  run is the remaining acceptance step.
