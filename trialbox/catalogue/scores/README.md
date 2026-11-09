# Score definitions as data

One YAML file per derived score. Each file is the content of one `tb_score_definition` row plus its
`tb_score_component` rows (design 2026-11-09 §2.3). The box implements the small fixed set of `formula_kind`
values; a file only supplies inputs, coefficients, windows and edge cases. A model never writes a formula.

Fields:

- `score_id`: the `items.csv` id of the derived item.
- `formula_kind`: one of `weighted_sqrt_log`, `sum`, `mean_of_categories`, `power_product`, `linear`, `band_table`,
  `rule_table`, `ratio`, `conversion_table`.
- `inputs`: role, item id, unit the formula expects, whether required, and the time window in days relative to the
  anchor input (the joint count for DAS28, the creatinine for eGFR).
- `rounding`: how the published source rounds; stored values keep full precision, display uses the rounding.
- `edge_cases`: what the compute step does when a value is at or past a bound. A missing required input gives no row.
- `examples`: worked examples. Every expected output is copied from a published source named in `source`;
  `source_grade` is `primary` (the defining paper or body), `secondary` (a textbook, guideline table or trial
  protocol) or `calculator` (a public calculator page, cross-checked by hand by the person who wrote this file).
  No expected value in these files was computed by the author of the file. Where no published worked example was
  found, the file says so and lists only published thresholds; the owner or a clinician supplies the example before
  the definition is approved.
- `verified`: `yes` when formula, coefficients and examples were checked at the source on 2026-11-09; `partial` or
  `no` otherwise.
