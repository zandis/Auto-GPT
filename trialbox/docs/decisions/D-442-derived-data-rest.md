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
   window moves from met or not met to unknown). The recorded CQL test sets move the same way: `rulesets/GOUT-COH`
   and `GZQO` `tests/expected.json` re-recorded with the local CQL engine (`tools.cql_eval`), `RA-JAK` with
   `tools.build_scenario_ruleset` (its gold, `tools/synth/rajak.py`, says no eGFR for the 15-16 band); the e2e
   pinned GOUT-COH screen numbers move by one patient to review.
2. **Rulesets pin the score definitions.** An approval writes `derived_pins` (schema `RulesetManifest`, new
   `DerivedPin`: `def_version`, `sha256`) for every engine score its compiled criteria follow
   (`scores.FOLLOWS`: `egfr` pins CKD-EPI 2021, `das28` both DAS28 variants; BMI, BASDAI and ASDAS have no catalogue
   definition and pin nothing). `ruleset.approval_state` reports `approval_needed` with a reason of kind `derived`
   (`newer`, `changed` or `unknown`) when the box computes a pinned score under another version or text; the approval
   page says so in three languages. A recompile drops the pins; the next approval writes them again. **The eight
   committed approved rulesets have no pins**: a study approved before D-442 is unpinned until its next approval, so
   "approval needed" never fires for a changed score definition there. They are not back-filled; the approval page
   says so (`s20.pins.unpinned`).
