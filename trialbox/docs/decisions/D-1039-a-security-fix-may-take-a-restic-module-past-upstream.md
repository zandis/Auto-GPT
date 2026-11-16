# D-1039 A security fix may take a restic module one version past restic's main branch

- **Task:** the integrator's ruling on lane D's question (PR #639, 2026-11-16), under D-1035's condition "pinned"
- **Date:** 2026-11-16
- **Status:** accepted

## Ruling

1. `golang.org/x/crypto` may go to v0.59.0, one minor version past restic's main branch, to clear GO-2026-5932. The
   modules that version forces (`x/text` v0.44.0, and `x/sys` and `x/term` by minimal version selection) are inside
   this ruling.
2. Conditions: every version pinned by hash in the build; the licence count stays at most 86 (D-1038); restic's own
   test suite runs in the build, and what is left out of it is listed with its reason in D-968; our restore
   rehearsal passes on the built binary; the card says in one line why the versions differ from upstream.
3. Left out of restic's suite, as D-968 lists it: the FUSE mount tests, four tests that need Python in the builder,
   the vet step, and the package `internal/selfupdate`, which only the self-update command imports and which the
   binary is built without.

## Where the wording comes from

The integrator's replies to lane D of 2026-11-16.

## Used by

D-968.
