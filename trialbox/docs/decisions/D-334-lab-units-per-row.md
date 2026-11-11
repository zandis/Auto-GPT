# D-334 Lab units read per row: one conversion table, one presence reader

- **Task:** T-613b (wave 1 of TB-PLAN-06, `docs/plan/28-master-plan-v6.md` §6.2.4; the wave-1 half of T-613)
- **PR:** this branch (`agent/T-613b-units-per-row`)
- **Date:** 2026-11-10
- **Status:** accepted
- **Builds on:** D-149 (`unit_defaults`), D-215 (the row-unit check of PR #70), D-275 (`tb_common.labunit`: the
  engines' unit key and the reason `unit_mismatch`)
- **Closes:** STD-001 (rest), STD-002, STD-022; CR-001 (adapter half)

## Context

PR #70 made the adapter read a lab row's own unit: a row whose unit is not the lookup's has no value and the reason
`unit_mismatch` (D-215). Three things were left. The JP path and the site templates were not tested to carry the
row unit (STD-001). There was no table that says which units convert, and by what factor (STD-002). Japanese and
Chinese qualitative results (陰性, 陽性, 未檢出, (−)) matched no lookup answer and stayed text, so hepatitis B,
TB and pregnancy criteria could never be decided from Japanese data (STD-022). The shipped mappings declared no
`unit_defaults` (D-149).

## Decision

1. **The adapter still never converts on its own.** A row in another unit has no value (D-215). A site that reports
   an analyte in another unit says so once in its lab lookup (`source_unit` and `factor`). µmol/L creatinine against
   an mg/dL lookup stays `unit_mismatch`, on the CSV, CGRD SQL and SS-MIX2 paths alike.
2. **One conversion table**, in `tb_common.labvalue` (`SCALES`, `MOLAR`, `ANALYTES`, `conversion`). Units of one
   kind (mass, substance, number, enzyme or international units per volume) convert by definition. Mass to
   substance needs the analyte: a molar mass per LOINC code, and a charge for meq/L. The analytes the engines
   already convert (`tb_common.labunit.ANALYTES`: creatinine, CRP, ESR, weight, height) take their factors from
   there, so the adapter's table and the engines never disagree. Units are compared by `labunit.key` after the
   spelling table `labvalue.UCUM`. HbA1c % and mmol/mol are an offset apart, not a factor: they never convert;
   enzyme units and international units stay apart. The table is checked against 36 textbook pairs and against
   the catalogue's JLAC10 factors.
3. **The table's job** is to check and to propose: `tools/mapping_check.py` lists every (lab code, row unit) pair,
   how it is read, and for a mismatch the factor the lookup could declare. A person accepts it; nothing converts
   silently.
4. **One presence reader**, `labvalue.presence`: NFKC, lower case, no spaces, then one table in Japanese, Chinese
   and English (陰性, 未檢出, (−), Non-reactive; 陽性, 檢出, (+), 2+, Reactive). Held or borderline words (判定保留,
   ±, 弱陽性, 灰區, equivocal) are read as unknown on purpose. A word with its sign in brackets reads when both
   agree (`陰性(−)`) and is unknown when they disagree. The site's own `answers` are read first; the table only
   adds. A result neither reads stays text, which the engines treat as unknown.
5. **`unit_defaults` are the lookup's units.** The shipped TW and JP mappings declare them per LOINC analyte, equal
   to the lab lookup's `ucum`, in the file itself (a `fhir_bulk` feed reads them without `extends`). mapping_check
   fails when a line contradicts the lookup.
6. **The synthetic SS-MIX2 site writes 陽性 and 陰性**, as a Japanese laboratory does. They read to the same
   LOINC answers as POS and NEG did: `python -m tools.goldens --check --profile ci` is IDENTICAL from both lake
   sources (23 goldens), so no golden is rewritten.

## Consequences

- A Japanese hepatitis B, IGRA or pregnancy result now settles a criterion. A held result never does.
- The SQL and CQL generators are unchanged (D-275 owns them). The lake's reading of a FHIR `valueString` from a
  `fhir_bulk` feed does not use the presence reader yet.
- Adding an analyte to the table is a reviewed change with its textbook pair in `tests/unit/test_lab_units_per_row.py`.
