# r3core: IR 3.1 and the compiler on IR 3 (R3 items 1 to 3)

**Reader:** the people who build TrialBox.

Three changes, one pull request each, stacked: the IR 3.1.0 contract, the compiler reading IR 3, and the IR 3
constructs compiled in both engines. Verified on 2026-11-27 by the tests named below and the offline recompile; the
SQL against CQL equivalence of the new constructs on executed engines is not verified (it needs the FHIR store).

## 1. IR 3.1.0 (additive)

`libs/tb_contracts/criterion_ir.py`: `card_ref {card_id, card_version, params}` on the criterion, `on_hit`
(`exclude` | `review`) on atoms, `Window.unit` (`d` | `h`). `IR_VERSION` is 3.1.0; `ir_version` accepts 3.0.0 and
3.1.0, is 3.0.0 by default and from `upgrade_v1`, and must be 3.1.0 when a 3.1 construct is used.

- `card_ref` is in `_DROP_TOP`: provenance, outside the canonical hash.
- The hashed form carries the lowest version it needs and drops the written-out defaults (`on_hit: exclude`,
  `unit: d`), so a criterion that uses no 3.1 construct keeps its hash. Checked: the 129 committed criteria
  (8 rulesets, the open-data rulesets, the v3 fixtures) hash the same under the base and the new module.
- `downgrade_to_v1` refuses each 3.1 construct; the v4 schemas are regenerated.
- Tests: `tests/unit/test_criterion_ir_31.py`.

## 2. The compiler reads IR 3

Merged the earlier v3 SQL entry (#1531) with its tests. `semantics.lower()` is now shared by both generators: a v1
criterion is upgraded to IR 3 at load, each atom is lowered to the v1-shaped atom the templates compile, and its IR 3
atom rides beside it for the qualifiers a generator compiles itself. A qualifier no generator compiles raises
`CompileError`, so the criterion goes to a person.

- `tools.build_rulesets --check`: all 8 live rulesets equal to the compiler's output.
- `tests/unit/test_compiler_reads_v3.py`: each live ruleset's SQL and CQL from v1 and from IR 3 input equal the
  committed files byte for byte. The SQL against CQL replay (`tests/integration/test_ruleset_expected.py`) is
  therefore unchanged.

## 3. IR 3 constructs in SQL and CQL

| Construct | SQL | CQL |
| --- | --- | --- |
| `value.ref` | the OMOP row's own range (#1531), else the signed site table, else NULL with `no_reference_range` | the signed site table, else null |
| study anchors | `criterion_anchors` (#1531) | library parameters `ScreeningDate`, `RandomizationDate` |
| `value_if` | lowered to logic: `(c and x) or (not c and r) or (x and r)` | the same logic |
| `on_hit: review` | `(atom AND NULL)`: met goes to a person | `(atom) and (null as Boolean)` |
| medication route, dose, basis | OMOP `drug_exposure` (#1531) | refused (`CompileError`) |

The site table (`semantics.SiteRefRanges`) is signed (`signed.by`, `signed.at`) or refused, and is matched on code,
unit key and sex, a row for the patient's sex before the row for both. Hour windows stay refused in both engines.

- `tests/unit/test_compile_r3_constructs.py`: the SQL runs in DuckDB on synthetic rows (true, false and unknown per
  construct); the CQL is read as text. A library holding every construct, with and without a site table, translates
  with no error and no warning (the CQL translator, run by hand; not part of the tests).
- GZQO-EXC-13 in IR 3 (`docs/handover/cx-ir31/GZQO-EXC-13-v3.json`) compiles in both engines against 3 times the ULN.
  The shipped ruleset is not changed: see the question below.

## Findings

- R3CORE-01 (High): the lake carries no result reference range. `lake/flatten.py` keeps no range column and the OMOP
  load writes no `measurement.range_high`; the SQL reads the OMOP row (not in the night's connection, CXIR31-01) and
  the CQL does not read `Observation.referenceRange`, so both decide from the site table. A range column in the lake is
  the lake's change.
- R3CORE-02 (High): no signed site table exists and nothing passes one to `build_artifacts`. Until both exist every
  `value.ref` criterion is unknown with `no_reference_range`.
- R3CORE-03 (Medium): no caller supplies study anchor dates (neither `criterion_anchors` nor the CQL parameters); a
  per-patient parameter in the CQL evaluation is not verified.
- R3CORE-04 (Medium): medication route and dose stay SQL only. The SQL compares OMOP route concept ids and the
  quantity of one exposure; the IR documents route as SNOMED codes and FHIR carries a dose per administration, so a CQL
  twin would compare other codes and another quantity. The representation needs a ruling.
- R3CORE-05 (Medium): `no_reference_range` is not in `tb_common.labunit.TOKENS`, so `reason_of` reads it as a record
  reference; the night report would not name the reason.
- R3CORE-06 (Medium): the SQL against CQL equivalence of the new constructs on executed engines is not run.

## Question

GZQO-EXC-13 moving to IR 3 needs a ruling before it can ship. `tests/unit/test_criterion_ir_v3.py` asserts that every
ruleset IR file is v1 (`test_every_v1_criterion_upgrades_validates_and_round_trips`), and `libs/tb_common/ruleset.py`
loads rulesets as v1; with no signed site table the moved criterion is unknown for every patient. The golden would
also need the five evidence items of F17-B, two of which are not this job's to give (an independent recompute and
the owner's re-approval).
