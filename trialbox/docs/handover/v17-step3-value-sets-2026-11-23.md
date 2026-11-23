# V-17: step 3, the FHIR store cannot expand the compiled value sets (2026-11-23)

**Reader:** the people who build TrialBox: the integrator, the lanes that load the FHIR store (criteria compiler,
orchestrator) and the reviewer.

Card V-17 (lane V): the MVP walk on a fresh box stopped at step 3, protocol import. Every compile, the shipped
synthetic protocol GZQO too, failed its equivalence check: "the FHIR server refused it (FhirEvalError) ... Failed to
expand ValueSet .../GZQO-VS-GOUT". The same fault on the bench the day before was "the step 3 value-set card"; it was
not built (nothing in the tree, the history or the pull requests). Findings in the register's `--add-from` form:
`v17-step3-value-sets-2026-11-23/findings.json`.

## Why

- The FHIR store holds no code system, and nothing loads one: the install, the compile and the rehearsal all leave
  it empty, and the compiler posts each ValueSet as a plain list of codes (`compose`), never expanded.
- The store's CQL engine looks for an expansion first, then the store's own `$expand`, then reads the `compose`
  itself, with the warning "ValueSet ... is not expanded. Falling back to compose definition. This will potentially
  produce incorrect results." That is the warning the box's store log shows for every GZQO value set.
- A compiled ValueSet with no code (a concept that mapped to none: the mapper's method `none`, the compile's warning
  "concept ... could not be mapped") is written with `compose: {"include": []}`, which is no `compose` once sent. The
  engine then has nothing to read and stops the whole evaluation: "Failed to expand ValueSet". So one unmapped concept
  stopped the equivalence check of the whole protocol. Shown on a fresh store of the pinned image (in memory and on
  Postgres, the deploy's settings): the shipped `VS_GOUT` evaluates; the same ValueSet with no code gives the box's
  error word for word; an expansion with no code is read as none (the same error).
- The rehearsal and the compose tests did not see it: the protocols they compile map every concept with the test
  model's answers. A real model names concepts in words the tables may not hold (lane G's run of 2026-11-13: "concept
  'rheumatoid arthritis' (observation) could not be mapped", and two more). Which concept of the box's GZQO compile
  mapped to none is **not verified**: the box's compile output was not available to this card.

## The fix

`tb_common.fhir.store_valueset`, used by `FhirEvaluator.load` (every path that loads the store: the compile's
equivalence check, approval, SCREEN and NAV pre-checks, the scenario tools). The store is given each ValueSet expanded
already, from the codes it lists, offline: no code system, no terminology server, no hand step. A ValueSet with no code
lists one code of TrialBox's own system `https://trialbox.local/fhir/CodeSystem/no-member`, which no record is coded
in, so the store answers "no member" as the SQL does. The ruleset's own ValueSets (the files, the hashes, the
version) are unchanged: only the copy sent to the store differs. A ValueSet that is not a plain list (a filter,
another ValueSet, an exclusion) or is expanded already is sent as it is.

Decision: D-1181 (`docs/decisions/D-1181-the-fhir-store-needs-no-code-system.md`): the FHIR store needs no code system at install; built on D-1028 and D-991.

## Proof

`tests/integration/test_valueset_store_compose.py`: the off-list fixture's five criteria and one criterion whose
concept maps to no code, translated, loaded into a fresh FHIR store with its patients, through the compile's gate
(`run_gate`) against the in-process lake. On master it fails with `FhirEvalError ... Failed to expand ValueSet
.../VS-UNMAPPED`; with the fix the gate passes (100 %, every patient compared, the unmapped criterion false for all).
`tests/unit/test_fhir_store_valueset.py`: the store copy, four tests.

Not run: the rehearsal (`tools/rehearse_box/rehearse.sh`, it needs the release bundle and a box), the whole GZQO compile
and approval with the real models, the compose stack's own tests that need the lake service.

## Left open

- An unmapped concept still compiles to a coded criterion that no patient meets (both engines agree, so the check
  passes); the mapping's `needs_review` flag shows it to the reviewer. Whether such a criterion should go to a person
  instead (as B14, D-502, does for a value set no concept defined) is the compiler owner's decision.
- The doctor's lines "nothing loaded in /data/terminology" and "no ruleset repository at /data/rulesets" on a fresh box
  are not this fault: the compiler reads the shipped tables when nothing is loaded.
