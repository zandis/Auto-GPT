# D-442 Derived data, the rest: screening reads stored rows, rulesets pin score definitions, the batch after ingest, no eGFR under 18

- **Task:** T-207 (`docs/plan/28-master-plan-v6.md` §6.2)
- **PR:** this branch (`agent/T-207-derived-data-rest`)
- **Date:** 2026-11-11
- **Status:** accepted
- **Closes:** CR-066 (the rest after PR #59); D-190 "Not done" (screening reading stored rows, ruleset pinning of
  definition versions, scheduling the batch, the eGFR under-18 rule); CR-120 in part (see Open)
- **Builds on:** D-189 (definitions from the catalogue), D-190 (stored derived rows), D-275 (unusable data is unknown),
  D-318 (prompt pins), D-301 (terminology pins), D-397 (the follow-up after an ingest)

## Decision

1. **No eGFR under 18.** Both equations are for adults (catalogue `egfr_ckd_epi_2021.yaml`, `egfr_jsn_2009.yaml`:
   "age < 18: do not compute"). An age under `derived.EGFR_MIN_AGE` (18) gives no value and
   `derived_adult_only:age` in the Python reference, the SQL generator and the CQL `TB_Common` (`EGFR2021`,
   `EGFRJSN`). An age of 0 or less stays `derived_missing_input:age`, now in the SQL CKD-EPI template too. The engines
   keep their own age: the SQL and CQL the age at the index date, a stored row the age at its anchor. New reason code
   `derived_adult_only` with words in ja, zh-TW and en. **This changes screening results on purpose**: the goldens are
   regenerated with the tool (every eGFR criterion of a patient under 18 at the index date with a creatinine in the
   window moves from met or not met to unknown).
2. **Rulesets pin the score definitions.** An approval writes `derived_pins` (schema `RulesetManifest`, new
   `DerivedPin`: `def_version`, `sha256`) for every engine score its compiled criteria follow
   (`scores.FOLLOWS`: `egfr` pins CKD-EPI 2021, `das28` both DAS28 variants; BMI, BASDAI and ASDAS have no catalogue
   definition and pin nothing). `ruleset.approval_state` reports `approval_needed` with a reason of kind `derived`
   (`newer`, `changed` or `unknown`) when the box computes a pinned score under another version or text; the approval
   page says so in three languages. A recompile drops the pins; the next approval writes them again. A ruleset
   approved before this decision has no pins and reads the box's current definitions.
3. **Screening reads the stored rows.** The SQL keeps computing the score (the engines agree), and the stored row of
   record must stand behind every decided answer on a stored score (CDAI, SDAI, DAS28, both eGFRs):
   `matching.stored_scores.StoredScores`, applied by `SqlEngine` after the coverage and proposed-fact rules when it is
   given the store (`screen.structured_engine` gives it whenever there is a trial database). It can only turn a
   decided answer into unknown, never decide one: `derived_not_stored` when there is no finished batch of the
   snapshot, the batch ran under other definitions or failed for the patient, there is no current row in the window,
   the row is of another definition than pinned, or it is anchored on another visit than the SQL used; the row's own
   reason when it has no value; `derived_vs_documented` for an open conflict, or when the documented value a person
   kept gives another answer; `derived_not_stored` when the stored computed value gives another answer. An unknown
   stays unknown. The goldens and the bench run the SQL alone (no store), as before.
4. **The batch runs after every ingest that passed**, before the follow-up micro-batch (`orchestrator.derive`,
   called by the INGEST scenario): every patient of the new snapshot, under the lake's mapping version(s)
   (`derived_store.mapping_version_of`). A batch over a named snapshot of every patient is recorded in the new table
   `derived.batch_run` (migration 2: snapshot, mapping version, the definitions it ran under, counts, failed
   patients) and audited (`derive.batch`). A failed batch is logged and audited (`derive.failed`) and never fails the
   ingest; its snapshot then reads every stored score as unknown.
5. **`DerivedStore.latest_many`** reads the rows of many patients in one query (newest anchor date, then the larger
   anchor row id); `latest` is now that read for one patient. `Latest` carries the anchor row id and the definition
   sha.

## Evidence

`tests/unit/test_derived_rest.py` (the under-18 rule in the three engines and the words; pins and approval needed;
the approval writes the pins; the screening read on a lake with the real store: no batch, batch, open conflict,
documented value kept, another pinned text; the rule only ever takes a decided answer away; DAS28 reads the variant
the visit used; the batch after the ingest, and a failed batch audited and not raised); the existing derived, safety
and migration tests; `tools.build_rulesets --check`; `tools.goldens --check` after the regeneration.

## Open

- The console has no page for derived conflicts (the steward resolves through `DerivedStore.resolve`).
- The stored rows are not written to the OMOP `measurement` table with `FACT_RELATIONSHIP`
  (`services/omop/derived_rows.py` of the plan row is not built).
- FEAS counts read the SQL alone; only SCREEN, MICROBATCH and NAV read the stored rows.
- A kept documented value never decides a criterion on its own: when it agrees with the SQL the answer stands, when
  it does not the criterion reads "needs information".
- Two anchor rows on the same day: the SQL takes the later time, the store the larger row id; when they differ the
  criterion reads "needs information" (safe, rare).
- CR-120 Lows not done here: the engine version is not in the fingerprint; the sha is over the whole YAML; the
  generator guard can be bypassed; import-time coupling; version namespaces; migration nits; the fallback anchor key.
- The clinician worked examples for DAS28, BASDAI, ASDAS and MELD 3.0 (owner's examples) are not in the YAML.
