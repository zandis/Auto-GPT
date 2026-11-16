# D-919 A line that permits, or covers part of the population, goes to a person

- **Task:** NEW-LIFE-18 (plan v7 §A: two real public protocols, an RA trial and an early-AD trial, as fixtures; LIFE-002). The fixtures are lane G's G-8 records in `tests/fixtures/public_protocols`. The early-AD trial (NCT03887455) was already held by `test_protocol_structure` and `test_any_of_groups`; the RA trial (NCT02629159, upadacitinib) had no expected structure. Lane A2's backlog, card 3 (#639, 2026-11-16). **Date:** 2026-11-16. **Status:** reserved.
- **Decision:**
  - **The RA trial's structure is written down by reading the protocol**, never copied from a model's output (lane G's validation reset of 2026-11-14 kept G-8's model-derived fixtures off the trains). It has 7 inclusion and 3 exclusion lines, in their order, with what a person reads each as.
  - **A permission, not a requirement.** Reading it found that inclusion 6, "Subjects with prior exposure to only one bDMARD … may be enrolled (up to 20 % of total study population)", permits rather than requires. Compiled as a required inclusion, it excluded every bDMARD-naive patient, most of them, silently. Exclusion 3's "History of secondary Sjogren's Syndrome is permitted" is an exception inside an exclusion. `structure.check` now flags `permission`:
    - en: may be enrolled / included / eligible; is or are permitted / allowed / acceptable; up to N % of;
    - ja: 組み入れ可;
    - zh-TW: 可納入, 得納入, 允許.

    The line goes to a person, who rejects it or rewrites what it requires.
  - **A line for part of the population.** `part_population` flags "does not apply to …", "not applicable to …", "applies only to …", "only in the … cohort / arm / part" and 適用しない / 不適用. The case is TRAILBLAZER-ALZ 2's "… criteria - does not apply to safety cohort". The line goes to a person, as another phase does (`other_phase`).
  - **Direction.** Both flags only move a line from the machine to a person, never the other way. The early-AD fixture's findings are unchanged, and shipped rulesets keep their approved IR.
- **Test:** `tests/unit/test_public_ra_protocol_structure.py`.
