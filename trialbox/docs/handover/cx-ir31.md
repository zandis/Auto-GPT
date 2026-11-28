# cx-ir31: IR 3 SQL qualifiers

**Reader:** the people who build TrialBox.

Compiler implementation and local execution verified on 2026-11-26. Integration into the runtime snapshot is
not verified. Decision number needed: retain the v1 generator path and lower supported v3 qualifiers only at
the SQL entry point. No contract, lake schema, ingestion, or approved ruleset source changes.

## Changes and inputs

`SqlGenerator.render` accepts validated v1 or v3 criteria. V3 boolean references become the existing nested
logic, with reference-range, medication and window qualifiers retained separately. Unsupported semantic
qualifiers raise `CompileError`; they are not silently discarded. The shared CQL semantics are unchanged.

The compiler still reads flattened observation and medication rows. V3 detail queries additionally require
the existing OMOP measurement or drug_exposure tables, tb_record, and tb_id_map to be visible in the same
SQL snapshot. Joins use the export's record and patient mappings, including observation component ids and
counted record statuses. Duplicate mappings fail a scalar subquery; they do not multiply evidence.
This job does not expose those tables in the deployed query connection.

Reference comparisons use measurement.value_as_number and that measurement's range_high or range_low.
Missing numbers, bounds, or eligible mappings produce UNKNOWN. No site-default bound is used. Values
and bounds are compared in their shared row unit, without converting one side independently. Existing
censored-result, quantifier and boolean three-valued handling remains in effect.

Study windows read caller-supplied `criterion_anchors(ruleset, pid, index_date, screening_date,
randomization_date)`. The key is ruleset/patient/index date; duplicate keys fail, absent rows or dates
produce UNKNOWN. Dates are DATE values. The caller must provide the relation, even when it is empty.
Queries without study anchors do not refer to it or add bind parameters. Existing $1/$2 parameters are unchanged.

Medication route strings are OMOP route concept ids, compared to route_concept_id; NULL and concept 0
mean UNKNOWN. Dose requires exact dose_unit_source_value equality. NULL quantity, missing or unequal
units, or a missing requested route mean UNKNOWN, even if another qualifier would fail. Cumulative dose
means quantity on one exposure, not a sum across exposures. Daily dose is mean quantity per supply day,
quantity / positive days_supply; absent or nonpositive supply is UNKNOWN. Exposure windows include
end date or start plus days_supply minus one. An unknown end cannot disprove overlap with a later window.
Drug matching retains the existing code, ingredient-stem and off-list-family handling.

## ULN example and ruleset comparison

The approved GZQO-EXC-13 source has `num: 120.0` at line 11. It remains unchanged because the shipped
loader and CQL build consume v1. The separate [v3 example](cx-ir31/GZQO-EXC-13-v3.json) replaces only
the threshold semantics with `"value": {"op": ">", "ref": {"kind": "uln", "multiple": 3}}` and uses
neutral explanatory text. Its existing index-relative 180-day window remains. A screening window instead
sets anchor to screening and requires the anchor input described above.

The [generated SQL example](cx-ir31/GZQO-EXC-13-v3.sql) compares
`(o.value_num > (o.ref_bound * 3))`, with value_num selected from m.value_as_number and ref_bound from
m.range_high. Before: `(o.value_num > 120)`. After: the row-specific multiplication, also used in the
censored comparison branches. NULL propagates through both branches. This example is not an approved ruleset.

Direct rendering of all eight live rulesets against their committed value sets was compared with the
checked-in SQL text and with rendering after v1-to-v3 upgrade. Every comparison passed. Text comparison
normalizes filesystem line endings; the generator's returned strings match exactly between v1 and v3.

| Ruleset | Before / after SQL, by criterion and line |
| --- | --- |
| AD-MAB | Identical; no changed criterion or line |
| GOUT-COH | Identical; no changed criterion or line |
| GZQO | Identical; no changed criterion or line, including GZQO-EXC-13 |
| NEUR-COH | Identical; no changed criterion or line |
| ONC-OSI | Identical; no changed criterion or line |
| RA-BIO | Identical; no changed criterion or line |
| RA-COH | Identical; no changed criterion or line |
| RA-JAK | Identical; no changed criterion or line |

The offline recompile `PYTHONPATH=libs:services:. python -m tools.build_rulesets --recompile` reports all eight
rulesets equal to the compiler's output and writes no file.
The direct rendering above does not refresh terminology, CQL or translated artifacts.

## Tests and failing-first evidence

`pytest tests/unit/test_sql_ir3_features.py` runs the new tests (in-memory database, no server).
The initial ten tests failed with 35 subtest errors because the v1 generator
treated v3 string references as boolean nodes (`AttributeError: 'str' object has no attribute 'args'`).
After implementation they passed. Seven additional tests exposed missing-end overlap and nonfinite
threshold defects; those tests were added before the fixes. All 17 now pass with a fixed 2026-10-05 index.

New methods in SqlIR3Features:

- test_reference_range_true_false_unknown
- test_reference_sql_uses_row_bound
- test_anchor_true_false_unknown
- test_medication_route_true_false_unknown
- test_medication_dose_true_false_unknown
- test_single_dose_is_not_exposure_quantity
- test_medication_window_includes_days_supply
- test_daily_dose_without_positive_supply_is_unknown
- test_missing_exposure_end_cannot_disprove_window_overlap
- test_missing_route_overrides_failed_dose
- test_reference_censored_and_boolean_unknown
- test_duplicate_anchor_is_rejected
- test_nonfinite_threshold_is_rejected
- test_all_reference_quantifiers_preserve_unknown
- test_record_mapping_is_patient_specific_and_respects_status
- test_unsupported_fields_are_not_silently_dropped
- test_all_live_v1_rulesets_stay_byte_identical

No snapshots were updated and no test was changed, skipped or gated. The only edit to an existing test file is a
type-only one: the render override in tests/unit/test_criteria_safety_review.py takes a Sequence like the base class.

## Skipped and findings

- Single administration dose: exposure quantity is a total, not an administration dose. No safe conversion
  follows from these columns. It raises CompileError. No dose-era-to-exposure association is invented.
- Per-ingredient equivalents, medication status and duration combined with medication details are rejected.
- value_if, attribute, event-relative windows, macros, change, aggregate, line of therapy and diagnosis role
  remain unsupported. No schema additions were made.
- The deployed flattened snapshot does not currently export the additional OMOP columns or relations.
  Runtime exposure of those existing relations and supplying study dates remain integration work.
- The current ruleset loader and CQL compiler still require v1; this job adds the v3 SQL entry point, not
  v3 end-to-end approval. GZQO's approved fixed threshold therefore remains a separate remediation item.

Existing assertions proposed for change: none. Scripts called by file path: none; executable-bit changes: none.
No network, commits, history changes, scan exceptions, or edits to the central findings register.
Generated examples were written through a temporary file, flushed, fsynced and renamed.

Files changed: the SQL generator, new ir3 helper and anchor/detail/medication SQL templates, the new
test_sql_ir3_features test module, this card page, and its findings and two generated example artifacts.
