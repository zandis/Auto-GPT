# D-574 The box rehearsal runs the real installer to its end

- **Task:** OPS-004b (the second part of OPS-004, TB-PLAN-07 v7.2 wave 1, lane D; D-570 names what it left)
- **PR:** this branch (`agent/OPS-004b-rehearsal-to-the-end`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Builds on:** D-570 (the rehearsal run again: five stops fixed, two named), D-176 (every image a box runs comes
  from the bundle; none is pulled), T-012b (a pin is the registry's expected manifest; champion only through a
  qualification record), D-569 (the shipped record and the install's promotion), D-566
- **Read by:** lane G (what only a real card proves), every card that changes `deploy/install.sh`

## Context

After D-570 the real `install.sh` runs inside the rehearsal's clean container up to the start of the stack. Two
things stood between it and "TrialBox is running": it asked for every pinned third-party image by its variable,
also for a model server that the rehearsal's stand-ins replace; and the rehearsal's placeholder weights are refused
by the rule that a pin is the registry's expected manifest.

## Decision

1. **The installer asks for the images its stack runs.** `tools/image_pins.py resolve` gets the rendered stack
   (`docker compose config --images` with the box's overrides). A pinned variable whose image no service runs is
   noted and not asked for. What the stack runs must still be on the box, by digest or by the bundle's pin, and the
   second check (every image of the rendered stack is on the box, nothing is pulled) is unchanged.
2. **The rehearsal's bundle carries what the box's stack runs**: the image list comes from the file set
   `install.sh` uses for the rehearsal's answers, with the stand-ins' override.

(The rest of this record is written as the rehearsal reaches each further stop.)

## Consequences

- A site that replaces a service through its compose override is not asked for the replaced service's image.
- No setting, no limit, no new store.
