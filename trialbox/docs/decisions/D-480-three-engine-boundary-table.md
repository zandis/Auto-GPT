# D-480 The three-engine boundary table: the Python reference, the generated SQL and CQL on the same edge cases

- **Task:** T-711 (`docs/plan/31-master-plan-v6.1-addendum.md` §3.1, wave D; TB-PLAN-06.1)
- **PR:** this branch (`agent/T-711-three-engine-boundary`)
- **Date:** 2026-11-12
- **Status:** accepted
- **Measures:** answer 3 of `docs/reviews/2026-11-12-architecture/decision.md` ("clinical arithmetic: what is
  compared"; card AD-7); the `differential` gate of TB-PLAN-06 §7.5, which no workflow ran
- **Builds on:** T-619a (the five ALT edge cases, `criteria_compiler/equivalence/edge.py`), D-321 (the local CQL
  engine), T-652 (the equivalence gate), D-442 (derived data), D-315 (no site zone in code)

## Context

SQL and CQL are compared at approval on a sample of the site's own patients, at one index date; a boundary case is
compared only if the site happens to hold one. The Python reference (`tb_common.derived`: age, unit conversion,
physiological ranges, the scores) is in no gate. Not compared at all: age on the birthday and for a 29 February
birth; both ends of a window; the day boundary for anything but one ALT time; unit conversion and impossible values
across the three; derived scores in CQL.

## Decision

1. **One generated table of boundary cases** (`criteria_compiler/equivalence/boundary.py`), each a synthetic
   patient built to sit on an edge of one criterion of a shipped ruleset, with the answer the Python reference
   gives: age on the birthday and the day before, a 29 February birth in a leap and a common year, the first and
   last day of a window and the day outside each, 23:30Z and 00:30 in the site's zone on a window edge, each unit a
   criterion converts, a value outside the physiological range, each derived score on both sides of its threshold.
2. **Three engines answer it**: the Python reference states the expected answer; the generated SQL runs on an
   in-process lake built from the cases' FHIR resources through the ingest's own steps; CQL runs on the local
   engine (the one behind HAPI's `$evaluate`). A disagreement of any two fails.
3. **A CI job `differential`** (TB-PLAN-06 §7.5) runs the table through all three and fails on a disagreement or on
   a missing engine. The unit job runs the Python and SQL halves (no JDK needed).
4. **A disagreement found is not hidden.** A case on which the engines part today is listed by name with its
   finding and fails the job when it starts to agree (the line is then removed), as the tables of T-705 and T-706.

## Consequences

- No product code changes unless a disagreement is a defect small enough to fix here; otherwise it is a finding
  for its owner card.
- Goldens unchanged.
