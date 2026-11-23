# D-1091 On a PoC box the install stops for five things only (H-94)

- **Task:** lane H, card H-94 (the owner's ruling, relayed by the integrator in comment 7092087958; the fifth stop in
  7095256773; the answers in 7096436960) · **Date:** 2026-11-23
- **Status:** reserved for H-94 (the integrator flips the row when merged)
- **Builds on:** D-127 (a box is PRODUCTION unless it says otherwise), D-726 and D-887 (the rehearsal box), D-1087
  (the real servers on a rehearsal box)

## Decision

1. **On a PoC box** (DEV, TEST or VALIDATION by every source that speaks: `TB_ENV` in `deploy/.env`, an installed
   box with none being PRODUCTION, the rehearsal mark, this run's `--environment` and `--rehearsal`; never a
   caller's variable; a box that cannot be told is PRODUCTION) the install, start and update paths stop for five
   things only: (1) the bundle's or update's signature or hashes do not hold; (2) the machine physically cannot run
   it (disk, memory, card); (3) a PoC box would load real patient data or become PRODUCTION; (4) the step needs root
   and does not have it; (5) a secret would be read from, or written to, a place others can read.
2. **Every other stop warns** there: one line on stderr, one line of `deploy/site/poc-stops.jsonl` (no secret's
   value, no path under `uploads/`), which `trialbox doctor` shows as a WARN line with its action, and the step goes
   on. Where the next lines depend on the check, the step it guards is skipped and the list says what.
3. **A stop the next lines depend on is kept only if it protects one of the five** on the input that reaches it;
   otherwise it warns.
4. **On a PRODUCTION box nothing changes:** every stop prints the same words with the same exit code.
5. Each stop on these paths names its number in a comment or calls `stop_or_warn` (`tools/trialbox/stops.py` for
   Python); a ratchet test holds every file of the path to its count.
6. The real path binds every guard (7092045961 items 1-2): the one test drives the real `deploy/install.sh` through
   the bundle load and the signed re-run, with every converted point forced, to the end.
   `tests/unit/test_poc_stops_h94.py::test_a_poc_install_goes_through_every_converted_point`.

The card's page: `docs/handover/poc-stops-h94-2026-11-23.md`.
