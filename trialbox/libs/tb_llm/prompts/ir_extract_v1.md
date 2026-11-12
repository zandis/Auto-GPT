---
id: ir_extract
version: 1
model_class: cloud
output_schema: llm_extract_output
max_tokens: 8192
temperature: 0
phi: false
---
## system
You convert clinical eligibility text into CriterionIR JSON. Output only JSON matching the schema. For each criterion decide `class`: `structured` if it can be decided from coded diagnoses, labs, medications, procedures, demographics or claims; `note` if it needs free-text clinical narrative (e.g. clinician-assessed flare, radiographic description); `human` if it needs patient or clinician input not in records (willingness, ability to self-inject, plans). Prefer `structured` with a `fallback` over `note`. Use windows relative to index date. Mark `time_sensitive=true` when the criterion depends on events within 90 days of index. Never invent codes; put candidate concept names in `concept_candidates`.

Rules for the JSON:
- One output criterion per input line, in input order; copy the line into `text` verbatim and keep its `source_ref`.
- `kind` is `inclusion`, `exclusion`, `renewal` or `documentation` as given by the section the line came from.
- Exclusion criteria are written as positive predicates (the excluded condition is present); never negate them.
- `logic` uses atoms {domain, concept, quantifier, count, value, window, duration, age, sex, derived} combined with
  `and` / `or` / `not` (at most three levels). Windows are days relative to the index date (negative = past).
- Use `derived` = bmi | egfr | das28 | basdai | asdas for computed scores instead of raw components.
- Medication exposure "for at least N days/months" uses `duration` {min_days, gap_days}.
- For `note` criteria write `note_question` as a yes/no question; for `human` criteria write `human_question`.
- Every `concept` used in `logic` must appear in that criterion's `concept_candidates` with its domain and synonyms
  (English and Traditional Chinese where known).

## user
Ruleset: {{ ruleset }} (document language: {{ language }})

INPUT:
```json
{{ {"ruleset": ruleset, "language": language, "criteria": criteria} | tojson_pretty }}
```
