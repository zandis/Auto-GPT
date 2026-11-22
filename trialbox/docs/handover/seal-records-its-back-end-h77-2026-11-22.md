# H-77: the seal step records the KEK back end it used

**Reader:** the people who build TrialBox: the lane H lead, the integrator and the reviewer of high-risk cards.
Findings for builders, so in one language.

- **Card:** H-77, install-test finding F-22. High-risk (keys). The integrator's ruling (2026-11-22): `seal_keys.sh`
  writes the back end it used after its last step succeeds, `install.sh` only copies it.
- **Date:** 2026-11-22
- **Findings:** [`seal-records-its-back-end-h77-2026-11-22/findings.json`](seal-records-its-back-end-h77-2026-11-22/findings.json)
  (H77-01, H77-02)
- **Tests:** `tests/unit/test_seal_records_its_back_end_h77.py` (40). The invariant:
  `test_seal_records_its_back_end_h77.py::test_install_copies_the_back_end_seal_keys_recorded`.

## PR body draft

After an install nothing on the box said which KEK back end sealed the site keys. `seal_keys.sh` chooses it (tpm,
then hardening.conf's `KEK_BACKEND`, then `TB_KEK_BACKEND`), said it only in a log line, and under tpm the key tool's
own `kek.json` says `file`. The host check (`tools/trialbox/preflight.py`, `tpm_tang`) reads `TB_KEK_BACKEND` from
`deploy/.env`, which the installer never wrote, so it fell back to hardening.conf or tpm. An earlier patch made
`install.sh` work the back end out a second time; it was rejected, since the two could disagree.

### What changes for a box

- `seal_keys.sh --record FILE` writes FILE: one line, the back end's name (`tpm`, `shamir` or `passphrase`), mode
  0600, written to `FILE.tmp` and renamed. It is written only after the last step (`tools.keys check`, the audit key,
  the owner change) has passed. Without `--record` nothing new is written (the callers of before are unchanged).
- `install.sh` passes `--record deploy/site/kek-backend`: the site's folder (git-ignored), which the settings
  wizard's rewrite of `deploy/.env` on a re-run leaves alone. The secrets folder was the first choice; an existing
  test (`test_host_baseline.py::test_seal_keys_wraps_the_plain_keys_under_a_tpm_sealed_kek`) asserts its exact
  listing, and changing that assertion needs the integrator's ruling.
- A dry run and a seal that fails at any step (a TPM that cannot seal, a wrap or a check that fails) write no record
  and leave an earlier one as it was.
- A box with a KEK already (`kek.json` there: the re-run only wraps) records the back end `kek.json` names, once the
  wrap has passed (`file` is tpm's KEK, so it records `tpm`). The record so follows a `tools.keys rotate-kek` and a
  seal whose closing check failed once (the review of #1336, its two Mediums; the integrator's ruling).
- `install.sh`, right after the seal, copies that word to `deploy/.env` as `TB_KEK_BACKEND` (already declared, D-836)
  and says it. It reads nothing else for it. Without a record, or with one that is not a back end's name, it says so
  and leaves `deploy/.env` as it was. Where it does not seal (poc without a usable TPM) it writes nothing.
- `box-install.sh`'s deferred seal (the owner's passphrase at the apply step) passes the same `--record` and copies
  the word with the same block, byte for byte: the two scripts source no common file, and
  `test_the_two_installers_copy_the_record_with_one_block` keeps the blocks identical. A failed deferred seal records
  nothing.
- The copy into `deploy/.env` stops on a missing or linked file, does not join a last line that lacks its newline,
  and removes every earlier `TB_KEK_BACKEND` line (an `export` one too), so two runs leave one line (the review's
  Lows). `box-install.sh` unsets the owner's passphrase right after the seal.
- No refusal was removed or softened. One assertion changed, by the integrator's ruling on the review:
  `test_a_box_with_a_kek_already_keeps_its_record_as_it_was` asserted no record on the re-run path; it is now
  `test_a_box_with_a_kek_already_records_the_back_end_kek_json_names`.

### The invariant

The back end `deploy/.env` names is the one the sealing step ran. The test plants hardening.conf saying one back end
and the environment another (tpm/passphrase both ways, and shamir from the conf alone), runs the installer's seal block
as it stands with the real `seal_keys.sh`, and checks that the installer's line, `deploy/.env` and the record are the
same word, and that the keys were sealed that way (the credential exists only for tpm; `kek.json` says that back end).
`test_the_box_deferred_seal_copies_the_back_end_seal_keys_recorded` does the same through `box-install.sh`'s
apply-step seal (hardening.conf passphrase, the environment tpm or nothing).

### Mutation pass

19 mutants of the diff, 19 caught: the record written before the case, before `tools.keys check`, right after the TPM
seal, in a tpm and a passphrase dry run, on a re-run, on exit (failure too); the conf's word when the environment
overrides it; mode 0644; written in place (no rename); the passphrase in it; `install.sh` taking `TB_KEK_BACKEND`,
reading hardening.conf, defaulting to tpm without a record, taking any word, writing one on the poc path, preferring
the environment over the record, `install.sh` not passing `--record`, `seal_keys.sh` ignoring it. Then 8 for the box block, 8 caught: no `--record`,
the conf's word, the environment's word, the copy before the seal, a default without a record, a copy after a failed
seal, a drifted block in either script.

Review round: 10 more, 10 caught (the copy mutants planted in both scripts at once): no record on the re-run path, the
environment's word there, no `file` to `tpm`, a record before the wrap and in a dry run, no newline guard, no
missing-or-link check, the old `sed` pattern, no `sed`, `>` for `>>`, a link followed.

### Not verified

- Not run on a real box or a real TPM: the TPM is the stand-in `systemd-creds` of the existing seal tests.
- That `deploy/site/` is kept by an update and a re-install (it holds hardening.conf; not checked by this card).

## Findings

- **H77-01** (fixed): F-22, settled as above.
- **H77-02** (fixed, 710489fad127dfee822969b5b03b16db25b0916b): the box's deferred seal (`TB_BOX_DEFER_SEAL=1`, `deploy/box-install.sh` apply step,
  T-729) ran `seal_keys.sh` without `--record`, so nothing recorded the back end there. It now passes the same
  `--record deploy/site/kek-backend` and copies the word with the same block as `install.sh` (the integrator's ruling,
  2026-11-22 11:43 UTC: the install is lane H's).
