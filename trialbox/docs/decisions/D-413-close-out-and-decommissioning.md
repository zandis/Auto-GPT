# D-413 Close-out and decommissioning: freeze, archive, crypto-erase, purge, certificate

- **Task:** T-628, close-out and decommissioning procedure per site (`docs/plan/28-master-plan-v6.md` §6.2, row T-628)
- **PR:** this branch (`agent/T-628-closeout`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** LIFE-028 (the written procedure part), OPS-075
- **Not here:** `trialbox study close` with a dated, indexed bundle per study and account expiry in the software
  (WS-18.1, LIFE-028 "later"); a switch that stops one study's runs; the drill itself (T-213b)

## Context

The review found no close-out and no decommissioning: no final freeze of the logs, no archive with hashes, no wipe
of the box with a certificate (LIFE-028), and nothing for the stores off the box: the 14 backups, the pgBackRest
repository on the hospital share, the audit archive, USB disks, the model weights and, on the shared host, the
volumes on hospital storage (OPS-075). The IT pack (A.5) promises an NIST 800-88 purge with a certificate.

## Decision

1. **RUNBOOK §20 (its reserved number) has eight numbered steps**: announce, freeze, archive, verify, handover,
   crypto-erase, purge, certificate. A study that closes while others go on runs steps 1 to 5 only.
2. **The freeze is the audit chain's own tools**: stop the services, `audit_verify` whole, a signed head written off
   the box (`--sign-head`), and `--heads` passing. The head is written on the close-out record.
3. **The archive reuses what exists**: the encrypted backup (its stream hashes), the audit chain with its anchors,
   the audit archive with its `MANIFEST.sha256`, the export ledger and the plan, in one folder with `SHA256SUMS`. It
   is verified on the hospital's store before anything is erased, and handed to the trial office with the backup
   private key that opens it.
4. **Keys first.** Crypto-erase (the KEK, disk keys, every other copy of the backup private key) comes before the
   purge, so a copy nobody listed is unreadable too. The audit archive and anchor folders are kept, not purged.
5. **Purge by medium, NIST SP 800-88 Rev. 1** (Clear, Purge, Destroy per its §2.5 and Appendix A); shared stores that
   hold only encrypted backups are deleted after the crypto-erase and certified as logical clear.
6. **`trialbox decommission-plan`** (stdlib, dry run) lists the steps and every store from `deploy/.env` and the
   compose file, each **keep**, **purge** or **ask**. It changes nothing.
7. **Site documents**: `close-out-record.md` (TB-SITE-11) and `purge-certificate.md` (TB-SITE-12, the Appendix G
   fields in English, 日本語 and 繁體中文). Filled copies name people and stay with the hospital. Both tabletop
   records gain scenario 12.

## Consequences

- The card's acceptance "signed by each trial office before G6" is dropped (D-311): no signature gates anything.
- `tests/unit/test_decommission.py` holds the page to the step list, the certificate to its 24 fields in three
  languages, and the plan to the settings.
