# H-77: the seal step records the KEK back end it used

**Reader:** the people who build TrialBox: the lane H lead, the integrator and the reviewer of high-risk cards.
Findings for builders, so in one language.

- **Card:** H-77, install-test finding F-22. High-risk (keys). The integrator's ruling (2026-11-22): `seal_keys.sh`
  writes the back end it used after its last step succeeds, `install.sh` only copies it.
- **Date:** 2026-11-22
- **Findings:** [`seal-records-its-back-end-h77-2026-11-22/findings.json`](seal-records-its-back-end-h77-2026-11-22/findings.json)
  (H77-01, H77-02)
- **Tests:** `tests/unit/test_seal_records_its_back_end_h77.py` (27). The invariant:
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
- A dry run, a seal that fails at any step (a TPM that cannot seal, a wrap or a check that fails) and a box with a KEK
  already (`kek.json` there: the re-run only wraps) write no record and leave an earlier one as it was. On a re-run
  the script cannot tell an existing seal's back end (tpm's `kek.json` says `file`), so it records none.
- `install.sh`, right after the seal, copies that word to `deploy/.env` as `TB_KEK_BACKEND` (already declared, D-836)
  and says it. It reads nothing else for it. Without a record, or with one that is not a back end's name, it says so
  and leaves `deploy/.env` as it was. Where it does not seal (poc without a usable TPM, the box's deferred seal) it
  writes nothing.
- No refusal was removed or softened; no existing test changed.

### The invariant

The back end `deploy/.env` names is the one the sealing step ran. The test plants hardening.conf saying one back end
and the environment another (tpm/passphrase both ways, and shamir from the conf alone), runs the installer's seal block
as it stands with the real `seal_keys.sh`, and checks that the installer's line, `deploy/.env` and the record are the
same word, and that the keys were sealed that way (the credential exists only for tpm; `kek.json` says that back end).

### Mutation pass

19 mutants of the diff, 19 caught: the record written before the case, before `tools.keys check`, right after the TPM
seal, in a tpm and a passphrase dry run, on a re-run, on exit (failure too); the conf's word when the environment
overrides it; mode 0644; written in place (no rename); the passphrase in it; `install.sh` taking `TB_KEK_BACKEND`,
reading hardening.conf, defaulting to tpm without a record, taking any word, writing one on the poc path, preferring
the environment over the record, `install.sh` not passing `--record`, `seal_keys.sh` ignoring it.

### Not verified

- Not run on a real box or a real TPM: the TPM is the stand-in `systemd-creds` of the existing seal tests.
- That `deploy/site/` is kept by an update and a re-install (it holds hardening.conf; not checked by this card).

## Findings

- **H77-01** (fixed): F-22, settled as above.
- **H77-02** (open): the box's deferred seal (`TB_BOX_DEFER_SEAL=1`, `deploy/box-install.sh` apply step, T-729) runs
  `seal_keys.sh` without `--record`, so nothing records the back end there and the host check on such a box still
  reads hardening.conf or tpm. `box-install.sh` is outside this card.