3. **Screening reads the stored rows, behind one audited flag that is OFF.** The flag `derived.stored_read`
   (`tb_common.flags`, default `off`, no seed variable: the administrator switches it on `/ops/flags` with a reason)
   is read once per job through `tb_common.derived_store.stored_read` (`orchestrator.derive.reader`). **It stays off
   until items 3a to 3c below are proven on a real run.** Off, no path reads the store: the answers are the SQL's,
   as before. On, every path that decides a score criterion runs the one function
   `matching.stored_scores.apply_rows` on the approved SQL's rows before it reads them: the v1 engine (`SqlEngine`:
   v1 SCREEN, NAV, the MICROBATCH re-check, CASE), the cascade's S1 (cascade SCREEN, the new-patient MICROBATCH) and
   COHORT. A test runs the same patients on the same snapshot through the v1 engine, the cascade and the cohort rows
   with the flag off and on and gets the same answer on every path. FEAS counts read the SQL alone: unknowns in FEAS
   belong to T-216 ("FEAS does not hard-exclude on unknown"). The read only ever turns a decided answer into
   unknown, never decides one:
   - **3a, one age rule** (the index date's). A row with no value because the patient was under 18 at the
     creatinine's date reads `derived_not_stored` when the SQL decided (the patient is 18 at the index date), never
     `derived_adult_only`.
   - **3b, reproducible reads.** A snapshot's rows are read as they stood when its first derive batch finished
     (`batch_run.finished_at`: rows computed by then and not yet superseded, conflicts opened by then with their
     state then), so a re-run of a job (`orchestrator.rerun`) reads what the job read. A later batch of the same
     snapshot changes nothing read. A conflict opened or resolved after the batch is read from the next snapshot's
     batch on. The batch must have run under the definitions the ruleset pinned (unpinned: those the box computes
     now; an unpinned ruleset re-run after a definition change reads unknown).
   - **3c, a missing or failed batch is seen.** The snapshot is published before the batch runs; a batch that never
     finishes leaves `finished_at` empty. The readiness page says so (`patients.scores_unverified`), the health line
     has `derive_batch` (`tb_common.metrics.check_derive`: red while the flag is on, amber while off), and a
     screening list of a ruleset on stored scores says in its own header that the scores were not verified for its
     snapshot (the summary PDF's scope lines, the list workbook under its footer, `scores_unverified` in the JSON).
   - **Combined criteria.** The criterion's logic is evaluated in three values with each score atom at its stored
     comparison and the other atoms free; the SQL's answer stands when some value of the others gives it.
     `eGFR < 30 OR dialysis` with dialysis and no creatinine stands; `NOT eGFR < 30` with a stored eGFR of 20 is a
     contradiction. Limit of the flag-on mode: the other atoms are not read from the SQL, so a contradiction that
     needs their values is not seen (more than eight other atoms: only an unknown score atom is).
   - Reasons: `derived_not_stored`, `derived_vs_documented`, or the row's own (`derived_unit`, ...). The goldens and
     the bench run the SQL alone.
4. **The batch runs after every ingest that passed**, before the follow-up micro-batch (`orchestrator.derive`,
   called by the INGEST scenario): every patient of the new snapshot, under the lake's mapping version(s)
   (`derived_store.mapping_version_of`). A batch over a named snapshot of every patient is recorded in the new table
   `derived.batch_run` (migration 2: snapshot, mapping version, the definitions it ran under, counts, failed
   patients) and audited (`derive.batch`). A failed batch is logged and audited (`derive.failed`) and never fails the
   ingest; its snapshot then reads every stored score as unknown.
5. **`DerivedStore.latest_many`** reads the rows of many patients in one query (newest anchor date, then the larger
   anchor row id), as of a batch's finish when given; `latest` is now that read for one patient. `Latest` carries the anchor row id and the definition
   sha.

6. **One age in the three engines.** Complete years at the index date, the day before the birthday still the
   younger age: the SQL (`AGE_SQL`, for the eGFR and the age atom) and CQL (`TB_Common.AgeAt`, for both) now count
   as the Python `derived.age_at`. Measured before: DuckDB `date_sub('year', ...)` and the CQL engine's
   `AgeInYearsAt` both gave 18 on 2026-02-28 for a birth on 2008-02-29, Python 17. A three-engine test pins 17 on
   02-28 and 18 on 03-01. The goldens, the recorded CQL sets and the CQL path check stayed identical (no 29 February
   birth there).

## Evidence

`tests/unit/test_derived_rest.py` (the under-18 rule in the three engines and the words; pins and approval needed;
the approval writes the pins; the screening read on a lake with the real store: no batch, batch, open conflict,
documented value kept, another pinned text; the rule only ever takes a decided answer away; DAS28 reads the variant
the visit used; the batch after the ingest, and a failed batch audited and not raised; round 2: the flag decides for
every path, every path gives the same answer with the flag off and on, the age rule (born 2008-06-01, creatinine
2026-05-15, index 2026-11-01), the three-valued check of combined criteria, reads pinned to the batch, a missing or
crashed batch on the readiness page, the health line and the list header, and a 29 February birth in the three
engines); the existing derived, safety
and migration tests; `tools.build_rulesets --check`; `tools.goldens --check` after the regeneration.

## Open

- The console has no page for derived conflicts (the steward resolves through `DerivedStore.resolve`).
- The stored rows are not written to the OMOP `measurement` table with `FACT_RELATIONSHIP`
  (`services/omop/derived_rows.py` of the plan row is not built).
- The flag `derived.stored_read` is off until 3a to 3c are proven on a real run (a night with a batch, a night with a
  crashed batch, a re-run of a job after a conflict was resolved).
- FEAS counts read the SQL alone even with the flag on (T-216 owns how FEAS counts unknowns).
- A kept documented value never decides a criterion on its own: when it agrees with the SQL the answer stands, when
  it does not the criterion reads "needs information". It is read from the next snapshot's batch on.
- Two anchor rows on the same day: the SQL takes the later time, the store the larger row id; when they differ the
  criterion reads "needs information" (safe, rare).
- CR-120 Lows not done here: the engine version is not in the fingerprint; the sha is over the whole YAML; the
  generator guard can be bypassed; import-time coupling; version namespaces; migration nits; the fallback anchor key.
- The clinician worked examples for DAS28, BASDAI, ASDAS and MELD 3.0 (owner's examples) are not in the YAML.
