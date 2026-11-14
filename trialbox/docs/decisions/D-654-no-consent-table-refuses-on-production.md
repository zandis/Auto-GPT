# D-654 On a PRODUCTION box a lake snapshot without a consent table refuses

- **Task:** OPTOUT-no-registry-refuses-on-production (the owner's decision of 2026-11-13 on the question D-651
  put to him, relayed by the integrator)
- **PR:** this branch (`agent/OPTOUT-no-registry-refuses-on-production`), cut from train 14 (`45416a9b`) with its two fixes (`f6db577f`),
  which holds D-651 (#535)
- **Date:** 2026-11-13
- **Status:** proposed (merges on a green train)
- **Ruling:** the owner: yes, refuse.
- **Builds on:** D-651 (whether the lake has no registry is asked of the lake), D-127 (fail closed; `TB_ENV`
  unset is PRODUCTION)
- **Outside lane A2's folders, placed by the integrator:** `libs/tb_common/optout.py`,
  `services/orchestrator/decision_context.py`. Read and tested, not changed: `services/datacore/optout_worker.py`
  (lane E's).

## Context

After D-651 a snapshot that the lake says has no `consent` table still read as "no registry", and every caller
takes that for "no opt-out to apply". The lake's own store builds the table on every rebuild, empty when there is
no Consent feed. So on a box built by this software a snapshot without the table was made by hand or by other
software; on a production box that is not "this site has no registry", it is a lake that should not be there, and
a run on it would list patients with no opt-out applied.

## Decision

1. **`registry_state` refuses.** When the lake answers that the snapshot has no consent table and the box is not
   a DEV or TEST box, it raises `NoRegistryTable`. Its sentence is fixed and holds no name, date or id:
   "The lake snapshot has no consent table. A snapshot built by TrialBox always has one, so this snapshot was made
   by hand or by other software. The run stops: without the table no opt-out could be applied."
2. **Which boxes.** `TB_ENV` by the one rule (`tb_common.config.environment_name`): unset is PRODUCTION. Only
   **DEV** and **TEST** keep the old reading (None), so tests and tools that build small lakes keep working.
   Every other name refuses: PRODUCTION, VALIDATION (a name the code base knows: `policy.classes.Environment`,
   the key rules, the not-matched gate), unset, and any name this code does not know, as the pair canary's gate
   does (D-117).
3. **The job stops with the sentence.** A job reads the registry through its decision context
   (`DecisionContext.consent`, also behind the cascade's S0, `refused()` and `no_contact()`): it turns the refusal
   into a step failure whose message is the sentence, at the step the job is in, so the job page and the "failed"
   mail say it; one line goes to the log. Nothing is cached: the next read asks again. A tool that runs the
   cascade with no job gets `NoRegistryTable` itself.
4. **The opt-out worker.** Unchanged, and already right: it catches the refusal like any failure of the read,
   names `registry` in `failed`, syncs nothing, and still runs every clear in the tick for the patients its
   register holds. On a DEV or TEST box a snapshot without the table fails nothing, as before.

## What is not covered

- A decision context with no lake at all still answers None on any box. No real job has one: the orchestrator
  always builds a lake client, and a job's lake is pinned; only stand-in contexts of tests get there.

- A snapshot whose consent table is there and **empty** because a night had no Consent feed: nobody is read as
  having refused; only the opt-out register protects (D-651's note).
- The worker when the lake cannot name a snapshot at all (`LakeHttp.snapshot()` answering None after a failed
  health check): it still takes that for nothing to read. Reported with D-651; lane E's and the lake's.

## Test

`tests/unit/test_optout_no_registry_on_production.py`: the refusal for `TB_ENV` unset, PRODUCTION in any case,
and any other name; None on DEV and TEST; a snapshot that has the table reads the same on PRODUCTION, and another
failure is that failure; the job's step failure with the sentence from `consent`, `refused` and `no_contact`; the
worker on PRODUCTION and on TEST. `tests/unit/test_cascade_exclusion_rules.py`: the cascade on a production box.
Before the change, run once: on PRODUCTION a snapshot without the table gave None.

## Review

One adversarial review by running (on `dd08eb22`). Verdict: merge; no HIGH or MED.

| Finding | Confirmed | What was done |
|---|---|---|
| LOW: the record and a comment said the settings have no VALIDATION name; the code base has one (it refuses, as it should) | by reading | both reworded |
| LOW: the step failure always named "running"; CASE reads the registry while parsing | by reading | the step the job is in; test |
| LOW: no log line for a job's refusal | by reading, by a run | one line |
| LOW: a decision context with no lake answers None on any box (no real job has one) | by reading | stated above |

Held (the reviewer's runs): on a real lake with the consent table dropped, unset, PRODUCTION in any case, an
empty value, TESTING, DEV2 and VALIDATION all refuse, DEV and TEST do not; real FEAS, SCREEN, NAV and COHORT jobs
on the in-process box end failed with the sentence, no output, a mail with no name, date or id, and all four end
done on a TEST box; the worker names the registry as failed and still clears; the service's environment and the
library's read are the same source, and where they could differ the library refuses; every tool builds its lake
through the store, which always makes the table; 57 test files that set PRODUCTION never meet the refusal; six
mutations each fail a test. The fixes after the review were not reviewed again.
