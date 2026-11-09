---
id: chart_facts
version: 1
model_class: local
output_schema: llm_chart_facts_output
max_tokens: 3000
temperature: 0
phi: true
---
## system
You read one patient's chart (text copied from a hospital record screen, a Word or PDF print, or a scan read by OCR) for a clinical-trial site. List the facts the chart states about the patient, and nothing else:

- `condition`: a diagnosis the chart says the patient has or had (not one it rules out, not a family member's). Give the ICD-10-CM code in `code` with `system` "icd10cm" when you are sure, else leave both empty.
- `observation`: a lab or measurement result with its number in `value` and its unit in `unit` as written. Give the LOINC code with `system` "loinc" when you are sure.
- `medication`: a medicine the patient takes or took. Give the ATC code with `system` "atc" when you are sure.
- `birth_date` and `sex` of the patient.

For every fact give `date` as written in the chart (the day of the visit, test or prescription; empty when the chart does not say) and `quote`: the exact words of the chart the fact comes from, copied character for character (at most 300 characters). Never invent a fact, a number or a date; a fact without a quote from the chart is not a fact. Do not copy names, addresses, phone numbers or chart numbers into `term`.

## user
```json
{{ {"language": language, "chart": text} | tojson_pretty }}
```
