# D-633 A PRODUCTION or VALIDATION box refuses a bundle built from a working tree

- **Task:** RELEASE-DIRTY (the owner's decision of 2026-11-13, given in the integrator's session, on lane D's
  finding in D-631)
- **PR:** this branch (`agent/RELEASE-DIRTY-a-site-box-refuses-it`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-631 (a bundle is built from a commit, or with `--allow-dirty` and says so in
  `release.json`), D-127 (an unset `TB_ENV` means PRODUCTION), D-210 (the update's preflight)

## Context

D-631 made the vendor's side honest: a bundle built from a working tree says `dirty: true` in its signed
`release.json`. Nothing on the box read that. A rehearsal bundle, signed with the vendor key, installed on a
site box like a release.

## Decision

The owner's decision: a PRODUCTION or VALIDATION box refuses a bundle whose `release.json` says it was built
from a dirty checkout, at install and at update, with the reason in the refusal; DEV and TEST boxes take it.

1. **Where.** Two places in `tools/trialbox/update.py`, both before anything is changed: the update's
   preflight, and `main_apply`, ahead of its two paths. The second is needed because a first install
   (`deploy/install.sh`, `TB_SKIP_AUDIT`) takes the short path that only loads the payloads and never runs the
   preflight (found by the review: the first version of this card left a fresh PRODUCTION box open).
2. **Which box.** The box's environment is `TB_ENV` in `deploy/.env`, PRODUCTION when it is not set (D-127). The
   process environment is not asked: a `TB_ENV=DEV` typed in front of the installer is not written to the box,
   so it must not open the door. A fresh install has no `deploy/.env` yet and is therefore PRODUCTION; a DEV or
   TEST box that is to take such a bundle has `TB_ENV` in its `deploy/.env` first (the installer keeps it).
3. **A bundle that does not say.** A bundle with no `release.json` is taken as before; the update says in its
   notes that it has no release record. The verifier already refuses images without one. A `release.json`
   whose `source.dirty` is missing or not true/false, or whose `source.commit` is not a commit id (a build
   outside a git checkout writes `dirty: false` and no commit), is refused on a PRODUCTION or VALIDATION box.
4. **The record.** `installed.json` keeps `dirty` of the release it names.

**Which updater runs the check.** At an update the check is run by the installed release's updater, not the
new bundle's. A box on a release from before this card takes a dirty bundle at its next update; the rule holds
from the update after the first release with this card. A first install is run from the media's own tree, so a
fresh box is held to it from that release on.

## Consequences

- The box rehearsal installs as PRODUCTION. Run from a checkout with local changes its own box now refuses its
  bundle: commit first, then rehearse. From a clean checkout (CI) nothing changes.
- Not closed here: a bundle of the host tree alone, signed by hand without `release.json`, says nothing about
  how it was built and is taken. The verifier accepts a release record only together with images, so such a
  bundle cannot carry one; `tools/make_bundle.sh` never builds one. Closing it means letting the verifier take
  a release record without images, then refusing a host tree without a record: a further card.
- Not closed here: a box set to DEV, given a dirty bundle, and then set to PRODUCTION. `installed.json` now
  holds what a `doctor` check needs to fail such a box; that check is a further card.
