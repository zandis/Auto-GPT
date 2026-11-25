# D-1073 A medication look-back reads the supply period

- **Card:** INT-R1 (the owner's order through the integrator, 2026-11-25; the number is the integrator's)
- **Date:** 2026-11-25
- **Status:** proposed (merges on a green train). Every shipped ruleset's stored SQL changes (NEUR-COH's mark line
  only), so each needs the owner's re-approval; no lane approves a ruleset.

## Decision

1. In a look-back with a first day, a dated medication order counts when its order date is in the window or its
   supply period overlaps the window, both ends inclusive, in the SQL and the CQL alike.
2. A supply's last covered day is its start plus its days less one.
3. An order written before the window with no end (a start or only an order date) makes the answer unknown where
   nothing else settles it: it goes to the investigator and removes nobody. **There is no bound on how old such an
   order may be, for ring 0. A bound is a later parameter of the owner's.**
4. The CQL duration atom reads the same period as the SQL.
5. SQL compiled before this decision is not run alone: the overlay of D-275 runs it beside a fresh rendering and
   leaves a difference unknown (the mark line names D-1073).

Not here: the check of uncoded orders (`matching/coverage.py`) still reads the order date (INTR1-04, open).

The evidence, the tests and what was found and not fixed: `docs/handover/med-supply-lookback-intr1-2026-11-25.md`.
