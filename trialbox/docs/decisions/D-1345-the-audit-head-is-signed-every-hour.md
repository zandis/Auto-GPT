# D-1345 The audit head is signed every hour, and an anchor folder the box's root can write over fails

- **Task:** 10G-2 (plan 10, track G; review 16, card 16-19), lane H · **Date:** 2026-11-19 · **Status:** accepted ·
  **Builds on:** D-355, D-562 (its default of 36 h is replaced here)

1. `trialbox audit-sign` (D-562, unchanged in what it checks and signs) runs every hour at :50 from
   `/etc/cron.d/trialbox-retention`; `logs daily` stays at 00:20 on its own line. `deploy/install.sh` writes both
   lines; `tools.trialbox.audit_heads.cron_lines` is the same text (a test holds them equal).
2. A box updated from a release that signed once a night is moved by the new tree's `pre-start` step
   "hourly audit head" (`tools/trialbox/prestart.py`): the one known nightly line becomes the two lines, the install
   folder and log kept; again is a no-op; a missing file or an unknown line is left alone and said. The floor
   (`MIN_INSTALLED_SEQ`) stays 0: no release has reached a box.
3. The key is the box's existing audit signing key (`audit_sign.key`, Ed25519, in the secrets volume, wrapped under
   the KEK). The only service that writes the audit volume (`audit-writer`) mounts neither the secrets volume nor the
   KEK; the services that mount them (orchestrator, adapter) mount the audit volume read-only. No new key.
4. After each run on a site box the host (root, from cron) asks the kernel whether it could write the newest head of
   each anchor folder (`access(2)`). If it could, the run fails: the head is still written, the problem is in the
   result file (`kind: open_to_root`) and in the event's `failed`. `doctor` FAILs on it in PRODUCTION and WARNs in
   VALIDATION, TEST and DEV (a result file without `kind`, from before, reads as a refusal, as it did). A folder
   passes only when the box's root is refused: the hospital's share with root squashed, a WORM share, or
   `chattr +i` on each head. RUNBOOK 01 step 3 says so at install.
5. `TB_AUDIT_HEAD_MAX_AGE_H` defaults to 2 (was 36): `doctor` (`audit_heads`) FAILs in VALIDATION and PRODUCTION
   (WARN elsewhere) when the newest signed head of any folder is older than 2 h, or dated more than 2 h ahead of the
   box's clock, and says since when and what to run. No head yet is a WARN while the audit key is younger than the
   limit (a box installed within the hour; the installer also signs once).
6. What it stops, and what not: `docs/handover/audit-head-signed-hourly-2026-11-19.md`. Tests:
   `tests/unit/test_audit_head_signed_hourly.py`, `tests/unit/test_audit_heads_nightly.py`.
