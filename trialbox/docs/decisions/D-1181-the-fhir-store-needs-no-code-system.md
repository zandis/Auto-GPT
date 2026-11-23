# D-1181 The FHIR store needs no code system: each value set reaches it expanded (V-17)

- **Task:** lane V, card V-17 (MVP walk step 3: every compile on a fresh box failed its equivalence check with "Failed
  to expand ValueSet"; the integrator's addition: close the gap D-1028 and D-991 leave for the FHIR store) ·
  **Date:** 2026-11-23
- **Status:** reserved for V-17 (the integrator flips the row when merged)
- **Builds on:** D-1028 (code systems are loaded at install), D-991 (the services read the loaded code systems)

## Decision

1. **At install the FHIR store needs nothing but its image and its database.** No code system, no CodeSystem
   resource, no terminology server, no ValueSet loaded into it. D-1028's code systems go to the services that read
   them (D-991); none goes to the FHIR store.
2. **Who gives it what the compile's equivalence check needs:** the service that loads it, at the time of the check,
   through `tb_common.fhir.FhirEvaluator.load` (the compile's check, approval, the SCREEN and NAV pre-checks, the
   scenario tools). It sends the libraries and each ValueSet **expanded already**, computed offline from the codes the
   ValueSet lists (`store_valueset`). The store's CQL engine reads that expansion as it is: no `$expand`, no fallback
   to the listed codes.
3. **A ValueSet with no code** (a concept that mapped to none) is sent listing one code of TrialBox's own system
   `https://trialbox.local/fhir/CodeSystem/no-member`, which no record is coded in: the store answers "no member",
   as the SQL does. An empty expansion is never sent (the engine reads it as no expansion).
4. **The ruleset is not changed:** its ValueSet files, hashes and versions stay as compiled; only the copy sent to the
   store carries the expansion. A ValueSet that is not a plain list of codes (a filter, another ValueSet, an
   exclusion, a whole code system) or is expanded already is sent as it is.
5. **The test:** `tests/integration/test_valueset_store_compose.py` (the compile's gate on a fresh FHIR store with a
   criterion whose concept maps to no code: fails on master with "Failed to expand ValueSet", passes with this) and
   `tests/unit/test_fhir_store_valueset.py`.

## Why

Every compiled ValueSet is a list of codes with no filter: it needs no code system content to expand, and no licensed
content (LOINC, WHO ICD-10, ATC) may ship. The store was given the lists unexpanded, so its engine fell back to
them with a warning, and a list with no code has no `compose` at all, which stopped the whole protocol's check.

## Not chosen

- Loading code systems, or stub CodeSystem resources, into the FHIR store at install: content that may not ship, a
  second home for D-1028's tables, and it does not help a ValueSet with no code.
- Writing the expansion into the ruleset's ValueSet files: every committed ruleset rewritten, its codes twice.
- Sending a criterion whose concept maps to no code to a person instead: the compiler owner's decision (V17-03).
