# 8. Derived scores

A derived score is computed from other rows: eGFR (CKD-EPI 2021 or JSN 2009), BMI, DAS28, BASDAI, ASDAS, CDAI and
SDAI. Code: `libs/tb_common/derived.py` (formulas, units, same visit), `libs/tb_common/scores.py` (definitions),
`libs/tb_common/derived_store.py` (stored rows) (D-149, D-189, D-190).

**Definitions come from the catalogue.** Each score is a YAML file in `catalogue/scores/`: inputs, units, windows,
coefficients, edge cases and published worked examples. `python tools/gen_score_defs.py` writes them to
`libs/tb_common/score_defs.json`; the box reads only that file. A definition is named `<score_id>@<version>` (for
example `rheum.cdai@1`) and carries the sha256 of its YAML. A YAML that changed but kept its version is refused:
bump the version. The same-visit windows of CDAI, SDAI, DAS28-ESR and DAS28-CRP are read from the definitions.

**Units.** Every input is converted to the unit its formula expects (CRP mg/dL x 10 = mg/L; creatinine µmol/L /
88.4 = mg/dL). The CDAI and SDAI globals are on a 0-10 scale (LOINC 75844-1 and 75846-6); a 0-100 mm VAS recorded
under them is divided by 10, a 10 cm VAS is already 0-10, and a value outside 0-10 gives no value. SDAI takes the
CRP in mg/dL.

**No value is unknown.** A missing input, or a unit or scale that does not fit, gives no value and a reason
(`derived_missing_input:<input>`, `derived_unit:<input>`). Screening reads this as unknown, never as "no". A proposed
fact (read from a chart, not yet confirmed) never counts as an input; nor does a rejected or preliminary row. An
impossible value gives no value and `derived_unit:<input>` too: a negative CRP or ESR, a joint count outside 0-28, a
creatinine of 0 or less. An age of 0 or less gives `derived_missing_input:age`.

**Status in the lake.** The status rule needs the row's status. The lake's `observation` table has no status column
yet, so the `derive` batch records each lake row's status as `not_recorded`, and such a row counts. Proposed facts
still never reach a stored score: the lake keeps them out of `observation` by their basis tag. But an
entered-in-error or preliminary row from the hospital feed is not filtered out until the lake carries
`Observation.status`.

**Screening.** The SQL and CQL engines compute the score per patient at the index date, from one visit: the newest
anchor input in the window (the joint count; the creatinine for eGFR) and the other inputs near it. CDAI and SDAI are
in both engines and in the Python reference, and a test checks that all three give the published worked examples
(`tests/unit/test_derived_definitions.py`). A criterion names its score (`cdai`, `sdai`, `egfr_jsn`, ...).

**Stored rows.** The `derive` batch (`derived_store.run_batch`, one patient at a time with
`DerivedStore.recompute`) writes CDAI, SDAI, DAS28-ESR, DAS28-CRP and both eGFRs to schema `derived` of the trial
database, one row per patient, score and anchor row:

| Table | What it holds |
| --- | --- |
| `definition` | the definitions in use: version, sha256, the full text |
| `score_row` | value (or no value and the reason), unit, anchor date, definition version and sha, the site mapping version, and every input: source table, row id, date, value and unit as recorded, status, and the value and unit the formula used |
| `input_link` | one row per input ("derived from") |
| `conflict` | a documented score that does not match the computed one |

A row is written only when something it depends on changed: an input added, corrected, confirmed or deleted, a new
mapping version, or a new definition version. Otherwise the batch writes nothing. A new row supersedes the old one;
rows are never changed in place or deleted. An anchor deleted at the source retires its row. A definition that
changed under the same version stops the store from opening. One patient whose recompute fails is counted in the
batch report, and the batch goes on with the next patient.

**Documented scores.** A score written in a note (a proposed fact) or signed by a physician is compared with the
computed row within 7 days of it. When they differ by more than the score's tolerance (CDAI and SDAI 0.5, DAS28 0.2,
eGFR 5), a `derived_vs_documented` conflict opens. Neither value is overwritten. The score reads as unknown until a
person chooses `keep_derived`, `keep_documented` or `both_at_dates`. A documented score with no computed row near it
stands alone, as what it is. When a row is recomputed, its conflicts move to the new row and are checked again
against the stored documented value, even if the batch was not given the documented scores. A conflict that still
differs stays open. A person's decision stays, unless the new value differs from the value they decided on by more
than the tolerance; then the conflict opens again.

Not yet: screening still computes scores in its own SQL and CQL rather than reading the stored rows; an approved
ruleset does not pin definition versions; nothing schedules the `derive` batch and the console has no page for
derived conflicts; DAS28, BASDAI, ASDAS and MELD 3.0 still need clinician worked examples before approval; the SQL
and CQL engines do not yet carry the joint-count, CRP and ESR ranges. For the lake owner: the lake's `observation`
table should carry `Observation.status` so that the batch can leave out entered-in-error and preliminary rows.
