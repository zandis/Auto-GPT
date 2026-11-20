# D-1345 The audit head is signed every hour, and an anchor folder the box's root can write over fails

- **Task:** 10G-2 (plan 10, track G; review 16, card 16-19), lane H · **Date:** 2026-11-19 · **Status:** accepted ·
  **Builds on:** D-355, D-562 (its default of 36 h is replaced here)

1. `trialbox audit-sign` (D-562, unchanged in what it checks and signs) runs every hour at :50 from
   `/etc/cron.d/trialbox-retention`; `logs daily` stays at 00:20 on its own line. `deploy/install.sh` writes both
   lines; `tools.trialbox.audit_heads.cron_lines` is the same text (a test holds them equal).
2. A box updated from a release that signed once a night is moved by the new tree's `pre-start` step
   "hourly audit head" (`tools/trialbox/prestart.py`), in the folder `TB_CRON_DIR` names (else `/etc/cron.d`, as
   install.sh): the one known nightly line becomes the two lines, every other line byte for byte; again is a no-op;
   a missing, unreadable or unknown file is left alone and said. The floor (`MIN_INSTALLED_SEQ`) stays 0.
3. The key is the box's existing audit signing key (`audit_sign.key`, Ed25519, wrapped under the KEK). Its private
   files are root's, mode 0600 (`seal_keys.sh`, `init_key`, the pre-start step "audit key root only"); `doctor`
   (`audit_key_root`) FAILs anything else. adapter and orchestrator (uid 10001) keep the secrets volume and the KEK
   for their own keys and are refused the file; the KEK is shared, so that file's permissions are the only barrier
   (H10G2-04). No new key.
4. The signer, as root in its container, judges each anchor folder root-proof (`audit_heads.root_proof`): a folder
   on the box's own disk or of a type it cannot tell never is; on a share, overwriting the head just written (by
   name), and renaming, deleting or overwriting a test file in `heads/`, must each be refused. In PRODUCTION a folder
   that cannot be root-proof gets no head; elsewhere it gets one. Either way the run exits 1, the result file says
   `kind: open_to_root`, and `doctor` FAILs it in PRODUCTION and WARNs in VALIDATION, TEST and DEV. A signer answer
   without the judgement (an older image) fails closed. Nothing is followed through a link.
5. `doctor` (`audit_heads`) fails closed: no result file of the hourly run (a WARN only while the key is younger than
   the limit), an unreadable result, unreadable public keys, a head whose signature it cannot check (it counts only
   verified heads), or `TB_AUDIT_HEAD_MAX_AGE_H` not a positive finite number. `TB_AUDIT_HEAD_MAX_AGE_H` defaults to
   2 (was 36); a head older than that, or dated more than 5 minutes ahead of the box's clock, FAILs, with since when
   and what to run. `deploy/check_host.sh` mounts the result file's folder into the doctor's image.
6. What it stops, and what not: `docs/handover/audit-head-signed-hourly-2026-11-19.md`. Tests:
   `tests/unit/test_audit_head_review_10g2.py`, `tests/unit/test_audit_head_signed_hourly.py`,
   `tests/unit/test_audit_heads_nightly.py`.
