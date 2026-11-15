# D-886 the release gates name a missing local image and the target that builds it

- **Task:** I-7 (the demo image in SC_OWN_IMAGES versus release-gates; F3a of the installer first contact)
- **PR:** this branch (`agent/I-7f-the-gates-name-a-missing-image`)
- **Date:** 2026-11-15
- **Status:** accepted

## Decision

`release-gates` checks every local image it is given before any scan and stops with one line per missing image and
the target that builds it (`make demo-bundle` for trialbox-demo, `make images` for the others), or `SC_OWN_IMAGES` to
leave it out. The demo image stays in the gated list: the gates still scan everything a bundle can carry.

## Test

`tests/unit/test_gates_name_a_missing_image.py`: before, 3 failed; after, 3 passed.
