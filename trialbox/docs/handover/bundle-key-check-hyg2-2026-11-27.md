# HYG2: the stick's public key verifies what the stick carries, or the release build is refused

**Reader:** the people who build TrialBox: the lane H lead and the integrator. Findings for builders, so in one
language.

- **Card:** hygiene item 2 of the open-tool audit (integrator, comment 7211450855 on #1504): a release-build test
  that the public key shipped beside the bundle verifies the manifest, the bootstrap `.sig` and the `.sha256.sig`;
  refuse to build otherwise. The integrator re-signs at the R1+1 build; no key material is in the repository
- **Date:** 2026-11-27
- **Base:** int/r1plus1 3390bf74
- **Findings:** [`bundle-key-check-hyg2-2026-11-27/findings.json`](bundle-key-check-hyg2-2026-11-27/findings.json)
  (HYG2-01 to HYG2-03; the review round of the pull request added R1 to R6 and F1, answered below)

## Files outside the card

Under the lead's go and the integrator's approval (comments 7215849144 and 7215869583 on #1504), bodies only:

- `tools/make_bundle.sh`: `--pub FILE` (required outside a `--rehearsal`); the release written to a pending folder
  beside `--out`'s folder and published as one directory rename; `--out`'s folder absent or empty;
  `--model-pack-out` beside `--out`; the `.sha256` signed to `.sha256.sig` with the same key (`sign_bundle.py
  sign-file`, unchanged); the key check; the hand-over line names the `.sha256.sig`
- `tools/rehearse_box/rehearse.sh`: the rehearsal moves the `.sha256.sig` to the media with the other stick files, and
  compares the key it was handed with the vendor's key instead of overwriting it
- the callers, to pass `--pub` or a fresh folder: `deploy/gcp/box-install-run.sh`,
  `tests/rehearsal/box-run/rehearse-box-run.sh` (its stand-in takes `--pub`), `deploy/gcp/demo-vm-update.sh`,
  `tools/runbook_install.py`, `tools/p0_media.sh`, the `Makefile` comment, and one clause at the end of step 6 of
  `docs/runbook/01-install-a-new-site.md`

The card's own: `tools/bundle_keycheck.py`, `tests/unit/test_bundle_keycheck_hyg2.py`, this page and its findings.
The shared test helper (`tests/unit/test_release_bundle.py`, `_make`) builds into the fresh folder `release/` and passes
`--pub`; the 12 path references that name its output follow it (same claims, new folder).

## What changed

Before, nothing wrote a `.sha256.sig`, and `make_bundle.sh` derived `vendor_ed25519.pub` from `--key` itself, so
nothing checked that the key on the stick is the one the signatures need. Now:

- `--pub FILE` names the vendor public key the boxes trust (kept outside the repository, like `--key`); it is
  required outside a `--rehearsal` (exit 2, `--pub is required outside a --rehearsal`), because a key derived from
  `--key` verifies its own signatures whatever key was used. Only the parsed public key is written to the stick
  (`openssl pkey -pubin -pubout`): anything after the key in the file, a private key included, does not ship.
- `tools/bundle_keycheck.py` checks, with the stick's key, `manifest.json.sig` inside the bundle, the bootstrap's
  `.sig` and the `.sha256.sig`. The sidecar is read once, and the bytes verified are the bytes parsed. It must hold
  exactly one well-formed line for each of the bundle, the bootstrap and its `.sig`, no other line, and each digest is
  of the file at the path given. A sidecar that is not text, or a key of an unsupported kind, is a line and exit 1.
- The release is written to `.make_bundle-pending.*` beside `--out`'s folder (the model pack and its `.sha256` too,
  which must sit beside `--out`) and published by one `mv -T` of the whole folder onto `--out`'s folder, which must be
  absent or empty (exit 2, `--out's folder ... must be absent or empty`). An interrupted build publishes nothing, a
  second builder that got there first makes the rename fail, and an earlier release is never overwritten. A refused
  key check exits 1 and nothing, the model pack included, is written to the destination.
- Refusals, each with a test: `--pub` missing, `--pub` not a public key, `--out`'s folder not empty (with a model
  pack in it too), `--model-pack-out` not beside `--out`, a mismatched `--pub`, a failed rename.

## What ran

- First round: the test on the base with the test and the checker added but `make_bundle.sh` as it was: 4 failed (the
  four runs of `make_bundle.sh`), 5 passed (the checker's own cases); at the head, 9 passed.
- Fix round: the new tests (R1 to R6, F1, F5, each refusal) added before the fix: see the pull request for the counts
  before and after. Every key is a throwaway pair made in the test's tmp folder; none is committed.
- The checks of CLAUDE.md and the policy set: see the pull request.

## Not verified

- The launcher (`deploy/launcher.sh`) and the bootstrap (`deploy/bootstrap.sh`) do not check the `.sha256.sig` yet,
  and RUNBOOK section 1 does not name it: a finding for a later card (HYG2-02).
- No real release was built: the runs use the stand-in `docker` of `test_release_bundle.py`.
