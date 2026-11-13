# D-651 Whether the lake has no opt-out registry is asked of the lake, not read out of an error's text

- **Task:** OPTOUT-registry-table-probe (placed by the integrator across the lane line on 2026-11-13; found by the
  review of D-650)
- **PR:** this branch (`agent/OPTOUT-registry-table-probe`), cut from the D-650 card (`9750b4be`), which sits on
  #517 (D-649) and #505
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Builds on:** D-649, D-650 (the same remedy for `site_fact` and `document`), D-127 / F-04, D-477 (one consent
  rule)
- **Outside lane A2's folders, placed by the integrator:** `libs/tb_common/optout.py`,
  `libs/tb_common/lakeprobe.py`. Read, not changed: `services/orchestrator/decision_context.py`,
  `services/datacore/optout_worker.py` (lane E's).

## Context

`tb_common.optout.registry_state` reads the lake's `consent` table: who refuses research use, who refuses
contact. It answers None for "the lake has no consent table (the registry was never ingested)", and every caller
takes None for "no opt-out to apply". It told that case from any other failure by the error's text: "consent"
with "does not exist" or "Catalog Error".

**What a mistaken reading did.** Another failure of the registry query whose text held those words read as "no
registry". Run for this card: a lake that has the table and raises `lake query failed (503): Catalog busy; consent
does not exist in the cache` gave None. Then:

- the cascade (`matching/cascade/engine.py`, S0) applied no opt-out: `refused` and `no_contact` empty, and
  patients who said no were screened and listed. This leans to a **pass**, unlike D-649 and D-650, which lean to
  unknown;
- a job's decision context (`orchestrator/decision_context.py`) gave `refused()` and `no_contact()` as empty to
  every scenario of the job;
- the opt-out worker (`datacore/optout_worker.py`) took it for "no registry": it synced nothing, and reported
  nothing as failed.

The deep review of 2026-11-12 lists it as ENG-036, severity Low ("still classify exceptions by message text").
For this file the severity was too low: it is a failure that lists patients who refused. The review file is not
edited; this note stands for the correction.

## Decision

1. `lakeprobe` moves to the library (`libs/tb_common/lakeprobe.py`); `matching/proposed.py` and the cascade
   import it from there.
2. `registry_state` reads the registry through `lakeprobe.rows_or_no_table(..., "consent")`. After the query
   fails, the lake is asked how many tables or views named `consent` the snapshot has. Only one row with the
   integer 0 gives None. Any other answer, and a failure of the question, raises the first failure.
3. Every caller fails closed on that raise, with no change to its code:
   - the cascade's S0 does not catch it: no run without the opt-out answer;
   - the decision context does not catch it: `refused()`, `no_contact()` and `consent()` raise, the job fails;
   - the opt-out worker catches it, names `registry` in `failed`, syncs nothing, and goes on with the register it
     already holds (opt-outs already known still apply and are still erased).
4. A test over `libs` and `services` holds that no code decides by the text of an error it caught
   (`tests/unit/test_no_decision_by_error_text.py`). It sees `str`, `repr`, `format`, an f-string, `%`, `.args`,
   `.message`, a name assigned from these, and the error handed to a helper inside a condition (how the note
   reader's check escaped D-700's scan). Eight files are listed with whose each is and what it does; one of
   them is the same defect in another lane (`services/edc/prefill.py`, lane E).

## The harder question, put to the owner (not changed here)

**Should a clear "no consent table" still mean "apply no opt-out" on a PRODUCTION box?**

What today's install guarantees: the lake's own store builds every table of its schema on every rebuild, `consent`
among them (`lake.flatten.SCHEMAS`), empty when the registry has no row. So a snapshot built by this software
always has the table. A snapshot without it was made by hand, by other software, or by a store from before the
table existed. On a production box that is not "this site has no registry"; it is a lake that should not be
there.

Proposal: with `TB_ENV` PRODUCTION (also when unset), a lake without a `consent` table **stops the run** with a
sentence that says so; None stays for DEV and TEST, where hand-made lakes are used. This card does not do it: it
changes what a production box does when its registry is absent, and that is the owner's decision.

## Test

- `tests/unit/test_optout_registry_probe.py`: the confirming case first (the 503 with the words gave None;
  "DID NOT RAISE" before the change); every failure on a lake that has the table stops; a lake that answers 0 has
  no registry; every answer that is not a clear 0, and a failing question, stop; the decision context raises from
  `refused`, `no_contact` and `consent`; the opt-out worker names the registry as failed and keeps its register.
- `tests/unit/test_cascade_exclusion_rules.py::test_a_consent_table_error_stops_the_run`: its control was the
  defect itself (an error with the words, from a lake that has the table, and the patient stayed in scope). The
  control is now a lake that answers it has no such table; the same words from a lake that has the table stop the
  run. The 503 case is kept.
- `tests/unit/test_no_decision_by_error_text.py`: the scan and a test of the scan on thirteen spellings that must
  be found and six that must not.
