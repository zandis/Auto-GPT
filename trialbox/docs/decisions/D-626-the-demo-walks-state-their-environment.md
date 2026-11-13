# D-626 The demo walks state their environment, and CI runs every one of them

- **Task:** DEMO-WALKS (from lane A2 by running, through the integrator, 2026-11-13; for the demo of 2026-11-17)
- **PR:** this branch (`agent/DEMO-WALKS-one-environment`)
- **Date:** 2026-11-13
- **Status:** accepted
- **Builds on:** D-127 (an unset `TB_ENV` means PRODUCTION), D-281 (the EDC signature key), T-504 (the walks in
  the demo image)

## Context

`python -m tools.cgmh_demo --walk registry` inside the demo image fails: the study's EDC page answers 503,
"edc.sign_key ... has no KEK: in PRODUCTION this key is made only wrapped under it". The refusal is right for a
PRODUCTION box. The walk is not one: it builds a synthetic site and a box of its own in a scratch folder, in one
process. But the demo image sets no `TB_ENV`, and the walk tool set none, so by the one rule the walk's box
counted as PRODUCTION. The image's served tool, `tools.demo`, sets `TB_ENV=DEV` itself and does not have the
fault. CI's `demo-boot` job ran one walk of three (`amend`), so the fault never showed.

## Decision

1. The walk tool states its environment itself, in its `main`, as `tools.demo` does: `TB_ENV=DEV` unless the
   caller set one, and the first line it prints names the environment. Not the image: an `ENV TB_ENV=DEV` in
   the image would make every command run in it DEV, also one that is a product path, and would hide the
   PRODUCTION rules from it. A caller that sets `TB_ENV` is obeyed, so a walk against the PRODUCTION rules stays
   possible and fails where those rules say.
2. `demo-boot` runs every walk in `tools.cgmh_demo.WALKS`, in the three languages. A test holds the workflow's
   list equal to the tool's, so a new walk is in CI the day it is written.
3. No PRODUCTION rule changes. The EDC key rule is untouched.

## Consequences

- The three walks of the demo script run the same way in the image, on a developer's machine and in CI.
- The demo image still has no `TB_ENV`: what is served decides its own environment.
