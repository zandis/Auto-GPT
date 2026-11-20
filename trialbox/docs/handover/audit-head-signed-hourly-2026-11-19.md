# The audit head signed every hour (card 10G-2, 2026-11-19)

**Reader:** the people who build TrialBox, and the two reviewers of this card

Review 16 (card 16-19) asked for three things: the head of the audit chain signed hourly, an anchor folder the box's
root can write refused, and `doctor` failing a head older than 2 h. Decision **D-1345**.

## What was there before this card

- `trialbox audit-sign` (D-562, `tools/trialbox/audit_heads.py`): checks the chain against every earlier signed head
  under the box's own public keys, signs where it stands, writes the head write-once to every folder of
  `TB_AUDIT_ANCHOR_TARGETS`, and records `audit.head_signed`. Run once a night at 00:20 from
  `/etc/cron.d/trialbox-retention`, after `logs daily`, and once by the installer.
- `doctor` check `audit_heads`: FAIL when no folder is set, the key is missing, the last run failed, a head is not
  signed by this box's key, or the newest head is older than `TB_AUDIT_HEAD_MAX_AGE_H` (36 h).
- Nothing checked whether the box's own root could overwrite a head in an anchor folder.

## What this card adds

| Part | Where |
| --- | --- |
| `audit-sign` every hour at :50; `logs daily` stays at 00:20 on its own line | `deploy/install.sh`; `audit_heads.cron_lines` |
| an updated box's nightly cron line moved to the hourly one, idempotently | `tools/trialbox/prestart.py` step "hourly audit head" |
| a run fails (exit 1) when the host's root could write the newest head of a folder; `doctor` FAILs it in PRODUCTION, WARNs in VALIDATION, TEST and DEV | `audit_heads.overwritable`, `sign_on_box`, `kind` |
| `TB_AUDIT_HEAD_MAX_AGE_H` 36 -> 2; the FAIL line says since when and what to run | `libs/tb_common/config.py`, `tools/trialbox/doctor.py` |
| a head dated more than 2 h ahead of the clock FAILs and names both times | `doctor.check_audit_heads` |

A 3-hour-old head FAILs; 1 minute, 1 h and 2 h pass. A fresh box with no head yet is a WARN while the audit key is
younger than 2 h (the installer also signs once), then a FAIL. Time is a parameter in every test.

## Which key signs, and who can use it

The box's existing audit signing key, `audit_sign.key` (Ed25519) in the secrets volume, wrapped under the KEK. No new
key. It is used by root on the host (the cron job runs the signer in the box's image with the secrets volume and the
KEK folder read-only). In the compose file the only service that writes the audit volume, `audit-writer`, mounts
neither the secrets volume nor the KEK; the two services that do (orchestrator, adapter) mount the audit volume
read-only. A test reads the compose file and holds this.

## Threat note

**What this stops.** Someone holding the audit writer's account (the `audit-writer` container, or the database role
`tb_audit_writer`) can change the chain's files, but cannot sign a head for them; the next hourly run checks the
chain against every signed head and refuses it, and `doctor` FAILs. Someone holding the box's root can rewrite the
chain and sign a new head with the box's key, but, when the anchor folder refuses the box's root, cannot change or
replace a head already written: a rewrite of anything before the newest head shows in `tools/audit_verify.py --heads`
and in the next run.

**What it does not stop.** The box's root can change events written since the last signed head (at most about an
hour, two with one missed run) and sign over them; the key lives on the box, as review 16 says. It does not stop the
box's root from deleting heads where the share lets it (H10G2-01), or anything on an anchor folder on the box's own
disk without `chattr +i` (the run then fails, by design; `doctor` WARNs outside PRODUCTION, so a VALIDATION box on a
local folder is told, not stopped). It does not hide the chain from anyone who can read the
audit volume.

## Findings

[findings.json](audit-head-signed-hourly-2026-11-19/findings.json): H10G2-01 (deletion of a head is not checked),
H10G2-02 (the refusal not yet run on a real share), H10G2-03 (doctor reads the last run's result, it cannot test the
folder itself).

## Tests

`tests/unit/test_audit_head_signed_hourly.py` (new); `tests/unit/test_audit_heads_nightly.py` (four tests: their
times moved inside or outside the new 2 h limit, the same verdicts, and the declared default "36" -> "2");
`tests/unit/test_update_minseq.py` (its pre-start pin list gains "hourly audit head"; the floor stays 0). The stand-in for a refused write runs as a non-root account; as root it is skipped, since root
writes a read-only file on a local disk.
