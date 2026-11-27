# HYG2: the stick's public key verifies what the stick carries, or the release build is refused

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** hygiene item 2 of the open-tool audit (integrator, comment 7211450855 on #1504): a release-build test
  that the public key shipped beside the bundle verifies the manifest, the bootstrap `.sig` and the `.sha256.sig`;
  refuse to build otherwise. The integrator re-signs at the R1+1 build; no key material is in the repository
- **Date:** 2026-11-27
- **Base:** int/r1plus1 3390bf74
- **Findings:** [`bundle-key-check-hyg2-2026-11-27/findings.json`](bundle-key-check-hyg2-2026-11-27/findings.json)
  (HYG2-01 to HYG2-03)

## Files outside the card

Under the lead's go, bodies only:

- `tools/make_bundle.sh`: the optional `--pub FILE` (in its usage); the stick's files written to a pending folder
  beside `--out`; the `.sha256` signed to `.sha256.sig` with the same key (`sign_bundle.py sign-file`, unchanged);
  the key check; the files moved into place only after it passes; the hand-over line names the `.sha256.sig`
- `tools/rehearse_box/rehearse.sh`: the rehearsal moves the `.sha256.sig` to the media with the other stick files

The card's own: `tools/bundle_keycheck.py`, `tests/unit/test_bundle_keycheck_hyg2.py`, this page and its findings.

## What changed

Before, nothing wrote a `.sha256.sig`, and `make_bundle.sh` derived `vendor_ed25519.pub` from `--key` itself, so
nothing checked that the key on the stick is the one the signatures need. Now:

- `--pub FILE` names the vendor public key the boxes trust (kept outside the repository, like `--key`); it is the
  key put on the stick. Without it the key is derived from `--key`, as before.
- `tools/bundle_keycheck.py` checks, with the stick's key, `manifest.json.sig` inside the bundle, the bootstrap's
  `.sig` and the `.sha256.sig`, and that the `.sha256` lines match the bundle, the bootstrap and its `.sig`.
- The bundle, its `.sha256` and `.sha256.sig`, the bootstrap and its `.sig`, `install` and the public key are
  written to `.make_bundle-pending.*` beside `--out` and renamed into place only after the check passes. A refused
  build exits 1 and the pending folder is removed: no half set is left for the stick.

## What ran

- The test on the base with the test and the checker added but `make_bundle.sh` as it was: 4 failed (the four runs of
  `make_bundle.sh`: no `.sha256.sig`, and `--pub` unknown), 5 passed (the checker's own cases).
- At the head: 9 passed. Every key is a throwaway pair made in the test's tmp folder; none is committed. A
  mismatched `--pub` refuses the build and leaves none of the stick's files; a tampered `.sha256` is refused.
- The checks of CLAUDE.md and the policy set: see the pull request.

## Not verified

- The launcher (`deploy/launcher.sh`) and the bootstrap (`deploy/bootstrap.sh`) do not check the `.sha256.sig` yet,
  and RUNBOOK section 1 does not name it: a finding for a later card (HYG2-02).
- No real release was built: the runs use the stand-in `docker` of `test_release_bundle.py`.
